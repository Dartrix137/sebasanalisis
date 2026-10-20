"""Panel de administracion: CRUD de juegos/variantes y backtest del motor (§3.4).

Los usuarios y la bitacora viven en `admin_users.py`; los documentos legales, en
`admin_legal.py`.

El MVP usa un formulario estructurado simple, NO un builder visual de categorias
(decision explicita de CLAUDE.md). Toda `categories_json` que entre por aqui pasa
por `validate_game_config` antes de persistir: una configuracion mal formada que
se guarda en silencio rompe `engine/probability.py` sin error visible.
"""

from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser, DbSession
from app.api.game_modules import implemented
from app.api.v1.admin_users import Limit, Offset
from app.api.v1.legal import client_ip
from app.core import audit
from app.core.game_config_validation import check_payouts_against_house_edge
from app.engine.backtest import WARMUP, backtest, fair_wheel_histories
from app.engine.probability import GameConfig
from app.engine.recommendation import SignalBand as EngineSignalBand
from app.engine.recommendation import weak_threshold_for
from app.models import Game, GameSession, GameVariant, Spin
from app.schemas.games import (
    AdminGameListResponse,
    CreateGameRequest,
    CreateGameVariantRequest,
    GameModule,
    GameResponse,
    GameStatus,
    GameVariantConfig,
    GameVariantResponse,
    UpdateGameRequest,
    UpdateGameVariantRequest,
)
from app.schemas.suggestions import BacktestBandRow, BacktestReport, BacktestTally

router = APIRouter(prefix="/admin", tags=["admin"])


class BacktestSource(str, Enum):
    """Sobre que historiales corre el backtest.

    `sessions` son datos reales, fuera de calibracion por construccion.
    `simulated` es la linea base: ruedas justas donde el ROI tiene que quedarse
    en la ventaja de la casa.
    """

    sessions = "sessions"
    simulated = "simulated"


def _validate_config_or_422(
    game: Game, config: GameVariantConfig, house_edge: float
) -> list[str]:
    """Bloquea si hay errores; devuelve los avisos para informarlos al admin.

    El validador es el del modulo del juego (`api/game_modules.py`).
    """
    modulo = implemented(game.module)
    if modulo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El módulo '{game.module}' no está implementado",
        )
    result = modulo.validate_config(config)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "La configuración del juego no es válida",
                "errors": result.errors,
            },
        )
    return result.warnings + check_payouts_against_house_edge(config, house_edge)


def _game_or_404(db: DbSession, game_id: UUID) -> Game:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Juego no encontrado")
    return game


_GAME_SNAPSHOT_FIELDS = (
    "name",
    "type",
    "slug",
    "module",
    "description",
    "icon",
    "sort_order",
    "status",
)


def _game_snapshot(game: Game) -> dict[str, Any]:
    return {f: getattr(game, f) for f in _GAME_SNAPSHOT_FIELDS}


# ---------- Juegos ----------


@router.get("/games", response_model=AdminGameListResponse)
def list_admin_games(
    db: DbSession,
    admin: AdminUser,
    limit: Limit = 50,
    offset: Offset = 0,
    status_filter: Annotated[GameStatus | None, Query(alias="status")] = None,
    module: GameModule | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> AdminGameListResponse:
    """Todos los juegos, en el orden del menu, con todas sus variantes."""
    filtros = []
    if status_filter is not None:
        filtros.append(Game.status == status_filter)
    if module is not None:
        filtros.append(Game.module == module)
    if q and q.strip():
        patron = f"%{q.strip()}%"
        filtros.append(or_(Game.name.ilike(patron), Game.slug.ilike(patron)))
    total = db.scalar(select(func.count()).select_from(Game).where(*filtros)) or 0
    games = db.scalars(
        select(Game)
        .options(selectinload(Game.variants))
        .where(*filtros)
        .order_by(Game.sort_order, Game.name)
        .limit(limit)
        .offset(offset)
    )
    return AdminGameListResponse(
        items=[GameResponse.model_validate(g) for g in games],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/games", response_model=GameResponse, status_code=status.HTTP_201_CREATED)
def create_game(
    payload: CreateGameRequest, db: DbSession, admin: AdminUser, request: Request
) -> Game:
    """Crea un juego. Su modulo tiene que estar implementado (§7.3).

    Deja fila en la bitacora: un juego que nace activo ya lo ven los clientes.
    """
    if implemented(payload.module) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"El módulo '{payload.module}' está reservado y todavía no tiene "
                "implementación: no se puede crear un juego con él"
            ),
        )
    if db.scalar(select(Game.id).where(Game.type == payload.type)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un juego con el tipo '{payload.type}'",
        )
    if db.scalar(select(Game.id).where(Game.slug == payload.slug)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un juego con el slug '{payload.slug}'",
        )
    game = Game(**payload.model_dump(exclude={"reason"}))
    game.name = game.name.strip()
    game.description = game.description.strip()
    db.add(game)
    db.flush()
    audit.record(
        db,
        admin,
        action="game.create",
        target_type="game",
        target_id=game.id,
        after=_game_snapshot(game),
        reason=payload.reason.strip(),
        ip=client_ip(request),
    )
    db.commit()
    db.refresh(game)
    return game


