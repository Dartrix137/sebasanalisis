# CLAUDE.md — Sebasanálisis

Este archivo guía a Claude Code en este repositorio. Léelo completo antes de escribir código, y vuelve a él ante cualquier duda de alcance o de lenguaje del producto.

Está organizado por tema, no por fecha: cada sección dice la regla **vigente**. La historia de cómo se llegó a ella (qué se construyó, en qué orden, qué decisiones cambiaron) vive en `docs/HOJA_DE_RUTA.md`.

## Qué es este proyecto

Plataforma fullstack por suscripción con un **motor de recomendación estadística** para juegos de casino. El usuario registra a mano los números de una mesa de ruleta europea o americana y, después de cada giro, la pantalla le dice **qué apostar en el siguiente giro** o **NO APOSTAR**, con un Signal Score 0-100, su banda y lo que pide cada gestión de banca. La arquitectura está preparada para agregar más juegos desde el panel de administración sin escribir código nuevo por cada uno.

La recomendación sale de reglas estadísticas sobre resultados ya registrados. **No es una predicción** — ver la regla de lenguaje más abajo.

## Estado y rumbo

| Etapa | Qué fue | Estado |
|---|---|---|
| MVP (pasos 1-8) | Analizador estadístico de ruleta: schema, auth, admin básico, mesa, motor estadístico, bankroll, carga inicial. | Construido |
| Fase 2 | Reglas de pagos con Wompi. | Reglas vigentes; la construcción pasó a la Fase 4 |
| Fase 3 | Motor de recomendación. | Construido |
| **Fase 4** | **Plataforma comercial: acceso, pagos, correo, legal, admin completo, multijuego.** | **En curso** |

El detalle de cada etapa, la tabla de decisiones que cambiaron y el avance paso a paso de la Fase 4 están en `docs/HOJA_DE_RUTA.md`. **Actualiza ese documento cuando cierres un paso o cuando el usuario tome una decisión de rumbo.**

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
- **Lo que suma la Fase 4** (`docs/PLATAFORMA_COMPLETA.md` §13): tipos del cliente API generados con `openapi-typescript`, CI en GitHub Actions, Playwright para tests de punta a punta, correo por SMTP (Resend), monitoreo con GlitchTip, pagos con Wompi. **No se agrega** Redis, Celery ni ninguna cola.

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
- **Cuatro estados de salida** (decididos el 2026-09-24): SEÑAL FUERTE (score ≥ 80, `STRONG_THRESHOLD`), SEÑAL MEDIA (umbral medio ≤ score < 80), SEÑAL DÉBIL (umbral débil ≤ score < umbral medio) y SIN SEÑAL (bajo el débil → `NO_APOSTAR`). Los umbrales medio (`recommendation_threshold`, por defecto 50) y débil (`weak_threshold`, por defecto 35, nunca mayor que el medio) son por variante y editables en el admin; todos son inclusivos. **Con SEÑAL DÉBIL solo se ofrece la gestión plana a la apuesta base**: martingala y dos sectores no aplican y ningún escalón avanza, aunque el usuario anote esa gestión. La tarjeta DÉBIL lleva un aviso de que la señal es débil. Con menos de 10 giros en la sesión (`MIN_SPINS_FOR_SIGNAL`) no hay recomendación aunque el score llegue al umbral. La banda (`strong`/`medium`/`weak`/`none`) sale de los mismos umbrales que la decisión, así que nunca la contradice. La pantalla muestra solo la jugada elegida: nunca un segundo mercado con su banda al lado, y con SIN SEÑAL no se nombra ninguna alternativa.
- El χ² entra sólo como **bono** (+10) y sólo con ≥200 giros y p corregido por Benjamini-Hochberg < 0.05. Ojo: a diferencia de §2.6, aquí una señal puede llegar a FUERTE sin χ². Es deliberado y está anotado en el doc.
- **`Z_MAX` no es un umbral de significancia.** Es la escala con la que el producto decide cada cuánto habla. Con la calibración vigente (2026-09-24: `Z_MAX` 1.6, pesos 0.58/0.32/0.10) y los umbrales por defecto (débil 35, medio 50), el motor recomienda en ~9 de cada 10 giros de una mesa perfectamente justa: ~1/3 de las recomendaciones son DÉBIL y ~7 % FUERTE. Ninguna banda acierta más que otra (backtest en §2.10). Si cambias `Z_MAX` o los pesos, vuelve a medir las dos cifras con el backtest antes de darlo por bueno.

### Gestión de banca

