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
| "Va a salir" / "seguro" / "garantizado"      | "Recomendación" / "Apostar: …" / "No apostar este giro" (§2.10)        |
| "Ventaja sobre la casa"                     | "Fuerza de señal" / "Signal Score" — describe el criterio interno      |

Todo endpoint, componente de UI y texto de marketing debe pasar este filtro. Si Claude Code genera copy que suene predictivo, debe corregirse antes de continuar.

### Disclaimers estructurales (obligatorios, no opcionales)

- ~~Banner fijo y visible en toda pantalla donde se muestren sugerencias.~~ **Retirado en la Fase 3** (2026-09-22): el carácter estadístico y no predictivo del producto está cubierto en los términos y condiciones. Lo que queda en la vista de ruleta es la línea fija al pie de la tarjeta de recomendación (§2.10): _"Recomendación generada a partir del análisis estadístico de los resultados registrados. No es una predicción."_
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

#### 2.8.1 Plan del giro: siguiente paso de la progresión

Durante la sesión, `GET /sessions/:id/bankroll/suggestion` devuelve, además del monto que pide el escalón actual, **dónde queda la progresión en los dos casos posibles** (`engine.bankroll.bankroll_plan`):

- `next_if_lost` / `next_if_won`: escalón siguiente, apuesta que pediría y banca resultante, más tres banderas: `exceeds_bankroll` (la banca ya no la cubriría), `exceeds_table_limit` (la mesa no la aceptaría) y `reaches_loss_limit` (se alcanzaría el límite de pérdida del usuario).
- `stages_supported`: escalones seguidos, contando el actual, que la banca actual puede pagar (se detiene también en el límite de mesa).

Reglas que la UI respeta:

- **Es condicional, nunca un pronóstico.** El copy dice "si este giro cierra en contra / a favor"; jamás cuál de los dos va a ocurrir.
- **El escalón avanza por el neto de la ronda**, no por apuesta: solo se mueve cuando el giro tenía apuestas registradas (`advance_stage_by_round`). Los montos del plan suponen que se apuesta lo que pide la progresión; si el usuario apuesta otro monto, la banca resultante cambia, pero el escalón avanza igual.
- **Si la apuesta del escalón actual no se puede colocar** (banca o mesa), la UI no muestra los dos casos —describirían un giro imposible, con banca negativa— y deja solo las alertas.
- Tras cada giro que mueve el escalón se muestra un aviso del cambio ("el último giro cerró en contra: la progresión sube del escalón 2 al 3"). Reiniciar la progresión o cambiar de estrategia también mueven el escalón, pero no generan ese aviso: atribuírselo a un giro sería falso.

#### 2.8.2 Alertas de gestión de banca

La misma respuesta trae `alerts`: lista ordenada de la más grave a la menos grave, con `level` ∈ {`critical`, `caution`, `info`}, un `code` estable y un `message` listo para mostrar. Se apoyan en las reglas de disciplina del documento verificado (§9: fijar un límite de pérdida, no subirlo para recuperar, detenerse si la progresión llega a un monto incómodo, revisar el límite de la mesa, no leer una racha a favor como prueba de que la estrategia venció a la casa). Ninguna dice a qué apostar ni qué resultado esperar.

| `code` | Nivel | Cuándo |
| --- | --- | --- |
| `bankroll_insufficient` | crítico | La banca actual no cubre la apuesta del escalón actual. |
| `last_affordable_stage` | crítico | Es el último escalón que la banca cubre. |
| `few_stages_left` | atención | La banca cubre 2 escalones o menos desde aquí (`FEW_STAGES_LEFT`). |
| `table_limit_exceeded` | crítico | La apuesta por sector del escalón actual supera el límite de la mesa. |
| `table_limit_near` | atención | El límite de la mesa se alcanza en 1 o 2 escalones (`TABLE_LIMIT_LOOKAHEAD`). No aplica a la plana. |
| `loss_limit_reached` | crítico | La pérdida neta de la sesión ya alcanzó el límite del usuario. |
| `loss_limit_next` | crítico | Perder el giro actual alcanzaría el límite del usuario. |
| `loss_limit_near` | atención | Se perdió el 75 % o más del límite (`LOSS_LIMIT_NEAR`). |
| `drawdown` | atención / crítico | **Solo si la sesión no tiene límite propio**: pérdida ≥ 25 % / ≥ 50 % de la banca inicial. |
| `in_profit` | nota | La banca actual supera la inicial: recordatorio de que eso no prueba nada y de fijar un punto de retiro. |
| `exponential_growth` | atención | Martingala o dos sectores desde el escalón 4: cuánto pediría el siguiente. |

