#!/usr/bin/env python3
"""Hook PostToolUse: guardian de terminologia no-predictiva de Sebasanalisis.

Lee el payload JSON del hook por stdin, mira el archivo que se acaba de escribir
y busca vocabulario predictivo (docs/ARQUITECTURA_Y_ESTADISTICA.md §0 y la skill
`terminologia-no-predictiva`). No bloquea la edicion: inyecta el hallazgo como
contexto para que se corrija antes de seguir.

Reemplaza al agente `guardian-terminologia`: un agente solo corre si alguien lo
invoca; esto corre siempre que se escriba un archivo con texto visible.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# --- Alcance -----------------------------------------------------------------

# Prefijos (relativos a la raiz del repo) donde vive texto visible al usuario:
# copy de UI, mensajes de error, nombres de endpoints/tablas/campos, labels de
# seed, documentacion.
INCLUDED_PREFIXES = (
    "frontend/app",
    "frontend/components",
    "frontend/lib",
    "backend/app",
    "docs",
    ".claude/skills",
    "CLAUDE.md",
    "README.md",
)

# docs/reference/ es insumo citable con su lenguaje original (ver "Cuando NO
# aplica" en la skill). node_modules y compilados no son nuestros.
EXCLUDED_SUBSTRINGS = (
    "docs/reference/",
    "node_modules/",
    ".next/",
    "__pycache__/",
    ".pytest_cache/",
    "package-lock.json",
    "tsconfig.tsbuildinfo",
)

CHECKED_SUFFIXES = (".ts", ".tsx", ".py", ".md", ".json", ".txt", ".sql", ".mako")

# --- Patrones ----------------------------------------------------------------

# Terminos prohibidos. Cada entrada: (regex, reemplazo sugerido).
FORBIDDEN = [
    (r"predicci[oó]n(es)?", "sugerencia estadistica / senal"),
    (r"predictiv[oa]s?", "descriptivo / estadistico"),
    (r"predice[nr]?", "detecta una desviacion en"),
    (r"predecir", "describir la desviacion observada"),
    (r"prediction[s]?", "statistical_suggestion / signal"),
    (r"predicted", "observed / suggested"),
    (r"va[nm]? a salir", "ha salido con mayor/menor frecuencia que la esperada"),
    (r"deber[ií]a(n)? salir", "ha salido con menor frecuencia que la esperada"),
    (r"esta pendiente de salir", "desviacion observada"),
    (r"acierto(s)?\b", "coincidencia con el resultado observado"),
    (r"precisi[oó]n del (modelo|motor)", "tasa de coincidencia"),
    (r"n[uú]mero ganador", "resultado del giro"),
    (r"ganancia(s)? asegurada(s)?", "no prometas resultados"),
    (
        r"garanti\w+\s+(de\s+)?(ganancia|resultado|beneficio|utilidad)\w*",
        "no prometas resultados",
    ),
    (r"infalible", "no prometas resultados"),
]

# Si alguno de estos aparece en los ~70 caracteres previos al termino, la linea
# se considera legitima: es una negacion ("no predictivo", "nunca predice") o una
# cita del boceto/mockup que se esta contrastando a proposito.
EXEMPTING_CONTEXT = re.compile(
    r"\b(no|non|nunca|jam[aá]s|sin|never|not)\b"
    r"|\b(dec[ií]a|original|boceto|cita|mockup|reemplaza|en lugar de|prohibid\w*"
    r"|nomenclatura|nunca `|no `)\b"
    # Metalenguaje: hablar *sobre* la regla no es romperla.
    r"|\b(suen[ae]|suenan|parezca|parece|lenguaje|terminolog\w+|vocabulario"
    r"|evita\w*|corrige|corregir|regla)\b",
    re.IGNORECASE,
)

LOOKBEHIND = 70

# Archivos de UI que muestran senales y deberian arrastrar el disclaimer fijo.
SIGNAL_HINTS = re.compile(
    r"sugerencia|se[nñ]al|racha|chi.?cuadrado|chi_square|FUERTE|MEDIA|D[EÉ]BIL",
    re.IGNORECASE,
)


def candidate_paths(payload: dict) -> list[str]:
    out: list[str] = []
    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    for source in (tool_response, tool_input):
        if not isinstance(source, dict):
            continue
        for key in ("filePath", "file_path", "path"):
            value = source.get(key)
            if isinstance(value, str):
                out.append(value)
        # Bash con diff de archivos: listas de rutas cambiadas.
        for key, value in source.items():
            if not isinstance(value, list) or "file" not in key.lower():
                continue
            for item in value:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    for k in ("filePath", "file_path", "path"):
                        if isinstance(item.get(k), str):
                            out.append(item[k])
    seen: set[str] = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def in_scope(rel: str) -> bool:
    if not rel.endswith(CHECKED_SUFFIXES):
        return False
    if any(chunk in rel for chunk in EXCLUDED_SUBSTRINGS):
        return False
    return rel.startswith(INCLUDED_PREFIXES)


QUOTE_CHARS = "\"'`“”«»"


def _is_quoted(line: str, start: int, end: int) -> bool:
    """True si el termino esta entre comillas (cita), no en prosa."""
    before = line[:start]
    after = line[end:]
    opening = before.rstrip()[-1:] if before.rstrip() else ""
    closing = after.lstrip()[:1] if after.lstrip() else ""
    if opening in QUOTE_CHARS and closing in QUOTE_CHARS:
        return True
    # Termino de varias palabras dentro de una cita mas larga en la misma linea.
    quotes_before = sum(before.count(q) for q in QUOTE_CHARS)
    return quotes_before % 2 == 1


def scan(path: Path, rel: str) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    is_markdown = rel.endswith(".md")
    findings: list[str] = []
    previous: list[str] = ["", ""]
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, replacement in FORBIDDEN:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                # El contexto exento puede venir de la linea anterior: una cita o
                # una negacion suele abrirse en el renglon de arriba.
                before = (
                    " ".join(previous)[-2 * LOOKBEHIND :]
                    + " "
                    + line[max(0, match.start() - LOOKBEHIND) : match.start()]
                )
                if EXEMPTING_CONTEXT.search(before):
                    continue
                # En documentacion, un termino entrecomillado se esta citando
                # (la tabla de terminologia de §0, el lenguaje del boceto), no
                # usando. En codigo no aplica: ahi las comillas son copy real.
                if is_markdown and _is_quoted(line, match.start(), match.end()):
                    continue
                findings.append(
                    f"  {rel}:{lineno}  \"{match.group(0)}\"  ->  usa: {replacement}"
                )
                break
        previous = [previous[-1], line]

    if (
        rel.startswith("frontend/app/")
        and rel.endswith(".tsx")
        and SIGNAL_HINTS.search(text)
        and "DISCLAIMER" not in text.upper()
    ):
        findings.append(
            f"  {rel}  es una pantalla que muestra senales/sugerencias y no "
            "referencia el Disclaimer. "
            "El disclaimer fijo es obligatorio en toda pantalla que muestre "
            "sugerencias, rachas o chi-cuadrado (§0 del doc de arquitectura)."
        )
    return findings


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    root = Path(__file__).resolve().parents[2]
    findings: list[str] = []

    for raw in candidate_paths(payload):
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if not in_scope(rel) or not path.is_file():
            continue
        findings.extend(scan(path, rel))

    if not findings:
        return 0

    detail = "\n".join(findings[:20])
    if len(findings) > 20:
        detail += f"\n  ... y {len(findings) - 20} hallazgo(s) mas."

    context = (
        "GUARDIAN DE TERMINOLOGIA — posible lenguaje predictivo en lo que acabas "
        "de escribir:\n"
        f"{detail}\n\n"
        "La regla no-predictiva es no negociable (CLAUDE.md y §0 de "
        "docs/ARQUITECTURA_Y_ESTADISTICA.md). Corrige estas lineas ahora, antes "
        "de seguir con otra cosa. Si alguna es un falso positivo (una negacion o "
        "una cita explicita del boceto), dilo en tu respuesta y sigue. "
        "Ante la duda, corre la skill `terminologia-no-predictiva`."
    )

    print(
        json.dumps(
            {
                "systemMessage": (
                    f"Guardian de terminologia: {len(findings)} posible(s) uso(s) "
                    "de lenguaje predictivo en el archivo editado."
                ),
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context,
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
