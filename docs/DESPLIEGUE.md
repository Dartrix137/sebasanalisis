# Despliegue en VPS con Dokploy

## Un solo repositorio

Sebasanalisis va en **un repositorio**, con `backend/` y `frontend/` dentro. No en dos.

La razon no es comodidad, es una regla que ya existe en el proyecto: los tipos
de TypeScript del frontend se generan desde la API (`npm run gen:types`) y se
commitean **en el mismo commit** que el cambio de schema, pero el frontend no
valida las respuestas al recibirlas (ver `.claude/skills/api-schema-sync`). Con
dos repositorios ese "mismo commit"
deja de ser posible: el backend puede mezclarse a produccion con un campo nuevo
mientras el frontend sigue apuntando al viejo, y nadie lo nota hasta que un
usuario ve la pantalla rota.

Dokploy no obliga a lo contrario: cada aplicacion apunta al mismo repositorio
con un *Build Path* distinto.

## Piezas a crear en Dokploy

Tres, dentro de un mismo proyecto:

| Pieza | Tipo en Dokploy | Build Path |
|---|---|---|
| Base de datos | PostgreSQL 16 | — |
| API | Application (Dockerfile) | `/backend` |
| Web | Application (Dockerfile) | `/frontend` |

La base como servicio nativo de Dokploy y no como contenedor propio: asi el
panel se encarga de los respaldos, que es justo lo que no conviene improvisar
con las sesiones y apuestas de los usuarios adentro.

## Variables de entorno

### API (`Environment`)

```
DATABASE_URL=postgresql+psycopg://USUARIO:CLAVE@HOST_INTERNO:5432/sebasanalisis
JWT_SECRET_KEY=<cadena larga y aleatoria, distinta a la de desarrollo>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
CORS_ORIGINS=["https://sebasanalisis.com"]
SEED_ADMIN_EMAIL=<correo real del administrador>
SEED_ADMIN_PASSWORD=<clave fuerte>
FORWARDED_ALLOW_IPS=<red del proxy de Dokploy, ver abajo>
SENTRY_DSN=<DSN del proyecto de la API en GlitchTip; vacio hasta instalarlo>
FRONTEND_BASE_URL=https://sebasanalisis.com
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASSWORD=<API key de Resend>
SMTP_FROM=Sebasanálisis <no-responder@correo.sebasanalisis.com>
SMTP_USE_TLS=true
EMAIL_DAILY_LIMIT=80
```

`FRONTEND_BASE_URL` es la base de los enlaces que viajan en los correos
(verificar el correo, restablecer la contrasena). Es la direccion **publica del
frontend**, sin barra final. Si queda el `localhost` por defecto, los correos
salen con enlaces que no abren.

`EMAIL_BACKEND=smtp` con las `SMTP_*` es lo que esta puesto en produccion desde
el 2026-10-07; el detalle esta en "Correo" abajo. Con `EMAIL_BACKEND=console` (o
sin la variable) la API **no envia correo**: lo imprime en su log.

Tres cosas que se rompen en silencio si se copian de desarrollo o se dejan vacias:

- **`FORWARDED_ALLOW_IPS` es la red de Docker desde la que el proxy de Dokploy
  (Traefik) le habla a la API.** Sin ella, la API ve a todos los usuarios con la
  IP del proxy: el limite de intentos de login queda compartido entre todos, y
  las IP que se guarden como evidencia no sirven. Se saca en el VPS con:

  ```
  docker network inspect dokploy-network --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'
  ```

  y se pone tal cual, en formato CIDR (por ejemplo `10.0.1.0/24`). **No se pone
  `*`**: con `*` cualquiera que alcance el puerto de la API puede escribir la
  cabecera `X-Forwarded-For` y hacerse pasar por otra IP. Comprobacion despues
  de desplegar: fallar el login 5 veces desde un equipo deja bloqueado ese
  correo solo desde ese equipo; desde otra red (el celular con datos) el mismo
  correo todavia responde "credenciales invalidas" y no "demasiados intentos".

