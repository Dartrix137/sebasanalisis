# Ruleta Analyzer Pro — Guía Completa

## Cómo funciona el análisis estadístico de la ruleta y cómo funciona la aplicación

> Documento de referencia en español. Parte I explica la estadística de la ruleta y las herramientas matemáticas que usa el motor. Parte II explica la aplicación real: su arquitectura, el flujo de datos, cada señal, cómo se eligen las apuestas y cómo interpretar la interfaz.

---

# PARTE I — La estadística de la ruleta

## 1. El juego: ruleta europea

La ruleta europea tiene **37 casillas**: los números 1 al 36 más el 0. Cada casilla tiene un color fijo:

- **18 números rojos**: 1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36
- **18 números negros**: 2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35
- **1 cero** (verde): ni rojo ni negro, no pertenece a ninguna docena, columna ni mitad

Además del color, los números se agrupan de tres formas más:

- **Docenas**: D1 = 1–12, D2 = 13–24, D3 = 25–36
- **Columnas** (según el resto de dividir entre 3): C1 = n%3=1, C2 = n%3=2, C3 = n%3=0
- **Mitades**: BAJA = 1–18, ALTA = 19–36

Un **pleno** es apostar a un número exacto. Todas las apuestas de esta app son de esos cinco tipos: color, docena, columna, mitad y pleno (este último solo en circunstancias muy especiales).

## 2. Probabilidades justas y pagos

La "probabilidad justa" es la frecuencia con la que cada apuesta ganaría en una ruleta perfecta, sin defectos. Se calcula simplemente contando casillas:

| Apuesta | Casillas ganadoras | Probabilidad justa | Pago del casino |
|---|---|---|---|
| Color (rojo o negro) | 18 de 37 | **48.65%** | 1 a 1 (ganas lo apostado) |
| Mitad (alta o baja) | 18 de 37 | **48.65%** | 1 a 1 |
| Docena | 12 de 37 | **32.43%** | 2 a 1 |
| Columna | 12 de 37 | **32.43%** | 2 a 1 |
| Pleno | 1 de 37 | **2.70%** | 35 a 1 |
| Cero (para apuestas externas) | 1 de 37 | 2.70% | — (hace perder todo lo externo) |

Un detalle importante: **el cero no es neutral, es la ventaja de la casa**. Si no existiera el cero, el color sería 18/36 = 50% exacto y el juego sería perfectamente equitativo (a largo plazo, nadie ganaría ni perdería).

## 3. La ventaja de la casa: de dónde sale el famoso 2.70%

El valor esperado (EV) de una apuesta es el promedio matemático de lo que ganarás o perderás por cada unidad apostada, si repitieras la apuesta infinitas veces:

```
EV = (probabilidad de ganar × ganancia neta) + (probabilidad de perder × (−1))
```

Calculemos para el color (pago 1 a 1):

```
EV = (18/37 × 1) + (19/37 × (−1)) = 18/37 − 19/37 = −1/37 = −2.70%
```

Para la docena (pago 2 a 1):

```
EV = (12/37 × 2) + (25/37 × (−1)) = 24/37 − 25/37 = −1/37 = −2.70%
```

Para el pleno (pago 35 a 1):

```
EV = (1/37 × 35) + (36/37 × (−1)) = 35/37 − 36/37 = −1/37 = −2.70%
```

**Conclusión clave:** en la ruleta europea, TODAS las apuestas tienen exactamente la misma desventaja matemática (−2.70%). No hay apuesta "más segura" ni "más rentable" en una ruleta perfecta: por cada 100 unidades apostadas, el casino espera quedarse con 2.70 a largo plazo. Ningún sistema de progresión (martingala, Fibonacci, etc.) cambia este número — solo cambia cómo se distribuyen las pérdidas.

## 4. Independencia y la falacia del jugador

