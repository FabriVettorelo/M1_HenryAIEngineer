"""Tests del flujo: fallback entre proveedores, reintentos y códigos de salida. Sin API. Ejecutar: pytest -v"""
import openai
import pytest
from google.genai import errors as genai_errors

from src import main as m
from src.errors import ContratoInvalidoError, ProveedoresNoDisponiblesError
from src.schemas import LLMResponse
from tests.conftest import OK_JSON


def respuesta(texto: str) -> LLMResponse:
    return LLMResponse(text=texto, prompt_tokens=100, completion_tokens=50)


def openai_falla(*args):
    raise openai.OpenAIError("sin crédito")


def gemini_falla(*args):
    raise genai_errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})


# --- Fallback entre proveedores -----------------------------------------------
def test_usa_openai_si_responde(monkeypatch):
    monkeypatch.setattr(m, "classify_with_openai", lambda *a: respuesta(OK_JSON))
    monkeypatch.setattr(m, "classify_with_gemini", lambda *a: pytest.fail("no debía llamar a Gemini"))
    assert m.classify_ticket("sp", "hola")[0] == "openai"


@pytest.mark.parametrize("error", [openai.OpenAIError("caído"), ValueError("falta OPENAI_API_KEY")])
def test_cae_a_gemini_si_openai_falla(monkeypatch, error):
    def openai_roto(*args):
        raise error

    monkeypatch.setattr(m, "classify_with_openai", openai_roto)
    monkeypatch.setattr(m, "classify_with_gemini", lambda *a: respuesta(OK_JSON))
    assert m.classify_ticket("sp", "hola")[0] == "gemini"


def test_ambos_proveedores_caidos(monkeypatch):
    monkeypatch.setattr(m, "classify_with_openai", openai_falla)
    monkeypatch.setattr(m, "classify_with_gemini", gemini_falla)
    with pytest.raises(ProveedoresNoDisponiblesError):
        m.classify_ticket("sp", "hola")


# --- Reintentos acotados ------------------------------------------------------
def test_reintenta_si_el_json_es_invalido_y_se_recupera(monkeypatch):
    salidas = iter(["basura", OK_JSON])
    monkeypatch.setattr(m, "classify_with_openai", lambda *a: respuesta(next(salidas)))
    provider, resultado = m.classify_and_validate("sp", "hola")
    assert provider == "openai" and resultado.category == "billing"


def test_agota_los_reintentos(monkeypatch):
    llamadas = []

    def siempre_invalida(*args):
        llamadas.append(1)
        return respuesta("no es json")

    monkeypatch.setattr(m, "classify_with_openai", siempre_invalida)
    with pytest.raises(ContratoInvalidoError):
        m.classify_and_validate("sp", "hola")
    assert len(llamadas) == m.MAX_ATTEMPTS


def test_ticket_invalido_no_llama_al_modelo(monkeypatch):
    monkeypatch.setattr(m, "classify_with_openai", lambda *a: pytest.fail("se llamó al modelo"))
    monkeypatch.setattr(m, "classify_with_gemini", lambda *a: pytest.fail("se llamó al modelo"))
    with pytest.raises(m.ConsultaInvalidaError):
        m.classify_and_validate("sp", "   ")


# --- Códigos de salida de la CLI ----------------------------------------------
def test_cli_exito_imprime_el_json_validado(monkeypatch, capsys):
    monkeypatch.setattr(m, "classify_with_openai", lambda *a: respuesta(OK_JSON))
    assert m.main(["me cobraron dos veces"]) == 0
    salida = capsys.readouterr().out
    assert "PROVEEDOR: openai" in salida and '"category": "billing"' in salida


def test_cli_ticket_vacio_sale_con_1(monkeypatch):
    monkeypatch.setattr(m, "classify_with_openai", lambda *a: pytest.fail("se llamó al modelo"))
    assert m.main([" "]) == m.EXIT_CONSULTA_INVALIDA == 1


def test_cli_proveedores_caidos_sale_con_2(monkeypatch):
    monkeypatch.setattr(m, "classify_with_openai", openai_falla)
    monkeypatch.setattr(m, "classify_with_gemini", gemini_falla)
    assert m.main(["hola"]) == m.EXIT_FALLO_SERVICIO == 2


def test_cli_contrato_invalido_sale_con_2(monkeypatch):
    monkeypatch.setattr(m, "classify_with_openai", lambda *a: respuesta("no es json"))
    assert m.main(["hola"]) == m.EXIT_FALLO_SERVICIO
