"""Tests del contrato de salida, el parser, el guardrail de entrada y el prompt. Ejecutar: pytest -v"""
import pytest
import yaml
from pydantic import ValidationError

from src.errors import ConsultaInvalidaError
from src.guardrails import MAX_TICKET_CHARS, check_input
from src.main import PROMPT_PATH, parse_result
from src.schemas import TicketResult
from tests.conftest import OK_JSON

CATEGORIAS = ["billing", "technical", "account", "other"]


# --- Parser y esquema ---------------------------------------------------------
def test_json_valido():
    resultado = parse_result(OK_JSON)
    assert isinstance(resultado, TicketResult)
    assert resultado.category == "billing"


def test_json_envuelto_en_vallas_de_codigo():
    assert parse_result(f"```json\n{OK_JSON}\n```").category == "billing"


@pytest.mark.parametrize("categoria", CATEGORIAS)
def test_acepta_las_cuatro_categorias(categoria):
    assert parse_result(OK_JSON.replace("billing", categoria)).category == categoria


@pytest.mark.parametrize("salida", [
    OK_JSON.replace("billing", "facturacion"),  # categoría fuera de la lista
    OK_JSON.replace("0.9", "1.5"),  # confianza fuera de rango
    OK_JSON.replace("0.9", "-0.1"),
    OK_JSON.replace('"Hola"', '""'),  # respuesta vacía
    '{"answer": "x", "confidence": 0.5, "category": "other"}',  # falta actions
    OK_JSON[:-1] + ', "extra": 1}',  # campo extra
    "Hola, soy el modelo",  # no es JSON
    "",
])
def test_rechaza_salidas_que_no_cumplen_el_contrato(salida):
    with pytest.raises(ValidationError):
        parse_result(salida)


# --- Guardrail de entrada -----------------------------------------------------
def test_check_input_recorta_espacios():
    assert check_input("  hola  ") == "hola"


@pytest.mark.parametrize("ticket", ["", "   ", "\n\t"])
def test_check_input_rechaza_vacios(ticket):
    with pytest.raises(ConsultaInvalidaError):
        check_input(ticket)


def test_check_input_rechaza_tickets_enormes():
    check_input("a" * MAX_TICKET_CHARS)  # en el límite, pasa
    with pytest.raises(ConsultaInvalidaError):
        check_input("a" * (MAX_TICKET_CHARS + 1))


# --- Prompt -------------------------------------------------------------------
def test_el_prompt_yaml_menciona_las_categorias_y_el_contrato():
    with open(PROMPT_PATH, encoding="utf-8") as f:
        system = yaml.safe_load(f)["system"]
    assert all(c in system for c in CATEGORIAS)
    assert all(campo in system for campo in ["answer", "confidence", "category", "actions"])
