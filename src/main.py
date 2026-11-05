import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google.genai import errors as genai_errors
from google.genai import types
from openai import OpenAIError
from pydantic import ValidationError

from src.clients.gemini_client import create_gemini_client
from src.clients.openai_client import create_openai_client
from src.errors import ConsultaInvalidaError, ContratoInvalidoError, ProveedoresNoDisponiblesError
from src.guardrails import check_input
from src.metrics import log_request
from src.schemas import LLMResponse, TicketResult

load_dotenv()  # carga las variables del .env en el entorno

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system-prompt-v1.yaml"

MODEL = "gpt-4o-mini"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")  # backup; configurable desde el .env
TEMPERATURE = 0  # clasificar pide respuestas estables, no creativas
MAX_TOKENS = 400  # tope de la respuesta para controlar costo
MAX_ATTEMPTS = 3  # intentos totales si la respuesta no cumple el contrato

# Structured Outputs de OpenAI: el modelo queda obligado a respetar el JSON Schema del contrato (no solo "ser JSON").
OPENAI_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "ticket_result", "strict": True, "schema": TicketResult.model_json_schema()},
}

EXIT_CONSULTA_INVALIDA = 1  # error del usuario: no tiene sentido reintentar
EXIT_FALLO_SERVICIO = 2  # error del servicio: proveedores caídos o contrato no cumplido

TICKETS = [
    "Hola, me cobraron dos veces la suscripción de este mes, necesito que me reintegren uno de los cargos.",
    "no me llega la factura de agosto, la necesito para mi contador urgente",
    "El dashboard de reportes me tira error 500 desde ayer, no puedo generar el cierre de caja.",
    "Se me cayó la integración con Mercado Pago, los pagos no se están sincronizando desde esta mañana.",
    "Quiero agregar un usuario nuevo a mi cuenta con permisos de solo lectura, ¿cómo lo hago?",
    "Necesito cambiar el email de administrador de la cuenta, el actual ya no existe en mi empresa.",
    "¿Tienen algún descuento para clientes que llevan más de 2 años con Nubbix?",
    "hola buenas, quería saber si tienen planes para empresas más grandes, somos 80 empleados",
]
TICKET = ["Hola, me cobraron dos veces la suscripción de este mes, necesito que me reintegren uno de los cargos."]

def load_system_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["system"]


def classify_with_openai(system_prompt: str, ticket: str) -> LLMResponse:
    client = create_openai_client()
    response = client.chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        response_format=OPENAI_RESPONSE_FORMAT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": ticket},
        ],
    )
    return LLMResponse(
        text=response.choices[0].message.content or "",
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
    )


def classify_with_gemini(system_prompt: str, ticket: str) -> LLMResponse:
    client = create_gemini_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=ticket,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=TEMPERATURE,
            max_output_tokens=MAX_TOKENS,
            response_mime_type="application/json",
            response_schema=TicketResult,
        ),
    )
    usage = response.usage_metadata
    return LLMResponse(
        text=response.text or "",  # text es None si Gemini bloquea la respuesta
        prompt_tokens=usage.prompt_token_count or 0,
        # los tokens de razonamiento (thoughts) se cobran como salida
        completion_tokens=(usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
    )


def call_and_log(provider: str, model: str, call, system_prompt: str, ticket: str) -> str:
    """Ejecuta la llamada al proveedor, mide la latencia, registra la métrica y devuelve el texto."""
    start = time.perf_counter()
    response = call(system_prompt, ticket)
    log_request(provider, model, response, time.perf_counter() - start)
    return response.text


def classify_ticket(system_prompt: str, ticket: str) -> tuple[str, str]:
    """Prueba OpenAI y, si falla (sin crédito, caída, clave inválida), usa Gemini. Devuelve (proveedor, texto)."""
    try:
        return "openai", call_and_log("openai", MODEL, classify_with_openai, system_prompt, ticket)
    except (OpenAIError, ValueError) as error:
        print(f"[aviso] OpenAI falló ({type(error).__name__}); usando Gemini", file=sys.stderr)

    try:
        return "gemini", call_and_log("gemini", GEMINI_MODEL, classify_with_gemini, system_prompt, ticket)
    except (genai_errors.APIError, ValueError) as error:
        raise ProveedoresNoDisponiblesError(f"Fallaron OpenAI y Gemini (Gemini: {type(error).__name__}).") from error


def parse_result(raw: str) -> TicketResult:
    """Convierte el texto del modelo en un TicketResult; lanza ValidationError si no cumple el contrato."""
    text = raw.strip()
    # Algunos modelos envuelven el JSON en ```json ... ```; se quitan esas vallas.
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return TicketResult.model_validate_json(text)


def classify_and_validate(system_prompt: str, ticket: str) -> tuple[str, TicketResult]:
    """Valida la entrada, pide la clasificación y la valida; reintenta hasta MAX_ATTEMPTS si el JSON es inválido."""
    ticket = check_input(ticket)  # antes de gastar una llamada al modelo
    for attempt in range(1, MAX_ATTEMPTS + 1):
        provider, raw = classify_ticket(system_prompt, ticket)
        try:
            return provider, parse_result(raw)
        except ValidationError as error:
            print(f"[aviso] intento {attempt}/{MAX_ATTEMPTS}: respuesta inválida ({error.error_count()} errores)", file=sys.stderr)
    raise ContratoInvalidoError(f"No se obtuvo una respuesta válida tras {MAX_ATTEMPTS} intentos.")


def main(args: list[str]) -> int:
    """Corre la CLI y devuelve el código de salida (0 = ok)."""
    # Con argumentos: usa ese texto como ticket. Sin argumentos: usa TICKET (1 solo, para gastar poco).
    # Para probar los 8 ejemplos, cambiar TICKET por TICKETS en la línea de abajo.
    tickets = [" ".join(args)] if args else TICKET

    system_prompt = load_system_prompt()

    try:
        for ticket in tickets:
            print(f"TICKET: {ticket}")
            provider, result = classify_and_validate(system_prompt, ticket)
            print(f"PROVEEDOR: {provider}")
            print(result.model_dump_json(indent=2))
            print("-" * 40)
    except ConsultaInvalidaError as error:
        print(f"[error] Consulta inválida: {error}", file=sys.stderr)
        return EXIT_CONSULTA_INVALIDA
    except (ContratoInvalidoError, ProveedoresNoDisponiblesError) as error:
        print(f"[error] {error}", file=sys.stderr)
        return EXIT_FALLO_SERVICIO
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
