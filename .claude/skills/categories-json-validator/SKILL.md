---
name: categories-json-validator
description: Valida la estructura y consistencia de cualquier configuración de juego (possible_outcomes + categories + groups + payouts) en Sebasanálisis, usada en game_variants.categories_json. Úsala SIEMPRE al crear el seed de ruleta europea/americana, al construir o revisar el formulario de admin para crear/editar variantes de juego, al diseñar el JSON de un juego nuevo (ej. dados), o cuando el motor estadístico (engine/) dé resultados inesperados que podrían venir de una configuración de categorías mal formada.
---

# Validador de categories_json — modelo genérico de juegos

Sebasanálisis usa un esquema genérico para describir cualquier juego de resultados discretos y probabilidad fija (ruleta, dados, futuros), de forma que `engine/` nunca necesite código específico por juego. Toda la semántica del juego vive en este JSON, validado contra el schema Pydantic `GameVariantConfig` (ver `schemas/games.py`).

## Estructura esperada

```json
{
  "possible_outcomes": ["0", "00", "1", "2", "...", "36"],
  "categories": [
    {
      "id": "color",
      "label": "Color",
      "groups": {
        "red": { "outcomes": ["1", "3", "5", "..."], "payout": 1 },
        "black": { "outcomes": ["2", "4", "6", "..."], "payout": 1 },
        "green": { "outcomes": ["0", "00"], "payout": 35 }
      }
    }
  ]
}
```

## Reglas de validación (en este orden)

1. **`possible_outcomes` no vacío** y sin duplicados.
2. **Cada `category.id` es único** dentro de la variante (ej. no puede haber dos categorías `"color"`).
3. **Cada `group.outcomes` es subconjunto de `possible_outcomes`** — si un grupo referencia un valor que no está en `possible_outcomes`, es un error de configuración que debe bloquear el guardado, no solo advertir. Este es el chequeo más importante: es la causa más común de que el motor estadístico calcule mal una probabilidad teórica.
4. **Cobertura de cada categoría**: idealmente cada categoría cubre todos o casi todos los `possible_outcomes` (ej. color cubre los 37/38 números incluyendo verde). Si una categoría deja resultados sin grupo asignado, adviértelo explícitamente — puede ser intencional (ej. "cero" queda fuera de "docena" en ruleta) pero debe confirmarse, no asumirse.
5. **Payout > 0** en todos los grupos.
6. **Suma de probabilidades teóricas de una categoría ≈ 1** (permitiendo que el resultado(s) excluidos, como el 0 en docenas, queden fuera intencionalmente) — si la suma da muy por debajo de 1 sin resultados excluidos evidentes, hay grupos faltantes.

## Casos de referencia ya verificados (usar como fixture de test, no reinventar)

**Ruleta europea (37 números, 0-36):**

- `color`: red (18 números) / black (18 números) / green (["0"]) — payout red/black=1, green=35
- `dozen`: first (1-12) / second (13-24) / third (25-36) — el "0" queda fuera intencionalmente, payout=2
- `column`: first (n%3==1) / second (n%3==2) / third (n%3==0, excluyendo 0) — payout=2
- `parity`: even / odd — el "0" queda fuera intencionalmente, payout=1
- `high_low`: low (1-18) / high (19-36) — el "0" queda fuera intencionalmente, payout=1

**Ruleta americana (38 números, 0-36 + 00):** igual estructura, pero `green` incluye `["0","00"]` con **payout 17** (no 35 — un grupo de 2 números a 35:1 da EV=+0.89, matemáticamente insostenible; 17:1 es el pago real de la apuesta "0-00 split" en mesas americanas y devuelve el EV correcto de −0.0526, la ventaja de la casa). Todas las demás categorías siguen excluyendo ambos ceros. La probabilidad teórica de cada apuesta baja proporcionalmente (ver tabla en `docs/ARQUITECTURA_Y_ESTADISTICA.md` §2.1).

### Campo `shrinkage_alpha` — dónde vive

`shrinkage_alpha` es configuración del juego, no una constante del motor: depende de cuántos grupos tiene la categoría (más grupos → α proporcionalmente mayor). Vive **dentro de cada objeto de categoría** en `categories_json`, no en `engine/frequency.py`:

```json
{ "id": "color", "label": "Color", "shrinkage_alpha": 8, "groups": { ... } }
```

Valores de referencia ya validados: `8` para categorías binarias (color, paridad, alto/bajo), `12` para categorías de 3 grupos (docena, columna). `engine/frequency.py` lee este valor desde la categoría, nunca lo hardcodea.

## Al diseñar un juego nuevo (ej. dados)

Sigue el mismo proceso de validación. Ejemplo mínimo para dos dados (suma 2-12):

- `possible_outcomes`: ["2","3",...,"12"]
- Cada categoría (ej. `sum_range`, `parity`) debe cubrir explícitamente qué pasa con el 7 u otros valores especiales, igual que el 0 en ruleta — no dejarlo implícito.

## Antes de guardar cualquier categories_json (admin o seed)

- [ ] ¿Corrió la validación de outcomes-subset (regla 3)? Un fallo aquí silencioso rompe el cálculo de `theoretical_probability` en `engine/probability.py` sin lanzar error visible al usuario final — trátalo como bloqueante.
- [ ] ¿Los payouts coinciden con las tablas verificadas en `docs/reference/ESTRATEGIA_DE_RULETA_CORREGIDA_Y_VERIFICADA.txt`?
- [ ] ¿Se probó con `engine/probability.py` que la probabilidad teórica calculada coincide con la tabla de §2.1 del documento de arquitectura antes de marcar la variante como `active: true`?
