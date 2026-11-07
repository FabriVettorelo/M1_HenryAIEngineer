# M1 — Triage de soporte con LLMs para Nubbix

Proyecto Integrador del Módulo 1 de AI Engineering de Henry.

Nubbix es un SaaS para pymes de LATAM (≈12.000 clientes, ≈400 tickets diarios). Esta CLI recibe el texto de un ticket, lo **clasifica** (`billing`, `technical`, `account`, `other`), **propone una respuesta** y **sugiere acciones para un agente humano**. La salida es JSON validado con Pydantic. Las respuestas son borradores para una persona: el sistema nunca ejecuta acciones.

## Cómo funciona

```text
ticket ──► validar largo ──► guardrail de entrada ──► LLM (OpenAI → fallback Gemini) ──► validar JSON (Pydantic) ──► guardrail de salida ──► JSON
              │                 (injection, moderación)        │ reintentos 429/5xx            │ hasta 3 intentos
              └─ error 1                │ bloqueado: respuesta segura       └─ cada llamada se registra en data/metrics.jsonl
                                        └─ (category other, confidence 0, "Revisar manualmente")
```

- **El ticket va separado de las instrucciones.** El system prompt lleva las reglas y el ticket viaja en el mensaje de usuario entre `<consulta_del_cliente>…</consulta_del_cliente>`. Si el cliente escribe esas etiquetas, se eliminan.
- **Salida estructurada.** OpenAI recibe un `json_schema` estricto y Gemini un `response_json_schema`, generados desde el modelo Pydantic `TicketResult`. Además se valida de nuevo al recibir la respuesta.
- **Fallback.** OpenAI es el proveedor principal; si falla, se usa Gemini. Con `--provider` se fija uno y no hay fallback.

### Contrato de salida

| Campo | Tipo | Significado |
| --- | --- | --- |
| `answer` | texto no vacío | Respuesta propuesta al cliente (borrador). |
| `confidence` | número entre 0 y 1 | Confianza que **declara el modelo**. No está calibrada: sirve como señal orientativa, no como probabilidad real. Los guardrails devuelven 0.0. |
| `category` | `billing`, `technical`, `account` u `other` | Clasificación del ticket. |
| `actions` | lista de textos | Acciones sugeridas **para el agente humano**, no acciones ejecutadas. |

Cualquier campo extra o valor fuera de rango invalida la respuesta.

## Estructura del repositorio

```text
├── src/
│   ├── main.py            # CLI, selección de proveedor, reintentos y flujo completo
│   ├── schemas.py         # TicketResult (Pydantic) y LLMResponse
│   ├── guardrails.py      # guardrails de entrada y salida, wrap_ticket
│   ├── logger.py          # logging estructurado por pasos (JSON por stderr, sin PII)
│   ├── metrics.py         # precios, costo estimado y escritura de data/metrics.jsonl
│   ├── errors.py          # excepciones propias
│   └── clients/           # clientes de OpenAI y Gemini
├── prompts/               # system-prompt-v1.yaml, system-prompt-v2.yaml
├── evals/                 # dataset.jsonl, adversarial.jsonl y runner.py
├── tests/                 # pytest sin API (más 2 tests de integración opcionales)
├── docs/RESULTADOS.md     # evidencia: comparación de prompts y modelos, adversarial, limitaciones
├── data/metrics.jsonl     # una línea por llamada al modelo (append-only)
├── .env.example           # variables de entorno, sin claves reales
└── requirements.txt
```

## Instalación

Probado con Python 3.12 (instalación limpia y tests). El código usa sintaxis de Python 3.10 o superior.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Completar `.env` con las claves reales (nunca se suben a Git):

| Variable | Obligatoria | Uso |
| --- | --- | --- |
| `OPENAI_API_KEY` | Sí | Proveedor principal y moderación. La clave necesita los permisos *Chat completions* y *Moderations*. |
| `GOOGLE_API_KEY` | Para el fallback | Gemini. |
| `GEMINI_MODEL` | No | Modelo de Gemini; por defecto `gemini-3.5-flash-lite`. |