En una ruleta perfecta, cada giro es **independiente**: la ruleta no tiene memoria. El resultado anterior no altera la probabilidad del siguiente. Esto desmonta la intuición más común del jugador:

> **Falacia del jugador:** "Ha salido rojo 8 veces seguidas, entonces negro ahora 'debe' salir para equilibrar."
> **Realidad:** la probabilidad de negro sigue siendo exactamente 18/37 (48.65%). La rueda no sabe cuántas veces salió rojo.

La ley de los grandes números NO dice que las frecuencias se corrigen a corto plazo: dice que a MUY largo plazo la proporción global converge a la justa, sin que eso ayude a ninguna tirada individual.

**Por qué esta app no cae en esa trampa:** el motor nunca apuesta a "lo que falta por salir". Al contrario: detecta cuando un resultado sale MÁS de lo esperado y evalúa si esa desviación es estadísticamente real (sesgo físico) o simple ruido. Su lógica es la opuesta a la falacia del jugador: persigue desviaciones persistentes, no reversiones imaginarias.

## 5. Dónde puede existir margen real

Si la ruleta fuera matemáticamente perfecta, la estadística no podría ayudarte y la única estrategia óptima sería no jugar. Pero las ruletas son objetos físicos, y en la práctica surgen desviaciones reales:

1. **Sesgo de rueda:** imperfecciones de fabricación, desgaste, nivelación imperfecta o deflectores dañados hacen que ciertas zonas de la rueda ganen más de lo esperado. Históricamente demostrable (el caso clásico: Gonzalo García-Pelayo en los años 90 ganó millones midiendo ruletas reales de casinos).
2. **Firma del crupier:** algunos crupieres lanzan la bola con ángulos y fuerza tan consistentes que ciertas zonas reciben la bola con más frecuencia mientras duran en la mesa.
3. **Desgaste de componentes:** la bola, el cono y los deflectores cambian con el uso y pueden introducir preferencias sutiles.

Estos fenómenos comparten una característica crucial: **son persistentes mientras las condiciones físicas no cambien**. Eso es exactamente lo que un análisis estadístico puede detectar: no adivinar el futuro, sino **medir si el pasado reciente se desvía de lo esperado con significancia estadística**. Y también explica dos reglas de la app: el análisis pondera más lo reciente (las condiciones cambian) y las sesiones se separan por mesa (el sesgo de una mesa no aplica a otra).

**El corolario honesto:** si la mesa no tiene ningún sesgo real, el mejor "pronóstico" posible es el justo (48.65% / 32.43% / 2.70%), ninguna estrategia supera el −2.70%, y la app debería usarse solo como registro. El motor está diseñado para señalar cuándo los datos NO respaldan ninguna ventaja — de hecho la mayoría de las veces será así.

## 6. Las herramientas estadísticas del motor

El motor combina siete herramientas matemáticas. Estas son sus explicaciones completas:

### 6.1 Probabilidad condicional — P(siguiente | actual)

En lugar de preguntar "¿cuánto salió NEGRO en total?", pregunta "**después de que salió ROJO, qué salió después?**". Es la probabilidad de un evento B dado que ocurrió el evento A:

```
P(B | A) = veces que ocurrió "A y luego B" / veces que ocurrió A
```

Ejemplo: si tras 11 ROJOs anteriores el sucesor fue NEGRO 7 veces, la estimación cruda es P(NEGRO|ROJO) = 7/11 = 63.6%, muy por encima del 48.65% justo. El motor la usa en la señal TRANSICIÓN y en PLENO_MARKOV. La pregunta clave es siempre si esa diferencia es estadísticamente sólida (por eso va acompañada de shrinkage y mínimos de muestra).

### 6.2 Ponderación por recencia — el decaimiento exponencial

No todos los números históricos valen lo mismo: los de hace 5 tiradas reflejan la mesa actual; los de hace 200, probablemente otra condición (otro crupier, otra bola). El motor asigna a cada observación un **peso que decae exponencialmente con su antigüedad**:

