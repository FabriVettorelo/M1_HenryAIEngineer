from src.errors import ConsultaInvalidaError

MAX_TICKET_CHARS = 2000  # un ticket real es corto; un texto enorme es abuso o error y cuesta tokens


def check_input(ticket: str) -> str:
    """Guardrail de entrada: devuelve el ticket sin espacios sobrantes o lanza ConsultaInvalidaError."""
    ticket = ticket.strip()
    if not ticket:
        raise ConsultaInvalidaError("El ticket está vacío.")
    if len(ticket) > MAX_TICKET_CHARS:
        raise ConsultaInvalidaError(f"El ticket supera el máximo de {MAX_TICKET_CHARS} caracteres.")
    return ticket
