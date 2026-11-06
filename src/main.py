import argparse
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google.genai import errors as genai_errors
from google.genai import types
from openai import InternalServerError, OpenAIError, RateLimitError
from pydantic import ValidationError

from src.clients.gemini_client import create_gemini_client
from src.clients.openai_client import create_openai_client
from src.errors import ConsultaInvalidaError, ContratoInvalidoError, ProveedoresNoDisponiblesError
from src.guardrails import check_input, check_output, detect_injection, moderate, safe_result, wrap_ticket
from src.logger import configure as configure_logging
from src.logger import log_event, start_request
from src.metrics import estimate_cost, log_request
from src.schemas import LLMResponse, TicketResult

load_dotenv()  # carga las variables del .env en el entorno

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system-prompt-v1.yaml"

MODEL = "gpt-4o-mini"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")  # backup; configurable desde el .env
TEMPERATURE = 0  # clasificar pide respuestas estables, no creativas
MAX_TOKENS = 400  # tope de la respuesta para controlar costo
MAX_ATTEMPTS = 3  # intentos totales si la respuesta no cumple el contrato
PROVIDER_ORDER = ["openai", "gemini"]  # prioridad por defecto: OpenAI y, si falla, Gemini
# Reintentos propios ante 429/5xx. OpenAI = 0 porque su SDK ya reintenta solo (max_retries=2); el de Gemini no.
RETRIES_BY_PROVIDER = {"openai": 0, "gemini": 2}
RETRY_BASE_WAIT_S = 2.0  # espera antes del primer reintento; se duplica en cada uno (2 s, 4 s)
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}

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

def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    with open(path, encoding="utf-8") as f:
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
            {"role": "user", "content": wrap_ticket(ticket)},
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
        contents=wrap_ticket(ticket),
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=TEMPERATURE,
            max_output_tokens=MAX_TOKENS,
            response_mime_type="application/json",
            response_json_schema=TicketResult.model_json_schema(),
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
    latency = time.perf_counter() - start
    log_request(provider, model, response, latency)
    log_event(
        "llamada_modelo", provider=provider, model=model, ok=True, latency_s=round(latency, 3),
        prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
        cost_usd=estimate_cost(model, response.prompt_tokens, response.completion_tokens),
    )
    return response.text


def get_provider(name: str) -> tuple[str, object, tuple]:
    """Devuelve (modelo, función, errores que justifican pasar al siguiente) del proveedor.
    Se arma en cada llamada para que siempre use las funciones actuales del módulo."""
    return {
        "openai": (MODEL, classify_with_openai, (OpenAIError, ValueError)),
        "gemini": (GEMINI_MODEL, classify_with_gemini, (genai_errors.APIError, ValueError)),
    }[name]


def is_rate_limit(error: Exception) -> bool:
    """429: se superó el límite de uso del proveedor."""
    return isinstance(error, RateLimitError) or (isinstance(error, genai_errors.APIError) and error.code == 429)


def is_transient(error: Exception) -> bool:
    """Error que puede resolverse esperando un poco: límite de uso (429) o falla del servidor (5xx)."""
    if isinstance(error, RateLimitError):
        return error.code != "insufficient_quota"  # sin crédito no se arregla esperando
    if isinstance(error, InternalServerError):
        return True
    return isinstance(error, genai_errors.APIError) and error.code in TRANSIENT_HTTP_CODES


def describe_error(error: Exception) -> str:
    """Motivo legible del fallo, para los avisos y el mensaje final."""
    if isinstance(error, RateLimitError) and error.code == "insufficient_quota":
        return "sin crédito o cuota agotada"
    if is_rate_limit(error):
        return "límite de uso (429)"
    if is_transient(error):
        return "error temporal del servicio"
    return type(error).__name__


def call_with_retries(name: str, model: str, call, system_prompt: str, ticket: str) -> str:
    """Llama al proveedor y reintenta con espera creciente ante errores temporales (429/5xx), hasta RETRIES_BY_PROVIDER."""
    max_retries = RETRIES_BY_PROVIDER.get(name, 0)
    for attempt in range(max_retries + 1):
        try:
            return call_and_log(name, model, call, system_prompt, ticket)
        except (OpenAIError, genai_errors.APIError) as error:
            if attempt == max_retries or not is_transient(error):
                raise
            wait = RETRY_BASE_WAIT_S * 2**attempt
            log_event("reintento", provider=name, attempt=attempt + 1, wait_s=wait, error=describe_error(error))
            print(f"[aviso] {name}: {describe_error(error)}; reintento {attempt + 1}/{max_retries} en {wait:g} s", file=sys.stderr)
            time.sleep(wait)