```
peso(edad) = 0.969^edad      (vida media ≈ 22 tiradas)
```

La "vida media de 22 tiradas" significa que una observación pierde la mitad de su influencia cada 22 números de antigüedad:

| Antigüedad (tiradas) | Peso que conserva |
|---|---|
| 0 (última) | 100% |
| 10 | 73% |
| 22 | 50% |
| 44 | 25% |
| 66 | 12.5% |
| 100 | 4.3% |
| 200 | 0.2% |

Efecto práctico: la **memoria útil del motor es de unos 60–80 números**; todo lo anterior se desvanece solo. Esto responde una pregunta frecuente: *"¿me confunde tener 50 números registrados?"* — No: el motor ya está diseñado para que los viejos pesen casi nada. Es además la razón técnica por la que el límite de 300 números por sesión es más que suficiente.

### 6.3 Shrinkage bayesiano — no fiarse de muestras chicas

Si una moneda sale "cara" 3 de 4 veces, ¿cara tiene 75% de probabilidad? Obviamente no: 4 lanzamientos casi no informan nada. El motor enfrenta este problema constantemente ("NEGRO salió 7 de 11 veces tras ROJO") y lo responde con **shrinkage**: mezcla la observación cruda con la probabilidad justa, con una fuerza α que depende de cuántos datos hay:

```
p̂ = (casos_favorables + α × prob_justa) / (total_casos + α)
```

La estimación p̂ (p-gorro) se acerca a la proporción observada cuando hay muchos datos, y se queda cerca de la probabilidad justa cuando hay pocos. Ejemplo real del motor (α = 8, prob justa 48.65%):

```
Crudo:      7 de 11  →  63.6%  (¡demasiado atrevido para 11 casos!)
Shrinkage:  (7 + 8×0.4865) / (11 + 8)  =  10.89 / 19  =  57.3%  (prudente)
```

Con 50 casos en vez de 11, el mismo α apenas movería la estimación. Así el motor solo se atreve cuando la evidencia lo respalda.

### 6.4 Prueba χ² (chi-cuadrado) — ¿la frecuencia global está desviada?

El χ² mide si las frecuencias observadas de TODAS las categorías se desvían más de lo que el azar explicaría:

```
χ² = Σ (observado − esperado)² / esperado        para cada categoría
```

Se compara contra su distribución teórica (con grados de libertad = categorías − 1) y produce un **p-valor**: la probabilidad de ver una desviación así de grande si la ruleta fuera perfecta. Convención estadística: p < 0.05 = "significativo".

Requisitos del motor para la señal SESGO: **mínimo 36 números** en la sesión y p < 0.05. Ejemplo de evidencia que produce: *"DOCENA 2 salió 15 de 40 (37.5%) vs 32.4% esperado (χ² p=0.03)"* — es decir, una desviación que el azan explicaría solo el 3% de las veces. Nota importante: es la única señal que usa TODA la sesión sin decaimiento (los sesgos físicos reales necesitan volumen para detectarse), por lo que también es la más sensible a condiciones ya cambiadas.

### 6.5 Cola binomial — rachas y alternancia

Para eventos "sí/no" (¿cambió el color?, ¿continuó la racha?) se usa la **distribución binomial** y su cola superior: la probabilidad de observar X o más casos extremos si la probabilidad fuera la justa. El motor la aplica en:

- **ALTERNANCIA:** en la ventana reciente, ¿la tasa de cambio entre tiradas se aleja más de 2 desviaciones estándar de lo esperado?
- **PLENO_CALIENTE:** ¿un número salió tantas veces que p < 0.01 bajo la hipótesis de uniformidad?

### 6.6 k-gramas — patrones de secuencia con memoria corta

Un k-grama es una secuencia de k resultados consecutivos. El motor toma los últimos k resultados como "sufijo" y busca en el historial apariciones idénticas de ese patrón, para ver **qué vino después**:

```
Sufijo actual: ROJO → NEGRO → ROJO   (k = 3)
Historial:     ... ROJO → NEGRO → ROJO | NEGRO
               ... ROJO → NEGRO → ROJO | NEGRO
               ... ROJO → NEGRO → ROJO | ROJO
→ "El patrón ROJO→NEGRO→ROJO apareció 3 veces; siguió NEGRO en 2 de 3"
```

Con pocas tiradas usa patrones largos (k=3) solo si se repiten; si no hay coincidencias suficientes, cae a k=2. Las coincidencias también se ponderan por recencia. Es la señal PATRÓN (y su versión de números exactos, PLENO_CICLO).

### 6.7 Valor esperado de la apuesta (EV) — el filtro final

Cada predicción del motor se traduce a EV en unidades apostadas:

```
EV = p̂ × pago − (1 − p̂)
```

Ejemplos: color con p̂=55% → EV = 0.55×1 − 0.45 = **+0.10** (10 centavos por cada unidad). Docena con p̂=36% → EV = 0.36×2 − 0.64 = **+0.08**. Pleno con p̂=5% → EV = 0.05×35 − 0.95 = **+0.80**. El motor solo considera candidatas con EV > 0.03, y califica su fuerza: FUERTE si EV ≥ 0.15 con lift ≥ 1.12, MEDIA si EV ≥ 0.06, DEBIL por debajo.

## 7. ¿Más historial = mejores predicciones?

No exactamente, y entender por qué evita errores de uso:

- **Para transiciones, patrones, rachas y alternancia:** más historial NO molesta (el decaimiento lo desactiva), pero tampoco ayuda mucho más allá de ~80 tiradas. El beneficio real llega en los primeros 20–30 números, cuando las señales alcanzan sus mínimos de muestra.
- **Para el χ² (SESGO):** sí ayuda: es un acumulador global. Con 40 números puede activarse; con 100+ su veredicto es más firme.
- **El riesgo real es lo contrario:** datos VIEJOS de otra condición de mesa. La defensa es doble: el decaimiento (para las señales condicionales) y el sistema de sesiones (para el χ²): cuando cambia la mesa o el crupier, se cierra la sesión y se abre una nueva. Ese es el "reinicio limpio" correcto — no borrar por borrar.
- **Mínimos de arranque:** el motor necesita 5 números para encenderse y recomienda 10+. Con menos de eso, sus señales no tienen base.

## 8. Los límites honestos del análisis

Ningún motor —incluido este— puede predecir una ruleta perfecta. Lo que sí puede hacer:

1. **Cuantificar la evidencia**: decirte "esta mesa muestra una desviación que el azar explicaría solo el 3% de las veces" o "aquí no hay nada aprovechable".
2. **Evitar el auto-engaño**: el shrinkage, los mínimos de muestra y los p-valores existen precisamente para no confundir ruido con patrón.
3. **Medirse a sí mismo**: la app compara su precisión real acumulada contra una línea base ingenua (repetir el último color). Si el motor no supera a esa línea base en tu historial, la conclusión honesta es que la mesa no presenta estructura explotable.

El uso correcto de la herramienta es estadístico y disciplinado: registrar con fidelidad, apostar solo cuando el motor emite señales de calidad, y aceptar que las rachas malas existen incluso con ventaja real.

---

# PARTE II — Cómo funciona la aplicación

## 9. Vista general y arquitectura

La app es una **aplicación web de una sola página** construida con Next.js 16 (TypeScript). Enfoque de diseño: todo el peso intelectual vive en un **motor puro de análisis** y el resto del sistema lo consume.