@router.patch("/games/{game_id}", response_model=GameResponse)
def update_game(
    game_id: UUID, payload: UpdateGameRequest, db: DbSession, admin: AdminUser, request: Request
) -> Game:
    """Edita un juego. El tipo, el slug y el modulo no cambian.

    Un cambio de estado pide motivo y deja fila en la bitacora
    (`game.status.update`): ocultar un juego o pasarlo a "proximamente" le quita
    la mesa nueva a los clientes. Los demas campos son de presentacion y no la
    dejan.
    """
    game = _game_or_404(db, game_id)
    before = _game_snapshot(game)
    cambios = payload.model_dump(exclude_unset=True, exclude={"reason"})
    for campo, valor in cambios.items():
        if valor is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El campo {campo} no puede quedar vacío",
            )
        setattr(game, campo, valor.strip() if isinstance(valor, str) else valor)
    after = _game_snapshot(game)
    if after == before:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No hay nada que cambiar")

    if after["status"] != before["status"]:
        if payload.reason is None or not payload.reason.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cambiar el estado de un juego pide un motivo",
            )
        audit.record(
            db,
            admin,
            action="game.status.update",
            target_type="game",
            target_id=game.id,
            before={"status": before["status"]},
            after={"status": after["status"]},
            reason=payload.reason.strip(),
            ip=client_ip(request),
        )
    db.commit()
    db.refresh(game)
    return game


# ---------- Variantes ----------


