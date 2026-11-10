"""Genera `app/billing/data/siigo_cities.json` desde la lista de ciudades de Siigo.

Uso (desde backend/):

    python -I scripts/siigo_cities_from_xlsx.py <archivo.xlsx>

Lee dos formatos (docs/PLATAFORMA_COMPLETA.md §3.17, "Lo decidido por el usuario
sobre estas respuestas", ciudades, opcion b):

- **El reporte de la empresa en Siigo Nube** (el que se usa desde el 2026-11-10):
  "Reportes > Carteras/Proveedores > Reportes de sistema > Paises, Estados y
  Ciudades / Municipios", exportado a Excel. Trae las ciudades creadas en la
  empresa ("Configuracion > General > Regional > Ciudades"). Para sumar una
  ciudad: se crea alla, se vuelve a sacar el reporte y se corre este script.
  Columnas `Pais`, `Estado / Departamento`, `Ciudad`, `Codigo pais`,
  `Codigo Estado / Departamento` y `Codigo ciudad` (con tildes), despues de unas
  filas de titulo con el nombre y el documento del titular de la cuenta, y una
  fila final "Procesado en: ...".
- **La lista publica** que enlaza la documentacion de clientes de la API
  (`https://saprodcentralassets.blob.core.windows.net/siigoapi/documentation/
  Lista-de-ciudades.xlsx`), con las columnas `CityCode`, `CityName`,
  `StateCode`, `StateName`, `CountryCode` y `CountryName`. De ahi salio la
  primera version del JSON (2026-11-09).

Del reporte se toma que (pais, departamento, ciudad) existen y sus codigos de
departamento y ciudad. Dos cosas se toman de la lista que ya esta en el JSON,
porque el reporte las trae mal (comparado el 2026-11-10):

- **El codigo de pais.** El reporte lo trae en tres letras (`COL`, `ESP`), y la
  API recibe y guarda el de la lista publica (`Co`: lo devolvio
  `GET /v1/customers/{id}` en la prueba del 2026-11-10). Ademas, el reporte le pone
  a El Salvador el `VCT` de San Vicente y las Granadinas. Por eso el codigo se
  busca por el nombre del pais. Un pais que no esta en el JSON se deja por fuera
  y se avisa: su codigo se confirma con Siigo antes de agregarlo a
  `EXTRA_COUNTRY_CODES`.
- **Los nombres de las ciudades que ya estaban.** El reporte cambia "ao" por
  "u" con tilde ("Sao Luis" con tilde sale "Su Luis") y pega las palabras
  separadas por un espacio duro. Una ciudad nueva lleva el nombre del reporte.

En los dos formatos, el espacio duro pasa a espacio normal.

Solo usa la biblioteca estandar: un xlsx es un zip de XML. Corre con `-I` y
recibe la ruta como argumento, porque el archivo viene de fuera. No copia al JSON
ninguna fila de titulo del reporte.
"""

import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
OUT = Path(__file__).resolve().parent.parent / "app" / "billing" / "data" / "siigo_cities.json"

# El orden de cada tupla: ciudad, nombre, departamento, nombre, pais, nombre.
PUBLIC_COLUMNS = ("CityCode", "CityName", "StateCode", "StateName", "CountryCode", "CountryName")
REPORT_COLUMNS = (
    "Código ciudad",
    "Ciudad",
    "Código Estado / Departamento",
    "Estado / Departamento",
    "Código país",
    "País",
)
REPORT_FOOTER = "Procesado en:"

#: Codigos de pais de la API confirmados para paises que la lista publica no
#: traia, por nombre del pais en el reporte. Vacio: ninguno confirmado todavia.
EXTRA_COUNTRY_CODES: dict[str, str] = {}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _column(ref: str | None, position: int) -> int:
    """La columna de la celda: la de su referencia (`C12`) o, si no trae, su
    posicion en la fila (el reporte de Siigo Nube no trae referencias)."""
    match = re.match(r"[A-Z]+", ref or "")
    if match is None:
        return position
    col = 0
    for ch in match.group(0):
        col = col * 26 + ord(ch) - 64
    return col - 1


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
        for position, cell in enumerate(row.findall(f"{NS}c")):
            col = _column(cell.get("r"), position)
            if cell.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter(f"{NS}t"))
            else:
                v = cell.find(f"{NS}v")
                if v is None or v.text is None:
                    continue
                text = shared[int(v.text)] if cell.get("t") == "s" else v.text
            values[col] = _clean(text)
        rows.append([values.get(i, "") for i in range(max(values) + 1)] if values else [])
    return rows