- **`DATABASE_URL` lleva el prefijo `postgresql+psycopg://`**, no `postgres://`.
  Dokploy muestra la cadena en el formato corto; hay que adaptarla.
- **`CORS_ORIGINS` es JSON**, con corchetes y comillas. Y va el dominio del
  frontend, no el de la API. Si queda el `localhost` de desarrollo, la API
  responde bien a `curl` pero el navegador bloquea cada peticion antes de que
  salga: la aplicacion se ve viva y no funciona nada.

### Web (`Build Arguments`, no `Environment`)

```
NEXT_PUBLIC_API_BASE_URL=https://api.sebasanalisis.com
NEXT_PUBLIC_SENTRY_DSN=<DSN del proyecto del frontend en GlitchTip; vacio hasta instalarlo>
```

Next.js incrusta las variables `NEXT_PUBLIC_*` en el JavaScript del navegador
**durante el build**, no las lee al arrancar. Puesta solo como variable de
entorno del contenedor no tiene ningun efecto: el sitio queda apuntando al
`http://localhost:8000` por defecto y ningun usuario puede entrar. Cambiar este
valor obliga a reconstruir, no basta con reiniciar.

Este proyecto guarda la sesion en `localStorage` y llama la API desde el
navegador, asi que la URL tiene que ser la **publica** de la API — la direccion
interna de Docker no le sirve al navegador del usuario.

## Dominios

- `sebasanalisis.com` -> aplicacion Web, puerto 3000
- `api.sebasanalisis.com` -> aplicacion API, puerto 8000

HTTPS activado en ambos. Con la API en `http://` el navegador bloquea las
peticiones desde una web `https://` por contenido mixto.

## Migraciones y seed

Las migraciones corren solas en cada arranque (`backend/docker-entrypoint.sh`).
No hay que hacer nada.

El seed **no** corre solo, a proposito: reactiva las variantes de ruleta
(`active=True`), asi que en cada despliegue pisaria en silencio una variante que
el administrador haya desactivado. Se corre una sola vez, en la terminal de la
aplicacion API dentro de Dokploy. La terminal abre en `/` y el codigo esta en
`/app`: sin el `cd`, Python no encuentra los modulos (`No module named
'app.core'`).

```
cd /app
python -m app.db.seed
```

Crea el administrador y precarga la ruleta europea y americana. Es idempotente:
si se vuelve a correr no duplica nada ni cambia la clave del administrador.

### Documentos legales (Fase 4, paso 2)

La migracion `c3f81a5d7e20` publica la version 1 de los cuatro documentos
legales (terminos, datos, reembolsos, cookies). Son **borradores** pendientes de
abogado y lo dicen en su primer parrafo. No hay que correr nada a mano.

Que pasa al desplegar este paso:

- El registro empieza a exigir las tres casillas (terminos, datos, mayoria de
  edad).
- **Toda cuenta que ya existia, incluido el administrador, ve la pantalla de
  aceptacion la proxima vez que entra a la mesa.** No pierde la sesion ni el
  acceso a `/cuenta`.
- El texto revisado por el abogado se publica desde `/admin/legal` como version
  nueva, marcando "exigir aceptacion": eso se lo vuelve a pedir a todas las
  cuentas.

### Control de acceso (Fase 4, paso 3)

Que pasa al desplegar este paso:

- Las cuentas `trial` que ya existian pasan a `invited` sin vencimiento: siguen
  usando la mesa. La migracion lo hace sola.
- **Toda cuenta nueva queda sin acceso** hasta que un administrador se lo de en
  `/admin/usuarios` (buscar la cuenta, "Ver", tipo de acceso "Invitado", motivo,
  "Guardar acceso"). Mientras no exista el pago (paso 5) es la unica via.
- Cada cambio de acceso y cada suspension queda en `/admin/auditoria`.

## Comprobacion despues del primer despliegue

