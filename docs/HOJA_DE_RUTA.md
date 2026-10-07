# Sebasanálisis — Hoja de ruta

> Punto de entrada a la documentación. Dice qué es el producto hoy, qué se construyó, qué decisiones cambiaron por el camino y qué se construye ahora. No define reglas ni fórmulas: apunta al documento que las define.
>
> **Se actualiza cada vez que se cierra un paso o se toma una decisión de rumbo.** Última actualización: 2026-10-06.

---

## 1. El producto hoy

Sebasanálisis es una plataforma web por suscripción. El usuario registra a mano los números que salen en una mesa de ruleta y, después de cada giro, la plataforma le entrega **una recomendación** para el giro siguiente (qué apostar, o no apostar), con un Signal Score de 0 a 100, su banda, y el monto que pide cada gestión de banca.

La recomendación sale de reglas estadísticas sobre los resultados registrados. **No es una predicción**: cada giro es independiente y ninguna gestión de banca cambia la ventaja de la casa. Esa regla de lenguaje es la más importante del proyecto (`ARQUITECTURA_Y_ESTADISTICA.md` §0).

**Dónde está:** el núcleo (motor, mesa de ruleta, admin básico) está construido y aprobado. Todavía no cobra: cualquier cuenta registrada usa la mesa.

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
| Buzón de soporte en Hostinger sobre el dominio (`soporte@sebasanalisis.com`). | El correo de soporte y de contacto es una cuenta de Gmail: `sebas.analisis.ia.com@gmail.com`. | 2026-10-07 |
| Chequeo externo de disponibilidad sobre la API y la página de inicio. | No se hace. Si el VPS se cae, no hay aviso. | 2026-10-07 |

---

## 5. Lo que se construye ahora: Fase 4

Especificación completa en `PLATAFORMA_COMPLETA.md`. No toca el motor. El orden pone primero lo que bloquea cobrar, y no se avanza a un paso sin que el anterior tenga tests o una verificación manual funcionando.

| # | Paso | Detalle | Estado |
|---|---|---|---|
| 0 | Preparación del stack: actualización de Next.js y React, CI, generador de tipos, IP real tras el proxy, Playwright, GlitchTip | §13 | **Cerrado el 2026-10-07.** Construido y en `main` el 2026-10-06; GlitchTip instalado y comprobado el 2026-10-07 (ver abajo) |
| 1 | Correo, verificación, restablecimiento de contraseña, revocación de sesiones | §5 | **Cerrado el 2026-10-07.** Construido el 2026-10-06 (rama `fase-4-paso-1-correo`); correo real encendido con Resend sobre `correo.sebasanalisis.com` y comprobado por el usuario con una cuenta nueva: registro, restablecimiento y aviso de cuenta eliminada (ver `DESPLIEGUE.md`, "Correo"). Queda anotado: en Hotmail el correo llegó a no deseado |
| 2 | Legal: documentos versionados, consentimientos, páginas públicas, Juego Responsable, onboarding | §6 | Pendiente |
| 3 | Modelo de acceso (`has_access`, `RequireAccess`) y bitácora de auditoría | §2, §4.6 | Pendiente |
| 4 | Planes y cupones, cálculo de precios, página de planes | §3.2, §3.3, §4.4, §4.5 | Pendiente |
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

### Decisiones tomadas para la Fase 4

- Cobro con renovación automática y tarjeta tokenizada en Wompi.
- Correo transaccional con Resend por SMTP. El correo de soporte y de contacto es `sebas.analisis.ia.com@gmail.com` (2026-10-07); no hay buzón en Hostinger.
- Monitoreo de errores con GlitchTip autohospedado en el VPS, en `errores.sebasanalisis.com` desde el 2026-10-07.
- Tests de frontend de punta a punta con Playwright.
- Tipos del cliente API generados con `openapi-typescript`.
- Dominio `sebasanalisis.com`, en Hostinger junto con el VPS. Desde el 2026-10-07 la aplicación corre en `sebasanalisis.com` y `api.sebasanalisis.com`, con HTTPS.
- Resend en el plan gratuito (100 correos al día) mientras se construye, con `EMAIL_DAILY_LIMIT=80`; se pasa al plan Pro antes del lanzamiento comercial.
- El VPS tiene 8 GB de RAM (confirmado el 2026-10-06): alcanza para GlitchTip junto a la aplicación.

### Pendiente del usuario

La lista completa, con la propuesta por defecto de cada una, está en `PLATAFORMA_COMPLETA.md` §10. Las que bloquean un paso:

| Decisión | Bloquea |
|---|---|
| Textos legales revisados por abogado; responsable que figura en la política de datos (el correo de contacto ya está decidido: `sebas.analisis.ia.com@gmail.com`) | Lanzamiento (el paso 2 se construye con borradores) |
| Pasar Resend al plan Pro y subir `EMAIL_DAILY_LIMIT` | Lanzamiento |
| Qué pasa con los usuarios `trial` actuales | Paso 3 |
| Planes y precios iniciales | Paso 4 |
| Cuenta de comercio en Wompi (sandbox y producción); medios de pago; facturación electrónica | Paso 5 |

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
