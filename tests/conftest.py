"""Fixtures compartidas. Los tests no llaman a ninguna API: simulan las funciones de los proveedores."""
import pytest

from src import metrics

OK_JSON = '{"answer": "Hola", "confidence": 0.9, "category": "billing", "actions": ["Revisar el cobro"]}'


@pytest.fixture(autouse=True)
def metricas_temporales(tmp_path, monkeypatch):
    """Evita que los tests escriban en el data/metrics.jsonl real."""
    ruta = tmp_path / "metrics.jsonl"
    monkeypatch.setattr(metrics, "METRICS_PATH", ruta)
    return ruta
