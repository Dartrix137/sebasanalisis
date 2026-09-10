---
name: motor-estadistico-testing
description: Guía para escribir y verificar tests unitarios con pytest de cualquier módulo dentro de backend/app/engine/ (probability.py, frequency.py, chi_square.py, streak.py, ranking.py, bankroll.py, baseline.py) en el proyecto Sebasanálisis. Úsala SIEMPRE antes de conectar un módulo del motor a un endpoint de FastAPI, y cada vez que se cree, modifique o refactorice una fórmula estadística o de gestión de banca. Incluye los casos de regresión numéricos exactos tomados del documento de estrategia verificado — no los inventes de memoria, cópialos de aquí.
---

# Testing del motor estadístico de Sebasanálisis

El motor (`backend/app/engine/`) debe ser Python puro: sin FastAPI, sin SQLAlchemy, sin llamadas de red. Esto significa que se puede y se debe testear con pytest sin levantar infraestructura, y ningún módulo del motor se conecta a un endpoint hasta tener tests pasando.

## Regla de flujo

1. Escribe o modifica la función pura en `engine/`.
2. Escribe los tests en `backend/tests/engine/test_<modulo>.py` ANTES de exponerla en un endpoint.
3. Corre `pytest backend/tests/engine/ -v` y confirma que pasa.
4. Solo entonces conecta el módulo a `api/v1/`.

## Casos de regresión obligatorios (no inventar cifras — usar estas)

### Martingala clásica (pago 1:1), apuesta base $100 — tabla del documento verificado

| Intento | Apuesta | Pérdida acumulada si falla |
| ------- | ------- | -------------------------- |
| 1       | $100    | $100                       |
| 2       | $200    | $300                       |
| 3       | $400    | $700                       |
| 4       | $800    | $1.500                     |
| 5       | $1.600  | $3.100                     |
| 6       | $3.200  | $6.300                     |
| 7       | $6.400  | $12.700                    |
| 8       | $12.800 | $25.500                    |
| 9       | $25.600 | $51.100                    |
| 10      | $51.200 | $102.300                   |

Test de regresión: `martingale()` con `base_bet=100` y 10 pérdidas consecutivas debe dar pérdida acumulada de `$102.300`, NO `$100.000` (ese fue el error del documento original que se corrigió).

### Progresión dos-sectores (docenas/columnas dobles), unidad $100 — tabla del documento verificado

| Escalón | Apuesta por docena | Total del giro | Pérdida acumulada si falla |
| ------- | ------------------ | -------------- | -------------------------- |
| 1       | 1 u. ($100)        | $200           | $200                       |
| 2       | 2 u. ($200)        | $400           | $600                       |
| 3       | 6 u. ($600)        | $1.200         | $1.800                     |
| 4       | 18 u. ($1.800)     | $3.600         | $5.400                     |
| 5       | 54 u. ($5.400)     | $10.800        | $16.200                    |

Test de regresión: 5 pérdidas consecutivas en modo dos-sectores con unidad $100 debe dar pérdida acumulada de `$16.200`.

### Probabilidades teóricas (constantes) — europea (37) vs. americana (38)

| Apuesta                       | Europea        | Americana      |
| ----------------------------- | -------------- | -------------- |
| Pleno                         | 2.70% (1/37)   | 2.63% (1/38)   |
| Color / Par-Impar / Alto-Bajo | 48.65% (18/37) | 47.37% (18/38) |
| Docena / Columna              | 32.43% (12/37) | 31.58% (12/38) |

Test de regresión: `theoretical_probability()` para cada tipo de apuesta y variante debe devolver estos valores exactos (con tolerancia de redondeo ≤ 0.01%).

### Rachas (cola binomial) — probabilidad de N repeticiones consecutivas, ruleta europea (p=18/37)

| Repeticiones | Probabilidad |
| ------------ | ------------ |
| 2            | 23.67%       |
| 3            | 11.52%       |
| 4            | 5.60%        |
| 5            | 2.73%        |
| 6            | 1.33%        |

Test de regresión: `streak_probability(n, p_teorica=18/37)` para n=2..6 debe coincidir con esta tabla (tolerancia ≤ 0.05%).

### Shrinkage bayesiano — ejemplo de referencia del boceto

Con α=8, prob. justa 48.65%, observado 7 de 11:

```
p̂ = (7 + 8 × 0.4865) / (11 + 8) = 10.892 / 19 ≈ 0.5733  (57.3%)
```

Test de regresión: `shrinkage_estimate(favorable=7, total=11, p_teorica=0.4865, alpha=8)` debe devolver ≈0.573, NO 0.636 (que sería la frecuencia cruda sin shrinkage — un test que devuelva 0.636 indica que el shrinkage no se está aplicando).

### χ² — mínimo de activación

Test de regresión: con menos de **200 giros** (`MIN_SPINS`) en la sesión, `chi_square_signal()` debe devolver un flag `active=False` y `p_value=None` sin importar cuán "significativo" sea el p-valor calculado — el mínimo de muestra es un requisito duro, no una sugerencia.

Ese 200 es un **piso de ruido, no un umbral de detección de sesgo**, y los tests deben reflejarlo: a 200 giros la prueba solo tiene potencia para ver una docena saliendo ~43% contra 32.4% teórico. No escribas tests que asuman que a partir de ahí se detecta sesgo real — un sesgo explotable (>33.3% frente al pago 2:1) pediría del orden de 30.000 giros.

### χ² — corrección por comparaciones múltiples

`all_chi_square_signals()` corre la prueba sobre las 5 categorías y ajusta los p-valores con Benjamini-Hochberg antes de decidir `active`. Dos reglas al testear:

- **Una prueba aislada es familia de tamaño 1**: `chi_square_signal()` por sí sola no corrige nada y `p_value_adjusted == p_value`. Si un test necesita comprobar la corrección, tiene que pasar por `all_chi_square_signals()`.
- **Las categorías sin muestra suficiente no entran en la familia**: no son pruebas, y contarlas inflaría `m` castigando a las demás.

Caso de regresión disponible en `tests/engine/test_chi_square.py`: `GIROS_SIN_SESGO_CON_UN_P_BAJO`, 210 giros de una rueda justa donde `color` da p=0.023 crudo y q=0.116 corregido. Sin corrección esa sesión mostraría una señal FUERTE inexistente.

### Intervalo de Wilson — valor de referencia

Test de regresión: `wilson_interval(0, 10)` al 95% debe dar `[0, 0.2775]`, el valor tabulado. Comprobar además que **no colapsa a ancho cero** cuando el grupo nunca salió (es la razón de usar Wilson y no la aproximación normal) y que se estrecha con el volumen: el intervalo de 6/10 es más de 8 veces más ancho que el de 600/1000, aunque ambos sean 60%.

No derives de este intervalo un veredicto por grupo del tipo "esta desviación se distingue del azar": serían 13 pruebas simultáneas y marcarían algo en ~⅓ de las sesiones de una rueda justa (ver §2.2 del doc de arquitectura).

## Checklist antes de dar por cerrado un módulo del motor

- [ ] ¿Tiene tests con los casos de regresión de esta skill que apliquen a ese módulo?
- [ ] ¿Es una función pura (mismo input → mismo output, sin I/O)?
- [ ] ¿Los tests corren sin base de datos ni red (`pytest backend/tests/engine/` aislado)?
- [ ] Si el módulo calcula una probabilidad o frecuencia, ¿el test verifica que SIEMPRE se devuelve junto con la probabilidad teórica (nunca una sola)?