```
src/
  lib/
    roulette-v3.ts      ⭐ EL MOTOR: matemática pura, sin React, sin base de datos, sin red
    stats-v3.ts         verificación de aciertos + métricas + respaldo local
    auth.ts             cuentas: hash de contraseñas, tokens firmados
    db.ts               cliente de base de datos (Prisma + SQLite)
  app/
    page.tsx            toda la interfaz (login + plataforma)
    api/…               rutas de servidor: auth, sesiones, análisis de imagen
  prisma/schema.prisma  tablas User y SesionRuleta
```

**Por qué el motor es un módulo aislado:** puede probarse matemáticamente sin abrir el navegador, garantiza que la interfaz nunca "contamina" el análisis, y hace auditable cualquier cambio futuro. La interfaz solo le entrega la secuencia de números y muestra lo que él devuelve.

**Persistencia en dos niveles:** cada usuario tiene sus sesiones guardadas en el servidor (con respaldo local en el navegador por si falla la conexión), y el motor vive en el cliente — el análisis corre en tu propio navegador, número a número, sin enviar la secuencia a ningún servicio externo.

## 10. El flujo de un número, paso a paso

Así es el viaje completo de un número desde que lo ves en la mesa hasta que aparece una recomendación:

```
 1. ENTRADA          teclado 0–36 | escritura manual | pegar secuencia | foto del marcador (IA)
 2. VALIDACIÓN       entero entre 0 y 36, máximo 300 números por sesión
 3. SECUENCIA        se agrega AL FINAL (el orden cronológico es sagrado: nunca se reordena)
 4. VERIFICACIÓN     si había predicciones pendientes, se evalúan contra este número (acierto/fallo)
 5. ANÁLISIS         el motor mapea la secuencia a 5 dimensiones y genera señales
 6. FUSIÓN           señales de cada dimensión → un candidato por dimensión
 7. SELECCIÓN        filtro de calidad → las 2–3 mejores apuestas (máx. 1 pleno)
 8. UI               tarjetas de predicción + paneles de estadísticas actualizados
 9. GUARDADO         automático con retardo de 800 ms al servidor + respaldo local
```

Los pasos 4 a 8 ocurren en milisegundos: cada vez que agregas un número, la recomendación se recalcula completa sobre la secuencia entera (ponderada por recencia).

## 11. Las 9 señales del motor

El motor trabaja en 5 dimensiones: COLOR, DOCENA, COLUMNA, MITAD (llamadas "externas") y PLENO. Cada dimensión convierte la secuencia de números a su propio alfabeto (p. ej. `7 → NEGRO / D1 / C1 / BAJA`) y sobre él busca estas señales:

| # | Señal | Qué detecta | Requisitos mínimos |
|---|---|---|---|
| 1 | **TRANSICIÓN** | P(siguiente \| último resultado) anómala | ≥6 tiradas, ≥4 ocurrencias del estado actual, mejor sucesor repetido ≥2 veces |
| 2 | **PATRÓN (k-grama)** | el último patrón de 2–3 resultados ya ocurrió y suele repetir su continuación | ≥3 coincidencias (k=3) o ≥4 (k=2) |
| 3 | **RACHA** | rachas de longitud ≥4 que históricamente continúan o se rompen más de lo normal | ≥4 rachas comparables |
| 4 | **ALTERNANCIA** | la tasa de cambio (cambia/repite) en la ventana reciente se desvía >2σ de lo esperado | ventana de 4×(nº de clases) tiradas |
| 5 | **CICLO** | periodicidad en docenas/columnas (D1→D2→D3→D1…) | ≥3 ciclos coincidentes en las últimas 12 |
| 6 | **SESGO χ²** | desviación de frecuencia global estadísticamente significativa | ≥36 tiradas, p<0.05 |
| 7 | **PLENO_MARKOV** | un número concreto suele ir seguido de otro número concreto | ≥3 ocurrencias, sucesor ≥2 veces |
| 8 | **PLENO_CICLO** | una secuencia exacta de 3–4 números se repite y siempre sigue el mismo número | ≥2 coincidencias exactas |
| 9 | **PLENO_CALIENTE** | un número sale con frecuencia extremadamente anómala | ≥40 tiradas, ≥4 apariciones, p<0.01 (binomial) |

