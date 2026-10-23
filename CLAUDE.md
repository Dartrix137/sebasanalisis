# CLAUDE.md — Sebasanálisis

Este archivo guía a Claude Code en este repositorio. Léelo completo antes de escribir código, y vuelve a él ante cualquier duda de alcance o de lenguaje del producto.

Está organizado por tema, no por fecha: cada sección dice la regla **vigente**. La historia de cómo se llegó a ella (qué se construyó, en qué orden, qué decisiones cambiaron) vive en `docs/HOJA_DE_RUTA.md`.

## Qué es este proyecto

Plataforma fullstack por suscripción con un **motor de recomendación estadística** para juegos de casino. El usuario registra a mano los números de una mesa de ruleta europea o americana y, después de cada giro, la pantalla le dice **qué apostar en el siguiente giro** o **NO APOSTAR**, con un Signal Score 0-100, su banda y lo que pide cada gestión de banca. **El producto sale solo con la ruleta** (decisión del 2026-10-14). Cada juego que venga después tendrá su propio motor, escrito en código como el de la ruleta, y entrará como un módulo nuevo del registro de módulos (`api/game_modules.py`, `lib/game-modules.ts`); no se crea desde el panel de administración.

La recomendación sale de reglas estadísticas sobre resultados ya registrados. **No es una predicción** — ver la regla de lenguaje más abajo.

## Estado y rumbo

| Etapa | Qué fue | Estado |
|---|---|---|
| MVP (pasos 1-8) | Analizador estadístico de ruleta: schema, auth, admin básico, mesa, motor estadístico, bankroll, carga inicial. | Construido |
| Fase 2 | Reglas de pagos con Wompi. | Reglas vigentes; la construcción pasó a la Fase 4 |
| Fase 3 | Motor de recomendación. | Construido |
| Fase 4 | Plataforma comercial: acceso, pagos, correo, legal, admin completo, multijuego. | Construida; cerrada el 2026-10-23. El cobro con Wompi se probó solo en sandbox y salió en el paso 5.1 |
| **Fase 5** | **Salida al mercado: retiro de Wompi, Tipster Page, facturación con Dataico, textos legales v2, lanzamiento.** | **En curso** |

El detalle de cada etapa, la tabla de decisiones que cambiaron y el avance paso a paso de las Fases 4 y 5 están en `docs/HOJA_DE_RUTA.md`. **Actualiza ese documento cuando cierres un paso o cuando el usuario tome una decisión de rumbo.**

## Documentos

| Documento | Para qué |
|---|---|
| `docs/HOJA_DE_RUTA.md` | Estado, historia y rumbo. Punto de entrada. |
| `docs/ARQUITECTURA_Y_ESTADISTICA.md` | **Referencia obligatoria del núcleo**: terminología (§0), fórmulas exactas del motor (§2), motor de recomendación (§2.10), modelo de datos y endpoints del núcleo (§3), alcance por etapas (§4). |
| `docs/PLATAFORMA_COMPLETA.md` | **Especificación de la Fase 4.** Léela antes de tocar acceso, pagos, correo, legal, admin o multijuego. |
| `docs/DESPLIEGUE.md` | Despliegue en el VPS con Dokploy y variables de entorno. |
| `docs/design/` | Mockups de login, registro y mesa. |
| `docs/reference/` | **Insumos, no se modifican.** `ESTRATEGIA_DE_RULETA_CORREGIDA_Y_VERIFICADA.txt` es la fuente de verdad matemática validada por un analista. `explicacion_analisis_estadistico_ruleta.md` es un boceto previo del que se toman técnicas estadísticas (shrinkage, χ², recencia, EV), no su lenguaje ni su arquitectura. `Comparativo_Software_Actual_vs_Software_Deseado.md` originó la Fase 3. |

Si algo en este CLAUDE.md o en `PLATAFORMA_COMPLETA.md` parece contradecir a `ARQUITECTURA_Y_ESTADISTICA.md`, gana el documento de arquitectura — pídele al usuario que lo aclare antes de asumir.

## Regla de producto no negociable: lenguaje no-predictivo

Este es el requisito más importante del proyecto, por encima de conveniencia de código o velocidad de desarrollo:

- **Prohibido**: "predicción", "predice", "va a salir", "seguro", "garantizado", "infalible", "ventaja sobre la casa", y cualquier cosa que implique que el sistema anticipa el resultado futuro de un giro independiente.
- **Permitido**: "Recomendación", "Apostar: …", "No apostar este giro", "Fuerza de señal", "Signal Score", "sugerencia estadística", "señal", "desviación observada".
- En código: `recommendation`, `signal_score`, `signal_band`, `statistical_suggestions`. Nunca `prediction` ni `predictions`. Aplica a nombres de tablas, campos y variables.
- Aplica también a todo lo que trae la Fase 4: página de planes, correos transaccionales, textos legales, nombres de planes y códigos de cupones. Ningún plan "da ventaja", ningún correo promete resultados.
- Si al escribir un commit, componente de UI, string de copy o nombre de variable/tabla dudas si suena predictivo, revísalo contra la tabla de terminología en `docs/ARQUITECTURA_Y_ESTADISTICA.md` §0 antes de continuar.
- **Única excepción**: el panel de admin. Son métricas internas que no ve el cliente, y ahí "aciertos" y "fallos" se usan tal cual.
- **Deportes** (decidido el 2026-10-15): la palabra "pronóstico" se permite solo en el texto visible del módulo de deportes. En la ruleta sigue prohibida, nunca va con palabras de certeza y los nombres en código siguen siendo `recommendation`. Los demás términos de deportes y el alcance completo están en §0 del doc de arquitectura.

