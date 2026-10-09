# Sebasanálisis — Hoja de ruta

> Punto de entrada a la documentación. Dice qué es el producto hoy, qué se construyó, qué decisiones cambiaron por el camino y qué se construye ahora. No define reglas ni fórmulas: apunta al documento que las define.
>
> **Se actualiza cada vez que se cierra un paso o se toma una decisión de rumbo.** Última actualización: 2026-10-08.

---

## 1. El producto hoy

Sebasanálisis es una plataforma web por suscripción. El usuario registra a mano los números que salen en una mesa de ruleta y, después de cada giro, la plataforma le entrega **una recomendación** para el giro siguiente (qué apostar, o no apostar), con un Signal Score de 0 a 100, su banda, y el monto que pide cada gestión de banca.

La recomendación sale de reglas estadísticas sobre los resultados registrados. **No es una predicción**: cada giro es independiente y ninguna gestión de banca cambia la ventaja de la casa. Esa regla de lenguaje es la más importante del proyecto (`ARQUITECTURA_Y_ESTADISTICA.md` §0).

**Dónde está:** el núcleo (motor, mesa de ruleta, admin básico) está construido y aprobado. Todavía no cobra. Desde el paso 3 de la Fase 4 la mesa exige acceso: una cuenta nueva no entra hasta que un administrador se lo otorgue, porque el pago todavía no existe (paso 5).

**Hacia dónde va:** la Fase 4 lo convierte en plataforma comercial. Control de acceso, pagos con Wompi, correo, textos legales, admin completo y una base que admita más juegos.

---

## 2. Mapa de documentos

| Documento | Qué define | Cuándo se lee |
|---|---|---|
| `CLAUDE.md` | Reglas de trabajo vigentes: lenguaje, stack, convenciones, qué no hacer. | Siempre, antes de escribir código. |
| `docs/HOJA_DE_RUTA.md` (este) | Estado, historia y rumbo. | Para ubicarse. |
| `docs/ARQUITECTURA_Y_ESTADISTICA.md` | Filosofía y terminología (§0), motor estadístico y de recomendación (§2), arquitectura y modelo de datos del núcleo (§3), alcance por etapas (§4). | Al tocar el motor, la mesa o el modelo de juego. |
| `docs/PLATAFORMA_COMPLETA.md` | Especificación de la Fase 4: acceso, pagos, admin, auth, legal, multijuego, preparación del stack. | Al tocar cualquiera de esas áreas. Es el trabajo en curso. |
| `docs/DESPLIEGUE.md` | Despliegue en el VPS con Dokploy, variables de entorno, dominios. | Al desplegar o agregar una variable. |
| `docs/design/` | Mockups de login, registro y mesa. | Al construir o cambiar esas pantallas. |
| `docs/reference/` | Insumos que no se modifican: estrategia verificada por un analista, boceto estadístico previo, comparativo que originó la Fase 3. | Como fuente; nunca como especificación vigente. |

**Si dos documentos se contradicen:** gana `ARQUITECTURA_Y_ESTADISTICA.md` sobre `CLAUDE.md` y sobre `PLATAFORMA_COMPLETA.md`, y se le pide al usuario que lo aclare antes de asumir.

---

## 3. Lo que ya se hizo

### Etapa 1 — MVP: analizador estadístico de ruleta (construido)

Ocho pasos, en este orden:

1. Schema de base de datos con Alembic y seed (usuario admin, ruleta europea y americana con su `categories_json`).
2. Auth: registro, login, refresh, perfil.
3. Admin: CRUD de juegos y variantes con formulario simple.
4. Menú principal y selector de juegos.
5. Mesa de ruleta con ingreso manual de números giro a giro.
6. Motor estadístico núcleo: frecuencia con shrinkage, recencia, χ², racha, EV, ranking top-3, auto-evaluación.
7. Motor de bankroll: martingala, d'Alembert, Fibonacci, plana y modo dos sectores.
8. Carga inicial de números al abrir una sesión.

