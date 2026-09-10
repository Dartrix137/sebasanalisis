# Sebasanálisis — Arquitectura, Motor Estadístico y Alcance del MVP

> Documento de referencia técnica y de producto. Es la fuente de verdad para Claude Code al construir el proyecto. Cualquier ambigüedad se resuelve consultando este documento antes de asumir.

---

## 0. Filosofía del producto (no negociable)

Esta plataforma **NO predice** el resultado de un juego de azar. Ningún número, color, docena o columna tiene mayor probabilidad de salir por lo que pasó antes — cada giro de ruleta es un evento independiente. Esto es un hecho matemático, verificado y citado en `docs/reference/ESTRATEGIA_DE_RULETA_CORREGIDA_Y_VERIFICADA.txt`.

Lo que la plataforma sí hace, y que es legítimo:

1. **Describe estadísticamente** lo que ya ocurrió en una sesión (frecuencias, desviaciones, rachas).
2. **Cuantifica si esa desviación es "ruido" o estadísticamente notable**, usando herramientas matemáticas reales (shrinkage, chi-cuadrado, EV).
3. **Gestiona el tamaño de las apuestas** (bankroll) de forma matemáticamente correcta, dejando claro que ningún sistema de progresión cambia la ventaja de la casa.
4. **Se audita a sí misma**: compara su desempeño contra una línea base ingenua para ser honesta sobre si hay o no estructura aprovechable en una mesa.

### Terminología obligatoria en todo el código, UI y copy

| Prohibido                                  | Usar en su lugar                                                      |
| ------------------------------------------ | --------------------------------------------------------------------- |
| "Predicción"                               | "Sugerencia estadística" / "Señal"                                    |
| "El sistema predice X"                     | "El sistema detecta una desviación en X"                              |
| "Precisión del modelo"                     | "Tasa de coincidencia" (nunca implicar causalidad)                    |
| "Confianza" (en sentido de certeza futura) | "Fuerza de la señal" (FUERTE/MEDIA/DÉBIL, basada en evidencia pasada) |
| "Va a salir"                               | "Ha salido con mayor/menor frecuencia que lo esperado"                |

Todo endpoint, componente de UI y texto de marketing debe pasar este filtro. Si Claude Code genera copy que suene predictivo, debe corregirse antes de continuar.

### Disclaimers estructurales (obligatorios, no opcionales)

- Banner fijo y visible en toda pantalla donde se muestren sugerencias: _"La ruleta no tiene memoria. Cada giro es independiente. Este análisis es descriptivo, no predictivo."_
- Onboarding con scroll-to-accept explicando esto antes de dar acceso.
- Página de "Juego responsable": límites de tiempo/dinero, nunca usar dinero de obligaciones, detenerse ante progresiones incómodas (contenido tomado del documento de estrategia verificado).

---

## 1. Fuentes de referencia

- `ESTRATEGIA_DE_RULETA_CORREGIDA_Y_VERIFICADA.txt`: documento validado por un analista. Es la **fuente de verdad matemática** para probabilidades, house edge, y advertencias sobre martingala/docenas/columnas. Úsalo para copy educativo dentro de la app.
- `explicacion_analisis_estadistico_ruleta.md`: boceto de una versión anterior hecha con IA. Contiene técnicas estadísticas válidas (shrinkage, chi-cuadrado, ponderación por recencia, EV) que sí vale la pena adoptar — pero su lenguaje ("predicción", "IA predice") **no se usa tal cual**; se reescribe con la terminología de la sección 0. Su arquitectura (Next.js monolítico + Prisma + SQLite) tampoco se replica — este proyecto usa la arquitectura de la sección 3.

---

## 2. Estadística: fundamentos y motor

### 2.1 Probabilidades teóricas (constantes, nunca cambian)

Para ruleta europea (37 números) y americana (38 números), por tipo de apuesta:

| Apuesta                | Cobertura  | Prob. europea | Prob. americana | Pago |
| ---------------------- | ---------- | ------------- | --------------- | ---- |
| Pleno                  | 1 número   | 2.70%         | 2.63%           | 35:1 |
| Color (rojo/negro)     | 18 números | 48.65%        | 47.37%          | 1:1  |
| Par/Impar              | 18 números | 48.65%        | 47.37%          | 1:1  |
| Alto/Bajo (1-18/19-36) | 18 números | 48.65%        | 47.37%          | 1:1  |
| Docena                 | 12 números | 32.43%        | 31.58%          | 2:1  |
| Columna                | 12 números | 32.43%        | 31.58%          | 2:1  |