### Disclaimer

- **El banner fijo de §0 se retiró de todas las pantallas**: el carácter estadístico y no predictivo del producto está cubierto en los términos y condiciones.
- Lo que queda, y es obligatorio, son dos líneas en la tarjeta de recomendación: bajo el score, _"81/100 es la fuerza del criterio interno, no la probabilidad de acertar."_; al pie, fija, _"Recomendación generada a partir del análisis estadístico de los resultados registrados. No es una predicción."_

## Stack técnico

- **Backend**: FastAPI (Python 3.11+), SQLAlchemy, Alembic, PostgreSQL, Pydantic v2.
- **Frontend**: Next.js (React + TypeScript), Tailwind CSS.
- **Sin IA**: el proyecto no integra modelos de visión ni de lenguaje. Los números los ingresa siempre el usuario, a mano. Esto es una decisión de producto deliberada — ver "Ingreso de números" más abajo.
- **Auth**: JWT (access + refresh), hash de contraseñas con argon2.
- **Motor estadístico**: vive en `backend/app/engine/`, debe ser Python puro (sin FastAPI, sin SQLAlchemy, sin llamadas de red) para poder testear con pytest sin infraestructura. Usa `numpy`/`scipy` donde corresponda (chi-cuadrado, distribución binomial).
- **Despliegue**: VPS con Dokploy; backend y frontend en un solo repositorio (`docs/DESPLIEGUE.md`).
- **Lo que suma la Fase 4** (`docs/PLATAFORMA_COMPLETA.md` §13): tipos del cliente API generados con `openapi-typescript`, CI en GitHub Actions, Playwright para tests de punta a punta, correo por SMTP (Resend), monitoreo con GlitchTip, pagos detrás de `PaymentProvider` (con Wompi hasta el 2026-10-22; la pasarela nueva entra en la Fase 5). **No se agrega** Redis, Celery ni ninguna cola.

## Estructura de carpetas esperada

Sigue exactamente la estructura definida en `docs/ARQUITECTURA_Y_ESTADISTICA.md` §3.1. No la reinventes ni la aplanes por conveniencia.

## Motor estadístico: reglas de implementación

- El motor (`engine/`) opera únicamente sobre la estructura genérica `possible_outcomes` + `categories` (ver §3.2 del doc de arquitectura). **Nunca** hardcodees lógica específica de ruleta (docenas, colores) dentro del motor — eso vive solo en los datos de `game_variants.categories_json`. Esto es lo que permite agregar dados después sin tocar `engine/`.
- Cada función del motor debe ser pura: recibe datos, devuelve resultado, sin efectos secundarios ni acceso a DB.
- Toda sugerencia estadística debe traer siempre juntos `theoretical_probability` y `observed_frequency_shrunk` — nunca uno solo (regla anti-falacia del jugador, §2 del doc de arquitectura). **La regla aplica a la respuesta de la API y a la sección desplegable "¿Por qué recomienda esto?", no a la vista principal de ruleta**: ahí el protagonista es la recomendación (mercado + Signal Score + banda + monto), y las frecuencias son el respaldo. Lo que no cambia es que los dos valores viajen siempre en pareja y que ninguno se muestre sin el otro allí donde se muestren.
- El χ² requiere mínimo 200 giros y p<0.05 para activarse — no lo actives con menos datos aunque el cálculo "funcione" matemáticamente con menos. Ese mínimo es un **piso de ruido, no un umbral de detección de sesgo**: detectar un sesgo explotable pediría del orden de 30.000 giros (ver §2.4 del doc de arquitectura). No describas esa señal como si detectara mesas sesgadas.
- El p<0.05 del χ² se evalúa sobre el p-valor **ya corregido por comparaciones múltiples** (Benjamini-Hochberg), nunca sobre el crudo: la prueba corre sobre las 5 categorías a la vez, y sin corregir una de cada cuatro sesiones mostraría una señal FUERTE espuria.
- Toda frecuencia observada viaja con su intervalo de Wilson (§2.2). No derives de él un veredicto por opción del tipo "esta desviación se distingue del azar" — serían 13 pruebas simultáneas y marcarían algo en un tercio de las mesas justas. El intervalo describe incertidumbre; afirmar es trabajo de `strength`, que sí está corregida.
- La auto-evaluación (línea base ingenua vs. motor) es un requisito del motor, no un nice-to-have.
- **Lo que el motor calcula y la vista no pinta** (desde el 2026-09-23): el top-3, las señales por categoría, la racha activa y la tasa de coincidencia se siguen calculando en sus endpoints (`/suggestions/latest`, `/streak`, `/performance`), pero el cliente no los muestra.
- **Señales avanzadas** (transición condicional, k-gramas, ciclo, señales de pleno, fusión multi-señal; §2.9 del doc de arquitectura): fuera de alcance hasta que el usuario las pida explícitamente, una por una.

