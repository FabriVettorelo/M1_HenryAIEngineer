"""Test de humo contra las APIs reales: 1 llamada por proveedor, ticket corto.

No corre por defecto. Ejecutar: python -m pytest -m integration -v
Verifica que la integración funcione (esquema aceptado, tokens informados), no que la categoría sea la correcta: eso lo miden los evals.
"""
import os

import pytest

from src import main as m
from src.metrics import estimate_cost
from src.schemas import LLMResponse

pytestmark = pytest.mark.integration

TICKET = "me cobraron dos veces la suscripción"

# Se llama a cada función directo (no a classify_ticket) para que el fallback no tape un fallo del proveedor.
PROVEEDORES = [
    pytest.param("OPENAI_API_KEY", m.classify_with_openai, m.MODEL, id="openai"),
    pytest.param("GOOGLE_API_KEY", m.classify_with_gemini, m.GEMINI_MODEL, id="gemini"),
]


@pytest.mark.parametrize("variable_clave,clasificar,modelo", PROVEEDORES)
def test_el_proveedor_responde_con_el_contrato_y_los_tokens(variable_clave, clasificar, modelo):
    if not os.getenv(variable_clave):
        pytest.skip(f"falta {variable_clave}")

    respuesta = clasificar(m.load_system_prompt(), TICKET)

    assert isinstance(respuesta, LLMResponse)
    assert respuesta.prompt_tokens > 0 and respuesta.completion_tokens > 0
    m.parse_result(respuesta.text)  # lanza ValidationError si no cumple el contrato
    assert estimate_cost(modelo, respuesta.prompt_tokens, respuesta.completion_tokens) is not None