Los umbrales (`DRAWDOWN_*`, `FEW_STAGES_LEFT`, `TABLE_LIMIT_LOOKAHEAD`, `LOSS_LIMIT_NEAR`, `EXPONENTIAL_STAGE_WARNING`) son constantes de `engine/bankroll.py`: valores por defecto conservadores, no calibrados contra datos. Todos los textos tienen test de lenguaje no-predictivo.

#### 2.8.3 Límite de pérdida por sesión

`game_sessions.loss_limit` (opcional) es la pérdida neta —`bankroll_start - bankroll_current`— en la que el usuario decidió detenerse. Se fija al crear la sesión o después, desde "Ajustes de la sesión".

- **Validación**: `0 < loss_limit ≤ bankroll_start` (schema, endpoint y `CHECK` en DB). No se puede perder más de lo que se trajo a la mesa.
- **Se puede fijar o bajar, nunca subir ni quitar con la sesión abierta.** El `PATCH` rechaza con 422 un valor mayor al actual o `null` si ya había uno. Es la regla literal del documento verificado ("no aumentes el límite para recuperar pérdidas"): si se pudiera subir a mitad de sesión, dejaría de ser una decisión tomada antes de jugar. Para otro límite, se cierra la sesión y se abre otra.
- **No bloquea el registro de apuestas.** La app anota lo que el usuario apostó de verdad en la mesa; negarse a registrarlo solo haría que el historial mintiera. El límite actúa a través de las alertas y del paso siguiente (`reaches_loss_limit`).
- Con límite propio, las alertas genéricas de caída (`drawdown`) no se emiten: el usuario ya dijo dónde quiere detenerse y dos avisos de caída distintos confunden.

#### 2.8.4 Editar la sesión con una serie abierta

`PATCH /sessions/:id` permite cambiar estrategia, límite de mesa y límite de pérdida con la sesión abierta. La banca inicial y la apuesta base no se editan: cambiarlas invalidaría toda la progresión calculada.