1. `https://api.sebasanalisis.com/health` devuelve `{"status":"ok"}`.
2. `https://api.sebasanalisis.com/docs` lista los endpoints.
3. Entrar a la web con el correo del administrador.
4. Abrir una mesa de ruleta y registrar un numero — esto confirma de una vez
   que el CORS y la URL de la API quedaron bien.

## MVP sin dominio propio (dominios gratuitos de Dokploy)

Mientras no se compre `sebasanalisis.com`, se puede desplegar igual con los
subdominios gratuitos que Dokploy genera para cada aplicacion (tipo
`algo-random.sslip.io`). **Estos dominios son solo HTTP**: `sslip.io` no
soporta HTTPS/SSL y Dokploy lo advierte al generarlos — el toggle de "HTTPS"
no tiene ningun efecto ahi, a diferencia de `traefik.me` en otras instancias.

Esto no es un problema mientras **las dos aplicaciones queden en HTTP por
igual**. El bloqueo por contenido mixto solo aparece cuando se mezclan
protocolos distintos entre frontend y API — con ambas en HTTP no hay
inconsistencia.

Con los dominios generados, las variables cambian de valor y de protocolo:

```
# API - Environment
CORS_ORIGINS=["http://DOMINIO-WEB-GENERADO.sslip.io"]

# Web - Build Arguments
NEXT_PUBLIC_API_BASE_URL=http://DOMINIO-API-GENERADO.sslip.io
```

### Migrar al dominio real cuando se compre

No basta con cambiar el dominio en Dokploy. Hay que repetir estos dos pasos o
la aplicacion queda viva pero rota:

1. Actualizar `CORS_ORIGINS` en la API al nuevo dominio del frontend, y de
   paso pasar de `http://` a `https://` — el dominio real si va con HTTPS.
2. Cambiar `NEXT_PUBLIC_API_BASE_URL` en los Build Arguments del Web (tambien
   a `https://`) y **reconstruir** — un reinicio no alcanza, porque Next.js
   incrusta esa variable en el JavaScript durante el build, no la lee al
   arrancar.

Repetir la comprobacion de la seccion anterior despues de migrar.

**Hecho el 2026-10-07.** En el primer intento las dos URL quedaron cruzadas
(`CORS_ORIGINS` con el dominio de la API y `NEXT_PUBLIC_API_BASE_URL` con el del
frontend) y `/health` respondia bien igual, porque no pasa por el CORS del
navegador. Dos comprobaciones que si lo detectan:

```
# Debe responder 200. Un 400 "Disallowed CORS origin" es CORS_ORIGINS mal puesto.
curl -s -o /dev/null -w "%{http_code}\n" -X OPTIONS https://api.sebasanalisis.com/auth/login \
  -H "Origin: https://sebasanalisis.com" -H "Access-Control-Request-Method: POST"
```

Y en el navegador, al intentar entrar, la pestana Red debe mostrar la peticion
saliendo hacia `https://api.sebasanalisis.com/auth/login`, no hacia
`https://sebasanalisis.com/auth/login`.

No se usa `www.sebasanalisis.com`: el registro se borro del DNS. Si algun dia se
quiere, se agrega en Dokploy como dominio del Web con redireccion al principal;
un registro DNS sin dominio en Dokploy responde con error de certificado.

## Correo

La API envia correos de verificacion, de restablecimiento de contrasena y de
aviso. El codigo solo conoce SMTP generico; el proveedor elegido es Resend.

### Como quedo encendido (2026-10-07)

Resend confirmo que su politica de uso admite el producto (analisis estadistico
por suscripcion, que no recibe apuestas). Si algun dia hay que cambiar de relay
(Brevo, Amazon SES), solo cambian las variables `SMTP_*` y los registros DNS.

- **Dominio remitente**: el subdominio `correo.sebasanalisis.com`, dado de alta
  en Resend. No el dominio principal: separa la reputacion del correo automatico.