Cada señal produce un objeto con: la apuesta sugerida, la probabilidad estimada (con shrinkage), la probabilidad justa, las muestras que la respaldan y una **evidencia en texto legible** — la frase que luego verás en la tarjeta, p. ej.: *"Después de ROJO salió NEGRO 7 de 11 veces (64%)"* o *"La secuencia [8, 27, 13] apareció 3 veces y siempre siguió el 36"*.

Las señales de plenos tienen barreras extra: sus probabilidades estimadas se recortan con techos duros (20% para ciclo, 15% para caliente) para que nunca presenten un pleno como "seguro" — la probabilidad justa de un pleno es 2.7% y aunque la evidencia sea notable, la estimación se mantiene prudente.

## 12. De señales a apuestas: fusión y selección

### 12.1 Fusión por dimensión

Dentro de cada dimensión pueden activarse varias señales a la vez. El motor las **agrupa por resultado predicho** y calcula un puntaje:

```
score = Σ  p̂ᵢ × (0.6 + 0.4 × min(1, muestrasᵢ/8))
```

Es decir: cada señal aporta su probabilidad, con más peso cuantas más muestras la respalden (el factor crece hasta 1.0 con 8 muestras). El grupo con mayor score gana la dimensión.

**Detectar contradicciones:** si el segundo grupo alcanza al menos el 85% del score del primero (p. ej. una señal fuerte por D2 y otra casi igual de fuerte por D3), el motor lo interpreta como señales contradictorias: reduce la probabilidad estimada en 4 puntos (nunca por debajo de la justa) y añade la nota *"Señales contradictorias en esta dimensión: confianza reducida"*.

**Bonus por acuerdo:** al construir la predicción final, si varias señales de tipos distintos coinciden en el mismo resultado, se suma un pequeño bonus de probabilidad (1.5 puntos por tipo adicional de señal que concuerda). Dos evidencias independientes apuntando lo mismo es más creíble que una sola.

### 12.2 El filtro de calidad

Los candidatos pasan por un filtro estricto; solo se consideran apuestas:

- **EV > 0.03** (la apuesta debe tener valor esperado positivo real tras el análisis)
- **≥3 muestras** que respalden la señal (los plenos están exentos de este mínimo porque ya superaron sus propias barreras a nivel de señal)
- **Fuerza ≠ DEBIL**

### 12.3 La selección final: 2–3 apuestas

- Los que pasan el filtro se ordenan por EV (y luego por muestras).
- Se eligen **hasta 3** como máximo, con la regla de que **solo 1 puede ser pleno**.
- Si no hay suficientes candidatos de calidad, la app puede **completar hasta 2 con señales débiles honestas** — pero siempre etiquetadas como DEBIL para que las distingas. Nunca presenta una apuesta débil disfrazada de segura.
- Con menos de 5 números, no hay análisis: la app lo avisa ("Agrega más números").

Así, en una mesa sin estructura, verás pocas tarjetas o tarjetas DEBIL; en una mesa con desviaciones reales, aparecen 2–3 señales FUERTE/MEDIA consistentes entre sí. La interfaz también muestra el **estado de cada dimensión** (con datos / señal detectada / sin patrón) para transparencia total.

## 13. Cómo leer una tarjeta de predicción

Cada tarjeta muestra los campos que necesitas para decidir:

| Campo | Qué significa | Cómo usarlo |
|---|---|---|
| **Tipo y apuesta** | "Color — NEGRO", "Docena — 2", "Pleno — 17" | La apuesta concreta sugerida |
| **Prob. estimada vs justa** | p̂ frente a pJ | La brecha es la ventaja detectada; 55% vs 48.6% en color ya es interesante |
| **Lift** | p̂ / pJ | >1.12 junto a EV ≥ 0.15 es FUERTE |
| **EV** | valor esperado por unidad apostada | El criterio de calidad principal: +0.10 = 10% de ventaja teórica |
| **Fuerza** | FUERTE / MEDIA / DEBIL | Resumen del motor. Apuesta solo FUERTE/MEDIA si buscas máxima exigencia |
| **Muestras** | casos que respaldan la señal | Más muestras = evidencia más estable; desconfía de señales con 3–4 |
| **Evidencias** | hasta 2 frases citando los datos | Leelas siempre: son el "por qué" de la apuesta |

## 14. Verificación y auto-evaluación: el control de honestidad

La app no solo recomienda: **se califica a sí misma**.

1. Cuando emites predicciones y llega el siguiente número, cada predicción pendiente se evalúa automáticamente: ¿acertó? (el CERO hace fallar toda apuesta externa).
2. Cada verificación queda registrada en el historial de la sesión con su tipo de apuesta.
3. Los paneles calculan: **precisión del motor** (aciertos/total) desglosada por tipo de apuesta, y la **precisión de la línea base trivial** — un "rival tonto" que siempre repite el último color ganador.
4. La comparación es el examen de honestidad: si tu motor no supera a la línea base trivial a lo largo de decenas de verificaciones, la mesa no tiene estructura explotable y las "señales" son ruido. El panel global "Rendimiento histórico" agrega todas tus sesiones para dar ese veredicto a largo plazo.

Puedes deshacer el último número (junto con la verificación que generó) si te equivocaste al ingresarlo.

## 15. Sesiones de mesa

Una **sesión** es el registro de una mesa concreta (p. ej. "Ruleta 1 – viernes noche"). El motor de sesiones:

- **Nueva / renombrar / eliminar** sesiones desde la tarjeta "Sesiones de mesa" (con confirmación antes de eliminar).
- **Cambio de sesión**: guarda automáticamente la activa antes de cargar otra.
- **Guardado automático**: 800 ms después de cada número o verificación, la sesión va al servidor; el indicador del encabezado muestra "Guardado ✓ / Guardando… / Sin conexión". Si falla, tus datos siguen a salvo en el respaldo local y se reintenta con el próximo número.
- **Migración automática**: la primera vez que inicias sesión con una cuenta nueva, el progreso que tenías localmente se sube al servidor.
- **Límite**: 300 números por sesión (más que la memoria efectiva del motor, ver §6.2).

**La regla estadística de uso:** una sesión = una condición de mesa. Cambió la mesa o el crupier → nueva sesión. Así el χ² y las transiciones no se contaminan con datos de otra realidad física.

## 16. Lectura de imagen con IA (capturas del marcador)

El apartado "Extraer de captura (IA)" te evita teclear: sube una foto del marcador (marquee) de la mesa y una IA de visión extrae los números del historial visible.

Cómo funciona por dentro:

1. Validas tipo y tamaño (máx. 8 MB) en el navegador.
2. La imagen viaja a la ruta `/api/analyze`, que la envía a un modelo de visión con la instrucción de extraer solo los números del marquee, **del más reciente al más antiguo**, y responder un array JSON.
3. La respuesta se limpia con tres estrategias de parseo tolerante (JSON con clave `numbers` → cualquier array → búsqueda con expresión regular de números válidos), se deduplica conservando el orden, y se exige un mínimo de 3 números.
4. **Detalle crítico:** la IA devuelve los números en orden "más reciente primero", pero la app necesita cronológico (más antiguo primero). La ruta los **invierte antes de responder**, para que entren exactamente por el mismo camino que si los teclearas.
5. Tú confirmas con dos opciones: **"Reemplazar secuencia"** (empieza de cero con esos números) o **"Agregar al final"** (se suman después de los que ya tenías). Nada se modifica hasta que confirmas.

## 17. Cuentas, seguridad y datos