El 0 (y 00 en americana) no pertenece a ninguna docena, columna, color ni paridad — por eso esas apuestas pierden cuando sale. Esto va en `game_variants.categories_json` como configuración, nunca hardcodeado.

**Nota sobre el grupo "verde" en americana**: `["0","00"]` paga **17:1**, no 35:1. El pago de pleno (35:1) es para un solo número; un grupo de 2 números a 35:1 daría un EV de +0.89 (imposible de sostener, y generaría una señal permanentemente "FUERTE" falsa por diseño). 17:1 es además el pago real de la apuesta "0-00 split" que existe en mesas americanas físicas — no es un número inventado para cuadrar el EV.

**Valor esperado (EV)** — fórmula base, usada como filtro de calidad de toda señal:

```
EV = (p_estimada × pago) − (1 − p_estimada)
```

En una mesa sin sesgo real, `p_estimada = p_teórica` y el EV de CUALQUIER apuesta es exactamente `−1/37` (europea) o peor (americana). Esto se muestra siempre en la UI junto a cualquier señal, para que el usuario entienda que el "EV positivo" que a veces aparece es una lectura sobre _su muestra_, no una garantía.

### 2.2 Frecuencia observada con shrinkage bayesiano (reemplaza el "top-3 simple" que habíamos definido antes)

Contar frecuencias crudas en muestras chicas es engañoso (3 de 4 no es "75% de probabilidad"). Se usa shrinkage para prudencia matemática real:

```
p̂ = (casos_favorables + α × p_teórica) / (total_casos + α)
```

- `α` (fuerza de shrinkage) configurable por categoría; sugerido `α = 8` para categorías binarias (color, paridad, alto/bajo) y ajustado proporcionalmente para docenas/columnas (3 grupos, `α = 12`). **Vive dentro de cada objeto de categoría en `categories_json` como campo `shrinkage_alpha`** (es configuración del juego, no una constante de `engine/frequency.py` — depende de cuántos grupos tiene esa categoría, así que cada juego/categoría define el suyo).
- Con pocos datos, `p̂` se queda cerca de `p_teórica` (prudente). Con muchos datos, se acerca a la frecuencia cruda observada.

**Intervalo de Wilson: la escala del ruido.** El shrinkage modera la estimación, pero no dice *cuánto* puede moverse por azar — y sin eso, "60 %" leído sobre 10 giros y sobre 1.000 se ven idénticos. Cada frecuencia viaja con un intervalo de Wilson al 95 % (`observed_ci_low` / `observed_ci_high`):

```
centro = (p̂ + z²/2n) / (1 + z²/n)
margen = z/(1 + z²/n) × √( p̂(1−p̂)/n + z²/4n² )
```

- Se usa **Wilson y no la aproximación normal** (`p ± z√(p(1−p)/n)`) porque esa se rompe justo donde más hace falta: con pocos giros devuelve límites fuera de `[0,1]`, y cuando un grupo no salió ninguna vez colapsa a un intervalo de ancho cero — afirmando certeza absoluta a partir de no haber visto nada.
- Va sobre los **conteos crudos**, sin ponderar por recencia: Wilson supone un conteo binomial y la estimación con shrinkage y decaimiento no lo es. El intervalo describe lo que sostienen los datos crudos; `p̂` se muestra a su lado, no dentro.
- En la UI se dibuja como una banda con la probabilidad teórica marcada. Que la teórica caiga dentro se ve de un vistazo, y eso es todo lo que se comunica.

**Por qué NO hay un campo del tipo `deviation_compatible_with_chance`.** Es tentador derivar un booleano por opción ("esta desviación se distingue del azar"), pero serían 13 pruebas simultáneas —una por grupo— y en una rueda perfectamente justa marcarían al menos un grupo en **~⅓ de las sesiones**, medido por simulación. Es el mismo falso positivo que §2.4 corrige con Benjamini-Hochberg, reintroducido por otra puerta. El intervalo **describe incertidumbre y no afirma nada**; la afirmación la hace `strength`, que sí está corregida. Si alguna vez se agrega ese veredicto, hay que corregirlo por comparaciones múltiples primero.

### 2.3 Ponderación por recencia (decaimiento exponencial)