## Motor de recomendación

El detalle completo (fórmula, pesos, calibración, desempate) vive en `docs/ARQUITECTURA_Y_ESTADISTICA.md` §2.10. Lo que sigue es lo que hay que tener presente al escribir código.

- Vive en `backend/app/engine/recommendation.py`. Python puro, **genérico**: los mercados salen de `categories_json` (grupos con `market != false` más `allowed_combinations`). Nunca hardcodees docenas ni colores ahí.
- **Dirección de la señal: a favor = salió MÁS de lo esperado.** Es la misma que ya usaba el EV del ranking top-3. Un mercado que salió menos da componentes en 0, nunca negativos — recomendar lo que no ha salido es la falacia del jugador.
- `allowed_combinations` es un **array**, no un objeto: JSONB no conserva el orden de las claves de un objeto y el desempate necesita orden estable. Por lo mismo, el orden de catálogo nunca sale de iterar `groups`.
- **Una sola recomendación.** Desempate determinista: mayor score → menor cobertura → índice de la categoría en `categories` → `group_ids` alfabético → clave.
- **Cuatro estados de salida** (decididos el 2026-09-24): SEÑAL FUERTE (score ≥ 80, `STRONG_THRESHOLD`), SEÑAL MEDIA (umbral medio ≤ score < 80), SEÑAL DÉBIL (umbral débil ≤ score < umbral medio) y SIN SEÑAL (bajo el débil → `NO_APOSTAR`). Los umbrales medio (`recommendation_threshold`, por defecto 50) y débil (`weak_threshold`, por defecto 35, nunca mayor que el medio) son por variante y editables en el admin; todos son inclusivos. **Con SEÑAL DÉBIL solo se ofrece la gestión plana a la apuesta base**: martingala y dos sectores no aplican y ningún escalón avanza, aunque el usuario anote esa gestión. La tarjeta DÉBIL lleva un aviso de que la señal es débil. Con menos de 11 números registrados en la sesión (`MIN_SPINS_FOR_SIGNAL`, 11 desde el 2026-10-15; antes 10) no hay recomendación aunque el score llegue al umbral; el formulario de mesa nueva lo avisa antes de abrir (`MIN_NUMEROS` en `NewSessionForm.tsx`, que va a la par). La banda (`strong`/`medium`/`weak`/`none`) sale de los mismos umbrales que la decisión, así que nunca la contradice. La pantalla muestra solo la jugada elegida: nunca un segundo mercado con su banda al lado, y con SIN SEÑAL no se nombra ninguna alternativa.
- El χ² entra sólo como **bono** (+10) y sólo con ≥200 giros y p corregido por Benjamini-Hochberg < 0.05. Ojo: a diferencia de §2.6, aquí una señal puede llegar a FUERTE sin χ². Es deliberado y está anotado en el doc.
- **`Z_MAX` no es un umbral de significancia.** Es la escala con la que el producto decide cada cuánto habla. Con la calibración vigente (2026-09-24: `Z_MAX` 1.6, pesos 0.58/0.32/0.10) y los umbrales por defecto (débil 35, medio 50), el motor recomienda en ~9 de cada 10 giros de una mesa perfectamente justa: ~1/3 de las recomendaciones son DÉBIL y ~7 % FUERTE. Ninguna banda acierta más que otra (backtest en §2.10). Si cambias `Z_MAX` o los pesos, vuelve a medir las dos cifras con el backtest antes de darlo por bueno.

### Gestión de banca

- **La sesión no elige una progresión.** La mesa muestra las tres a la vez — plana, martingala, recuperación de dos sectores — con lo que pide cada una. D'Alembert y Fibonacci salieron del producto.
- Los **sectores los pone el mercado recomendado**, no la estrategia. La recuperación de dos sectores no se ofrece sobre un mercado de un solo sector.
- Cada progresión lleva su escalón (`stage_martingale`, `stage_two_sector`; la plana no tiene). **Un escalón solo avanza si el usuario apostó con esa gestión** (`bets.strategy`, que anota el botón "Aposté esto"), y lo hace según el cierre de la recomendación. Sin apuesta con esa gestión, su escalón no se mueve (decidido el 2026-09-23; antes avanzaban las tres apostara o no). Una apuesta manual por fuera de las progresiones (`strategy` null) mueve la banca pero ningún escalón, y una progresión que no aplica al mercado recomendado (dos sectores sobre un mercado de una zona) tampoco se mueve.
- **Estado de parar** (decidido el 2026-09-24): cuando la banca ya no cubre la apuesta base, o se alcanza el límite de pérdida, la mesa deja de aceptar apuestas (lo rechaza el servidor) y en lugar de la recomendación muestra BANCA AGOTADA / LÍMITE DE PÉRDIDA ALCANZADO, con la sugerencia de dejar de apostar y los botones "Cerrar mesa" y "Abrir una mesa nueva". **No se cierra sola**: una sesión cerrada no deja deshacer su último número, y un número mal ingresado quedaría sin arreglo. El estado se deriva de la banca (`engine/bankroll.stop_reason`, expuesto como `SessionResponse.stop_reason`), así que deshacer el giro que lo provocó lo levanta solo.
- **Las apuestas de la sesión se cuentan por giro** (2026-10-15, `engine/session_stats.py`): dos docenas son dos apuestas y un solo giro, con ganancia si cerró en positivo. Los giros con ganancia viajan siempre con lo esperable por azar con esas mismas apuestas, y no se llaman "efectividad". Van con el resultado neto, el mejor momento y la peor caída, en "Apuestas de esta sesión" y en el resumen al cerrar.
- **Con `NO_APOSTAR` ninguna progresión avanza.** La recomendación se resuelve siempre (HIT/MISS), se haya apostado o no: el backtest mide al motor, no al usuario.

