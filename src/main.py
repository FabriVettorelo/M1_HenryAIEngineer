import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google.genai import types
from openai import OpenAIError

from src.clients.gemini_client import create_gemini_client
from src.clients.openai_client import create_openai_client

load_dotenv()  # carga las variables del .env en el entorno

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system-prompt-v1.yaml"

MODEL = "gpt-4o-mini"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")  # backup; configurable desde el .env
TEMPERATURE = 0  # clasificar pide respuestas estables, no creativas
MAX_TOKENS = 200  # tope de la respuesta para controlar costo

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


def classify_with_openai(system_prompt: str, ticket: str) -> str:
    client = create_openai_client()
    response = client.chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": ticket},
        ],
    )
    return response.choices[0].message.content


def classify_with_gemini(system_prompt: str, ticket: str) -> str:
    client = create_gemini_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=ticket,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=TEMPERATURE,
            max_output_tokens=MAX_TOKENS,
        ),
    )
    return response.text


def classify_ticket(system_prompt: str, ticket: str) -> tuple[str, str]:
    """Prueba OpenAI y, si falla (sin crédito, caída, clave inválida), usa Gemini. Devuelve (proveedor, texto)."""
    try:
        return "openai", classify_with_openai(system_prompt, ticket)
    except (OpenAIError, ValueError) as error:
        print(f"[aviso] OpenAI falló ({type(error).__name__}); usando Gemini", file=sys.stderr)
        return "gemini", classify_with_gemini(system_prompt, ticket)


if __name__ == "__main__":
    # Con argumentos: usa ese texto como ticket. Sin argumentos: usa TICKET (1 solo, para gastar poco).
    # Para probar los 8 ejemplos, cambiar TICKET por TICKETS en la línea de abajo.
    tickets = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else TICKET

    system_prompt = load_system_prompt()

    for ticket in tickets:
        print(f"TICKET: {ticket}")
        provider, answer = classify_ticket(system_prompt, ticket)
        print(f"PROVEEDOR: {provider}")
        print(answer)
        print("-" * 40)
