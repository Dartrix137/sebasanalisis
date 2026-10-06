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
EMAIL_BACKEND=console
```

`FRONTEND_BASE_URL` es la base de los enlaces que viajan en los correos
(verificar el correo, restablecer la contrasena). Es la direccion **publica del
frontend**, sin barra final. Si queda el `localhost` por defecto, los correos
salen con enlaces que no abren.

`EMAIL_BACKEND=console` significa que la API **no envia correo**: lo imprime en
su log. Es el valor mientras no haya dominio ni proveedor; ver "Correo" abajo
para encenderlo.

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
aplicacion API dentro de Dokploy:

```
python -m app.db.seed
```

Crea el administrador y precarga la ruleta europea y americana. Es idempotente:
si se vuelve a correr no duplica nada ni cambia la clave del administrador.

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

## Correo

La API envia correos de verificacion, de restablecimiento de contrasena y de
aviso. El codigo solo conoce SMTP generico; el proveedor elegido es Resend.

### Mientras no hay dominio

Con `EMAIL_BACKEND=console` (o sin la variable) no se envia nada: cada correo
sale en el log de la API, con su enlace. Sirve para probar el flujo a mano
(registrarse, copiar el enlace del log, abrirlo), pero **un usuario real no
recibe nada**: no puede confirmar su correo ni recuperar su contrasena. Las
cuentas siguen entrando sin confirmar, asi que la mesa no se ve afectada.

### Encenderlo (pendiente: necesita el dominio)

1. **Confirmar con Resend, por escrito, que su politica de uso admite el
   producto**: analisis estadistico por suscripcion, adyacente a juegos de azar,
   que no recibe apuestas. Si la respuesta es no, se usa otro relay SMTP (Brevo,
   Amazon SES) cambiando solo las variables.
2. En Resend, dar de alta el **subdominio remitente** (por ejemplo
   `correo.sebasanalisis.com`), no el dominio principal: separa la reputacion
   del correo automatico.
3. En el DNS de Hostinger, crear los registros **SPF, DKIM y DMARC** que Resend
   muestra para ese subdominio. Sin ellos los correos caen en spam.
4. En la API (`Environment`), con los valores de host, puerto y usuario copiados
   de la **documentacion vigente de Resend** (la contrasena es la API key):

   ```
   EMAIL_BACKEND=smtp
   SMTP_HOST=...
   SMTP_PORT=587
   SMTP_USER=...
   SMTP_PASSWORD=<API key de Resend>
   SMTP_FROM=Sebasanálisis <no-responder@correo.sebasanalisis.com>
   SMTP_USE_TLS=true
   ```

   Con el puerto 465 la conexion es TLS desde el inicio; con 587 se cifra con
   STARTTLS. Los dos funcionan con `SMTP_USE_TLS=true`.
5. Redesplegar la API y comprobar: registrar una cuenta con un correo propio,
   recibir el correo en la bandeja de entrada (no en spam) y abrir el enlace.
   Repetir con "¿Olvidaste tu contraseña?".
6. Revisar los topes diario y mensual del plan de Resend contra el volumen
   esperado: un tope diario alcanzado deja sin correo de verificacion a quien se
   registre ese dia.
7. Poner `EMAIL_DAILY_LIMIT` **por debajo del tope diario del plan** (por
   defecto 300). Al llegar a ese numero la API deja de enviar hasta el dia
   siguiente (UTC) y lo registra como error, que llega al monitoreo: es la
   senal de que alguien esta abusando del registro o de que el plan ya queda
   corto.

`EMAIL_BACKEND=file` y `RATE_LIMIT_ENABLED=false` son solo para los tests de
punta a punta. **Nunca van en produccion.**

## Monitoreo de errores con GlitchTip

La API (`sentry-sdk`) y el frontend (`@sentry/nextjs`) ya traen el monitoreo,
**apagado mientras no tengan DSN**. Encenderlo es instalar GlitchTip en el VPS
y pegar dos DSN. GlitchTip habla el protocolo de Sentry y corre en el mismo
VPS: los errores no salen a ningun tercero.

Lo que el codigo nunca envia, haya el error que haya: cabeceras
`Authorization` y cookies, cuerpos de `/auth/*`, `/billing/*` y `/webhooks/*`,
variables locales de los tracebacks, y desde el navegador ningun cuerpo de
peticion (`backend/app/core/monitoring.py`, `frontend/lib/monitoring.ts`).

El VPS tiene 8 GB de RAM (confirmado el 2026-10-06), suficiente para GlitchTip
junto a la aplicacion. Antes de instalar, mirar igual la memoria libre real con
`free -h`.

### Instalacion (pendiente, se hace con el usuario)

1. **DNS.** En Hostinger, un registro `A` para `errores.sebasanalisis.com`
   apuntando a la IP del VPS.
2. **Servicio en Dokploy.** Dentro del mismo proyecto, un servicio nuevo de
   tipo *Compose* (o la plantilla de GlitchTip si Dokploy la ofrece). El
   `docker-compose.yml` se copia de la **documentacion oficial vigente de
   GlitchTip** (glitchtip.com, seccion de instalacion): no se escribe de
   memoria, porque los servicios que trae han cambiado entre versiones.
3. **Base de datos propia.** GlitchTip usa el PostgreSQL de su propio compose.
   **Nunca** se le da la `DATABASE_URL` de Sebasanalisis.
4. **Variables de GlitchTip** (los nombres exactos, de su documentacion):
   - una clave secreta larga y aleatoria, distinta a `JWT_SECRET_KEY`;
   - el dominio publico: `https://errores.sebasanalisis.com`;
   - el remitente y el servidor SMTP para las alertas (el mismo relay de
     Resend que usara la aplicacion; hasta tenerlo, las alertas por correo no
     funcionan y los errores se revisan entrando al panel);
   - el registro de usuarios nuevos **desactivado**, despues del paso 6.
5. **Dominio y HTTPS.** En la pestana de dominios del servicio:
   `errores.sebasanalisis.com` hacia el puerto del contenedor web de GlitchTip,
   con HTTPS activado.
6. **Cuenta de administrador.** Entrar a `https://errores.sebasanalisis.com`,
   registrar la primera cuenta y crear una organizacion. Despues, cerrar el
   registro (paso 4) y redesplegar GlitchTip.
7. **Dos proyectos**: `sebasanalisis-api` (plataforma Python/FastAPI) y
   `sebasanalisis-web` (plataforma JavaScript/Next.js). Cada uno muestra su DSN.
8. **Pegar los DSN**:
   - `SENTRY_DSN` en *Environment* de la API -> redesplegar;
   - `NEXT_PUBLIC_SENTRY_DSN` en *Build Arguments* del Web -> **reconstruir**
     (se incrusta en el build, igual que `NEXT_PUBLIC_API_BASE_URL`).
9. **Alertas.** En cada proyecto, una alerta por correo al administrador ante
   un error nuevo.
10. **Chequeo externo.** GlitchTip vive en el mismo VPS: si el VPS se cae, se
    cae con el y no avisa. Configurar un servicio externo gratuito de
    disponibilidad sobre `https://api.sebasanalisis.com/health` y sobre
    `https://sebasanalisis.com`.

### Comprobacion (cierra el paso 0 de la Fase 4)

Un error provocado a proposito en cada lado tiene que aparecer en su proyecto:

- **Frontend**: abrir `https://sebasanalisis.com/login`, y en la consola del
  navegador ejecutar
  `setTimeout(() => { throw new Error("prueba de monitoreo web") }, 0)`.
  Debe aparecer en `sebasanalisis-web` en menos de un minuto.
- **API**: en la terminal de la aplicacion API en Dokploy,
  `python -c "from app.main import app; import sentry_sdk; sentry_sdk.capture_exception(RuntimeError('prueba de monitoreo api')); sentry_sdk.flush()"`.
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