- **Cada usuario solo ve sus sesiones**: toda consulta filtra por el dueño de la cuenta. Ningún otro usuario puede acceder a tus datos por mucho que conozca el identificador.
- **Contraseñas**: nunca se almacenan — se guarda un hash scrypt con sal aleatoria única por usuario y comparación en tiempo constante.
- **Sesión de cuenta**: token firmado (HMAC-SHA256, 30 días) entregado de dos formas simultáneas — cookie httpOnly y token Bearer en cabecera — para que funcione tanto en acceso directo como incrustado en chats/previews donde los navegadores bloquean cookies.
- **Protecciones**: límite de intentos de acceso (8 por combinación IP+correo en 10 minutos), mensajes genéricos que no revelan si un correo existe, validación de todos los payloads.
- **Exportar CSV**: cada sesión se descarga como archivo con BOM UTF-8 (apertura limpia en Excel), una fila por número (orden, número, color, docena, columna, mitad) y el bloque de verificaciones de predicciones.

## 18. Guía práctica en la mesa

1. **Al sentarte:** crea una sesión nueva con nombre de la mesa (o retoma una si es la misma mesa y crupier del mismo día).
2. **Registra todo:** cada número que sale, en el orden exacto. La foto del marcador ayuda a arrancar rápido con el histórico visible; después, número a número.
3. **Paciencia estadística:** con menos de 10–15 números el motor apenas tiene evidencia — es normal que muestre poco. Su valor aparece con volumen.
4. **Lee las tarjetas completas:** no solo la apuesta, también fuerza, muestras y evidencias. Dos señales coincidentes con 10+ muestras valen más que una con 3.
5. **Apuesta con criterio:** si tu disciplina es máxima, actúa solo con tarjetas FUERTE. Las MEDIA son situaciones intermedias; las DEBIL son información, no recomendación.
6. **Verifica el veredicto global:** tras decenas de predicciones, compara la precisión del motor contra la línea base trivial en el panel histórico. Ese número es tu brújula honesta sobre esa mesa.
7. **Al levantarte o cambiar de mesa:** nueva sesión. Deja la antigua como registro — su CSV siempre estará disponible.

## 19. Preguntas frecuentes

**¿Tener 50 números me confunde las predicciones?**
No. Las señales condicionales ponderan por recencia: a partir de ~80 tiradas de antigüedad los datos pesan menos del 10%. El único análisis de memoria larga es el χ², que precisamente necesita acumular. Lo que sí contamina es mezclar MESAS distintas en una sesión — para eso están las sesiones separadas.

**¿Por qué a veces no muestra ninguna predicción?**
Porque no hay señales que pasen el mínimo de evidencia. Es el comportamiento correcto: el motor no rellena por rellenar (salvo señales DEBIL claramente etiquetadas). Menos predicciones con más calidad es el diseño.

**¿Puede garantizarme ganancias?**
No, y ninguna herramienta honesta puede. En una mesa sin sesgo real, matemáticamente nada supera el −2.70%. La app maximiza tus probabilidades cuando EXISTE estructura real, te cuantifica la evidencia y te mide los resultados — la decisión de apostar y cuánto es siempre tuya.

**¿Por qué el pleno aparece tan poco?**
Por diseño: paga 35 a 1 pero su probabilidad justa es 2.7%. Sus señales necesitan coincidencias exactas repetidas o frecuencias anómalas con p<0.01, y aun así las probabilidades estimadas se recortan con techos de 15–20%. Máximo 1 pleno por predicción.

**¿Qué pasa si me equivoco al digitar un número?**
El botón Deshacer retira el último número junto con la verificación que haya generado. El CSV y el guardado se recalculan en el siguiente guardado.

---

*Ruleta Analyzer Pro — herramienta de análisis estadístico. El juego conlleva riesgo; ninguna predicción garantiza resultados. Juega con responsabilidad.*

