# Instrucciones para trabajar en M1

## Contexto y objetivo

Proyecto Integrador del Módulo 1 de AI Engineering de Henry: automatizar el primer nivel de soporte de Nubbix mediante una CLI que clasifica consultas, propone respuestas y sugiere acciones para un agente humano. Consultar `README.md` para el resumen y los enlaces a la consigna.

## Forma de colaborar

- La interacción con el estudiante es **human in the loop**: el asistente propone y explica; el usuario revisa, da feedback y conserva la decisión sobre los cambios y los próximos pasos. Avanzar con su participación y respetar el alcance que autorice.
- Responder en español, explicar con ejemplos concretos y avanzar en pasos pequeños. Cuando ayude, relacionar Python con JavaScript.
- Priorizar la comprensión del estudiante: ante consultas de aprendizaje, explicar y orientar antes de reescribir su código. Implementar cuando lo pida explícitamente.
- Mantener funciones pequeñas y responsabilidades claras; evitar frameworks propios y abstracciones innecesarias.
- Distinguir requisitos oficiales, recomendaciones y decisiones locales. No inventar resultados, implementaciones ni exigencias de la consigna.
- Mantener el README sincronizado con el comportamiento real. Documentar el uso de IA, los prompts de asistencia relevantes y su influencia en las decisiones.

## Contrato y requisitos que se deben preservar

- CLI en `src/main.py` o equivalente; salida JSON validada con `answer`, `confidence`, `category`, `actions`.
- `category` admite únicamente `billing`, `technical`, `account`, `other`; `actions` es una lista de sugerencias para una persona, no acciones ejecutadas.
- Validar con Pydantic y definir reintentos acotados ante parsing/validación inválidos. Manejar errores transitorios y rate limits explícitamente.
- Al menos dos proveedores LLM configurables mediante una abstracción mínima, sin cambiar la lógica de negocio al alternarlos. (Deberia priorizar OPENAI y de fallback otro modelo, tambien fijarse de balancear las cargas y latencias)
- Al menos dos versiones de prompt en `prompts/*.yaml`, fuera del código, comparadas sobre el mismo dataset. Justificar la técnica elegida con resultados.
- Dataset propio de al menos 30 casos etiquetados en `evals/dataset.jsonl`, con cobertura de las cuatro categorías y entradas variadas/ambiguas.
- Runner de evals como script simple en `evals/runner.py`, ejecutable por comando, con score global y por categoría. No convertirlo en una suite de pytest ni en un framework de evals.
- Guardrail de entrada y guardrail de salida; contemplar moderación e intentos de prompt injection.
- Métricas append-only por request en `data/metrics.jsonl`: timestamp, tokens de prompt/completion/total, latencia en segundos y costo estimado en USD. Documentar cómo se calcula el costo.
- Usar JSONL para métricas; la guía indica no usar SQLite ni otra base de datos para este propósito.

## Seguridad y configuración

- Claves mediante variables de entorno; `.env.example` contiene solo nombres y valores ficticios.
- Nunca incluir secretos en código, documentación, ejemplos, logs o commits. No versionar `.env`, `.venv/` ni dependencias instaladas.
- Tratar el texto del ticket como entrada no confiable, separado de las instrucciones del sistema.
- No ejecutar acciones sugeridas por el modelo ni prometer operaciones reales de cuenta/facturación que el servicio no realiza.
- Documentar proveedor, modelo, temperature, límites de tokens y precios utilizados. No inventar precios ni mediciones.

## Desarrollo y verificación

1. Completar primero el flujo mínimo: consulta → proveedor → validación → JSON → métricas.
2. Agregar segundo proveedor, prompts alternativos, guardrails y evals.
3. Comparar resultados y documentar decisiones antes de sumar extras.
4. Verificar casos válidos, ambiguos, maliciosos, errores de API y agotamiento de reintentos según lo implementado.
5. Antes de entregar, ejecutar CLI y evals realmente, verificar una línea de métricas y comprobar instalación limpia. Informar límites o comprobaciones pendientes.

Los comandos de la CLI y de los evals están definidos (ver `README.md`). Antes de documentar un comando nuevo o cambiado, verificarlo contra la implementación. No consumir APIs pagas para una verificación sin que el usuario haya autorizado ese uso; los tests (`pytest`) no llaman a ninguna API.

## Estado actual del proyecto

Al 06/11/2026 el proyecto está implementado y documentado:

- **CLI** en `src/main.py`: OpenAI como proveedor principal (`gpt-4o-mini`) y Gemini como fallback (`gemini-3.5-flash-lite`); `--provider` fija uno sin fallback. Salida validada con Pydantic (`src/schemas.py`), reintentos acotados y manejo explícito de 429/5xx. Anthropic no se usa.
- **Prompts** en `prompts/`: `system-prompt-v1.yaml` (zero-shot, el elegido) y `system-prompt-v2.yaml` (few-shot, comparado y descartado). El ticket viaja separado de las instrucciones, entre `<consulta_del_cliente>`.
- **Guardrails** en `src/guardrails.py`: detector de prompt injection, moderación de OpenAI, validación de entrada y chequeo de salida.
- **Métricas** en `src/metrics.py` → `data/metrics.jsonl` (una línea por llamada al modelo). **Logging** estructurado sin PII en `src/logger.py` (`--verbose`; el contenido del ticket solo con `--log-contenido`, redactado).
- **Evals** en `evals/`: `dataset.jsonl` (52 casos, splits `dev` y `holdout`), `adversarial.jsonl` (12 ataques) y `runner.py`.
- **Tests** en `tests/` (pytest, sin API); los 2 de integración, que sí llaman a las APIs, se excluyen por defecto (`pytest -m integration`).
- **Documentación**: `README.md` describe instalación, comandos, resultados medidos, decisiones y limitaciones. `docs/RESULTADOS.md` guarda la evidencia detallada (comparaciones, adversarial, limitaciones). Mantener ambos sincronizados con cualquier cambio.
- Hecho como extra credit: comparativa de modelos (OpenAI contra Gemini).