### Persistencia

- `statistical_suggestions` **se escribe**: una fila por recomendación emitida, incluido el `NO_BET` (con los datos del mejor candidato, que siempre existe). Sin esas filas el backtest no puede comparar cuándo el motor habló con cuándo calló.
- Montos en **centavos** (`stake_cents`), nunca float, con la moneda explícita.
- Deshacer un giro deshace también su recomendación: la que ese giro resolvió vuelve a `PENDING` y la emitida después se borra. Si no, quedaría un HIT o un MISS falso en lo que el backtest mide.

### Métricas internas

`engine/backtest.py` (puro), `scripts/backtest_recommendations.py` (CLI) y `GET /admin/recommendations/backtest`. **No se muestran al cliente.** La regla que las hace útiles: los pesos se calibraron sobre simulaciones, así que el backtest tiene que correr sobre historiales que el motor no haya visto. Si alguna vez ajustas los pesos contra un conjunto de datos, ese conjunto deja de servir para medir.

## Ingreso de números

Todos los números de una sesión los ingresa el usuario. Hay dos momentos, y ambos son manuales:

- **Carga inicial (al abrir la sesión)**: el usuario escribe o pega los números que ya vio en la pantalla de la mesa antes de sentarse a registrar. Quedan como historial de la sesión, con `source = 'initial_batch'`.
- **Giro a giro (durante la sesión)**: cada número nuevo se ingresa en el momento, con `source = 'manual'`.

Reglas que no se negocian:

- **El orden importa y hay que preguntarlo, nunca adivinarlo.** El motor pondera por recencia (§2.3): si el orden se invierte, la ponderación queda al revés y el análisis sale mal sin que nada falle visiblemente. La carga inicial debe pedir explícitamente si la lista viene del más antiguo al más reciente o al revés, y el backend normaliza siempre a orden cronológico ascendente (`spin_index` creciente = más antiguo → más reciente).
- **Validar contra `possible_outcomes` de la variante.** Un valor que no pertenece a la variante se rechaza; no se descarta en silencio ni se "corrige".
- **Sin IA, sin OCR, sin lectura de imágenes.** Se evaluó un pipeline de pantallazos con un modelo de visión y se descartó: introduce errores de extracción que el usuario tendría que revisar igual, y un costo por uso que no se justifica frente a escribir los números.

## Fase 4 — plataforma completa (trabajo en curso)

Decidida el 2026-10-02. Convierte el núcleo aprobado en plataforma comercial: pagos y suscripciones con Wompi, admin dashboard completo, verificación de correo y recuperación de contraseña, términos y políticas versionados, y una base multijuego que deje lista la entrada futura de apuestas deportivas. **La especificación completa vive en `docs/PLATAFORMA_COMPLETA.md`**: léela antes de tocar cualquiera de esas áreas. No cambia el motor.

### Orden de construcción (no saltar pasos)

0. Preparación del stack (§13).
1. Correo, verificación, restablecimiento de contraseña, `token_version` (§5).
2. Legal: documentos versionados, consentimientos, páginas públicas, onboarding (§6).
3. Modelo de acceso y bitácora de auditoría (§2, §4.6).
4. Planes y cupones (§3.2, §3.3).
5. Wompi (§3).
6. Admin dashboard completo (§4).
7. Generalización multijuego (§7).
8. Base de apuestas deportivas (§8).
9. Lanzamiento comercial (§9).

No avances a un paso sin que el anterior tenga al menos un test o una verificación manual funcionando. Si vas a saltarte este orden por alguna razón, dilo explícitamente y pide confirmación. Al cerrar un paso, márcalo en `docs/HOJA_DE_RUTA.md` §5.

### Acceso y cuentas