- **Cambiar de estrategia (o de modo) reinicia el escalón a 0.** El escalón de una progresión no significa nada en otra (el escalón 3 de la martingala son 4 unidades; en D'Alembert serían otras). La serie abierta no se traslada; lo ya perdido sigue contando en la banca y en el límite de pérdida.
- **El reinicio solo ocurre si la estrategia cambia de verdad.** El backend compara contra lo persistido: reenviar la misma estrategia junto con otro campo (por ejemplo, al editar solo el límite de mesa) no toca el escalón.
- **Deshacer un giro anterior al cambio no restaura un escalón ajeno.** Al cambiar de estrategia se borra `spins.strategy_stage_before` de los giros existentes; deshacerlos devuelve la banca y deja pendientes sus apuestas, pero ya no restaura un escalón de la progresión vieja.
- **Apuestas pendientes**: si se cambia de estrategia con una apuesta registrada y aún sin resolver, esa apuesta se resuelve normalmente con el giro siguiente y el escalón avanza según la estrategia nueva, desde 0.
- **Cambio de modo (1:1 ↔ dos sectores)**: las apuestas elegibles para estimar el riesgo de ruina cambian. Si la que el usuario tenía elegida deja de existir, la UI la descarta y sigue sin estimación, en lugar de pedir una apuesta incompatible (que daría 422).

### 2.10 Motor de recomendación (Fase 3, decidido el 2026-09-22)

El producto deja de ser un analizador descriptivo y pasa a ser un **motor de recomendación**: después de cada giro dice qué apostar en el siguiente, o `NO_APOSTAR`. Vive en `engine/recommendation.py`, es Python puro y genérico — los mercados salen de `categories_json`, nunca hardcodeados.

#### Catálogo de mercados

Dos fuentes, ambas en los datos:

- cada grupo con `market != false`. El verde de la ruleta lo pone en `false`: cubre el 0/00 y no es una zona que el producto recomiende, pero se conserva como grupo para que las frecuencias de color sumen 1 y el χ² tenga todas sus celdas.
- cada entrada de `allowed_combinations` (dos docenas, dos columnas).

`allowed_combinations` es un **array y no un objeto** a propósito: JSONB no conserva el orden de las claves de un objeto, y el desempate necesita un orden de catálogo estable. Por el mismo motivo el orden de los mercados simples no sale de iterar `groups`, sino de la posición de la categoría en el array `categories` y de `group_ids` ordenados alfabéticamente.

#### Dirección de la señal

Un mercado juega a favor cuando su frecuencia observada con shrinkage quedó **por encima** de su teórica. Es la misma dirección que ya usaba el ranking top-3: allí la lleva el EV (`expected_value(observed_frequency_shrunk, payout)`), monótono creciente en la frecuencia observada, así que sólo un grupo que salió más de lo esperado podía alcanzar MEDIA o FUERTE. Aquí se hace explícita con el signo de `z`. Un mercado que salió **menos** de lo esperado da componentes en 0, nunca negativos: recomendar lo que no ha salido sería la falacia del jugador.

#### Signal Score

Por cada mercado y cada ventana, una desviación estandarizada con signo:

```
z_v = (p̂_v − p_teórica) / √( p_teórica(1−p_teórica) / N_v )
```

`p̂_v` es el shrinkage + recencia de §2.2-2.3 y `N_v` el total ponderado. No es una métrica nueva: es el `significance_score` de §2.6 con signo y dividido por la desviación típica binomial. Ese divisor es lo que vuelve comparables coberturas distintas (18/37 frente a 24/37) y variantes distintas (18/37 frente a 18/38).

Ventanas: 10, 20, 50 y 100 giros; con menos giros que la ventana más corta, el historial entero como ventana única.

```
signal_score = 100 × (0.58·D + 0.32·R + 0.10·C) + 10·[χ² activo]      acotado a [0, 100]
```

| Componente | Qué mide | Cálculo | Peso |
| --- | --- | --- | --- |
| **D** desviación | cuánto se separó con la muestra más grande | `clamp(z_ventana_larga / Z_MAX, 0, 1)` | 0.58 |
| **R** recencia | cuánto se está separando ahora | `clamp(z_ventana_corta / Z_MAX, 0, 1)` | 0.32 |
| **C** consistencia | si la inclinación aguanta en tramos distintos | `clamp(media(z) / media(abs z), 0, 1)` | 0.10 |

**C se calcula sobre tramos disjuntos** (0-10, 10-20, 20-50, 50-100), no sobre las ventanas acumuladas. Las ventanas están anidadas: los 10 giros más recientes caen dentro de las cuatro, y medir "consistencia" sobre ellas premiaría a un mercado por un único tramo caliente contado cuatro veces. La explicación que ve el usuario sigue mostrando las ventanas acumuladas; los tramos son sólo para este componente.

**Con un solo tramo, C queda indefinida** y su peso se reparte entre D y R. Un tramo no tiene con qué ser consistente; darla por 1 regalaría sus puntos a cualquier mercado que asome por encima de la teórica en los primeros giros.

El χ² suma sus 10 puntos sólo con ≥200 giros y p corregido por Benjamini-Hochberg < 0.05 (§2.4). Es un **bono, no un requisito**: a diferencia de §2.6, donde el χ² activo era condición necesaria para la etiqueta FUERTE, aquí un mercado puede llegar a SEÑAL FUERTE sin él. Es consecuencia directa de que las bandas se deriven del score, y conviene tenerlo presente al comparar las dos etiquetas: no significan lo mismo.

#### Z_MAX y qué compra el umbral

`Z_MAX = 1.6`. **No es un umbral de significancia.** Un z de 2 sobre una prueba aislada sería el clásico "dos sigmas", pero aquí se evalúa sobre ~18 mercados solapados a la vez y sin corregir por comparaciones múltiples, así que llegar a 2 no dice que la desviación se distinga del azar. Es la escala con la que el producto decide cada cuánto habla, y junto con los pesos, cuántas de esas veces la señal llega a FUERTE.

**Recalibración del 2026-09-24.** La calibración anterior (Z_MAX 2.0, pesos 0.45/0.25/0.30) recomendaba en ~35 % de los giros, pero solo ~5 % de esas recomendaciones llegaba a 80: la consistencia, que es un cociente y no una magnitud, daba sus 30 puntos a cualquier inclinación pareja por chica que fuera, y apelotonaba los scores entre 60 y 79. Con los tres estados de salida (MEDIA 60-79, FUERTE 80+), eso dejaba FUERTE prácticamente fuera de alcance. Bajar el peso de C a 0.10 y Z_MAX a 1.6 conserva cuánto habla el motor y abre el tramo de arriba.

Se barrió Z_MAX (1.0-3.0) × peso de C (0-0.40) sobre ruedas europeas justas con una semilla de calibración (200 sesiones × 150 giros), y se validó en dos conjuntos no vistos (otras 200 × 150, y 40 × 400 con el χ² activo). Con el peso de C fijo, la frecuencia con que habla el motor y la parte FUERTE no se mueven por separado: para hablar en ~1 de cada 3 giros, FUERTE queda entre ~6 % (C 0.30) y ~21 % (C 0). Se eligió C 0.10 porque todavía descuenta las inclinaciones que se cancelan entre tramos.

Backtest fuera de muestra (`scripts/backtest_recommendations.py`, semilla 90217, 150 × 150, umbral 60):

| Calibración | variante | % NO APOSTAR por giro | FUERTE / recomendaciones | coincidencia MEDIA | coincidencia FUERTE | ROI/unidad |
| --- | --- | --- | --- | --- | --- | --- |
| anterior (2.0; .45/.25/.30) | europea | 64.6 % | 4.6 % | — | — | −0.018 |
| **vigente (1.6; .58/.32/.10)** | europea | **64.2 %** | **18.4 %** | 46.9 % | 45.3 % | −0.022 |
| **vigente (1.6; .58/.32/.10)** | americana | **64.4 %** | **20.0 %** | 45.6 % | 45.2 % | −0.050 |

**FUERTE no acierta más que MEDIA**, y ninguna de las dos se aparta de la ventaja de la casa (−0.027 europea, −0.053 americana). FUERTE dice que la muestra ya ocurrida se separó más, no que el giro siguiente cambie de probabilidad. Esa es la razón por la que el texto bajo el score es obligatorio.

**Lo que cambió en el comportamiento.** Con C pesando menos, una desviación reciente y grande pesa más que el hecho de que la inclinación se sostenga en tramos distintos. Ejemplo concreto (test `test_una_racha_reciente_da_señal_aunque_el_total_este_parejo`): un barrido ordenado 0→36 repetido seis veces, donde cada número sale lo mismo pero los últimos diez son 27-36, antes quedaba en 58.7 (NO APOSTAR) y ahora marca "Alto" con 82.8 (FUERTE).

**Umbral por defecto 50 (2026-09-24).** Con 60, en mesa real el motor pasaba la mayoría de los giros en SIN SEÑAL: las señales llegan en bloques de ~4 giros seguidos y una sesión corta puede quedar muy por debajo del promedio. Se bajó el umbral por defecto a 50. Los pesos y Z_MAX no cambian. Mismo backtest fuera de muestra:

| Umbral | variante | % NO APOSTAR por giro | FUERTE / recomendaciones | coincidencia MEDIA | coincidencia FUERTE | ROI/unidad |
| --- | --- | --- | --- | --- | --- | --- |
| **50** | europea | **39.8 %** | **11.0 %** | 47.2 % | 45.3 % | −0.023 |
| **50** | americana | **41.8 %** | **12.3 %** | 45.9 % | 45.2 % | −0.050 |

Bajar el umbral agrega recomendaciones MEDIA con desviaciones más chicas. Las FUERTE son las mismas (el umbral alto no se movió) y la coincidencia no cambia.

Es decir: con la calibración vigente y el umbral por defecto, **el motor recomienda en aproximadamente seis de cada diez giros de una mesa perfectamente justa**. Es lo que corresponde a la decisión de producto de dar una instrucción clara en cada giro. Lo que el umbral regula es cuánto habla el producto, no cuánto separa señal de ruido: la tasa de coincidencia y el ROI se quedan en la ventaja de la casa en toda la tabla, que es lo esperado y lo que el backtest confirma.

#### Bandas, umbral y desempate

Tres estados de salida y nada más (decidido el 2026-09-24):

| Estado | Condición | Salida |
| --- | --- | --- |
| **SEÑAL FUERTE** (`strong`) | score ≥ umbral alto (80) | APOSTAR: mercado, fuerza interna y monto por gestión |
| **SEÑAL MEDIA** (`medium`) | umbral mínimo ≤ score < umbral alto | Igual, indicando que la fuerza es media |
| **SIN SEÑAL** (`weak`) | score < umbral mínimo | NO APOSTAR ESTE GIRO. Esperar el siguiente resultado y volver a analizar |

- El umbral mínimo es el de recomendación, configurable por variante (`recommendation_threshold`, por defecto 50; era 60 hasta el 2026-09-24, migración `9e3f61a0c7d2`) y editable desde el admin. El alto es fijo (`STRONG_THRESHOLD = 80`). Los dos son inclusivos. Si el admin sube el mínimo por encima de 80, desaparece la MEDIA: todo lo que se recomienda es FUERTE.
- **La banda sale de los mismos umbrales que la decisión**, así que nunca la contradice: una recomendación es MEDIA o FUERTE, y un NO APOSTAR es SIN SEÑAL, también en el mejor candidato que se guarda. Antes la banda era una escala absoluta de cuatro tramos (0-39 DÉBIL, 40-59 MEDIA, 60-79 FUERTE, 80+ MUY FUERTE) que no coincidía con el umbral: un NO APOSTAR podía salir "MEDIA" y toda recomendación salía "FUERTE". Las filas ya guardadas se reetiquetaron (migración `221b8df05052`).
- El motor no está obligado a recomendar en cada giro: la mejor alternativa disponible **no se asciende** a señal si no pasa el mínimo.
- **Con menos de 10 giros en la sesión no hay recomendación**, aunque el score pase el umbral (`MIN_SPINS_FOR_SIGNAL`, la ventana más corta). Con el umbral en 50, cinco rojos seguidos ya daban 51 puntos. La pantalla lo muestra como FALTA INFORMACIÓN.
- Se devuelve **una sola** recomendación, y la pantalla muestra solo esa: aunque otro mercado también pase el umbral, no aparece como segunda jugada. Con SIN SEÑAL no se nombra ninguna alternativa. Desempate determinista: mayor score → menor cobertura → índice de la categoría en el array `categories` → `group_ids` alfabético → clave del mercado. Ninguna parte de la clave depende del orden de un objeto JSON.

#### Gestión de apuesta

El flujo es: primero la recomendación, después el monto. Desde la Fase 3 **la sesión no elige una progresión al crearse**: la mesa muestra las tres (plana, martingala, recuperación de dos sectores) con lo que pide cada una, y el usuario sigue la que quiera. D'Alembert y Fibonacci salen del producto.

- **Los sectores los pone el mercado, no la estrategia.** Si la recomendación cubre dos docenas son dos sectores, la siga quien la siga.
- La recuperación de dos sectores **no se ofrece** sobre un mercado de un solo sector: su aritmética asume que el otro sector se pierde y que el acertado paga 2:1, así que sobre "Negro" no describe nada.
- Cada progresión lleva su propio escalón (`game_sessions.stage_martingale`, `stage_two_sector`; la plana no tiene, siempre es 0) y **solo avanza si el usuario apostó con esa gestión** en ese giro (`bets.strategy`), según el cierre de la recomendación. Así el escalón que se muestra es el de la serie que el usuario lleva de verdad. Sin apuesta con esa gestión, el escalón no se mueve; una apuesta manual por fuera de las progresiones mueve la banca pero ningún escalón; y una progresión que no aplica al mercado recomendado (la recuperación de dos sectores sobre un mercado de una sola zona) no se mueve aunque se anote. Decidido el 2026-09-23; antes avanzaban las tres con cada recomendación, se apostara o no.
- **El escalón ya no avanza por el neto de las apuestas reales.** La banca refleja lo que el usuario apostó de verdad en la mesa; el escalón refleja dónde estaría quien siguiera al motor. Son dos cosas distintas, y juntarlas significaba que apostar por fuera de la recomendación corría la progresión que la mesa muestra.
- **Estado de parar (2026-09-24).** Si la banca ya no cubre la apuesta base (`bankroll_exhausted`) o se alcanzó el límite de pérdida (`loss_limit_reached`), la mesa sigue abierta pero no acepta apuestas: el servidor las rechaza y la pantalla reemplaza la recomendación por la indicación de dejar de apostar, el resumen de la banca y los botones "Cerrar mesa" y "Abrir una mesa nueva". Si pasan las dos cosas, gana `bankroll_exhausted`. No hay cierre automático porque una sesión cerrada no deja deshacer su último número: si la banca se agotó por un error de ingreso, "Deshacer último" la restaura y el estado se levanta solo, ya que se deriva de la banca y no se guarda. Se pueden seguir anotando números; el motor sigue evaluando y guardando sus recomendaciones, porque el backtest mide al motor, no al usuario.
- **Con `NO_APOSTAR` ninguna progresión avanza y el saldo no cambia.** Cobrar un escalón por un giro que el motor pidió no jugar sería cobrar por una apuesta que no se hizo.
- **Resolución**: al llegar el siguiente resultado, la recomendación anterior se marca `HIT` o `MISS` y las progresiones se mueven con eso. Un `NO_BET` se queda en `PENDING` para siempre: no hubo nada que acertar ni que fallar.

#### Persistencia

`statistical_suggestions` **se escribe desde la Fase 3**, una fila por recomendación emitida — hasta el MVP estaba creada y vacía a propósito (§3.3). El motivo del cambio: `outcome` y `resolved_spin_id` son hechos del pasado que no se pueden re-simular, porque dependen de qué recomendó el motor con la fórmula de ese momento, no con la de hoy.

Antes de la primera fila se aplicó la alineación que §3.3 exigía: `chi_square_pvalue` pasó a `chi_square_pvalue_adjusted` y se agregaron `observed_ci_low` / `observed_ci_high`. Salieron `significance_score`, `strength` e `is_top3`, que describían el ranking top-3.

**El `NO_APOSTAR` también se guarda**, con los datos del mejor candidato: siempre hay uno, sólo que por debajo del umbral. Sin esa fila el backtest no podría comparar los giros en los que el motor habló con los que calló, que es la mitad de lo que §9 del comparativo pide medir.

Montos en **centavos** (`stake_cents`), nunca float, con la moneda explícita.

#### Qué muestra la pantalla

La vista principal de ruleta muestra una sola recomendación grande: estado (SEÑAL FUERTE / SEÑAL MEDIA / SIN SEÑAL) + mercado + fuerza interna + monto por gestión ("$X en cada docena" cuando el mercado cubre dos zonas). **Salieron de la vista principal** el ranking top-3 con porcentajes y el porcentaje de mesa como dato principal. La sección desplegable "¿Por qué recomienda esto?" aparece solo cuando hay recomendación, y desde el 2026-09-24 ya no lista "los demás mercados" con su banda: al lado de la jugada se leían como segundas apuestas. La API los sigue devolviendo en `candidates`.

La regla anti-falacia del jugador de §2 **se mantiene**, con un cambio de sitio: `theoretical_probability` y `observed_frequency_shrunk` siguen viajando siempre juntas en la respuesta de la API y se muestran en la sección desplegable "¿Por qué recomienda esto?", no en la tarjeta principal.

Dos textos obligatorios:

- Bajo el score: _"81/100 es la fuerza del criterio interno, no la probabilidad de acertar."_
- Al pie de la tarjeta, fijo: _"Recomendación generada a partir del análisis estadístico de los resultados registrados. No es una predicción."_

**El banner fijo de §0 se retiró de todas las pantallas** (decisión de producto del 2026-09-22): el carácter estadístico y no predictivo del producto está cubierto en los términos y condiciones. La línea al pie de la tarjeta es el recordatorio que queda en la vista de ruleta.

#### Lenguaje

Permitido: "Recomendación", "Apostar: …", "No apostar este giro", "Fuerza de señal", "Signal Score". Sigue prohibido: "predicción", "va a salir", "seguro", "garantizado", "infalible", "ventaja sobre la casa". En código: `recommendation`, `signal_score`, `signal_band`; nunca `prediction`.

#### Métricas internas (sólo admin)

`engine/backtest.py` (puro) más `scripts/backtest_recommendations.py` (CLI) y `GET /admin/recommendations/backtest`. Reporta número de recomendaciones, % de NO APOSTAR, aciertos y fallos, ROI con pagos reales (1:1, 2:1, y **1:2 para dos docenas** — se apuesta 1 unidad en cada docena, el sector acertado paga 2 y el otro se pierde, o sea +1 neto sobre 2 arriesgadas), resultado por unidad y caída máxima, todo desglosado por banda.

**La regla que hace que esto sirva de algo**: los pesos se fijaron mirando simulaciones de ruedas justas, no historiales concretos. El backtest corre sobre sesiones reales —fuera de muestra por construcción— y las ruedas simuladas quedan como línea base, donde el ROI tiene que quedarse en la ventaja de la casa. Si ahí apareciera una ventaja, sería un error de medición y no un hallazgo.

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
Pagos:     Wompi (Colombia) — fase 2 (en alcance); campos de DB preparados desde el MVP
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
      recommendation.py                  # catálogo de mercados, signal_score, decisión (§2.10)
      backtest.py                         # métricas del motor sobre historiales (§2.10)
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
  loss_limit,                          -- nullable; 0 < loss_limit <= bankroll_start (§2.8.3)
  stage_martingale, stage_two_sector,  -- un escalón por progresión (§2.10); la plana no tiene
  started_at, closed_at
)
   -- Desde la Fase 3 NO hay strategy_selected ni strategy_mode: la mesa muestra
   -- las tres progresiones a la vez y el usuario sigue la que quiera (§2.10).