def classify_ticket(system_prompt: str, ticket: str, provider: str | None = None) -> tuple[str, str]:
    """Clasifica con el proveedor indicado, o con OpenAI y, si falla, Gemini (fallback). Devuelve (proveedor, texto)."""
    order = [provider] if provider else PROVIDER_ORDER
    last_error = None
    for position, name in enumerate(order):
        model, call, recoverable_errors = get_provider(name)
        try:
            return name, call_with_retries(name, model, call, system_prompt, ticket)
        except recoverable_errors as error:
            last_error = error
            log_event("llamada_modelo", provider=name, model=model, ok=False, error=describe_error(error))
            if position + 1 < len(order):
                print(f"[aviso] {name} falló ({describe_error(error)}); usando {order[position + 1]}", file=sys.stderr)
    raise ProveedoresNoDisponiblesError(f"Falló {' y '.join(order)} (último error: {describe_error(last_error)}).") from last_error


def parse_result(raw: str) -> TicketResult:
    """Convierte el texto del modelo en un TicketResult; lanza ValidationError si no cumple el contrato."""
    text = raw.strip()
    # Algunos modelos envuelven el JSON en ```json ... ```; se quitan esas vallas.
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return TicketResult.model_validate_json(text)


def classify_and_validate(
    system_prompt: str, ticket: str, provider: str | None = None, guardrails: bool = True
) -> tuple[str, TicketResult]:
    """Valida la entrada, pide la clasificación y la valida; reintenta hasta MAX_ATTEMPTS si el JSON es inválido.

    Con guardrails=True, un ticket sospechoso no llega al modelo y una respuesta insegura se reemplaza por una
    respuesta segura; en ambos casos el proveedor devuelto es 'guardrail-entrada' o 'guardrail-salida'."""
    start_request()  # un id por ticket para seguirlo en los logs
    try:
        ticket = check_input(ticket)  # antes de gastar una llamada al modelo
    except ConsultaInvalidaError as error:
        log_event("entrada", ok=False, error=str(error))
        raise
    log_event("entrada", ok=True, chars=len(ticket))

    if guardrails:
        reason = detect_injection(ticket)
        log_event("injection", flagged=reason is not None, reason=reason or "limpio")
        reason = reason or moderate(ticket)  # la moderación registra su propio evento
        if reason:
            print(f"[aviso] guardrail de entrada: {reason}", file=sys.stderr)
            log_event("resultado", provider="guardrail-entrada", bloqueado=True, category="other")
            return "guardrail-entrada", safe_result(reason)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            used_provider, raw = classify_ticket(system_prompt, ticket, provider)
        except ProveedoresNoDisponiblesError as error:
            log_event("resultado", ok=False, error=str(error))
            raise
        try:
            result = parse_result(raw)
        except ValidationError as error:
            print(f"[aviso] intento {attempt}/{MAX_ATTEMPTS}: respuesta inválida ({error.error_count()} errores)", file=sys.stderr)
            log_event("validacion", attempt=attempt, ok=False, error=f"{error.error_count()} errores de validación")
            continue
        log_event("validacion", attempt=attempt, ok=True)
        reason = check_output(result) if guardrails else None
        if guardrails:
            log_event("salida", flagged=reason is not None, reason=reason or "limpio")
        if reason:
            print(f"[aviso] guardrail de salida: {reason}", file=sys.stderr)
            log_event("resultado", provider="guardrail-salida", bloqueado=True, category="other")
            return "guardrail-salida", safe_result(reason)
        log_event("resultado", provider=used_provider, bloqueado=False, category=result.category, confidence=result.confidence)
        return used_provider, result
    log_event("resultado", ok=False, error=f"respuesta inválida tras {MAX_ATTEMPTS} intentos")
    raise ContratoInvalidoError(f"No se obtuvo una respuesta válida tras {MAX_ATTEMPTS} intentos.")


def main(args: list[str]) -> int:
    """Corre la CLI y devuelve el código de salida (0 = ok)."""
    parser = argparse.ArgumentParser(description="Clasifica un ticket de soporte de Nubbix.")
    parser.add_argument("ticket", nargs="*", help="texto del ticket; sin texto usa el ticket de ejemplo (TICKET)")
    parser.add_argument("--provider", choices=PROVIDER_ORDER, help="fuerza un proveedor (sin fallback); por defecto openai con fallback a gemini")
    parser.add_argument("--prompt", type=Path, default=PROMPT_PATH, help="YAML con el system prompt a usar")
    parser.add_argument("--verbose", action="store_true", help="imprime por stderr un log JSON por cada paso (sin contenido del ticket)")
    parser.add_argument("--log-contenido", action="store_true", help="incluye en el log una vista previa del ticket, redactada y truncada (implica --verbose)")
    options = parser.parse_args(args)
    configure_logging(enabled=options.verbose or options.log_contenido, include_content=options.log_contenido)

    # Para probar los 8 ejemplos, cambiar TICKET por TICKETS en la línea de abajo.
    tickets = [" ".join(options.ticket)] if options.ticket else TICKET

    system_prompt = load_system_prompt(options.prompt)

    try:
        for ticket in tickets:
            print(f"TICKET: {ticket}")
            provider, result = classify_and_validate(system_prompt, ticket, options.provider)
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