Definido en `ARQUITECTURA_Y_ESTADISTICA.md` §2.1 a §2.9, §3 y §4.

### Fase 2 — Pagos con Wompi (decidida el 2026-09-17, no construida como fase aparte)

Se fijaron las reglas de pagos (firma, reconsulta, idempotencia, centavos, acceso en el servidor) y los cuatro tests obligatorios. **No se llegó a construir**: la Fase 3 entró antes, y la Fase 4 absorbió los pagos con un alcance mayor. Las reglas siguen vigentes tal cual y viven en `CLAUDE.md` y en `PLATAFORMA_COMPLETA.md` §3.1.

"Fase 2" también se usó para nombrar las **señales avanzadas del motor** (transición condicional, k-gramas, ciclo, señales de pleno). Esas siguen fuera de alcance y no tienen fecha (§6).

### Fase 3 — Motor de recomendación (decidida el 2026-09-22, construida)

El producto dejó de ser un analizador descriptivo y pasó a recomendar una sola jugada por giro. Entregó:

- `engine/recommendation.py`: catálogo de mercados desde `categories_json`, Signal Score, decisión y desempate determinista.
- La mesa muestra las tres gestiones de banca a la vez (plana, martingala, dos sectores); la sesión ya no elige una.
- `statistical_suggestions` se escribe: una fila por recomendación emitida, incluido el `NO_BET`.
- Backtest interno (`engine/backtest.py`, CLI y endpoint de admin).

Ajustes posteriores, ya construidos:

- **2026-09-23:** la vista deja de pintar el top-3, las señales por categoría, la racha y la tasa de coincidencia (los endpoints siguen). Un escalón de progresión solo avanza si el usuario apostó con esa gestión.
- **2026-09-24:** cuatro estados de salida (FUERTE, MEDIA, DÉBIL, SIN SEÑAL) con umbrales por variante; calibración vigente (`Z_MAX` 1.6, pesos 0.58/0.32/0.10); estado de parar de la mesa (banca agotada, límite de pérdida).

Definido en `ARQUITECTURA_Y_ESTADISTICA.md` §2.10. El origen del cambio está en `docs/reference/Comparativo_Software_Actual_vs_Software_Deseado.md`.

---

## 4. Decisiones que cambiaron

Lo que un documento viejo o un trozo de código antiguo puede seguir sugiriendo, y ya no vale:

| Antes | Ahora | Desde |
|---|---|---|
| Producto descriptivo: mostraba estadísticas y un ranking top-3. | Motor de recomendación: una jugada por giro, o no apostar. | Fase 3 |
| Banner fijo de disclaimer en toda pantalla con sugerencias. | Retirado. Quedan dos líneas obligatorias en la tarjeta de recomendación; el resto lo cubren los términos. | Fase 3 |
| La sesión elegía una progresión al crearse. | La mesa muestra las tres; el usuario sigue la que quiera. | Fase 3 |
| Cinco gestiones de banca. | Tres: plana, martingala, dos sectores. D'Alembert y Fibonacci salieron del producto. | Fase 3 |
| Las progresiones avanzaban con el cierre de la recomendación, apostara o no el usuario. | Un escalón solo avanza si el usuario apostó con esa gestión. | 2026-09-23 |
| Tres bandas de señal. | Cuatro estados, con DÉBIL limitada a gestión plana. | 2026-09-24 |
| Lectura de pantallazos con un modelo de visión para cargar números. | Descartada. Todo número lo ingresa el usuario a mano; el proyecto no llama a ninguna IA. | MVP |
| Prueba gratuita (`access_type = trial`). | Desaparece. Cuenta nueva sin acceso hasta pagar, o acceso manual del admin. | Fase 4 |
| Cualquier cuenta registrada usa la mesa. | El acceso lo decide una sola función en el servidor, en todos los endpoints de juego. | Fase 4, paso 3 |
| Tipos TypeScript del cliente API mantenidos a mano. | Generados desde el OpenAPI de FastAPI. | Fase 4, paso 0 |
| Pagos como "Fase 2" independiente. | Parte de la Fase 4, con renovación automática, planes y cupones. | Fase 4 |
| Cobro solo con renovación automática y tarjeta tokenizada; PSE y transferencias descartados. | Dos modos: renovación automática con fuente tokenizada, y pago manual mes a mes para quien no tokeniza. | 2026-10-08 |
| Varios planes (mensual y anual). | Un solo plan, mensual, de 100.000 COP. Se muestra y se cobra solo en COP. | 2026-10-08 |
| Mostrar además un precio fijo de 30 USD, solo visual (2026-10-08). | No se muestra: un solo precio, el que se cobra. | 2026-10-09 |
| Buzón de soporte en Hostinger sobre el dominio (`soporte@sebasanalisis.com`). | El correo de soporte y de contacto es una cuenta de Gmail: `sebas.analisis.ia.com@gmail.com`. | 2026-10-07 |
| Chequeo externo de disponibilidad sobre la API y la página de inicio. | No se hace. Si el VPS se cae, no hay aviso. | 2026-10-07 |
| Página de Juego Responsable (`/legal/juego-responsable`), exigida por §0 del documento de arquitectura. | Descartada por decisión del usuario: no se construye. Los documentos legales son cuatro (términos, datos, reembolsos, cookies). | 2026-10-08 |
| `GET /admin/users` devolvía todas las cuentas y el acceso se cambiaba con un desplegable, sin dejar rastro. | `/admin/usuarios` pagina, busca y filtra en el servidor; cada cambio de acceso pide un motivo y queda en la bitácora. | Fase 4, paso 3 |
| El registro pedía correo y contraseña. | Exige además aceptar los términos y la política de datos vigentes y declarar la mayoría de edad. | Fase 4, paso 2 |

---

## 5. Lo que se construye ahora: Fase 4

Especificación completa en `PLATAFORMA_COMPLETA.md`. No toca el motor. El orden pone primero lo que bloquea cobrar, y no se avanza a un paso sin que el anterior tenga tests o una verificación manual funcionando.

| # | Paso | Detalle | Estado |
|---|---|---|---|
| 0 | Preparación del stack: actualización de Next.js y React, CI, generador de tipos, IP real tras el proxy, Playwright, GlitchTip | §13 | **Cerrado el 2026-10-07.** Construido y en `main` el 2026-10-06; GlitchTip instalado y comprobado el 2026-10-07 (ver abajo) |
| 1 | Correo, verificación, restablecimiento de contraseña, revocación de sesiones | §5 | **Cerrado el 2026-10-07.** Construido el 2026-10-06 (rama `fase-4-paso-1-correo`); correo real encendido con Resend sobre `correo.sebasanalisis.com` y comprobado por el usuario con una cuenta nueva: registro, restablecimiento y aviso de cuenta eliminada (ver `DESPLIEGUE.md`, "Correo"). Queda anotado: en Hotmail el correo llegó a no deseado |
| 2 | Legal: documentos versionados, consentimientos, páginas públicas, onboarding | §6 | **Construido el 2026-10-08** (rama `fase-4-paso-2-legal`), con tests de backend y de punta a punta (ver abajo). Los textos son borradores: la revisión del abogado y los datos del responsable bloquean el lanzamiento, no este paso |
| 3 | Modelo de acceso (`has_access`, `RequireAccess`) y bitácora de auditoría | §2, §4.6 | **Construido el 2026-10-08** (rama `fase-4-paso-3-acceso`), con los tests de §2.4 y de punta a punta (ver abajo) |
| 4 | Planes y cupones, cálculo de precios, página de planes | §3.2, §3.3, §3.11, §4.4, §4.5 | **Construido el 2026-10-09** (rama `fase-4-paso-4-planes`), con tests de backend y de punta a punta (ver abajo). No cobra: eso es el paso 5 |
| 5 | Wompi: alta, webhook, renovación automática, cancelación, cambio de tarjeta, página de cuenta | §3 | Pendiente |
| 6 | Admin dashboard completo por secciones | §4 | Pendiente |
| 7 | Generalización multijuego, con dados como fixture de test | §7 | Pendiente |
| 8 | Base para apuestas deportivas: solo estructura y preguntas respondidas | §8 | Pendiente |
| 9 | Lanzamiento comercial | §9, párrafo final | Pendiente |