spins (id, session_id, spin_index, result_value, source,
       stage_martingale_before, stage_two_sector_before, created_at)
   -- source: 'manual' (giro a giro) | 'initial_batch' (carga inicial al abrir la sesión)
   -- stage_*_before: escalones antes de resolver el giro, para deshacerlo (§2.10)

bets (id, session_id, spin_id, category, option_label, amount, followed_suggestion,
      status, won, payout, net_change, created_at, resolved_at)

statistical_suggestions (              -- una fila por recomendación emitida (§2.10)
  id, session_id, spin_id,
  decision,                               -- 'RECOMMEND' | 'NO_BET'
  market_key, category, option_label,
  signal_score, signal_band,              -- 'weak' (SIN SEÑAL) | 'medium' | 'strong'
  theoretical_probability, observed_frequency_shrunk, deviation,
  observed_ci_low, observed_ci_high,       -- intervalo de Wilson (§2.2)
  ev, chi_square_pvalue_adjusted,          -- null si el χ² no está activo
  stake_cents, currency,                   -- dinero en enteros; stake null con NO_BET
  outcome, resolved_spin_id,               -- 'PENDING' | 'HIT' | 'MISS'
  window_size_used, created_at
)

bankroll_suggestions (id, session_id, spin_id, strategy, suggested_bet, stage,
                       risk_warning, ruin_probability_estimate, created_at)

