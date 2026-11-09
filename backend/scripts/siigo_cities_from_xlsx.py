"""Genera `app/billing/data/siigo_cities.json` desde la lista de ciudades de Siigo.

Uso (desde backend/):

    python -I scripts/siigo_cities_from_xlsx.py <Lista-de-ciudades.xlsx>

La lista es la publica que enlaza la documentacion de clientes de Siigo
(`https://saprodcentralassets.blob.core.windows.net/siigoapi/documentation/
Lista-de-ciudades.xlsx`), con las columnas `CityCode`, `CityName`, `StateCode`,
`StateName`, `CountryCode` y `CountryName` (docs/PLATAFORMA_COMPLETA.md §3.17,
"Paso 5.4", punto 8). Sirve igual el reporte de la empresa en Siigo Nube si trae
esas columnas.

Solo usa la biblioteca estandar: un xlsx es un zip de XML. Corre con `-I` y
recibe la ruta como argumento, porque el archivo viene de fuera.
"""

import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COLUMNS = ("CityCode", "CityName", "StateCode", "StateName", "CountryCode", "CountryName")
OUT = Path(__file__).resolve().parent.parent / "app" / "billing" / "data" / "siigo_cities.json"


def _rows(path: str) -> list[list[str]]:
    book = zipfile.ZipFile(path)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in book.namelist():
        root = ET.fromstring(book.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(f"{NS}t")) for si in root.findall(f"{NS}si")]
    sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in sheet.iter(f"{NS}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{NS}c"):
            ref = re.match(r"[A-Z]+", cell.get("r", "")).group(0)  # type: ignore[union-attr]
            col = 0
            for ch in ref:
                col = col * 26 + ord(ch) - 64
            v = cell.find(f"{NS}v")
            if v is None or v.text is None:
                continue
            values[col - 1] = (shared[int(v.text)] if cell.get("t") == "s" else v.text).strip()
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
    return rows


def main(path: str) -> None:
    rows = _rows(path)
    header = rows[0]
    try:
        index = [header.index(c) for c in COLUMNS]
    except ValueError:
        sys.exit(f"El archivo no trae las columnas {COLUMNS}: {header}")
    cities: list[list[str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows[1:]:
        city_code, city, state_code, state, country_code, country = (
            row[i] if i < len(row) else "" for i in index
        )
        if not (city_code and city and state_code and country_code and country):
            continue
        key = (country_code.upper(), state_code, city_code)
        if key in seen:
            sys.exit(f"Ciudad repetida: {key}")
        seen.add(key)
        cities.append([country_code, country, state_code, state, city_code, city])
    cities.sort(key=lambda c: (c[1], c[3], c[5]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": "Siigo, Lista-de-ciudades.xlsx (documentacion de clientes de la API)",
        "generated": date.today().isoformat(),
        "columns": ["country_code", "country", "state_code", "state", "city_code", "city"],
        "cities": cities,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(cities)} ciudades de {len({c[0].upper() for c in cities})} paises -> {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
