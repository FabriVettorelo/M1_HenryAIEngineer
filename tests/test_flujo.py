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


# --- Proveedor forzado --------------------------------------------------------
def test_proveedor_forzado_gemini_no_llama_a_openai(monkeypatch):
    monkeypatch.setattr(m, "classify_with_openai", lambda *a: pytest.fail("no debía llamar a OpenAI"))
    monkeypatch.setattr(m, "classify_with_gemini", lambda *a: respuesta(OK_JSON))
    assert m.classify_ticket("sp", "hola", provider="gemini")[0] == "gemini"


def test_proveedor_forzado_no_tiene_fallback(monkeypatch):
    monkeypatch.setattr(m, "classify_with_openai", openai_falla)
    monkeypatch.setattr(m, "classify_with_gemini", lambda *a: pytest.fail("no debía hacer fallback"))
    with pytest.raises(ProveedoresNoDisponiblesError):
        m.classify_ticket("sp", "hola", provider="openai")


def test_cli_flag_provider_se_respeta(monkeypatch, capsys):
    monkeypatch.setattr(m, "classify_with_openai", lambda *a: pytest.fail("no debía llamar a OpenAI"))
    monkeypatch.setattr(m, "classify_with_gemini", lambda *a: respuesta(OK_JSON))
    assert m.main(["--provider", "gemini", "me cobraron dos veces"]) == 0
    assert "PROVEEDOR: gemini" in capsys.readouterr().out


def test_cli_flag_prompt_usa_el_yaml_indicado(monkeypatch):
    recibidos = []

    def openai_espia(system_prompt, ticket):
        recibidos.append(system_prompt)
        return respuesta(OK_JSON)

    monkeypatch.setattr(m, "classify_with_openai", openai_espia)
    ruta_v2 = m.PROMPT_PATH.parent / "system-prompt-v2.yaml"
    assert m.main(["--prompt", str(ruta_v2), "hola"]) == 0
    assert recibidos == [m.load_system_prompt(ruta_v2)]


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


# --- Errores 429 y temporales: reintento con espera y fallback ------------------
def error_openai(codigo: str | None, estado: int = 429):
    import httpx

    respuesta_http = httpx.Response(estado, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    clase = openai.RateLimitError if estado == 429 else openai.InternalServerError
    return clase("error", response=respuesta_http, body={"code": codigo})


def error_gemini(codigo: int):
    clase = genai_errors.ServerError if codigo >= 500 else genai_errors.ClientError
    return clase(codigo, {"error": {"code": codigo, "status": "X"}})


def gemini_que_falla_y_luego_responde(fallos: int, error):
    llamadas = []

    def llamar(*args):
        llamadas.append(1)
        if len(llamadas) <= fallos:
            raise error
        return respuesta(OK_JSON)

    return llamar, llamadas


@pytest.mark.parametrize("codigo", [429, 503])
def test_gemini_reintenta_ante_429_y_5xx_y_se_recupera(monkeypatch, codigo):
    llamar, llamadas = gemini_que_falla_y_luego_responde(2, error_gemini(codigo))
    monkeypatch.setattr(m, "classify_with_gemini", llamar)
    assert m.classify_ticket("sp", "hola", provider="gemini")[0] == "gemini"
    assert len(llamadas) == 3  # 1 intento + 2 reintentos


def test_la_espera_entre_reintentos_crece(monkeypatch):
    esperas = []
    monkeypatch.setattr("src.main.time.sleep", esperas.append)
    llamar, _ = gemini_que_falla_y_luego_responde(2, error_gemini(429))
    monkeypatch.setattr(m, "classify_with_gemini", llamar)
    m.classify_ticket("sp", "hola", provider="gemini")
    assert esperas == [m.RETRY_BASE_WAIT_S, m.RETRY_BASE_WAIT_S * 2]


def test_los_reintentos_estan_acotados_y_el_error_final_explica_el_motivo(monkeypatch):
    llamar, llamadas = gemini_que_falla_y_luego_responde(99, error_gemini(429))
    monkeypatch.setattr(m, "classify_with_gemini", llamar)
    with pytest.raises(ProveedoresNoDisponiblesError, match="límite de uso"):
        m.classify_ticket("sp", "hola", provider="gemini")
    assert len(llamadas) == 3


def test_un_error_no_temporal_no_se_reintenta(monkeypatch):
    llamar, llamadas = gemini_que_falla_y_luego_responde(99, error_gemini(400))
    monkeypatch.setattr(m, "classify_with_gemini", llamar)
    with pytest.raises(ProveedoresNoDisponiblesError):
        m.classify_ticket("sp", "hola", provider="gemini")
    assert len(llamadas) == 1


def test_openai_con_429_pasa_a_gemini_sin_reintento_propio(monkeypatch, capsys):
    llamadas = []

    def openai_limitado(*args):
        llamadas.append(1)
        raise error_openai("rate_limit_exceeded")

    monkeypatch.setattr(m, "classify_with_openai", openai_limitado)
    monkeypatch.setattr(m, "classify_with_gemini", lambda *a: respuesta(OK_JSON))
    assert m.classify_ticket("sp", "hola")[0] == "gemini"
    assert len(llamadas) == 1  # el SDK de OpenAI ya reintentó antes de lanzar el error
    assert "límite de uso (429)" in capsys.readouterr().err


def test_openai_sin_credito_se_distingue_del_limite_de_uso(monkeypatch):
    def sin_credito(*args):
        raise error_openai("insufficient_quota")

    monkeypatch.setattr(m, "classify_with_openai", sin_credito)
    with pytest.raises(ProveedoresNoDisponiblesError, match="sin crédito"):
        m.classify_ticket("sp", "hola", provider="openai")


@pytest.mark.parametrize("error, esperado", [
    (error_openai("rate_limit_exceeded"), True),
    (error_openai("insufficient_quota"), True),  # es un 429, aunque no sea temporal (eso lo decide is_transient)
    (error_openai(None, estado=500), False),
    (error_gemini(429), True),
    (error_gemini(400), False),
    (ValueError("x"), False),
])
def test_is_rate_limit(error, esperado):
    assert m.is_rate_limit(error) is esperado


@pytest.mark.parametrize("error, esperado", [
    (error_openai("rate_limit_exceeded"), True),
    (error_openai("insufficient_quota"), False),
    (error_openai(None, estado=500), True),
    (error_gemini(503), True),
    (error_gemini(400), False),
    (openai.OpenAIError("x"), False),
])
def test_is_transient(error, esperado):
    assert m.is_transient(error) is esperado