- **El acceso lo decide una sola función** (`core/access.py`, `has_access`), aplicada con la dependencia `RequireAccess` en todos los routers de juego. No repitas la lógica de acceso en otro lado. Desde el paso 3 aplica las reglas de §2.2 (suspendida, consentimiento, administrador, `full`, `invited`, suscripción vigente) y responde `403` con el motivo en `detail.code`. Desde el paso 7 aplica también la regla n.º 7 (juego incluido en el plan, `game_not_in_plan`): `has_access` recibe el juego, y `RequireGameAccess` la aplica a nivel de router en todas las rutas de una mesa (`{session_id}`), antes de validar el cuerpo; abrir una mesa la pide con el juego de la variante. Un router nuevo de la mesa lleva las dos dependencias. La cuenta con su decisión de acceso se arma con `api/presenters.user_response`, nunca con `UserResponse.model_validate`.
- **Legal** (paso 2, §6 y §6.7 del documento de la Fase 4): una versión publicada de un documento legal no se edita, se publica otra. El registro exige aceptar los documentos vigentes y declarar la mayoría de edad; no se crean consentimientos por migración ni por código en nombre de nadie. Los textos publicados son borradores pendientes de abogado: no los presentes como revisados. No hay página de Juego Responsable (descartada el 2026-10-08). Una versión nueva que exige aceptación se avisa por correo (paso 9, decidido el 2026-10-19): solo a cuentas con una suscripción vigente y el correo confirmado, al publicar, por tandas desde el job de renovaciones (`core/legal_notices.py`), y sin repetir por la restricción única de `legal_notices`. El aviso no reemplaza la pantalla de aceptación, que es la que deja la constancia.
- Cuenta nueva = **sin acceso hasta pagar** (o acceso manual del admin). `trial` ya no existe; `access_type` es `none | invited | full`. Sin pasarela configurada (`PAYMENT_PROVIDER` ausente o `none`, el estado desde el paso 5.1 de la Fase 5), la única vía es el acceso manual desde `/admin/usuarios` y `/planes` muestra el botón de suscribirse deshabilitado; con una pasarela, la cuenta sin acceso se suscribe desde `/planes`.
- El acceso se decide **siempre en el servidor** a partir de `access_type` y `current_period_end`. Nada que dependa de lo que mande el cliente.
- Correo por **SMTP genérico** detrás de la interfaz `EmailSender`; los tests usan un sender falso. Los tokens de correo se guardan **hasheados** y son de un solo uso.
- Toda acción de admin que toque acceso o dinero escribe en `admin_audit_log` en la misma transacción, con `core/audit.record` (que no hace commit) y con motivo obligatorio.

### Pagos: reglas no negociables

Estas reglas se fijaron el 2026-09-17 para Wompi (la antigua "Fase 2") y valen igual para cualquier pasarela. Wompi salió del proyecto el 2026-10-22 sin cobrar dinero real, y su código se retiró en el paso 5.1 de la Fase 5 (§3.18 del documento de la Fase 4). Hasta que entre la pasarela nueva (5.3) no hay pasarela: el pago está apagado y el acceso es manual.

