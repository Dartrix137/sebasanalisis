"""La pagina de pago de un solo uso (Fase 5, paso 5.3; decidido el 2026-11-04).

Tipster Page responde la creacion de la orden con una pagina HTML que lleva al
navegador al procesador (manual V2 §7.2), y la orden se crea desde el backend,
con llaves que el navegador no puede ver. La API guarda esa pagina aqui y le da
al navegador un enlace de un solo uso: `GET /billing/checkout/{token}`. La
navegacion a la API no lleva la sesion del frontend (el token de acceso vive en
`localStorage`), asi que el enlace mismo es la credencial.

- En memoria, por `TTL` (decidido por el usuario el 2026-11-04): la API corre en
  un solo proceso. Si se reinicia, el enlace se pierde y el cliente abre un pago
  nuevo. Nada de esto se escribe en la base.
- La pagina no lleva los datos del comprador que pidio el medio: esos viajaron
  en el cuerpo de la orden y no se guardan en ningun lado.
- Se guarda la huella del enlace, no el enlace.
- Abrir el enlace lo consume: una recarga no vuelve a mostrar la pagina.

`page_csp` arma la Content Security Policy de esa pagina: deja correr solo los
scripts que trae (por su huella sha256) y enviar formularios solo a los
origenes a los que apuntan sus formularios.
"""

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

TTL_SECONDS = 10 * 60
#: Tope de paginas guardadas a la vez. Con el limite de intentos de pago por
#: cuenta no deberia acercarse; si se llega, salen las mas viejas.
MAX_PAGES = 1000


@dataclass(frozen=True)
class StoredPage:
    html: str
    csp: str


@dataclass
class _Entry:
    page: StoredPage
    expires_at: float


_pages: dict[str, _Entry] = {}
_lock = threading.Lock()


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def put(html: str, *, return_url: str | None = None, now: float | None = None) -> str:
    """Guarda la pagina y devuelve el token del enlace. `return_url` es a donde
    vuelve el navegador al terminar: su origen entra en `form-action`."""
    moment = time.monotonic() if now is None else now
    token = secrets.token_urlsafe(32)
    extra = (_origin(return_url, allow_http=True),) if return_url else ()
    csp = page_csp(html, form_origins=tuple(o for o in extra if o))
    entry = _Entry(page=StoredPage(html=html, csp=csp), expires_at=moment + TTL_SECONDS)
    with _lock:
        for key in [k for k, e in _pages.items() if e.expires_at <= moment]:
            del _pages[key]
        while len(_pages) >= MAX_PAGES:
            del _pages[min(_pages, key=lambda k: _pages[k].expires_at)]
        _pages[_key(token)] = entry
    return token


def take(token: str, *, now: float | None = None) -> StoredPage | None:
    """La pagina del enlace, una sola vez. None si no existe, ya se uso o vencio."""
    moment = time.monotonic() if now is None else now
    with _lock:
        entry = _pages.pop(_key(token), None)
    if entry is None or entry.expires_at <= moment:
        return None
    return entry.page


def clear() -> None:
    """Para los tests."""
    with _lock:
        _pages.clear()


class _Inventory(HTMLParser):
    """Lo que la pagina necesita ejecutar y a donde envia sus formularios."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.inline_scripts: list[str] = []
        self.handlers: list[str] = []
        self.script_origins: set[str] = set()
        self.form_origins: set[str] = set()
        self._in_script = False
        self._script = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value or "" for name, value in attrs}
        for name, value in values.items():
            if name.startswith("on") and value:
                self.handlers.append(value)
        if tag == "script":
            src = values.get("src")
            if src:
                origin = _origin(src)
                if origin:
                    self.script_origins.add(origin)
            else:
                self._in_script, self._script = True, ""
        elif tag == "form":
            origin = _origin(values.get("action", ""))
            if origin:
                self.form_origins.add(origin)

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script += data

    def handle_entityref(self, name: str) -> None:
        if self._in_script:
            self._script += f"&{name};"

    def handle_charref(self, name: str) -> None:
        if self._in_script:
            self._script += f"&#{name};"

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_script:
            self.inline_scripts.append(self._script)
            self._in_script = False


def _origin(url: str, *, allow_http: bool = False) -> str | None:
    """El origen de una URL absoluta por HTTPS. Una relativa no cuenta, ni una
    por HTTP salvo `allow_http` (el frontend en desarrollo y en las pruebas)."""
    parts = urlsplit(url.strip())
    schemes = ("https", "http") if allow_http else ("https",)
    if parts.scheme not in schemes or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _hash(source: str) -> str:
    digest = hashlib.sha256(source.encode()).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


def page_csp(html: str, *, form_origins: tuple[str, ...] = ()) -> str:
    """La CSP de la pagina de pago.

    - Scripts: solo los de la pagina, por su huella; los manejadores en linea
      (`onload=...`) con `unsafe-hashes`, que tambien los limita a su huella.
    - Formularios: a `self` (la pasarela simulada), a los origenes HTTPS de
      los formularios que trae la pagina (el TPV de Redsys, por ejemplo) y a
      `form_origins`. Chrome aplica `form-action` tambien a las redirecciones
      que siguen al envio: si la respuesta del procesador redirige de vuelta a
      la aplicacion, el origen del frontend tiene que estar.
    - Nada de marcos, ni `base`, ni conexiones.
    """
    inventory = _Inventory()
    inventory.feed(html)
    inventory.close()
    sources = sorted({_hash(s) for s in inventory.inline_scripts})
    if inventory.handlers:
        sources += ["'unsafe-hashes'", *sorted({_hash(h) for h in inventory.handlers})]
    sources += sorted(inventory.script_origins)
    script_src = " ".join(sources) if sources else "'none'"
    form_action = " ".join(["'self'", *sorted(inventory.form_origins | set(form_origins))])
    return "; ".join(
        (
            "default-src 'none'",
            f"script-src {script_src}",
            "style-src 'unsafe-inline'",
            "img-src https: data:",
            f"form-action {form_action}",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        )
    )
