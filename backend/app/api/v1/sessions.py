"""Router de sesiones de mesa y de los giros que se registran en ellas.

Todos los numeros los ingresa el usuario a mano: giro a giro durante la sesion,
o de una vez con la carga inicial al abrirla (§3.5). El proyecto no lee
pantallazos ni llama a ninguna IA.

Regla de §3.6: toda consulta filtra por el `user_id` del token. Nunca se resuelve
una sesion por el id de la URL sin comprobar quien es el dueno.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession
from app.models import Bet, GameSession, GameVariant, Spin
from app.schemas.games import GameVariantConfig
from app.schemas.sessions import (
    BankrollStrategy,
    CreateSessionRequest,
    SessionResponse,
    SessionStatus,
    SessionSummaryResponse,
    StrategyMode,
    UpdateSessionRequest,
)
from app.engine.bulk_entry import EntryOrder, prepare_bulk_entry
from app.engine.probability import GameConfig
from app.schemas.spins import BulkSpinsRequest, BulkSpinsResponse, CreateSpinRequest, SpinResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_owned_session(db: DbSession, user_id: UUID, session_id: UUID) -> GameSession:
    """Carga una sesion comprobando que pertenezca al usuario.

    Devuelve 404 (no 403) cuando la sesion es de otro: confirmar que existe pero
    es ajena filtraria informacion.
    """
    session = db.scalar(
        select(GameSession).where(
            GameSession.id == session_id, GameSession.user_id == user_id
        )
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesion no encontrada")
    return session


def require_active(session: GameSession) -> GameSession:
    """Una sesion cerrada es historico: no admite giros ni cambios de configuracion."""
    if session.status != SessionStatus.active.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La sesion ya no esta abierta",
        )
    return session


# ---------- Sesiones ----------


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: CreateSessionRequest, db: DbSession, user: CurrentUser) -> GameSession:
    # `validate_bet_within_bankroll` es un metodo normal del schema, no un
    # validador de Pydantic: si no se llama aqui, nunca corre.
    try:
        payload.validate_bet_within_bankroll()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    variant = db.get(GameVariant, payload.game_variant_id)
    if variant is None or not variant.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variante de juego no disponible"
        )

    session = GameSession(
        user_id=user.id,
        game_variant_id=variant.id,
        name=payload.name,
        status=SessionStatus.active.value,
        window_size=payload.window_size,
        bankroll_start=payload.bankroll_start,
        bankroll_current=payload.bankroll_start,
        base_bet=payload.base_bet,
        table_limit=payload.table_limit,
        loss_limit=payload.loss_limit,
        strategy_selected=payload.strategy.value,
        strategy_mode=payload.strategy_mode.value,
        strategy_stage=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    db: DbSession,
    user: CurrentUser,
    status_filter: SessionStatus | None = Query(
        default=None,
        alias="status",
        description="Filtra por estado. Sin el, devuelve todas las del usuario.",
    ),
) -> list[GameSession]:
    stmt = (
        select(GameSession)
        .where(GameSession.user_id == user.id)
        .order_by(GameSession.started_at.desc())
    )
    if status_filter is not None:
        stmt = stmt.where(GameSession.status == status_filter.value)
    return list(db.scalars(stmt))


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID, db: DbSession, user: CurrentUser) -> GameSession:
    return get_owned_session(db, user.id, session_id)


def _check_loss_limit_change(session: GameSession, nuevo: float | None) -> None:
    """Un limite de perdida se puede fijar o bajar, nunca subir ni quitar.

    Es la regla del documento verificado (§9): "no aumentes el limite para
    recuperar perdidas". Si se pudiera subir a mitad de sesion, el limite dejaria
    de ser una decision tomada antes de jugar.
    """
    actual = float(session.loss_limit) if session.loss_limit is not None else None
    if actual is not None and (nuevo is None or nuevo > actual):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "El límite de pérdida se puede bajar, pero no subir ni quitar con la "
                "sesión abierta: aumentarlo para recuperar es justo lo que el límite "
                "busca evitar. Si quieres otro límite, cierra esta sesión y abre una nueva."
            ),
        )
    if nuevo is not None and nuevo > float(session.bankroll_start):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El límite de pérdida no puede superar la banca inicial",
        )


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: UUID, payload: UpdateSessionRequest, db: DbSession, user: CurrentUser
) -> GameSession:
    session = require_active(get_owned_session(db, user.id, session_id))
    cambios = payload.model_dump(exclude_unset=True)

    # El validador del schema solo cruza modo y estrategia cuando el request trae
    # ambos. Si viene uno solo hay que combinarlo con lo ya persistido, o el
    # CHECK de §2.8 rechazaria el UPDATE con un 500 en vez de un 422 explicativo.
    nuevo_modo = payload.strategy_mode or StrategyMode(session.strategy_mode)
    nueva_estrategia = payload.strategy or BankrollStrategy(session.strategy_selected)
    if (nuevo_modo is StrategyMode.two_sector) != (
        nueva_estrategia is BankrollStrategy.two_sector_recovery
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La combinacion strategy_mode='{nuevo_modo.value}' con "
                f"strategy='{nueva_estrategia.value}' no es valida (§2.8): el modo "
                "dos-sectores exige la progresion 'two_sector_recovery' y esa "
                "progresion no aplica en modo 1:1"
            ),
        )

    cambia_progresion = (
        nueva_estrategia.value != session.strategy_selected
        or nuevo_modo.value != session.strategy_mode
    )
    cambios.pop("strategy", None)
    cambios.pop("strategy_mode", None)
    if cambia_progresion:
        session.strategy_selected = nueva_estrategia.value
        session.strategy_mode = nuevo_modo.value
        # Cambiar de estrategia reinicia la progresion: mantener el escalon de la
        # anterior daria un tamano de apuesta que no corresponde a ninguna serie.
        # Se compara contra lo persistido porque el formulario reenvia la
        # estrategia aunque solo se haya tocado otro campo.
        session.strategy_stage = 0
        # Por lo mismo, deshacer un giro anterior al cambio no puede devolver un
        # escalon de la progresion vieja: esos giros dejan de restaurarlo.
        db.execute(
            update(Spin)
            .where(Spin.session_id == session.id)
            .values(strategy_stage_before=None)
        )

    if "loss_limit" in cambios:
        _check_loss_limit_change(session, cambios["loss_limit"])

    for campo, valor in cambios.items():
        setattr(session, campo, valor)

    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/close", response_model=SessionResponse)
def close_session(session_id: UUID, db: DbSession, user: CurrentUser) -> GameSession:
    """Cierra la sesion. Las apuestas pendientes quedan canceladas, no resueltas.

    Nunca llego el giro que las resolveria, asi que darlas por ganadas o perdidas
    seria inventar un resultado.
    """
    session = require_active(get_owned_session(db, user.id, session_id))
    session.status = SessionStatus.closed.value
    session.closed_at = datetime.now(UTC)

    for pendiente in db.scalars(
        select(Bet).where(Bet.session_id == session.id, Bet.status == "pending")
    ):
        pendiente.status = "cancelled"

    db.commit()
    db.refresh(session)
    return session


@router.get("/{session_id}/summary", response_model=SessionSummaryResponse)
def session_summary(
    session_id: UUID, db: DbSession, user: CurrentUser
) -> SessionSummaryResponse:
    """Resumen de la sesion: cuanto se jugo y como termino la banca.

    Solo describe lo que ya paso. `win_rate` es la proporcion de apuestas
    resueltas que se ganaron en esta sesion — no es una tasa de acierto del
    motor ni dice nada sobre las proximas.
    """
    session = get_owned_session(db, user.id, session_id)

    total_giros = db.scalar(
        select(func.count()).select_from(Spin).where(Spin.session_id == session.id)
    )
    apuestas = list(
        db.scalars(
            select(Bet)
            .where(Bet.session_id == session.id, Bet.status == "resolved")
            .order_by(Bet.resolved_at)
        )
    )

    ganadas = sum(1 for b in apuestas if b.won)
    seguidas = sum(1 for b in apuestas if b.followed_suggestion)
    inicial = float(session.bankroll_start)
    actual = float(session.bankroll_current)

    # Maxima caida desde un pico previo: el peor bajon que se vivio dentro de la
    # sesion, que un neto final positivo puede esconder por completo.
    pico = saldo = inicial
    caida_maxima = 0.0
    for b in apuestas:
        saldo += float(b.net_change or 0)
        pico = max(pico, saldo)
        caida_maxima = max(caida_maxima, pico - saldo)

    fin = session.closed_at or datetime.now(UTC)
    minutos = (fin - session.started_at).total_seconds() / 60

    return SessionSummaryResponse(
        session_id=session.id,
        duration_minutes=round(minutos, 1),
        total_spins=total_giros or 0,
        total_bets=len(apuestas),
        win_rate=ganadas / len(apuestas) if apuestas else 0.0,
        bankroll_start=inicial,
        bankroll_final=actual,
        net_change=round(actual - inicial, 2),
        strategy_used=BankrollStrategy(session.strategy_selected),
        max_drawdown=round(caida_maxima, 2),
        followed_suggestion_rate=seguidas / len(apuestas) if apuestas else 0.0,
    )


@router.post("/{session_id}/reset-strategy", response_model=SessionResponse)
def reset_strategy(session_id: UUID, db: DbSession, user: CurrentUser) -> GameSession:
    """Vuelve la progresion al escalon inicial sin tocar la banca ni los giros."""
    session = require_active(get_owned_session(db, user.id, session_id))
    session.strategy_stage = 0
    db.commit()
    db.refresh(session)
    return session


# ---------- Giros ----------


@router.get("/{session_id}/spins", response_model=list[SpinResponse])
def list_spins(session_id: UUID, db: DbSession, user: CurrentUser) -> list[Spin]:
    """Orden cronologico ascendente: `spin_index` creciente va del mas antiguo al
    mas reciente. La UI que quiera mostrar "mas reciente primero" invierte al
    pintar, no en la base."""
    session = get_owned_session(db, user.id, session_id)
    return list(
        db.scalars(
            select(Spin).where(Spin.session_id == session.id).order_by(Spin.spin_index)
        )
    )


@router.post(
    "/{session_id}/spins", response_model=SpinResponse, status_code=status.HTTP_201_CREATED
)
def create_spin(
    session_id: UUID, payload: CreateSpinRequest, db: DbSession, user: CurrentUser
) -> Spin:
    session = require_active(get_owned_session(db, user.id, session_id))
    variant = db.get(GameVariant, session.game_variant_id)
    config = GameVariantConfig.model_validate(variant.categories_json)

    if payload.result_value not in config.possible_outcomes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"'{payload.result_value}' no es un resultado posible de esta variante"
            ),
        )

    ultimo = db.scalar(
        select(func.max(Spin.spin_index)).where(Spin.session_id == session.id)
    )
    spin = Spin(
        session_id=session.id,
        spin_index=0 if ultimo is None else ultimo + 1,
        result_value=payload.result_value,
        source=payload.source.value,
        # Se guarda antes de resolver nada, para poder volver aqui si se deshace.
        strategy_stage_before=session.strategy_stage,
    )
    db.add(spin)
    db.flush()  # asigna el id del giro, que la resolucion necesita

    # Las apuestas pendientes se resuelven contra este giro. Importado aqui y no
    # arriba porque `bets` importa este modulo: es una dependencia circular.
    from app.api.v1.bets import resolve_pending_bets

    resolve_pending_bets(db, session, GameConfig.from_dict(variant.categories_json), spin)

    db.commit()
    db.refresh(spin)
    return spin


@router.post(
    "/{session_id}/spins/bulk",
    response_model=BulkSpinsResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_spins_bulk(
    session_id: UUID, payload: BulkSpinsRequest, db: DbSession, user: CurrentUser
) -> BulkSpinsResponse:
    """Carga inicial: registra de una vez los numeros ya observados en la mesa.

    El usuario declara en que orden los escribio y el backend normaliza siempre a
    orden cronologico ascendente antes de guardar (§3.5). Adivinar el orden no es
    aceptable: el motor pondera por recencia, asi que invertirlo en silencio da
    un analisis equivocado sin ningun error visible.
    """
    session = require_active(get_owned_session(db, user.id, session_id))
    variant = db.get(GameVariant, session.game_variant_id)
    config = GameConfig.from_dict(variant.categories_json)

    try:
        resultado = prepare_bulk_entry(
            config, payload.values, EntryOrder(payload.order.value)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if not resultado.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Hay valores que no pertenecen a esta variante",
                "errors": resultado.invalid_values,
            },
        )

    ultimo = db.scalar(
        select(func.max(Spin.spin_index)).where(Spin.session_id == session.id)
    )
    siguiente = 0 if ultimo is None else ultimo + 1

    giros = [
        Spin(
            session_id=session.id,
            spin_index=siguiente + i,
            result_value=valor,
            source="initial_batch",
        )
        for i, valor in enumerate(resultado.values)
    ]
    db.add_all(giros)
    db.commit()
    for g in giros:
        db.refresh(g)

    return BulkSpinsResponse(created=len(giros), spins=giros)


@router.delete("/{session_id}/spins/{spin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_spin(
    session_id: UUID, spin_id: UUID, db: DbSession, user: CurrentUser
) -> Response:
    """Deshacer: solo se puede borrar el ultimo giro.

    Borrar uno del medio dejaria huecos en `spin_index`, y el decaimiento por
    recencia (§2.3) pesa cada observacion por su antiguedad — un hueco
    desplazaria en silencio el peso de todos los giros posteriores.

    Si el giro habia resuelto apuestas, deshacerlo tiene que deshacer tambien su
    efecto: las apuestas vuelven a estar pendientes, la banca recupera lo que
    movieron y el escalon vuelve al que habia antes. Lo que se deshace es el
    numero mal tecleado, no la apuesta — esa se hizo de verdad y sigue viva.
    """
    session = require_active(get_owned_session(db, user.id, session_id))
    spin = db.scalar(
        select(Spin).where(Spin.id == spin_id, Spin.session_id == session.id)
    )
    if spin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Giro no encontrado")

    ultimo = db.scalar(
        select(func.max(Spin.spin_index)).where(Spin.session_id == session.id)
    )
    if spin.spin_index != ultimo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se puede deshacer el ultimo giro registrado",
        )

    # Deshacer el efecto del giro antes de borrarlo.
    for bet in db.scalars(
        select(Bet).where(Bet.spin_id == spin.id, Bet.status == "resolved")
    ):
        session.bankroll_current = float(session.bankroll_current) - float(
            bet.net_change or 0
        )
        bet.status = "pending"
        bet.spin_id = None
        bet.won = None
        bet.payout = None
        bet.net_change = None
        bet.resolved_at = None

    if spin.strategy_stage_before is not None:
        session.strategy_stage = spin.strategy_stage_before

    db.delete(spin)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
