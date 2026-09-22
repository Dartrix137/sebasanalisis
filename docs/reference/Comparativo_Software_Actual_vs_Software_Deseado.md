# COMPARATIVO FUNCIONAL

## SOFTWARE ACTUAL vs. SOFTWARE QUE SE QUIERE DESARROLLAR

*Documento para el equipo de ingeniería*

---

## 1. Qué hace actualmente el software

Según el prototipo revisado, el software actual funciona principalmente como un **analizador estadístico**. El usuario registra resultados y la interfaz muestra información sobre lo que ha ocurrido, pero no transforma de forma clara ese análisis en una decisión concreta para el siguiente giro.

| Elemento actual | Qué hace |
|---|---|
| Frecuencia observada | Muestra qué porcentaje de veces ha salido una categoría en la muestra. |
| Probabilidad / base de mesa | Compara la frecuencia registrada con una referencia matemática configurada. |
| Fuerza tipo Media/Débil | Clasifica ciertas estadísticas, pero no le dice claramente al usuario qué jugar. |
| Rachas | Informa secuencias recientes y aclara que una racha no cambia por sí sola la probabilidad del próximo giro. |
| Gestión de apuesta | Permite trabajar con importe, saldo y métodos de gestión/progresión. |
| Resultado final | El cliente todavía debe interpretar los datos y decidir por su cuenta qué apostar. |

> **PROBLEMA PRINCIPAL DEL PROTOTIPO:** puede mostrar, por ejemplo, que Alto (19-36) ha aparecido con determinada frecuencia o que una docena está débil, pero el cliente todavía queda preguntándose: *"¿Entonces qué apuesto en el próximo giro?"*

---

## 2. Qué se quiere en el producto final

El producto final debe conservar las estadísticas actuales, pero añadir encima un **MOTOR DE DECISIÓN / RECOMENDACIÓN**. Después de cada nuevo resultado, el sistema debe analizar automáticamente los mercados disponibles y entregar una recomendación clara para el giro siguiente, o indicar que no existe una señal suficiente.

La recomendación no se presenta como una predicción segura ni como una garantía. Es una sugerencia generada por las reglas estadísticas del software.

> **RECOMENDACIÓN PARA EL SIGUIENTE GIRO**
>
> **APOSTAR:** 1.ª + 2.ª DOCENA
>
> - **Fuerza de señal:** 81/100 — FUERTE
> - **Gestión elegida:** Martingala
> - **Apuesta indicada:** $XXX en cada docena
>
> *Nota: 81/100 representa fuerza del criterio interno; no significa 81% de probabilidad de acertar.*

Cuando no exista una señal suficiente:

> **NO APOSTAR ESTE GIRO**
>
> Esperar el siguiente resultado y volver a analizar.

---

## 3. Configuración que debe conservarse

El usuario debe seguir pudiendo elegir **Ruleta Europea** o **Ruleta Americana**. Esa elección debe cambiar automáticamente probabilidades teóricas, tratamiento del 0/00, cobertura y cálculos. También debe poder escoger el método de gestión disponible: **Martingala, Factores, Plan** u otros.

La selección del método de gestión debe ocurrir **aparte del análisis**. Primero el software decide qué recomendar; después el método elegido calcula cuánto apostar.

---

## 4. Mercados que el motor debe evaluar

El sistema debe analizar simultáneamente:

- Rojo / Negro
- Par / Impar
- Bajo (1-18) / Alto (19-36)
- 1.ª / 2.ª / 3.ª docena
- Columnas 1 / 2 / 3
- Combinaciones permitidas como **dos docenas** o **dos columnas**

El motor debe poder recomendar cualquiera de estas alternativas cuando cumpla los criterios definidos.

---

## 5. Diferencia esencial entre ambos productos

| SOFTWARE ACTUAL | SOFTWARE DESEADO |
|---|---|
| Describe lo que ya ocurrió. | Analiza lo ocurrido y genera una recomendación para el próximo giro. |
| Muestra porcentajes y estadísticas. | Muestra primero qué jugar y después explica las estadísticas. |
| El cliente interpreta la información. | El motor interpreta sus propias reglas y entrega una decisión. |
| Puede mostrar Media/Débil. | Debe mostrar recomendación + fuerza de señal. |
| No queda claro qué apostar. | Debe decir: Negro, Alto, 2.ª docena, dos docenas, columnas, etc. |
| El análisis es el producto principal. | La recomendación es el producto principal; el análisis es el respaldo. |
| La gestión de apuesta aparece integrada. | Recomendación y gestión deben ser módulos separados. |
| Puede terminar mostrando datos en todos los giros. | Puede responder NO APOSTAR cuando no haya señal suficiente. |

---

## 6. Cómo debería funcionar cada giro

1. **Paso 1.** El usuario introduce el nuevo resultado.
2. **Paso 2.** El sistema actualiza ventanas estadísticas (por ejemplo 10, 20, 50 y 100 giros).
3. **Paso 3.** Evalúa todos los mercados y combinaciones permitidas.
4. **Paso 4.** Calcula un *Signal Score* interno para cada alternativa.
5. **Paso 5.** Descarta opciones que no superen el umbral mínimo.
6. **Paso 6.** Si existe una señal válida, muestra **UNA recomendación principal**.
7. **Paso 7.** El método de gestión seleccionado calcula el importe de la apuesta.
8. **Paso 8.** Si no existe señal suficiente, muestra **NO APOSTAR**.

---

## 7. Cómo debe verse para el cliente

La pantalla principal no debería obligar al cliente a interpretar tablas. El botón central puede ser **ANALIZAR Y RECOMENDAR PRÓXIMO GIRO**. La respuesta debe aparecer grande y visible. Debajo puede existir una sección *¿POR QUÉ RECOMIENDA ESTO?* con frecuencias, ventanas, desviaciones, probabilidad teórica y demás estadísticas.

---

## 8. Precisión conceptual obligatoria

El sistema **no debe decir que conoce el próximo resultado**. Una racha anterior tampoco implica que un color, docena o columna esté obligado a salir o a dejar de salir. Por eso deben diferenciarse tres conceptos:

- **Estadística histórica**
- **Señal del algoritmo**
- **Probabilidad teórica**

> **Texto sugerido para la interfaz:** *"Recomendación generada a partir del análisis estadístico de los resultados registrados. No constituye una predicción ni garantiza el resultado del siguiente giro."*

---

## 9. Validación antes del lanzamiento

Antes de comercializar el producto como una herramienta de recomendación, el motor debe probarse **fuera de la muestra utilizada para diseñarlo**. El equipo debe medir:

- Número de recomendaciones
- Aciertos / fallos
- Porcentaje de NO APOSTAR
- ROI con pagos reales y ventaja de la casa
- Beneficio / pérdida por unidad
- Drawdown máximo
- Comportamiento separado de señales Débil / Media / Fuerte / Muy fuerte

Esto permite comprobar si el motor aporta información útil o únicamente describe el pasado.

---

## 10. Solicitud concreta al equipo de ingeniería

Mantener el analizador estadístico actual, pero **convertirlo en la base de un motor de recomendación**. Después de cada giro, el software debe evaluar automáticamente todos los mercados, decidir si existe una señal suficiente y mostrar de forma prioritaria qué recomienda apostar en el siguiente giro. La recomendación puede ser una zona individual o una combinación permitida. Si no existe señal suficiente, debe indicar **NO APOSTAR**. Posteriormente, y de forma separada, el método de gestión elegido por el usuario determinará el importe de la apuesta. El resultado debe presentarse como **recomendación estadística, nunca como predicción garantizada**.
