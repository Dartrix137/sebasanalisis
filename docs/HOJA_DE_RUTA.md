# Sebasanálisis — Hoja de ruta

> Punto de entrada a la documentación. Dice qué es el producto hoy, qué se construyó, qué decisiones cambiaron por el camino y qué se construye ahora. No define reglas ni fórmulas: apunta al documento que las define.
>
> **Se actualiza cada vez que se cierra un paso o se toma una decisión de rumbo.** Última actualización: 2026-10-15 (ajustes de la mesa y del admin).

---

## 1. El producto hoy

Sebasanálisis es una plataforma web por suscripción. El usuario registra a mano los números que salen en una mesa de ruleta y, después de cada giro, la plataforma le entrega **una recomendación** para el giro siguiente (qué apostar, o no apostar), con un Signal Score de 0 a 100, su banda, y el monto que pide cada gestión de banca.

La recomendación sale de reglas estadísticas sobre los resultados registrados. **No es una predicción**: cada giro es independiente y ninguna gestión de banca cambia la ventaja de la casa. Esa regla de lenguaje es la más importante del proyecto (`ARQUITECTURA_Y_ESTADISTICA.md` §0).

**Dónde está:** el núcleo (motor, mesa de ruleta, admin básico) está construido y aprobado. Desde el paso 3 de la Fase 4 la mesa exige acceso, y desde el paso 5 (cerrado el 2026-10-13) una cuenta nueva lo obtiene suscribiéndose con Wompi o por acceso manual de un administrador. **El VPS cobra todavía contra el sandbox de Wompi**: con las llaves de prueba cualquiera obtiene acceso con una tarjeta de prueba, sin que se mueva dinero. Antes de abrir al público hay que pasar a las llaves de producción (`DESPLIEGUE.md`).

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
| Varios planes (mensual y anual). | Dos planes: mensual de 100.000 COP y de dos meses de 150.000 COP (el 2026-10-08 se había decidido uno solo). Se muestra y se cobra solo en COP. | 2026-10-09 |
| Mostrar además un precio fijo de 30 USD, solo visual (2026-10-08). | No se muestra: un solo precio, el que se cobra. | 2026-10-09 |
| Buzón de soporte en Hostinger sobre el dominio (`soporte@sebasanalisis.com`). | El correo de soporte y de contacto es una cuenta de Gmail: `sebas.analisis.ia.com@gmail.com`. | 2026-10-07 |
| Chequeo externo de disponibilidad sobre la API y la página de inicio. | No se hace. Si el VPS se cae, no hay aviso. | 2026-10-07 |
| Página de Juego Responsable (`/legal/juego-responsable`), exigida por §0 del documento de arquitectura. | Descartada por decisión del usuario: no se construye. Los documentos legales son cuatro (términos, datos, reembolsos, cookies). | 2026-10-08 |
| `GET /admin/users` devolvía todas las cuentas y el acceso se cambiaba con un desplegable, sin dejar rastro. | `/admin/usuarios` pagina, busca y filtra en el servidor; cada cambio de acceso pide un motivo y queda en la bitácora. | Fase 4, paso 3 |
| El registro pedía correo y contraseña. | Exige además aceptar los términos y la política de datos vigentes y declarar la mayoría de edad. | Fase 4, paso 2 |
| Un juego nuevo de resultados discretos se crearía completo desde el admin, sin escribir código (`PLATAFORMA_COMPLETA.md` §7.3). | El producto sale solo con la ruleta. Cada juego futuro tendrá su propio motor, escrito en código, y entrará como un módulo nuevo. El alta de juegos y de variantes del admin queda oculta, no borrada. | 2026-10-14 |
| La primera recomendación salía con 10 números registrados (la ventana más corta). | Sale con 11, y el formulario de mesa nueva lo avisa antes de abrir. | 2026-10-15 |
| Las apuestas de la sesión se contaban por casilla, y el porcentaje de ganadas solo se veía al cerrar. | Se cuentan por giro, con lo esperable por azar al lado, el resultado neto, el mejor momento y la peor caída, también con la mesa abierta. | 2026-10-15 |
| La ficha de un usuario en el admin repetía las acciones sobre su suscripción. | Las acciones viven solo en `/admin/suscripciones`; la ficha resume y enlaza. | 2026-10-15 |
| La tarjeta se escribía en el widget de Wompi, en modo tokenización. | Se escribe en un formulario propio que la tokeniza contra la API de Wompi, cifrada, desde el navegador. Nequi se tokeniza por la API. La llave de cifrado la pide el backend, porque Wompi no deja pedirla desde el navegador. Construido y probado a mano contra el sandbox el 2026-10-19. | 2026-10-19 |

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
| 5 | Wompi: alta, webhook, renovación automática, cancelación, cambio de tarjeta, página de cuenta | §3, §3.12 | **Cerrado el 2026-10-13**, en tres entregas. Entrega 1 (alta con pago manual, webhook y reconsulta) construida el 2026-10-13 en la rama `fase-4-paso-5a-alta-y-webhook`, con tests, y mezclada y desplegada ese día; pagos de prueba aprobados en el sandbox de Wompi, en local y en el VPS, con el webhook recibiendo eventos reales (ver abajo). Entrega 2 (tokenización y renovación automática, con cancelar y reanudar) construida el 2026-10-13 en la rama `fase-4-paso-5b-renovacion`, con los doce casos de §3.9 en verde y probada con tarjeta contra el sandbox (falta Nequi). Entrega 3 (cambiar el medio de pago, pasar de un modo al otro, borrado y exportación de la cuenta con pagos) construida el 2026-10-13 en la rama `fase-4-paso-5c-cuenta-y-cierre` y probada contra el sandbox. El job de renovaciones quedó programado en Dokploy ese día. El usuario desplegó la entrega 3, la probó en el VPS y dio el paso por cerrado. **Sigue con llaves de sandbox**: el paso a producción está en `DESPLIEGUE.md`. Las acciones del admin sobre suscripciones y pagos son del paso 6 |
| 6 | Admin dashboard completo por secciones | §4, §4.8, §4.9, §4.10 | **Cerrado el 2026-10-14.** Entrega 1 (suscripciones y pagos en el admin) construida el 2026-10-14 en la rama `fase-4-paso-6a-suscripciones-y-pagos` y mezclada ese día (PR #17). Entrega 2 (navegación lateral, resumen, `/admin/juegos` y `/admin/motor`, forzar el restablecimiento y reenviar la verificación) construida el 2026-10-14 en la rama `fase-4-paso-6b-navegacion-y-resumen` y mezclada ese día (PR #18). Entrega 3 (traslado de un precio nuevo a las suscripciones vigentes) construida el 2026-10-14 en la rama `fase-4-paso-6c-traslado-de-precio`, con tests (ver abajo), y mezclada ese día (PR #19). Con ella quedó construido todo el paso. El usuario desplegó la entrega 3 y la probó en el VPS el 2026-10-14 con un plan de prueba: una subida con su aviso, la cancelación del traslado y una bajada, con los avisos enviados por el job y correo real. Dio el paso por cerrado ese día |
| 7 | Generalización multijuego, con dados como fixture de test | §7, §7.7, §7.8, §7.9 | **Cerrado el 2026-10-14.** Entrega 1 (backend y admin: metadatos del juego, registro de módulos, `plan_games` y la regla n.º 7 de `has_access` con `403 game_not_in_plan`, juegos por plan en `/admin/planes`, campos nuevos en `/admin/juegos`, fixture de dados por la API) construida el 2026-10-14 en la rama `fase-4-paso-7a-multijuego-backend`, con tests, y mezclada ese día (PR #21). Entrega 2 (la mesa en `/juegos/[slug]/mesa/[sessionId]` con la redirección de la ruta vieja, `components/mesa/*`, el teclado desde `possible_outcomes` y la pista `display`, el menú de juegos, la página de cada juego, los juegos incluidos en `/planes` y el fixture de dados en Playwright) construida el 2026-10-14 en la rama `fase-4-paso-7b-mesa-y-menu`, con tests, y mezclada ese día (PR #22). Ese mismo día el usuario decidió salir solo con la ruleta y dejar los juegos futuros para código (§7.9; el alta de juegos del admin quedó oculta, PR #23). El usuario lo desplegó y lo probó en el VPS el 2026-10-14 y dio el paso por cerrado |
| 8 | Base para apuestas deportivas: solo estructura y preguntas respondidas | §8, §8.4 | **Documentado el 2026-10-15** (rama `fase-4-paso-8-deportivas`), sin código. Las siete preguntas de §8.3 respondidas en §8.4; la fuente de datos y el marco regulatorio quedan pendientes (§10 n.º 13 y 14) y bloquean construir y sacar deportes, no el lanzamiento de la ruleta. Los espacios de nombres quedan reservados solo en el documento. Ver abajo |
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

- Tablas `plans`, `coupons`, `coupon_plans` y `coupon_redemptions`. Tres migraciones: el DDL, y aparte las dos que siembran los planes: **Acceso Mensual** (100.000 COP al mes) y **Acceso Bimestral** (150.000 COP cada dos meses).
- `backend/app/billing/pricing.py`, puro y con `mypy` estricto: `quote(plan, coupon, now)` con subtotal, descuento, total y moneda, o el motivo por el que el cupón no aplica. El porcentaje redondea hacia abajo.
- `GET /plans` (pública) y `POST /billing/quote` (con sesión). El cliente manda plan y código; un monto que mande se ignora. Límite de intentos en la cotización con código: 10 cada 15 minutos por cuenta y 30 por hora por IP.
- `/admin/planes` y `/admin/descuentos`: crear, editar, activar y desactivar, y ver las redenciones de un cupón. No hay borrado. Todo cambio pide motivo y deja fila en la bitácora.
- **Página `/planes`**, pública. La cuenta sin acceso o con el acceso vencido llega allí en lugar del aviso provisional del paso 3. Muestra un solo precio, `100.000 COP / mes`, y la nota de que el cobro es en pesos colombianos y el banco de quien paga con tarjeta de otro país convierte a su tasa. El botón "Suscribirme" está deshabilitado hasta el paso 5.
- No existe el cupón del 100 %: el porcentaje va de 1 a 99.

Comprobado: 810 tests de backend, entre ellos cada caso de cupón (vencido, agotado, de otro plan, ya usado por el usuario, de otra moneda, inactivo) y "un monto enviado por el cliente se ignora"; 24 tests de Playwright, entre ellos "cuenta sin acceso: ve /planes con el precio que se cobra". Las tres migraciones se subieron, se bajaron y se volvieron a subir sobre una base desechable, y `alembic check` no reporta diferencias con los modelos.

Quedó para después, a propósito: cobrar y redimir un cupón de verdad, el correo de aviso antes de cada cobro, el campo de cupón en la pantalla de pago, y `subscriptions.plan_id` como llave foránea (paso 5); `plan_games` (paso 7). La redacción del precio la revisa el abogado antes del lanzamiento.

### Paso 5, entrega 1: qué quedó hecho

Construido el 2026-10-13 en la rama `fase-4-paso-5a-alta-y-webhook`. El detalle y las decisiones están en `PLATAFORMA_COMPLETA.md` §3.12. **El paso 5 no está cerrado**: faltan las entregas 2 y 3.

- Interfaz `PaymentProvider` (`backend/app/payments/`), con la implementación de Wompi, una pasarela simulada para desarrollo y Playwright, y el estado "sin configurar" cuando no hay llaves.
- `subscriptions` ampliada (plan como llave foránea, precio y moneda congelados, cupón, períodos, `renewal_mode`), tabla `payments`, y `payment_events` con suscripción opcional y `payment_id`. Tres migraciones: DDL, datos y cierre. **Una cuenta no puede tener dos suscripciones `pending`, `active` o `past_due`**: lo impide un índice único de la base.
- `POST /billing/subscriptions`: abre el pago manual de un período y devuelve el enlace al Web Checkout de Wompi. Exige correo confirmado y documentos aceptados; el total sale de `billing/pricing.quote`.
- `POST /webhooks/wompi`: verifica la firma, guarda todo evento, reconsulta la transacción contra Wompi y solo con esa respuesta mueve la suscripción. `GET /billing/payments/:id` pasa por la misma función.
- El pago aprobado activa la suscripción, fija `current_period_end`, registra la redención del cupón y sube su contador. Correos de bienvenida y de recibo.
- `/planes` con el botón funcionando, `/planes/pagar` con cupón y total del servidor, y `/pago/:id`, que espera el resultado.
- Variables `WOMPI_*` en `.env.example` y en `DESPLIEGUE.md`. La API registra al arrancar contra qué ambiente de Wompi quedó, y no arranca con llaves incompletas o mezcladas.

**Efecto al desplegar:** ninguno para el usuario mientras no se pongan las llaves de Wompi; `/planes` sigue con el botón apagado. Las tres migraciones corren solas.

Comprobado: de los doce casos de §3.9, los ocho de esta entrega (firma inválida, evento duplicado, transacción declinada, suscripción vencida, reconsulta que contradice al evento, referencia desconocida, monto enviado por el cliente y cupón rechazado con motivo), más "cuenta sin correo confirmado no puede suscribirse" y "un pago aprobado registra una sola redención"; y en Playwright, "una cuenta sin acceso se suscribe con la pasarela simulada y entra a la mesa". Las migraciones se subieron, se bajaron y se volvieron a subir sobre una base desechable, con filas viejas puestas a mano.

**Prueba contra el sandbox (2026-10-13, en local, con las llaves que puso el usuario):** un pago de prueba aprobado de punta a punta. Wompi aceptó la firma de integridad, devolvió al cliente con el id de la transacción, y la reconsulta activó la suscripción y envió los correos. **Prueba en el VPS (2026-10-13, llaves de sandbox):** dos pagos aprobados por la interfaz; el webhook de Wompi llegó y respondió `200` las dos veces, la pantalla mostró "Pago aprobado" y llegaron los correos. **Falta:** un pago rechazado y un medio que no responde de inmediato (PSE o Nequi). Detalle en `DESPLIEGUE.md`, "Pagos con Wompi".

**Entrega corta (2026-10-13, rama `fase-4-paso-5a2-suscripcion-en-cuenta-y-admin`)**, adelantada de la entrega 3 por decisión del usuario; detalle en `PLATAFORMA_COMPLETA.md` §3.13. Todo de solo lectura: `/cuenta` muestra la suscripción y el historial de pagos; `/admin/usuarios` filtra por suscripción (vigente, vencida, pago sin completar, nunca abrió un pago) y muestra la suscripción y los pagos de cada cuenta; el formulario de acceso manual explica qué hace sobre una cuenta que paga; y `/planes` deja de ofrecer un pago que el servidor rechazaría.

Quedó para después, a propósito: tokenización, renovación automática, estados `past_due` y `expired`, avisos antes del cobro y el descuento de los cupones `repeating` en las renovaciones (entrega 2); cancelar, cambiar el medio de pago, `/cuenta`, el admin de suscripciones y pagos, eliminar la cuenta con pagos y la prueba en el sandbox (entrega 3).

### Paso 5, entrega 2: qué quedó hecho

Construido el 2026-10-13 en la rama `fase-4-paso-5b-renovacion`. El detalle y las decisiones están en `PLATAFORMA_COMPLETA.md` §3.14. **El paso 5 no está cerrado**: falta la entrega 3.

- **Renovación automática** con una tarjeta o un Nequi guardados. El cliente los escribe en la ventana de Wompi; a la aplicación solo llega un token, y solo se guardan la referencia de Wompi, la marca y los últimos cuatro dígitos.
- La pantalla de pago deja elegir entre **pago manual** y **renovación automática**, sin ninguno marcado.
- `backend/app/billing/schedule.py` (puro): intentos de cobro a 48 h, 24 h y 0 h antes del vencimiento, y avisos 7 días antes.
- `backend/scripts/run_renewals.py`: el job que avisa, cobra, reintenta y deja vencidas las suscripciones. Idempotente por un candado de Postgres y por una referencia por (suscripción, período, intento).
- Estados `past_due` (conserva el acceso hasta el fin del período) y `expired` (sin período de gracia).
- Correos: aviso antes de cada cobro, período por vencer en el pago manual, cobro fallido, suscripción vencida y renovación cancelada.
- El cupón `repeating` descuenta un período en cada renovación aprobada, también en el pago manual del período siguiente.
- **Cancelar y reanudar** la renovación desde `/cuenta` (adelantado de la entrega 3: no se enciende un cobro que el cliente no pueda detener).

**Al desplegar hay que programar el job** (`DESPLIEGUE.md`, "Job de renovaciones"). Sin él no se cobra ninguna renovación ni salen los avisos.

Comprobado: los doce casos de §3.9 en verde (los cuatro que faltaban: dos corridas sobre el mismo período, cancelación, precio congelado y tres intentos fallidos); renovación automática de punta a punta en Playwright con la pasarela simulada; la migración subida, bajada y vuelta a subir en una base desechable; y el script del job corrido allí, también con el candado tomado.

**Prueba contra el sandbox (2026-10-13, en local):** el usuario guardó la tarjeta de prueba en el widget de Wompi y el primer cobro quedó aprobado; el job, con el vencimiento adelantado en la base de la prueba, avisó, cobró a la tarjeta guardada y extendió el período; la tarjeta que Wompi rechaza no dio acceso. De ahí salieron dos cosas: la marca de la tarjeta viene en la transacción y no en la fuente de pago (corregido), y el widget solo tokeniza desde https o `localhost`. **Sin probar:** Nequi y tarjetas con 3D Secure. El detalle está al final de §3.14.

### Paso 5, entrega 3: qué quedó hecho

Construido el 2026-10-13 en la rama `fase-4-paso-5c-cuenta-y-cierre`. El detalle está en `PLATAFORMA_COMPLETA.md` §3.15.

- **Cambiar el medio de pago** de una renovación automática desde `/cuenta`. No cobra nada; si la suscripción tenía un cobro sin aprobar, lo reintenta de inmediato con el medio nuevo.
- **Pasar de un modo al otro** sobre la misma suscripción y sin perder el período: de pago manual a renovación automática (guardando un medio de pago, sin cobro), y de automática a pago manual (se borra la referencia del medio de pago).
- **Reanudar una renovación cancelada con otro medio de pago.**
- **Eliminar la cuenta con pagos**: la suscripción se borra (eso cancela la renovación), los pagos quedan sin cuenta, sus eventos se reducen a lo que explica el pago, y el uso de un cupón queda sin cuenta (`coupon_redemptions.user_id` pasó a `SET NULL`). Con un cobro en proceso no se elimina todavía.
- **Exportar los datos** trae la suscripción y los pagos.
- Correos: cambio del medio de pago y paso a pago manual.

Lo que el encargo del paso 5 listaba en la entrega 3 y ya había entrado antes: cancelar y reanudar y el correo de cancelación (entrega 2); la suscripción y los pagos en `/cuenta` y en el detalle del admin, y el filtro por suscripción (entrega corta).

Comprobado: los tests de `tests/api/test_subscription_changes.py`; tres recorridos nuevos en Playwright; la migración subida, bajada y vuelta a subir en una base desechable; y la prueba contra el sandbox que está al final de §3.15.

El usuario probó además en `/cuenta`, con la ventana de Wompi, las acciones nuevas con tarjeta y con Nequi, y un cobro a Nequi rechazado y otro aprobado (§3.15).

Mezclada y desplegada el 2026-10-13 (PR #14); el usuario la probó en el VPS y dio el paso 5 por cerrado ese día.

**Sin probar:** tarjetas con 3D Secure, y un cobro con llaves de producción. **Fuera del paso 5:** las acciones del admin sobre suscripciones y pagos (paso 6).

### Decisiones tomadas para la Fase 4

- **Tokenización con un formulario propio (2026-10-19), construida ese día en la rama `fase-4-tokenizacion-formulario-propio`** (detalle en `PLATAFORMA_COMPLETA.md` §3.16, "Cómo quedó construido"). Al construir, el endpoint de la llave de cifrado de Wompi resultó no admitir llamadas desde el navegador: el usuario decidió que esa llave la pida el backend (`GET /billing/card-encryption-key`); la tarjeta sigue yendo cifrada del navegador directo a Wompi. El JWE lo arma `jose` 6.2.12 (decisión del usuario). Tests de backend y de Playwright en verde. **Probado a mano contra el sandbox ese día**: alta con tarjeta en `/planes/pagar`, y en `/cuenta` el ciclo de mora completo (tarjeta que rechaza, Nequi que rechaza, Nequi que aprueba con el reintento inmediato); el usuario lo dio por bueno. Motivo de la decisión: en la ventana del widget de Wompi los medios de pago se ven deshabilitados aunque funcionan, no se puede corregir desde nuestra página, y abrirlo en modo tokenización por JavaScript no está documentado. La tarjeta pasa a un formulario nuestro que la manda cifrada directo a Wompi (`POST /v1/tokens/cards`), y Nequi se tokeniza por la API (`POST /v1/tokens/nequi`, esperando la aprobación en la app). La fuente de pago, el cobro y el job no cambian. Queda por preguntarle a Wompi qué exige PCI DSS con la tarjeta escrita en nuestra página. Detalle en `PLATAFORMA_COMPLETA.md` §3.16.
- **Ajustes de la mesa y del admin (2026-10-15)**, pedidos por el usuario tras la revisión de lanzamiento:
  - **11 números para la primera recomendación** (`MIN_SPINS_FOR_SIGNAL`, antes 10). El formulario de mesa nueva lo avisa: tomarlos del historial de la mesa y, si la mesa obliga a apostar para ver un giro, apostar solo el mínimo que acepte la casa. Detalle en `ARQUITECTURA_Y_ESTADISTICA.md` §2.10. A revisar con el abogado: la frase le pide al cliente apostar dinero real antes de usar la herramienta.
  - **"Apuestas de esta sesión" cuenta por giro**, con lo esperable por azar con esas mismas apuestas al lado (regla de §2): "Giros con ganancia 29 de 66 · 43.9 %" va junto a, por ejemplo, "Lo esperable por azar 45.1 %". Suma el resultado neto, el mejor momento y la peor caída, y el resumen al cerrar usa las mismas cifras. No se llama "efectividad": describe lo que pasó, no una capacidad del motor (`engine/session_stats.py`).
  - **Usuarios y Suscripciones siguen siendo dos secciones del admin**: una responde quién es la persona y la otra filtra por estado, plan y modo. Lo repetido eran las acciones: la ficha del usuario ya no las tiene y enlaza a `/admin/suscripciones?query=<correo>`, que abre con el detalle desplegado.
  - **Al llegar al límite de pérdida** (pregunta, sin cambio): la mesa deja de aceptar apuestas, pero se pueden seguir anotando números y deshacer el último. El límite no se sube con la sesión abierta; para volver a apostar hay que abrir otra mesa.
- **Un período se cobra con un solo precio (2026-10-15)**: los tres intentos del cobro automático de un período van con el precio que corre en el primero, el mismo que dice el aviso de 7 días; una subida que empieza a correr entre intentos queda para el período siguiente, y una bajada sí alcanza al reintento. `/cuenta`, el admin y el correo de la subida dicen desde qué cobro se paga el precio nuevo. Salió de una prueba en el VPS (bajada a 99.000 y vuelta a 100.000). Detalle en `PLATAFORMA_COMPLETA.md` §4.10.
- **Solo la ruleta, y juegos futuros escritos en código (2026-10-14)**: crear un juego desde cero en el admin resultó difícil de hacer bien. La configuración tiene que describir resultados equiprobables (la suma de dos dados no lo es, y Baccarat tampoco), y la martingala y los dos sectores están pensados para los pagos de la ruleta (1:1 y 2:1). El producto se lanza con la ruleta. Cada juego que venga tendrá su motor propio, como un módulo nuevo del registro de módulos. En `/admin/juegos` se ocultan "Nuevo juego" y "+ Variante" (interruptor `ALTA_DE_JUEGOS`) para poder volver a abrirlos en una versión futura; la API de alta se conserva. **La martingala se deja como está**: se sigue ofreciendo también sobre una docena o una columna (2:1), con el monto calculado con el pago real.
- **Logo (2026-10-13)**: el hexágono dorado que entregó el usuario reemplaza al círculo amarillo en el login, los encabezados, el icono de la pestaña y los correos. El original (`docs/design/logo-original.webp`) es dorado sobre negro, sin transparencia; `frontend/scripts/make-logo.mjs` le quita el fondo y genera los archivos. El texto del logo dice "Análisis Sebastián" y el producto se llama "Sebasanálisis": se usa solo el hexágono, con el nombre escrito al lado como antes. Los correos cargan el logo desde `<FRONTEND_BASE_URL>/logo-email.png`, así que el `Dockerfile` del frontend ahora copia `public`.
- **Paso 5, entrega 2 (2026-10-13)**: se pueden guardar tarjetas y Nequi; la tarjeta se escribe en el widget de Wompi; cancelar y reanudar entran en esta entrega; y en la pantalla de pago ningún modo entra marcado.

- **Wompi confirmó** que acepta esta categoría de negocio y tarjetas internacionales (lo informó el usuario el 2026-10-13). Las llaves de sandbox ya están en `backend/.env`.
- **El acceso manual sobre un suscriptor queda como está** (2026-10-13): Invitado o Completo pasan por encima de la suscripción y mientras duren no se le ofrece pagar; Sin acceso manual no le quita la mesa, para eso se suspende la cuenta. El formulario del admin lo explica.
- **Paso 5 (2026-10-13)**: el pago manual usa el Web Checkout de Wompi, con los medios que el comercio habilite en su panel; un pago hecho antes del vencimiento extiende desde el vencimiento; el modo de pago es `subscriptions.renewal_mode`; los dos planes se ofrecen en los dos modos; el aviso antes del cobro automático va 7 días antes; la nota de la tasa de cambio se repite en la pantalla de pago y en el recibo; al eliminar una cuenta se conservan sus pagos sin usuario; y en `/planes` un administrador o una cuenta con acceso manual no ve el botón de pago, mientras que un suscriptor ve su plan marcado como actual.

- Cobro con renovación automática y fuente de pago tokenizada en Wompi, **y además pago manual mes a mes** para quien no tokeniza (2026-10-08).
- El público es internacional. Los cupones se mantienen (2026-10-08).
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
- **Dos planes**: mensual de 100.000 COP (`mensual`, **Acceso Mensual**) y de dos meses de 150.000 COP (`bimestral`, **Acceso Bimestral**). El de dos meses es un plan aparte, no un cupón. Los siembran migraciones (2026-10-09).
- **Aviso por correo antes de cada cobro automático**, con el monto y la fecha, que remite al apartado de suscripción del perfil para dudas o para gestionarla. Se construye en el paso 5; los días de anticipación están por definir (2026-10-09).
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
| Preguntarle a Wompi qué exige (PCI DSS) con la tarjeta escrita en un formulario de nuestra página (`PLATAFORMA_COMPLETA.md` §3.16 y §10 n.º 15) | Lanzamiento |
| Aviso por correo cuando se publica una versión nueva de un documento legal que exige aceptación (2026-10-08). Hoy solo se muestra la pantalla de aceptación al volver a entrar: quien no entra no se entera. Detalle en `PLATAFORMA_COMPLETA.md` §6.7 | Lanzamiento |
| Revisión del abogado del precio en pantalla (100.000 COP): si debe decir que incluye impuestos y si aplica IVA, y qué ley de consumo aplica a clientes de fuera de Colombia (`PLATAFORMA_COMPLETA.md` §3.11) | Lanzamiento |
| Pasar el VPS de las llaves de sandbox a las de producción antes de abrir al público (con las de sandbox, cualquier cuenta obtiene acceso con la tarjeta de prueba). Cuenta de comercio en Wompi: llaves de sandbox ya puestas en Dokploy y en `backend/.env`, y la URL de eventos en su panel (`DESPLIEGUE.md`, "Pagos con Wompi"). Qué medios de pago se habilitan en el panel de Wompi. Facturación electrónica | Cierre del paso 5 (la entrega 1 se construyó sin llaves) |

---

## 6. Fuera de alcance

No se construye hasta que el usuario lo pida explícitamente:

- **Señales avanzadas del motor**: transición condicional, k-gramas, ciclo, señales de pleno, fusión multi-señal (`ARQUITECTURA_Y_ESTADISTICA.md` §2.9). Entran una por una.
- **Builder visual de categorías** en el admin. Se usa formulario estructurado.
- **Juego de dados como producto.** En la Fase 4 entra solo como fixture de test de genericidad.
- **Apuestas deportivas.** Las respuestas a `PLATAFORMA_COMPLETA.md` §8.3 están en §8.4 (paso 8). Para construirlas faltan el proveedor de datos y el concepto del abogado (§10 n.º 13 y 14), y salen solo si el backtest supera al mercado.
- **Cambio de plan en caliente** (mensual ↔ anual) y reembolsos por API.
- **Exportar CSV**, migración de datos locales, notificaciones.
- **Cualquier IA, OCR o lectura de imágenes.** Descartado, no pospuesto.

### Paso 6, entrega 1: qué quedó hecho

Construido el 2026-10-14 en la rama `fase-4-paso-6a-suscripciones-y-pagos`. El detalle y las decisiones están en `PLATAFORMA_COMPLETA.md` §4.8. **El paso 6 no está cerrado.**

- `/admin/suscripciones`: lista paginada con filtros en el servidor (estado, plan, modo, correo), detalle con pagos y bitácora, y tres acciones con motivo: **extender** el período (sin cobrar; en la renovación automática se corren el cobro y su aviso), **cancelar al final del período** y **cancelar de inmediato** (el acceso cae en el acto, no se devuelve nada). Al cliente le llega un correo en las tres.
- `/admin/pagos`: todos los cobros con filtros, la cadena de eventos de Wompi de cada uno (también los de firma inválida), **reconsultar en Wompi** (la misma función del webhook) y **registrar un reembolso** hecho en el panel de Wompi.
- **Un pago aprobado que Wompi anula después pierde su período**: si era el último, el acceso cae en el acto. Si ya hay un período posterior pagado, no se toca nada y queda la nota para revisarlo a mano.
- Las acciones sobre la suscripción también desde el detalle de la cuenta en `/admin/usuarios`, que muestra además la bitácora de su suscripción y sus pagos.
- Una migración, solo DDL: `payments.reversed_at`, `payments.reversal_note` y la tabla `payment_refunds`.

Decisiones del usuario (2026-10-14): la anulación quita el acceso sola y el reembolso se registra a mano (cierra §10 n.º 7); cancelar de inmediato quita el acceso sin devolver; extender corre el cobro y el aviso; se avisa por correo en las tres acciones; el resumen de la entrega 2 compara el mes calendario en curso contra el mismo tramo del anterior, en hora de Bogotá; y **el traslado de un precio nuevo a las suscripciones vigentes se construye** (§10 n.º 5), en una entrega propia: aviso 30 días antes, a todas las vigentes del plan, con el cupón descontando sobre el precio nuevo.

Comprobado: 1108 tests de backend (54 nuevos en `tests/api/test_admin_payments.py`: cada acción con su fila y su motivo y rechazada sin motivo, su efecto sobre `has_access` y sobre el job de renovaciones, reconsultar un pago resuelto sin dar otro período, las anulaciones, los reembolsos, `403` para quien no es administrador); 37 tests de Playwright, entre ellos "el administrador encuentra una suscripción, la extiende con motivo y la ve en la bitácora"; la migración subida, bajada con filas puestas y vuelta a subir en una base desechable.

**Sin probar:** una anulación real en el sandbox de Wompi (se probó con el doble) y qué hace Wompi con un reembolso.

### Paso 6, entrega 2: qué quedó hecho

Construido el 2026-10-14 en la rama `fase-4-paso-6b-navegacion-y-resumen`. El detalle y las decisiones están en `PLATAFORMA_COMPLETA.md` §4.9. **El paso 6 no está cerrado**: falta la entrega del traslado de precio.

- **Navegación lateral** del admin con las secciones de §4.1 (una fila desplazable en el celular).
- **`/admin` es el Resumen**. Hoy: ingreso recurrente mensual y suscripciones por estado. Del mes en curso frente al mismo tramo del anterior: cobrado (neto de reembolsos), altas, cancelaciones con su tasa, cobros fallidos, registros y correos confirmados. Todo calculado en el servidor, en centavos y en hora de Bogotá. Sin gráficos.
- El CRUD de juegos pasó a **`/admin/juegos`** y el backtest a **`/admin/motor`**.
- **Forzar el restablecimiento de la contraseña** desde `/admin/usuarios`: cierra las sesiones, la contraseña anterior deja de servir y la cuenta recibe el enlace para elegir otra. Con motivo y fila en la bitácora.
- **Reenviar el correo de confirmación** desde `/admin/usuarios`, con fila en la bitácora.

Decisiones del usuario (2026-10-14): la contraseña anterior deja de servir al forzar el restablecimiento; reenviar la verificación no pide motivo pero deja fila; el recurrente cuenta las vigentes que siguen, de los dos modos; y se agrega lo cobrado en el mes, neto de reembolsos.

Comprobado: 22 tests nuevos de backend (10 sin base, de las ventanas del resumen, y 12 de API) y 4 de Playwright (navegación y resumen, una cuenta que no es administradora, forzar el restablecimiento y reenviar la verificación). Además se revisaron capturas del resumen en escritorio y a 390 px de ancho, sin desplazamiento horizontal.

### Paso 6, entrega 3: qué quedó hecho

Construido el 2026-10-14 en la rama `fase-4-paso-6c-traslado-de-precio`. El detalle y las decisiones están en `PLATAFORMA_COMPLETA.md` §4.10. Cierra §10 n.º 5.

- **Trasladar el precio actual de un plan a sus suscripciones vigentes**, desde `/admin/planes`, con motivo y fila en la bitácora. Alcanza a las activas y en mora de los dos modos de pago; no a las canceladas.
- **Una subida** se cobra 30 días después de que a cada cliente le llegó el aviso por correo. Si el correo no sale, el plazo no corre.
- **Una bajada** aplica ya, desde el próximo cobro, con un aviso informativo.
- **Un cupón que todavía descuenta** sigue descontando sobre el precio nuevo.
- **Se puede cancelar** mientras no se haya aplicado; quien ya recibió el aviso recibe otro que dice que el precio no cambia.
- El job de renovaciones envía los avisos (hasta 40 por corrida) y aplica cada precio nuevo cuando llega su fecha, antes de cobrar.
- `/cuenta` muestra el precio nuevo ya avisado y desde cuándo corre.
- Una migración, solo DDL: `price_changes` y `subscription_price_changes`.

Comprobado: 25 tests nuevos de backend (5 sin base y 20 de API) y uno de Playwright; la migración subida, bajada con filas y vuelta a subir en una base desechable; y el script del job corrido en otra.

**Al desplegar** no hay que programar nada nuevo: los avisos los envía el mismo job de renovaciones que ya corre cada hora.

**Probado en el VPS el 2026-10-14** por el usuario, con un plan de prueba: una subida con su aviso, la cancelación del traslado y una bajada. Los avisos los envió el job programado, con correo real. Con esto el paso 6 quedó cerrado.

### Paso 7, entrega 1: qué quedó hecho

Construido el 2026-10-14 en la rama `fase-4-paso-7a-multijuego-backend`. El detalle y las decisiones están en `PLATAFORMA_COMPLETA.md` §7.7. **El paso 7 no está cerrado**: falta la entrega 2 (la mesa en la ruta nueva y el menú de juegos).

- **Metadatos del juego**: `slug` (la ruleta es `ruleta`), `module`, `description`, `icon` (set fijo), `sort_order` y `status` (`active`, `hidden`, `coming_soon`), que reemplaza a `active`. Las variantes suman `description` y `sort_order`.
- **Registro de módulos** (`api/game_modules.py`): `discrete_outcome` con los routers de la mesa y su validador; `sports` reservado sin implementación. Crear un juego con un módulo sin implementar se rechaza.
- **Acceso por juego**: `has_access` recibe el juego y aplica la regla n.º 7. `RequireGameAccess` la aplica en todas las rutas de una mesa, y abrir una mesa también la pide: `403 game_not_in_plan`.
- **`plan_games`**: un plan sin juegos incluye todos. En `/admin/planes` se eligen con motivo y fila en la bitácora. Quitarle un juego a un plan con suscripciones vigentes se rechaza.
- **`/admin/juegos`**: lista paginada con filtros, alta con los metadatos (el juego nace oculto), cambio de estado con motivo y fila en la bitácora, y la pista de presentación del teclado (`display`) en el formulario de variantes.
- **Fixture de dados** (un dado de seis caras) de punta a punta por la API, sin tocar `engine/`.
- Cinco migraciones: DDL, backfill, DDL de cierre (retira `games.active`), `plan_games` y el backfill de `display` en las variantes de ruleta.

Decisiones del usuario (2026-10-14): un juego activo pasa a `active` y uno inactivo a `hidden`; la ruleta lleva el slug `ruleta` y la URL en español, y el slug no se edita; `coming_soon` se ve sin abrir mesa; `hidden` solo lo ve y lo prueba un administrador; las mesas abiertas siguen funcionando aunque su juego se oculte; cambiar el estado pide motivo y deja fila; el ícono es de un set fijo, sin subida de archivos; las sesiones abiertas no se tocan y `/games/roulette/:id` redirige a `/juegos/ruleta/mesa/:id` (entrega 2); un plan sin juegos incluye todos, y el acceso manual y el administrador ven todos; quitar un juego a un plan con vigentes se rechaza; `/planes` nombra los juegos solo de un plan con lista (entrega 2); el dashboard sigue siendo el inicio y su sección de mesa nueva pasa a ser el menú (entrega 2).

Comprobado: 28 tests nuevos de backend en `tests/api/test_multijuego.py`, entre ellos el que recorre todas las rutas de una mesa con un juego fuera del plan; la suite completa del backend; dos tests nuevos de Playwright (`e2e/admin-games.spec.ts`) y el recorrido del admin con Juegos y Motor; las cinco migraciones subidas, bajadas con filas y vueltas a subir en una base desechable, con `alembic check` sin diferencias.

### Paso 7, entrega 2: qué quedó hecho

Construido el 2026-10-14 en la rama `fase-4-paso-7b-mesa-y-menu`. El detalle está en `PLATAFORMA_COMPLETA.md` §7.8. Con ella está construido todo el paso 7.

- **La mesa vive en `/juegos/<slug>/mesa/<id>`**: la ruleta en `/juegos/ruleta/mesa/<id>`. `/games/roulette/<id>` redirige ahí, así que los enlaces guardados siguen sirviendo. La pantalla la elige el registro de módulos del frontend (`lib/game-modules.ts`).
- **`components/mesa/*`** reemplaza a `components/roulette/*`. El teclado sale de `possible_outcomes`, con el tono y las columnas de la pista `display`: ya no se supone la categoría `color` de la ruleta.
- **El inicio tiene el menú de juegos** ("Elige un juego"). Muestra "Próximamente" y "Disponible en otro plan", y cada juego tiene su página (`/juegos/<slug>`) con sus variantes y el formulario de mesa nueva.
- **Pantalla de `game_not_in_plan`** en la mesa y en la página del juego, con "Ver planes".
- **`/planes`** dice qué juegos incluye un plan que tiene lista.
- Una migración de datos: la descripción de la ruleta y de sus variantes, y su orden, donde estaban vacíos (en el VPS el seed no vuelve a correr).

Comprobado: la suite completa del backend (con un test nuevo); cuatro tests nuevos de Playwright (`e2e/multijuego.spec.ts`), entre ellos el fixture de dados de punta a punta y la redirección de la ruta vieja; los Playwright de la mesa en la ruta nueva; la migración en una base desechable; y capturas en escritorio y a 390 px.

**Probado en el VPS el 2026-10-14** por el usuario, con el alta de juegos ya oculta (PR #23): el menú de juegos, una mesa nueva en la ruta `/juegos/ruleta/mesa/<id>`, la redirección de un enlace viejo, una mesa abierta antes del despliegue, `/admin/juegos` y los juegos incluidos de los planes. Con esto el paso 7 quedó cerrado. Lo que en el VPS no se puede probar porque solo existe la ruleta (un juego fuera del plan, "Próximamente", el dado) lo cubren los tests de backend y de Playwright.

Decisiones del usuario (2026-10-14): se quita el aviso fijo "La ruleta no tiene memoria…", que `CLAUDE.md` ya daba por retirado, del dashboard, del pie del login y del registro, y de la descripción de la página; y se corrige el ejemplo de dos dados de la skill `categories-json-validator` (las sumas no son equiprobables).


### Paso 8: qué quedó hecho

Documentado el 2026-10-15 en la rama `fase-4-paso-8-deportivas`, sin código. El detalle está en `PLATAFORMA_COMPLETA.md` §8.4.

- **Fuente de datos**: pendiente (§10 n.º 13). No se elige proveedor hasta que se vaya a construir; el requisito es la licencia de uso comercial confirmada por escrito.
- **Alcance inicial**: fútbol, resultado final (local, empate o visitante) y pocas ligas, que se eligen junto con el proveedor.
- **Ingreso**: calendario y resultados automáticos desde el proveedor; la cuota la escribe el usuario. Sin IA.
- **Recomendación y medición**: la probabilidad implícita en la cuota, sin margen, contra una estimación estadística propia; backtest fuera de muestra contra la cuota de cierre. **Deportes sale solo si el backtest supera al mercado.**
- **Lenguaje**: términos de deportes agregados a la tabla de §0 de `ARQUITECTURA_Y_ESTADISTICA.md`. **"Pronóstico" se permite en deportes**, con el alcance de §8.4: no en la ruleta, nunca con palabras de certeza, y los nombres en código no cambian.
- **Marco regulatorio**: pendiente del abogado (§10 n.º 14); deportes no sale sin concepto escrito.
- **Gestión de banca**: apuesta fija y proporcional; sin martingala, sin dos sectores y sin Kelly.

No se crearon `backend/app/engine/sports/`, `/sports` ni `/deportes` (decisión del usuario): el módulo ya está reservado en el enum de `games.module`, en los dos registros de módulos y en el admin.

Comprobado: solo cambiaron documentos y la skill de terminología, así que no hacía falta correr la suite.