En vez de una "ventana fija de últimos N giros" (lo que habíamos definido antes como `window_size`), se usa un peso que decae con la antigüedad — matemáticamente más correcto y evita el efecto escalón de una ventana dura:

```
peso(antigüedad) = λ^antigüedad,   λ = 0.969  (vida media ≈ 22 tiradas)
```

`window_size` se mantiene en el modelo de datos como un límite superior de cuántos giros se cargan para el cálculo (rendimiento), pero el peso real de cada observación es exponencial, no binario.

### 2.4 Prueba χ² (chi-cuadrado) — señal de sesgo global

Mide si las frecuencias observadas de TODAS las categorías de una dimensión (ej. las 3 docenas) se desvían más de lo que el azar explicaría:

```
χ² = Σ (observado − esperado)² / esperado
```

- Requiere **mínimo 200 giros** en la sesión y **p < 0.05 (ya corregido)** para activarse.
- Es la única señal que usa el historial completo de la sesión sin decaimiento (los sesgos físicos reales de una mesa necesitan volumen para detectarse). Ese historial completo se le pasa **aparte de la ventana de recencia** — ver "Ventana de recencia vs. historial completo" más abajo.
- Evidencia generada, ej.: _"Docena 2 salió 15 de 40 (37.5%) vs. 32.4% esperado (χ² p=0.03)"_.

**Qué compra el mínimo de 200, y qué no.** Es un piso de ruido, no un umbral de detección de sesgo, y confundirlos lleva a leer la señal como algo que no es. La potencia real de la prueba sobre docenas (df=3, potencia 80%, α=0.05):

| Giros | Sesgo mínimo detectable | |
|---|---|---|
| 36 (umbral anterior) | una docena saliendo **58.2%** | una rueda visiblemente rota |
| 200 (umbral actual) | 43.4% | sigue siendo enorme |
| 5.000 | 34.6% | |
| ~29.660 | 33.3% | el mínimo *explotable* frente al pago 2:1 |

Contra un 32.43% teórico. Es decir: **ningún umbral dentro de una sesión convierte esta prueba en un detector de sesgo físico** — eso requeriría acumular giros por mesa entre sesiones, que está fuera del MVP. Lo que el mínimo de 200 sí garantiza es que la etiqueta FUERTE (§2.6) no se desbloquee con muestras que no sostienen ninguna afirmación.

**Ventana de recencia vs. historial completo.** `window_size` (§2.3) es un límite superior por rendimiento que aplica **solo a las señales ponderadas**, donde recortar casi no cuesta: con λ=0.969 los 50 giros más recientes ya concentran el 79% del peso total y un giro con 200 de antigüedad pesa 0.0018. Al χ² no se le aplica: ahí no hay decaimiento y cada giro recortado se pierde entero, así que la capa de API carga las dos listas por separado y `rank_suggestions` recibe ambas. Aplicarle la ventana lo dejaba viendo 50 giros por defecto y contradecía en silencio lo que esta sección dice que hace.

**Corrección por comparaciones múltiples (obligatoria).** La prueba no se corre sobre una dimensión sino sobre las cinco a la vez (color, docena, columna, paridad, alto/bajo). Contrastar cada una contra p < 0.05 por separado no da un 5% de falsos positivos sino `1 − 0.95⁵ = 23%`: aproximadamente **una de cada cuatro sesiones mostraría una señal FUERTE espuria**, porque `active` es lo que habilita esa etiqueta en el ranking (§2.6).

Por eso los p-valores de la familia se ajustan con **Benjamini-Hochberg (FDR)** antes de decidir la activación:

```
q_(i) = min sobre j≥i de ( m/j × p_(j) ),  acotado a 1 y monótono
activa  ⟺  q < 0.05
```

- `m` cuenta **solo las categorías que llegaron a calcular un p-valor**. Las que se detuvieron por muestra insuficiente no son pruebas: incluirlas inflaría `m` y castigaría a las demás sin haber mirado nada.
- BH controla la tasa de falsos descubrimientos bajo independencia o **dependencia positiva**. Las categorías de la ruleta no son independientes —color, paridad y alto/bajo reparten los mismos 37 números— pero su dependencia es positiva, que es el caso que BH cubre.
- El valor que viaja a la UI y se persiste es el **corregido** (`chi_square_pvalue_adjusted`), nunca el crudo: mostrar el crudo junto a una señal activada por el corregido invita a leer una significancia que la familia de pruebas no respalda.
- Una prueba corrida aisladamente es una familia de tamaño 1, donde `q = p` por definición y no hay nada que corregir.