## Uso

### Clasificar un ticket

```bash
python -m src.main "Me cobraron dos veces la suscripción de este mes"
python -m src.main                                   # sin texto usa el ticket de ejemplo (TICKET en src/main.py)
python -m src.main "..." --provider gemini           # fuerza un proveedor, sin fallback
python -m src.main "..." --prompt prompts/system-prompt-v2.yaml
python -m src.main "..." --verbose                   # log JSON de cada paso por stderr
python -m src.main "..." --log-contenido             # igual, con una vista previa redactada del ticket
```

Imprime `TICKET`, `PROVEEDOR` (`openai`, `gemini`, `guardrail-entrada` o `guardrail-salida`) y el JSON. Salida real de una ejecución:

```text
$ python -m src.main "Me cobraron dos veces la suscripción de este mes"
TICKET: Me cobraron dos veces la suscripción de este mes
PROVEEDOR: openai
{
  "answer": "Lamentamos la confusión con los cobros. Te recomendamos que un agente humano revise tu cuenta para verificar los cargos y resolver esta situación.",
  "confidence": 0.9,
  "category": "billing",
  "actions": [
    "Revisar los cobros en la cuenta del cliente y verificar si hubo un error en la facturación."
  ]
}
----------------------------------------
```

Los avisos (fallbacks, reintentos, guardrails) salen por `stderr`.

**Códigos de salida:** `0` ok · `1` consulta inválida (vacía o de más de 2000 caracteres; no se reintenta) · `2` falla del servicio (proveedores caídos o respuesta que no cumple el contrato tras 3 intentos).

### Logging por pasos

Con `--verbose`, cada paso imprime una línea JSON por `stderr` (el resultado sigue limpio por `stdout`). Solo se imprime, no se guarda. Salida real de un ticket normal, con `--log-contenido` (el JSON del resultado, que va por `stdout`, se omite acá):

```text
$ python -m src.main "Me cobraron dos veces la suscripción de este mes" --verbose --log-contenido
{"timestamp": "2026-11-06T23:55:01.653Z", "request_id": "a153cb21", "step": "entrada", "ok": true, "chars": 48}
{"timestamp": "2026-11-06T23:55:01.654Z", "request_id": "a153cb21", "step": "injection", "flagged": false, "reason": "limpio"}
{"timestamp": "2026-11-06T23:55:17.556Z", "request_id": "a153cb21", "step": "moderacion", "content": "Me cobraron dos veces la suscripción de este mes", "flagged": false, "reason": "limpio"}
{"timestamp": "2026-11-06T23:55:51.612Z", "request_id": "a153cb21", "step": "llamada_modelo", "provider": "openai", "model": "gpt-4o-mini", "ok": true, "latency_s": 34.055, "prompt_tokens": 433, "completion_tokens": 99, "cost_usd": 0.00012435}
{"timestamp": "2026-11-06T23:55:51.612Z", "request_id": "a153cb21", "step": "validacion", "attempt": 1, "ok": true}
{"timestamp": "2026-11-06T23:55:51.612Z", "request_id": "a153cb21", "step": "salida", "flagged": false, "reason": "limpio"}
{"timestamp": "2026-11-06T23:55:51.612Z", "request_id": "a153cb21", "step": "resultado", "provider": "openai", "bloqueado": false, "category": "billing", "confidence": 0.9}
```

Un ticket que el detector bloquea termina antes: solo `entrada`, `injection` y `resultado`, sin llamar al modelo.

| Campo | Significado |
| --- | --- |
| `timestamp` | Cuándo ocurrió el paso (UTC). |
| `request_id` | Id único por ticket: une todos sus pasos (también reintentos y fallback). |
| `step` | `entrada`, `injection`, `moderacion`, `reintento`, `llamada_modelo`, `validacion`, `salida` o `resultado`. |
| `flagged` | Si el guardrail marcó el contenido (`injection`, `moderacion`, `salida`). |
| `reason` | Motivo o categorías que devolvió la moderación; `limpio` si no hubo marca. |
| `error` | Solo aparece si hubo un error (nombre del tipo o motivo, nunca el mensaje de la excepción). |
| `content` | **Solo con `--log-contenido`**, en el paso `moderacion`: vista previa de hasta 60 caracteres con emails, URLs y números largos reemplazados. |