- **Registros en el DNS de Hostinger.** Los valores se copian del panel de
  Resend (cambian con la region y con el tiempo; los de su guia publica ya no
  coincidian). En el campo *Name* de Hostinger va el nombre **sin** el dominio:

  | Para que | Tipo | Name | Valor |
  |---|---|---|---|
  | SPF (ruta de retorno) | MX | `send.correo` | el del panel de Resend, prioridad 10 |
  | SPF | TXT | `send.correo` | el `v=spf1 ...` del panel de Resend |
  | DKIM | TXT | `resend._domainkey.correo` | la clave `p=...` completa del panel |
  | DMARC | TXT | `_dmarc` | `v=DMARC1; p=none;` |

  El DMARC va en el dominio raiz y cubre tambien el subdominio. Empieza en
  `p=none`, como recomienda Resend. Queda **sin `rua`**: el correo de soporte es
  una cuenta de Gmail (decidido el 2026-10-07), y los reportes DMARC hacia un
  dominio ajeno solo se entregan si ese dominio los autoriza en su DNS, cosa que
  con Gmail no se puede. Si algun dia hay un buzon en el dominio propio, se
  agrega `rua=mailto:...` y con los reportes se decide subirlo a `p=quarantine`.
- **Variables de la API**: las del bloque de "Variables de entorno". Host,
  puertos y usuario salen de `resend.com/docs/send-with-smtp` (leida el
  2026-10-07): host `smtp.resend.com`, usuario `resend`, contrasena la API key.
  El 587 cifra con STARTTLS y el 465 es TLS desde el inicio; los dos funcionan
  con `SMTP_USE_TLS=true`. **No usar el 2465 ni el 2587**: el codigo solo trata
  como TLS directo el 465. Si el VPS no deja salir por el 587, se cambia a 465.
- **API key**: con permiso solo de envio (*Sending access*) y restringida a ese
  dominio. Vive unicamente en Dokploy.
- **Seguimiento de aperturas y de clics: apagado.** El de clics reescribe los
  enlaces de verificacion.
- **Recepcion (*Enable Receiving*)**: no hace falta. El remitente es
  `no-responder@` y los correos recibidos gastan la misma cuota. Si esta
  encendida, hay un MX en `correo` que se borra al apagarla.

### Cuota y `EMAIL_DAILY_LIMIT`

El plan gratuito de Resend da **100 correos al dia y 3.000 al mes**; el dia se
cuenta en UTC, igual que el tope de la API. `EMAIL_DAILY_LIMIT=80` deja margen
porque la cuota de Resend cuenta todo lo que salga de la cuenta (tambien las
alertas de GlitchTip cuando usen el mismo relay) y porque el contador de la API
vive en memoria: un reinicio lo pone en cero.

Al llegar al tope la API deja de enviar hasta el dia siguiente y lo registra
como error, que llega al monitoreo: es la senal de que alguien esta abusando del
registro o de que el plan ya queda corto. **Antes del lanzamiento comercial se
pasa al plan Pro** (sin tope diario) y se sube `EMAIL_DAILY_LIMIT`: con 100
diarios, un dia de muchos registros deja gente sin correo de verificacion.

### Comprobacion

Hecha el 2026-10-07 con una cuenta nueva: registro, "¿Olvidaste tu contraseña?"
y aviso de cuenta eliminada llegaron y sus enlaces funcionaron. Se repite cada
vez que se toque el dominio, el DNS o las `SMTP_*`:

1. Registrar una cuenta con un correo propio: llega el correo y el enlace, que
   empieza por `https://sebasanalisis.com/verificar-correo`, confirma la cuenta.
2. "¿Olvidaste tu contraseña?" y eliminar la cuenta desde `/cuenta`.
3. En Gmail, "Mostrar original": SPF, DKIM y DMARC en `PASS`.

Si no llega nada: el log de la API en Dokploy y la tabla *Emails* de Resend.

**Entrega conocida**: en Gmail llego a la bandeja principal; en Hotmail llego a
**correo no deseado**. Es frecuente con un dominio recien estrenado y sin
historial de envio, y no se arregla con una variable. Las pantallas le dicen al
usuario que revise esa carpeta. Volver a probar con Hotmail/Outlook antes del
lanzamiento comercial.