### 2.5 Cola binomial — señal de racha

Para eventos binarios (¿se repitió el mismo color/paridad/alto-bajo N veces seguidas?):

```
P(racha de n) = p_teórica^n
```

Se calcula sobre la racha activa en tiempo real y se muestra siempre junto con el recordatorio de que la probabilidad del próximo giro no cambia por la racha (evita reforzar la falacia del jugador).

### 2.6 Ranking y selección: top 3 por significancia

Ya definido en la conversación, se mantiene, pero el `significance_score` ahora usa `p̂` (con shrinkage) en vez de frecuencia cruda:

```
significance_score = |p̂ − p_teórica| × sqrt(total_giros_ponderados)
```

Se muestran las **top 3 categorías** por `significance_score`, con badge de fuerza:

- **FUERTE**: EV ≥ 0.15 y `|p̂ − p_teórica|` con soporte de χ² significativo si aplica a esa dimensión — donde "significativo" es **p<0.05 sobre el p-valor ya corregido** por comparaciones múltiples (§2.4), nunca sobre el crudo. Es el único punto del motor donde una señal se declara fuerte, así que es el que tiene que aguantar la corrección.
- **MEDIA**: EV ≥ 0.06.
- **DÉBIL**: por debajo, se muestra igual pero claramente etiquetada — nunca se oculta ni se disfraza de fuerte.

### 2.7 Auto-evaluación (control de honestidad — obligatorio en el MVP)

Cada sesión calcula y muestra:

- **Tasa de coincidencia del motor**: de las sugerencias top-3 emitidas, cuántas coincidieron con el resultado real.
- **Línea base ingenua**: un "rival tonto" que siempre repite el último color/categoría ganador.
- Veredicto explícito: si el motor no supera la línea base a lo largo de la sesión/histórico del usuario, la conclusión honesta (mostrada en UI) es que esa mesa no muestra estructura aprovechable. Esto es un requisito de producto, no opcional — es lo que separa esta app de una que promete falsamente.

### 2.8 Gestión de banca (bankroll) — ya definido, con una corrección importante

El documento de estrategia verificado corrige un error común: **la martingala clásica solo aplica tal cual a apuestas de pago 1:1** (color, par/impar, alto/bajo). Para dos docenas o dos columnas (pago 2:1, apostando a dos sectores a la vez), la progresión de recuperación es distinta porque la ganancia neta al acertar es solo una fracción de lo apostado. El motor de bankroll debe soportar ambos modos:

- **Modo 1:1** (`martingale`, `dalembert`, `fibonacci`, `flat`): igual a lo ya diseñado en `engine/bankroll.py`.
- **Modo dos-sectores** (nuevo, para docenas/columnas dobles): progresión de recuperación con la secuencia validada en el documento (1-1, 2-2, 6-6, 18-18, 54-54 como ejemplo, configurable), calculando pérdida acumulada y advirtiendo del crecimiento exponencial del riesgo explícitamente en la UI.

Todas las estrategias deben mostrar, antes de que el usuario las active, la tabla de progresión con montos reales según su apuesta base — igual que las tablas del documento verificado — para que el riesgo sea visible, no abstracto.

**Regla de validación cruzada** (aplica en el schema y debe replicarse en el endpoint/DB): `strategy_mode='single'` solo admite `strategy` ∈ {martingale, dalembert, fibonacci, flat}; `strategy_mode='two_sector'` solo admite `strategy='two_sector_recovery'`. Nunca se puede mezclar un modo con una estrategia del otro modo — el backend debe rechazar la combinación inválida con 422, no intentar interpretarla.

### 2.9 Alcance del motor: qué entra al MVP y qué queda para después

El boceto de referencia (`explicacion_analisis_estadistico_ruleta.md`) tiene 9 señales (transición, patrón k-grama, racha, alternancia, ciclo, sesgo χ², y 3 de pleno vía Markov/ciclo/caliente). Implementar las 9 en el primer sprint es demasiado alcance. División:

**MVP (Fase 1) — Núcleo estadístico:**

- Frecuencia con shrinkage (2.2) + recencia (2.3) por categoría (color, paridad, alto/bajo, docena, columna)
- χ² de sesgo global (2.4)
- Racha activa con cola binomial (2.5)
- EV + ranking top-3 (2.1, 2.6)
- Auto-evaluación vs. línea base (2.7)
- Bankroll: martingala, d'Alembert, Fibonacci, flat + modo dos-sectores (2.8)

