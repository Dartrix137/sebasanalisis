"""Exporta el OpenAPI de la API a un archivo, sin levantar el servidor.

Es la entrada del generador de tipos del frontend (`npm run gen:types`, ver
docs/PLATAFORMA_COMPLETA.md §13.2). Importa la app y escribe `app.openapi()`
con las claves ordenadas, para que el diff de un cambio de schema sea estable.
No abre conexion a la base.

    python scripts/export_openapi.py [destino]

Sin argumento escribe en `frontend/lib/api/openapi.json`.
"""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = BACKEND_DIR.parent / "frontend" / "lib" / "api" / "openapi.json"

sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402


def main() -> None:
    output = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    spec = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False)
    # LF fijo: el CI corre en Linux y compara este archivo byte a byte.
    output.write_text(spec + "\n", encoding="utf-8", newline="\n")
    print(f"OpenAPI escrito en {output}")


if __name__ == "__main__":
    main()