Privacidad: por defecto no se registra el texto del ticket, la respuesta del modelo ni los mensajes de las excepciones, porque pueden repetir datos del cliente. La redacción de `content` no detecta nombres ni datos en texto libre: usar `--log-contenido` solo para depurar. El runner de evals no activa este log.

### Evals

Gastan tokens reales: una llamada por caso.

```bash
python -m evals.runner --provider openai                      # dataset completo (52 casos)
python -m evals.runner --provider gemini --pausa 5            # --pausa: segundos entre casos (plan gratuito)
python -m evals.runner --prompt prompts/system-prompt-v2.yaml --split holdout
python -m evals.runner --limit 3                              # prueba rápida
python -m evals.runner --adversarial --provider openai        # suite de ataques con guardrails
python -m evals.runner --adversarial --provider openai --sin-guardrails   # línea base
```

El reporte muestra el score global y por categoría, los casos incorrectos, qué proveedor respondió y, al final, las llamadas, latencia, tokens y costo estimado de esa corrida. Usar `--provider` para comparar prompts o modelos: sin él, un fallback mezclaría modelos en el mismo score.

### Tests

```bash
pytest                       # 143 tests, sin API ni costo
pytest -m integration        # 2 tests que llaman a las APIs reales (unos pocos tokens)
```

## Métricas y costo

Cada llamada al modelo agrega una línea a `data/metrics.jsonl` (formato JSONL, append-only). Es una línea por llamada, no por ticket: un reintento o un fallback generan líneas adicionales. La moderación no se registra.

```json
{"timestamp": "2026-11-06T20:24:25.772026+00:00", "provider": "gemini", "model": "gemini-3.5-flash-lite", "prompt_tokens": 362, "completion_tokens": 113, "total_tokens": 475, "latency_s": 2.322, "cost_usd": 0.0003911}
```

**Cálculo del costo:**

```text
costo_usd = (prompt_tokens × precio_entrada + completion_tokens × precio_salida) / 1.000.000
```

| Modelo | Entrada (USD / 1M tokens) | Salida (USD / 1M tokens) |
| --- | --- | --- |
| `gpt-4o-mini` | 0.15 | 0.60 |
| `gemini-3.5-flash-lite` | 0.30 | 2.50 |

Precios de las páginas oficiales de OpenAI y Google, consultados el 2026-11-04 (están en `src/metrics.py`). Verificación con la línea de arriba: (362 × 0.30 + 113 × 2.50) / 1.000.000 = 0.0003911. En Gemini los tokens de razonamiento se cobran como salida. Un modelo sin precio documentado registra `cost_usd: null`. El costo de Gemini es una **estimación a precio de lista**: con una clave del plan gratuito el costo real fue US$ 0.

## Parámetros

| Parámetro | Valor | Motivo |
| --- | --- | --- |
| Modelo principal | `gpt-4o-mini` | Barato y suficiente para clasificar. |
| Modelo de fallback | `gemini-3.5-flash-lite` | Segundo proveedor independiente. |
| `temperature` | 0 | Clasificar pide respuestas estables, no creativas. |
| `max_tokens` | 400 | Tope de la respuesta para controlar el costo. |
| Intentos por respuesta inválida | 3 | Límite explícito de reintentos de parsing/validación. |
| Reintentos ante 429/5xx | OpenAI: 2 (los hace su SDK) · Gemini: 2 con espera de 2 s y 4 s | El SDK de Gemini no reintenta solo. |
| Timeout de OpenAI | 30 s | Evita colgarse. |

**Errores 429.** El `insufficient_quota` de OpenAI (sin crédito) se distingue del límite de uso: no se reintenta porque esperar no lo arregla. Si el proveedor sigue fallando, se pasa al siguiente con un aviso que indica el motivo; si no queda ninguno, la CLI sale con código 2 explicando la causa.

