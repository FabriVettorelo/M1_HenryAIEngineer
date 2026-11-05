"""Tests de costo y métricas JSONL. Ejecutar: pytest -v"""
import json

import pytest

from src import main as m
from src import metrics
from src.schemas import LLMResponse


# --- Costo --------------------------------------------------------------------
def test_costo_gpt_4o_mini():
    # (1000 × 0.15 + 200 × 0.60) / 1M = 0.00027
    assert metrics.estimate_cost("gpt-4o-mini", 1000, 200) == pytest.approx(0.00027)


def test_costo_gemini():
    # (1000 × 0.30 + 200 × 2.50) / 1M = 0.0008
    assert metrics.estimate_cost("gemini-3.5-flash-lite", 1000, 200) == pytest.approx(0.0008)


def test_modelo_sin_precio_no_inventa_un_costo():
    assert metrics.estimate_cost("modelo-inventado", 1000, 200) is None


# --- JSONL --------------------------------------------------------------------
def llamada_falsa(system_prompt, ticket):
    return LLMResponse(text="ok", prompt_tokens=350, completion_tokens=90)


def test_call_and_log_devuelve_el_texto_y_escribe_una_linea(metricas_temporales):
    assert m.call_and_log("openai", "gpt-4o-mini", llamada_falsa, "sp", "t") == "ok"

    lineas = metricas_temporales.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    registro = json.loads(lineas[0])
    assert registro["provider"] == "openai"
    assert registro["prompt_tokens"] == 350
    assert registro["completion_tokens"] == 90
    assert registro["total_tokens"] == 440
    assert registro["latency_s"] >= 0
    assert registro["cost_usd"] == pytest.approx(metrics.estimate_cost("gpt-4o-mini", 350, 90))
    assert "timestamp" in registro


def test_las_metricas_son_append_only(metricas_temporales):
    for _ in range(3):
        m.call_and_log("gemini", "gemini-3.5-flash-lite", llamada_falsa, "sp", "t")
    assert len(metricas_temporales.read_text(encoding="utf-8").splitlines()) == 3


def test_una_llamada_fallida_no_registra_metricas(metricas_temporales):
    def llamada_rota(system_prompt, ticket):
        raise ValueError("falló")

    with pytest.raises(ValueError):
        m.call_and_log("openai", "gpt-4o-mini", llamada_rota, "sp", "t")
    assert not metricas_temporales.exists()
