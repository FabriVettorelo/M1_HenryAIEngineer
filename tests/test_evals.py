"""Tests de los archivos de evals y del runner (sin API). Ejecutar: pytest -v"""
import json
from pathlib import Path

import pytest

from evals import runner
from src.errors import ContratoInvalidoError
from src.main import load_system_prompt
from src.schemas import TicketResult

EVALS_DIR = Path(runner.__file__).parent
CATEGORIAS = {"billing", "technical", "account", "other"}


def cargar(nombre: str) -> list[dict]:
    return runner.load_cases(EVALS_DIR / nombre)


# --- Dataset ------------------------------------------------------------------
def test_dataset_tiene_al_menos_30_casos_con_ids_unicos():
    casos = cargar("dataset.jsonl")
    assert len(casos) >= 30
    assert len({c["id"] for c in casos}) == len(casos)


def test_dataset_cubre_las_cuatro_categorias_y_solo_esas():
    categorias = [c["category"] for c in cargar("dataset.jsonl")]
    assert set(categorias) == CATEGORIAS
    assert all(categorias.count(cat) >= 5 for cat in CATEGORIAS)


def test_dataset_incluye_casos_ambiguos_y_ruidosos():
    tipos = {c["tipo"] for c in cargar("dataset.jsonl")}
    assert {"claro", "ambiguo", "ruidoso"} <= tipos


def test_dataset_tiene_splits_dev_y_holdout_con_las_cuatro_categorias():
    casos = cargar("dataset.jsonl")
    assert {c["split"] for c in casos} == set(runner.SPLITS)
    for split in runner.SPLITS:
        assert {c["category"] for c in casos if c["split"] == split} == CATEGORIAS


def test_los_ejemplos_few_shot_no_estan_en_ningun_split():
    prompt = load_system_prompt(EVALS_DIR.parent / "prompts" / "system-prompt-v2.yaml")
    assert all(c["ticket"] not in prompt for c in cargar("dataset.jsonl"))


def test_los_tickets_del_dataset_pasan_el_guardrail_de_entrada():
    from src.guardrails import check_input

    for caso in cargar("dataset.jsonl"):
        check_input(caso["ticket"])


def test_adversarial_tiene_10_prompts_documentados():
    casos = cargar("adversarial.jsonl")
    assert len(casos) == 10
    assert len({c["id"] for c in casos}) == 10
    assert all(c["ticket"] and c["esperado"] for c in casos)
    assert {"injection", "jailbreak", "extraccion_prompt"} <= {c["tipo"] for c in casos}  # lo que pide el bonus


# --- Runner -------------------------------------------------------------------
def resultado(categoria: str):
    return "openai", TicketResult(answer="x", confidence=0.9, category=categoria, actions=[])


def test_evaluate_case_acierto_y_fallo(monkeypatch):
    caso = {"id": "x1", "ticket": "hola", "category": "billing"}
    monkeypatch.setattr(runner, "classify_and_validate", lambda sp, t, p=None, guardrails=True: resultado("billing"))
    assert runner.evaluate_case("sp", caso)["ok"] is True
    monkeypatch.setattr(runner, "classify_and_validate", lambda sp, t, p=None, guardrails=True: resultado("other"))
    assert runner.evaluate_case("sp", caso)["ok"] is False


def test_un_caso_con_error_cuenta_como_incorrecto(monkeypatch):
    def falla(sp, t, p=None, guardrails=True):
        raise ContratoInvalidoError("agotado")

    monkeypatch.setattr(runner, "classify_and_validate", falla)
    fila = runner.evaluate_case("sp", {"id": "x1", "ticket": "hola", "category": "billing"})
    assert fila["ok"] is False and fila["error"] == "ContratoInvalidoError"


