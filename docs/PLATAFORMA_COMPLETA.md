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
3. [Pagos y suscripciones con Wompi](#3-pagos-y-suscripciones-con-wompi)
4. [Admin dashboard](#4-admin-dashboard)
5. [Mejoras de autenticación](#5-mejoras-de-autenticación)
6. [Términos, condiciones y políticas](#6-términos-condiciones-y-políticas)
7. [Plataforma multijuego](#7-plataforma-multijuego)
8. [Base para apuestas deportivas](#8-base-para-apuestas-deportivas)
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
| Modalidad de cobro | **Renovación automática** con tarjeta tokenizada en Wompi. El backend cobra cada período sin intervención del usuario. |
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
| **Páginas legales** | No existe ninguna. Tampoco el onboarding scroll-to-accept ni la página de Juego Responsable que exige §0 del doc de arquitectura. | Se construyen con versionado y registro de aceptación. §6. |
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

- **Nunca se guardan datos de tarjeta.** La tarjeta la tokeniza el widget de Wompi en el navegador; el backend solo recibe y guarda la referencia de la fuente de pago y, para mostrar, marca y últimos cuatro dígitos.
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
  │ ingresa tarjeta        │ widget tokeniza ──────────────────────────────────────────▶│
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

`subscriptions.price_cents` guarda el precio al suscribirse. Un cambio de precio del plan en el admin aplica a **suscripciones nuevas**; las vigentes renuevan con su precio congelado. Si se decide trasladar el precio nuevo a las existentes, es una acción explícita del admin, auditada, con aviso por correo al usuario antes del cobro (decisión pendiente, §10).

### 3.8 Correos transaccionales de cobro

Bienvenida al activar, recibo de cada cobro aprobado, cobro fallido con enlace para cambiar la tarjeta, aviso de vencimiento cuando se agotan los reintentos, confirmación de cancelación. Todos pasan el filtro de terminología: describen el servicio, nunca resultados.

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
- **Pendiente para el paso 4**: límite de intentos en la cotización con cupón, para que no se puedan adivinar códigos.
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
| Juego Responsable | `/legal/juego-responsable` | Exigida por §0 del doc de arquitectura y todavía sin construir. Contenido tomado de `docs/reference/ESTRATEGIA_DE_RULETA_CORREGIDA_Y_VERIFICADA.txt`: límites de tiempo y dinero, nunca usar dinero de obligaciones, detenerse ante progresiones incómodas, líneas de ayuda. |
| Cancelación y Reembolsos | `/legal/reembolsos` | Cómo cancelar, qué pasa con el período pagado, reembolsos. Revisar con abogado el derecho de retracto del Estatuto del Consumidor (Ley 1480 de 2011) en ventas a distancia. |
| Cookies y almacenamiento local | `/legal/cookies` | Hoy la sesión vive en `localStorage` y no hay analítica de terceros; el documento lo dice así. Si se agrega analítica, se actualiza. |
| Aviso sobre la naturaleza del servicio | dentro de T&C | Ver §6.5. |

### 6.2 Versionado

```sql
legal_documents (
  id, kind,                -- 'terms' | 'privacy' | 'responsible_gaming' | 'refunds' | 'cookies'
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
- Espacios de nombres reservados: `/deportes` en el frontend, `/sports` en la API, `backend/app/engine/sports/` para su motor (también puro y testeable).
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

---

## 9. Orden de construcción

Como en `CLAUDE.md`: no se avanza a un paso sin que el anterior tenga tests o una verificación manual funcionando. El orden pone primero lo que bloquea cobrar.

| # | Paso | Por qué en este lugar | Hecho cuando |
|---|---|---|---|
| 0 | **Preparación del stack** (§13) | Hay vulnerabilidades críticas abiertas en el frontend y no hay CI; las dos cosas se cierran antes de escribir código que maneja dinero. | Lista "Fase 0 hecha cuando" de §13.5 completa. |
| 1 | **Correo + verificación + restablecimiento + `token_version`** (§5) | Sin correo no hay recibos, avisos de cobro fallido ni recuperación de cuenta, y verificar el correo es requisito para pagar. | Tests de §5.8 en verde; correo real recibido desde el SMTP elegido. |
| 2 | **Legal**: documentos versionados, consentimientos en el registro, páginas públicas, Juego Responsable, onboarding (§6) | No se puede cobrar sin T&C y política de datos aceptados. | Registro sin consentimientos → rechazado; versión nueva → re-aceptación. |
| 3 | **Modelo de acceso** (`has_access`, `RequireAccess`, migraciones de `access_type`) (§2) | Sin esto el pago no compra nada. Se hace antes de Wompi para probarlo con accesos manuales. | Tests de §2.4 en verde, incluido el que recorre todos los routers. |
| 4 | **Planes y cupones**: modelo, `billing/pricing.py`, CRUD en el admin, página `/planes` (§3.2, §3.3, §4.4, §4.5) | Wompi necesita algo que cobrar. | Cotizaciones correctas en todos los casos de cupón. |
| 5 | **Wompi**: alta, webhook, reconsulta, renovación, reintentos, cancelación, cambio de tarjeta, `/cuenta` (§3) | Es el núcleo del negocio y depende de 1-4. | Los 12 casos de §3.9 en verde + flujo completo probado a mano en el sandbox. |
| 6 | **Admin dashboard completo**: secciones, auditoría, resumen (§4) | Con dinero real circulando, operarlo y auditarlo es obligatorio. | Toda acción de acceso o dinero deja fila en `admin_audit_log`. |
| 7 | **Generalización multijuego** + fixture de dados (§7) | No bloquea vender ruleta; sí bloquea agregar juegos. | Tests de §7.6 en verde; la ruleta funciona igual en la ruta nueva. |
| 8 | **Base de deportivas** (§8) | Solo estructura y respuestas a §8.3. | Preguntas de §8.3 respondidas por el usuario y documentadas. |
| 9 | **Lanzamiento comercial** | Con todo construido, lo que falta es operativo y no de código. | La lista "Antes del lanzamiento comercial" de abajo, completa. |

Dos precisiones sobre el orden (2026-10-05):

- **`admin_audit_log` (§4.6) se crea en el paso 3, no en el 6.** Otorgar o retirar acceso manual ya es una acción auditable, y el paso 3 se prueba justamente con accesos manuales. Desde ese paso, toda acción de admin sobre acceso escribe su fila.
- **Las pantallas de admin de cada área nacen con su paso**: `/admin/legal` en el 2, `/admin/planes` y `/admin/descuentos` en el 4. El paso 6 las reúne bajo la navegación lateral y agrega usuarios, suscripciones, pagos, auditoría y resumen.

Trámites con tiempo de espera externo, que se inician al empezar la Fase 0 y no cuando su paso llega:

- Cuenta de comercio en Wompi: llaves de sandbox y aprobación para producción (bloquea el paso 5).
- Abogado para los textos de §6 (bloquea el lanzamiento, no la construcción: se construye con textos de borrador).
- Compra del dominio, proveedor SMTP y registros DNS (bloquea el cierre del paso 1; mientras tanto se trabaja con `ConsoleEmailSender`).

Antes del lanzamiento comercial, además: probar el flujo completo en el sandbox de Wompi, configurar SPF/DKIM/DMARC del dominio remitente, programar el cron de renovaciones en Dokploy, restaurar un respaldo de la base en un entorno de prueba para confirmar que sirve, y que un abogado haya revisado los textos de §6.

---

## 10. Decisiones pendientes

Lo que este documento no puede cerrar y necesita respuesta del usuario (o de un abogado o contador):

| # | Decisión | Propuesta por defecto (la más conservadora) |
|---|---|---|
| 1 | Qué pasa con los usuarios `trial` actuales al activar el control de acceso | Pasan a `invited` con `access_expires_at` 14 días después del despliegue y se les avisa por correo. |
| 2 | Planes y precios iniciales (mensual, trimestral, anual; montos en COP) | Un plan mensual y uno anual. |
| 3 | Medios de pago que no se pueden tokenizar (PSE, transferencias) | No se ofrecen en esta fase; solo tarjeta (y Nequi si la documentación vigente de Wompi permite tokenizarlo para cobros recurrentes). Reevaluar con datos de conversión. |
| 4 | Facturación electrónica ante la DIAN | Consultar con el contador si aplica y con qué proveedor; no se integra hasta definirlo. |
| 5 | Si un cambio de precio del plan se traslada a las suscripciones vigentes | No se traslada: precio congelado (§3.7). |
| 6 | Cupón que deja el total en cero (100 % de descuento) | No se permite en cupones; una cortesía total se da como acceso `invited` desde el admin. |
| 7 | Reembolsos: manuales en el panel de Wompi o integrados por API | Manuales en Wompi y registrados en el admin. |
| 8 | Textos legales definitivos | Los redacta o revisa un abogado; el equipo entrega la estructura de §6.5. |
| 9 | Proveedor SMTP concreto | **Resuelta (2026-10-05): Resend**, enviando desde un subdominio propio. Resend confirmó que su política de uso admite el producto y el correo quedó encendido el 2026-10-07. Ver §13.6 y `DESPLIEGUE.md`. |
| 10 | Correo y responsable que figuran en la política de datos | **Correo resuelto (2026-10-07): `sebas.analisis.ia.com@gmail.com`**, una cuenta de Gmail, separada del remitente transaccional; no hay buzón en Hostinger. El responsable sigue pendiente del usuario. |
| 11 | Servicio de monitoreo de errores | **Resuelta (2026-10-05): GlitchTip autohospedado** en el mismo VPS. Ver §13.6. |
| 12 | Mejoras opcionales de §13.4 (`ruff`/`mypy`, cabeceras CSP, refresh token en cookie) | `ruff` y `mypy`: **resueltas (2026-10-06)**, en el CI. Cabeceras CSP y refresh token en cookie: no se hacen hasta que el usuario lo diga. Los tests de frontend ya están decididos (§13.3). |

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
           POST /billing/quote               {plan_id, coupon_code?}
           GET  /billing/acceptance          (acceptance token y enlace de términos de Wompi)
           POST /billing/subscriptions       {plan_id, coupon_code?, card_token, acceptance_token}
           GET  /billing/subscription
           POST /billing/subscription/cancel
           POST /billing/subscription/resume
           PUT  /billing/payment-method      {card_token, acceptance_token}
           GET  /billing/payments            GET /billing/payments/:id

Webhooks:  POST /webhooks/wompi              (sin JWT; autenticado por firma)

Admin:     GET  /admin/overview
           GET  /admin/users?query&filters&cursor     GET /admin/users/:id
           PATCH /admin/users/:id/access     PATCH /admin/users/:id/role
           PATCH /admin/users/:id/status     POST  /admin/users/:id/force-password-reset
           POST /admin/users/:id/resend-verification
           GET  /admin/subscriptions         PATCH /admin/subscriptions/:id
           GET  /admin/payments              GET   /admin/payments/:id
           POST /admin/payments/:id/requery
           GET|POST /admin/plans             PATCH /admin/plans/:id
           GET|POST /admin/coupons           PATCH /admin/coupons/:id
           GET  /admin/coupons/:id/redemptions
           GET|POST /admin/legal-documents   PATCH /admin/legal-documents/:id
           POST /admin/legal-documents/:id/publish
           GET  /admin/audit-log
           (los de juegos y variantes existentes suman los campos de §7.2)
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
| `WOMPI_API_BASE_URL` | Sandbox o producción. |
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
| Cabeceras `Content-Security-Policy` en `next.config.ts` | Los tokens viven en `localStorage` y el checkout carga un script de terceros (el widget de Wompi). Una CSP limita qué puede ejecutar la página. | Paso 5. |
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