### Sin proveedor

Con `EMAIL_BACKEND=console` (o sin la variable) no se envia nada: cada correo
sale en el log de la API, con su enlace. Sirve para probar el flujo a mano en
desarrollo, pero un usuario real no recibe nada.

`EMAIL_BACKEND=file` y `RATE_LIMIT_ENABLED=false` son solo para los tests de
punta a punta. **Nunca van en produccion.**

## Monitoreo de errores con GlitchTip

La API (`sentry-sdk`) y el frontend (`@sentry/nextjs`) ya traen el monitoreo,
**apagado mientras no tengan DSN**. Encenderlo fue instalar GlitchTip en el VPS
y pegar dos DSN. GlitchTip habla el protocolo de Sentry y corre en el mismo
VPS: los errores no salen a ningun tercero.

Lo que el codigo nunca envia, haya el error que haya: cabeceras
`Authorization` y cookies, cuerpos de `/auth/*`, `/billing/*` y `/webhooks/*`,
variables locales de los tracebacks, y desde el navegador ningun cuerpo de
peticion (`backend/app/core/monitoring.py`, `frontend/lib/monitoring.ts`).

El VPS tiene 8 GB de RAM (confirmado el 2026-10-06), suficiente para GlitchTip
junto a la aplicacion. Antes de instalar, mirar igual la memoria libre real con
`free -h`.

### Como quedo instalado (2026-10-07)

GlitchTip corre en `https://errores.sebasanalisis.com`, como un servicio
*Compose* aparte dentro del mismo proyecto de Dokploy.

1. **DNS.** En Hostinger, un registro `A` con Name `errores` hacia la IP del VPS.
2. **Compose.** Es el de ejemplo de la documentacion oficial de GlitchTip
   (`glitchtip.com/assets/compose.sample.yml`, leido el 2026-10-07; al
   actualizar de version mayor se vuelve a leer, porque los servicios que trae
   han cambiado entre versiones), con tres cambios: los secretos salen de
   variables, Postgres lleva contrasena, y el puerto 8000 **no se publica** en
   el VPS (`expose` en lugar de `ports`): publicado, GlitchTip quedaria abierto
   por HTTP sin pasar por el proxy.

   ```yaml
   x-environment: &default-environment
     DATABASE_URL: postgres://postgres:${POSTGRES_PASSWORD}@postgres:5432/postgres
     VALKEY_URL: redis://valkey:6379
     SECRET_KEY: ${SECRET_KEY}
     EMAIL_URL: ${EMAIL_URL}
     GLITCHTIP_DOMAIN: https://errores.sebasanalisis.com
     DEFAULT_FROM_EMAIL: alertas@correo.sebasanalisis.com
     ENABLE_USER_REGISTRATION: "False"
     ENABLE_ADMIN: "False"
     ENABLE_OPENAPI: "False"
     GLITCHTIP_ENABLE_MCP: "False"
     GLITCHTIP_ENABLE_DUCKDB: "False"

   services:
     postgres:
       image: postgres:18
       environment:
         POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
       restart: unless-stopped
       volumes:
         - pg-data:/var/lib/postgresql
     valkey:
       image: valkey/valkey:9
       restart: unless-stopped
     web:
       image: glitchtip/glitchtip:6
       depends_on:
         - postgres
         - valkey
       expose:
         - "8000"
       environment:
         <<: *default-environment
         SERVER_ROLE: all_in_one
       restart: unless-stopped
       volumes:
         - uploads:/code/uploads

   volumes:
     pg-data:
     uploads:
   ```

3. **Base de datos propia.** GlitchTip usa el PostgreSQL de su compose.
   **Nunca** se le da la `DATABASE_URL` de Sebasanalisis.