- La verificación de firma (integridad de la transacción y firma del webhook) se lee de la **documentación oficial vigente de la pasarela**, nunca de memoria. Deja en un comentario de dónde salió el algoritmo. Una firma mal verificada es una puerta abierta a conceder acceso gratis.
- **El webhook no es fuente de verdad por sí solo**: tras verificarlo, vuelve a consultar el estado de la transacción contra la API de la pasarela antes de mover `subscriptions.status` o `users.access_type`.
- **Idempotencia** por `payment_events.provider_event_id` (único). Los webhooks se reintentan: reprocesar el mismo evento no puede otorgar dos períodos de acceso.
- Secretos solo por variable de entorno — `.env` está en `.gitignore` y Dokploy las inyecta. `.env.example` lista los nombres, nunca los valores.
- Montos en enteros (centavos), nunca `float`, con la moneda explícita en el campo.
- Dos modos de cobro (2026-10-08, §3.10 del documento de la Fase 4): **renovación automática** con una fuente de pago tokenizada, y **pago manual mes a mes**. Las reglas de esta lista aplican igual a los dos. Dos planes (2026-10-09): mensual de 100.000 COP y de dos meses de 150.000 COP; el de dos meses es un plan aparte, no un cupón. Antes de cada cobro automático el usuario recibe un correo de aviso con el monto y la fecha, que lo remite al apartado de suscripción de su perfil (§3.8 del documento de la Fase 4; se construye en el paso 5). El cálculo puro de precios, cupones y calendario de cobros vive en `backend/app/billing/`, con la misma disciplina que `engine/`: sin DB, sin red, con tests.
- **Planes y cupones** (paso 4, §3.11 del documento de la Fase 4): el precio lo calcula siempre el servidor con `billing/pricing.quote`; el cliente manda plan y código, nunca un monto. **Se muestra un solo precio, el que se cobra, en COP**: el precio de referencia en dólares se descartó el 2026-10-09 y no se vuelve a agregar sin que el usuario lo pida. Un cupón nunca deja el total en cero (porcentaje de 1 a 99). Planes y cupones no se borran, se desactivan, y todo cambio pide motivo y deja fila en la bitácora.
- El precio de una suscripción queda **congelado** al suscribirse; el precio nuevo de un plan aplica solo a suscripciones nuevas, salvo que un administrador lo traslade a las vigentes (§4.10 del documento de la Fase 4). El traslado vive en `core/price_changes.py`: una subida corre 30 días después de que el aviso le llegó a cada cliente (si el correo no sale, no corre), una bajada aplica ya. `subscriptions.price_cents` solo lo cambia `apply_due`, antes de cada cobro. Los tres intentos del cobro automático de un período van con un solo precio, el que corre en el primero (`billing/price_change.charge_price`, decidido el 2026-10-15): nunca se cobra el precio de la hora de cada intento.
- Copy de las pantallas de suscripción: ninguna promesa de resultados o de "ventaja".
- **Cómo está construido** (paso 5, entrega 1; §3.12 y §3.18 del documento de la Fase 4): la aplicación habla con `PaymentProvider` (`backend/app/payments/`), nunca con una pasarela directamente. `PAYMENT_PROVIDER` es `none` (por defecto: sin pasarela, pago apagado) o `fake` (pasarela simulada: solo desarrollo y Playwright, nunca en producción). **Un pago y su suscripción solo los mueve `core/subscriptions.apply_transaction`**, con una transacción que salió de `fetch_transaction` (la reconsulta); la usan el webhook (`POST /webhooks/payments`) y `GET /billing/payments/:id`. No escribas otro camino que cambie `payments.status` o `subscriptions.status`. `users.access_type` no se toca al pagar: el acceso sale de la suscripción. Los tests de API corren sobre `tests/api/pasarela_double.py`, una pasarela en memoria con eventos firmados con HMAC. Es transitoria: con la pasarela nueva vuelve la regla de usar su proveedor real con un transporte HTTP simulado, y el doble se borra.
- **Renovación automática** (paso 5, entrega 2; §3.14): cuándo se avisa, se cobra y se vence lo decide `billing/schedule.py` (puro); lo ejecuta `core/renewals.py`, que corre `scripts/run_renewals.py` cada hora. La idempotencia del job son dos cosas y no se quita ninguna: el candado de Postgres y la referencia por (suscripción, período, intento), con el pago confirmado en la base **antes** de cobrar. El aviso por correo sale siempre antes del cobro. Nunca se guarda el token ni un dato de tarjeta: solo la referencia de la fuente de pago, la marca y los últimos cuatro. Los datos de un medio de pago van del navegador a la pasarela: nunca pasan por nuestro backend, ni por un log, ni por GlitchTip, ni por `localStorage`. Si hiciera falta pasarlos por el servidor, se para y se pregunta. (El formulario propio de tarjeta y Nequi de §3.16, con `lib/tokenize.ts`, `jose` y `GET /billing/card-encryption-key`, era de Wompi y salió con él en el paso 5.1; hoy `PaymentSourceForm` solo tiene el selector de la pasarela simulada.)
- **Gestión de la suscripción y cierre de la cuenta** (paso 5, entrega 3; §3.15): cambiar el medio de pago y pasar de un modo al otro es `PUT`/`DELETE /billing/payment-method`, sobre la misma suscripción y **sin cobrar nada**; el único cobro que disparan es el reintento de una suscripción en mora (`core/renewals.retry_now`), que cuenta como uno de los tres intentos del período. En el frontend un medio de pago solo se guarda con `components/billing/PaymentSourceForm.tsx`. Al eliminar una cuenta la suscripción se borra y los pagos quedan anonimizados: lo que se conserva y lo que se reduce está en `core/payment_privacy.py`, y un evento de un pago sin cuenta se guarda ya reducido.
- **Facturación electrónica** (decidida el 2026-10-20, con **Dataico** desde el 2026-10-23; **base construida en el paso 5.2, emisión sin construir**; §3.17 del documento de la Fase 4, pasos 5.2 y 5.4 de la Fase 5):
  - Cada pago aprobado lleva una factura electrónica, emitida con Dataico por su API. **A quién va está por definir** (2026-10-23): a consumidor final, o con el nombre y la identificación del cliente, que hoy no se piden. No lo decidas en silencio: es del contador y, por los datos nuevos, de los textos legales.
  - **La factura nace con el pago aprobado**: `core/invoices.create_pending`, llamado solo desde la rama de aprobación de `apply_transaction`, en la misma transacción. Es única por pago (`invoices.payment_id`) y queda `pending` hasta el paso 5.4. No escribas otro camino que cree facturas. La fecha de la operación y la conversión a pesos son de `billing/fx.py` (puro, con tests).
  - Un pago en otra moneda se factura en pesos con la tasa del día del pago, contado en hora de Colombia. Para el euro: de euros a dólares con la tasa del día, y de dólares a pesos con la TRM de esa fecha. Las tasas van en `Decimal`, nunca en `float`, y quedan congeladas en la factura antes del primer envío.
  - El recibo por correo sigue siendo una constancia de pago y nunca se presenta como factura.
  - La API de Dataico se lee de su documentación oficial vigente, como la de la pasarela.
  - La emisión no se construye hasta resolver con el contador la moneda de la factura, el IVA y la tasa, y tener la cuenta de Dataico.
