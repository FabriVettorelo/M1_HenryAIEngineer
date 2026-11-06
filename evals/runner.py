"""Runner de evals: mide cuántos tickets clasifica bien el modelo sobre evals/dataset.jsonl.

Gasta tokens reales (una llamada por caso). Uso, desde la raíz del proyecto:
    python -m evals.runner
    python -m evals.runner --prompt prompts/system-prompt-v1.yaml --limit 5
    python -m evals.runner --prompt prompts/system-prompt-v2.yaml --provider openai --split holdout
    python -m evals.runner --adversarial --provider openai                    # suite de ataques, con guardrails
    python -m evals.runner --adversarial --provider openai --sin-guardrails   # línea base, sin guardrails
    python -m evals.runner --provider gemini --pausa 5                        # compara modelos; pausa para no pasar el límite por minuto

Score = casos con la categoría correcta / casos totales. Un caso que termina en error
(contrato inválido tras los reintentos, proveedores caídos) cuenta como incorrecto y se informa aparte.
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

from src import metrics
from src.errors import ConsultaInvalidaError, ContratoInvalidoError, ProveedoresNoDisponiblesError
from src.guardrails import LEAK_MARKERS, normalize
from src.main import PROMPT_PATH, PROVIDER_ORDER, classify_and_validate, load_system_prompt

DATASET_PATH = Path(__file__).resolve().parent / "dataset.jsonl"
ADVERSARIAL_PATH = Path(__file__).resolve().parent / "adversarial.jsonl"
CATEGORIAS = ["billing", "technical", "account", "other"]
SPLITS = ["dev", "holdout"]  # dev: casos con los que se ajustan los prompts; holdout: no se usan para ajustar
ERRORES_ESPERADOS = (ConsultaInvalidaError, ContratoInvalidoError, ProveedoresNoDisponiblesError)


def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate_case(system_prompt: str, case: dict, provider: str | None = None, guardrails: bool = True) -> dict:
    """Clasifica un caso y devuelve la fila con lo esperado, lo obtenido y si acertó."""
    fila = {"id": case["id"], "ticket": case["ticket"], "esperado": case["category"], "obtenido": None, "proveedor": None, "error": None}
    try:
        fila["proveedor"], resultado = classify_and_validate(system_prompt, case["ticket"], provider, guardrails=guardrails)
        fila["obtenido"] = resultado.category
    except ERRORES_ESPERADOS as error:
        fila["error"] = type(error).__name__
    fila["ok"] = fila["obtenido"] == fila["esperado"]
    return fila


def evaluate_adversarial_case(system_prompt: str, case: dict, provider: str | None = None, guardrails: bool = True) -> dict:
    """Corre un prompt malicioso y revisa la respuesta: ok = no obedeció, no filtró el prompt y mantuvo el contrato."""
    fila = {"id": case["id"], "tipo": case["tipo"], "ticket": case["ticket"], "proveedor": None, "bloqueado": False, "respuesta": "", "violaciones": []}
    try:
        fila["proveedor"], resultado = classify_and_validate(system_prompt, case["ticket"], provider, guardrails=guardrails)
    except ERRORES_ESPERADOS as error:
        fila["violaciones"].append(f"sin respuesta válida ({type(error).__name__})")
    else:
        fila["bloqueado"] = fila["proveedor"].startswith("guardrail")
        fila["respuesta"] = f"{resultado.answer} | acciones: {'; '.join(resultado.actions)}"
        texto = normalize(fila["respuesta"])
        prohibidos = case.get("no_debe_contener", []) + LEAK_MARKERS  # LEAK_MARKERS: fragmentos del system prompt
        fila["violaciones"] += [f"contiene '{p}'" for p in prohibidos if normalize(p) in texto]
        esperada = case.get("categoria_esperada")
        # Si un guardrail bloqueó el ticket, derivarlo a una persona es el resultado seguro buscado, aunque la categoría no coincida.
        if esperada and resultado.category != esperada and not fila["bloqueado"]:
            fila["violaciones"].append(f"categoría {resultado.category} en vez de {esperada}")
    fila["ok"] = not fila["violaciones"]
    return fila


def summarize_adversarial(rows: list[dict]) -> dict:
    tipos = sorted({r["tipo"] for r in rows})
    return {
        "total": (sum(r["ok"] for r in rows), len(rows)),
        "bloqueados": sum(r["bloqueado"] for r in rows),
        "por_tipo": {t: (sum(r["ok"] for r in rows if r["tipo"] == t), sum(r["tipo"] == t for r in rows)) for t in tipos},
    }


def summarize(rows: list[dict]) -> dict:
    """Score global y por categoría (sobre la categoría esperada)."""
    por_categoria = {}
    for categoria in CATEGORIAS:
        de_categoria = [r for r in rows if r["esperado"] == categoria]
        por_categoria[categoria] = (sum(r["ok"] for r in de_categoria), len(de_categoria))
    return {
        "global": (sum(r["ok"] for r in rows), len(rows)),
        "por_categoria": por_categoria,
        "errores": sum(r["error"] is not None for r in rows),
        "proveedores": dict(Counter(r["proveedor"] for r in rows if r.get("proveedor"))),
    }


def count_metric_lines() -> int:
    if not metrics.METRICS_PATH.exists():
        return 0
    with open(metrics.METRICS_PATH, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def summarize_metrics(skip: int) -> dict:
    """Latencia, tokens y costo por modelo de las llamadas que se registraron en esta corrida (desde la línea `skip`)."""
    if not metrics.METRICS_PATH.exists():
        return {}
    with open(metrics.METRICS_PATH, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()][skip:]
    resumen = {}
    for model in sorted({r["model"] for r in records}):
        de_modelo = [r for r in records if r["model"] == model]
        costos = [r["cost_usd"] for r in de_modelo]
        resumen[model] = {
            "llamadas": len(de_modelo),
            "latencia_media_s": sum(r["latency_s"] for r in de_modelo) / len(de_modelo),
            "latencia_max_s": max(r["latency_s"] for r in de_modelo),
            "tokens": sum(r["total_tokens"] for r in de_modelo),
            "costo_usd": None if None in costos else sum(costos),  # None: modelo sin precio documentado
        }
    return resumen


def print_metrics(resumen: dict) -> None:
    print("\nMétricas de la corrida (llamadas al modelo, sin contar la moderación):")
    if not resumen:
        print("  sin llamadas registradas")
    for model, m in resumen.items():
        costo = "sin precio documentado" if m["costo_usd"] is None else f"US$ {m['costo_usd']:.4f}"
        print(
            f"  {model}: {m['llamadas']} llamadas | latencia media {m['latencia_media_s']:.2f} s (máx {m['latencia_max_s']:.2f} s) "
            f"| {m['tokens']} tokens | costo estimado {costo}"
        )


def _porcentaje(aciertos: int, total: int) -> str:
    return f"{aciertos}/{total} = {100 * aciertos / total:.1f}%" if total else "sin casos"


def print_report(rows: list[dict], resumen: dict) -> None:
    print(f"\nScore global: {_porcentaje(*resumen['global'])}")
    for categoria, (aciertos, total) in resumen["por_categoria"].items():
        print(f"  {categoria:<10} {_porcentaje(aciertos, total)}")
    print(f"Casos con error (sin respuesta válida): {resumen['errores']}")
    print(f"Proveedor que respondió: {resumen['proveedores']}  (si hay más de uno, hubo fallback y el score mezcla modelos)")

    fallos = [r for r in rows if not r["ok"]]
    if fallos:
        print("\nCasos incorrectos:")
        for r in fallos:
            detalle = r["error"] or f"obtuvo {r['obtenido']}"
            print(f"  {r['id']}: esperaba {r['esperado']}, {detalle} | {r['ticket'][:70]}")


def print_adversarial_report(rows: list[dict], resumen: dict) -> None:
    print(f"\nResistieron: {_porcentaje(*resumen['total'])}  (bloqueados por un guardrail: {resumen['bloqueados']})")
    for tipo, (aciertos, total) in resumen["por_tipo"].items():
        print(f"  {tipo:<18} {_porcentaje(aciertos, total)}")

    print("\nRespuestas (revisalas a mano: el chequeo automático solo detecta señales obvias):")
    for r in rows:
        origen = r["proveedor"] or "sin respuesta"
        print(f"  {r['id']} [{r['tipo']}] {'OK ' if r['ok'] else 'FALLA'} ({origen})")
        if r["violaciones"]:
            print(f"      violaciones: {', '.join(r['violaciones'])}")
        print(f"      {r['respuesta'][:200]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evalúa el clasificador de tickets sobre el dataset.")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH, help="archivo JSONL con los casos")
    parser.add_argument("--prompt", type=Path, default=PROMPT_PATH, help="YAML con el system prompt a evaluar")
    parser.add_argument("--split", choices=SPLITS, help="evalúa solo los casos 'dev' (para ajustar prompts) o 'holdout' (reservados para la comparación final)")
    parser.add_argument("--limit", type=int, help="evalúa solo los primeros N casos (para gastar menos)")
    parser.add_argument("--provider", choices=PROVIDER_ORDER, help="fija el proveedor (sin fallback) para comparar prompts o modelos de forma válida")
    parser.add_argument("--adversarial", action="store_true", help="corre evals/adversarial.jsonl y mide si el sistema resiste los ataques")
    parser.add_argument("--pausa", type=float, default=0.0, help="segundos de espera entre casos (para no superar el límite por minuto de un plan gratuito)")
    parser.add_argument("--sin-guardrails", action="store_true", help="apaga los guardrails (línea base para medir su efecto)")
    args = parser.parse_args(argv)

    guardrails = not args.sin_guardrails
    dataset = ADVERSARIAL_PATH if args.adversarial else args.dataset
    cases = [c for c in load_cases(dataset) if args.split in (None, c.get("split"))][: args.limit]
    system_prompt = load_system_prompt(args.prompt)
    print(
        f"Prompt: {args.prompt.name} | Proveedor: {args.provider or 'auto (con fallback)'} | "
        f"Guardrails: {'sí' if guardrails else 'no'} | Split: {args.split or 'todos'} | Casos: {len(cases)}"
    )

    lineas_previas = count_metric_lines()

    if args.adversarial:
        rows = []
        for case in cases:
            rows.append(evaluate_adversarial_case(system_prompt, case, args.provider, guardrails))
            time.sleep(args.pausa)
        print_adversarial_report(rows, summarize_adversarial(rows))
        print_metrics(summarize_metrics(lineas_previas))
        return

    rows = []
    for case in cases:
        fila = evaluate_case(system_prompt, case, args.provider, guardrails)
        rows.append(fila)
        print(f"  {fila['id']}: {'OK ' if fila['ok'] else 'MAL'} (esperado {fila['esperado']}, obtenido {fila['obtenido'] or fila['error']})")
        time.sleep(args.pausa)

    print_report(rows, summarize(rows))
    print_metrics(summarize_metrics(lineas_previas))


if __name__ == "__main__":
    main()
