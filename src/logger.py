"""Logging estructurado sin PII: una línea JSON por paso, por stderr (stdout queda limpio para el resultado).

Está apagado por defecto (`configure(enabled=True)` lo activa; la CLI lo hace con --verbose). Solo se imprime, no se guarda.

Privacidad: nunca se registra la respuesta del modelo ni el mensaje de las excepciones (pueden repetir datos del cliente).
El texto del ticket (`content`) solo aparece si se pide expresamente, y siempre redactado y truncado.
"""
import json
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

PREVIEW_CHARS = 60

_enabled = False
_include_content = False
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://\S+")
_LONG_NUMBER = re.compile(r"(?:\d[ .\-]?){6,}")  # teléfonos, tarjetas, documentos, cuentas


def configure(enabled: bool, include_content: bool = False) -> None:
    global _enabled, _include_content
    _enabled = enabled
    _include_content = include_content


def start_request() -> str:
    """Genera el id que une todos los pasos de un mismo ticket."""
    request_id = uuid.uuid4().hex[:8]
    _request_id.set(request_id)
    return request_id


def redact(text: str) -> str:
    """Vista previa del texto sin emails, URLs ni números largos, y truncada.

    Es una mitigación, no una garantía: no detecta nombres ni datos escritos en texto libre.
    """
    for patron, reemplazo in ((_EMAIL, "[email]"), (_URL, "[url]"), (_LONG_NUMBER, "[número]")):
        text = patron.sub(reemplazo, text)
    text = " ".join(text.split())
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS].rstrip() + "…"


def log_event(step: str, content: str | None = None, **fields) -> None:
    """Imprime un evento JSON. Los campos con valor None se omiten (por ejemplo `error` cuando no hubo error)."""
    if not _enabled:
        return
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "request_id": _request_id.get(),
        "step": step,
    }
    if content is not None and _include_content:
        record["content"] = redact(content)
    record.update({clave: valor for clave, valor in fields.items() if valor is not None})
    print(json.dumps(record, ensure_ascii=False), file=sys.stderr)
