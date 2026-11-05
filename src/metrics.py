import json
from datetime import datetime, timezone
from pathlib import Path

from src.schemas import LLMResponse

METRICS_PATH = Path(__file__).resolve().parent.parent / "data" / "metrics.jsonl"

# USD por 1M de tokens: (entrada, salida). Fuente: páginas oficiales de precios de OpenAI y Google, consultadas el 2026-11-04.
# En Gemini los tokens de razonamiento se cobran al precio de salida.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Costo estimado en USD, o None si no hay precio documentado para el modelo."""
    if model not in PRICES:
        return None
    input_price, output_price = PRICES[model]
    return round((prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000, 8)


def log_request(provider: str, model: str, response: LLMResponse, latency_s: float) -> None:
    """Agrega una línea al archivo JSONL (append-only) con las métricas de una llamada al modelo."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "total_tokens": response.prompt_tokens + response.completion_tokens,
        "latency_s": round(latency_s, 3),
        "cost_usd": estimate_cost(model, response.prompt_tokens, response.completion_tokens),
    }
    METRICS_PATH.parent.mkdir(exist_ok=True)
    with open(METRICS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
