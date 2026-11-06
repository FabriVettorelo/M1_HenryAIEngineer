"""Fixtures compartidas. Los tests no llaman a ninguna API: simulan las funciones de los proveedores."""
import pytest

from src import guardrails, metrics

OK_JSON = '{"answer": "Hola", "confidence": 0.9, "category": "billing", "actions": ["Revisar el cobro"]}'


@pytest.fixture(autouse=True)
def metricas_temporales(tmp_path, monkeypatch):
    """Evita que los tests escriban en el data/metrics.jsonl real."""
    ruta = tmp_path / "metrics.jsonl"
    monkeypatch.setattr(metrics, "METRICS_PATH", ruta)
    return ruta


@pytest.fixture(autouse=True)
def logging_apagado():
    """El logger guarda estado global: cada test arranca con él apagado y lo deja apagado."""
    from src import logger

    logger.configure(enabled=False)
    yield
    logger.configure(enabled=False)


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """Los reintentos con espera no deben hacer dormir a los tests."""
    monkeypatch.setattr("src.main.time.sleep", lambda segundos: None)


@pytest.fixture(autouse=True)
def sin_moderacion_real(monkeypatch):
    """La moderación llama a OpenAI: en los tests se desactiva, y si algo intenta llegar a la API real, el test falla."""

    def api_real_prohibida():
        raise RuntimeError("un test intentó llamar a la API real de OpenAI")

    monkeypatch.setattr("src.main.moderate", lambda ticket: None)
    monkeypatch.setattr(guardrails, "create_openai_client", api_real_prohibida)
