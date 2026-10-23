# M1 — Triage de soporte con LLMs para Nubbix

Proyecto Integrador del Módulo 1 de AI Engineering de Henry.

> Estado al 21/10/2026: estructura inicial en `src/`, con el borrador en `src/main.py` y una función para construir el cliente OpenAI en `src/clients/openai_client.py`. La CLI de triage, los prompts YAML y las evaluaciones todavía no están implementados.

## Problema y objetivo

Nubbix es un SaaS para pymes de LATAM con 12.000 clientes y aproximadamente 400 tickets diarios. El 60 % de las consultas son repetitivas y el tiempo de primera respuesta llegó a 9 horas.

El objetivo es construir un servicio independiente que reciba texto libre, clasifique la consulta, proponga una respuesta y sugiera acciones al agente humano, con calidad medible, costos controlados y protección frente a usos maliciosos.

## Contrato de salida

La CLI debe devolver JSON validado con estos cuatro campos:

| Campo | Propósito |
| --- | --- |
| `answer` | Respuesta propuesta a la consulta. |
| `confidence` | Confianza del resultado. Tipo, escala y validación a definir y documentar. |
| `category` | Uno de `billing`, `technical`, `account`, `other`. |
| `actions` | Lista de acciones sugeridas para el agente humano. |

Validar con Pydantic y reintentar automáticamente cuando la respuesta no se pueda parsear o no respete el contrato. Los reintentos deben tener un límite explícito.

Las categorías abarcan facturación (cobros/facturas), problemas técnicos (errores/integraciones), gestión de cuenta (usuarios/permisos/cambio de email) y otros (consultas comerciales, por ejemplo). Los tickets ilustrativos de Henry son referencias de tono; construir el dataset propio es parte del proyecto.

## Entregables obligatorios

| Entregable | Ubicación esperada | Mínimo requerido |
| --- | --- | --- |
| CLI | `src/main.py` o equivalente | Consulta por línea de comandos, JSON validado y retry ante parsing inválido. |
| Cliente LLM | Dentro de `src/` | Al menos dos proveedores configurables mediante una abstracción común. |
| Prompts | `prompts/*.yaml` | Al menos dos versiones, fuera del código, comparadas con evals. |
| Dataset | `evals/dataset.jsonl` | Al menos 30 casos etiquetados, con cobertura de las cuatro categorías. |
| Runner | `evals/runner.py` | Script simple ejecutable por comando; score global y por categoría. |
| Métricas | `data/metrics.jsonl` | Una línea por request, append-only: timestamp, tokens prompt/completion/total, latencia (s), costo estimado (USD). |
| Guardrails | Dentro de `src/` | Al menos uno de entrada y uno de salida; moderación y mitigación de injection. |
| Configuración | `.env.example`, `requirements.txt` | Variables documentadas sin claves reales y dependencias declaradas. |
| Documentación | `README.md` | Setup, uso con comando/respuesta, técnica elegida, resultados de evals y decisiones técnicas. |

El servicio debe controlar errores, consumo y latencia. El cálculo del costo debe poder reproducirse con los precios y tokens documentados.

## Estructura prevista

Ya existen `src/`, `.env.example` y los documentos. `prompts/`, `evals/` y `data/` son parte de la estructura prevista, todavía pendientes.

```text
M1/
├── AGENTS.md
├── README.md
├── requirements.txt
├── .env.example
├── src/
│   ├── __init__.py
│   ├── main.py
│   └── clients/
│       ├── __init__.py
│       └── openai_client.py
├── prompts/
│   ├── v1.yaml
│   └── v2.yaml
├── evals/
│   ├── dataset.jsonl
│   ├── runner.py
│   └── adversarial.jsonl  # bonus
└── data/
    └── metrics.jsonl
```

## Preparación y ejecución

Desde la raíz del proyecto, para preparar el entorno Python:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Ya existe un entorno local `.venv/`; se puede activar directamente. La instalación de dependencias no fue verificada durante la preparación de esta documentación.

Para ejecutar el borrador desde la raíz:

```bash
python -m src.main
```

Por ahora imprime `Hola mundo`. Se conservó el contenido del antiguo `main.py` de la raíz en `src/main.py`.

`create_openai_client()` lee `OPENAI_API_KEY` del entorno y devuelve una instancia de `OpenAI`. Si falta la clave, genera un `ValueError` claro. Construir el cliente no envía solicitudes; aún no está conectado al flujo de `main.py`. `.env.example` es una referencia: no se carga automáticamente. El modelo se elegirá al agregar la primera consulta.