- **La sesión no elige una progresión.** La mesa muestra las tres a la vez — plana, martingala, recuperación de dos sectores — con lo que pide cada una. D'Alembert y Fibonacci salieron del producto.
- Los **sectores los pone el mercado recomendado**, no la estrategia. La recuperación de dos sectores no se ofrece sobre un mercado de un solo sector.
- Cada progresión lleva su escalón (`stage_martingale`, `stage_two_sector`; la plana no tiene). **Un escalón solo avanza si el usuario apostó con esa gestión** (`bets.strategy`, que anota el botón "Aposté esto"), y lo hace según el cierre de la recomendación. Sin apuesta con esa gestión, su escalón no se mueve (decidido el 2026-09-23; antes avanzaban las tres apostara o no). Una apuesta manual por fuera de las progresiones (`strategy` null) mueve la banca pero ningún escalón, y una progresión que no aplica al mercado recomendado (dos sectores sobre un mercado de una zona) tampoco se mueve.
- **Estado de parar** (decidido el 2026-09-24): cuando la banca ya no cubre la apuesta base, o se alcanza el límite de pérdida, la mesa deja de aceptar apuestas (lo rechaza el servidor) y en lugar de la recomendación muestra BANCA AGOTADA / LÍMITE DE PÉRDIDA ALCANZADO, con la sugerencia de dejar de apostar y los botones "Cerrar mesa" y "Abrir una mesa nueva". **No se cierra sola**: una sesión cerrada no deja deshacer su último número, y un número mal ingresado quedaría sin arreglo. El estado se deriva de la banca (`engine/bankroll.stop_reason`, expuesto como `SessionResponse.stop_reason`), así que deshacer el giro que lo provocó lo levanta solo.
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

- **Hoy el acceso no se verifica en ningún endpoint de juego.** El paso 3 lo cierra con una sola función (`core/access.py`, `has_access`) y la dependencia `RequireAccess` en todos los routers de juego. No repitas la lógica de acceso en otro lado.
- Cuenta nueva = **sin acceso hasta pagar** (o acceso manual del admin). `trial` desaparece; `access_type` pasa a `none | invited | full`.
- El acceso se decide **siempre en el servidor** a partir de `access_type` y `current_period_end`. Nada que dependa de lo que mande el cliente.
- Correo por **SMTP genérico** detrás de la interfaz `EmailSender`; los tests usan un sender falso. Los tokens de correo se guardan **hasheados** y son de un solo uso.
- Toda acción de admin que toque acceso o dinero escribe en `admin_audit_log` en la misma transacción.

### Pagos con Wompi: reglas no negociables

Estas reglas se fijaron el 2026-09-17 (la antigua "Fase 2") y siguen vigentes tal cual:

- La verificación de firma (integridad de la transacción y checksum del webhook) se lee de la **documentación oficial vigente de Wompi**, nunca de memoria. Deja en un comentario de dónde salió el algoritmo. Una firma mal verificada es una puerta abierta a conceder acceso gratis.
- **El webhook no es fuente de verdad por sí solo**: tras verificarlo, vuelve a consultar el estado de la transacción contra la API de Wompi antes de mover `subscriptions.status` o `users.access_type`.
- **Idempotencia** por `payment_events.provider_event_id` (único). Los webhooks se reintentan: reprocesar el mismo evento no puede otorgar dos períodos de acceso.
- Secretos solo por variable de entorno — `.env` está en `.gitignore` y Dokploy las inyecta. `.env.example` lista los nombres, nunca los valores.
- Montos en enteros (centavos), nunca `float`, con la moneda explícita en el campo.
- Cobro con **renovación automática** (tarjeta tokenizada). El cálculo puro de precios, cupones y calendario de cobros vive en `backend/app/billing/`, con la misma disciplina que `engine/`: sin DB, sin red, con tests.
- El precio de una suscripción queda **congelado** al suscribirse; el precio nuevo de un plan aplica solo a suscripciones nuevas.
- Copy de las pantallas de suscripción: ninguna promesa de resultados o de "ventaja".

El flujo de pagos no se da por cerrado sin estos cuatro tests, que son los que distinguen "funciona con el caso feliz" de "aguanta producción" (la lista completa de doce está en §3.9 del documento de la Fase 4):

- Firma inválida → se rechaza, sin tocar el acceso.
- Evento duplicado (mismo `provider_event_id`) → se otorga un solo período.
- Transacción declinada → no se concede acceso.
- Suscripción vencida (`current_period_end` en el pasado) → el acceso queda revocado.