4. **Secretos**, en la pestana *Environment* del servicio:

   ```
   SECRET_KEY=<openssl rand -hex 32; distinta a JWT_SECRET_KEY>
   POSTGRES_PASSWORD=<openssl rand -hex 24>
   EMAIL_URL=smtp+tls://resend:<API key de Resend>@smtp.resend.com:587
   ```

   La contrasena de Postgres va en hexadecimal porque viaja dentro de una URL.
   La API key de Resend es **una aparte** de la de la aplicacion, solo de envio:
   se puede revocar sin tocar la API. Las alertas salen por el mismo dominio
   remitente y gastan la misma cuota diaria de Resend.
5. **Registro cerrado desde el inicio.** Con `ENABLE_USER_REGISTRATION: "False"`
   GlitchTip deja registrar solo a la primera cuenta: no hace falta redesplegar
   despues de crearla.
6. **Dominio y HTTPS.** En *Domains* del servicio: `errores.sebasanalisis.com`,
   servicio `web`, puerto 8000, HTTPS.
7. **Dos proyectos**: `sebasanalisis-api` (Python/FastAPI) y `sebasanalisis-web`
   (JavaScript/Next.js). Cada uno muestra su DSN.
8. **Los DSN**:
   - `SENTRY_DSN` en *Environment* de la API -> redesplegar;
   - `NEXT_PUBLIC_SENTRY_DSN` en *Build Arguments* del Web -> **reconstruir**
     (se incrusta en el build, igual que `NEXT_PUBLIC_API_BASE_URL`).
9. **Alertas.** En cada proyecto, una alerta "1 evento en 1 minuto" con correo a
   los miembros del equipo del proyecto. GlitchTip no distingue errores nuevos:
   alerta por cantidad en una ventana. Si un error ruidoso gasta la cuota de
   correo, se sube la ventana. La casilla de monitores de disponibilidad queda
   marcada, para el monitor del job de renovaciones del paso 5.
10. **Retencion**: 90 dias, el valor por defecto (`GLITCHTIP_RETENTION_DAYS`).
11. **Sin chequeo externo de disponibilidad** (decidido por el usuario el
    2026-10-07). Consecuencia que se acepta: GlitchTip vive en el mismo VPS, asi
    que si el VPS entero se cae, se cae con el y nadie recibe aviso. Si se cambia
    de opinion, basta un servicio externo gratuito sobre
    `https://api.sebasanalisis.com/health` y `https://sebasanalisis.com`; no toca
    codigo.

### Comprobacion (cierra el paso 0 de la Fase 4)

Hecha el 2026-10-07: los dos eventos llegaron a su proyecto y el correo de
alerta tambien. Se repite cada vez que se toquen los DSN o GlitchTip. Un error
provocado a proposito en cada lado tiene que aparecer en su proyecto:

- **Frontend**: abrir `https://sebasanalisis.com/login`, y en la consola del
  navegador ejecutar
  `setTimeout(() => { throw new Error("prueba de monitoreo web") }, 0)`.
  Debe aparecer en `sebasanalisis-web` en menos de un minuto.
- **API**: en la terminal de la aplicacion API en Dokploy, **desde `/app`**
  (la terminal abre en `/`, y desde ahi el comando falla sin enviar nada):
  `cd /app && python -c "from app.main import app; import sentry_sdk; sentry_sdk.capture_exception(RuntimeError('prueba de monitoreo api')); sentry_sdk.flush()"`.
  Debe aparecer en `sebasanalisis-api`.
- Abrir cada evento y confirmar que **no** trae cabecera `Authorization` ni
  cuerpos de peticion.

Si no llega nada: revisar que el DSN use `https://` y el dominio publico, que
el Web se haya reconstruido (no solo reiniciado), y que el navegador no este
bloqueando la peticion a `errores.sebasanalisis.com` (pestana Red).

## Antes del primer despliegue

- El repositorio **no** debe llevar `backend/.env`: tiene la clave JWT y la del
  administrador. Ya esta en `.gitignore`; verificalo con `git status` antes del
  primer commit.
- `docker-compose.yml` de la raiz es solo para desarrollo local. En el VPS no
  se usa.