def test_summarize_calcula_score_global_y_por_categoria():
    filas = [
        {"esperado": "billing", "ok": True, "error": None},
        {"esperado": "billing", "ok": False, "error": None},
        {"esperado": "technical", "ok": True, "error": None},
        {"esperado": "other", "ok": False, "error": "ContratoInvalidoError"},
    ]
    resumen = runner.summarize(filas)
    assert resumen["global"] == (2, 4)
    assert resumen["por_categoria"]["billing"] == (1, 2)
    assert resumen["por_categoria"]["technical"] == (1, 1)
    assert resumen["por_categoria"]["account"] == (0, 0)
    assert resumen["por_categoria"]["other"] == (0, 1)
    assert resumen["errores"] == 1


def test_main_respeta_limit_y_muestra_el_reporte(monkeypatch, capsys):
    llamadas = []

    def falsa(sp, ticket, provider=None, guardrails=True):
        llamadas.append(provider)
        return resultado("billing")

    monkeypatch.setattr(runner, "classify_and_validate", falsa)
    runner.main(["--limit", "3", "--provider", "gemini"])
    assert llamadas == ["gemini"] * 3  # el flag llega hasta la llamada
    assert "Score global" in capsys.readouterr().out


def test_summarize_cuenta_que_proveedor_respondio():
    filas = [
        {"esperado": "billing", "ok": True, "error": None, "proveedor": "openai"},
        {"esperado": "billing", "ok": True, "error": None, "proveedor": "openai"},
        {"esperado": "other", "ok": True, "error": None, "proveedor": "gemini"},
        {"esperado": "other", "ok": False, "error": "ContratoInvalidoError", "proveedor": None},
    ]
    assert runner.summarize(filas)["proveedores"] == {"openai": 2, "gemini": 1}


# --- Prompts ------------------------------------------------------------------
def test_main_con_split_evalua_solo_esos_casos(monkeypatch):
    evaluados = []

    def falsa(sp, ticket, provider=None, guardrails=True):
        evaluados.append(ticket)
        return resultado("billing")

    monkeypatch.setattr(runner, "classify_and_validate", falsa)
    runner.main(["--split", "holdout"])
    esperados = [c["ticket"] for c in cargar("dataset.jsonl") if c["split"] == "holdout"]
    assert evaluados == esperados and len(esperados) == 20


# --- Métricas de la corrida y pausa ---------------------------------------------
def registrar(ruta, modelo, latencia, tokens, costo):
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(json.dumps({"model": modelo, "latency_s": latencia, "total_tokens": tokens, "cost_usd": costo}) + "\n")


def test_summarize_metrics_ignora_lo_anterior_y_agrupa_por_modelo(metricas_temporales):
    registrar(metricas_temporales, "viejo", 9.0, 999, 1.0)
    registrar(metricas_temporales, "gpt-4o-mini", 1.0, 100, 0.001)
    registrar(metricas_temporales, "gpt-4o-mini", 3.0, 300, 0.003)
    resumen = runner.summarize_metrics(runner.count_metric_lines() - 2)
    assert list(resumen) == ["gpt-4o-mini"]
    datos = resumen["gpt-4o-mini"]
    assert datos["llamadas"] == 2 and datos["latencia_media_s"] == 2.0 and datos["latencia_max_s"] == 3.0
    assert datos["tokens"] == 400 and datos["costo_usd"] == pytest.approx(0.004)


def test_summarize_metrics_sin_precio_devuelve_costo_none(metricas_temporales):
    registrar(metricas_temporales, "modelo-sin-precio", 1.0, 10, None)
    assert runner.summarize_metrics(0)["modelo-sin-precio"]["costo_usd"] is None


def test_summarize_metrics_sin_archivo(metricas_temporales):
    assert runner.count_metric_lines() == 0 and runner.summarize_metrics(0) == {}


def test_main_imprime_metricas_y_respeta_la_pausa(monkeypatch, capsys):
    esperas = []
    monkeypatch.setattr(runner.time, "sleep", esperas.append)
    monkeypatch.setattr(runner, "classify_and_validate", lambda *a, **k: resultado("billing"))
    runner.main(["--limit", "2", "--pausa", "5"])
    assert esperas == [5.0, 5.0]
    assert "Métricas de la corrida" in capsys.readouterr().out