## Resultados y decisiones

Resumen; la evidencia completa (tablas por categoría, comparación de prompts y modelos, suite adversarial y cómo reproducirlas) está en **[docs/RESULTADOS.md](docs/RESULTADOS.md)**.

| Tema | Resultado |
| --- | --- |
| Técnica de prompting | **Zero-shot (v1).** Empató con few-shot (v2): 49/52 los dos. La mejora de v2 en `dev` no se sostuvo en `holdout`, y v2 cuesta ≈54 % más por llamada. |
| Calidad (52 casos, `gpt-4o-mini`) | **51/52 (98.1%).** billing, technical y account 13/13; other 12/13. |
| Proveedores | **OpenAI principal, Gemini fallback.** Calidad similar (51/52 contra 50/52). |
| Latencia y costo (52 tickets) | OpenAI: 8.26 s de media, US$ 0.0059. Gemini: 2.30 s, US$ 0.0201 a precio de lista (US$ 0 reales con el plan gratuito). Una sola corrida por modelo. |
| Suite adversarial (12 ataques) | **11/12 sin guardrails; 12/12 con guardrails** (6 bloqueados antes de llamar al modelo). Sin guardrails falla solo `adv02`. |

## Seguridad

- **Entrada, antes de gastar una llamada:** validación de largo (máx. 2000 caracteres), detector local de prompt injection (patrones insensibles a mayúsculas y tildes) y moderación de OpenAI (`omni-moderation-latest`; si no está disponible avisa y deja pasar, *fail-open*).
- **Salida:** si la respuesta filtra fragmentos del system prompt, afirma haber ejecutado algo ("ya reembolsé…") o contiene claves o números de tarjeta, se reemplaza.
- **Ticket bloqueado:** no llega al modelo; se devuelve una respuesta segura (`category: other`, `confidence: 0.0`, acción "Revisar manualmente: motivo") para que lo atienda una persona.
- **Otras medidas:** el ticket va separado de las instrucciones y se trata como dato no confiable, la salida se fuerza al esquema y las claves viven solo en `.env`.

## Limitaciones principales

- Evidencia chica: 52 casos y 12 ataques, etiquetados por una sola persona; el `holdout` ya no es independiente para el prompt.
- El detector de injection es de patrones: atrapa 5 de los 12 ataques; el resto depende del prompt y del esquema.
- El guardrail de salida solo se probó con tests unitarios, y no se observó ningún 429 real.
- `confidence` no está calibrada (la declara el modelo) y las latencias salen de una sola corrida.

Lista completa en [docs/RESULTADOS.md](docs/RESULTADOS.md#5-limitaciones).

## Uso de IA en el desarrollo

El proyecto se construyó con **Claude (Claude Code)** como asistente, en pasos pequeños y con revisión humana: la IA proponía y escribía código, y yo ejecutaba, revisaba los resultados y decidía. Decisiones mías: usar solo OpenAI y Gemini (descarté Anthropic por costo), fijar `max_tokens` en 400, elegir v1 sobre v2, mantener OpenAI como principal, y el orden de las etapas.

Errores de la asistencia que se detectaron y corrigieron: una estimación de tokens de v2 muy baja (≈600 estimados, 937 reales); un error de Gemini al usar `response_schema` con `extra="forbid"`, que encontró el test de integración y se resolvió con `response_json_schema`; y una llamada accidental a la API real al probar un argumento vacío en PowerShell. Para evitar que se repita, los tests fallan si algo intenta llamar a la API real.

## Consigna oficial

Resumen original elaborado a partir de las secciones de **M1PI | Proyecto**; la consigna oficial es la referencia ante cambios o dudas:

- [Contexto y objetivos](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/HntBLeBul283)
- [Ejemplos ilustrativos de tickets](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/inYeljqsQhHy)
- [Entregables y requisitos](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/UfGW-mUVrYMR)
- [Evaluación](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/lPEgXrjlgiaF)
- [Guía de desarrollo](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/67O1eXIoIT9i)
