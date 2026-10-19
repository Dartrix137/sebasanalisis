# Sebasanálisis — Fase 4: de MVP a plataforma completa

> Especificación de la fase que convierte el MVP aprobado en una plataforma comercial: cobro por suscripción con Wompi, panel de administración completo, cuentas con verificación y recuperación, términos y políticas, y una base de juegos que no dependa de la ruleta.
>
> El avance paso a paso y el contexto de las etapas anteriores están en `docs/HOJA_DE_RUTA.md`; al cerrar un paso de §9 se marca allá.
>
> Complementa a `docs/ARQUITECTURA_Y_ESTADISTICA.md`, no lo reemplaza: el motor, sus fórmulas y la Fase 3 siguen definidos allá. Si este documento y aquel parecen contradecirse, gana el de arquitectura hasta que el usuario aclare.
>
> Redactado el 2026-10-02. Actualizado el 2026-10-05: se agrega la Fase 0 de preparación del stack (§13), el generador de tipos y dos ajustes al orden de construcción (§9).

---

## Índice

0. [Propósito y reglas que se heredan](#0-propósito-y-reglas-que-se-heredan)
1. [Estado de partida](#1-estado-de-partida)
2. [Modelo de acceso](#2-modelo-de-acceso)
3. [Pagos y suscripciones con Wompi](#3-pagos-y-suscripciones-con-wompi) (la entrega 1 del paso 5 está en §3.12; la tokenización con un formulario propio, en §3.16)
4. [Admin dashboard](#4-admin-dashboard) (las tres entregas del paso 6 están en §4.8, §4.9 y §4.10)
5. [Mejoras de autenticación](#5-mejoras-de-autenticación)
6. [Términos, condiciones y políticas](#6-términos-condiciones-y-políticas)
7. [Plataforma multijuego](#7-plataforma-multijuego)
8. [Base para apuestas deportivas](#8-base-para-apuestas-deportivas) (lo decidido en el paso 8 está en §8.4)
9. [Orden de construcción](#9-orden-de-construcción)
10. [Decisiones pendientes](#10-decisiones-pendientes)
11. [Endpoints nuevos](#11-endpoints-nuevos)
12. [Variables de entorno nuevas](#12-variables-de-entorno-nuevas)
13. [Fase 0: preparación del stack](#13-fase-0-preparación-del-stack)

---

## 0. Propósito y reglas que se heredan

El núcleo (los ocho pasos del MVP más la Fase 3, motor de recomendación; ver `docs/HOJA_DE_RUTA.md` §3) está aprobado. La Fase 4 no toca el motor: construye todo lo que hace falta alrededor para venderlo.

### Decisiones cerradas (2026-10-02)

| Tema | Decisión |
|---|---|
| Modalidad de cobro | **Dos modos** (ampliado el 2026-10-08, ver §3.10): **renovación automática** con una fuente de pago tokenizada en Wompi, donde el backend cobra cada período sin intervención del usuario; y **pago manual mes a mes**, para quien no tiene o no quiere tokenizar un medio de pago. |
| Cuenta recién registrada | **Sin acceso hasta pagar.** La única otra vía es el acceso manual que otorga un administrador. Desaparece la prueba gratuita (`trial`). |
| Envío de correo | **SMTP genérico.** El código habla con una interfaz, no con un proveedor; el proveedor concreto es configuración. |
| Apuestas deportivas | **Solo se deja la base lista** y se documentan las preguntas abiertas. No se construye en esta fase. |
| Tipos del cliente API (2026-10-05) | **Se generan desde el OpenAPI de FastAPI** con `openapi-typescript`; deja de mantenerse a mano `frontend/lib/types/`. Detalle en §13.2. |
| Proveedor de correo (2026-10-05) | **Resend**, por su relay SMTP, sujeto a que confirme que su política de uso admite el producto. Detalle en §13.6. |
| Monitoreo de errores (2026-10-05) | **GlitchTip autohospedado** en el mismo VPS. Detalle en §13.6. |
| Tests de frontend (2026-10-05) | **Playwright**, sobre los flujos críticos. Detalle en §13.3. |

### Reglas que siguen vigentes

- **Lenguaje no predictivo** (§0 del doc de arquitectura y `CLAUDE.md`). Aplica también, y con más razón, a lo nuevo: página de planes, correos transaccionales, textos legales, nombres de planes y de cupones. Ningún plan "da ventaja", ningún correo promete resultados.
- **Montos en enteros (centavos)** con la moneda explícita en el campo. Nunca `float`, ni en la base, ni en los schemas, ni en el frontend.
- **El acceso se decide siempre en el servidor.** El cliente puede ocultar o mostrar botones, pero ninguna decisión de acceso depende de lo que mande.
- **Secretos solo por variable de entorno.** `.env.example` lista nombres, nunca valores.
- **Motor puro y genérico** (`backend/app/engine/`): nada de esta fase entra al motor. La lógica de cobros, precios y descuentos que sea cálculo puro (precio con cupón, fechas de período, calendario de reintentos) vive en su propio módulo puro, `backend/app/billing/`, con la misma disciplina: sin DB, sin red, testeable con pytest.
- **Migraciones**: una por cambio lógico, downgrade probado (`alembic upgrade head` sobre base limpia y `alembic downgrade -1`), backfills separados del DDL, nunca editar una migración ya aplicada.
- **Tipos regenerados en el mismo commit** que cualquier cambio de schema: `apiFetch` no valida en runtime y un tipo desincronizado se ve como `undefined` en producción. Desde la Fase 0 (§13.2) eso significa correr `npm run gen:types` y commitear el resultado; el CI falla si quedó desactualizado. Hasta que la Fase 0 esté hecha, sigue valiendo la sincronización manual con la skill `api-schema-sync`.

---

## 1. Estado de partida

Lo que el MVP ya tiene y lo que falta, revisado contra el código el 2026-10-02.

| Área | Estado actual | Consecuencia para la Fase 4 |
|---|---|---|
| **Control de acceso** | `users.access_type` (`trial \| invited \| full`) existe, pero **no se verifica en ningún endpoint**. `api/deps.py` solo tiene `get_current_user` y `require_admin`. Cualquier cuenta registrada usa la mesa. | Es el hueco más importante: hay que cerrarlo antes de cobrar, o el pago no compra nada. §2. |
| **Suscripciones y pagos** | Tablas `subscriptions` y `payment_events` creadas sin lógica (`models/user.py`). `subscriptions.plan_id` es un `String` suelto; `payment_events.subscription_id` es NOT NULL. | `plan_id` pasa a FK de `plans`. `subscription_id` debe ser nullable: un evento de una referencia desconocida tiene que poder quedar registrado para auditarlo. §3. |
| **Verificación de correo** | `users.email_verified` existe, siempre en `False`. No hay envío de correo. | Se implementa. §5. |
| **Recuperación de contraseña** | No existe. | Se implementa. §5. |
| **Revocación de sesiones** | JWT sin estado (`core/security.py`): un refresh token vale 30 días pase lo que pase. | Cambiar la contraseña tiene que cerrar las demás sesiones. §5. |
| **Rate limit** | Solo en login, en memoria y por proceso (`core/rate_limit.py`). | Se extiende a los endpoints nuevos sensibles. §5. |
| **Páginas legales** | No existe ninguna. Tampoco el onboarding scroll-to-accept ni la página de Juego Responsable que exige §0 del doc de arquitectura (esta última se descartó el 2026-10-08). | Se construyen con versionado y registro de aceptación. §6. |
| **Admin** | Una sola página (`frontend/app/admin/page.tsx`) con juegos, variantes, usuarios y backtest. `GET /admin/users` devuelve todos, sin paginar. | Se reorganiza en secciones. §4. |
| **Multijuego** | El motor y `categories_json` ya son genéricos. El acoplamiento a ruleta está en el **frontend y el seed**: ruta `/games/roulette/[sessionId]`, `components/roulette/*`, `dashboard/page.tsx` redirige a `/games/roulette/…`. `lib/outcomes.ts` ya cae en `neutral` si no hay categoría `color`. | El trabajo es de frontend y de metadatos del juego, no del motor. §7. |

---

## 2. Modelo de acceso

Es la base de todo lo demás y por eso va primero en el diseño (aunque en el orden de construcción va después de auth y legal, ver §9).

### 2.1 Una sola función decide

```python
# backend/app/core/access.py
def has_access(user: User, now: datetime, game: Game | None = None) -> AccessDecision: ...
```

- Es la **única** fuente de verdad. Ningún endpoint repite la lógica.
- Devuelve una decisión con motivo (`admin`, `full`, `invited`, `subscription`, o el motivo de rechazo: `no_access`, `expired`, `suspended`, `email_not_verified`, `game_not_in_plan`, `consent_required`), para que el frontend muestre la pantalla correcta sin adivinar.
- Se expone como dependencia FastAPI `RequireAccess` y se aplica a **todos** los routers de juego: `games`, `sessions`, `suggestions`, `recommendations`, `bankroll`, `bets`. Responde `403` con el motivo.
- `GET /auth/me` incluye la decisión (`access: {granted, reason, until}`) para que el cliente sepa si mostrar la mesa o la página de planes. Es informativo: el servidor vuelve a decidir en cada llamada.

### 2.2 Fuentes de acceso

En este orden:

1. `users.is_active = false` → **sin acceso**, sin importar lo demás (cuenta suspendida por un admin).
2. Consentimiento legal vigente no aceptado → **sin acceso** hasta aceptar (§6.3).
3. `role = 'admin'` → acceso.
4. `access_type = 'full'` → acceso sin vencimiento (cortesías permanentes, equipo interno).
5. `access_type = 'invited'` y (`access_expires_at` es null o `> now`) → acceso.
6. Una suscripción con `status ∈ {active, canceled}` y `current_period_end > now` → acceso. `canceled` cuenta porque la cancelación es al final del período (§3.6).
7. Si se pasa `game`, se exige además que el plan de esa suscripción incluya el juego (§7.4). Los accesos manuales (`full`, `invited`) incluyen todos los juegos.
8. Cualquier otro caso → **sin acceso**.

La verificación del correo no da ni quita acceso a la mesa por sí sola: es requisito para **pagar** (§5.2). Como sin pago no hay acceso, en la práctica una cuenta sin verificar no entra a la mesa salvo acceso manual.

### 2.3 Cambios de datos

- `users.access_type`: pasa de `trial | invited | full` a **`none | invited | full`**, con `none` por defecto. `trial` desaparece porque ya no hay prueba gratuita.
- `users.access_expires_at` (nullable): vencimiento del acceso `invited`.
- `users.is_active` (default `true`): permite suspender una cuenta sin borrarla.
- Migraciones: una para el DDL (agregar `none`, `access_expires_at`, `is_active`) y **una separada de backfill** que decide qué pasa con los usuarios `trial` existentes (decisión pendiente, §10), y otra que retira `trial` del enum una vez que ninguna fila lo use.

### 2.4 Tests de aceptación

- Cuenta nueva → `403` en `POST /sessions` con motivo `no_access`.
- `invited` con `access_expires_at` en el pasado → `403 expired`.
- Cuenta suspendida con suscripción activa → `403 suspended`.
- Suscripción `canceled` con `current_period_end` en el futuro → acceso; en el pasado → sin acceso.
- Admin siempre accede, aunque no tenga suscripción.
- Un test que recorre **todos** los routers de juego con una cuenta sin acceso y confirma `403` en cada uno: así un router nuevo que olvide `RequireAccess` rompe un test en vez de quedar abierto.

### 2.5 Cómo quedó construido (2026-10-08)

Decisiones de implementación que este documento no fijaba, confirmadas por el usuario el 2026-10-08.

- **`core/access.py` ya existía** desde el paso 2, con la regla de consentimiento. Este paso agregó las demás en el orden de §2.2. La firma era `has_access(db, user, now)`; `game` y la regla n.º 7 llegaron en el paso 7 (§7.7).
- **Motivos**: `admin`, `full`, `invited`, `subscription` cuando hay acceso; `suspended`, `consent_required`, `expired`, `no_access` cuando no. `expired` se usa cuando la cuenta tuvo un acceso `invited` o una suscripción y venció; `no_access`, cuando nunca tuvo. `email_not_verified` no es un motivo de acceso a la mesa (§2.2): es requisito para pagar y lo responde `POST /billing/subscriptions` en el paso 5.
- **`until`**: hasta cuándo vale el acceso si vence, o cuándo venció si el motivo es `expired`. Null en los accesos sin vencimiento.
- **La suscripción se lee con lo que hay hoy** en la tabla (`status` y `current_period_end`): da acceso con `status` `active` o `canceled` y el período en el futuro. No hay ninguna suscripción todavía; los tests insertan filas a mano. El paso 5 amplía la tabla sin cambiar esta regla.
- **Cuentas `trial`**: pasaron a `invited` sin vencimiento (decisión de §10 n.º 1). Tres migraciones, como pedía §2.3: DDL (`none`, `access_expires_at`, `is_active`), backfill, y retiro de `trial` del CHECK. El backfill no tiene vuelta: después de subir, una cuenta que venía de `trial` no se distingue de una invitada.
- **Despliegue sin esperar al pago** (decisión del usuario): desde que este paso sale, una cuenta nueva nace con `access_type = none` y no entra a la mesa hasta que un administrador le dé acceso. No hay interruptor para apagarlo.
- **`access` viaja en toda respuesta que trae la cuenta**, no solo en `GET /auth/me`: también en el login, el registro y el refresh, que es de donde el frontend toma la cuenta al entrar. Se arma en `api/presenters.user_response` con la decisión de `has_access`.
- **El `403` de un endpoint de juego** lleva `detail.code` con el motivo y un mensaje de respaldo.
- **Cuenta suspendida**: inicia sesión, entra a `/cuenta`, exporta y elimina sus datos; no usa la mesa. Un administrador suspendido deja de administrar (`require_admin` lo rechaza) hasta que otro lo reactive. Nadie se suspende a sí mismo (`409`).
- **Qué ve una cuenta sin acceso** (decisión del usuario): una pantalla que dice que no tiene acceso activo y que las suscripciones estarán disponibles pronto, **sin correo de contacto**. Si el acceso venció, dice cuándo. Si está suspendida, lo dice. Si le falta confirmar el correo, se lo recuerda. Era provisional: desde el paso 4 la cuenta sin acceso o con el acceso vencido va a `/planes` (§3.11); la suspendida conserva su aviso.
- **Compuerta del frontend**: `LegalGate` pasó a llamarse `AccessGate`. Antes de montar una pantalla de juego vuelve a pedir la cuenta al servidor, porque la decisión guardada en la sesión puede ser vieja, y muestra la mesa, la aceptación de documentos o el aviso según `access`. Sigue siendo presentación: decide el servidor.
- **El acceso manual no aplica a un administrador** (2026-10-08, lo señaló el usuario al probarlo): entra por su rol, así que guardar un cambio no tendría efecto y confunde. `PATCH /admin/users/:id/access` responde `409` sobre una cuenta de administrador y la pantalla muestra una nota en lugar del formulario.
- **Un cambio que no cambia nada se rechaza** (`409`), tanto de acceso como de estado, para no llenar la bitácora de filas que no dicen nada (2026-10-08).
- **La cuenta del administrador** (2026-10-08). `SEED_ADMIN_EMAIL` y `SEED_ADMIN_PASSWORD` solo sirven para crear el primer administrador; después es una cuenta más y puede cambiar su nombre, su correo y su contraseña (cambiar la del `.env` es lo recomendable). Tres ajustes de este paso: el seed **no crea un administrador si ya existe alguno**, tenga el correo que tenga (antes buscaba por el correo del `.env`, y bastaba cambiar el correo desde `/cuenta` para que volver a correrlo creara un segundo administrador con la clave del `.env`); el único administrador **activo** no puede eliminar su cuenta (uno suspendido no cuenta como relevo; la regla vive en `core/accounts.is_last_active_admin`); y la cuenta trae `can_delete_account`, con el que `/cuenta` explica el bloqueo en lugar de ofrecer el botón. **Otro administrador se nombra desde `/admin/usuarios`** (cambio de rol, adelantado del paso 6 por decisión del usuario el 2026-10-08): `PATCH /admin/users/:id/role` recibe `{role, reason}`, deja fila en la bitácora (`user.role.update`) y rechaza con `409` cambiarse el rol a uno mismo, un cambio que no cambia nada y nombrar a una cuenta suspendida. Como quien llama es un administrador activo y no puede cambiarse a sí mismo, siempre queda al menos uno. Al quitar el rol no se toca `access_type`: la cuenta vuelve a depender de su acceso manual, y la pantalla dice cuál es antes de confirmar.
- **No se envía correo** al otorgar, retirar o suspender.
- **`admin_audit_log`** (§4.6) se creó aquí. Además de lo previsto guarda `admin_email`, porque `admin_user_id` queda en null si ese administrador elimina su cuenta, y `target_id` es texto y no una llave foránea, para que la fila sobreviva al objeto. Lo escribe `core/audit.record`, que no hace commit: el cambio y su fila se confirman juntos. Acciones de hoy: `user.access.update`, `user.status.update` y `legal_document.publish`.
- **El motivo es obligatorio** (3 a 500 caracteres) en los cambios de acceso y de estado. Un cambio rechazado no deja fila.
- **`/admin/usuarios` se adelantó del paso 6** (decisión del usuario): `GET /admin/users` pagina (`limit` hasta 100, `offset`) y filtra en el servidor por texto (correo o nombre), acceso manual, rol, correo confirmado y estado; devuelve `{items, total, limit, offset}`. `GET /admin/users/:id` trae la cuenta, su decisión de acceso, los documentos aceptados, la cantidad de mesas y las últimas 20 acciones sobre ella. `PATCH /admin/users/:id/access` recibe `{access_type, access_expires_at?, reason}`; el vencimiento solo aplica a `invited` y debe ser futuro. `PATCH /admin/users/:id/status` recibe `{is_active, reason}`.
- **`/admin/auditoria`**: `GET /admin/audit-log` paginado, lo más reciente primero. No hay endpoint para editar ni borrar.
- **Queda para el paso 6**: `POST …/force-password-reset`, `POST …/resend-verification` y la navegación lateral (**hechos en la entrega 2 del paso 6**, §4.9). **Para el paso 5**: el filtro por estado de suscripción, y la suscripción y los pagos en el detalle de la cuenta (hechos el 2026-10-13, §3.13).
- **Tests**: el cliente de los tests de API deja cada cuenta que registra con acceso `invited`, porque casi ningún test trata del acceso; los que sí usan `register_raw`, que registra como un cliente real. En Playwright, `registerViaApi` le pide el acceso al administrador sembrado.

---

## 3. Pagos y suscripciones con Wompi

### 3.1 Reglas no negociables (de `CLAUDE.md`, "Pagos con Wompi")

Se repiten aquí porque son las que distinguen un flujo que funciona en el caso feliz de uno que aguanta producción:

- **Firma**: la verificación de integridad de la transacción y del checksum del webhook se implementa leyendo la **documentación oficial vigente de Wompi**, nunca de memoria. Un comentario en el código cita la URL y la fecha de consulta. Este documento a propósito **no** describe el algoritmo.
- **El webhook no es fuente de verdad por sí solo**: tras verificar la firma, el backend **vuelve a consultar la transacción** contra la API de Wompi y solo con esa respuesta mueve `subscriptions.status` o el acceso.
- **Idempotencia** por `payment_events.provider_event_id` (único). Reprocesar el mismo evento no puede otorgar dos períodos.
- **Montos en centavos** con moneda explícita (Wompi también opera en centavos).
- **Acceso decidido en el servidor**, desde `has_access` (§2).
- **Copy sin promesas de resultados** en planes, checkout y correos de cobro.

### 3.2 Modelo de datos

```sql
plans (
  id, code UNIQUE,                    -- 'mensual', 'anual'… identificador estable
  name, description,
  price_cents, currency,              -- 'COP'
  interval,                           -- 'month' | 'year'
  interval_count,                     -- 1 = cada mes; 3 = trimestral
  active, sort_order,
  created_at, updated_at
)

plan_games (plan_id, game_id)          -- §7.4; sin filas = el plan incluye todos los juegos

coupons (
  id, code UNIQUE,                     -- se guarda en mayúsculas
  kind,                                -- 'percent' | 'fixed_cents'
  value,                               -- 1..100 si percent; centavos si fixed
  currency,                            -- obligatorio si fixed_cents
  duration,                            -- 'once' | 'repeating' | 'forever'
  duration_periods,                    -- solo con 'repeating'
  max_redemptions, redemptions_count,
  valid_from, valid_until,
  active, created_by, created_at
)
coupon_plans (coupon_id, plan_id)      -- sin filas = aplica a todos los planes
coupon_redemptions (id, coupon_id, user_id, subscription_id, created_at,
                    UNIQUE (coupon_id, user_id))

subscriptions (                         -- tabla existente, ampliada
  id, user_id,
  plan_id FK plans,                     -- antes String suelto
  provider,                             -- 'wompi'
  status,                               -- 'pending' | 'active' | 'past_due' | 'canceled' | 'expired'
  price_cents, currency,                -- CONGELADOS al suscribirse (§3.7)
  coupon_id, discount_periods_remaining,
  current_period_start, current_period_end,
  cancel_at_period_end,
  payment_source_id,                    -- reemplaza payment_token_ref; referencia de Wompi, nunca datos de tarjeta
  card_brand, card_last4,               -- solo para mostrar "Visa •••• 4242"
  next_charge_at, retry_count,
  created_at, updated_at, canceled_at
)

payments (
  id, subscription_id, user_id,
  reference UNIQUE,                     -- una por intento de cobro de un período
  kind,                                 -- 'initial' | 'renewal'
  period_start, period_end,             -- el período que este cobro paga
  amount_cents, currency,
  discount_cents,
  provider_transaction_id,
  status,                               -- 'pending' | 'approved' | 'declined' | 'voided' | 'error'
  failure_reason,
  created_at, resolved_at
)

payment_events (                        -- tabla existente
  id,
  subscription_id NULLABLE,             -- antes NOT NULL
  payment_id NULLABLE,
  provider_event_id UNIQUE,
  event_type, status,
  raw_payload, signature_verified,
  processed_at, created_at
)
```

Notas:

- **Nunca se guardan datos de tarjeta.** La tarjeta se tokeniza en el navegador, que la manda directo a Wompi (con el widget hasta el 2026-10-19; con un formulario propio desde entonces, §3.16); el backend solo recibe y guarda la referencia de la fuente de pago y, para mostrar, marca y últimos cuatro dígitos.
- `payment_events` guarda **todo** evento recibido, verificado o no (`signature_verified` lo distingue), para poder auditar intentos de falsificación. Solo los verificados y reconsultados mueven estado.
- `payments.reference` única por período es la segunda capa de idempotencia: dos corridas del job de renovación no pueden crear dos cobros para el mismo período (§3.5).

### 3.3 Cálculo de precio (módulo puro `backend/app/billing/pricing.py`)

- `quote(plan, coupon, now) -> Quote` con `subtotal_cents`, `discount_cents`, `total_cents`, `currency`, y el motivo si el cupón no aplica.
- El precio **siempre** lo calcula el servidor. El cliente manda `plan_id` y, opcional, `coupon_code`; nunca un monto.
- Redondeo de porcentajes: hacia abajo al centavo (a favor del cliente), documentado en el código.
- Un descuento nunca deja el total en negativo; si lo deja en cero, se resuelve en la decisión pendiente de §10 (Wompi no procesa cobros de cero).
- Validaciones del cupón: activo, dentro de vigencia, con cupos (`redemptions_count < max_redemptions`), aplicable al plan, misma moneda si es `fixed_cents`, no usado antes por ese usuario.

### 3.4 Flujo de alta

```
Usuario                 Frontend                     Backend                         Wompi
  │ elige plan (+cupón)    │                            │                               │
  │──────────────────────▶│ POST /billing/quote ──────▶│ pricing.quote()               │
  │                        │◀──── total en centavos ────│                               │
  │                        │ GET /billing/acceptance ──▶│ obtiene el acceptance token ─▶│
  │ acepta términos Wompi  │◀── token + enlace términos ─│◀──────────────────────────────│
  │ ingresa tarjeta        │ el navegador tokeniza (§3.16) ────────────────────────────▶│
  │                        │◀────────────────────────────────────── token de tarjeta ───│
  │                        │ POST /billing/subscriptions▶│ crea payment source ─────────▶│
  │                        │  {plan, cupón, token,       │ crea suscripción 'pending'     │
  │                        │   acceptance}               │ crea payment 'initial' ──────▶│ transacción
  │                        │◀──── 202 + payment_id ──────│                               │
  │                        │ consulta el estado ────────▶│                               │
  │                        │                            │◀──────── webhook ─────────────│
  │                        │                            │ verifica firma                 │
  │                        │                            │ reconsulta la transacción ────▶│
  │                        │                            │ APPROVED → suscripción 'active'│
  │                        │                            │ fija current_period_end        │
```

- Requisito previo: correo verificado y consentimientos legales vigentes aceptados (§5, §6).
- El frontend no da por activa la suscripción por lo que diga el widget: consulta `GET /billing/payments/:id` hasta que el backend la reporte resuelta.
- Si el webhook se demora, el backend también puede reconsultar la transacción al recibir esa consulta del frontend. Las dos vías pasan por la misma función idempotente, así que no hay doble período.
- Un usuario no puede tener dos suscripciones `pending | active | past_due` a la vez (restricción en la base, no solo en el código).

### 3.5 Renovación automática

- **Job**: `backend/scripts/run_renewals.py`, idempotente, programado como tarea cron en Dokploy (cada hora). No se agrega un worker ni una cola nuevos.
- **Calendario** (módulo puro `billing/schedule.py`): primer intento **48 h antes** de `current_period_end`; reintentos a **24 h** y a **0 h**. Así un fallo transitorio de la tarjeta no corta el acceso.
- **Si todos fallan**: el período vence y el acceso cae en `current_period_end`, sin período de gracia. Es la regla de `CLAUDE.md` ("suscripción vencida → acceso revocado"). La suscripción pasa a `expired` y el usuario la reactiva desde `/cuenta` con un pago nuevo.
- Mientras hay reintentos pendientes, `status = past_due`, se envía correo al usuario y la pantalla de cuenta le pide actualizar la tarjeta.
- **Idempotencia del job**: el cobro de cada período usa una `reference` derivada de (suscripción, período, número de intento). Dos ejecuciones simultáneas o repetidas chocan con la restricción única en vez de cobrar dos veces. El job toma un lock de Postgres (`pg_try_advisory_lock`) para no correr en paralelo consigo mismo.
- El cobro de renovación también se confirma con webhook + reconsulta. Al aprobarse, el período avanza desde el `current_period_end` anterior (no desde la fecha de cobro), para no regalar ni quitar días.
- El descuento de un cupón `repeating` descuenta `discount_periods_remaining` en cada renovación aprobada; en cero, se cobra el precio congelado completo.

### 3.6 Cancelación, cambio de tarjeta e historial

- **Cancelar** (`POST /billing/subscription/cancel`): `cancel_at_period_end = true`, `status = canceled`. Conserva el acceso hasta `current_period_end`; el job no vuelve a cobrar. **Reanudar** antes del vencimiento revierte la cancelación.
- **Cambiar tarjeta**: mismo flujo de tokenización; reemplaza `payment_source_id`. Si la suscripción está `past_due`, intenta el cobro pendiente de inmediato.
- **Historial**: `GET /billing/payments` lista los cobros del usuario (fecha, plan, monto, estado, últimos cuatro dígitos).
- **Cambio de plan** (mensual ↔ anual): no entra en esta fase. Para cambiar, se cancela y se suscribe al otro al vencer. Se anota como mejora posterior.

### 3.7 Precio congelado

`subscriptions.price_cents` guarda el precio al suscribirse. Un cambio de precio del plan en el admin aplica a **suscripciones nuevas**; las vigentes renuevan con su precio congelado. Si se decide trasladar el precio nuevo a las existentes, es una acción explícita del admin, auditada, con aviso por correo al usuario antes del cobro (decisión pendiente, §10). **Construido el 2026-10-14** (§4.10): una subida se cobra 30 días después del aviso a cada cliente y una bajada aplica ya.

### 3.8 Correos transaccionales de cobro

Bienvenida al activar, recibo de cada cobro aprobado, cobro fallido con enlace para cambiar la tarjeta, aviso de vencimiento cuando se agotan los reintentos, confirmación de cancelación. Todos pasan el filtro de terminología: describen el servicio, nunca resultados.

**Aviso antes de cada cobro automático** (decidido el 2026-10-09, se construye en el paso 5). Con anticipación suficiente, el usuario recibe un correo que dice que se le va a cobrar: qué plan, cuánto, en qué moneda y qué día. El correo le indica que, si tiene dudas o quiere gestionar su suscripción (cancelarla, cambiar el medio de pago), vaya al apartado de suscripción de su perfil (`/cuenta`), con el enlace. Pesa más en el plan de dos meses, donde pasan dos meses entre un cobro y el siguiente. Reglas:

- Se envía **antes del primer intento de cobro** de §3.5, no después.
- Uno por período: el job de renovaciones lo marca como enviado para no repetirlo en cada corrida.
- No se envía a una suscripción cancelada, porque ya no se le va a cobrar.
- En el pago manual mes a mes el aviso es el de §3.10: que el período está por vencer y cómo pagar el siguiente.
- **Definido el 2026-10-13: 7 días antes del cobro.** Se construye en la entrega 2 del paso 5.

### 3.9 Tests de aceptación

Los cuatro obligatorios de `CLAUDE.md`, más los que cubren lo nuevo de esta fase:

| Caso | Resultado esperado |
|---|---|
| Firma inválida | Se rechaza, queda registrado con `signature_verified = false`, el acceso no cambia. |
| Evento duplicado (mismo `provider_event_id`) | Se otorga un solo período. |
| Transacción declinada | No se concede acceso. |
| Suscripción vencida (`current_period_end` en el pasado) | Acceso revocado. |
| Webhook con firma válida pero la reconsulta dice `DECLINED` | No se concede acceso (gana la reconsulta). |
| Dos corridas del job de renovación sobre el mismo período | Un solo cobro. |
| Monto o descuento enviado por el cliente | Se ignora; el total sale de `pricing.quote`. |
| Cupón vencido, agotado, de otro plan, o ya usado por el usuario | Rechazado con motivo. |
| Cancelación | Acceso hasta `current_period_end`, sin cobros después. |
| Cambio de precio del plan | Las suscripciones vigentes renuevan con su precio congelado. |
| Los tres intentos de renovación fallan | Acceso cae exactamente en `current_period_end`; estado `expired`. |
| Evento de una referencia desconocida | Se guarda en `payment_events` sin suscripción y no mueve nada. |

Los tests de API usan un cliente falso de Wompi (inyectado como dependencia); ningún test llama a la red. Las pruebas contra el sandbox real de Wompi se hacen a mano antes de salir a producción y quedan anotadas en `docs/DESPLIEGUE.md`.

### 3.10 Monetización: decisiones del 2026-10-08

Tomadas por el usuario antes de empezar el paso 4. Ajustan lo que dicen §3.2 a §3.6 donde se contradigan; lo que no se menciona aquí sigue igual.

**Público y precio**

- El público es **internacional**, no solo Colombia.
- **Dos planes** (2026-10-09; el 2026-10-08 se había decidido uno solo): **mensual, de 100.000 COP**, y **de dos meses, de 150.000 COP**. El de dos meses es un plan aparte, no un cupón: un solo cobro cada dos meses (`interval = month`, `interval_count = 2`). No hay plan anual ni trimestral. El modelo de `plans` (§3.2) se conserva tal cual: cada plan es una fila, y nada impide crear otro después.
- **No hay precio de referencia en dólares** (decidido el 2026-10-09, al construir el paso 4). El 2026-10-08 se había decidido mostrar además un precio fijo de 30 USD, solo visual; se descartó: 30 USD no es el equivalente de 100.000 COP, y mostrar una cifra que no se cobra presta a confusión. **Se muestra y se cobra un solo precio: 100.000 COP.** El plan no tiene campos de presentación.
- A quien pague con una tarjeta de otro país su banco le convertirá los 100.000 COP a su tasa. La pantalla de planes lo dice, y la de pago deberá decirlo también (§3.11).
- **Los cupones se mantienen** (§3.3, §4.5).

**Dos modos de pago**

- **Automático**: lo que ya describían §3.4 y §3.5. Fuente de pago tokenizada, cobro en cada período, reintentos.
- **Manual mes a mes**: el usuario paga un período cada vez, sin tokenizar nada. El pago aprobado fija o extiende `current_period_end`; no hay cobro automático ni reintentos. Antes del vencimiento se le avisa por correo para que pague el siguiente; si no paga, el acceso cae en `current_period_end`, igual que una suscripción vencida.
- El control de acceso no cambia: `has_access` ya decide por `status` y `current_period_end` (§2.2 n.º 6), sin importar cómo se pagó el período.
- Las reglas no negociables de §3.1 aplican igual a los dos modos: firma verificada, reconsulta de la transacción, idempotencia, montos en centavos y acceso decidido en el servidor.
- **Definido el 2026-10-13 (§3.12)**: el modo es `subscriptions.renewal_mode`, un pago hecho antes del vencimiento extiende desde `current_period_end`, y se pasa de un modo al otro sobre la misma suscripción (entrega 3). Lo que este punto dejaba abierto: cómo se representa el modo en `subscriptions` (por ejemplo un campo `renewal_mode`), si un pago manual hecho antes del vencimiento extiende desde `current_period_end` o desde la fecha de pago, y cómo se pasa de un modo al otro.

**Pasarela**

- **Wompi es la pasarela principal.** Consultado en su documentación oficial el 2026-10-08: opera en COP; ofrece tarjetas, PSE, Nequi, Daviplata, Botón Bancolombia, corresponsales en efectivo y cuotas; y se pueden tokenizar para cobro automático las tarjetas y las cuentas Nequi, Daviplata y Bancolombia. Estos datos se vuelven a leer de la documentación vigente al construir el paso 5 (§3.1).
- **Por confirmar con Wompi, por escrito, antes del paso 5**: que acepta esta categoría de negocio (análisis estadístico por suscripción, adyacente a juegos de azar, que no recibe apuestas) y que acepta tarjetas internacionales. Un directorio de terceros dice que sí acepta Visa y MasterCard internacionales; no se vio en la documentación oficial.
- **El paso 5 se construye detrás de una interfaz de proveedor**, como el correo (`EmailSender`), para que una segunda pasarela no obligue a reescribir. `subscriptions.provider` ya existe.
- **Hueco conocido**: un cliente de fuera de Colombia sin tarjeta no puede pagar con Wompi.
- **Premium Pay** (`premiumpay.pro`, operada por BETANDEAL USA, CORP., Florida) se evaluó el 2026-10-08 para cubrir ese hueco. **No sirve como base del cobro**: no es una pasarela sino una plataforma de venta para creadores con página de pago propia; no se le vio API ni webhooks, así que la aplicación no puede activar el acceso sola; cobra entre 7 % y 11 %; su aviso legal le permite retener saldos hasta 180 días por "riesgo regulatorio"; y no actúa como comerciante de registro. Acepta transferencia, criptomonedas y Skrill. **Uso posible**: canal manual para pocos clientes internacionales sin tarjeta, en el que el cliente paga por su enlace y el administrador le da acceso `invited` con vencimiento desde `/admin/usuarios`. No requiere código. Antes de usarla: pedirle los términos para vendedores y preguntar si tiene API o webhooks firmados.
- Si el volumen internacional sin tarjeta crece, la opción a evaluar es una pasarela de criptomonedas con API, que sí se puede automatizar con las reglas de §3.1.

### 3.11 Planes y cupones: cómo quedó construido (2026-10-09)

Paso 4 del orden de §9. Decisiones de implementación que este documento no fijaba, confirmadas por el usuario el 2026-10-09. Aquí no se cobra ni se redime nada: eso es del paso 5.

**Decisiones del usuario**

- **Un solo precio en pantalla**: `100.000 COP / mes`, el que se cobra. La primera versión de este paso mostraba debajo `Precio de referencia: 30 USD`; el usuario lo descartó el mismo 2026-10-09, antes de mezclar la rama, y los campos `display_price_cents` y `display_currency` se quitaron de la tabla, de la API y del admin. Queda una nota corta bajo el precio: "Cobro en pesos colombianos (COP). Con tarjeta de otro país, tu banco aplica su tasa de cambio y puede cobrar comisiones." (el usuario pidió acortarla el 2026-10-09).
- **Para el abogado** (bloquea el lanzamiento, no este paso): si el precio debe decir que incluye impuestos y si aplica IVA (va con §10 n.º 4); qué ley de consumo aplica a un cliente de fuera de Colombia; y si la nota sobre la conversión del banco debe repetirse en la pantalla de pago, en el recibo y en los términos.
- **Los planes los siembran migraciones de datos**, separadas del DDL: `mensual` (**Acceso Mensual**, 100.000 COP al mes) y `bimestral` (**Acceso Bimestral**, 150.000 COP cada dos meses). Después se editan desde `/admin/planes`. Esas filas iniciales no dejan entrada en la bitácora.
- **Cupón del 100 %: no existe** (§10 n.º 6). El porcentaje va de 1 a 99 (lo exigen el endpoint y un `CHECK` de la tabla), y un cupón de monto fijo que cubra todo el precio no aplica a ese plan (`covers_total`). Una cortesía total se da como acceso `invited` desde `/admin/usuarios`.
- **`/planes` sin pago**: el plan con su precio y el botón "Suscribirme" deshabilitado, con la nota "El pago estará disponible pronto". Sin correo de contacto y sin campo de cupón hasta el paso 5.

**Datos**

- Tablas `plans`, `coupons`, `coupon_plans` y `coupon_redemptions` como en §3.2, sin campos de más: el plan guarda un solo precio (`price_cents`, `currency`), que es el que se cobra y el que se muestra.
- **Solo se cobra en COP**: los schemas del admin rechazan otra moneda de cobro, en planes y en cupones de monto fijo. Es validación, no estructura: la columna `currency` sigue ahí para el día que haya otra pasarela.
- `coupon_redemptions.user_id` es `ON DELETE CASCADE`, como el resto de lo que hoy cuelga de la cuenta: eliminar la cuenta borra también el rastro de que usó el cupón. **El paso 5 lo revisa** junto con el `ON DELETE` de `subscriptions` (§5.7.1). **Revisado en la entrega 3 del paso 5: pasó a `SET NULL`** (§3.15).
- `subscriptions.plan_id` sigue siendo texto suelto; pasa a llave foránea en el paso 5. Por eso `/admin/planes` todavía no muestra cuántas suscripciones vigentes conservan su precio (§4.4): el formulario dice la regla, sin el número.
- `plan_games` no se creó: es del paso 7.

**Cálculo (`backend/app/billing/`, puro, con `mypy` estricto)**

- `pricing.quote(plan, coupon, now)` devuelve subtotal, descuento, total y moneda, y el motivo si el cupón no aplica. Un cupón que no aplica **no es un error**: la cotización sale por el precio completo.
- Motivos, en el orden en que se revisan: `inactive`, `not_started`, `expired`, `exhausted`, `other_plan`, `currency_mismatch`, `already_used`, `covers_total`. `not_found` lo pone el endpoint cuando el código no existe. `valid_until` es exclusivo.
- El porcentaje se calcula con división entera (`monto * porcentaje // 100`): redondea el descuento hacia abajo al centavo, sin pasar por `float`.
- La cotización calcula **el primer cobro**. `duration` y `duration_periods` se guardan, pero quienes los aplican son las renovaciones del paso 5.
- `coupon_codes.py`: un código se guarda en mayúsculas, lleva de 3 a 40 caracteres (letras sin tilde, números, guion y guion bajo) y no puede contener una lista corta de fragmentos (`GANA`, `SEGUR`, `GARANT`, `INFALIB`, `PREDIC`, `VENTAJA`, `ACIERT`, `WIN`, `SUERTE`, `PREMIO`…). La lista es tosca a propósito: prefiere rechazar un código inocente a dejar pasar uno que suene a promesa.

**API**

- `GET /plans`: pública, solo los planes activos.
- `POST /billing/quote {plan_id, coupon_code?}`: **exige sesión** (hace falta saber quién cotiza para "ya usado por el usuario") pero no acceso a la mesa. No reserva ni redime nada. Cualquier otro campo del cuerpo, un monto incluido, se ignora. Un plan desactivado responde `404`.
- **Límite de intentos** (pendiente de §5.7.1): solo cuentan las cotizaciones que traen código, 10 cada 15 minutos por cuenta y 30 por hora por IP; al pasarse, `429`. Sin código no hay límite. En memoria, como los demás, y lo apaga `RATE_LIMIT_ENABLED`.
- Admin: `GET|POST /admin/plans`, `PATCH /admin/plans/:id`, `GET|POST /admin/coupons`, `PATCH /admin/coupons/:id`, `GET /admin/coupons/:id/redemptions`. Las listas paginan con `limit` y `offset`. **No hay `DELETE`**: activar y desactivar es el campo `active` del `PATCH`.
- **Motivo obligatorio** (3 a 500 caracteres) en toda creación y todo cambio; cada uno deja su fila en `admin_audit_log` (`plan.create`, `plan.update`, `coupon.create`, `coupon.update`) con el antes y el después. Un cambio que no cambia nada responde `409` y no deja fila.
- **Lo que no se edita**: el código de un plan, su moneda de cobro y el código de un cupón. **Con redenciones**, tampoco el descuento del cupón (`kind`, `value`, `currency`, `duration`, `duration_periods`): se desactiva y se crea otro. El tope de usos no puede bajar de lo ya usado.

**Frontend**

- `/planes` es pública. `AccessGate` manda allí a la cuenta sin acceso o con el acceso vencido, en lugar del aviso provisional del paso 3. La cuenta suspendida sigue viendo su aviso: no se le ofrecen planes.
- `/admin/planes` y `/admin/descuentos`, enlazadas desde `/admin`. Los montos se escriben en pesos y viajan en centavos (`lib/money.ts` los convierte sin pasar por decimales de coma flotante).
- El nombre y la descripción de un plan son texto libre del administrador. El formulario recuerda la regla de lenguaje, pero **no hay filtro automático** sobre esos dos campos: la descripción aprobada usa "predicción" y "ventaja" en negativo, y un filtro por palabras la rechazaría.

**Tests**

- `tests/billing/`: 59 tests del módulo puro, sin base de datos (redondeo, cada motivo, el orden de los motivos, el total que nunca llega a cero, los códigos).
- `tests/api/test_billing.py` y `tests/api/test_admin_billing.py`: cada caso de cupón del "hecho cuando" de §9 por el endpoint (vencido, agotado, de otro plan, ya usado por el usuario, de otra moneda, inactivo), el monto enviado por el cliente que se ignora, el límite de intentos, y el admin con su bitácora.
- Playwright (`e2e/plans.spec.ts`): una cuenta sin acceso ve `/planes` con el precio; la página se ve sin sesión; el administrador crea, edita y desactiva un plan y un cupón, y los cambios aparecen en la bitácora.

### 3.12 Wompi, entrega 1: cómo quedó construido (2026-10-13)

Paso 5 del orden de §9, primera de tres entregas: alta con pago manual, webhook y reconsulta (rama `fase-4-paso-5a-alta-y-webhook`). La tokenización y la renovación automática son de la entrega 2; cancelar, `/cuenta`, el admin de pagos y la prueba en el sandbox, de la 3. **El paso 5 no está cerrado.**

**Probado en parte contra el sandbox de Wompi (2026-10-13).** Se construyó sin llaves, contra respuestas simuladas. El mismo día el usuario puso las llaves de sandbox y se hizo un pago real de prueba en local: el checkout aceptó la firma de integridad, la redirección volvió con `?id=`, y la reconsulta activó la suscripción y envió los correos. Ese mismo día, ya desplegado en el VPS con llaves de sandbox, **el webhook recibió dos eventos reales y los aceptó** (`200`). El detalle y lo que falta (un pago rechazado y un medio que no responde de inmediato) están en `DESPLIEGUE.md`, "Pagos con Wompi", y al final de esta sección. El usuario confirmó también el 2026-10-13 que Wompi respondió que acepta esta categoría de negocio y tarjetas internacionales (§3.10).

**Decisiones del usuario (2026-10-13)**

- **El pago manual usa el Web Checkout de Wompi**: el cliente paga en la página de Wompi con cualquier medio que el comercio tenga habilitado en su panel (cierra §10 n.º 3). Qué medios se ofrecen se enciende o se apaga en Wompi, no en el código, y por la aplicación no pasa ningún dato de tarjeta ni de cuenta.
- **Un pago hecho antes del vencimiento extiende desde `current_period_end`**; uno hecho después, o el primero, cuenta desde el momento del pago.
- **`subscriptions.renewal_mode`** (`manual` | `automatic`) representa el modo. En esta entrega toda suscripción nace `manual`. Pasar de un modo al otro será cambiar ese campo sobre la misma suscripción, sin perder el período (entrega 3).
- **Los dos planes se ofrecen en los dos modos.** El pago manual del bimestral compra dos meses.
- **Aviso antes del cobro automático: 7 días** (entrega 2).
- **La nota de la tasa de cambio se repite** en la pantalla de pago y en el recibo, mientras el abogado decide.
- **Al eliminar una cuenta se conservan los pagos anonimizados**: las filas de `payments` y `payment_events` quedan sin usuario; la suscripción se borra. Las llaves foráneas ya quedaron así; el flujo completo (cancelar la renovación antes de borrar) es de la entrega 3.
- **`/planes` con sesión**: un administrador o una cuenta con acceso manual (`full`, `invited`) ve los planes sin botón de pago; un suscriptor ve su plan marcado "Tu plan actual", con la fecha hasta la que tiene acceso y el botón de pagar el período siguiente solo en ese plan.
- De §10 no cambia nada más: no hay facturación electrónica (n.º 4), el precio no se traslada a las suscripciones vigentes (n.º 5) y los reembolsos son manuales en el panel de Wompi (n.º 7).

**Proveedor de pagos (`backend/app/payments/`)**

- `PaymentProvider` (`base.py`) es la interfaz, como `EmailSender`: `checkout_url`, `parse_event`, `fetch_transaction` y `describe`. La aplicación no menciona a Wompi fuera de `payments/wompi.py`, salvo en la ruta del webhook.
- `WompiProvider` (`wompi.py`) lleva en su encabezado las URL de la documentación oficial y la fecha de consulta (2026-10-13). Siguiendo §3.1, este documento no describe los algoritmos de firma: están en el código, con su fuente, y los fijan los tests de `tests/payments/`.
- `UnconfiguredPaymentProvider`: `PAYMENT_PROVIDER=wompi` sin llaves. El pago queda apagado y `/planes` se ve como antes de este paso.
- `FakePaymentProvider` (`fake.py`): pasarela simulada para desarrollo y para Playwright. El botón de pagar lleva a una página de la propia API (`/dev/fake-checkout`, fuera del OpenAPI y `404` con cualquier otro proveedor) con "aprobar" y "rechazar". No se usa con llaves de producción: la API no arranca.
- **Las llaves se validan al arrancar**: las cuatro presentes, todas del mismo ambiente (por su prefijo) y `WOMPI_API_BASE_URL`, si se pone, la de ese ambiente. Si no, la API no arranca y el error dice qué variable, nunca su valor. El log de arranque dice el ambiente (§12).
- `httpx` pasó de dependencia de desarrollo a dependencia de la API: es con lo que se reconsulta a Wompi.

**Datos**

- Tres migraciones, como en el paso 3: DDL que no depende de los datos, la de datos, y el DDL que cierra (`NOT NULL`, `CHECK`, índice único parcial, retiro de `plan_code_legacy` y `payment_token_ref`). La de datos se detiene, sin inventar nada, si encuentra una suscripción con un plan que no existe, con un estado que el modelo no admite, o dos suscripciones vivas de una misma cuenta.
- `subscriptions` queda como en §3.2, más `renewal_mode`. **Índice único parcial `uq_subscriptions_one_live_per_user`**: una cuenta no tiene dos suscripciones `pending`, `active` o `past_due` a la vez.
- `payments` lleva, además de lo previsto en §3.2, **`plan_id`, `coupon_id` y `provider`**: una cuenta puede abrir el pago de un plan, devolverse y abrir el de otro, y lo que se compró lo dice el pago que se aprueba, no la suscripción pendiente. `period_start` y `period_end` son nulos hasta que el pago se aprueba, porque en el pago manual el período depende de cuándo se paga.
- `payment_events`: `subscription_id` nullable, `payment_id`, `event_type`, `processed_at` y `created_at`. Las llaves a la suscripción y al pago son `SET NULL`.
- `coupon_redemptions.user_id` seguía en `CASCADE`. **Desde la entrega 3 es `SET NULL`** (§3.15).

**Alta (`POST /billing/subscriptions`)**

- Recibe `{plan_id, coupon_code?}` y responde `202` con `payment_id`, `checkout_url` y el desglose. No recibe `card_token` ni `acceptance_token` (§11 los listaba): eso es de la entrega 2. Cualquier otro campo, un monto incluido, se ignora.
- Requisitos, con el motivo en `detail.code`: cuenta activa (`403 suspended`), correo confirmado (`403 email_not_verified`), documentos aceptados (`403 consent_required`), y que la cuenta no tenga ya acceso por ser administrador o por acceso manual (`409 already_has_access`). Sin pasarela, `503 payments_unavailable`.
- **Un cupón que no aplica rechaza el pago** (`400 coupon_rejected`, con `reason` y mensaje), a diferencia de la cotización, donde no es un error: cobrar el precio completo a quien escribió un código sería una sorpresa.
- Con una suscripción pagada y vigente, el pago es del período siguiente: mismo plan (`409 other_plan` si no), **precio congelado** de la suscripción y sin cupón (`400 coupon_only_on_first_payment`). Con el período ya vencido es un alta nueva: cualquier plan, al precio de hoy.
- Cada intento crea un `payment` con una referencia nueva (`SA-…`): Wompi rechaza una referencia repetida. Una suscripción que nunca se pagó se reutiliza; no se acumulan filas `pending`.
- Límite: 10 intentos cada 15 minutos por cuenta, más el de códigos de cupón de la cotización.
- `GET /billing/availability` (pública) dice si hay pasarela; `GET /billing/subscription` devuelve la suscripción de la cuenta con `in_force` (si el período pagado sigue vigente, según el reloj del servidor) o `null`.

**Confirmación del pago**

- **Una sola función mueve un pago y su suscripción**: `core/subscriptions.apply_transaction`, y solo con una transacción que salió de reconsultar a Wompi. La usan el webhook y `GET /billing/payments/:id`.
- `POST /webhooks/wompi`: (1) guarda todo evento, con firma válida o no; (2) sin firma válida responde `401` y no reconsulta nada; (3) con firma válida reconsulta la transacción por su id y aplica **esa** respuesta, no el cuerpo del evento. La referencia con la que se busca el pago es la de la respuesta de Wompi, no la del evento.
- **Idempotencia en dos capas.** `payment_events.provider_event_id`: Wompi no manda un id de evento, así que se usa el checksum verificado, que es el mismo en cada reintento. Un evento sin firma válida recibe un id de otro espacio de nombres (`wompi:invalid:…`), para que uno falsificado no pueda ocupar el id de uno auténtico. Y el pago mismo: se resuelve una sola vez, con la fila bloqueada, llegue lo que llegue después.
- Si Wompi no responde a la reconsulta, el webhook contesta `502`, el evento queda sin procesar y el reintento de Wompi lo retoma.
- Una transacción aprobada por un monto o una moneda distintos a los del pago no concede nada: el pago queda en `error`.
- `GET /billing/payments/:id` acepta `?transaction_id=`, que es el `id` que Wompi agrega a la URL de regreso. Viene del navegador: solo sirve para saber qué reconsultar, y la respuesta se aplica solo si su referencia es la de ese pago.
- El pago aprobado activa la suscripción, fija el período, registra la redención del cupón (una por cuenta) y sube `redemptions_count` en SQL. `discount_periods_remaining` queda listo para las renovaciones: 0 con `once`, `duration_periods − 1` con `repeating`, nulo con `forever`.
- **`users.access_type` no se toca**: el acceso sale de la suscripción, por `has_access`, que no cambió.
- Correos: bienvenida al activar y recibo de cada cobro aprobado, solo en la llamada que resolvió el pago. El recibo dice que es una constancia de pago, no una factura.

**Frontend**

- `/planes`: el botón depende de la cuenta (ver "Decisiones"). Una cuenta con documentos por aceptar tampoco ve el botón: no podría pagar, y el aviso de la página la lleva a aceptarlos.
- `/planes/pagar?plan=…`: resumen, campo de cupón, total del servidor, la nota de la tasa de cambio y el botón que lleva a Wompi. Sin correo confirmado el botón está apagado.
- `/pago/:id`: a donde vuelve el cliente. Consulta el pago cada 3 segundos, unos dos minutos, y muestra lo que responda el servidor; si sigue pendiente, lo dice y deja de consultar sola.

**Tests**

- `tests/payments/test_wompi.py` y `tests/billing/test_periods.py`: firmas, lectura de eventos, reconsulta, validación de llaves y cálculo de períodos, sin base ni red.
- `tests/api/test_subscriptions.py`: usa el `WompiProvider` de verdad con un transporte HTTP que responde desde un diccionario, así que pasa por la verificación de firma real sin salir a la red. De §3.9, en verde los que tocan esta entrega: firma inválida, evento duplicado, transacción declinada, suscripción vencida, reconsulta que contradice al evento, referencia desconocida, monto enviado por el cliente y cupón rechazado con motivo. Además: cuenta sin correo confirmado (§5.8) y una sola redención por pago aprobado.
- Playwright (`e2e/subscribe.spec.ts`): una cuenta sin acceso se suscribe con cupón en la pasarela simulada y entra a la mesa; pago rechazado; sin correo confirmado; el administrador no ve la opción de suscribirse.

**Lo que queda sin probar o sin hacer**

- Contra el sandbox se probó el 2026-10-13 el pago aprobado con tarjeta: firma de integridad, regreso con `?id=`, reconsulta y, en el VPS, el webhook con eventos reales. **Faltan un pago rechazado y un medio que no responde de inmediato** (PSE o Nequi), que es el caso en que el webhook resuelve el pago sin ayuda de la pantalla. Queda anotado en `DESPLIEGUE.md`.
- El VPS corre con llaves de sandbox: hasta pasar a las de producción, cualquier cuenta obtiene acceso pagando con la tarjeta de prueba.
- Wompi rechaza una dirección de regreso con `localhost` o `127.0.0.1` (`403` en el checkout). No afecta a producción; para probar en local se usa `localtest.me` (`DESPLIEGUE.md`).
- La documentación de Wompi no describe una consulta por referencia. Si el cliente no vuelve del checkout y el webhook no llega, el pago queda `pending` hasta que llegue un evento.
- **Un pago aprobado que después se anula o se reembolsa no quita el acceso**: el pago ya está resuelto y el evento posterior no lo mueve. Hoy se corrige a mano; el admin de pagos es de la entrega 3 y del paso 6. **Desde el paso 6 (§4.8) la anulación sí retira el período**; el reembolso se registra a mano.
- Una renovación manual no aplicaba el descuento de un cupón `repeating` o `forever`. **Corregido en la entrega 2** (§3.14).
- No se usa `expiration-time` en el checkout: un pago abierto se puede completar más tarde, al precio con que se abrió.
- `past_due` no daba acceso en `has_access`. **Desde la entrega 2 sí**, mientras el período pagado esté vigente (§3.14).
- La exportación de datos de la cuenta (`GET /auth/me/export`) devolvía `payments` vacío. **Desde la entrega 3 trae la suscripción y los pagos** (§3.15).

### 3.13 Wompi, entrega corta: la suscripción en `/cuenta` y en el admin (2026-10-13)

Adelantada de la entrega 3 por decisión del usuario, antes de la entrega 2 (rama `fase-4-paso-5a2-suscripcion-en-cuenta-y-admin`). Con la entrega 1 ya desplegada, el administrador veía cuentas con acceso por "Suscripción" sin poder saber qué habían pagado, y el suscriptor no encontraba su suscripción en ninguna parte. **Todo es de solo lectura**: cancelar, reanudar, cambiar el medio de pago y las acciones del admin sobre una suscripción o un pago siguen en la entrega 3.

**Decisión del usuario: el acceso manual sobre un suscriptor queda como está, y se explica.** `has_access` evalúa el acceso manual antes que la suscripción (§2.2), así que:

- Darle **Invitado** o **Completo** a un suscriptor sí tiene efecto: entra por ese acceso, y mientras lo tenga no se le ofrece pagar (`409 already_has_access`). Su período pagado sigue corriendo debajo.
- Dejarlo en **Sin acceso manual** no le quita la mesa: sigue entrando por su suscripción. Para sacarlo, se suspende la cuenta.
- El formulario de acceso manual de `/admin/usuarios` lo dice cuando la cuenta tiene una suscripción vigente. La alternativa (que el servidor rechace el acceso manual a quien paga) se descartó.

**API**

- `GET /billing/payments`: el historial de la cuenta, paginado (`limit`, `offset`), lo más reciente primero. **No trae los pagos `pending`**: casi todos son intentos que no se completaron. Al cliente no le llegan la referencia ni lo que dijo el proveedor.
- `GET /admin/users/:id` suma `subscription` (la que tiene un período pagado, con `in_force`) y `payments`: los últimos 20 intentos, incluidos los que no se completaron, con su referencia, el id de la transacción en Wompi y el motivo del rechazo.
- `GET /admin/users?subscription=`: `in_force` (período pagado vigente), `lapsed` (pagó y venció), `pending` (abrió un pago y no lo completó) o `none` (nunca abrió uno). **No es `subscriptions.status` tal cual**, como proponía §4.3: hoy nadie pone el estado `expired`, así que una suscripción vencida sigue en `active`, y filtrar por la columna habría mostrado como activas cuentas sin acceso. Es un filtro de lista; la decisión de acceso de cada fila sigue siendo la de `has_access`. Cuando la entrega 2 introduzca `past_due` y `expired` se revisa si hace falta además el estado crudo.
- `api/presenters.py` arma la suscripción y el pago (`subscription_response`, `payment_response`, `admin_payment_response`) para el usuario y para el admin.

**Frontend**

- `/cuenta`: tarjeta **Suscripción** (plan, vigente o vencida, hasta cuándo, precio congelado, que no se renueva sola y el enlace para pagar el período siguiente) y tarjeta **Historial de pagos**.
- `/admin/usuarios`: filtro "Suscripción", y en el detalle de la cuenta el bloque de suscripción y pagos y la nota del acceso manual.
- `/planes` ya no ofrece un pago que el servidor rechazaría: una cuenta con acceso manual, suspendida o con documentos por aceptar no ve el botón aunque tenga una suscripción vigente. Era una inconsistencia de la entrega 1.
- La lista de `/admin/usuarios` descarta la respuesta de una búsqueda anterior que llegue tarde: la lista completa del primer render podía pisar el resultado de una búsqueda ya hecha.

**Tests**

- Los tests de API ya no dependen de las llaves de `backend/.env`: el cliente de tests arranca siempre sin pasarela, y el test que necesita una la pone encima. Con las llaves de sandbox en el `.env` local, un test habría construido el proveedor real.
- `tests/api/test_subscriptions.py`: historial de la cuenta, detalle del admin y los cuatro valores del filtro. Playwright: `/cuenta` después de pagar, el admin que encuentra la cuenta por su suscripción, el suscriptor con acceso manual, y la cuenta que nunca ha pagado.

**Lo que seguía pendiente** y dónde quedó: cancelar y reanudar (§3.14); cambiar el medio de pago y el modo, la sección de pagos de la exportación de datos y el borrado de la cuenta con pagos (§3.15). Las acciones del admin (extender, cancelar, reconsultar) y los reembolsos en el admin son del paso 6.

### 3.14 Wompi, entrega 2: tokenización y renovación automática (2026-10-13)

Segunda de las tres entregas del paso 5 (rama `fase-4-paso-5b-renovacion`). **El paso 5 no está cerrado**: falta la entrega 3.

**Probado contra el sandbox de Wompi el 2026-10-13, en local, con tarjeta.** El usuario escribió la tarjeta de prueba en el widget: guardó el medio, el primer cobro quedó aprobado y la cuenta entró. Después se adelantó el vencimiento de esa suscripción en la base de la prueba y se corrió el job tres veces: avisó, cobró a la fuente guardada y, con el cobro aprobado, extendió el período. También se probó la tarjeta que Wompi rechaza: el pago queda `declined` y no hay acceso. **Nequi y las tarjetas con 3D Secure siguen sin probar**; la lista está al final.

**Decisiones del usuario (2026-10-13)**

- **Se pueden guardar tarjetas y Nequi.** Daviplata y Bancolombia quedan fuera; quien quiera pagar con otro medio tiene el pago manual.
- **La tarjeta se escribe en el widget de Wompi**, en modo tokenización. A nuestra página solo vuelve un token y su tipo. **Reemplazada el 2026-10-19** por un formulario propio que tokeniza contra la API de Wompi (§3.16).
- **Cancelar y reanudar la renovación entran en esta entrega** (estaban en la 3): no se enciende un cobro automático que el cliente no pueda detener. Cambiar el medio de pago y pasar de un modo al otro siguen en la entrega 3.
- **Ningún modo entra marcado** en la pantalla de pago: el cliente elige entre pago manual y renovación automática, y el botón no se enciende antes.
- El aviso va 7 días antes del primer intento de cobro (decidido en la entrega 1); en el pago manual, 7 días antes del vencimiento.

**Proveedor**

- `PaymentProvider` suma `tokenizer`, `acceptance`, `create_payment_source` y `charge`. Las URL de la documentación y la fecha de consulta están en el encabezado de `payments/wompi.py`.
- El widget en modo tokenización está mencionado en la documentación ("Fuentes de pago") sin detallar qué devuelve. Se leyó del propio `widget.js` el 2026-10-13: se abre con la llave pública y `widgetOperation: "tokenize"`, y al terminar llama al callback con `{ payment_source: { token, type } }`. Queda anotado en `frontend/lib/tokenize.ts`. Si Wompi cambia el widget, es lo primero que hay que volver a mirar.
- El cobro a un medio guardado lleva la misma firma de integridad del checkout, `recurrent: true` y, solo si es tarjeta, `installments: 1`.
- La pasarela simulada tiene "medios" de prueba (cobros aprobados, cobros rechazados, medio que no se puede guardar) para Playwright y desarrollo.

**Datos**

- Una migración, solo DDL: `subscriptions.payment_source_type` (`CARD` | `NEQUI`) y `subscriptions.notice_sent_for`, el `current_period_end` del período cuyo aviso ya se envió. Es lo que hace que el aviso salga una vez por período aunque el job corra cada hora.
- **Nunca se guardan datos de tarjeta ni el token**: solo `payment_source_id` (la referencia de Wompi), `card_brand` y `card_last4`. Un test vuelca las filas y lo comprueba.

**Alta con medio de pago guardado**

- `GET /billing/acceptance` (con sesión) trae los dos contratos de Wompi y sus tokens, pedidos al momento. `GET /billing/availability` dice además cómo se tokeniza (`tokenizer`) y la llave **pública**.
- `POST /billing/subscriptions` acepta `renewal_mode: "automatic"` con `payment_source_token`, `payment_source_type`, `acceptance_token` y `personal_data_token`. Guarda el medio en Wompi **antes** de escribir nada: si Wompi no lo acepta (`400 payment_source_rejected`), no queda ni suscripción ni pago. Después crea el pago y le cobra. Responde `202` sin `checkout_url`; la pantalla de resultado espera igual que en el pago manual.
- Si Wompi no contesta al cobrar, el pago queda en `error` sin transacción y la respuesta es `502`. **Ese pago todavía se puede resolver**: si el cobro sí llegó a Wompi, su evento lo activa después.
- Con una suscripción vigente: la que se renueva sola no admite un pago manual (`409 renews_automatically`), y la de pago manual no puede pasar a automática todavía (`409 mode_change_not_available`).

**Job de renovaciones**

- `backend/scripts/run_renewals.py`, cada hora. La lógica está en `core/renewals.py` y el calendario en `billing/schedule.py` (puro, con `mypy` estricto).
- **Calendario**: intentos a 48 h, 24 h y 0 h antes de `current_period_end`. Si el job estuvo caído, los atrasados se hacen de a uno por corrida, en orden.
- **Aviso antes del cobro**: 7 días antes del primer intento, una vez por período. Si a la hora de cobrar el aviso todavía no ha salido, esa corrida avisa y **no cobra**; el cobro queda para la siguiente. No se le escribe a una suscripción cancelada.
- **Idempotencia en dos capas**: el job toma un candado de Postgres (`pg_try_advisory_lock`) y, si otra corrida lo tiene, sale sin hacer nada; y cada intento lleva la referencia `SA-R-<suscripción>-<vencimiento>-<intento>`, que choca con la restricción única de `payments.reference` si ya existe. El pago se confirma en la base antes de cobrar.
- Al aprobarse, el período avanza desde el `current_period_end` anterior, no desde el día del cobro. El precio es el congelado de la suscripción, con el descuento que todavía lleve.
- **Cobro rechazado**: `past_due`, correo de cobro fallido, y el acceso sigue hasta `current_period_end`. Si Wompi no contesta, cuenta como intento hecho pero no se le escribe al cliente: no fue su tarjeta.
- **Los tres fallan**: `expired` exactamente en `current_period_end`, sin gracia, con su correo. Un cobro todavía sin resolver impide vencer.
- **Pago manual**: aviso 7 días antes del vencimiento y, si no se pagó, `expired` con su correo. Una cancelada vence sin correo.
- Una suscripción con problemas no detiene a las demás: se registra y el script sale con código 1.

**Estados y acceso**

- `has_access` ahora da acceso también en `past_due` mientras el período pagado esté vigente, y reporta `expired` (y no `no_access`) para una suscripción que el job marcó como vencida. Son los dos únicos cambios en `core/access.py`.
- Al volver después de vencida se crea una suscripción nueva; la vencida queda como historia. `current_subscription` (lo que ven `/cuenta` y el admin) incluye las vencidas.

**Cupón `repeating`**

- `billing/pricing.renewal_quote` calcula cada renovación desde el precio congelado y `discount_periods_remaining`; cada renovación aprobada gasta uno. Con `forever` descuenta siempre. **El cupón no se vuelve a validar**: lo prometido al suscribirse se cumple aunque después se desactive o venza.
- Aplica igual al pago manual del período siguiente, que en la entrega 1 cobraba el precio completo.

**Cancelar y reanudar**

- `POST /billing/subscription/cancel`: solo para la renovación automática vigente. `status = canceled`, `cancel_at_period_end = true`, acceso hasta `current_period_end`, y correo de confirmación. El job no la cobra ni le avisa.
- Si había un cobro en curso al cancelar y se aprueba, ese período se le da pero la suscripción sigue cancelada.
- `POST /billing/subscription/resume`: antes del vencimiento, vuelve a `active` con su medio de pago. Si después de cancelar abrió otro pago sin completarlo, esa suscripción pendiente se descarta.

**Correos nuevos**: aviso del próximo cobro, período por vencer (pago manual), cobro fallido, suscripción vencida y renovación cancelada. La bienvenida dice si el plan se renueva solo. Los arma `core/billing_emails.py`.

**Frontend**

- `/planes/pagar`: selector de modo, los dos contratos de Wompi con sus casillas, y el botón que abre la ventana de Wompi.
- `/cuenta`: medio de pago guardado ("Visa •••• 4242"), próximo cobro, y cancelar o reanudar, con confirmación en la misma tarjeta.
- `/planes`: una suscripción que se renueva sola no lleva botón de pago.

**Tests**

- `tests/billing/test_schedule.py`: calendario, avisos, vencimiento y precio de la renovación, sin base ni red.
- `tests/api/test_renewals.py`: el job se llama directo con el `now` que cada caso necesita. De §3.9 quedan en verde los cuatro que faltaban: dos corridas sobre el mismo período → un solo cobro; cancelación → acceso hasta el fin del período y sin cobros; cambio de precio → renovación con el precio congelado; tres intentos fallidos → `expired` en `current_period_end`. **Con esto están los doce.**
- Playwright: renovación automática de punta a punta (elegir el modo, aceptar los contratos, guardar el medio, entrar, cancelar y reanudar) y primer cobro rechazado.
- Las migraciones se subieron, se bajaron y se volvieron a subir en una base desechable, y el script del job se corrió allí, también con el candado tomado.

**Lo que queda sin probar o sin hacer**

- **Lo que la prueba contra el sandbox corrigió o aclaró (2026-10-13)**: el widget entrega el token como se leyó en su código y ofrece tarjeta y Nequi. **La fuente de pago no trae la marca de la tarjeta** (su `public_data` solo tiene `bin`, `last_four`, `card_holder`, `validity_ends_at` y `type`); la marca viene en la transacción (`payment_method.extra.brand`), así que `apply_transaction` la anota con el primer cobro aprobado. **El widget solo tokeniza en un contexto seguro** (https o `localhost`): cifra la tarjeta en el navegador, y abierto desde `http://localtest.me` falla con "Tu tarjeta no pudo ser verificada (error desconocido)". En producción no afecta; para probar en local, `DESPLIEGUE.md`. En la ventana de Wompi los botones de tarjeta y Nequi se ven como deshabilitados (sin color, con el cursor de "no permitido") aunque funcionan.
- **Los botones que se ven deshabilitados en la ventana de Wompi son un defecto de Wompi, no nuestro** (investigado el 2026-10-19). La ventana es un iframe de `https://checkout.wompi.co/p/`, y el estilo de lo que hay dentro no se puede cambiar desde nuestra página. En modo tokenización, el `widget.js` vigente ese día (`configAsTokenize`) solo lee `publicKey` y `widgetOperation`, y nosotros ya mandamos las dos: no hay opción que corrija el aspecto. La documentación ("Fuentes de pago") solo muestra el modo tokenización como botón (`<script data-render="button" data-widget-operation="tokenize">` dentro de un `<form method="POST">`); nosotros lo abrimos por JavaScript (`new WidgetCheckout(...).open`). En el `widget.js` los dos caminos pasan por la misma configuración (`configAsTokenize`) y la misma ventana (`openModal`): el botón solo agrega el `<form>` al que se envía el token. Lo demás coincide con esa página: la fuente de pago se crea en el backend con la llave privada y los dos tokens de aceptación, y se usa solo si queda `AVAILABLE`; el cobro va con `payment_source_id`, la firma de integridad, `recurrent` y, si es tarjeta, `installments`. Se redactó un reporte para el soporte de Wompi. **El mismo día el usuario decidió reemplazar el widget por un formulario propio** (§3.16).
- **Nequi**: el token queda pendiente hasta que el cliente lo aprueba en su app. Se asumía que el widget espera esa aprobación antes de devolverlo. **Probado en la entrega 3** (§3.15): en el sandbox el widget entregó un token que Wompi aceptó como fuente de pago, y los cobros a esa fuente se aprobaron y se rechazaron según el número de prueba. No se escucha todavía el evento `nequi_token.updated`.
- **Tarjetas que exigen 3D Secure**: la documentación tiene una guía aparte (3RI) que no se implementó. Si el banco pide autenticación en un cobro sin el cliente presente, ese cobro se rechaza y sigue el camino de los reintentos.
- El cron no estaba programado al construir esta entrega. **El usuario lo programó en Dokploy el 2026-10-13**, al desplegarla (`DESPLIEGUE.md`). Sin él no hay cobros, ni avisos, ni vencimientos marcados (el acceso sí cae en su fecha, porque lo decide `has_access`).
- Cambiar el medio de pago, pasar de un modo al otro y el borrado de la cuenta con una renovación activa: **hechos en la entrega 3** (§3.15). Las acciones del admin sobre una suscripción son del paso 6.
- Una fuente de pago no se anula en Wompi al cancelar: la documentación solo describe anularla para Daviplata y Bancolombia.

### 3.15 Wompi, entrega 3: gestión de la suscripción y cierre de la cuenta (2026-10-13)

Tercera y última entrega del paso 5 (rama `fase-4-paso-5c-cuenta-y-cierre`). **Con ella el usuario dio el paso 5 por cerrado el 2026-10-13**, después de desplegarla y probarla en el VPS con llaves de sandbox. Cancelar y reanudar, el apartado de suscripción de `/cuenta`, el historial de pagos, la suscripción en el detalle del admin y su filtro ya habían entrado en las entregas anteriores (§3.13 y §3.14); aquí está lo que faltaba.

**Qué NO entra** (es del paso 6, como decía el encargo del paso 5): las acciones del admin sobre una suscripción o un pago (extender, cancelar, reconsultar) y `/admin/suscripciones` y `/admin/pagos`. Tampoco los reembolsos por API.

**Cambiar el medio de pago y pasar de un modo al otro**

Las dos cosas son sobre la misma suscripción, sin perder el período pagado, y ninguna cobra nada: el período vigente ya está pagado.

- `PUT /billing/payment-method {payment_source_token, payment_source_type, acceptance_token, personal_data_token}` guarda un medio de pago en la suscripción vigente, que queda renovándose sola con él. Un solo endpoint para tres casos: **cambiar la tarjeta o el Nequi** de una renovación automática, **pasar de pago manual a renovación automática**, y **reanudar una renovación cancelada con otro medio**. El medio se guarda en Wompi antes de escribir nada: si Wompi no lo acepta (`400 payment_source_rejected`), todo queda como estaba. Pide otra vez los dos contratos de Wompi, porque cada fuente de pago se crea con ellos.
- El primer cobro al medio nuevo es el de la renovación, con su aviso por correo antes. Al pasar de manual a automática se borra `notice_sent_for`: el aviso de vencimiento del pago manual no vale como aviso del cobro.
- **En mora (`past_due`)**: guardar un medio nuevo reintenta el cobro de inmediato (`core/renewals.retry_now`), sin esperar a la hora del siguiente intento. Es uno de los tres intentos del período y lleva la misma referencia que usaría el job, así que si el job llegara a hacerlo a la vez, uno de los dos choca con la referencia única. **Agotados los tres no se cobra más**: la suscripción vence en su fecha, y el cliente puede pasar a pago manual y pagar a mano antes.
- `DELETE /billing/payment-method` pasa a **pago manual**: se borra la referencia del medio de pago, la marca y los últimos cuatro, y no se cobra más. La diferencia con cancelar es lo que pasa después: a la de pago manual se le avisa del vencimiento y paga el período siguiente cuando quiera. Vale también desde una renovación cancelada o en mora.
- Abrir un pago con `renewal_mode: automatic` teniendo un período pagado sigue rechazado (`409 mode_change_in_account`): eso cobraría un período, y el cambio de modo no cobra.
- Correos: "Cambió el medio de pago" (dice si con eso se activó la renovación, que hoy no se cobró nada, y cuánto y cuándo es el próximo cobro) y "Tu suscripción pasó a pago manual". Los dos terminan con qué hacer si no fue el titular.
- La marca de una tarjeta recién guardada no se conoce hasta su primer cobro (§3.14): mientras tanto `/cuenta` muestra "Tarjeta •••• 4242". Ahora se anota con el primer cobro **resuelto**, aprobado o no, y solo si los últimos cuatro de la transacción son los de la tarjeta guardada (un cobro tardío a la tarjeta anterior no le pone su marca a la nueva).
- Un pago aprobado cuya suscripción pendiente se descartó (al reanudar o cambiar de modo con ese pago en curso) extiende la suscripción viva de la cuenta, en vez de quedar sin a quién darle el período.

**Eliminar la cuenta con pagos** (`DELETE /auth/me`; decidido el 2026-10-13: se conservan los pagos anonimizados y la suscripción se borra)

- La suscripción se borra en cascada, y con ella la referencia del medio de pago: eso es lo que cancela la renovación. Sin esa referencia no hay cómo volver a cobrar, y el job ya no encuentra la suscripción.
- `payments` queda sin cuenta (`user_id` null). La fila no tiene nada más que identifique a nadie.
- **`payment_events` se anonimiza** (`core/payment_privacy.py`): el evento de Wompi trae el correo del cliente y datos de su medio de pago, así que se reduce a qué transacción fue, su estado, su monto y su fecha. Un evento que llegue después de borrada la cuenta se guarda ya reducido.
- **`coupon_redemptions.user_id` pasa de `CASCADE` a `SET NULL`** (migración `c8e3a5d7f216`, solo DDL): el uso del cupón queda sin cuenta y `redemptions_count` sigue coincidiendo con las filas. En el admin aparece como "Cuenta eliminada". El downgrade borra los usos que ya quedaron sin cuenta.
- **Con un cobro en proceso no se elimina todavía** (`409`): un pago que Wompi ya recibió y no ha resuelto, si se aprobara después, quedaría cobrado sin cuenta. Un pago abierto que nunca llegó a Wompi no lo impide.
- El correo de despedida dice, si había suscripción, que se eliminó con la cuenta, que la renovación quedó cancelada y qué se conserva de los pagos. `/cuenta` lo avisa antes de confirmar: se pierde el acceso del período ya pagado.
- `user_consents` sigue borrándose en cascada (§6.7): no se tocó.

**Exportar los datos** (`GET /auth/me/export`): trae `subscription` y `payments` (todos, también los que no se completaron), como los ve su dueño: sin la referencia del pago ni la del medio de pago.

**Frontend**

- `components/billing/PaymentSourceForm.tsx`: los dos contratos de Wompi, la ventana de Wompi y el botón. Lo usan la pantalla de pago y `/cuenta`; no hay otro sitio donde se guarde un medio de pago.
- `/cuenta`, apartado de suscripción: "Cambiar el medio de pago", "Pasar a pago manual" y "Cancelar la renovación" en la automática; "Activar la renovación automática" en la de pago manual; "Reanudar" y "Reanudar con otro medio de pago" en la cancelada. Todo se confirma en la misma tarjeta.
- Una cuenta con acceso manual que además tiene una renovación automática ve las mismas acciones (antes solo veía la nota, sin forma de cancelar).
- `/planes/pagar`, al pagar a mano el período siguiente, enlaza a `/cuenta` para quien prefiera que se renueve sola.

**Tests**

- `tests/api/test_subscription_changes.py`: cambio de tarjeta sin cobro y renovación a la tarjeta nueva; medio rechazado; de manual a automática con su aviso antes del cobro; de automática a manual; reanudar con otro medio; en mora, reintento inmediato, tope de tres y cobro en curso; borrado con renovación activa (pagos, evento, cupón, job); cobro en proceso; evento tardío; exportación.
- Playwright (`e2e/subscription-manage.spec.ts`): de manual a automática, cambio de medio y vuelta a manual; reanudar con otro medio; eliminar la cuenta con renovación.
- La migración se subió, se bajó (con un uso de cupón sin cuenta, que el downgrade borra) y se volvió a subir en una base desechable.

**Prueba contra el sandbox (2026-10-13, en local)**

Con las tarjetas de prueba publicadas por Wompi, tokenizadas por su API (sin el widget), y nuestra API para todo lo demás:

- Alta automática aprobada; paso a pago manual; de vuelta a automática con un medio nuevo, sin ningún cobro.
- Cambio a la tarjeta que Wompi rechaza; con el vencimiento adelantado en la base de la prueba, el job avisó, cobró y el cobro quedó rechazado: `past_due`, con acceso, y la marca de esa tarjeta anotada.
- En mora, cambio a la tarjeta buena: el reintento salió de inmediato con la referencia del segundo intento y quedó aprobado; el período se extendió desde el vencimiento.
- Exportación con la suscripción y los tres pagos.
- Cuenta eliminada: sin usuario ni suscripción, los tres pagos sin cuenta, y el job sin nada que hacer.

Y el usuario, en `/cuenta`, con la ventana de Wompi de verdad (desde `http://localhost`): cambiar el medio de pago, pasar a pago manual, activar la renovación automática, cancelar y reanudar, con tarjeta y con Nequi.

- **Nequi, de punta a punta**: guardó el Nequi de prueba que rechaza los cobros (`3992222222`); con el vencimiento adelantado, el job avisó, cobró y el cobro quedó rechazado ("Pago automático DECLINADO en Sandbox"), con la suscripción en mora y el acceso intacto. Después guardó el Nequi que aprueba (`3991111111`): el reintento salió de inmediato, quedó aprobado y el período se extendió.
- **Los números de prueba "de rechazo" de Wompi rechazan el cobro, no el guardado**: una tarjeta o un Nequi de esos se guarda sin problema, y el rechazo aparece al cobrarle (en el alta o en la renovación). En `/cuenta` no se cobra nada, así que ahí siempre "pasa".

**Lo que queda sin probar o sin hacer**

- **Tarjetas con 3D Secure**: siguen como en §3.14. Nequi ya se probó (arriba); lo que no se escucha todavía es el evento `nequi_token.updated`, que en el sandbox no hizo falta.
- En el sandbox un cobro a una fuente de pago responde `PENDING` y se resuelve segundos después. Con el webhook (VPS) llega solo; en local lo resuelve la siguiente corrida del job. Por eso, tras cambiar la tarjeta en mora, `/cuenta` puede decir que el cobro "todavía no pasó" y el resultado llega por correo.
- **La fuente de pago no se anula en Wompi** al cambiarla, al pasar a manual ni al eliminar la cuenta: se borra nuestra referencia, que es lo único con lo que se le puede cobrar desde aquí. La documentación solo describe anularla para Daviplata y Bancolombia.
- Un cobro del job que coincida en el mismo instante con el borrado de la cuenta puede quedar aprobado sin cuenta. Queda en el log como error ("aprobado sin suscripción") y se devuelve a mano desde el panel de Wompi.
- Acciones del admin sobre suscripciones y pagos, y que un pago anulado o reembolsado quite el acceso: paso 6. **Hechas en la entrega 1 del paso 6** (§4.8).

### 3.16 Tokenización con un formulario propio (decidida el 2026-10-19, por construir)

**Decisión del usuario (2026-10-19)**: el widget de Wompi en modo tokenización se reemplaza por un formulario nuestro que tokeniza contra la API de Wompi, como lo describe su documentación. Reemplaza la decisión del 2026-10-13 de escribir la tarjeta en el widget (§3.14). Motivos: en la ventana del widget los medios de pago se ven deshabilitados aunque funcionan, y eso no se puede corregir desde nuestra página; además, abrirlo en modo tokenización por JavaScript no está en la documentación, que solo lo muestra como botón dentro de un `<form>` (§3.14, "Lo que queda sin probar o sin hacer").

**Fuente de verdad**: "Fuentes de pago" (`https://docs.wompi.co/docs/colombia/fuentes-de-pago/`) y la sección "Tokeniza una tarjeta" de "Métodos de pago" (`https://docs.wompi.co/docs/colombia/metodos-de-pago/#tokeniza-una-tarjeta`), consultadas el 2026-10-19. Al construir se vuelven a leer: nada de memoria (§3.1).

**Lo que no cambia**

- La fuente de pago la crea el backend: `POST /v1/payment_sources` con la llave privada, `type`, `token`, `customer_email`, `acceptance_token` y `accept_personal_auth`, y solo sirve si queda `AVAILABLE` (`payments/wompi.create_payment_source`). El cobro, el job de renovaciones, las referencias y la idempotencia tampoco cambian.
- Los dos contratos de Wompi se aceptan en nuestra pantalla antes de tokenizar (`GET /billing/acceptance`).
- Solo tarjeta y Nequi. Daviplata y Bancolombia siguen fuera.
- Nunca se guarda el token ni un dato de tarjeta: solo la referencia de la fuente de pago, la marca y los últimos cuatro.
- `components/billing/PaymentSourceForm.tsx` sigue siendo el único lugar del frontend que guarda un medio de pago, en el alta (`/planes/pagar`) y en `/cuenta`. La pasarela simulada (`fake`) sigue para Playwright y desarrollo.
- El pago manual sigue con el Web Checkout de Wompi (§3.12).

**Lo que cambia**

- **Tarjeta**: el formulario pide número, CVC, mes y año de vencimiento (dos dígitos cada uno) y titular. Se tokeniza con el flujo cifrado, que es el que recomienda la documentación: `GET /v1/tokens/keys/tokenization` para la llave de cifrado y `POST /v1/tokens/cards` con un JWE (RSA-OAEP-256, A256GCM) en el campo `payload`, con la llave **pública** del comercio como Bearer. Wompi responde el token en `data.id`. El flujo simple, sin cifrar, solo con decisión del usuario.
- **Los datos de la tarjeta van del navegador directo a Wompi y nunca pasan por nuestro backend**: ni en una petición, ni en un log, ni en GlitchTip, ni en `localStorage`. Se borran del estado del formulario al terminar, salga bien o mal. Si la API de tokens no admite llamadas desde el navegador (CORS), no se resuelve pasándola por nuestro servidor: eso amplía lo que el comercio tiene que cumplir y es otra decisión del usuario.
- **Nequi**: el cliente escribe su celular; `POST /v1/tokens/nequi` con la llave pública devuelve un token `PENDING`; el cliente acepta la suscripción en su app; se consulta `GET /v1/tokens/nequi/{id}` hasta que quede `APPROVED`, con un tiempo límite y la opción de volver a intentar. Solo entonces el token va a nuestro backend, como hoy.
- Un token de tarjeta no se usa más de dos veces (lo dice la documentación): cada intento de guardar pide uno nuevo.
- `TokenizerInfo.kind` deja de ser `wompi_widget`, y `frontend/lib/tokenize.ts` se reescribe sin `widget.js`.

**Por confirmar antes del lanzamiento** (§10 n.º 15): con el widget la tarjeta se escribía en una ventana de Wompi; con el formulario se escribe en nuestra página. En general eso amplía lo que exige PCI DSS (de SAQ A a SAQ A-EP), así que hay que preguntarle a Wompi qué pide. Las cabeceras CSP de §13.4 pasan a convenir.

**Cómo se da por bueno**: los tests de backend y de Playwright en verde, y una prueba a mano contra el sandbox, en `/planes/pagar` y en `/cuenta`, con una tarjeta que aprueba, una que rechaza el cobro, y los Nequi de prueba `3991111111` (aprueba) y `3992222222` (rechaza).

---

## 4. Admin dashboard

### 4.1 Estructura

La página única actual se divide en secciones con navegación lateral (`frontend/app/admin/layout.tsx`):

| Ruta | Contenido |
|---|---|
| `/admin` (Resumen) | Indicadores del negocio (§4.7). |
| `/admin/usuarios` | Lista, búsqueda, detalle y acciones (§4.2). |
| `/admin/suscripciones` | Lista por estado y acciones (§4.3). |
| `/admin/pagos` | Cobros y eventos de Wompi (§4.3). |
| `/admin/planes` | CRUD de planes (§4.4). |
| `/admin/descuentos` | CRUD de cupones y su uso (§4.5). |
| `/admin/juegos` | El CRUD actual de juegos y variantes, más los campos nuevos de §7. |
| `/admin/legal` | Versiones de documentos legales (§6.2). |
| `/admin/motor` | El backtest actual (`BacktestPanel`). Sigue siendo la excepción de terminología: métricas internas que el cliente no ve. |
| `/admin/auditoria` | Bitácora de acciones de administradores (§4.6). |

Todas las listas del backend se paginan (`limit`, `cursor` u `offset`) y filtran en el servidor; ninguna devuelve la tabla completa.

### 4.2 Usuarios

- Búsqueda por correo o nombre; filtros por estado de acceso, rol, correo verificado, estado de suscripción.
- Detalle: datos de la cuenta, decisión de acceso actual (la misma de `has_access`), suscripción, historial de pagos, consentimientos aceptados, cantidad de mesas.
- Acciones: otorgar acceso `invited` con vencimiento o `full`; retirarlo; cambiar rol; suspender / reactivar (`is_active`); reenviar verificación; forzar restablecimiento de contraseña (invalida sus sesiones, §5.3).
- Un admin no puede quitarse a sí mismo el rol de admin ni suspenderse (evita quedar sin administradores).

### 4.3 Suscripciones y pagos

- Filtros por estado (`active`, `past_due`, `canceled`, `expired`) y por plan.
- Acciones sobre una suscripción: extender `current_period_end` manualmente (compensación por un problema del servicio), cancelar de inmediato o al final del período.
- Pagos: lista de cobros con su estado y la cadena de eventos de Wompi asociada (incluidos los rechazados por firma). Acción "reconsultar en Wompi", que pasa por la misma función idempotente del webhook.
- Los reembolsos se hacen desde el panel de Wompi; aquí solo se registran (decisión pendiente si se integran por API, §10).
- **Construido el 2026-10-14**: ver §4.8.

### 4.4 Planes

- Crear, editar, activar / desactivar, ordenar.
- Un plan con suscripciones (de cualquier estado) **no se borra**, se desactiva: deja de ofrecerse y las suscripciones existentes siguen renovando.
- Editar el precio muestra cuántas suscripciones vigentes **no** se ven afectadas (§3.7).
- Selección de juegos incluidos (`plan_games`, §7.4).

### 4.5 Descuentos

- Crear, editar, activar / desactivar cupones; ver redenciones (quién, cuándo, en qué suscripción).
- Un cupón con redenciones no se borra; se desactiva.
- Validación al guardar: `percent` entre 1 y 100; `fixed_cents` con moneda; `repeating` con `duration_periods`; `valid_until` posterior a `valid_from`.
- Los códigos pasan el filtro de terminología (nada tipo `GANASEGURO`).

### 4.6 Auditoría

```sql
admin_audit_log (
  id, admin_user_id,
  action,                 -- 'user.access.grant', 'subscription.extend', 'plan.update', ...
  target_type, target_id,
  before JSONB, after JSONB,
  reason,                 -- texto libre, obligatorio en acciones de dinero y acceso
  ip, created_at
)
```

Es **obligatorio** en toda acción que toque acceso, dinero, planes, cupones o documentos legales. Se escribe en la misma transacción que el cambio: si la auditoría falla, el cambio no ocurre. No tiene endpoint de borrado.

### 4.7 Resumen

Indicadores, todos calculados en el servidor y en centavos:

- Suscripciones por estado.
- Ingreso recurrente mensual normalizado (planes anuales divididos entre 12), por moneda.
- Altas y cancelaciones del período; tasa de cancelación.
- Cobros fallidos y suscripciones en `past_due`.
- Registros nuevos y cuántos verificaron el correo.

Sin gráficos elaborados en la primera versión: tarjetas con número y comparación contra el período anterior.

**Decidido el 2026-10-14** (construido en la entrega 2 del paso 6, §4.9): el período es el **mes calendario en hora de Bogotá** (America/Bogota, sin horario de verano), y se compara el mes en curso hasta hoy contra el mismo tramo del mes anterior (del día 1 al mismo día), con cortes a medianoche de Bogotá.

### 4.8 Suscripciones y pagos: cómo quedó construido (2026-10-14)

Paso 6, entrega 1 (rama `fase-4-paso-6a-suscripciones-y-pagos`). La entrega 2 (navegación lateral, `/admin/juegos`, `/admin/motor`, resumen, forzar el restablecimiento y reenviar la verificación) y la del traslado de precio (abajo) no están hechas. **El paso 6 no está cerrado.**

**Decisiones del usuario (2026-10-14)**

- **Anulaciones y reembolsos.** Una anulación la reporta Wompi como cambio de estado de la transacción (`VOIDED`, solo con tarjeta, llega como `transaction.updated`). Por eso **la anulación quita el acceso sola**: cuando la reconsulta (del webhook o de "reconsultar" en el admin) dice que un pago aprobado quedó anulado, `apply_transaction` lo pasa a `voided` y retira el período que había comprado. Un reembolso, en cambio, es un objeto aparte en Wompi y no se vio que cambie el estado de la transacción ni que mande un evento (documentación consultada el 2026-10-14). Por eso **el reembolso se hace en el panel de Wompi y el administrador lo registra a mano**, con monto y motivo. El registro no cambia el pago ni el acceso. Si además hay que quitar el acceso, se cancela la suscripción de inmediato. Cierra §10 n.º 7.
- **Cancelar de inmediato quita el acceso en el acto y no devuelve nada.** El período termina ahora, la suscripción queda `expired` y se borra la referencia del medio de pago. Si corresponde devolver, se hace en Wompi y se registra.
- **Extender una renovación automática corre todo**: el próximo cobro y su aviso se calculan sobre el vencimiento nuevo.
- **Al cliente se le avisa por correo** en las tres acciones (extender, cancelar al final del período, cancelar de inmediato). El motivo del administrador es interno y no va en el correo.
- **Trasladar un precio nuevo a las suscripciones vigentes (§10 n.º 5): se construye**, en una entrega propia después de esta. Lo decidido: aviso por correo **30 días** antes de cobrar el precio nuevo (plazo a confirmar con el abogado); aplica a **todas las suscripciones vigentes del plan**, en los dos modos, y no a las canceladas; y **un cupón que todavía descuenta sigue descontando sobre el precio nuevo** (el porcentaje sobre el precio nuevo, el monto fijo igual). No está construido.

**Anulación posterior a la aprobación (`core/subscriptions.apply_transaction`)**

- Es lo único que mueve un pago ya resuelto, y solo si la transacción anulada es la misma que lo aprobó. Una vez anulado ya no vuelve a cambiar, así que un evento repetido o una reconsulta más no hacen nada.
- Si el período que compró es el último de la suscripción, el vencimiento vuelve a donde estaba antes del pago. Si con eso ya pasó, la suscripción vence y el acceso cae en el acto. Si el período anterior todavía corre (un cobro de renovación anticipado, 48 h antes, que se anuló antes de empezar), ese período se respeta y **la renovación automática se cancela**: volver a cobrarle a quien le anularon un cobro lo decide una persona, no el job. Una renovación anulada devuelve el período con descuento que había gastado.
- Si después ya se pagó otro período, **no se retira nada**: queda la nota "revisarlo a mano" en el pago.
- `payments.reversed_at` y `payments.reversal_note` guardan cuándo se supo y qué se hizo. No sale correo al cliente: la anulación la hizo el comercio en el panel de Wompi.
- `apply_transaction` recibe un `before_commit` opcional: el admin lo usa para que la fila de bitácora de "reconsultar" se confirme en la misma transacción que el cambio, también cuando no cambió nada.

**Acciones sobre una suscripción (`core/subscription_admin.py`)**

- `PATCH /admin/subscriptions/:id {action, days?, reason}`, con `action` `extend` (con `days`, de 1 a 90), `cancel_at_period_end` o `cancel_now`. Cada una deja su fila (`subscription.extend`, `subscription.cancel_at_period_end`, `subscription.cancel_now`) con el antes y el después, en la misma transacción. Ninguna toca un pago.
- Las tres exigen un **período vigente** (`409 not_in_force`): a una cuenta vencida se le da acceso manual. Y ninguna se hace con un **cobro en proceso** (`409 charge_in_progress`), porque si se aprobara después daría un período que el administrador no vio.
- **Extender** corre `current_period_end`. En mora, la suscripción vuelve a `active` con los intentos en cero: los fallidos eran del cobro del vencimiento anterior. `notice_sent_for` se queda apuntando al vencimiento viejo, así que el aviso vuelve a salir para la fecha nueva.
- **Cancelar al final del período** es lo mismo que cancela el cliente (`stop_renewal`). Solo aplica a la renovación automática (`409 not_automatic`, porque la de pago manual no se cobra sola) y no dos veces (`409 already_canceled`). El cliente puede reanudarla desde `/cuenta`.
- **Cancelar de inmediato**: `current_period_end` = ahora, `expired`, sin medio de pago, en modo manual. `has_access` responde `expired` con esa fecha. La cuenta puede volver a suscribirse: es un alta nueva.
- **Un administrador no se deja sin acceso**: entra por su rol, así que cancelar su propia suscripción no le quita la mesa ni el admin (test).
- Correos nuevos: "Extendimos tu suscripción", "Cancelamos la renovación de tu suscripción" y "Tu suscripción terminó" (`core/billing_emails.admin_change`).

**Listas, detalle y reembolsos (`api/v1/admin_payments.py`)**

- `GET /admin/subscriptions`: paginada (`limit` hasta 100, `offset`), con filtros en el servidor por `status`, `plan_id`, `renewal_mode` y correo. **Sin filtro de estado no trae las `pending`** (son pagos abiertos y no completados, que se ven en Pagos); con `status=pending` sí. El estado es la columna tal cual, que el job pone cada hora. `in_force` de cada fila dice si el período sigue vigente según el reloj del servidor.
- `GET /admin/subscriptions/:id`: la suscripción, sus últimos 50 pagos y su bitácora.
- `GET /admin/payments`: paginada, con filtros por `status`, `kind`, `reversed`, `refunded`, `subscription_id` y `user_id`, y búsqueda por correo, referencia o id de la transacción.
- `GET /admin/payments/:id`: el pago, sus eventos de Wompi, sus reembolsos y su bitácora. **Los eventos con la firma inválida nunca se asocian al pago** (no se reconsultan), así que el detalle muestra además los eventos sin pago cuyo cuerpo nombra la transacción o la referencia, marcados "no asociado al pago". Ese cuerpo no es confiable: solo se muestra.
- `POST /admin/payments/:id/requery {reason}`: reconsulta en Wompi y aplica con `apply_transaction`, la misma función del webhook. Un pago resuelto no se vuelve a resolver, así que reconsultarlo no da otro período (test). Sin transacción en Wompi responde `409`: la documentación no describe una consulta por referencia. Sin pasarela, `503`. Si Wompi no responde, `502`.
- `POST /admin/payments/:id/refunds {amount_cents, refunded_at, provider_refund_id?, reason}`: solo para un pago aprobado. La moneda es la del pago y la fecha no puede ser futura. Lo reembolsado no pasa de lo cobrado. Deja la fila `payment.refund.record`. Tabla nueva `payment_refunds` (migración `d9a4c2e7b815`, solo DDL, junto con las dos columnas de `payments`).
- `AdminPaymentResponse` suma la cuenta (`user_id`, `user_email`), `subscription_id`, la anulación y `refunded_cents`. El detalle de la cuenta (`GET /admin/users/:id`) muestra también la bitácora de su suscripción y de sus pagos.
- Todos responden `403` a una cuenta que no es administradora, y a un administrador suspendido.

**Frontend**

- `/admin/suscripciones`: filtros, lista y detalle con las tres acciones (`components/admin/SubscriptionActions.tsx`), sus pagos y su bitácora. "Cancelar de inmediato" pide marcar una casilla además del motivo.
- `/admin/pagos`: filtros, lista y detalle (`components/admin/PaymentDetail.tsx`) con los eventos (y su cuerpo, desplegable), los reembolsos, "Reconsultar en Wompi" y "Registrar un reembolso". Acepta `?query=`.
- `/admin/usuarios`: el detalle de la cuenta lleva las mismas acciones sobre su suscripción, y cada referencia de pago enlaza a `/admin/pagos`. `/admin` enlaza a las dos páginas nuevas; la navegación lateral es de la entrega 2.
- **Cambio del 2026-10-15:** el detalle de la cuenta ya no repite las acciones. Resume la suscripción, lista sus pagos y enlaza a `/admin/suscripciones?query=<correo>`, que abre con el detalle desplegado cuando hay una sola coincidencia. Ahí también cada referencia de pago enlaza a `/admin/pagos`. Las dos secciones se quedan: Usuarios responde quién es la persona; Suscripciones filtra por estado, plan y modo.

**Tests**

- `tests/api/test_admin_payments.py` (54): `403` en los siete endpoints para una cuenta que no es administradora; cada acción con su fila y su motivo, y rechazada sin motivo y sin fila; el efecto de extender, cancelar al final y cancelar de inmediato sobre `has_access` y sobre el job de renovaciones (lo que se canceló no se vuelve a cobrar; lo que se extendió se cobra en la fecha nueva, con su aviso); reconsultar un pago ya resuelto no da otro período; las anulaciones (por evento y por reconsulta, con período posterior, de una renovación anticipada, de otra transacción); los reembolsos; y el administrador que cancela su propia suscripción.
- Playwright (`e2e/admin-billing.spec.ts`): el administrador encuentra una suscripción, la extiende con motivo y lo ve en la bitácora; y desde el detalle de la cuenta la cancela de inmediato (la cuenta pierde la mesa) y registra un reembolso en Pagos. Desde el 2026-10-15 la cancela siguiendo el enlace de la ficha a Suscripciones.
- La migración se subió, se bajó con un pago anulado y un reembolso puestos, y se volvió a subir en una base desechable; `alembic check` sin diferencias.

**Lo que queda sin probar o sin hacer**

- **Una anulación real en el sandbox de Wompi**: el camino se probó con el doble de Wompi, no con una transacción anulada de verdad. Falta anular un pago con tarjeta desde el panel de Wompi y ver llegar el evento.
- **Qué hace Wompi con un reembolso**: si cambia el estado de la transacción o manda un evento. Si lo hiciera, hoy no se interpreta y queda solo el registro manual.
- Un pago manual abierto antes de una cancelación inmediata, que el cliente complete después en Wompi, le da un período nuevo: pagó por él.
- El cliente no ve los reembolsos registrados ni en `/cuenta` ni en la exportación de sus datos.
- `/admin` (el CRUD de juegos) sigue detrás de `AccessGate`; la entrega 2 lo mueve a `/admin/juegos`. **Hecho** (§4.9).

### 4.9 Navegación, resumen y acciones sobre la cuenta: cómo quedó construido (2026-10-14)

Paso 6, entrega 2 (rama `fase-4-paso-6b-navegacion-y-resumen`). **El paso 6 no está cerrado**: falta la entrega del traslado de un precio nuevo a las suscripciones vigentes (§4.8, §10 n.º 5).

**Decisiones del usuario (2026-10-14)**

- **Forzar el restablecimiento deja sin efecto la contraseña actual**, además de cerrar las sesiones. La cuenta solo vuelve a entrar con una contraseña nueva, elegida con el enlace del correo. Si el enlace vence (1 h), pide otro desde "Olvidé mi contraseña". Motivo obligatorio.
- **Reenviar la verificación deja fila en la bitácora, sin motivo**: no toca acceso ni dinero.
- **El ingreso recurrente mensual** cuenta las suscripciones vigentes que siguen (activas y en mora, de los dos modos, sin las canceladas). Cada una suma lo que costará su próximo período, con el descuento que todavía lleve, llevado a un mes. Se muestra el total y su reparto entre renovación automática y pago manual.
- **Se agrega "Cobrado, neto de reembolsos"**, que §4.7 no pedía: pagos aprobados en el mes menos los reembolsos registrados en el mes.
- Del resumen se había decidido antes el período: mes calendario en hora de Bogotá, hasta ahora, contra el mismo tramo del mes anterior (§4.7).

**Navegación (`frontend/app/admin/layout.tsx`)**

- Las secciones de §4.1 en una columna lateral (una fila que se desplaza en el celular), con el encabezado de la aplicación arriba y la sección actual marcada (`aria-current`). Solo se dibuja para un administrador; cada página sigue redirigiendo a quien no lo es y el servidor responde `403`.
- `/admin` es el **Resumen**. El CRUD de juegos pasó a **`/admin/juegos`** y el backtest a **`/admin/motor`**. Los dos siguen detrás de `AccessGate`, porque listan juegos con un endpoint de juego: un administrador también acepta los documentos vigentes. El resumen y las demás secciones no lo exigen.
- Las páginas perdieron su botón "Volver al panel": la navegación lo reemplaza.

**Resumen (`GET /admin/overview`, `core/overview.py`)**

- Todo se calcula en el servidor, en centavos y con la moneda. `core/overview.periods` arma las dos ventanas `[inicio, fin)` en hora de Bogotá y se prueba sin base. Un mes anterior más corto (31 de marzo frente a febrero) termina al final de ese mes; enero se compara con diciembre.
- **Fotos del momento, sin comparación** (la base no guarda cómo estaban en una fecha pasada): suscripciones por estado (la columna tal cual), cuántas tienen el período vigente, e ingreso recurrente mensual por moneda.
- **Flujos, con comparación**:
  - **altas**: suscripciones cuyo primer pago se aprobó en el período; volver después de vencida también es un alta, y un pago anulado no cuenta;
  - **cancelaciones**: `canceled_at` en el período, sea del cliente o del administrador; una suscripción reanudada deja de contar;
  - **tasa de cancelación**: cancelaciones sobre las suscripciones con un período pagado al empezar el mes, según sus pagos aprobados, en puntos básicos; es aproximada, porque una extensión hecha a mano no tiene pago que la respalde;
  - **cobros fallidos**: rechazados o con error resueltos en el período;
  - **registros nuevos** y cuántos de ellos ya confirmaron el correo; una cuenta eliminada deja de contar;
  - **cobrado**: neto de reembolsos.
- La pantalla muestra tarjetas sin gráficos, con la variación con signo y flecha (no solo color) frente al mes anterior. El ingreso recurrente es el número grande.

**Acciones sobre la cuenta (`api/v1/admin_users.py`)**

- `POST /admin/users/:id/force-password-reset {reason}`:
  - sube `token_version`, lo que cierra todas las sesiones y anula los refresh tokens;
  - reemplaza el hash de la contraseña por el de un secreto aleatorio que nadie conoce;
  - emite un token `reset_password` y envía el correo "Elige una contraseña nueva" (sin el motivo);
  - deja la fila `user.password.force_reset` con la versión antes y después, sin nada de la contraseña;
  - no aplica sobre uno mismo (`409`): la propia contraseña se cambia desde `/cuenta`.
- `POST /admin/users/:id/resend-verification`: el mismo correo y el mismo enlace que pide la cuenta desde `/cuenta`. Con el correo ya confirmado responde `409`. Un segundo envío dentro del minuto responde `429`; ese límite va aparte de los cupos de la propia cuenta, para no gastárselos. Deja la fila `user.verification.resend`.
- En `/admin/usuarios`, el detalle de la cuenta muestra "Reenviar el correo de confirmación" si no lo ha confirmado, y "Forzar el restablecimiento de la contraseña", que pide el motivo y marcar una casilla.

**Tests**

- `tests/core/test_overview_periods.py` (10, sin base): ventanas, fronteras de Bogotá, meses cortos y bisiesto, enero, el primer instante del mes, y las cuentas de mes y de tasa.
- `tests/api/test_admin_overview.py` (12): el resumen solo para administradores; suscripciones por estado, recurrente (el bimestral cuenta la mitad), altas, cobros fallidos y cobrado, antes y después de un reembolso y de una cancelación; la comparación con el tramo anterior y la tasa; registros. Forzar el restablecimiento: sesiones y refresh cerrados, la contraseña anterior ya no entra, fila con motivo y sin él se rechaza, no sobre uno mismo, `403` y `404`; con el enlace se elige otra y se entra. Reenviar: correo, fila sin motivo, `429` al repetir, `409` con el correo confirmado y `403`.
- Playwright (`e2e/admin-panel.spec.ts`): el resumen y la navegación por las secciones; una cuenta que no es administradora no ve el admin; forzar el restablecimiento (la sesión se cierra, la contraseña anterior no entra y la nueva sí); reenviar el correo de confirmación.

**Lo que queda**

- El traslado de un precio nuevo a las suscripciones vigentes (§10 n.º 5), en su propia entrega. Con ella se cierra el paso 6. **Hecho** (§4.10).

### 4.10 Traslado de un precio nuevo a las suscripciones vigentes: cómo quedó construido (2026-10-14)

Paso 6, entrega 3 (rama `fase-4-paso-6c-traslado-de-precio`). Con ella está construido todo el paso 6. Cierra §10 n.º 5: hasta aquí el precio de una suscripción quedaba congelado para siempre (§3.7).

**Decisiones del usuario (2026-10-14)**

- **Alcance**: todas las suscripciones vigentes del plan (activas y en mora), en los dos modos de pago, cuyo precio congelado sea distinto del actual del plan. No a las canceladas.
- **Subida**: se cobra desde **30 días después de que a cada cliente le llegó su aviso**, no desde que se registró el traslado. Los avisos los envía el job por lotes, y la fecha se anota solo si el envío salió bien: un cliente al que no le llegó el correo sigue pagando el precio viejo. El plazo lo debe confirmar el abogado.
- **Bajada**: aplica al registrar el traslado, desde el próximo cobro o pago. El aviso es informativo.
- **Cupones**: uno que todavía descuenta sigue descontando, sobre el precio nuevo. Un porcentaje se calcula sobre el nuevo; un monto fijo queda igual.
- **Cancelar**: se puede mientras no se haya aplicado. Las suscripciones que faltaban conservan su precio, y quien ya había recibido el aviso recibe otro que dice que el precio no cambia. Mientras un plan tenga un traslado en curso, no se registra otro.

**Datos** (migración `e3b7d1f9a462`, solo DDL)

- `price_changes`: el traslado, con el plan, el precio nuevo, la moneda, el motivo, quién lo registró y, si se canceló, cuándo y por qué.
- `subscription_price_changes`: una fila por suscripción alcanzada, con el precio viejo y el nuevo, cuándo salió su aviso (`notice_sent_at`), desde cuándo corre (`effective_at`), cuándo se aplicó (`applied_at`), si se canceló (`canceled_at`) y cuándo salió el aviso de la cancelación. Un índice único parcial impide dos traslados abiertos en una misma suscripción. Se borra en cascada con la suscripción, es decir, con la cuenta.
- El precio que se cobra sigue siendo `subscriptions.price_cents`. Un traslado lo cambia cuando llega su fecha (`applied_at`).

**Cálculo** (`billing/price_change.py`, puro, `mypy` estricto): la dirección del cambio, la fecha desde la que corre (`effective_at`) y el precio que corre en un momento dado (`price_at`).

**Lógica** (`core/price_changes.py`)

- `create` y `cancel`: las acciones del admin, cada una con su fila en la bitácora (`plan.price.transfer` y `plan.price.transfer.cancel`) en la misma transacción.
- `apply_due` pone el precio nuevo en `subscriptions.price_cents` cuando llega su fecha. Lo llaman:
  - el job, al empezar cada corrida y antes de cobrar;
  - el pago manual del período siguiente (`start_payment`);
  - el reintento inmediato de un cobro en mora (`retry_now`).

  Así ningún cobro sale con un precio que ya no corre. No toca ningún pago.
- `send_notices`: lo corre `scripts/run_renewals.py` después de las renovaciones. Envía hasta 40 avisos por corrida, para no gastar el tope diario de correos (`EMAIL_DAILY_LIMIT`), uno por uno y anotando cada uno solo si el envío no falló.
  - Una subida de una suscripción cancelada espera: si la reanuda, se le avisa.
  - Una subida de una suscripción que ya no tiene período vigente sale del traslado sin correo.
- **Los avisos previos al cobro muestran el precio que correrá ese día**: el de 7 días antes del cobro automático y el de vencimiento del pago manual. El cobro mismo usa `price_cents`, ya al día.

**API**

- `GET /admin/plans/:id/price-transfer`: cuántas vigentes subirían y cuántas bajarían, y el traslado en curso con su avance (avisadas, esperando su aviso, aplicadas, canceladas).
- `POST /admin/plans/:id/price-transfer {reason}`: traslada el precio actual del plan. Responde `409` si no hay suscripciones con otro precio o si ya hay un traslado en curso.
- `GET /admin/price-changes` (paginado, filtro por plan) y `POST /admin/price-changes/:id/cancel {reason}`.
- `SubscriptionResponse.price_change`: el precio nuevo ya avisado y desde cuándo corre. `next_charge_cents` se calcula con el precio que correrá en la fecha del próximo cobro.

**Correos**: aviso de subida (de cuánto a cuánto, desde qué fecha, que el descuento sigue, y cómo cancelar la renovación o pasar a pago manual antes de esa fecha), aviso de bajada, y "el precio no cambia" al cancelar.

**Frontend**

- `/admin/planes`, debajo del formulario de cada plan: cuántas vigentes suben o bajan y qué pasa en cada caso, el botón para trasladar (con motivo y casilla de confirmación), y el traslado en curso con su avance y el botón para cancelarlo.
- `/cuenta` y el detalle de la suscripción en el admin muestran el precio nuevo ya avisado y desde cuándo corre.

**Tests**

- `tests/billing/test_price_change.py` (5, sin base).
- `tests/api/test_price_transfer.py` (20):
  - solo administradores;
  - alcance (las canceladas y las vencidas no entran), fila con motivo, y sin motivo se rechaza;
  - el aviso fija la fecha 30 días después;
  - un aviso que no sale no hace correr el plazo, ni con el tiempo;
  - el cobro antes de la fecha va con el precio viejo y el siguiente con el nuevo, con el cupón del 20 % descontando del nuevo; el aviso de 7 días ya muestra el monto nuevo;
  - el pago manual del período siguiente, antes y después de la fecha;
  - la cancelada que espera y recibe el aviso al reanudar, y la que vence y sale del traslado;
  - los lotes; la bajada que aplica ya y se cobra;
  - cancelar, antes y después del aviso; el historial; y que no se mueve ningún pago.
- Playwright (`e2e/price-transfer.spec.ts`): el administrador sube el precio de un plan, traslada el precio a la suscripción de una cuenta, el cliente sigue viendo su precio mientras no sale el aviso, cancela el traslado y lo ve en la bitácora.
- La migración se subió, se bajó con filas puestas y se volvió a subir en una base desechable; `alembic check` sin diferencias, y el índice parcial rechaza un segundo traslado abierto. El script del job se corrió en otra base desechable.

**Ajuste del 2026-10-15: un período, un precio**

Salió de un caso real en el VPS: una bajada a 99.000 y la vuelta a 100.000. La subida corría desde el 13 de noviembre, el período vencía el 14 y su primer intento de cobro era el 12. `/cuenta` decía "Precio nuevo 100.000, desde el 13 de noviembre" junto a "Próximo cobro 99.000, a partir del 12 de noviembre", y parecía un error. Además, cada intento tomaba el precio de su hora: si el del 12 fallaba, el reintento del 13 salía por 100.000, distinto de lo que había dicho el aviso de 7 días. Decidido por el usuario:

- **Los tres intentos del cobro automático de un período van con el precio que corre en el primero** (`schedule.first_charge_at`), el mismo que dice el aviso de 7 días. Una subida que empieza a correr entre un intento y otro no cambia el monto de los reintentos; una bajada sí los alcanza, porque solo favorece al cliente. Lo calcula `billing/price_change.charge_price` (puro); lo usan `core/renewals` en el aviso y en cada intento, y el presentador para "Próximo cobro".
- **La pantalla y el correo de una subida dicen desde qué cobro se paga el precio nuevo** en la renovación automática (`UpcomingPriceChange.first_charge_at`, de `billing/price_change.first_charge_with_new_price`): "desde el cobro del 12 de diciembre de 2026". En el pago manual sigue la fecha desde la que corre, que aplica a los pagos hechos desde entonces.
- Tests: `tests/billing/test_price_change.py` (el caso, la subida que corre antes del primer intento, la bajada entre intentos, el primer cobro con el precio nuevo) y, en `tests/api/test_price_transfer.py`, el período con el primer intento rechazado y los reintentos después de la fecha, y la bajada entre dos intentos.

**Lo que queda sin probar o sin hacer**

- El plazo de 30 días y el texto de los avisos los revisa el abogado (§3.11, "Para el abogado").
- El aviso de un traslado y el aviso de 7 días antes del cobro pueden llegar el mismo día si el traslado se registra a menos de una semana de un cobro. No es un problema de fechas (el precio nuevo no corre hasta 30 días después), pero el cliente recibe dos correos seguidos.
- El job programado en el VPS y el correo real: **probados el 2026-10-14** por el usuario, con un plan de prueba (una subida con su aviso, la cancelación del traslado y una bajada, con los avisos enviados por el job y correo real). Con esto el paso 6 quedó cerrado.
- El resumen no guarda historia: las fotos del momento no tienen contra qué compararse. Si hace falta, sería una tabla de cortes diarios escrita por un job, y eso no está decidido.

---

## 5. Mejoras de autenticación

### 5.1 Tokens de un solo uso

```sql
user_tokens (
  id, user_id,
  purpose,          -- 'verify_email' | 'reset_password' | 'change_email'
  token_hash,       -- SHA-256 del token; el token en claro solo viaja en el correo
  new_email,        -- solo con change_email
  expires_at, used_at, created_at
)
```

- El token es aleatorio (`secrets.token_urlsafe(32)`), se guarda **solo su hash** y se marca `used_at` al consumirse.
- Vigencia: verificación 48 h, restablecimiento 1 h, cambio de correo 24 h.
- Emitir un token nuevo de un propósito invalida los anteriores sin usar del mismo propósito y usuario.

### 5.2 Verificación de correo

- Al registrarse se envía el correo con el enlace `FRONTEND_BASE_URL/verificar-correo?token=…`.
- `POST /auth/verify-email {token}` → `email_verified = true` y `email_verified_at`.
- `POST /auth/resend-verification` con rate limit.
- **Requisito para pagar**: `POST /billing/subscriptions` rechaza con `403 email_not_verified`. El usuario puede iniciar sesión sin verificar (para ver planes, su cuenta y reenviar el correo).

### 5.3 Contraseña

- `POST /auth/forgot-password {email}` responde **siempre** igual (`202` con mensaje genérico), exista o no el correo, y tarda lo mismo: no revela qué correos están registrados (§3.6 del doc de arquitectura).
- `POST /auth/reset-password {token, new_password}`.
- `POST /auth/change-password {current_password, new_password}` con la sesión iniciada.
- **Revocación de sesiones**: `users.token_version` (entero) viaja en el JWT. Restablecer o cambiar la contraseña, o que un admin fuerce el restablecimiento, la incrementa; `get_current_user` y `/auth/refresh` rechazan tokens con versión vieja. Cierra todas las demás sesiones sin necesitar una tabla de refresh tokens.
- Política mínima de contraseña: 10 caracteres; se rechazan las contraseñas más comunes con una lista local (sin llamadas a servicios externos).
- Correo de aviso "tu contraseña cambió" tras cada cambio.

### 5.4 Cuenta

- `PATCH /auth/me` para el nombre visible.
- `POST /auth/change-email {new_email, password}` → correo de confirmación al correo nuevo; el cambio se aplica al confirmar. Aviso al correo anterior.
- `DELETE /auth/me {password}` → elimina la cuenta (derecho de supresión, §6.4). Si tiene suscripción activa, primero se cancela la renovación. Los registros de pagos se conservan anonimizados por obligación contable.
- Página `/cuenta`: perfil, seguridad, suscripción, método de pago, historial de pagos, documentos aceptados, eliminar cuenta.

### 5.5 Envío de correo

- `backend/app/core/email.py`: interfaz `EmailSender` con `send(to, subject, html, text)`.
  - `SmtpEmailSender` (producción), configurado con `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`.
  - `ConsoleEmailSender` (desarrollo): imprime el correo en el log.
  - `FakeEmailSender` (tests): guarda los correos en una lista para que el test lea el enlace.
  - `FileEmailSender` (tests de punta a punta, §13.3): escribe cada correo como un archivo JSON en `EMAIL_FILE_DIR`, de donde Playwright lee el enlace. El arranque de la API lo rechaza si hay llaves de producción de Wompi configuradas.
- Plantillas en `backend/app/emails/` (HTML + texto plano), en español, con el pie legal.
- El envío va en `BackgroundTasks`: un SMTP lento no demora la respuesta. Un fallo de envío se registra y no rompe el registro; el usuario puede reenviar.
- El dominio remitente necesita SPF, DKIM y DMARC configurados, o los correos terminan en spam. Se documenta en `docs/DESPLIEGUE.md` cuando se elija el proveedor.

### 5.6 Rate limit

Se extiende a `register`, `forgot-password`, `resend-verification`, `reset-password` y `change-email`. El limitador actual es en memoria por proceso: sirve mientras la API corra con un solo worker. Si se pasa a varios workers o réplicas, se mueve a una tabla de Postgres (no se agrega Redis solo para esto). Queda anotado en el código.

### 5.7 Páginas nuevas del frontend

`/verificar-correo`, `/olvide-contrasena`, `/restablecer-contrasena`, `/cuenta`. El registro suma los consentimientos de §6.3.

### 5.7.1 Cómo quedó construido (2026-10-06)

Decisiones de implementación que este documento no fijaba, confirmadas por el usuario el 2026-10-06.

- **Confirmar un cambio de correo usa el mismo endpoint y la misma página** que verificar la cuenta: `POST /auth/verify-email` acepta tokens `verify_email` y `change_email`, y el enlace apunta a `/verificar-correo` en los dos casos. No hay un endpoint aparte.
- **Sin dominio, el correo no se envía**: `EMAIL_BACKEND` vale `console` por defecto y la API imprime el correo en su log. Las cuentas entran sin confirmar; el aviso "Confirma tu correo" no bloquea nada.
- **Política de contraseñas**: 10 caracteres mínimo, máximo 200, se rechazan las de una lista local (`backend/app/core/common_passwords.txt`), las de un solo carácter repetido, las escaleras (`abcdefghij`) y la que es igual al correo. Aplica a contraseñas nuevas; el login no la revisa, para no dejar fuera a las cuentas anteriores. La lista tiene unas 9.170 entradas: las de 10 caracteres o más de la lista pública de las 100.000 contraseñas más usadas (SecLists, licencia MIT; la fuente y la fecha están en el encabezado del archivo) más una lista propia en español. Se actualiza reemplazando el archivo, sin tocar código.
- **`forgot-password` responde igual y con el mismo código**, exista o no el correo, y el envío va en segundo plano. Queda una diferencia de tiempo de una escritura en la base (emitir el token) entre los dos casos y **se decidió no igualarla**: el registro ya revela si un correo tiene cuenta ("Ya existe una cuenta con ese correo"), así que igualar el tiempo aquí no protegería nada. Ocultar de verdad quién tiene cuenta pediría cambiar el registro, y eso es una decisión de producto que no se ha tomado.
- **Eliminar la cuenta** (`DELETE /auth/me {password}`, adelantado del paso 5 por decisión del usuario: la política de datos promete la supresión). Borra el usuario y, por `ON DELETE CASCADE`, sus mesas, números, apuestas, recomendaciones y tokens; envía un correo de aviso. El único administrador no puede eliminarse (`409`). **Falta para el paso 5**: cancelar la renovación antes de borrar y conservar los pagos anonimizados. `payment_events` y `subscriptions` hoy se borran en cascada con el usuario; ese `ON DELETE` hay que cambiarlo cuando esas tablas tengan datos.
- **Sesiones al desplegar**: un JWT sin el claim `ver` se lee como versión 0, que es con la que arrancan todas las cuentas. Desplegar el paso 1 no cierra la sesión de nadie.
- **`change-password` devuelve tokens nuevos** para que la sesión que hizo el cambio siga abierta; todas las demás se cierran. Una contraseña actual incorrecta responde `400`, no `401`: el cliente trata un `401` como sesión vencida.
- **Límites** (por ventana, en memoria): `register` 10 por hora y 20 por día por IP; `verify-email` 20 cada 15 min por IP; `resend-verification` 1 por minuto, 3 cada 15 min y 10 por día por usuario (el minuto de espera y el tope diario se agregaron el 2026-10-07: 3 cada 15 min eran 288 correos al día desde una sola cuenta, más que la cuota diaria del proveedor; el botón muestra la espera); `forgot-password` 10 cada 15 min por IP, y 3 cada 15 min y 10 por día por correo; `reset-password` 10 cada 15 min por IP; `change-password` 10 cada 15 min por usuario; `change-email` 5 por hora y 10 por día por usuario (los topes diarios de `forgot-password` y `change-email` son del 2026-10-07, por la misma razón que el del reenvío); `DELETE /auth/me` 10 cada 15 min por usuario.
- **Login**: además del límite por IP y correo (5 fallos en 5 min), 30 fallos en 15 min por IP sin importar el correo. El primero no frenaba probar pocas contraseñas contra muchos correos. Un login correcto no borra la cuenta de fallos de la IP.
- **Tope diario de correos** (`EMAIL_DAILY_LIMIT`, 300 por defecto, no estaba en §12): al llegar, la API deja de enviar hasta el día siguiente (UTC) y lo registra como error, que llega al monitoreo. Existe porque el registro envía un correo a cualquier dirección que se escriba: sin tope, la plataforma serviría para mandar correo a terceros y gastar la cuota del proveedor. Debe quedar por debajo del límite diario del plan de Resend. En memoria: un reinicio lo pone en cero.
- **Límite de intentos en la cotización con cupón**, para que no se puedan adivinar códigos: hecho en el paso 4 (§3.11).
- **Variable `RATE_LIMIT_ENABLED`** (no estaba en §12): apaga los límites por endpoint. Existe solo para los tests de punta a punta, donde todas las peticiones salen de la misma IP. Los límites de login no la miran.
- **De §5.4 queda para después**: `GET /auth/me/export` (paso 2, con el resto de derechos del titular de §6.4) y las secciones de `/cuenta` de suscripción, método de pago, historial de pagos y documentos aceptados. `/cuenta` trae hoy perfil, correo, contraseña y eliminar cuenta.
- **De §5.8 queda para el paso 5**: "cuenta sin verificar → no puede crear suscripción", porque `POST /billing/subscriptions` todavía no existe.
- **`FileEmailSender`** no rechaza todavía el arranque con llaves de producción de Wompi: esas variables llegan en el paso 5. Queda anotado en `core/email.py`.

### 5.8 Tests de aceptación

- Token de verificación usado dos veces → el segundo uso se rechaza.
- Token vencido → rechazado.
- `forgot-password` con correo inexistente → misma respuesta que con uno existente, y ningún correo enviado.
- Tras restablecer la contraseña, el refresh token anterior → `401`.
- En la base nunca aparece un token en claro.
- Cuenta sin verificar → no puede crear suscripción.

---

## 6. Términos, condiciones y políticas

### 6.1 Documentos

| Documento | Ruta pública | Notas |
|---|---|---|
| Términos y Condiciones | `/legal/terminos` | Contrato de uso y de suscripción. |
| Política de Tratamiento de Datos Personales | `/legal/privacidad` | Ley 1581 de 2012 y Decreto 1377 de 2013 (Colombia): finalidades, derechos del titular, canal de consultas y reclamos, responsable del tratamiento. |
| ~~Juego Responsable~~ | ~~`/legal/juego-responsable`~~ | **Descartado por el usuario el 2026-10-08**: no se construye. |
| Cancelación y Reembolsos | `/legal/reembolsos` | Cómo cancelar, qué pasa con el período pagado, reembolsos. Revisar con abogado el derecho de retracto del Estatuto del Consumidor (Ley 1480 de 2011) en ventas a distancia. |
| Cookies y almacenamiento local | `/legal/cookies` | Hoy la sesión vive en `localStorage` y no hay analítica de terceros; el documento lo dice así. Si se agrega analítica, se actualiza. |
| Aviso sobre la naturaleza del servicio | dentro de T&C | Ver §6.5. |

### 6.2 Versionado

```sql
legal_documents (
  id, kind,                -- 'terms' | 'privacy' | 'refunds' | 'cookies'
  version,                 -- entero creciente por kind
  title, content_md,
  requires_acceptance,     -- terms y privacy: true
  published_at,            -- null = borrador
  created_by, created_at,
  UNIQUE (kind, version)
)

user_consents (
  id, user_id, legal_document_id,
  accepted_at, ip, user_agent
)
```

- El texto se edita desde `/admin/legal` como Markdown. Una versión publicada **no se edita**: se publica una nueva. Así cada aceptación apunta al texto exacto que el usuario vio.
- Las páginas públicas muestran la última versión publicada, con su fecha y versión.
- El Markdown se renderiza en el frontend sin permitir HTML crudo.

### 6.3 Aceptación

- **Registro**: casillas obligatorias para T&C y Tratamiento de Datos (con enlace a cada uno) y declaración de **mayoría de edad (18+)**. El backend rechaza el registro si faltan; guarda un `user_consent` por documento y `users.adult_confirmed_at`.
- **Onboarding scroll-to-accept** (§0 del doc de arquitectura): la primera vez que el usuario entra a la mesa, una pantalla explica qué hace y qué no hace la plataforma, y el botón de continuar se habilita al llegar al final.
- **Versión nueva** de un documento con `requires_acceptance`: el siguiente acceso a la mesa devuelve `403 consent_required` (§2.2) y el frontend muestra el documento para aceptarlo. No se bloquea el acceso a `/cuenta` ni a cancelar la suscripción.
- **Checkout**: además se muestran los términos de Wompi con su acceptance token (§3.4); esa aceptación la registra Wompi, no reemplaza la nuestra.

### 6.4 Derechos del titular de datos

- Consultar sus datos: la página `/cuenta` y un `GET /auth/me/export` que devuelve un JSON con su cuenta, mesas, giros, apuestas, consentimientos y pagos.
- Rectificar: edición de nombre y correo (§5.4).
- Suprimir: `DELETE /auth/me` (§5.4).
- Canal de reclamos: correo de contacto publicado en la política.

### 6.5 Contenido mínimo que deben cubrir los textos

El texto final lo redacta o revisa un abogado. Lo que el producto necesita que digan, en línea con la regla no predictiva:

- La plataforma ofrece **análisis estadístico y recomendaciones generadas por reglas** sobre resultados que el usuario registra. **No es una predicción** y no garantiza ningún resultado.
- El Signal Score es la fuerza del criterio interno, **no la probabilidad de acertar**.
- Cada giro es independiente; ninguna gestión de banca (plana, martingala, dos sectores) cambia la ventaja de la casa.
- Sebasanálisis **no es un operador de juegos de suerte y azar**: no recibe apuestas ni paga premios. El usuario juega por su cuenta en operadores autorizados.
- Servicio solo para mayores de edad.
- El usuario es responsable de los números que ingresa.
- Condiciones de la suscripción: renovación automática, cómo cancelarla, qué pasa con el período en curso.

### 6.6 Presencia en la interfaz

- Pie de página con enlaces a todos los documentos en **todas** las pantallas, incluidas login y registro.
- La línea fija de la tarjeta de recomendación (§2.10 del doc de arquitectura) se mantiene tal cual.

### 6.7 Cómo quedó construido (2026-10-08)

Decisiones de implementación que este documento no fijaba, confirmadas por el usuario el 2026-10-08.

- **No hay página de Juego Responsable.** El usuario la descartó: los documentos son cuatro (`terms`, `privacy`, `refunds`, `cookies`). El documento de arquitectura la exigía en §0 y quedó anotado allá.
- **Los textos publicados son borradores.** La versión 1 de los cuatro la inserta una migración de datos, ya publicada, porque el registro exige aceptar los términos y la política de datos: sin una versión publicada nadie podría crear una cuenta tras desplegar. Cada uno abre con un aviso de que es un borrador pendiente de abogado, y marca con `[PENDIENTE]` o `[PENDIENTE DE ABOGADO]` lo que falta: los datos del responsable y prestador (nombre, identificación, domicilio), el derecho de retracto y la política de reembolsos (Ley 1480), la transferencia internacional de datos, los plazos de conservación y el procedimiento de reclamos (Ley 1581), la limitación de responsabilidad y la jurisdicción. El texto del abogado se publica desde `/admin/legal` como versión 2 con "exigir aceptación", y eso se lo pide a todas las cuentas.
- **El texto de la versión 1 vive con la migración** (`backend/app/db/migrations/data/legal_v1/*.md`) y no se edita: un cambio de texto es una versión nueva.
- **Cuentas anteriores a este paso**: no se les crean consentimientos por migración, porque sería registrar una aceptación que no ocurrió. `adult_confirmed_at` queda en null y no tienen filas en `user_consents`; la próxima vez que entran a la mesa ven la pantalla de aceptación con los dos documentos y la casilla de mayoría de edad. Mientras tanto conservan el login, `/cuenta`, la exportación y eliminar la cuenta. Aplica también a los administradores, incluido el que crea el seed.
- **`core/access.py` nace aquí, con una sola regla.** §6.3 pide que una versión nueva responda `403 consent_required` "desde el control de acceso de §2.2", que es del paso 3. Para no escribir esa regla fuera de `core/access.py`, `has_access` y la dependencia `RequireAccess` se crearon en este paso con la regla n.º 2 de §2.2 y nada más: una cuenta al día con sus consentimientos usa la mesa como antes (motivo `open`). `RequireAccess` ya está en los seis routers de juego y el test que recorre todas las rutas de juego (§2.4) ya existe. **El paso 3 agrega las demás reglas dentro de `has_access`**, en el orden de §2.2, y reemplaza `open`. La firma es `has_access(db, user, now)`: recibe la sesión de base porque los consentimientos se consultan; `game` se suma en el paso 7.
- **El `403` lleva el motivo en `detail.code`** (`{"code": "consent_required", "message": …}`); `ApiError.code` lo expone en el frontend.
- **Qué significa "al día"**: una cuenta está al día con un documento si aceptó una versión igual o posterior a la última publicada con `requires_acceptance`. Por eso `requires_acceptance` se decide por versión: una versión nueva que no la exige (corregir una errata) no le pide nada a nadie. El registro pide la versión vigente de cada documento que alguna vez la exigió (hoy, términos y datos).
- **La aceptación apunta al texto que se vio.** El registro y `POST /legal/accept` reciben los ids de las versiones que la pantalla mostró. Si entre mostrar y aceptar se publicó otra versión, `POST /legal/accept` responde `409` y la pantalla trae la nueva. Un mismo documento no se acepta dos veces (restricción única por usuario y documento).
- **Registro**: `accepted_document_ids` y `adult_confirmed` en `POST /auth/register`. Si falta la mayoría de edad o alguno de los documentos exigidos, responde `422` con un mensaje propio, antes de mirar si el correo ya existe. Solo se guardan consentimientos de los documentos exigidos: un id de más en la petición se ignora.
- **IP y navegador**: la IP es la del cliente tras el proxy (§13.1); el user agent se recorta a 400 caracteres.
- **Un solo borrador por documento** en `/admin/legal`: con dos, el número de versión dependería de cuál se publique primero. No hay endpoint para borrar un borrador; se edita.
- **Auditoría**: al cerrar este paso, publicar un documento legal no escribía en `admin_audit_log` (§4.6) porque la tabla no existía. **Hecho en el paso 3** (2026-10-08): `POST /admin/legal-documents/:id/publish` deja su fila.
- **Onboarding**: `users.onboarding_completed_at` y `POST /auth/me/onboarding` (no estaban en §11). Es una pantalla informativa, no un consentimiento legal: se guarda en el servidor para que no reaparezca en cada dispositivo, la exige el frontend al entrar a la mesa y no participa en `has_access`. Su texto es fijo en el frontend (`components/AccessGate.tsx` desde el paso 3), no un documento versionado.
- **Compuerta del frontend** (`LegalGate`; `AccessGate` desde el paso 3): envuelve el menú principal, la mesa y el panel de admin (que lista juegos). Pregunta `GET /legal/pending` antes de montar la pantalla. Es presentación: quien decide es el servidor.
- **Markdown**: `react-markdown` 10.1.0, sin `rehype-raw` ni `remark-gfm` (los documentos se escriben sin tablas). Las imágenes se descartan. `npm audit --omit=dev` quedó sin vulnerabilidades tras instalarla.
- **Rutas públicas en español, `kind` en inglés**: `/legal/terminos`, `/legal/privacidad`, `/legal/reembolsos`, `/legal/cookies` (`frontend/lib/legal.ts`). Las páginas se renderizan en el navegador, pidiendo `GET /legal/:kind`.
- **Endpoints que no estaban en §11**: `GET /legal/required` (público: lo que el registro pide aceptar), `GET /legal/consents` (lo que la cuenta aceptó, para `/cuenta`) y `POST /auth/me/onboarding`.
- **`GET /auth/me/export`**: cuenta, mesas con sus giros y apuestas, y consentimientos. `payments` va vacío hasta el paso 5. Límite: 10 cada 15 min por usuario. No exige `RequireAccess`.
- **Eliminar la cuenta** borra en cascada sus `user_consents`. Si el abogado pide conservar la constancia de la autorización después de la supresión, hay que cambiar ese `ON DELETE`.
- **Pie de página**: en el layout raíz, así que aparece en todas las pantallas. Las pantallas dejaron de ocupar el alto completo por su cuenta (`min-h-screen`) para que el pie quede a la vista en login y registro.
- **Pendiente para el lanzamiento: aviso por correo de una versión nueva** (anotado por decisión del usuario el 2026-10-08). Publicar una versión que exige aceptación hoy **no envía correo**: cada cuenta ve la pantalla de aceptación la próxima vez que entra, y quien no entra no se entera. Con cobros activos eso deja a una cuenta con renovación automática pagando bajo términos que no ha visto. Lo que falta construir: un correo a cada cuenta al publicar, que diga qué documento cambió y enlace a su página pública, enviado por tandas para respetar `EMAIL_DAILY_LIMIT` (por eso va después de pasar Resend al plan Pro). La pantalla de aceptación se mantiene: es la que deja la constancia. A confirmar con el abogado: si el aviso es obligatorio y si debe salir con antelación a la entrada en vigor.
- **Tests de punta a punta**: el de re-aceptación corre en un proyecto aparte de Playwright (`*.serial.spec.ts`), al final: publicar una versión le pide re-aceptar a todas las cuentas de la base y en paralelo le cortaría la mesa a los demás tests. `start-api.mjs` fija las credenciales del administrador sembrado para esa base desechable.

---

## 7. Plataforma multijuego

### 7.1 Diagnóstico

El motor (`engine/`) y la configuración (`categories_json`) ya son genéricos: cualquier juego de resultados discretos con probabilidad fija se describe con `possible_outcomes` + `categories`. Lo que ata la plataforma a la ruleta está fuera del motor:

- La ruta del frontend (`/games/roulette/[sessionId]`) y la redirección en `dashboard/page.tsx`.
- Los componentes en `components/roulette/`.
- El seed, que solo conoce ruleta.
- El menú de juegos, que no tiene descripción, imagen ni orden.

### 7.2 Metadatos del juego

`games` suma:

| Campo | Uso |
|---|---|
| `slug` (único) | URL: `/juegos/ruleta`. |
| `module` | Familia de juego, que decide qué pantalla y qué motor se usan: `discrete_outcome` (ruleta, dados, y todo lo que se describa con `categories_json`) y `sports` (reservado, §8). |
| `description` | Texto del menú de juegos. |
| `icon` | Identificador del ícono o ruta de imagen. |
| `sort_order` | Orden en el menú. |
| `status` | `active` \| `hidden` \| `coming_soon` (se ve en el menú, no se puede abrir). |

`game_variants` suma `description` y `sort_order`.

### 7.3 Registro de módulos

- **Backend**: un registro `module → (router, validador de configuración)`. Hoy solo existe `discrete_outcome`, que agrupa los routers actuales. Crear un juego con un `module` sin registrar se rechaza en el admin.
- **Frontend**: un registro `module → componente de sesión`. La ruta pasa a `/juegos/[slug]/mesa/[sessionId]`; la página lee el `module` del juego y monta el componente que le corresponde. La ruta vieja `/games/roulette/[sessionId]` redirige a la nueva para no romper enlaces guardados.
- `components/roulette/*` pasa a `components/mesa/*` y deja de suponer ruleta. El teclado de resultados se arma desde `possible_outcomes`, con una pista opcional de presentación en `categories_json`:

```json
"display": {
  "outcome_tone_category": "color",
  "layout": "grid",
  "columns": 3
}
```

La pista es solo de presentación: el motor la ignora y el validador de configuración (`core/game_config_validation.py`, skill `categories-json-validator`) la acepta como opcional.

Resultado esperado: **un juego `discrete_outcome` nuevo se crea completo desde el admin, sin escribir código.**

> **Cambió el 2026-10-14 (decisión del usuario)**: el producto sale solo con la ruleta, y cada juego futuro tendrá su propio motor, escrito en código, como un módulo nuevo. El alta de juegos y de variantes del admin queda oculta, no borrada. El detalle está en §7.9.

### 7.4 Acceso por juego

- `plan_games` (§3.2) lista los juegos incluidos en un plan; sin filas, el plan incluye todos.
- `has_access(user, now, game)` lo verifica (§2.2).
- El menú de juegos muestra los no incluidos como "disponible en otro plan", con enlace a `/planes`.
- Esto es lo que permite vender, más adelante, un plan solo de apuestas deportivas o uno que lo combine con ruleta.

### 7.5 Prueba de genericidad

Una configuración de **dados** como fixture de test (no se publica ni se agrega al seed, porque el juego de dados sigue fuera de alcance): se crea por la API de admin, se abre una sesión, se cargan giros y se pide la recomendación. El test pasa sin tocar `engine/`. Si algún día falla, es que se coló lógica de ruleta fuera de los datos.

### 7.6 Tests de aceptación

- Juego creado desde el admin con un `module` registrado → aparece en el menú y se puede jugar.
- Juego con `module` no registrado → rechazado al crearlo.
- Juego no incluido en el plan del usuario → `403 game_not_in_plan`.
- `/games/roulette/:id` redirige a la ruta nueva.
- Fixture de dados de punta a punta (§7.5).

### 7.7 Entrega 1, backend y admin: cómo quedó construido (2026-10-14)

Paso 7, entrega 1 (rama `fase-4-paso-7a-multijuego-backend`). La entrega 2 (la mesa en `/juegos/[slug]/mesa/[sessionId]`, `components/mesa/*`, el menú de juegos, la redirección de la ruta vieja y el fixture de dados en Playwright) sigue pendiente.

**Decisiones del usuario (2026-10-14)**

- **Estado**: `games.active = true` pasa a `status = 'active'` y `false` a `'hidden'`.
- **Slug de la ruleta**: `ruleta`, con la URL en español (`/juegos/ruleta`). El slug no se edita después de creado, igual que el código de un plan.
- **`coming_soon`**: el cliente lo ve en el menú, pero no puede abrir mesa (`409`).
- **`hidden`**: no existe para el cliente (`404`). Un administrador lo ve y abre mesas para probarlo.
- **Mesas ya abiertas**: siguen funcionando aunque su juego pase a oculto o a "próximamente", igual que con una variante desactivada.
- **Bitácora del estado**: cambiar el estado de un juego pide motivo y deja fila (`game.status.update`). Crear un juego también la deja (`game.create`). Editar el nombre, la descripción, el ícono o el orden no la deja.
- **Ícono**: un identificador de un set fijo (`ruleta`, `dados`, `cartas`, `deportes`, `generico`) que dibuja el frontend. No hay subida de archivos.
- **Sesiones abiertas**: no se tocan. Una sesión llega a su juego por la variante, así que las de hoy ya son de ruleta.
- **`plan_games`**:
  - Un plan sin filas incluye todos los juegos, también los que se creen después.
  - El acceso manual (`full`, `invited`) y el administrador incluyen todos.
  - Agregar un juego a un plan siempre se puede.
  - **Quitar un juego a un plan con suscripciones vigentes se rechaza (`409`)**, por el mismo principio del precio congelado (§3.7). La salida es crear un plan nuevo y desactivar el viejo.
  - Pasar de "todos" a una lista que deje fuera un juego existente cuenta como quitarlo.
- **`/planes` dice qué juegos incluye un plan solo cuando el plan tiene una lista.** La respuesta pública ya lo trae; la pantalla es de la entrega 2.
- **Ninguna decisión de §10 ni de §8.3 toca este paso.** `sports` queda reservado: está en el enum y en el registro, sin implementación, y el admin rechaza crear un juego con él.

**Datos**: cinco migraciones, una por cambio lógico.

| Migración | Tipo | Qué hace |
|---|---|---|
| `a3c1e5f7b902` | DDL | Columnas nuevas de `games` y `game_variants`. Las que dependen de cada juego entran nullables. |
| `b6d2f4a8c013` | Backfill | `slug`, `module`, `icon` y `status` de cada juego. La ruleta reserva `ruleta`; los demás toman el slug de su `type`, con sufijo si chocan. |
| `c8e4a6b0d125` | DDL | Columnas obligatorias, slug único con CHECK de formato, CHECK de los enums. Retira `games.active`; el downgrade la recrea desde `status`. |
| `d0f6b8c2e237` | DDL | `plan_games`. No hay backfill: los dos planes de hoy quedan sin filas e incluyen todo. |
| `e2a8c0d4f349` | Backfill | Agrega `display` al `categories_json` de las variantes de ruleta. |

**Registro de módulos** (`backend/app/api/game_modules.py`)

- `module → (routers, validador de configuración)`. `discrete_outcome` agrupa los cinco routers de la mesa y usa `validate_game_config`; `sports` figura sin implementación.
- `main.py` monta los routers desde el registro.
- Un `assert` exige que el registro y el enum de `games.module` coincidan.
- Crear un juego con un módulo reservado o desconocido responde `422`.

**Acceso por juego (regla n.º 7 de §2.2)**

- `has_access(db, user, now, game=None)`: con un juego y una suscripción vigente, exige que el plan lo incluya; si no, `game_not_in_plan`. Los demás orígenes de acceso no miran el juego.
- `RequireAccess` sigue en los routers sin el juego. A su lado, **`RequireGameAccess`**, también a nivel de router en los cinco routers de la mesa, lee el `{session_id}` de la URL y vuelve a preguntar a `has_access` con el juego de esa mesa.
  - Va como dependencia y no dentro del endpoint porque así corre antes de validar el cuerpo: una mesa de un juego fuera del plan responde `403 game_not_in_plan` en todas sus rutas, también en los `POST`.
  - Un endpoint nuevo sobre una mesa no puede olvidarlo.
- Abrir una mesa (`POST /sessions`) pasa por la misma pregunta, después de mirar el estado del juego.
- `GET /auth/me` sigue decidiendo sin juego: una cuenta con suscripción tiene acceso aunque su plan no incluya todos los juegos.
- `core/access.current_subscriptions_of_plan` cuenta las suscripciones que dan acceso hoy con los mismos estados de la regla n.º 6. La usa el admin para el `409` de quitar un juego.

**Pista de presentación `display`** (`OutcomeDisplay` en `schemas/games.py`)

- `outcome_tone_category`: la categoría cuyos grupos dan el tono a cada resultado.
- `tones`: grupo → `red | black | green | neutral`.
- `layout`: `grid`.
- `columns`: opcional, de 1 a 12.

El motor la ignora. El validador rechaza una categoría o un grupo que no existe, y tonos sin categoría. Antes de este paso Pydantic descartaba en silencio una clave `display`; ahora se guarda. Las configuraciones de ruleta de `seed_data/` la traen.

**API**

| Endpoint | Qué cambia |
|---|---|
| `GET /games` | Es el menú de juegos: paginado, en el orden del menú, con las variantes activas y `access: {granted, reason}` por juego. El cliente ve `active` y `coming_soon`; el administrador ve también `hidden`. Desaparece `include_inactive`. |
| `GET /admin/games` | Nuevo. Paginado y con filtros por estado, módulo y texto (nombre o slug). Trae todas las variantes. |
| `POST /admin/games` | Pide `slug`, `module` y `reason`. Acepta `description`, `icon`, `sort_order` y `status` (por defecto `hidden`). |
| `PATCH /admin/games/:id` | Cambia nombre, descripción, ícono, orden y estado. El estado pide motivo. Un cambio que no cambia nada da `409`. |
| Variantes | Suman `description` y `sort_order`. La configuración se valida con el validador del módulo del juego. |
| `PUT /admin/plans/:id/games` | Nuevo: `{game_ids, reason}`. Una lista vacía significa todos los juegos. Deja fila `plan.games.update`. |
| `PlanResponse` | Suma `all_games` y `games` (sin los ocultos). |
| `AdminPlanResponse` | Suma `game_ids` (todos, también los ocultos). |

**Frontend del admin**

- `/admin/juegos`:
  - Lista paginada con filtro por estado y búsqueda.
  - Alta con nombre, tipo, slug, módulo, ícono, orden, descripción y motivo; el juego nace oculto.
  - Edición del juego, con el motivo cuando cambia el estado.
  - `VariantForm` suma descripción, orden y la pista del teclado.
  - `/admin/juegos` y `/admin/motor` ya no pasan por `AccessGate`: leen `/admin/games`, que no es un endpoint de juego.
- `/admin/planes`: debajo de cada plan, "Juegos incluidos" (todos, o una lista con motivo), y en la fila "todos los juegos" o cuántos.
- El dashboard lee el menú nuevo y, hasta la entrega 2, solo ofrece abrir mesa en los juegos activos que la cuenta puede jugar.

**Tests**

- `tests/api/test_multijuego.py`, 28 tests:
  - El fixture de dados (`tests/fixtures/dados_d6.json`) pasa el validador sin errores ni avisos, y funciona de punta a punta por la API sin tocar `engine/`. Es un dado de seis caras: el motor supone resultados equiprobables y las sumas de dos dados no lo son.
  - Módulo reservado o desconocido → `422`.
  - Slug inválido → `422`; slug repetido → `409`; el slug no se edita.
  - Juego nuevo oculto, con su fila en la bitácora.
  - El estado pide motivo y deja fila.
  - Menú y apertura de mesa según el estado, para cliente y administrador.
  - Mesa abierta de un juego que se oculta.
  - Paginación y filtros de `/admin/games`.
  - Cinco pistas mal formadas rechazadas; la pista es opcional; la ruleta sembrada la trae.
  - Plan sin juegos = todos, también los nuevos.
  - `403 game_not_in_plan` al abrir mesa, y el menú lo marca.
  - El acceso manual y el administrador incluyen todo.
  - **Recorrido de todas las rutas con `{session_id}`** con una mesa de un juego fuera del plan: `403 game_not_in_plan` en cada una (20 operaciones).
  - Juegos por plan: motivo, `409` al quitar con vigentes, de "todos" a lista; solo administradores; los planes públicos no nombran los juegos ocultos.
- Los tests que creaban juegos con `{name, type, active}` usan el helper `game_body` de `tests/api/conftest.py`.
- Playwright:
  - `e2e/admin-games.spec.ts`: crear un juego oculto y pasarlo a "próximamente" con motivo; elegir los juegos de un plan y verlo en la bitácora.
  - `admin-panel.spec.ts` ahora recorre también Juegos y Motor.
- Migraciones probadas en una base desechable:
  - Con tres juegos, uno de ellos con `type = 'ruleta'` para forzar el choque de slug.
  - Subida, CHECK del slug, bajada de las cinco con una fila en `plan_games` y `active` restaurado, vuelta a subir y `alembic check` sin diferencias.

**Lo que quedó para la entrega 2** (construida, §7.8): la ruta `/juegos/[slug]/mesa/[sessionId]` y la redirección de `/games/roulette/:id`, `components/mesa/*`, el teclado armado desde `possible_outcomes` con la pista `display` (hoy `lib/outcomes.ts` todavía busca la categoría `color`), el menú con "Próximamente" y "Disponible en otro plan", la pantalla de `game_not_in_plan`, los juegos incluidos en `/planes` y el fixture de dados en Playwright.

### 7.8 Entrega 2, la mesa y el menú: cómo quedó construido (2026-10-14)

Paso 7, entrega 2 (rama `fase-4-paso-7b-mesa-y-menu`). Con ella está construido todo el paso 7. Las decisiones son las de §7.7, que el usuario confirmó el 2026-10-14.

**Rutas**

| Ruta | Qué hace |
|---|---|
| `/juegos/[slug]/mesa/[sessionId]` | La mesa. `MesaScreen` pide la sesión, monta la pantalla del módulo de su juego y, si el slug de la URL no es el de su juego, lleva al correcto. Si el servidor responde `403 game_not_in_plan`, dice que el juego no está incluido en el plan, con "Ver planes". |
| `/juegos/[slug]` | La página del juego (`GamePage`): sus variantes y el formulario de mesa nueva, que antes estaban en el dashboard. Juego oculto o inexistente: "Este juego no está disponible". "Próximamente" (para un cliente): lo dice, sin mesa. Fuera del plan: "Este juego no está incluido en tu plan" con "Ver planes". |
| `/juegos` | Lleva al inicio, donde vive el menú. |
| `/games/roulette/:id` | Redirección permanente (308) a `/juegos/ruleta/mesa/:id`, en `next.config.ts`. Todos los enlaces viejos son de ruleta, así que no consulta nada. |

**Registro de módulos del frontend** (`lib/game-modules.ts`): `module → pantalla de la mesa`. `discrete_outcome` la juega `components/mesa/DiscreteOutcomeSession.tsx` (la vista que antes era `RouletteSession`); `sports` no tiene pantalla.

**`components/roulette/*` pasó a `components/mesa/*`** y dejó de suponer ruleta:

- El teclado se arma desde `possible_outcomes`. El tono de cada resultado sale de la pista `display` (`lib/outcomes.toneOf`) y las columnas de `display.columns`; sin pista, todo va en neutro y la grilla se ajusta al ancho. Ya no se busca la categoría `color`.
- La tarjeta de una variante muestra su descripción (o "N resultados posibles") y, como fichas, los resultados que la pista pinta de verde: los ceros de la ruleta.
- El ejemplo de la carga inicial sale de los resultados de la variante, y el campo tiene su nombre accesible (la etiqueta también envuelve el botón de ayuda y lo perdía).
- La tarjeta de recomendación conserva sus dos líneas obligatorias en la ruta nueva; lo comprueban los Playwright de la ruleta y del dado.

**El inicio** (`/dashboard`): las mesas abiertas y cerradas enlazan a `/juegos/<slug>/mesa/<id>`. La sección de mesa nueva pasó a ser **"Elige un juego"** (`components/GameMenu.tsx`), una tarjeta por juego con su ícono y su descripción:

- con acceso, "Jugar <juego>" lleva a su página;
- "Próximamente" se ve sin enlace (un administrador sí entra, para probarlo);
- fuera del plan: "Disponible en otro plan." con "Ver planes";
- oculto: solo le llega a un administrador, marcado "Oculto".

**Íconos** (`components/GameIcon.tsx`): SVG del set fijo (ruleta, dados, cartas, deportes, genérico).

**`/planes`**: un plan con lista de juegos dice "Incluye: …". Un plan que incluye todos no dice nada.

**Backend**

- `SessionResponse` suma `game_slug` y `game_module`, para armar la URL de cada mesa y elegir su pantalla.
- Los tres `Literal` del juego pasaron a `schemas/game_types.py`, para que la sesión los use sin una importación circular.
- Migración de datos `f4b0d2e6a571`: la descripción de la ruleta y de sus dos variantes, y el orden de las variantes (europea primero), donde estaban vacíos. El seed las pone al crear la ruleta, pero en el VPS la ruleta ya existía y el seed no corre al desplegar: sin esto, su tarjeta saldría sin descripción. No pisa lo que haya escrito un administrador.

**Tests**

- Backend: `test_multijuego.py` suma el de `game_slug` y `game_module` en la sesión y en la lista.
- Playwright, `e2e/multijuego.spec.ts`:
  - la ruta vieja redirige a la nueva, y un slug equivocado lleva al correcto;
  - un juego de dados creado por la API de admin con el fixture `dados_d6.json` aparece en el menú, abre mesa con carga inicial, el teclado tiene seis botones en seis columnas, se registra un giro, y la tarjeta muestra la recomendación con su línea fija;
  - un juego "próximamente" se ve sin enlace y su página no abre mesa;
  - una cuenta suscrita a un plan que solo incluye el dado: `/planes` dice qué incluye, en el menú la ruleta sale "Disponible en otro plan" y su página no ofrece mesa.
- Los Playwright de la mesa (`smoke.spec.ts` y el onboarding de `legal.spec.ts`) entran por el menú y esperan la ruta nueva.
- La migración se subió, se bajó y se volvió a subir en una base desechable, con un texto de administrador que no se pisa; `alembic check` sin diferencias.
- Se revisaron capturas del menú, la página del juego y la mesa del dado en escritorio y a 390 px, sin desplazamiento horizontal.

**Lo que queda señalado**

- El aviso fijo "La ruleta no tiene memoria…" (`components/Disclaimer.tsx`) seguía en el dashboard, aunque `CLAUDE.md` lo da por retirado de todas las pantallas. Se quitó en esta entrega (decisión del usuario del 2026-10-14) y el componente se borró. La misma frase también se quitó del pie del login y del registro (`AuthForm.tsx`) y de la descripción de la página (`app/layout.tsx`). Quedan las explicaciones de contexto que no son el aviso: la nota bajo las mesas cerradas, el onboarding y el resumen de una sesión cerrada.
- La skill `categories-json-validator` ponía de ejemplo de juego nuevo la suma de dos dados (2-12), que no son resultados equiprobables. Se corrigió: ahora exige resultados equiprobables y explica cómo describir dos dados (36 pares ordenados).
- Los textos de ayuda de la gestión de banca siguen dando ejemplos de ruleta ("dos docenas o dos columnas"), ahora marcados como tales.

### 7.9 Solo la ruleta por ahora; los juegos futuros, en código (2026-10-14)

**Decisión del usuario.** El producto sale solo con la ruleta. Cada juego que venga después tendrá su propio motor, escrito en código como el de la ruleta. Reemplaza el "resultado esperado" de §7.3: un juego nuevo ya no se crea desde el admin.

**Por qué.** Al revisar si el formulario de variantes servía para otros juegos salieron tres límites que la configuración sola no resuelve bien:

- **Resultados equiprobables.** El motor calcula la probabilidad de un grupo como resultados del grupo ÷ resultados posibles, así que cada resultado tiene que valer lo mismo y cada ronda ser independiente. Ningún validador lo puede comprobar.
  - Un dado de seis caras cabe. Dos dados caben solo como 36 pares, no como sumas 2-12.
  - Una carta de una baraja completa y rebarajada cabe. Baccarat y Dragon Tiger no: sus resultados no valen lo mismo, y haría falta un peso por resultado en el motor. Una baraja que se gasta sin rebarajar tampoco cabe.
- **Las progresiones están pensadas para los pagos de la ruleta.** La martingala recupera la serie con pago 1:1, y la de dos sectores con dos zonas que pagan 2:1. Con otros pagos la mesa muestra montos honestos (calcula con el pago real), pero la serie puede cerrar en pérdida aunque se acierte. Con un pago de 0,9:1, la martingala queda en −600 si se acierta en el escalón 4. Con dos zonas a 1,85:1, la de dos sectores queda en −300 si se acierta en el escalón 1.
- **El formulario no estaba listo para otro juego.**
  - El pago solo aceptaba múltiplos de 0,5.
  - Las combinaciones (dos docenas) no se podían crear.
  - Los ejemplos eran de ruleta.

**Qué se hizo** (rama `fase-4-solo-ruleta`):

- En `/admin/juegos` se ocultan "Nuevo juego" y "+ Variante", con el interruptor `ALTA_DE_JUEGOS` de `app/admin/juegos/page.tsx`. No se borran: una versión futura puede volver a encenderlo.
- Siguen a la vista la edición de las variantes de la ruleta (umbrales de señal) y el estado, el orden, el ícono y la descripción del juego.
- La API de alta (`POST /admin/games` y `POST /admin/games/:id/variants`) se conserva. La usan los tests y el fixture de dados de Playwright.
- No se tocó nada más. La infraestructura del paso 7 es la base para un juego escrito en código: el menú, los slugs, `plan_games`, el acceso por juego y los registros de módulos del backend y del frontend. Se agrega como un módulo nuevo, con sus rutas, su motor y su pantalla, igual que está previsto para deportes (§8).
- El fixture de dados se queda como test: vigila que el motor de la ruleta siga sin lógica de ruleta fuera de los datos.
- **La martingala se deja como está** (decisión del usuario). Se sigue ofreciendo también cuando la recomendación es una sola docena o columna (2:1), con el monto calculado con el pago real, aunque el documento verificado dice que la martingala clásica aplica tal cual solo a pagos 1:1.

**Tests**: el Playwright del admin comprueba que "Crear juego" y "+ Variante" no aparecen, y que las variantes de la ruleta se siguen editando. El juego de prueba del test de estado se crea por la API.

**Paso 7 cerrado el 2026-10-14**: el usuario lo desplegó y lo probó en el VPS con la ruleta (menú, mesa en la ruta nueva, redirección de la ruta vieja, mesas ya abiertas, `/admin/juegos` y los juegos incluidos de los planes).

---

## 8. Base para apuestas deportivas

**No se construye en esta fase.** Esta sección deja claro por qué necesita su propio módulo, qué queda preparado y qué hay que decidir antes de diseñarlo.

### 8.1 Por qué no cabe en `discrete_outcome`

| Ruleta / dados | Apuestas deportivas |
|---|---|
| Probabilidades fijas y conocidas (salen de `categories_json`). | No hay probabilidad teórica: hay **cuotas** de las casas, que cambian en el tiempo e incluyen el margen del operador. |
| Eventos idénticos e independientes. | Cada partido es distinto; el contexto (equipos, lesiones, localía) importa. |
| El usuario registra el resultado de la mesa. | Calendario de eventos, mercados y resultados vienen de una **fuente de datos externa**. |
| Un giro se resuelve en segundos. | Un evento se resuelve horas o días después; puede suspenderse o anularse. |
| El motor compara frecuencia observada con probabilidad teórica. | El análisis tendría que comparar la probabilidad implícita en las cuotas (sin margen) con alguna estimación propia. Es otro motor, con otros supuestos. |

Forzarlo dentro de `categories_json` rompería la regla de que el motor es genérico sobre resultados discretos con probabilidad fija.

### 8.2 Qué queda preparado en esta fase

- `games.module = 'sports'` reservado en el enum y en los registros de módulos (§7.3), sin implementación.
- Espacios de nombres reservados: `/deportes` en el frontend, `/sports` en la API, `backend/app/engine/sports/` para su motor (también puro y testeable). **Reservados solo en este documento** (decidido el 2026-10-15, §8.4): no se crean carpetas ni rutas vacías. El módulo ya está reservado donde hace efecto: el enum de `games.module`, los registros `api/game_modules.py` y `lib/game-modules.ts`, y el admin, que rechaza crear un juego con él.
- Acceso por juego y por plan (§7.4), para venderlo como plan aparte o combinado.
- Las tablas de suscripción, planes y cupones no dependen del tipo de juego.

### 8.3 Preguntas abiertas antes de diseñarlo

1. **Fuente de datos**: qué proveedor de calendario, cuotas y resultados se usa, su costo mensual, sus límites de uso y sus condiciones de licencia (¿permite mostrar sus cuotas a clientes de pago?).
2. **Alcance inicial**: qué deportes, ligas y mercados (resultado final, más/menos goles, ambos marcan, hándicap…).
3. **Ingreso**: ¿todo automático desde el proveedor, o el usuario registra cuotas como hoy registra giros? La regla de "sin IA" se mantiene en cualquier caso.
4. **Qué significa una recomendación** en deportes y cómo se mide: el backtest de §2.10 tendría su equivalente con resultados históricos que el motor no haya visto.
5. **Lenguaje**: la regla no predictiva aplica igual. Hace falta extender la tabla de terminología de §0 con los términos propios de deportes antes de escribir copy.
6. **Marco regulatorio**: confirmar con abogado que ofrecer análisis deportivo por suscripción no requiere autorización de Coljuegos, y qué avisos exige.
7. **Gestión de banca**: si las progresiones actuales aplican, o se necesita otra (por ejemplo, stake fijo o proporcional), y con qué advertencias.

### 8.4 Cómo quedó decidido (2026-10-15)

Respuestas del usuario a §8.3, en el paso 8. **Deportes no se construye en esta fase.** Lo que sigue es lo que hay que respetar el día que se construya, como un módulo nuevo con su propio motor escrito en código (§7.9).

| # | Pregunta | Decisión |
|---|---|---|
| 1 | Fuente de datos | **Pendiente** (§10 n.º 13). Propuesta por defecto: no se elige proveedor hasta que se vaya a construir. El requisito es su confirmación por escrito de que la licencia permite el uso comercial en un producto de pago. Precio, límites de uso y condiciones se leen de sus términos vigentes, no de memoria. Sus cuotas sirven solo para el backtest interno y no se muestran al cliente, salvo que la licencia lo permita expresamente. |
| 2 | Alcance inicial | **Pequeño**: fútbol, un solo mercado (resultado final: local, empate o visitante) y pocas ligas. Las ligas concretas se eligen junto con el proveedor; la propuesta es la Liga BetPlay y una o dos ligas europeas. Más o menos goles, ambos marcan y hándicap quedan para después, y cada mercado nuevo se mide por separado. |
| 3 | Ingreso | **Mixto.** Calendario y resultados llegan automáticos desde el proveedor: un resultado mal escrito contaminaría la medición. La cuota la escribe el usuario, la de la casa donde apuesta, como hoy escribe los giros. Sin IA, sin OCR y sin lectura de pantallazos. |
| 4 | Qué es una recomendación y cómo se mide | El motor compara la probabilidad implícita en la cuota, sin el margen de la casa, con una estimación estadística propia hecha a partir de resultados anteriores. "Apostar: …" sale solo cuando la cuota que escribió el usuario paga más de lo que justifica esa estimación; si no, "No apostar este partido". Se mide con un backtest sobre temporadas que el modelo no vio: número de recomendaciones, resultado neto a la cuota tomada y caída máxima, contra la línea base del propio mercado (la cuota de cierre sin margen). **Deportes sale solo si ese backtest supera al mercado.** Si el resultado neto queda en el margen de la casa, que es lo esperable, no sale. El backtest necesita cuotas históricas, así que depende de la n.º 1. |
| 5 | Lenguaje | Los términos de deportes están en la tabla de §0 de `ARQUITECTURA_Y_ESTADISTICA.md`. **"Pronóstico" se permite en deportes** (decisión del usuario, tomada sabiendo que choca con la regla de lenguaje no predictivo). El alcance de esa excepción está abajo. |
| 6 | Marco regulatorio | **Pendiente del abogado** (§10 n.º 14). Propuesta por defecto: mientras no haya concepto escrito se supone que podría requerir autorización de Coljuegos o tener restricciones de publicidad, y deportes no sale sin ese concepto. |
| 7 | Gestión de banca | **Apuesta fija y proporcional** (un porcentaje fijo de la banca). En deportes no se ofrecen la martingala ni la de dos sectores: con una cuota distinta en cada partido la serie no tiene sentido y el riesgo de ruina crece. Tampoco el criterio de Kelly, que supone una ventaja que no se puede afirmar. Se conservan el límite de pérdida y el estado de parar de la ruleta, con la advertencia de que ninguna gestión cambia el margen de la casa. |

**Alcance de la excepción de "pronóstico"**

- Solo en el texto visible del módulo de deportes. En la ruleta sigue prohibida, igual que "predicción".
- Nunca acompañada de palabras de certeza: "pronóstico seguro", "pronóstico fijo" o "pronóstico garantizado" siguen prohibidos.
- Los nombres en código no cambian: `recommendation`, nunca `prediction` ni `forecast`. Es la lectura más conservadora de la decisión; si el usuario quiere otra, se cambia aquí y en `CLAUDE.md`.
- **Queda abierto para cuando se diseñe la tarjeta de deportes**: la línea fija de la tarjeta de la ruleta dice "No es una predicción". La de deportes se redacta entonces, y no puede llamar "pronóstico" a lo mismo que dice que no es una predicción.
- El abogado de la n.º 6 revisa también esta palabra, junto con los avisos.

**Lo que tiene que estar antes de empezar a construir deportes**

1. Proveedor elegido, con la licencia confirmada por escrito (n.º 1).
2. Concepto escrito del abogado (n.º 6).
3. El backtest fuera de muestra, y que supere al mercado (n.º 4). Es la condición para que salga, no para empezar: el backtest es lo primero que se construye.

**Qué no se hizo en el paso 8, a propósito**: no se crearon `backend/app/engine/sports/`, el prefijo `/sports` de la API ni la ruta `/deportes`. Una carpeta o una ruta vacía no reserva nada que el enum y los registros de módulos no reserven ya, y una pantalla que no hace nada sería una promesa en la interfaz.

---

## 9. Orden de construcción

Como en `CLAUDE.md`: no se avanza a un paso sin que el anterior tenga tests o una verificación manual funcionando. El orden pone primero lo que bloquea cobrar.

| # | Paso | Por qué en este lugar | Hecho cuando |
|---|---|---|---|
| 0 | **Preparación del stack** (§13) | Hay vulnerabilidades críticas abiertas en el frontend y no hay CI; las dos cosas se cierran antes de escribir código que maneja dinero. | Lista "Fase 0 hecha cuando" de §13.5 completa. |
| 1 | **Correo + verificación + restablecimiento + `token_version`** (§5) | Sin correo no hay recibos, avisos de cobro fallido ni recuperación de cuenta, y verificar el correo es requisito para pagar. | Tests de §5.8 en verde; correo real recibido desde el SMTP elegido. |
| 2 | **Legal**: documentos versionados, consentimientos en el registro, páginas públicas, onboarding (§6). La página de Juego Responsable se descartó el 2026-10-08 | No se puede cobrar sin T&C y política de datos aceptados. | Registro sin consentimientos → rechazado; versión nueva → re-aceptación. |
| 3 | **Modelo de acceso** (`has_access`, `RequireAccess`, migraciones de `access_type`) (§2) | Sin esto el pago no compra nada. Se hace antes de Wompi para probarlo con accesos manuales. | Tests de §2.4 en verde, incluido el que recorre todos los routers. |
| 4 | **Planes y cupones**: modelo, `billing/pricing.py`, CRUD en el admin, página `/planes` (§3.2, §3.3, §4.4, §4.5) | Wompi necesita algo que cobrar. | Cotizaciones correctas en todos los casos de cupón. |
| 5 | **Wompi**: alta, webhook, reconsulta, renovación, reintentos, cancelación, cambio de tarjeta, `/cuenta` (§3) | Es el núcleo del negocio y depende de 1-4. | Los 12 casos de §3.9 en verde + flujo completo probado a mano en el sandbox. |
| 6 | **Admin dashboard completo**: secciones, auditoría, resumen (§4) | Con dinero real circulando, operarlo y auditarlo es obligatorio. | Toda acción de acceso o dinero deja fila en `admin_audit_log`. |
| 7 | **Generalización multijuego** + fixture de dados (§7) | No bloquea vender ruleta; sí bloquea agregar juegos. | Tests de §7.6 en verde; la ruleta funciona igual en la ruta nueva. |
| 8 | **Base de deportivas** (§8) | Solo estructura y respuestas a §8.3. | Preguntas de §8.3 respondidas por el usuario y documentadas. **Documentadas el 2026-10-15 en §8.4**, con la n.º 1 y la n.º 6 como pendientes (§10 n.º 13 y 14). |
| 9 | **Lanzamiento comercial** | Con todo construido, lo que falta es operativo y no de código. | La lista "Antes del lanzamiento comercial" de abajo, completa. |

Dos precisiones sobre el orden (2026-10-05):

- **`admin_audit_log` (§4.6) se crea en el paso 3, no en el 6.** Otorgar o retirar acceso manual ya es una acción auditable, y el paso 3 se prueba justamente con accesos manuales. Desde ese paso, toda acción de admin sobre acceso escribe su fila.
- **Las pantallas de admin de cada área nacen con su paso**: `/admin/legal` en el 2, `/admin/planes` y `/admin/descuentos` en el 4. El paso 6 las reúne bajo la navegación lateral y agrega usuarios, suscripciones, pagos, auditoría y resumen.

Trámites con tiempo de espera externo, que se inician al empezar la Fase 0 y no cuando su paso llega:

- Cuenta de comercio en Wompi: llaves de sandbox y aprobación para producción (bloquea el paso 5).
- Abogado para los textos de §6 (bloquea el lanzamiento, no la construcción: se construye con textos de borrador).
- Compra del dominio, proveedor SMTP y registros DNS (bloquea el cierre del paso 1; mientras tanto se trabaja con `ConsoleEmailSender`).

Antes del lanzamiento comercial, además: probar el flujo completo en el sandbox de Wompi, configurar SPF/DKIM/DMARC del dominio remitente, programar el cron de renovaciones en Dokploy, restaurar un respaldo de la base en un entorno de prueba para confirmar que sirve, que un abogado haya revisado los textos de §6, y el aviso por correo de versiones nuevas de los documentos legales (§6.7).

---

## 10. Decisiones pendientes

Lo que este documento no puede cerrar y necesita respuesta del usuario (o de un abogado o contador):

| # | Decisión | Propuesta por defecto (la más conservadora) |
|---|---|---|
| 1 | Qué pasa con los usuarios `trial` actuales al activar el control de acceso | **Resuelta (2026-10-08): pasan a `invited` sin vencimiento**, sin correo de aviso. El administrador les retira el acceso a mano cuando exista el pago. La propuesta original (14 días y correo) se descartó porque el pago podía no estar listo en ese plazo. |
| 2 | Planes y precios iniciales (mensual, trimestral, anual; montos en COP) | **Resuelta (2026-10-09): dos planes**, mensual de 100.000 COP y de dos meses de 150.000 COP. No hay plan anual. El precio de referencia de 30 USD que se decidió el 2026-10-08 se descartó: se muestra y se cobra solo en COP. Ver §3.10. |
| 3 | Medios de pago que no se pueden tokenizar (PSE, transferencias) | **Cambia (2026-10-08):** con el pago manual mes a mes (§3.10) estos medios sí se pueden ofrecer: cada pago compra un período, sin tokenizar nada. **Resuelta (2026-10-13):** el pago manual usa el Web Checkout de Wompi, que ofrece los medios que el comercio tenga habilitados en su panel; se encienden y se apagan allá, no en el código. Ver §3.12. |
| 4 | Facturación electrónica ante la DIAN | Consultar con el contador si aplica y con qué proveedor; no se integra hasta definirlo. |
| 5 | Si un cambio de precio del plan se traslada a las suscripciones vigentes | **Resuelta (2026-10-14): se construye la acción** (construida ese día, §4.10), en una entrega propia del paso 6, después de la 1: aviso por correo 30 días antes de cobrar el precio nuevo, a todas las suscripciones vigentes del plan en los dos modos (no a las canceladas), y el cupón que todavía descuenta sigue descontando sobre el precio nuevo. El plazo lo confirma el abogado. Ver §4.8. |
| 6 | Cupón que deja el total en cero (100 % de descuento) | **Resuelta (2026-10-09): no se permite.** El porcentaje va de 1 a 99 y un cupón de monto fijo que cubra todo el precio no aplica; una cortesía total se da como acceso `invited` desde el admin. Ver §3.11. |
| 7 | Reembolsos: manuales en el panel de Wompi o integrados por API | **Resuelta (2026-10-14): manuales en Wompi y registrados en el admin**, sin cambiar el pago ni el acceso. Una anulación (que Wompi sí reporta como estado de la transacción) retira sola el período que el pago había comprado. Ver §4.8. |
| 8 | Textos legales definitivos | Los redacta o revisa un abogado; el equipo entrega la estructura de §6.5. |
| 9 | Proveedor SMTP concreto | **Resuelta (2026-10-05): Resend**, enviando desde un subdominio propio. Resend confirmó que su política de uso admite el producto y el correo quedó encendido el 2026-10-07. Ver §13.6 y `DESPLIEGUE.md`. |
| 10 | Correo y responsable que figuran en la política de datos | **Correo resuelto (2026-10-07): `sebas.analisis.ia.com@gmail.com`**, una cuenta de Gmail, separada del remitente transaccional; no hay buzón en Hostinger. El responsable sigue pendiente: el usuario decidió el 2026-10-08 no ponerlo todavía, y los borradores publicados lo llevan como `[PENDIENTE]`. Bloquea el lanzamiento. |
| 11 | Servicio de monitoreo de errores | **Resuelta (2026-10-05): GlitchTip autohospedado** en el mismo VPS. Ver §13.6. |
| 12 | Mejoras opcionales de §13.4 (`ruff`/`mypy`, cabeceras CSP, refresh token en cookie) | `ruff` y `mypy`: **resueltas (2026-10-06)**, en el CI. Cabeceras CSP y refresh token en cookie: no se hacen hasta que el usuario lo diga. Los tests de frontend ya están decididos (§13.3). |
| 13 | Deportes: proveedor de calendario, resultados y cuotas, y presupuesto mensual (§8.3 n.º 1) | No se elige hasta que se vaya a construir deportes. Requisito: confirmación por escrito de que la licencia permite el uso comercial en un producto de pago; sus cuotas, solo para el backtest interno salvo que la licencia permita mostrarlas. Ver §8.4. Bloquea construir deportes, no el lanzamiento de la ruleta. |
| 14 | Deportes: si el análisis deportivo por suscripción requiere autorización de Coljuegos, qué avisos exige y si se puede usar la palabra "pronóstico" (§8.3 n.º 6) | Lo responde el abogado. Mientras tanto se supone que podría requerirla, y deportes no sale sin concepto escrito. Ver §8.4. Bloquea que salga deportes, no el lanzamiento de la ruleta. |
| 15 | Qué exige Wompi, y PCI DSS, con un formulario de tarjeta propio (§3.16) | Preguntarle a Wompi antes de lanzar. Con el widget la tarjeta se escribía en una ventana de Wompi; con el formulario propio se escribe en nuestra página, y en general eso amplía lo que el comercio tiene que cumplir (de SAQ A a SAQ A-EP). Bloquea el lanzamiento, no la construcción en sandbox. |

---

## 11. Endpoints nuevos

```
Auth:      POST /auth/verify-email          POST /auth/resend-verification
           POST /auth/forgot-password        POST /auth/reset-password
           POST /auth/change-password        POST /auth/change-email
           PATCH /auth/me                    DELETE /auth/me
           GET  /auth/me/export
           (GET /auth/me suma el campo access)

Legal:     GET  /legal/:kind                 (última versión publicada, pública)
           GET  /legal/pending               (documentos que el usuario debe aceptar)
           POST /legal/accept                {legal_document_ids}

Billing:   GET  /plans                       (pública)
           POST /billing/quote               {plan_id, coupon_code?}   (con sesión)
           GET  /billing/availability        (pública: si hay pasarela configurada)
           GET  /billing/acceptance          (acceptance token y enlace de términos de Wompi)
           POST /billing/subscriptions       {plan_id, coupon_code?, renewal_mode?, payment_source_token?,
                                              payment_source_type?, acceptance_token?, personal_data_token?}
           GET  /billing/subscription
           POST /billing/subscription/cancel
           POST /billing/subscription/resume
           PUT  /billing/payment-method      {payment_source_token, payment_source_type,
                                              acceptance_token, personal_data_token}
           DELETE /billing/payment-method    (pasa a pago manual)
           GET  /billing/payments            GET /billing/payments/:id

Webhooks:  POST /webhooks/wompi              (sin JWT; autenticado por firma)

Admin:     GET  /admin/overview
           GET  /admin/users?query&filters&cursor     GET /admin/users/:id
           PATCH /admin/users/:id/access     PATCH /admin/users/:id/role
           PATCH /admin/users/:id/status     POST  /admin/users/:id/force-password-reset
           POST /admin/users/:id/resend-verification
           (force-password-reset lleva {reason}; ver §4.9)
           GET  /admin/subscriptions         GET   /admin/subscriptions/:id
           PATCH /admin/subscriptions/:id    {action: extend|cancel_at_period_end|cancel_now, days?, reason}
           GET  /admin/payments              GET   /admin/payments/:id
           POST /admin/payments/:id/requery  {reason}
           POST /admin/payments/:id/refunds  {amount_cents, refunded_at, provider_refund_id?, reason}
           GET|POST /admin/plans             PATCH /admin/plans/:id
           GET|POST /admin/plans/:id/price-transfer   {reason}   (§4.10)
           PUT  /admin/plans/:id/games       {game_ids, reason}   (§7.7; vacio = todos)
           GET  /admin/price-changes         POST  /admin/price-changes/:id/cancel   {reason}
           GET|POST /admin/coupons           PATCH /admin/coupons/:id
           GET  /admin/coupons/:id/redemptions
           GET|POST /admin/legal-documents   PATCH /admin/legal-documents/:id
           POST /admin/legal-documents/:id/publish
           GET  /admin/audit-log
           GET  /admin/games?status&module&q&limit&offset   (§7.7)
           (los de juegos y variantes existentes suman los campos de §7.2;
            GET /games pasa a ser el menu paginado, con el acceso de cada juego)
```

Todos los endpoints de juego existentes (`games`, `sessions`, `suggestions`, `recommendations`, `bankroll`, `bets`) pasan a exigir `RequireAccess` (§2.1).

---

## 12. Variables de entorno nuevas

Se agregan a `backend/.env.example` (solo nombres) y a la sección de variables de `docs/DESPLIEGUE.md`.

| Variable | Uso |
|---|---|
| `FRONTEND_BASE_URL` | Base de los enlaces en los correos (`https://sebasanalisis.com`). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Servidor de correo. |
| `SMTP_FROM` | Remitente (`Sebasanálisis <no-responder@…>`). |
| `SMTP_USE_TLS` | `true` en producción. |
| `EMAIL_BACKEND` | `smtp` \| `console` \| `file` (solo tests de punta a punta). |
| `EMAIL_FILE_DIR` | Carpeta donde `FileEmailSender` escribe los correos. Solo con `EMAIL_BACKEND=file`. |
| `WOMPI_PUBLIC_KEY` | Llave pública (también va al frontend como build argument `NEXT_PUBLIC_WOMPI_PUBLIC_KEY`). |
| `WOMPI_PRIVATE_KEY` | Llave privada: crear fuentes de pago, cobrar, reconsultar transacciones. |
| `WOMPI_EVENTS_SECRET` | Verificación del checksum de los webhooks. |
| `WOMPI_INTEGRITY_SECRET` | Firma de integridad de las transacciones. |
| `WOMPI_API_BASE_URL` | Sandbox o producción. Opcional: se deduce de las llaves; si se pone, debe ser la de su ambiente. |
| `PAYMENT_PROVIDER` | `wompi` (por defecto) \| `fake`, una pasarela simulada solo para desarrollo y tests de punta a punta (§3.12). |
| `API_PUBLIC_URL` | Solo con `PAYMENT_PROVIDER=fake`: dónde responde la API, para el enlace de la pasarela simulada. |
| `FORWARDED_ALLOW_IPS` | Direcciones del proxy de Dokploy de las que uvicorn acepta `X-Forwarded-For` (§13.1). |
| `SENTRY_DSN` | DSN del proyecto de la API en GlitchTip (§13.6). Vacío = desactivado (desarrollo y tests). |
| `NEXT_PUBLIC_SENTRY_DSN` | DSN del proyecto del frontend en GlitchTip. Va como build argument, igual que `NEXT_PUBLIC_API_BASE_URL`. |

Las llaves de sandbox y de producción de Wompi son distintas; un despliegue nunca debe quedar con llaves de sandbox en producción. El arranque de la API registra en el log (sin mostrar la llave) contra qué ambiente de Wompi quedó configurada.

---

## 13. Fase 0: preparación del stack

Revisado contra el código el 2026-10-05. No agrega funcionalidad: deja el proyecto en condiciones de recibir código que maneja dinero y datos personales. El stack no cambia de fondo (FastAPI, SQLAlchemy, PostgreSQL, Next.js, Tailwind).

### 13.1 Cambios necesarios

| # | Cambio | Por qué |
|---|---|---|
| 1 | **Subir `next` y `react`** a la última versión estable parchada. Hoy: `next 15.1.4`, `react 19.0.0`. | `npm audit --omit=dev` reporta severidad crítica, incluida ejecución remota de código sin autenticación en el protocolo de React Server Components (GHSA-9qr9-h5gf-34mp) y un bypass de autorización en middleware (GHSA-f82v-jwr5-mffw). Aplica también al despliegue actual del MVP, no solo a la Fase 4. |
| 2 | **IP real del cliente detrás del proxy.** `docker-entrypoint.sh` levanta uvicorn con `--proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"`. | `auth.py` toma la IP de `request.client.host`. Detrás del proxy de Dokploy esa es la IP del proxy: el rate limit quedaría compartido entre todos los usuarios, y las IP de `user_consents` y `admin_audit_log` serían inútiles como evidencia. Nunca se confía en `X-Forwarded-For` de un origen que no sea el proxy. |
| 3 | **CI con GitHub Actions** (`.github/workflows/ci.yml`). Hoy no existe. | Corre en cada push: `pytest` con un servicio de PostgreSQL 16, `alembic upgrade head` sobre base limpia seguido de `alembic downgrade -1`, `npm run typecheck`, `npm run lint`, la comprobación de tipos generados (§13.2), `npm audit --omit=dev` y `pip-audit`. |
| 4 | **`httpx` pasa de `requirements-dev.txt` a `requirements.txt`.** | El cliente de Wompi lo usa en producción. Toda llamada lleva timeout explícito. Se hace en el paso 5, se anota aquí para que no se olvide. |
| 5 | **`jinja2`** para las plantillas de `backend/app/emails/`, con autoescape activado. | Los correos incluyen datos del usuario (nombre). El envío usa `smtplib` y `email.message` de la librería estándar: no se agrega dependencia para SMTP. Entra en el paso 1. |
| 6 | **`react-markdown`** para renderizar los documentos legales. | No interpreta HTML crudo por defecto, que es lo que exige §6.2. No se le agrega `rehype-raw`. Entra en el paso 2. |
| 7 | **Monitoreo de errores** en backend y frontend con GlitchTip (§13.6). | Un webhook que falla o un job de renovación que no corre es dinero perdido sin que nadie lo vea. Debe estar activo antes del paso 5. |
| 8 | **Playwright instalado** con un test de humo (§13.3). | Deja la infraestructura de tests de punta a punta lista para que cada paso sume su flujo. |

### 13.2 Generador de tipos (decidido el 2026-10-05)

Reemplaza la sincronización manual de `frontend/lib/types/` con los schemas Pydantic. La Fase 4 agrega cerca de 45 endpoints y mantenerlos a mano no escala.

**Cómo funciona:**

1. `backend/scripts/export_openapi.py` importa la app y escribe `app.openapi()` en `frontend/lib/api/openapi.json`, con las claves ordenadas para que el diff sea estable. No levanta el servidor ni toca la base.
2. `openapi-typescript` (devDependency del frontend) convierte ese archivo en `frontend/lib/api/schema.d.ts`.
3. Un solo comando hace las dos cosas: `npm run gen:types`.
4. **Los dos archivos generados se commitean.** Así el diff de un cambio de schema se ve en la revisión, y el build del frontend en Dokploy no necesita Python.
5. El CI vuelve a generar y corre `git diff --exit-code` sobre esos dos archivos: si alguien cambió un schema y no regeneró, el CI falla.

**Reglas:**

- Los archivos generados no se editan a mano.
- Todo endpoint declara su `response_model` (o su tipo de retorno): un endpoint sin él aparece en el OpenAPI sin forma, y el frontend volvería a tiparlo a mano.
- Los enums se declaran como `Literal` o `Enum` en Pydantic, para que lleguen al cliente como uniones y no como `string`.
- Todo schema hereda de `ApiModel` (`backend/app/schemas/base.py`), no de `BaseModel` (decidido el 2026-10-06). Sin eso, un campo de respuesta `X | None = None` se publica como opcional y el tipo generado dice que puede faltar, cuando la API siempre lo envía con `null`. Fue la única diferencia que la migración encontró entre los tipos manuales y el backend: 49 campos. Efecto secundario: un modelo que se usa a la vez en una petición y en una respuesta se publica dos veces (`-Input` y `-Output`); `lib/types/` reexporta la versión de salida.
- El generador evita que los tipos se desincronicen, pero **`apiFetch` sigue sin validar en runtime**. Un backend desplegado con una versión distinta a la del frontend todavía puede romper una pantalla; por eso backend y frontend siguen saliendo del mismo commit (`docs/DESPLIEGUE.md`).

**Migración** (parte de la Fase 0, sin cambiar comportamiento):

1. Generar `schema.d.ts` contra la API actual.
2. Cada archivo de `frontend/lib/types/*.ts` pasa a reexportar el tipo generado con el nombre que ya usan los componentes (`export type SessionResponse = components["schemas"]["SessionResponse"]`). Los componentes no se tocan.
3. `npm run typecheck` señala cada lugar donde el tipo manual ya se había desviado del backend. Cada diferencia se revisa y se corrige; son errores que hoy existen sin verse.
4. La skill `.claude/skills/api-schema-sync` se reescribe: su instrucción pasa a ser "corre `npm run gen:types` y commitea", y `CLAUDE.md` se actualiza para decir lo mismo.

### 13.3 Tests de frontend con Playwright (decidido el 2026-10-05)

Hoy el frontend no tiene ningún test. Se agregan tests de punta a punta (navegador real contra la API y una base de test), no tests unitarios de componentes: lo que interesa cubrir son los flujos donde un error cuesta una venta o un problema legal.

| Flujo | Se escribe en | Corre en CI |
|---|---|---|
| Humo: iniciar sesión, abrir una mesa, registrar un giro y ver la tarjeta de recomendación | Fase 0 | Sí |
| Registro con consentimientos → correo de verificación → cuenta verificada | Paso 1 (consentimientos se suman en el 2) | Sí |
| Restablecer contraseña y comprobar que la sesión anterior quedó cerrada | Paso 1 | Sí |
| Versión nueva de los términos → la mesa pide re-aceptar → se acepta y se entra | Paso 2 | Sí |
| Cuenta sin acceso → ve la página de planes y no la mesa | Paso 3 | Sí |
| Checkout completo contra el sandbox de Wompi | Paso 5 | **No**: se corre a mano antes de cada despliegue que toque pagos, con las llaves de sandbox. Depende de un servicio externo y no debe tumbar el CI. |

- Viven en `frontend/e2e/`, con `npm run test:e2e`.
- El CI levanta PostgreSQL, la API (con `EMAIL_BACKEND=file`) y el frontend ya construido; Playwright lee el enlace del correo desde `EMAIL_FILE_DIR` (§5.5).
- Los tests no comparten estado: cada uno registra su propio usuario.
- Los tests de punta a punta **no reemplazan** los de API de §2.4, §3.9, §5.8 y §7.6: las reglas de acceso y de dinero se prueban en el backend, que es donde se deciden.

### 13.4 Mejoras opcionales (sin decidir, #12 de §10)

| Mejora | Qué aporta | Cuándo convendría |
|---|---|---|
| `ruff` y `mypy` en el backend, dentro del CI | Errores de tipos y de estilo antes de la revisión. | **Hecho en la Fase 0 (decidido el 2026-10-06).** `ruff` revisa todo el backend (solo lint, sin formateador); `mypy` en modo estricto revisa `app/engine/`, y `app/billing/` se le suma al crearse. Configuración en `backend/pyproject.toml`. |
| Cabeceras `Content-Security-Policy` en `next.config.ts` | Los tokens viven en `localStorage` y, desde el 2026-10-19, la tarjeta se escribe en un formulario de nuestra página (§3.16). Una CSP limita qué puede ejecutar la página y a dónde puede enviar datos. | Paso 5. Con el formulario propio conviene antes del lanzamiento; sigue siendo decisión del usuario (§10 n.º 12). |
| Refresh token en cookie `httpOnly` en vez de `localStorage` | Lo saca del alcance de un script inyectado. Cambia el flujo de auth y la configuración de CORS. | Después del lanzamiento. |

### 13.5 Lo que no se agrega

- **Redis, Celery o cualquier cola en la aplicación.** El job de renovaciones es un script con cron de Dokploy, protegido por `pg_try_advisory_lock` y por restricciones únicas (§3.5). El rate limit, si hiciera falta compartirlo entre procesos, va a una tabla de Postgres (§5.6). GlitchTip trae sus propios servicios internos (§13.6); son suyos y la aplicación no los usa.
- **SDK no oficial de Wompi.** El cliente es propio, sobre `httpx`, escrito contra la documentación oficial (§3.1).
- **Reescritura a async.** Los endpoints y SQLAlchemy siguen síncronos.
- **Servidor de correo propio en el VPS.** Ver §13.6.

**Fase 0 hecha cuando:** `npm audit --omit=dev` sin vulnerabilidades críticas ni altas; CI en verde en `main`; tipos generados y `lib/types/` reexportando desde ellos; rate limit de login probado con dos IP distintas detrás del proxy; test de humo de Playwright corriendo en el CI; un error provocado a propósito en la API y otro en el frontend aparecen en GlitchTip; skill `api-schema-sync` y `CLAUDE.md` actualizados.

### 13.6 Correo y monitoreo: servicios elegidos

#### Correo: Resend (decidido el 2026-10-05)

El dominio `sebasanalisis.com` y el VPS están en Hostinger. Tres piezas distintas, que no se mezclan:

| Pieza | Qué se usa |
|---|---|
| **Correo transaccional** (verificación, recibos, cobros fallidos) | Resend, por su relay SMTP. El código solo conoce las variables `SMTP_*` (§12): los valores de host, puerto y usuario se copian de la documentación vigente de Resend al configurarlo, y la contraseña es la API key. Cambiar de proveedor no toca código. |
| **Buzón de personas** (soporte y contacto de la política de datos) | `sebas.analisis.ia.com@gmail.com`, una cuenta de Gmail (decidido el 2026-10-07; antes se preveía un buzón de Hostinger sobre el dominio). |
| **DNS** | En el panel de Hostinger: registros SPF, DKIM y DMARC que entrega Resend al dar de alta el dominio. |

- **No se envía desde el VPS** (Postfix o similar): una IP de VPS sin reputación cae en spam, y un correo de verificación que no llega es un cliente que no puede pagar.
- **No se usa un buzón de personas como remitente transaccional** (ni el de Gmail ni uno de Hostinger): tienen límites de envío pensados para personas.
- **Subdominio remitente** (por ejemplo `correo.sebasanalisis.com`): separa la reputación del correo automático de la del dominio principal.
- **Política de uso aceptable**: el producto es adyacente a juegos de azar y varios proveedores restringen ese contenido. Se confirma por escrito con Resend antes de configurar el dominio, describiendo el servicio como lo que es: análisis estadístico por suscripción, que no recibe apuestas. Si la respuesta es negativa, se cambia a otro relay SMTP (Brevo, Amazon SES) cambiando solo las variables.
- **Límites del plan**: se revisan los topes diario y mensual del plan contratado contra el volumen esperado antes del lanzamiento; un tope diario alcanzado deja sin correo de verificación a quien se registre ese día.

#### Monitoreo de errores: GlitchTip autohospedado (decidido el 2026-10-05)

- GlitchTip habla el protocolo de Sentry: la API usa `sentry-sdk` y el frontend `@sentry/nextjs`, apuntando al DSN de GlitchTip. No se envía nada a un tercero.
- Se despliega en Dokploy como un servicio aparte (plantilla o Docker Compose de la documentación vigente de GlitchTip), con **su propia base de datos**, nunca la de la aplicación, y su subdominio (por ejemplo `errores.sebasanalisis.com`) con HTTPS. El registro de usuarios nuevos queda cerrado tras crear la cuenta de administrador.
- Dos proyectos: uno para la API y otro para el frontend, cada uno con su DSN (§12).
- **Datos que no salen de la aplicación**: `send_default_pii` desactivado, y un filtro `before_send` que quita cabeceras `Authorization`, cuerpos de `/auth/*` y de `/billing/*`, y el cuerpo crudo de los webhooks. Ni contraseñas, ni tokens, ni referencias de pago llegan al monitoreo.
- **Alertas**: correo al administrador ante un error nuevo en producción. GlitchTip envía sus alertas por el mismo SMTP.
- **Job de renovaciones**: cada corrida termina llamando a un monitor de tipo *heartbeat* en GlitchTip; si pasan dos horas sin recibirlo, alerta.
- **Límite de tenerlo en el mismo VPS**: si el VPS se cae, el monitoreo se cae con él y no avisa. Se preveía cubrirlo con un chequeo externo gratuito de disponibilidad sobre `GET /health` de la API y sobre la página de inicio; **el usuario decidió no hacerlo (2026-10-07)** y acepta ese límite. Antes de instalarlo se confirma que el VPS tiene memoria libre suficiente para GlitchTip además de la aplicación.
- Retención de eventos limitada (90 días) para que no llene el disco.
