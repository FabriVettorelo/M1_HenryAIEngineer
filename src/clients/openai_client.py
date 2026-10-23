import os

from openai import OpenAI


def create_openai_client() -> OpenAI:
    """Construye el cliente; no envía consultas al modelo."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        raise ValueError("Falta configurar la variable de entorno OPENAI_API_KEY.")

    return OpenAI(api_key=api_key)
