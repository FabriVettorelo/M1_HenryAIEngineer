class ConsultaInvalidaError(Exception):
    """El ticket no es válido (vacío o demasiado largo). Error del usuario: no se reintenta."""


class ContratoInvalidoError(Exception):
    """El modelo no devolvió un JSON que cumpla el contrato tras agotar los reintentos."""


class ProveedoresNoDisponiblesError(Exception):
    """Fallaron todos los proveedores LLM (OpenAI y Gemini)."""
