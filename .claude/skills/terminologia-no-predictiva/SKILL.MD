---
name: terminologia-no-predictiva
description: Verifica que cualquier texto visible al usuario en Sebasanálisis (copy de UI, mensajes de error, nombres de endpoints/tablas/campos, commits, documentación) no use lenguaje predictivo sobre resultados de juegos de azar. Úsala SIEMPRE antes de escribir o revisar cualquier string, componente de UI, respuesta de API, nombre de tabla/campo, o documento que describa una sugerencia estadística, una señal del motor, o el resultado de un giro — incluso si el usuario no lo pide explícitamente. Es una skill de cumplimiento de producto no negociable, aplica también a copy de marketing y a nombres de variables/commits.
---

# Terminología no-predictiva de Sebasanálisis

Sebasanálisis nunca predice el resultado de un giro independiente. Cada giro de ruleta es un evento estadísticamente independiente del anterior — esto es un hecho matemático, no una postura de marketing. Todo el vocabulario del producto debe reflejarlo.

## Regla de oro

Antes de aceptar cualquier texto (código, copy, commit, doc) que hable de sugerencias, señales, o resultados de juego, pregúntate: **¿esto implica que el sistema sabe o anticipa qué va a pasar en el próximo giro?** Si la respuesta es sí o es ambigua, reescríbelo.

## Tabla de reemplazos obligatorios

| Prohibido | Usar en su lugar |
|---|---|
| predicción / predice / predictivo | sugerencia estadística / señal |
| "el sistema predice X" | "el sistema detecta una desviación en X" |
| "precisión del modelo" | "tasa de coincidencia" (nunca implicar causalidad) |
| "confianza" (sentido de certeza futura) | "fuerza de la señal" (FUERTE / MEDIA / DÉBIL) |
| "va a salir" / "debería salir" | "ha salido con mayor/menor frecuencia que la esperada" |
| "acierto del modelo" | "coincidencia con el resultado observado" |
| nombres de tabla/campo tipo `predictions`, `predicted_value` | `statistical_suggestions`, `suggested_action`, `option_label` |

## Checklist antes de aprobar un texto o pieza de código

1. ¿Aparece la palabra "predic-" en cualquier forma (predicción, predictivo, predice)? → reescribir.
2. ¿El texto muestra una frecuencia observada SIN la probabilidad teórica constante al lado? → agregar ambas, nunca una sola (regla anti-falacia del jugador, `docs/ARQUITECTURA_Y_ESTADISTICA.md` §2). Aplica a la respuesta de la API y a la sección desplegable "¿Por qué recomienda esto?". La vista principal de la mesa no muestra frecuencias: ahí el protagonista es la recomendación (mercado, Signal Score, banda y monto). Donde se muestren, viajan en pareja.
3. ¿La tarjeta de recomendación conserva sus **dos líneas obligatorias**? Son estas (CLAUDE.md, "Disclaimer"):
   - bajo el score: _"81/100 es la fuerza del criterio interno, no la probabilidad de acertar."_ (en `frontend/components/mesa/RecommendationCard.tsx`);
   - al pie, fija, haya o no señal: _"Recomendación generada a partir del análisis estadístico de los resultados registrados. No es una predicción."_ (la manda la API, `RECOMMENDATION_DISCLAIMER` en `backend/app/api/v1/recommendations.py`, y la tarjeta la pinta desde `recommendation.disclaimer`).

   Si alguna falta, restáurala. **No agregues el banner fijo de §0** ("La ruleta no tiene memoria. Cada giro es independiente…"): se retiró de todas las pantallas, también del inicio, del login y del registro (decisión del usuario del 2026-10-14). El carácter estadístico y no predictivo del producto lo cubren los términos y condiciones. El hook `.claude/hooks/check_terminologia.py` vigila estas dos líneas.
4. ¿Un nombre de tabla, campo, función o endpoint usa vocabulario predictivo? Revisa contra la tabla de reemplazos y renómbralo antes de continuar, incluso si ya hay migraciones o código dependiente — es más barato corregirlo temprano.
5. ¿El copy de marketing/onboarding/landing promete resultados, ganancias, o "ventaja"? Cualquier frase que suene a promesa de resultado debe matizarse explícitamente con que ningún sistema cambia la ventaja matemática de la casa.

## Cuándo NO aplica

Al citar textualmente el documento de referencia `docs/reference/explicacion_analisis_estadistico_ruleta.md` (el boceto original) con fines de comparación o auditoría interna, puedes mantener su lenguaje original entre comillas, dejando explícito que es una cita del boceto y no el vocabulario del producto final.