- **Suscripciones y pagos en el admin** (paso 6, entrega 1; §4.8): extender y cancelar viven en `core/subscription_admin.py` y no tocan ningún pago. "Reconsultar" en el admin es `apply_transaction` con `before_commit`, para que su fila de bitácora vaya en la misma transacción. Un pago aprobado solo vuelve a cambiar si la pasarela lo reporta anulado: entonces pierde el período que compró. Un reembolso se registra (`payment_refunds`) y no mueve ni el pago ni el acceso.

El flujo de pagos no se da por cerrado sin estos cuatro tests, que son los que distinguen "funciona con el caso feliz" de "aguanta producción" (la lista completa de doce está en §3.9 del documento de la Fase 4):

- Firma inválida → se rechaza, sin tocar el acceso.
- Evento duplicado (mismo `provider_event_id`) → se otorga un solo período.
- Transacción declinada → no se concede acceso.
- Suscripción vencida (`current_period_end` en el pasado) → el acceso queda revocado.

### Seguridad (paso 9, revisión del 2026-10-20)

- **El aislamiento entre cuentas lo hace el código** (no hay Row-Level Security, decisión del usuario), y lo garantiza `tests/api/test_seguridad.py`, que recorre todas las rutas del OpenAPI: sin sesión responden 401 salvo las de `PUBLICAS`, otra cuenta recibe 404 en todo lo de una mesa ajena, y una cuenta normal 403 en todo el admin. Una ruta pública nueva se agrega a `PUBLICAS` a propósito; una ruta nueva con un id de un recurso de la cuenta necesita su caso de acceso cruzado.
- **CSP con nonce** (`frontend/proxy.ts`, `lib/csp.ts`): todas las páginas se generan al pedirlas (`connection()` en el layout raíz). Un origen nuevo con el que hable el navegador va en `lib/csp.ts`, o el navegador lo bloquea sin error visible. Nada de scripts en línea ni `eval`; un script de terceros se inserta desde nuestro código (`strict-dynamic`), como el de Turnstile.
- Los tokens de sesión siguen en `localStorage` (decisión del usuario): lo que los protege es la CSP. No se pasa el refresh token a una cookie sin que el usuario lo pida.
- **Verificación contra bots** con Cloudflare Turnstile en el registro, el ingreso y el olvido de contraseña (`core/bot_check.py`, `components/BotCheck.tsx`). La API valida el token contra Cloudflare, falla cerrado y, sin llaves, queda apagada. El algoritmo sale de la documentación oficial de Cloudflare, citada en el módulo, nunca de memoria.

### Multijuego y deportivas

- **Por ahora, solo la ruleta** (decisión del 2026-10-14): crear un juego desde cero con la configuración a mano resultó difícil de hacer bien (resultados que tienen que ser equiprobables, pagos y progresiones pensados para la ruleta). Los juegos futuros se escriben en código, cada uno con su motor, como un módulo nuevo. En `/admin/juegos` el alta de juegos y de variantes está oculta (`ALTA_DE_JUEGOS` en `app/admin/juegos/page.tsx`), no borrada; la API la conserva. La edición de las variantes de la ruleta (umbrales) y del estado, el orden y la descripción del juego siguen a la vista.
- Los dados entran solo como **fixture de test** de genericidad (`backend/tests/fixtures/dados_d6.json`, un dado de seis caras: el motor supone resultados equiprobables y las sumas de dos dados no lo son); el juego de dados sigue fuera de alcance.
- Un juego tiene `slug` (va en la URL y no se edita), `module`, `status` (`active | hidden | coming_soon`) e ícono de un set fijo (§7.7 del documento de la Fase 4). Los routers de cada módulo salen del registro `api/game_modules.py`; `sports` está reservado sin implementación. Un plan sin filas en `plan_games` incluye todos los juegos, y quitarle un juego a un plan con suscripciones vigentes se rechaza.
- La pista de presentación `display` de `categories_json` es solo presentación: el motor no la lee. El frontend no supone ningún juego: el teclado sale de `possible_outcomes` y su tono de `display` (`lib/outcomes.toneOf`).
- La mesa vive en `/juegos/<slug>/mesa/<id>` (`/games/roulette/<id>` redirige ahí) y su pantalla la elige `lib/game-modules.ts` según el módulo del juego. Los componentes de la mesa están en `components/mesa/`.
- Las apuestas deportivas no se construyen en esta fase. Lo decidido para cuando se construyan está en §8.4 del documento (paso 8, 2026-10-15): fútbol y resultado final; calendario y resultados del proveedor, la cuota la escribe el usuario; apuesta fija y proporcional, sin martingala, dos sectores ni Kelly; y **salen solo si el backtest supera al mercado**. Faltan el proveedor y el concepto del abogado (§10 n.º 13 y 14). No se crean `engine/sports/`, `/sports` ni `/deportes` vacíos: el módulo ya está reservado en el enum y en los registros.

### Decisiones pendientes

Las decisiones pendientes de §10 de ese documento no se resuelven en silencio: se pregunta al usuario.

## Fase 5 — salida al mercado (trabajo en curso)

Decidida el 2026-10-23. El detalle, lo que bloquea cada paso y la lista del lanzamiento están en `docs/HOJA_DE_RUTA.md` §5.