### Paso 0: qué quedó hecho

Construido en la rama `fase-4-paso-0-stack` y mezclado a `main` (2026-10-06):

- Next.js 16.3.8 y React 19.3.0; `npm audit --omit=dev` sin vulnerabilidades. Next 16 retiró `next lint`: el script `lint` llama a ESLint.
- FastAPI 0.142.2, PyJWT 2.15.1 y python-multipart 0.0.32; `pip-audit` sin vulnerabilidades conocidas. No estaba en la lista original: lo exigió el `pip-audit` del CI.
- IP real del cliente tras el proxy (`--proxy-headers`, `FORWARDED_ALLOW_IPS`), con tests del rate limit de login.
- Tipos del cliente API generados (`npm run gen:types`); `lib/types/` reexporta. Los schemas heredan de `ApiModel`.
- CI en GitHub Actions: backend, frontend y punta a punta. Incluye `ruff` sobre todo el backend y `mypy` estricto sobre `app/engine/`.
- Playwright con el test de humo.
- `sentry-sdk` y `@sentry/nextjs` con el filtro de datos sensibles, apagados sin DSN.

La lista "Fase 0 hecha cuando" de `PLATAFORMA_COMPLETA.md` §13.5 quedó completa el 2026-10-07: GlitchTip está instalado en `errores.sebasanalisis.com`, y un error provocado en la API y otro en el frontend aparecieron cada uno en su proyecto, con su correo de alerta (prueba manual del usuario; el detalle de la instalación está en `DESPLIEGUE.md`).

El chequeo externo de disponibilidad que pedía §13.6 **no se hace** (decidido por el usuario el 2026-10-07). Se acepta que, si el VPS entero se cae, GlitchTip se cae con él y nadie recibe aviso.

Ya comprobado: CI en verde en `main` (commit `cf456bb`, 2026-10-06) y rate limit de login con dos IP detrás del proxy real de Dokploy, con `FORWARDED_ALLOW_IPS` puesto (prueba manual del usuario, 2026-10-06).

Quedó sin hacer, a propósito: las dos reglas nuevas de `react-hooks` que marcan `lib/session.tsx` y los formularios están como advertencia en `eslint.config.mjs`; y `npm audit` completo (con dependencias de desarrollo) sigue reportando avisos altos por la cadena de Tailwind 3, que solo se cierran migrando a Tailwind 4.

### Paso 2: qué quedó hecho

Construido el 2026-10-08 en la rama `fase-4-paso-2-legal`. El detalle y las decisiones de implementación están en `PLATAFORMA_COMPLETA.md` §6.7.

- Tablas `legal_documents` y `user_consents`, y `users.adult_confirmed_at` y `users.onboarding_completed_at`. Dos migraciones: el DDL, y aparte la que publica la versión 1 de los cuatro documentos.
- Los cuatro documentos (términos, datos, reembolsos, cookies) como **borradores**, marcados como tales en su primer párrafo y con lo que depende de un abogado señalado en el propio texto.
- `/admin/legal`: borrador en Markdown con vista previa; publicar lo congela.
- Páginas públicas `/legal/terminos`, `/legal/privacidad`, `/legal/reembolsos` y `/legal/cookies`, y pie con esos enlaces en todas las pantallas.
- Registro con tres casillas obligatorias; el servidor rechaza el registro sin ellas y guarda un consentimiento por documento con IP y navegador.
- **`core/access.py` nace en este paso** (adelantado del paso 3, confirmado por el usuario), solo con la regla de consentimiento: `RequireAccess` ya está en todos los routers de juego y responde `403 consent_required`. El paso 3 agrega las demás reglas en esa misma función.
- Onboarding scroll-to-accept la primera vez que se entra a la mesa.
- `GET /auth/me/export` y, en `/cuenta`, los documentos aceptados y la descarga de los datos.