### Multijuego y deportivas

- Los dados entran solo como **fixture de test** de genericidad; el juego de dados sigue fuera de alcance.
- Las apuestas deportivas no se construyen en esta fase: solo se reserva su estructura (§8 del documento).

### Decisiones pendientes

Las decisiones pendientes de §10 de ese documento no se resuelven en silencio: se pregunta al usuario.

## Convenciones de código

- Python: type hints en todo, Pydantic para validación de I/O, nombres de funciones y variables en español o inglés de forma consistente dentro de cada módulo (no mezclar en el mismo archivo).
- `ruff check .` y `mypy` corren en el CI y se corren en local antes de commitear (configuración en `backend/pyproject.toml`). `mypy` revisa en modo estricto los módulos puros: `app/engine/` hoy; al crear `app/billing/` se agrega a `files`.
- Nombres de tablas/campos en `snake_case`, en español donde ya están definidos en el doc de arquitectura (ej. `bankroll_current`), no los traduzcas.
- Tests: cada módulo de `engine/` y de `billing/` necesita tests unitarios con pytest antes de conectarse a un endpoint. Usa casos conocidos del documento de estrategia verificado (ej. la tabla de martingala $100→$102.300 en 10 pérdidas) como test de regresión.
- Frontend: componentes tipados, sin `any`.
- **Tipos del cliente API** (decidido el 2026-10-05): se generan desde el OpenAPI de FastAPI. `frontend/lib/api/openapi.json` y `frontend/lib/api/schema.d.ts` salen de `npm run gen:types` y se commitean **en el mismo commit** que el cambio de schema o de endpoint; no se editan a mano y el CI falla si quedaron desactualizados (§13.2 del documento de la Fase 4, skill `api-schema-sync`). `frontend/lib/types/` solo reexporta los tipos generados con el nombre que usan los componentes. Todo schema Pydantic hereda de `ApiModel` (`backend/app/schemas/base.py`), no de `BaseModel`: es lo que hace que un campo de respuesta `X | None = None` se genere como siempre presente. El generador no reemplaza una regla: `apiFetch` castea la respuesta (`as T`) sin validarla en runtime, así que backend y frontend se despliegan siempre desde el mismo commit.
- Migraciones: una por cambio lógico, con `down_revision` correcto y un downgrade que de verdad funcione. Antes de darla por terminada, `alembic upgrade head` sobre una base limpia y después `alembic downgrade -1`: una migración que no baja no está terminada. Nunca edites una migración ya aplicada en producción — agrega una nueva. Los backfills de datos van en su propia migración, separados del DDL.

## Diseños de referencia

`docs/design/` contiene mockups (login/registro, vista de ruleta). Impleméntalos fielmente en layout y jerarquía de información. Si hay conflicto entre el mockup y una regla de este documento (ej. el mockup no muestra las dos líneas obligatorias de la tarjeta de recomendación, o muestra el banner fijo que ya se retiró), **gana la regla de este documento**, y avisa al usuario de la discrepancia.

## Qué NO hacer

- No implementes la verificación de firma de Wompi de memoria, ni concedas acceso confiando solo en el cuerpo del webhook — lee "Pagos con Wompi: reglas no negociables" más arriba antes de tocar pagos.
- No repitas la lógica de acceso fuera de `core/access.py`.
- No construyas el builder visual de categorías del admin — usa un formulario estructurado simple.
- No implementes las señales avanzadas (transición condicional, k-gramas, ciclo, señales de pleno) sin que el usuario lo pida explícitamente (ver §2.9 del doc de arquitectura).
- No construyas el juego de dados como producto ni las apuestas deportivas, ni exportar CSV.
- No uses SQLite ni Prisma (eso era del boceto de referencia) — este proyecto usa PostgreSQL + SQLAlchemy/Alembic.
- No agregues Redis, Celery ni una cola (§13.5 del documento de la Fase 4).
- No agregues reconocimiento de imágenes, OCR, ni ninguna llamada a un modelo de visión o de lenguaje para leer los números de un pantallazo. Se evaluó y se descartó: el usuario los ingresa a mano.

## Cuando algo no esté claro

Si una decisión de producto no está cubierta en `docs/ARQUITECTURA_Y_ESTADISTICA.md`, en `docs/PLATAFORMA_COMPLETA.md` ni aquí, no la inventes en silencio: implementa la interpretación más simple y conservadora (menos alcance, más honestidad estadística), y déjalo señalado en tu respuesta para que el usuario lo confirme.