@router.post(
    "/games/{game_id}/variants",
    response_model=GameVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_variant(
    game_id: UUID, payload: CreateGameVariantRequest, db: DbSession, admin: AdminUser
) -> GameVariant:
    game = _game_or_404(db, game_id)
    if db.scalar(
        select(GameVariant).where(
            GameVariant.game_id == game_id, GameVariant.name == payload.name
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El juego ya tiene una variante llamada '{payload.name}'",
        )
    _validate_config_or_422(game, payload.config, payload.house_edge)
    variant = GameVariant(
        game_id=game_id,
        name=payload.name,
        description=payload.description.strip(),
        sort_order=payload.sort_order,
        house_edge=payload.house_edge,
        categories_json=payload.config.model_dump(),
        active=payload.active,
    )
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


@router.patch("/games/{game_id}/variants/{variant_id}", response_model=GameVariantResponse)
def update_variant(
    game_id: UUID,
    variant_id: UUID,
    payload: UpdateGameVariantRequest,
    db: DbSession,
    admin: AdminUser,
) -> GameVariant:
    variant = db.get(GameVariant, variant_id)
    if variant is None or variant.game_id != game_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variante no encontrada")

    cambios = payload.model_dump(exclude_unset=True)

    if payload.name is not None and payload.name != variant.name:
        if db.scalar(
            select(GameVariant).where(
                GameVariant.game_id == game_id, GameVariant.name == payload.name
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El juego ya tiene una variante llamada '{payload.name}'",
            )

    if payload.config is not None:
        # El house_edge contra el que se validan los pagos es el nuevo si viene
        # en el mismo request, y el ya persistido si no.
        house_edge = (
            payload.house_edge if payload.house_edge is not None else float(variant.house_edge)
        )
        _validate_config_or_422(variant.game, payload.config, house_edge)
        variant.categories_json = payload.config.model_dump()
    cambios.pop("config", None)

    for campo, valor in cambios.items():
        setattr(variant, campo, valor)
    db.commit()
    db.refresh(variant)
    return variant


# ---------- Metricas internas del motor (§2.10) ----------


@router.get("/recommendations/backtest", response_model=BacktestReport)
def recommendation_backtest(
    db: DbSession,
    admin: AdminUser,
    variant_id: UUID | None = Query(
        default=None, description="Variante a evaluar. Por defecto, la primera activa."
    ),
    source: BacktestSource = Query(
        default=BacktestSource.sessions,
        description=(
            "`sessions` corre sobre las sesiones reales de los usuarios; "
            "`simulated` sobre ruedas justas generadas, como linea base."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=500),
    spins: int = Query(default=150, ge=20, le=500),
    threshold: float | None = Query(default=None, ge=0, le=100),
    weak_threshold: float | None = Query(default=None, ge=0, le=100),
) -> BacktestReport:
    """Backtest del motor: cuanto recomienda, cuanto acierta y con que ROI.

    Es la validacion de §9 del comparativo y **no se muestra al cliente**.

    La honestidad de la medicion depende de una sola cosa: que los historiales no
    sean los que se usaron para calibrar los pesos. Las sesiones reales lo
    cumplen por construccion (los pesos se fijaron sobre simulaciones, antes de
    que existieran). Las ruedas simuladas usan una semilla propia y sirven de
    linea base: ahi el ROI TIENE que quedarse en la ventaja de la casa, y si no
    lo hace es que algo esta mal medido.
    """
    variant = (
        db.get(GameVariant, variant_id)
        if variant_id is not None
        else db.scalars(select(GameVariant).where(GameVariant.active)).first()
    )
    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variante no encontrada"
        )

    config = GameConfig.from_dict(variant.categories_json)
    umbral = threshold if threshold is not None else config.recommendation_threshold
    umbral_debil = weak_threshold_for(
        weak_threshold if weak_threshold is not None else config.weak_threshold, umbral
    )

    if source is BacktestSource.simulated:
        historiales = fair_wheel_histories(config, limit, spins, seed=90_217)
        origen = f"{limit} ruedas justas simuladas de {spins} giros"
    else:
        sesiones = db.scalars(
            select(GameSession.id)
            .where(GameSession.game_variant_id == variant.id)
            .limit(limit)
        ).all()
        historiales = []
        for sid in sesiones:
            giros = list(
                db.scalars(
                    select(Spin.result_value)
                    .where(Spin.session_id == sid)
                    .order_by(Spin.spin_index.asc())
                )
            )
            if len(giros) > WARMUP:
                historiales.append(giros)
        origen = f"{len(historiales)} sesiones reales de {variant.name}"

    informe = backtest(
        config, historiales, threshold=umbral, weak_threshold=umbral_debil
    )

    def _tally(t) -> dict:
        return {
            "recommendations": t.recommendations,
            "hits": t.hits,
            "misses": t.misses,
            "hit_rate": t.hit_rate,
            "units": round(t.units, 2),
            "roi": t.roi,
            "max_drawdown": round(t.max_drawdown, 2),
        }

    return BacktestReport(
        source=origen,
        sessions=len(historiales),
        spins_evaluated=informe.spins_evaluated,
        decisions=informe.decisions,
        recommendations=informe.overall.recommendations,
        no_bets=informe.no_bets,
        no_bet_rate=informe.no_bet_rate,
        threshold=umbral,
        weak_threshold=umbral_debil,
        overall=BacktestTally(**_tally(informe.overall)),
        by_band=[
            BacktestBandRow(
                band=banda.value,
                no_bets=informe.no_bet_by_band[banda],
                **_tally(informe.by_band[banda]),
            )
            for banda in EngineSignalBand
        ],
        house_edge_reference=-1 / len(config.possible_outcomes),
    )