Las cuentas que ya existían no reciben consentimientos por migración: se les piden, junto con la mayoría de edad, la próxima vez que entren a la mesa. Incluye a los administradores.

Comprobado: 628 tests de backend, entre ellos "registro sin consentimientos → rechazado", "versión nueva → re-aceptación" y el que recorre todos los routers de juego; 16 tests de Playwright, entre ellos registro con las casillas, página legal pública, onboarding y re-aceptación tras publicar desde `/admin/legal`.

Quedó para después, a propósito: la fila de `admin_audit_log` al publicar un documento (la tabla es del paso 3) y la sección de pagos de la exportación (paso 5).

### Paso 3: qué quedó hecho

Construido el 2026-10-08 en la rama `fase-4-paso-3-acceso`. El detalle está en `PLATAFORMA_COMPLETA.md` §2.5.

- `has_access` con todas las reglas de §2.2 menos la de juego incluido en el plan (paso 7): cuenta suspendida, consentimiento, administrador, acceso `full`, acceso `invited` con vencimiento, suscripción con el período vigente.
- `users.access_type` pasa a `none | invited | full`, con `access_expires_at` e `is_active`. Tres migraciones: DDL, backfill y retiro de `trial`. **Las cuentas `trial` pasaron a `invited` sin vencimiento.**
- `GET /auth/me` (y toda respuesta con la cuenta) trae `access: {granted, reason, until}`.
- `admin_audit_log`, escrito en la misma transacción que el cambio. Publicar un documento legal ya deja su fila.
- `/admin/usuarios` (adelantado del paso 6 por decisión del usuario): lista paginada con búsqueda y filtros, detalle de la cuenta, otorgar o retirar acceso y suspender o reactivar, todo con motivo. `/admin/auditoria` muestra la bitácora.
- Una cuenta sin acceso, con el acceso vencido o suspendida ve un aviso en lugar de la mesa. Era provisional: el paso 4 lo reemplazó por la página de planes.

**Efecto al desplegar:** toda cuenta nueva queda sin acceso hasta que un administrador le dé `invited` desde `/admin/usuarios`. Entre este paso y el 5 nadie entra por su cuenta (decisión del usuario).

Comprobado: 654 tests de backend, entre ellos los de §2.4 y el que recorre todos los routers de juego con una cuenta sin acceso; 18 tests de Playwright, entre ellos "cuenta sin acceso → no ve la mesa hasta que el administrador le da acceso" y "cuenta suspendida".

Ajustes hechos al probarlo el usuario (2026-10-08): el acceso manual no aplica a un administrador; un cambio que no cambia nada se rechaza; el seed no crea un segundo administrador y el único administrador activo no puede eliminar su cuenta; y el cambio de rol se adelantó del paso 6, porque sin él no había forma de nombrar otro administrador.

Quedó para después, a propósito: reenviar la verificación y forzar el restablecimiento desde el admin (paso 6); el filtro por estado de suscripción y la suscripción y los pagos en el detalle de la cuenta (paso 5); la navegación lateral del admin (paso 6).

### Paso 4: qué quedó hecho

Construido el 2026-10-09 en la rama `fase-4-paso-4-planes`. El detalle y las decisiones están en `PLATAFORMA_COMPLETA.md` §3.11.

