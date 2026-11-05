from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass
class LLMResponse:
    """Respuesta de un proveedor, sin importar cuál sea: texto y tokens consumidos."""

    text: str
    prompt_tokens: int
    completion_tokens: int


class TicketResult(BaseModel):
    """Contrato de salida de la CLI."""

    model_config = ConfigDict(extra="forbid")  # rechaza campos extra; también exigido por el modo strict de OpenAI

    answer: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)  # 0 = nada seguro, 1 = totalmente seguro
    category: Literal["billing", "technical", "account", "other"]
    actions: list[str]