**Fase 2 — Señales avanzadas (post-MVP):**

- Transición condicional P(siguiente | actual) (sección 6.1 del boceto)
- k-gramas / patrones de secuencia (6.6)
- Ciclo de docenas/columnas (señal CICLO)
- Señales de pleno (Markov, ciclo, caliente) — alto riesgo de sobre-prometer, requieren las barreras y techos duros que describe el boceto (máx. 20%/15% de probabilidad estimada) si se implementan

**Confirmado (paso 1)**: `categories_json` NO incluye una categoría `straight`/pleno con 37-38 grupos — sería redundante. `engine/probability.py` deriva la probabilidad teórica del pleno directamente desde `1 / len(possible_outcomes)` cuando haga falta mostrarla (ej. en la tabla de referencia de §2.1), sin que el admin tenga que configurarla.

- Fusión multi-señal con detección de contradicciones y bonus por acuerdo (sección 12.1-12.3 del boceto)

Esta división se declara explícitamente en la UI: un aviso "Motor en versión núcleo — más señales estadísticas próximamente" evita expectativas de que la v1 tiene todo el sofisticamiento del boceto.

---

## 3. Arquitectura técnica

```
Backend:   FastAPI (Python) — motor estadístico puro en engine/, sin efectos secundarios
Frontend:  Next.js (React + TypeScript)
DB:        PostgreSQL
Auth:      JWT (access + refresh), hash de contraseñas con bcrypt/argon2
Pagos:     Wompi (Colombia) — fuera de scope del MVP, campos de DB preparados
```

**Por qué separado (Backend Python + Frontend Next.js) y no monolítico como el boceto de referencia:** el ecosistema Python (numpy/scipy para χ², shrinkage, distribución binomial) es más natural para el motor estadístico que TypeScript, y mantiene el motor testeable de forma aislada, igual que en el boceto (`roulette-v3.ts` como módulo puro) pero en Python.

### 3.1 Estructura de carpetas

```
backend/
  app/
    api/v1/
      auth.py  games.py  sessions.py  spins.py  bets.py  bankroll.py  admin.py
    core/
      security.py  config.py
    engine/                      # PURO — sin DB, sin HTTP, testeable con pytest solo
      probability.py             # probabilidad teórica desde categories_json
      frequency.py                # shrinkage + decaimiento por recencia
      chi_square.py                 # señal de sesgo global
      streak.py                      # racha + cola binomial
      ranking.py                      # significance_score + top-3 + fuerza (FUERTE/MEDIA/DÉBIL)
      bankroll.py                      # martingala, d'alembert, fibonacci, flat, dos-sectores
      baseline.py                       # línea base ingenua para auto-evaluación
    models/                              # SQLAlchemy
    schemas/                             # Pydantic (ya definidos, ver /schemas del proyecto)
    db/
      session.py
      migrations/                        # Alembic

frontend/
  app/ (o pages/)
    (auth)/login  (auth)/register
    dashboard/                            # menú principal, selector de juegos
    games/roulette/[sessionId]/           # vista de juego
    admin/                                 # panel admin
  components/
  lib/api-client.ts                        # wrapper tipado de la API REST
```

### 3.2 Modelo de juego genérico (ya definido, se mantiene)

Cualquier juego de resultados discretos y probabilidad fija (ruleta, dados, futuros) se describe con:

```json
{
  "possible_outcomes": ["0","00","1",...,"36"],
  "categories": [
    { "id": "color", "label": "Color",
      "groups": { "red": {"outcomes": [...], "payout": 1}, "black": {...}, "green": {...} } },
    { "id": "dozen", "label": "Docena", "groups": { "first": {...}, "second": {...}, "third": {...} } }
  ]
}
```

El motor estadístico (`engine/`) opera solo sobre esta estructura — nunca sabe que "docena" es específico de ruleta. Esto es lo que permite agregar dados u otros juegos desde el admin sin escribir código nuevo (ver conversación previa para el detalle completo).

### 3.3 Modelo de datos (consolidado)

