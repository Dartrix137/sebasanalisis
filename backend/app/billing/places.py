"""Paises, departamentos y ciudades con los codigos de Siigo (docs/PLATAFORMA_COMPLETA.md
§3.17, "Paso 5.4", punto 8; Fase 5, paso 5.4).

Siigo exige, para crear el tercero de una factura, `address.city` con
`country_code`, `state_code` y `city_code` de su propia lista, y no tiene un
endpoint para consultarla. La lista vive en `data/siigo_cities.json`, generada
con `scripts/siigo_cities_from_xlsx.py`. Desde el 2026-11-10 sale del reporte de
paises, estados y ciudades de la empresa en Siigo Nube, que trae tambien las
ciudades creadas alla (la primera version salio de la lista publica que enlaza
la documentacion de clientes). Los codigos de pais y los nombres de las ciudades
que ya estaban se conservan de la lista publica: el script explica por que.

Lo que se sabe de esa lista:
- Colombia esta completa (1.123 municipios, con su codigo DANE).
- Fuera de Colombia trae pocas ciudades por pais, casi siempre capitales y
  algunas grandes. Faltan ciudades como Nueva York o Buenos Aires (Argentina),
  y tiene errores (Quito en Pastaza). Si la del cliente no esta, elige la mas
  cercana y escribe la real en la direccion; si hace falta, la ciudad se crea en
  Siigo Nube y se regenera la lista (§3.17, ciudades, opcion b).
- El codigo de ciudad no es unico: `0101` es Madrid y tambien Lisboa. Lo que
  identifica una ciudad es el trio (pais, departamento, ciudad).
- Los codigos de pais vienen casi todos con la primera letra en mayuscula
  (`Co`, `Es`) y dos en mayusculas (`AG`, `KY`): se guardan y se mandan a Siigo
  tal como vienen, y se comparan sin distinguir mayusculas.

Python puro: lee un archivo del paquete, sin red ni base de datos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

COLOMBIA = "Co"


@dataclass(frozen=True)
class City:
    country_code: str
    country: str
    state_code: str
    state: str
    city_code: str
    city: str


@dataclass(frozen=True)
class Country:
    code: str
    name: str


@lru_cache(maxsize=1)
def _cities() -> tuple[City, ...]:
    raw = resources.files("app.billing").joinpath("data/siigo_cities.json").read_text("utf-8")
    data = json.loads(raw)
    return tuple(City(*row) for row in data["cities"])


def _same(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def countries() -> list[Country]:
    """Todos los paises de la lista: Colombia primero, los demas por nombre."""
    found: dict[str, Country] = {}
    for c in _cities():
        found.setdefault(c.country_code.casefold(), Country(c.country_code, c.country))
    rest = sorted(
        (c for c in found.values() if not _same(c.code, COLOMBIA)),
        key=lambda c: c.name.casefold(),
    )
    colombia = [c for c in found.values() if _same(c.code, COLOMBIA)]
    return colombia + rest


def country(code: str) -> Country | None:
    return next((c for c in countries() if _same(c.code, code)), None)


def cities_of(country_code: str) -> list[City]:
    """Las ciudades de un pais, por departamento y nombre."""
    return sorted(
        (c for c in _cities() if _same(c.country_code, country_code)),
        key=lambda c: (c.state.casefold(), c.city.casefold()),
    )


def find(country_code: str, state_code: str, city_code: str) -> City | None:
    """La ciudad del trio exacto, o `None` si no esta en la lista."""
    for c in _cities():
        if (
            _same(c.country_code, country_code)
            and c.state_code == state_code
            and c.city_code == city_code
        ):
            return c
    return None


def is_colombia(country_code: str) -> bool:
    return _same(country_code, COLOMBIA)