session_performance (            -- nuevo, soporta la auto-evaluación (2.7)
  id, session_id, total_suggestions, matched_suggestions,
  baseline_matched, updated_at
)
```

**Nota sobre `statistical_suggestions` y `session_performance`.** Las dos nacieron latentes: creadas y sin que nada las escribiera, con los endpoints recalculando desde los giros en cada llamada.

- **`statistical_suggestions` se escribe desde la Fase 3** (§2.10), una fila por recomendación emitida. El motivo: `outcome` y `resolved_spin_id` son hechos del pasado que no se pueden re-simular — dependen de qué recomendó el motor con la fórmula de ese momento, no con la de hoy. Antes de la primera fila se aplicó la alineación que esta nota exigía: `chi_square_pvalue` pasó a `chi_square_pvalue_adjusted` y se agregaron `observed_ci_low` / `observed_ci_high`.
- **`session_performance` sigue latente**, y por el motivo original: el motor es determinista, así que re-simular da el mismo resultado que haber acumulado fila a fila, y evita que un cambio de fórmula deje conteos viejos e incomparables en la base. Está explicado en `api/v1/suggestions.py`.

La recomendación vigente (`GET /sessions/:id/recommendation`) **sí se recalcula** en cada llamada, por lo mismo: leerla o recalcularla da igual, y recalcular evita servir una recomendación vieja si entretanto se deshizo un giro. Lo que se persiste es el histórico, no el estado.

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
Bankroll:   GET /sessions/:id/bankroll/suggestion   (monto del escalón, plan del giro y alertas, §2.8.1-2.8.2)
            GET /sessions/:id/bankroll/eligible-bets  GET /sessions/:id/bankroll/progression
            GET /bankroll/progression            (tabla previa, sin sesión)
Suggestions: GET /sessions/:id/suggestions/latest  GET /sessions/:id/suggestions/history
Recommend.:  GET /sessions/:id/recommendation          (qué apostar en el giro siguiente, §2.10)
             GET /sessions/:id/recommendation/history  (emitidas y cómo cerró cada una)
Admin:      POST /admin/games  PATCH /admin/games/:id  POST /admin/games/:id/variants
            PATCH /admin/games/:id/variants/:variant_id  GET /admin/users
            PATCH /admin/users/:id/access
            GET /admin/recommendations/backtest       (métricas internas, §2.10)
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

1. **Auth**: registro, login, refresh, perfil. Acceso inicial: `access_type` en `'trial' | 'invited' | 'full'` — sin pagos en el MVP; Wompi entra en la Fase 2.
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
   - Plan de banca a la vista en la mesa: siguiente paso de la progresión si el giro cierra en contra o a favor, y alertas de gestión de banca por severidad (§2.8.1-2.8.2).
   - Límite de pérdida opcional por sesión, que se puede bajar pero no subir con la sesión abierta (§2.8.3).
   - Registro de apuesta real (categoría + monto) y resolución automática win/loss al ingresar el siguiente número.
   - Auto-evaluación: tasa de coincidencia del motor vs. línea base ingenua, visible en vivo y en el resumen de cierre.

   > **Actualización 2026-09-23:** la vista de ruleta ya no muestra el panel de sugerencias top-3, las señales por categoría, la alerta de racha ni la tasa de coincidencia. Los endpoints (`/suggestions/latest`, `/streak`, `/performance`) y sus cálculos se mantienen; lo que cambió es que el cliente no los pinta. Las frecuencias y probabilidades teóricas de la recomendación siguen visibles en "¿Por qué recomienda esto?".

### Fase 2 (en alcance, decidido el 2026-09-17)

- **Pagos/suscripciones con Wompi.** El MVP dejó `subscriptions` y `payment_events` con el modelo de datos preparado y sin lógica; la Fase 2 los implementa. Reglas: firma (integridad de la transacción y checksum del webhook) verificada contra la documentación oficial vigente de Wompi y nunca de memoria; el webhook no es fuente de verdad por sí solo, se reconsulta la transacción contra la API antes de mover `subscriptions.status` o `users.access_type`; idempotencia por `provider_event_id`, que es único, porque los webhooks se reintentan; montos en centavos con moneda explícita; secretos solo por variable de entorno; acceso decidido siempre en el servidor a partir de `access_type` y `current_period_end`.
- **Señales avanzadas del motor** (§2.9): entran una por una, solo cuando el usuario las pida explícitamente.

### Fase 3 (en alcance, decidido el 2026-09-22)

**El producto pasa de analizador descriptivo a motor de recomendación** (§2.10). Después de cada giro, la pantalla de ruleta dice qué apostar o que no se apueste, con un Signal Score 0-100 y su banda. Las estadísticas pasan a ser el respaldo.

Lo que cambia respecto del MVP:

- Sale de la vista principal el ranking top-3 con porcentajes y el porcentaje de mesa como dato principal. Siguen disponibles, plegados.
- La sesión ya no elige una progresión al crearse: la mesa muestra las tres (plana, martingala, recuperación de dos sectores) y el usuario sigue la que quiera. **D'Alembert y Fibonacci salen del producto.**
- `statistical_suggestions` se empieza a escribir; las progresiones avanzan con el cierre de la recomendación, no con las apuestas reales.
- El banner fijo de §0 se retira de todas las pantallas.
- Métricas internas de validación (§9 del comparativo) en el panel de admin.

Fuera de esta fase, igual que antes: las señales avanzadas de §2.9, el builder visual, los dados y el CSV. No se toca nada de pagos ni de Wompi.

Documento que define la fase: `docs/reference/Comparativo_Software_Actual_vs_Software_Deseado.md`.

### Fuera de scope (post-MVP, ya identificado)

- Builder visual de categorías en el admin (se usa formulario simple primero).
- Señales avanzadas: transición condicional, k-gramas, ciclo, señales de pleno (sección 2.9) — fuera del MVP; pasan a la Fase 2 solo cuando el usuario pida cada una.
- Juego de dados u otros — el modelo ya lo soporta, pero no se construye la UI/seed en el MVP.
- Exportar CSV, migración de datos locales, notificaciones.

---

## 5. Diseños de pantalla

Se agregará una carpeta `docs/design/` con mockups de: login/registro y vista de juego de ruleta. Claude Code debe tratarlos como especificación visual de referencia — implementar fielmente layout, jerarquía de información y componentes (panel top-3, banner de disclaimer, input de número, tarjeta de sugerencia de bankroll) salvo que el stack (Next.js + Tailwind, ver `frontend-design` en CLAUDE.md) requiera adaptaciones menores de implementación.