```sql
users (id, email, password_hash, display_name, access_type, role, created_at)  -- display_name: nullable, opcional en registro (decisión de paso 2)
subscriptions (id, user_id, provider, payment_token_ref, plan_id, status, current_period_end)  -- fase 2, Wompi
payment_events (id, subscription_id, provider_event_id, status, raw_payload, signature_verified) -- fase 2

games (id, name, type, active, created_at)
game_variants (id, game_id, name, house_edge, categories_json, active)

game_sessions (
  id, user_id, game_variant_id, status, window_size,
  bankroll_start, bankroll_current, base_bet, table_limit,
  strategy_selected, strategy_stage, strategy_mode,   -- 'single' (1:1) | 'two_sector' (docenas/columnas dobles)
  started_at, closed_at
)

spins (id, session_id, spin_index, result_value, source, created_at)
   -- source: 'manual' (giro a giro) | 'initial_batch' (carga inicial al abrir la sesión)

bets (id, session_id, spin_id, category, option_label, amount, followed_suggestion,
      status, won, payout, net_change, created_at, resolved_at)

statistical_suggestions (              -- TABLA LATENTE: hoy nada la escribe (ver nota)
  id, session_id, spin_id, category, option_label,
  theoretical_probability, observed_frequency_shrunk, deviation,
  significance_score, strength,          -- 'strong' | 'medium' | 'weak'
  ev, chi_square_pvalue,                  -- null si no aplica a esta categoría/momento
  window_size_used, is_top3, created_at
)

bankroll_suggestions (id, session_id, spin_id, strategy, suggested_bet, stage,
                       risk_warning, ruin_probability_estimate, created_at)

session_performance (            -- nuevo, soporta la auto-evaluación (2.7)
  id, session_id, total_suggestions, matched_suggestions,
  baseline_matched, updated_at
)
```

**Nota sobre `statistical_suggestions` y `session_performance`.** Ambas están creadas pero **hoy nada las escribe**: los endpoints recalculan desde los giros en cada llamada. Es deliberado y está explicado en `api/v1/suggestions.py` — el motor es determinista, así que re-simular da el mismo resultado que haber acumulado fila a fila, y evita que un cambio de fórmula deje conteos viejos e incomparables en la base.

Consecuencia práctica: **la lista de campos de arriba no es el contrato de la API**, que vive en `schemas/suggestions.py`. Divergen a propósito en dos puntos, y por eso no se hizo migración para alinearlos:

- La columna se llama `chi_square_pvalue`; el campo de la API es `chi_square_pvalue_adjusted`, porque lo que se expone es el p-valor ya corregido (§2.4).
- La API agrega `observed_ci_low` / `observed_ci_high` (§2.2); la tabla no los tiene.

Si alguna vez se empieza a persistir, hay que alinear ambas cosas con una migración antes de escribir la primera fila.

### 3.4 Endpoints (consolidado de la conversación)

```
Auth:       POST /auth/register  POST /auth/login  POST /auth/refresh  GET /auth/me
Games:      GET /games  GET /games/:id/variants
Sessions:   POST /sessions  GET /sessions/:id  GET /sessions  PATCH /sessions/:id
            POST /sessions/:id/reset-strategy  POST /sessions/:id/close
            GET /sessions/:id/summary  GET /sessions/:id/performance   (auto-evaluación 2.7)
Spins:      POST /sessions/:id/spins  DELETE /sessions/:id/spins/:spin_id
            GET /sessions/:id/spins
            POST /sessions/:id/spins/bulk        (carga inicial de números, 3.5)
Bets:       POST /sessions/:id/bets
Suggestions: GET /sessions/:id/suggestions/latest  GET /sessions/:id/suggestions/history
Admin:      POST /admin/games  PATCH /admin/games/:id  POST /admin/games/:id/variants
            PATCH /admin/games/:id/variants/:variant_id  GET /admin/users
            PATCH /admin/users/:id/access
```

### 3.5 Carga inicial de números — ingreso manual, sin IA

Al abrir una sesión el usuario puede cargar de una vez los números que ya observó en la pantalla de la mesa, en lugar de ingresarlos uno por uno. Es texto que él escribe o pega; el sistema no lee imágenes.

