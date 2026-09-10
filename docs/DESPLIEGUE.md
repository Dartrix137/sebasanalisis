# Despliegue en VPS con Dokploy

## Un solo repositorio

Sebasanalisis va en **un repositorio**, con `backend/` y `frontend/` dentro. No en dos.

La razon no es comodidad, es una regla que ya existe en el proyecto: no hay
generador automatico de tipos, asi que cada cambio en un schema de Pydantic
tiene que reflejarse a mano en su tipo de TypeScript **en el mismo commit**
(ver `.claude/skills/api-schema-sync`). Con dos repositorios ese "mismo commit"
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
```

Dos cosas que se rompen en silencio si se copian de desarrollo:

- **`DATABASE_URL` lleva el prefijo `postgresql+psycopg://`**, no `postgres://`.
  Dokploy muestra la cadena en el formato corto; hay que adaptarla.
- **`CORS_ORIGINS` es JSON**, con corchetes y comillas. Y va el dominio del
  frontend, no el de la API. Si queda el `localhost` de desarrollo, la API
  responde bien a `curl` pero el navegador bloquea cada peticion antes de que
  salga: la aplicacion se ve viva y no funciona nada.

### Web (`Build Arguments`, no `Environment`)

```
NEXT_PUBLIC_API_BASE_URL=https://api.sebasanalisis.com
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

## Antes del primer despliegue

- El repositorio **no** debe llevar `backend/.env`: tiene la clave JWT y la del
  administrador. Ya esta en `.gitignore`; verificalo con `git status` antes del
  primer commit.
- `docker-compose.yml` de la raiz es solo para desarrollo local. En el VPS no
  se usa.
