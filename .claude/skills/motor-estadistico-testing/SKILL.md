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

Test de regresión: con menos de 36 giros en la sesión, `chi_square_signal()` debe devolver `None` o un flag `activo=False` sin importar cuán "significativo" sea el p-valor calculado — el mínimo de muestra es un requisito duro, no una sugerencia.

## Checklist antes de dar por cerrado un módulo del motor

- [ ] ¿Tiene tests con los casos de regresión de esta skill que apliquen a ese módulo?
- [ ] ¿Es una función pura (mismo input → mismo output, sin I/O)?
- [ ] ¿Los tests corren sin base de datos ni red (`pytest backend/tests/engine/` aislado)?
- [ ] Si el módulo calcula una probabilidad o frecuencia, ¿el test verifica que SIEMPRE se devuelve junto con la probabilidad teórica (nunca una sola)?