def _header(rows: list[list[str]]) -> tuple[int, list[int], bool]:
    """La fila de encabezado, el indice de cada columna y si es el reporte."""
    for n, row in enumerate(rows):
        for columns, is_report in ((REPORT_COLUMNS, True), (PUBLIC_COLUMNS, False)):
            if all(c in row for c in columns):
                return n, [row.index(c) for c in columns], is_report
    sys.exit(f"No encuentro el encabezado: ni {REPORT_COLUMNS} ni {PUBLIC_COLUMNS}")


def _previous() -> tuple[dict[str, str], dict[tuple[str, str, str], tuple[str, str]]]:
    """Del JSON actual: el codigo de cada pais por su nombre, y los nombres de
    departamento y ciudad de cada trio."""
    if not OUT.exists():
        sys.exit(f"El reporte necesita el JSON actual ({OUT}) para los codigos de pais")
    data = json.loads(OUT.read_text(encoding="utf-8"))
    codes: dict[str, str] = {}
    names: dict[tuple[str, str, str], tuple[str, str]] = {}
    for country_code, country, state_code, state, city_code, city in data["cities"]:
        codes.setdefault(_clean(country), country_code)
        names[(country_code.upper(), state_code, city_code)] = (_clean(state), _clean(city))
    return codes, names


def main(path: str) -> None:
    rows = _rows(path)
    start, index, is_report = _header(rows)
    codes, names = _previous() if is_report else ({}, {})
    codes.update(EXTRA_COUNTRY_CODES)

    cities: list[list[str]] = []
    seen: set[tuple[str, str, str]] = set()
    unknown_countries: dict[str, str] = {}
    shared_codes: dict[str, set[str]] = {}
    for row in rows[start + 1 :]:
        if row and row[0].startswith(REPORT_FOOTER):
            continue
        city_code, city, state_code, state, country_code, country = (
            row[i] if i < len(row) else "" for i in index
        )
        if not (city_code and city and state_code and country_code and country):
            continue
        if is_report:
            shared_codes.setdefault(country_code, set()).add(country)
            report_code = country_code
            country_code = codes.get(country, "")
            if not country_code:
                unknown_countries[country] = report_code
                continue
            state, city = names.get((country_code.upper(), state_code, city_code), (state, city))
        key = (country_code.upper(), state_code, city_code)
        if key in seen:
            sys.exit(f"Ciudad repetida: {key}")
        seen.add(key)
        cities.append([country_code, country, state_code, state, city_code, city])
    cities.sort(key=lambda c: (c[1], c[3], c[5]))

    for code, countries in sorted(shared_codes.items()):
        if len(countries) > 1:
            print(f"Aviso: el reporte usa {code} para {sorted(countries)}; el codigo sale del nombre")
    for country, code in sorted(unknown_countries.items()):
        print(f"Fuera: {country} ({code} en el reporte) no tiene codigo de pais confirmado")
    if is_report:
        added = seen - set(names)
        gone = sorted(set(names) - seen)
        print(f"Nuevas frente al JSON anterior: {len(added)}. Ya no estan: {len(gone)}")
        for key in gone:
            print(f"  ya no esta: {key} {names[key]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    source = (
        "Siigo Nube, reporte Paises, Estados y Ciudades / Municipios de la empresa;"
        " codigos de pais y nombres anteriores de la lista publica"
        if is_report
        else "Siigo, Lista-de-ciudades.xlsx (documentacion de clientes de la API)"
    )
    data = {
        "source": source,
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