- Tablas `plans`, `coupons`, `coupon_plans` y `coupon_redemptions`. Dos migraciones: el DDL, y aparte la que siembra el plan único (**Acceso Mensual**, 100.000 COP al mes).
- `backend/app/billing/pricing.py`, puro y con `mypy` estricto: `quote(plan, coupon, now)` con subtotal, descuento, total y moneda, o el motivo por el que el cupón no aplica. El porcentaje redondea hacia abajo.
- `GET /plans` (pública) y `POST /billing/quote` (con sesión). El cliente manda plan y código; un monto que mande se ignora. Límite de intentos en la cotización con código: 10 cada 15 minutos por cuenta y 30 por hora por IP.
- `/admin/planes` y `/admin/descuentos`: crear, editar, activar y desactivar, y ver las redenciones de un cupón. No hay borrado. Todo cambio pide motivo y deja fila en la bitácora.
- **Página `/planes`**, pública. La cuenta sin acceso o con el acceso vencido llega allí en lugar del aviso provisional del paso 3. Muestra un solo precio, `100.000 COP / mes`, y la nota de que el cobro es en pesos colombianos y el banco de quien paga con tarjeta de otro país convierte a su tasa. El botón "Suscribirme" está deshabilitado hasta el paso 5.
- No existe el cupón del 100 %: el porcentaje va de 1 a 99.

Comprobado: 809 tests de backend, entre ellos cada caso de cupón (vencido, agotado, de otro plan, ya usado por el usuario, de otra moneda, inactivo) y "un monto enviado por el cliente se ignora"; 24 tests de Playwright, entre ellos "cuenta sin acceso: ve /planes con el precio que se cobra". Las dos migraciones se subieron, se bajaron y se volvieron a subir sobre una base desechable, y `alembic check` no reporta diferencias con los modelos.

Quedó para después, a propósito: cobrar y redimir un cupón de verdad, el campo de cupón en la pantalla de pago, y `subscriptions.plan_id` como llave foránea (paso 5); `plan_games` (paso 7). La redacción del precio la revisa el abogado antes del lanzamiento.

### Decisiones tomadas para la Fase 4

- Cobro con renovación automática y fuente de pago tokenizada en Wompi, **y además pago manual mes a mes** para quien no tokeniza (2026-10-08).
- El público es internacional. Un solo plan, mensual, de 100.000 COP. Los cupones se mantienen (2026-10-08).
- Wompi es la pasarela principal y el paso 5 se construye detrás de una interfaz de proveedor. Premium Pay se evaluó y no sirve como base del cobro; queda como posible canal manual para clientes internacionales sin tarjeta (2026-10-08). Detalle en `PLATAFORMA_COMPLETA.md` §3.10.
- Correo transaccional con Resend por SMTP. El correo de soporte y de contacto es `sebas.analisis.ia.com@gmail.com` (2026-10-07); no hay buzón en Hostinger.
- Monitoreo de errores con GlitchTip autohospedado en el VPS, en `errores.sebasanalisis.com` desde el 2026-10-07.
- Tests de frontend de punta a punta con Playwright.
- Tipos del cliente API generados con `openapi-typescript`.
- Dominio `sebasanalisis.com`, en Hostinger junto con el VPS. Desde el 2026-10-07 la aplicación corre en `sebasanalisis.com` y `api.sebasanalisis.com`, con HTTPS.
- Resend en el plan gratuito (100 correos al día) mientras se construye, con `EMAIL_DAILY_LIMIT=80`; se pasa al plan Pro antes del lanzamiento comercial.
- El VPS tiene 8 GB de RAM (confirmado el 2026-10-06): alcanza para GlitchTip junto a la aplicación.
- No hay página de Juego Responsable (2026-10-08).
- Las cuentas `trial` pasan a `invited` sin vencimiento y sin correo de aviso; el administrador les retira el acceso a mano cuando exista el pago (2026-10-08).
- El paso 3 se despliega sin esperar al pago: las cuentas nuevas entran solo con acceso manual (2026-10-08).
- La pantalla de una cuenta sin acceso no muestra correo de contacto: solo dice que no tiene acceso activo y que las suscripciones estarán disponibles pronto (2026-10-08).
- `/admin/usuarios` con búsqueda, filtros, paginación y detalle se adelanta del paso 6 al 3 (2026-10-08).
- El cambio de rol (nombrar o quitar administradores) también se adelanta al paso 3. Al quitar el rol, la cuenta conserva el acceso manual que tenía guardado (2026-10-08).
- **Se muestra un solo precio: 100.000 COP.** El precio de referencia de 30 USD decidido el 2026-10-08 se descartó; el plan no guarda un precio de presentación. Bajo el precio queda la nota de que el cobro es en pesos colombianos y el banco de quien paga con tarjeta de otro país convierte a su tasa (2026-10-09).
- El plan único lo siembra una migración: código `mensual`, nombre **Acceso Mensual** (2026-10-09).
- No existe el cupón del 100 %: el porcentaje va de 1 a 99 y un cupón nunca deja el total en cero (2026-10-09).
- Mientras no exista el pago, `/planes` muestra el precio con el botón "Suscribirme" deshabilitado y sin campo de cupón (2026-10-09).
- Cotizar exige sesión; solo se cobra en COP; todo cambio de plan o cupón pide motivo; no hay borrado; el código de un cupón no se edita (2026-10-09).
- Las cuentas anteriores al paso 2 aceptan los documentos y declaran la mayoría de edad al volver a la mesa; no se les crean consentimientos por migración (2026-10-08).
- La versión 1 de los documentos legales se publica como borrador marcado; el texto del abogado entra como versión 2 y pide re-aceptación a todas las cuentas (2026-10-08).