1. **Entrada**: una lista de valores más el **orden declarado** (`most_recent_first` | `most_recent_last`). El orden es obligatorio y explícito.
2. **Normalización**: si el usuario declara "más reciente primero", el backend **invierte el arreglo antes de guardar**, porque el sistema siempre persiste en orden cronológico ascendente (`spin_index` creciente = más antiguo → más reciente). Adivinar el orden no es aceptable: el motor pondera por recencia (2.3), así que invertirlo silenciosamente da un análisis equivocado sin ningún error visible.
3. **Parseo tolerante de la entrada**: se aceptan separadores por coma, espacio, salto de línea o punto y coma, en cualquier combinación. Es una función pura y testeable, sin red.
4. **Validación estricta**: todo valor debe pertenecer a `possible_outcomes` de la variante. Si alguno no pertenece, se rechaza la carga completa con 422 indicando cuáles — nunca se descartan valores en silencio ni se "corrigen".
5. **Duplicados permitidos**: en la ruleta un mismo número sale muchas veces; deduplicar destruiría la muestra. La lista se guarda tal cual, conservando repeticiones y orden.
6. Los giros cargados quedan con `source = 'initial_batch'`, distinguibles de los ingresados giro a giro (`'manual'`).

**Decisión de producto (reemplaza el pipeline de visión que estaba planeado aquí):** se descartó integrar un modelo de visión para extraer los números de un pantallazo. Los motivos: la extracción se equivoca y obliga igual a una pantalla de confirmación editable, con lo que el usuario termina revisando número por número; y agrega un costo por uso recurrente que no se justifica frente a escribir la lista. El proyecto no llama a ninguna IA.

### 3.6 Seguridad y cuentas (estándar a adoptar del boceto, son buenas prácticas)

- Contraseñas: hash con algoritmo de derivación de clave (bcrypt o argon2), nunca en texto plano, comparación en tiempo constante.
- Tokens: JWT firmado, access token de vida corta + refresh token de vida larga (ej. 30 días).
- Rate limiting en login: máx. intentos por combinación IP+correo en una ventana de tiempo, mensajes genéricos que no revelan si un correo existe.
- Cada consulta de sesión filtra estrictamente por `user_id` del token — nunca por ID en la URL sin validar dueño.

---

## 4. Alcance del MVP — definición cerrada

### En scope (MVP v1)

1. **Auth**: registro, login, refresh, perfil. Acceso inicial: `access_type` en `'trial' | 'invited' | 'full'` — sin pagos aún.
2. **Admin dashboard**: gestión de usuarios (cambiar access_type), CRUD de juegos/variantes vía formulario estructurado (NO builder visual drag-and-drop — se pospone).
3. **Menú principal**: selector de juegos activos + shortcut a sesión activa si existe.
4. **Juego de Ruleta** (europea y americana como variantes precargadas):
   - Crear/cerrar/renombrar sesión, reset de estrategia, deshacer último número.
   - Ingreso manual de números giro a giro, más carga inicial de la lista ya observada al abrir la sesión (3.5).
   - Panel de sugerencias: top-3 por categoría con fuerza (FUERTE/MEDIA/DÉBIL), EV visible, disclaimer fijo.
   - Alerta de racha activa (con recordatorio de que no predice el próximo giro).
   - Señal de sesgo χ² cuando la sesión tiene ≥200 giros, corregida por comparaciones múltiples (§2.4).
   - Cada frecuencia observada con su intervalo de Wilson, para que la desviación se lea a escala del ruido (§2.2).
   - Motor de bankroll (modo 1:1 y modo dos-sectores) con tabla de progresión visible antes de activar.
   - Registro de apuesta real (categoría + monto) y resolución automática win/loss al ingresar el siguiente número.
   - Auto-evaluación: tasa de coincidencia del motor vs. línea base ingenua, visible en vivo y en el resumen de cierre.

### Fuera de scope (post-MVP, ya identificado)

- Pagos/suscripciones con Wompi (queda con el modelo de datos preparado, sin lógica).
- Builder visual de categorías en el admin (se usa formulario simple primero).
- Señales avanzadas: transición condicional, k-gramas, ciclo, señales de pleno (sección 2.9).
- Juego de dados u otros — el modelo ya lo soporta, pero no se construye la UI/seed en el MVP.
- Exportar CSV, migración de datos locales, notificaciones.

---

## 5. Diseños de pantalla

Se agregará una carpeta `docs/design/` con mockups de: login/registro y vista de juego de ruleta. Claude Code debe tratarlos como especificación visual de referencia — implementar fielmente layout, jerarquía de información y componentes (panel top-3, banner de disclaimer, input de número, tarjeta de sugerencia de bankroll) salvo que el stack (Next.js + Tailwind, ver `frontend-design` en CLAUDE.md) requiera adaptaciones menores de implementación.
