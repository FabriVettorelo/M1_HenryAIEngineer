import os

from openai import OpenAI


def create_openai_client() -> OpenAI:
    """Construye el cliente; no envía consultas al modelo."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        raise ValueError("Falta configurar la variable de entorno OPENAI_API_KEY.")

    # El SDK ya reintenta solo ante 429 (rate limit), 5xx y cortes de conexión, con espera creciente.
    return OpenAI(api_key=api_key, timeout=30.0, max_retries=2)