- **Wompi sale del proyecto** (2026-10-22): no admite el modelo de negocio. Nunca se cobró dinero real, solo se probó con su sandbox. Lo reemplaza **Tipster Page**, que cobra en euros. Su código se retiró en el paso 5.1 (2026-10-23; §3.18 del documento de la Fase 4): sin pasarela configurada, el pago está apagado. Las reglas de "Pagos: reglas no negociables" de este archivo (firma, reconsulta, idempotencia, centavos, secretos, `apply_transaction` como único camino) valen para cualquier pasarela.
- **No se vende hasta tener Tipster Page y Dataico integrados.** Mientras tanto, el acceso es solo manual (prueba o cortesía).
- Orden: 5.1 retiro de Wompi → 5.2 base de la facturación sin proveedor → 5.3 Tipster Page → 5.4 emisión con Dataico → 5.5 textos legales v2 → 5.6 lanzamiento. Los pasos 5.3, 5.4 y 5.5 esperan a terceros: Tipster Page, el contador, Dataico y el abogado. No se diseña la integración de Tipster Page antes de leer su respuesta y su documentación: hacerlo antes sería adivinar.

## Convenciones de código

- Python: type hints en todo, Pydantic para validación de I/O, nombres de funciones y variables en español o inglés de forma consistente dentro de cada módulo (no mezclar en el mismo archivo).
- `ruff check .` y `mypy` corren en el CI y se corren en local antes de commitear (configuración en `backend/pyproject.toml`). `mypy` revisa en modo estricto los módulos puros: `app/engine/` y `app/billing/`.
- Nombres de tablas/campos en `snake_case`, en español donde ya están definidos en el doc de arquitectura (ej. `bankroll_current`), no los traduzcas.
- Tests: cada módulo de `engine/` y de `billing/` necesita tests unitarios con pytest antes de conectarse a un endpoint. Usa casos conocidos del documento de estrategia verificado (ej. la tabla de martingala $100→$102.300 en 10 pérdidas) como test de regresión.
- Frontend: componentes tipados, sin `any`.
- **Tipos del cliente API** (decidido el 2026-10-05): se generan desde el OpenAPI de FastAPI. `frontend/lib/api/openapi.json` y `frontend/lib/api/schema.d.ts` salen de `npm run gen:types` y se commitean **en el mismo commit** que el cambio de schema o de endpoint; no se editan a mano y el CI falla si quedaron desactualizados (§13.2 del documento de la Fase 4, skill `api-schema-sync`). `frontend/lib/types/` solo reexporta los tipos generados con el nombre que usan los componentes. Todo schema Pydantic hereda de `ApiModel` (`backend/app/schemas/base.py`), no de `BaseModel`: es lo que hace que un campo de respuesta `X | None = None` se genere como siempre presente. El generador no reemplaza una regla: `apiFetch` castea la respuesta (`as T`) sin validarla en runtime, así que backend y frontend se despliegan siempre desde el mismo commit.
- Migraciones: una por cambio lógico, con `down_revision` correcto y un downgrade que de verdad funcione. Antes de darla por terminada, `alembic upgrade head` sobre una base limpia y después `alembic downgrade -1`: una migración que no baja no está terminada. Nunca edites una migración ya aplicada en producción — agrega una nueva. Los backfills de datos van en su propia migración, separados del DDL.

## Diseños de referencia

`docs/design/` contiene mockups (login/registro, vista de ruleta). Impleméntalos fielmente en layout y jerarquía de información. Si hay conflicto entre el mockup y una regla de este documento (ej. el mockup no muestra las dos líneas obligatorias de la tarjeta de recomendación, o muestra el banner fijo que ya se retiró), **gana la regla de este documento**, y avisa al usuario de la discrepancia.

## Qué NO hacer

- No implementes la verificación de firma de una pasarela de memoria, ni concedas acceso confiando solo en el cuerpo del webhook — lee "Pagos: reglas no negociables" más arriba antes de tocar pagos.
- No repitas la lógica de acceso fuera de `core/access.py`.
- No construyas el builder visual de categorías del admin — usa un formulario estructurado simple.
- No implementes las señales avanzadas (transición condicional, k-gramas, ciclo, señales de pleno) sin que el usuario lo pida explícitamente (ver §2.9 del doc de arquitectura).
- No construyas el juego de dados como producto ni las apuestas deportivas, ni exportar CSV.
- No uses SQLite ni Prisma (eso era del boceto de referencia) — este proyecto usa PostgreSQL + SQLAlchemy/Alembic.
- No agregues Redis, Celery ni una cola (§13.5 del documento de la Fase 4).
- No agregues reconocimiento de imágenes, OCR, ni ninguna llamada a un modelo de visión o de lenguaje para leer los números de un pantallazo. Se evaluó y se descartó: el usuario los ingresa a mano.

## Cuando algo no esté claro

Si una decisión de producto no está cubierta en `docs/ARQUITECTURA_Y_ESTADISTICA.md`, en `docs/PLATAFORMA_COMPLETA.md` ni aquí, no la inventes en silencio: implementa la interpretación más simple y conservadora (menos alcance, más honestidad estadística), y déjalo señalado en tu respuesta para que el usuario lo confirme.