Esta separación inicial se preparó con asistencia de IA: el punto de entrada y el cliente tienen responsabilidades distintas. Quedan pendientes la interfaz común y el segundo proveedor.

Pendiente al implementar:

- Elegir los dos proveedores y modelos; documentar las variables requeridas en `.env.example` y cómo cargarlas en el entorno.
- Definir y verificar el comando real de la CLI y mostrar una respuesta JSON obtenida en una ejecución.
- Definir y verificar el comando del runner de evals.
- Documentar selección de proveedor, versión de prompt y parámetros configurables.

Nunca subir claves reales, `.env`, `.venv/` ni dependencias instaladas al repositorio.

## Plan de desarrollo recomendado

1. Definir el esquema Pydantic y resolver una consulta con un proveedor y un prompt.
2. Completar la CLI con validación, reintentos acotados y métricas JSONL.
3. Incorporar el segundo proveedor sin cambiar la lógica de negocio.
4. Crear el dataset etiquetado y comparar al menos dos versiones de prompt YAML.
5. Agregar y verificar guardrails de entrada y salida, entradas ambiguas y errores de API.
6. Elegir la técnica con evidencia, completar el README y verificar una ejecución limpia.
7. Abordar extras después de completar el flujo principal.

Separar cliente LLM, validación, guardrails y métricas en funciones o módulos simples. La guía recomienda JSONL sin base de datos y un runner de evals sin pytest ni framework propio.

## Context engineering y resultados

La técnica final todavía no está elegida. Comparar alternativas (por ejemplo, zero-shot y few-shot), versionar cada prompt en su propio YAML y conservar evidencia de qué mejoró o falló. La selección debe estar respaldada por el dataset, no por intuición.

Tabla para completar con ejecuciones reales:

| Prompt | Proveedor / modelo | N de casos | Score global | billing | technical | account | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v1 — pendiente | — | — | — | — | — | — | — |
| v2 — pendiente | — | — | — | — | — | — | — |

Definir la métrica de score, sus criterios y el tratamiento de errores. Documentar también costo y latencia observados, parámetros elegidos, limitaciones y motivos de selección de los proveedores. No hay resultados medidos todavía.

## Seguridad, bonus y extras

El mínimo incluye protección de entrada y salida, credenciales por entorno y validación del contrato. Documentar un caso adversarial con la detección, la decisión del sistema y su motivo.

El **bonus adversarial** pide 10 prompts maliciosos en `evals/adversarial.jsonl`, cubriendo injection, jailbreak y extracción del system prompt, con mitigaciones y efecto medido.

La rúbrica menciona **al menos un extra credit** dentro de la categoría de repositorio/README/extras: FastAPI, caché con hash MD5, LLM-as-judge en runtime o comparativa de modelos. La guía los presenta como opcionales y recomienda priorizar el MVP; esta diferencia queda registrada para tenerla en cuenta al preparar la entrega.

## Evaluación y checklist de entrega

La aprobación requiere **70/100**; de **81 a 100** supera lo esperado. Se evalúan funcionalidad y contrato JSON, dataset y evals, context engineering, seguridad, observabilidad y calidad del repositorio/documentación/extras. Los niveles son Excelente, Satisfactorio e Insuficiente; no se publican ponderaciones en la sección consultada.

- [ ] CLI incluida y versionada, con dos proveedores configurables.
- [ ] Ejecución real que produzca JSON válido y una línea de métricas.
- [ ] Dos prompts YAML comparados y selección justificada con resultados.
- [ ] Dataset de al menos 30 casos y runner ejecutado; reporte global y por categoría en este README.
- [ ] Guardrails de entrada y salida comprobados.
- [ ] Variables documentadas; sin secretos ni archivos locales en Git.
- [ ] Setup, comandos y ejemplos coinciden con el código y funcionan desde una instalación limpia.
- [ ] Decisiones y limitaciones documentadas, incluido el uso de IA y su influencia en el desarrollo.
- [ ] Repositorio público, autocontenido y enlace listo para entregar.
- [ ] Revisar extra credit y bonus adversarial según el alcance elegido.

## Fuentes

Resumen elaborado a partir de las cinco secciones de **M1PI | Proyecto**, consultadas el 21/10/2026. La consigna oficial es la referencia ante cambios o dudas:

- [Contexto y objetivos](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/HntBLeBul283)
- [Ejemplos ilustrativos de tickets](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/inYeljqsQhHy)
- [Entregables y requisitos](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/UfGW-mUVrYMR)
- [Evaluación](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/lPEgXrjlgiaF)
- [Guía de desarrollo](https://lp.soyhenry.com/share/lesson/W9H_JasyuOLs/s/67O1eXIoIT9i)
