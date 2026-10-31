import os

from google import genai


def create_gemini_client() -> genai.Client:
    """Construye el cliente; no envía consultas al modelo."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key or not api_key.strip():
        raise ValueError("Falta configurar la variable de entorno GOOGLE_API_KEY.")

    return genai.Client(api_key=api_key)