### Pendiente del usuario

La lista completa, con la propuesta por defecto de cada una, está en `PLATAFORMA_COMPLETA.md` §10. Las que bloquean un paso:

| Decisión | Bloquea |
|---|---|
| Textos legales revisados por abogado: los cuatro publicados son borradores y lo dicen (retracto de la Ley 1480, conformidad con la Ley 1581, limitación de responsabilidad, jurisdicción, plazos de conservación). Datos del responsable del tratamiento y prestador del servicio: nombre o razón social, identificación y domicilio figuran como `[PENDIENTE]` (decisión del usuario del 2026-10-08: todavía no se ponen) | Lanzamiento |
| Pasar Resend al plan Pro y subir `EMAIL_DAILY_LIMIT` | Lanzamiento |
| Aviso por correo cuando se publica una versión nueva de un documento legal que exige aceptación (2026-10-08). Hoy solo se muestra la pantalla de aceptación al volver a entrar: quien no entra no se entera. Detalle en `PLATAFORMA_COMPLETA.md` §6.7 | Lanzamiento |
| Revisión del abogado del precio en pantalla (100.000 COP): si debe decir que incluye impuestos y si aplica IVA, y qué ley de consumo aplica a clientes de fuera de Colombia (`PLATAFORMA_COMPLETA.md` §3.11) | Lanzamiento |
| Cuenta de comercio en Wompi (sandbox y producción); confirmación escrita de Wompi de que acepta esta categoría de negocio y tarjetas internacionales; qué medios se habilitan para el pago manual; facturación electrónica | Paso 5 |

---

## 6. Fuera de alcance

No se construye hasta que el usuario lo pida explícitamente:

- **Señales avanzadas del motor**: transición condicional, k-gramas, ciclo, señales de pleno, fusión multi-señal (`ARQUITECTURA_Y_ESTADISTICA.md` §2.9). Entran una por una.
- **Builder visual de categorías** en el admin. Se usa formulario estructurado.
- **Juego de dados como producto.** En la Fase 4 entra solo como fixture de test de genericidad.
- **Apuestas deportivas.** La Fase 4 reserva la estructura; el diseño espera las respuestas de `PLATAFORMA_COMPLETA.md` §8.3.
- **Cambio de plan en caliente** (mensual ↔ anual) y reembolsos por API.
- **Exportar CSV**, migración de datos locales, notificaciones.
- **Cualquier IA, OCR o lectura de imágenes.** Descartado, no pospuesto.
