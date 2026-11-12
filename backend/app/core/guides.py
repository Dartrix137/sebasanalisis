"""Las guias de uso de cada juego: videos de YouTube y un PDF (2026-11-12).

Decidido por el usuario: los videos van en YouTube como "no listados", y se
incrustan desde `www.youtube-nocookie.com` (el modo de privacidad mejorada); el
PDF va en Cloudinary. Los dos son terceros: estan en las politicas de cookies y
de datos, y cambiar de proveedor pide una version nueva de esas politicas.

El catalogo vive en codigo, por el `type` del juego (unico y estable; el
`module` lo comparten la ruleta y los juegos discretos futuros). No son
secretos, pero solo viajan por `GET /games/{slug}/guides`, que exige acceso:
asi no quedan en el bundle publico del frontend.

Los textos se revisan contra la regla de lenguaje no predictivo (CLAUDE.md).
"""

import re
from dataclasses import dataclass

YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PDF_URL_PREFIX = "https://res.cloudinary.com/"


@dataclass(frozen=True)
class GuideVideo:
    title: str
    youtube_id: str


@dataclass(frozen=True)
class GuidePdf:
    title: str
    url: str


@dataclass(frozen=True)
class GameGuides:
    videos: tuple[GuideVideo, ...]
    pdf: GuidePdf | None


# Un juego sin entrada no tiene guias: el endpoint responde la lista vacia y la
# ventana del inicio no se abre.
GUIDES: dict[str, GameGuides] = {
    "roulette": GameGuides(
        videos=(
            GuideVideo(title="Parte 1", youtube_id="fzoc2zF5Lsg"),
            GuideVideo(title="Parte 2", youtube_id="wpRE5B5gYtI"),
        ),
        # `fl_attachment` hace que Cloudinary lo entregue como descarga.
        pdf=GuidePdf(
            title="la guía paso a paso (PDF)",
            url=(
                "https://res.cloudinary.com/zs841cjr/image/upload/fl_attachment/"
                "v1794508519/GU%C3%8DA_PASO_A_PASO_PARA_UTILIZAR_EL_BOT.pdf"
            ),
        ),
    ),
}


def guides_for(game_type: str) -> GameGuides:
    """Las guias de un juego por su `type`, o ninguna."""
    return GUIDES.get(game_type, GameGuides(videos=(), pdf=None))


def validate(guides: GameGuides) -> None:
    """Falla si un id de YouTube o la URL del PDF no tienen la forma esperada.

    Lo corren los tests sobre todo el catalogo: un id mal copiado no se
    descubre en produccion con un recuadro de "video no disponible".
    """
    for video in guides.videos:
        if not YOUTUBE_ID.fullmatch(video.youtube_id):
            raise ValueError(f"Id de YouTube invalido: {video.youtube_id!r}")
    if guides.pdf is not None and not guides.pdf.url.startswith(PDF_URL_PREFIX):
        raise ValueError(f"El PDF no esta en Cloudinary: {guides.pdf.url!r}")
