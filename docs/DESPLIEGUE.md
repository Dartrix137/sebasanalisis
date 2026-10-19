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
WOMPI_PUBLIC_KEY=<llave publica de Wompi>
WOMPI_PRIVATE_KEY=<llave privada de Wompi>
WOMPI_EVENTS_SECRET=<secreto de eventos de Wompi>
WOMPI_INTEGRITY_SECRET=<secreto de integridad de Wompi>
WOMPI_API_BASE_URL=<https://sandbox.wompi.co/v1 o https://production.wompi.co/v1>
```

Las cinco `WOMPI_*` se dejan sin poner hasta tener la cuenta de comercio: sin
ellas la API arranca con el pago apagado. El detalle esta en "Pagos con Wompi"
abajo.

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

El administrador solo se crea si no existe ninguno. Si ya hay uno, con el correo
que sea, el seed no crea otro: `SEED_ADMIN_EMAIL` y `SEED_ADMIN_PASSWORD` son
solo para el primer arranque. Despues de entrar la primera vez, cambia la
contrasena desde "Mi cuenta": asi la del entorno deja de servir para entrar.

Para tener otro administrador: que la persona se registre, y desde
`/admin/usuarios` abrir su cuenta y usar "Nombrar administrador". Queda en la
bitacora. Conviene tener dos: el unico administrador activo no puede eliminar
su cuenta ni suspenderse, y si pierde el acceso al correo no hay relevo.

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

#### Aviso por correo de una version nueva (Fase 4, paso 9)

Desde el paso 9, publicar una version que exige aceptacion y reemplaza a otra
manda ademas un correo a las cuentas con una suscripcion vigente (activa, en
mora o cancelada con acceso), activas y con el correo confirmado
(`PLATAFORMA_COMPLETA.md` §6.7). No le llega a quien ya acepto la version
nueva. La pantalla de aceptacion sigue igual.

- **Lo envia el job de renovaciones**, no la publicacion: hasta 40 por corrida
  (una por hora) y, por dia, hasta la mitad de `EMAIL_DAILY_LIMIT`. Con
  `EMAIL_DAILY_LIMIT=80` son 40 al dia: **antes de publicar el texto del
  abogado, pasar a Resend Pro y subir el tope** (ver "Antes del lanzamiento
  comercial").
- La migracion `7d82b3f54867` crea la tabla `legal_notices` al desplegar; no hay
  que correr nada a mano.
- Comprobacion despues de publicar: en la tarea "Renovaciones" de Dokploy, el
  log de cada corrida termina con `Avisos legales: enviados=N fallidos=M`, y
  `enviados` baja a 0 cuando ya se le aviso a todos. Si dice "(quedan para
  manana: tope diario)", sigue al dia siguiente solo. Cuantos faltan, en la
  terminal de la base:

  ```
  select count(*) from legal_notices where legal_document_id = '<id de la version>';
  ```

### Control de acceso (Fase 4, paso 3)

Que pasa al desplegar este paso:

- Las cuentas `trial` que ya existian pasan a `invited` sin vencimiento: siguen
  usando la mesa. La migracion lo hace sola.
- **Toda cuenta nueva queda sin acceso** hasta que un administrador se lo de en
  `/admin/usuarios` (buscar la cuenta, "Ver", tipo de acceso "Invitado", motivo,
  "Guardar acceso"). Mientras no exista el pago (paso 5) es la unica via.
- Cada cambio de acceso y cada suspension queda en `/admin/auditoria`.

### Pagos con Wompi (Fase 4, paso 5, entrega 1)

Construido contra la documentacion oficial de Wompi consultada el 2026-10-13.

**Prueba contra el sandbox, en local (2026-10-13).** Con las llaves de sandbox
en `backend/.env`, una base aparte y el frontend abierto por `localtest.me`:

- La API arranco como `Wompi, ambiente sandbox`. El comercio figura activo,
  solo en COP.
- `POST /billing/subscriptions` abrio el pago del plan mensual (100.000 COP) y
  el Web Checkout **acepto la firma de integridad**: abrio en "MODO DE
  PRUEBAS" con tarjeta, Nequi, DaviPlata, QR, Transferencia Bancolombia, PSE,
  corresponsales y los dos creditos.
- Pago con la tarjeta de prueba aprobada (`4242 4242 4242 4242`): Wompi
  devolvio a `/pago/:id?id=<transaccion>&env=test`.
- La reconsulta con la llave privada trajo la transaccion aprobada por el
  monto esperado; el pago quedo `approved`, la suscripcion `active` con su
  periodo de un mes, la cuenta entro a la mesa y salieron la bienvenida y el
  recibo.

**Prueba en el VPS, con llaves de sandbox (2026-10-13).** Desplegada la
entrega 1 y con la URL de eventos puesta en el panel de Wompi, el usuario hizo
dos pagos aprobados con la tarjeta de prueba, cada uno con una cuenta distinta,
por la interfaz:

- `POST /billing/subscriptions` respondio `202` y el checkout cobro.
- **Llego el webhook de Wompi y respondio `200`** las dos veces, antes de que
  el navegador volviera del checkout: la firma de un evento real pasa la
  verificacion (habria sido `401`) y la reconsulta responde (habria sido
  `502`).
- La pantalla mostro "Pago aprobado" en la primera consulta, la cuenta entro
  a la mesa y llegaron los correos de bienvenida y de recibo.

El log de la API no muestra el cuerpo de la respuesta, asi que no distingue si
la suscripcion la activo el webhook o la consulta de la pantalla que llego
enseguida (las dos pasan por la misma funcion). Se confirma leyendo la base:

```sql
SELECT e.event_type, e.status, e.signature_verified,
       e.payment_id IS NOT NULL AS unido_al_pago,
       p.status AS pago, p.resolved_at, e.processed_at
FROM payment_events e LEFT JOIN payments p ON p.id = e.payment_id
ORDER BY e.created_at DESC LIMIT 5;
```

**Falta probar** (requisito para cerrar el paso 5): un pago rechazado
(`4111 1111 1111 1111`), un medio que no responde de inmediato (PSE o Nequi),
que es el caso en que el webhook resuelve el pago sin ayuda de la pantalla, y
que `/planes` marque "Tu plan actual" despues de pagar.

**Mientras el VPS tenga llaves de sandbox, cualquier cuenta puede obtener
acceso pagando con la tarjeta de prueba, sin que se mueva dinero.** Antes de
abrir el producto al publico hay que pasar a las llaves de produccion, y
retirar el acceso de las suscripciones de prueba.

**Wompi rechaza una direccion de regreso con `localhost` o `127.0.0.1`**: el
checkout responde `403` antes de mostrar nada. En produccion no afecta
(`FRONTEND_BASE_URL` es el dominio). Para probar pagos en local:
`FRONTEND_BASE_URL=http://localtest.me:3000`, ese mismo origen en
`CORS_ORIGINS`, y abrir el frontend por `http://localtest.me:3000`
(`localtest.me` es un nombre publico que apunta al propio equipo;
`next.config.ts` ya lo admite en `next dev`). La sesion se guarda por origen:
hay que iniciar sesion en esa direccion, no en `localhost`.

**Guardar un medio de pago (renovacion automatica) es al reves: en local solo
funciona desde `http://localhost:3000`.** Nuestro formulario cifra la tarjeta
en el navegador antes de mandarla a Wompi (`PLATAFORMA_COMPLETA.md` §3.16), y
el cifrado del navegador (WebCrypto) solo existe en un contexto seguro (https o
`localhost`); desde `http://localtest.me` el formulario dice "Tu navegador no
pudo cifrar la tarjeta en esta pagina". (Con el widget, hasta el 2026-10-19,
pasaba lo mismo.) Nequi no cifra nada, pero se prueba igual por `localhost`.
Para probar los dos modos en local, `CORS_ORIGINS` lleva los
dos origenes: el pago manual se prueba por `localtest.me` y la renovacion
automatica por `localhost`. En produccion, con https, no hay diferencia.

Que pasa al desplegar esta entrega:

- Tres migraciones corren solas: amplian `subscriptions`, crean `payments` y
  cambian `payment_events`. La de datos se detiene si encuentra una suscripcion
  puesta a mano con un plan que no existe; en produccion la tabla esta vacia.
- **Sin las `WOMPI_*`, nada cambia para el usuario**: `/planes` sigue mostrando
  el boton apagado con "El pago estara disponible pronto", y la unica via de
  acceso sigue siendo el acceso manual.
- Con las llaves puestas, el boton "Suscribirme" abre el pago en la pagina de
  Wompi (Web Checkout). Alli se ofrecen los medios que el comercio tenga
  habilitados en su panel de Wompi: encender o apagar un medio se hace alli,
  no en el codigo.

Para encender el pago:

1. En el panel de comercios de Wompi, "Desarrolladores": copiar la llave
   publica, la privada, el secreto de eventos y el de integridad **del mismo
   ambiente** a las variables de la API. `WOMPI_API_BASE_URL` puede quedar
   vacia (se deduce de las llaves); si se pone, debe ser la de ese ambiente.
2. En el mismo panel, poner la **URL de eventos** de ese ambiente:
   `https://api.sebasanalisis.com/webhooks/wompi`. Sandbox y produccion tienen
   cada uno la suya.
3. Reiniciar la API y mirar su log. Debe decir contra que ambiente quedo, sin
   mostrar ninguna llave:

   ```
   INFO:     app - Pagos: Wompi, ambiente sandbox (https://sandbox.wompi.co/v1)
   ```

**La API no arranca** si falta alguna de las cuatro llaves, si mezclan sandbox
y produccion, o si `WOMPI_API_BASE_URL` no es la del ambiente de las llaves. Es
a proposito: un despliegue de produccion nunca debe quedar con llaves de
sandbox a medias (el mensaje dice cual variable esta mal, sin su valor).

Como se confirma un pago (lo que hay que tener presente al mirar un problema):

- Wompi avisa por el webhook. La API verifica la firma, guarda el evento en
  `payment_events` (tambien los de firma invalida, con
  `signature_verified = false`) y **vuelve a preguntarle a Wompi** por la
  transaccion. Solo esa respuesta activa la suscripcion.
- Si la API responde algo distinto de `200`, Wompi reintenta a los 30 minutos,
  a las 3 horas y a las 24 horas. Un `401` en el log del webhook es una firma
  invalida: o alguien esta probando, o `WOMPI_EVENTS_SECRET` no es el del
  ambiente que esta enviando.
- Mientras el cliente espera en la pantalla de resultado, la aplicacion
  tambien reconsulta la transaccion, asi que un webhook demorado no lo deja
  esperando.
- Los reembolsos se hacen en el panel de Wompi. La aplicacion no los registra
  todavia: un pago aprobado que despues se anula o se reembolsa **no quita el
  acceso solo**; hay que retirarlo a mano (pendiente del admin de pagos).

### Job de renovaciones (Fase 4, paso 5, entrega 2)

**Desde que esta entrega se despliega con las llaves de Wompi puestas, la
pantalla de pago ofrece la renovacion automatica.** Sin el job programado, esas
suscripciones no se cobran nunca: el cliente pierde el acceso al terminar su
primer periodo sin que nadie le haya cobrado ni avisado. Hay que programarlo en
el mismo despliegue.

**Programado en Dokploy el 2026-10-13.** Como se crea (los nombres de los
campos salen del codigo fuente de Dokploy, rama `canary`, leido ese dia; pueden
variar con la version):

1. Aplicacion API -> pestana "Schedules" -> crear una tarea ("Create Schedule").
2. Task Name: `Renovaciones`. Schedule: `0 * * * *` (cada hora). Timezone:
   vacia (UTC). Shell Type: `Bash`. Command:

```
cd /app && python scripts/run_renewals.py
```

3. Guardar, dejarla habilitada y correrla una vez a mano desde la lista para
   ver el resumen en su log.

La tarea vive en la base de datos de Dokploy, no en el contenedor de la API:

- **Sobrevive a un deploy y a un reinicio del contenedor.** En cada ejecucion
  Dokploy busca el contenedor que este corriendo por el nombre de la aplicacion
  y corre el comando ahi (`docker exec`): usa el codigo y las variables del
  deploy vigente.
- **Sobrevive a un reinicio del VPS o de Dokploy**: al arrancar vuelve a cargar
  las tareas habilitadas.
- **Se pierde si se borra la aplicacion API** en Dokploy y se crea de nuevo.
- Una ejecucion que cae durante un deploy o con el VPS apagado no se repone. No
  hace falta: la siguiente corrida hace lo atrasado, de a un cobro por corrida.
- Nadie avisa si la tarea deja de correr: conviene mirar su log de vez en
  cuando.

Que hace cada corrida: avisa por correo antes de cada cobro automatico (7 dias
antes del primer intento) y antes de cada vencimiento del pago manual; cobra las
renovaciones que toquen (48 h, 24 h y 0 h antes del vencimiento); y deja
vencidas las suscripciones cuyo periodo termino. Desde el paso 6 (entrega 3)
tambien envia los avisos de un traslado de precio, hasta 40 por corrida, y
aplica cada precio nuevo cuando llega su fecha. Usa las mismas variables de
entorno de la API, incluidas las `SMTP_*`: los correos los envia el job.

Se puede correr a mano en la terminal de la API cuantas veces se quiera: es
idempotente. Dos corridas a la vez no cobran dos veces (la segunda sale diciendo
"ya hay otra corrida en curso"). La ultima linea resume lo que hizo:

```
INFO: app.renewals - Renovaciones: avisos=0 cobros=0 aprobados=0 fallidos=0 vencidas=0 errores=0 correos=0
INFO: app.renewals - Traslados de precio: avisos=0 fallidos=0 cerrados=0
```

Sale con codigo 1 si alguna suscripcion fallo (`errores` mayor que cero); el
detalle queda en el log y en el monitoreo de errores.

**Prueba contra el sandbox (2026-10-13, en local, llaves de prueba):**

- Tarjeta `4242 4242 4242 4242` escrita por el usuario en la ventana de Wompi:
  medio guardado, primer cobro aprobado, cuenta con acceso, y en la base solo
  la referencia de la fuente de pago, `VISA` y `4242`.
- Job con el vencimiento adelantado en la base de la prueba, tres corridas: la
  primera aviso por correo y no cobro; la segunda cobro a la tarjeta guardada
  (`cobros=1`); la tercera encontro el cobro aprobado, extendio el periodo un
  mes desde el vencimiento anterior y envio el recibo (`aprobados=1`).
- Tarjeta `4111 1111 1111 1111`: el medio se guarda, el cobro queda rechazado
  y la cuenta no entra.

**Prueba de la entrega 3 contra el sandbox (2026-10-13, en local):** cambiar
el medio de pago, pasar de un modo al otro, el reintento al cambiar la tarjeta
con un cobro rechazado, la exportacion y el borrado de la cuenta. El detalle
esta al final de `PLATAFORMA_COMPLETA.md` §3.15. El usuario probo ademas las
acciones de `/cuenta` con la ventana de Wompi, con tarjeta y con Nequi:

- Nequi `3992222222` guardado: el job cobro y el cobro quedo rechazado; la
  suscripcion paso a "Cobro pendiente" sin perder el acceso.
- Nequi `3991111111` guardado despues: el reintento salio de inmediato y
  quedo aprobado; el periodo se extendio.

Los numeros de prueba "de rechazo" de Wompi rechazan el cobro, no el
guardado: guardar uno de esos en `/cuenta` siempre funciona, porque ahi no se
cobra nada. Para ver el rechazo hay que cobrarle: en el alta, o adelantando el
vencimiento en una base de prueba y corriendo el job.

El 2026-10-13 la entrega 3 quedo desplegada y el usuario la probo en el VPS,
con llaves de sandbox. **Sin probar**: tarjetas con 3D Secure, y un cobro con
llaves de produccion.

### Pasar de sandbox a produccion

La URL de la API de Wompi no se configura: sale del prefijo de las llaves. Con
las cuatro de produccion (`pub_prod_`, `prv_prod_`, `prod_events_`,
`prod_integrity_`) la API usa `https://production.wompi.co/v1`, y el arranque
lo dice en el log: `Pagos: Wompi, ambiente production (...)`. La pagina de pago
no cambia de direccion: Wompi decide el ambiente por la llave publica. El
formulario de tarjeta y Nequi recibe la URL de la API de Wompi desde
`GET /billing/availability`, asi que tambien cambia solo.

1. **Antes de cambiar las llaves, retirar las suscripciones de prueba.** Las de
   renovacion automatica tienen fuentes de pago del sandbox, que en produccion
   no existen: el job intentaria cobrarles, fallaria tres veces y las dejaria
   vencidas, con correos de cobro fallido. Y todas dan acceso sin que nadie
   haya pagado. Se cancelan de inmediato desde `/admin/suscripciones`; la
   consulta para encontrarlas y la comprobacion estan en "Antes del lanzamiento
   comercial", punto 6.
2. Poner las cuatro llaves de produccion. **Las cuatro**: con llaves mezcladas
   la API no arranca, a proposito.
3. Si `WOMPI_API_BASE_URL` esta puesta con la URL del sandbox, borrarla. Si no
   coincide con las llaves, la API tampoco arranca.
4. En el panel de Wompi, **en modo produccion**, configurar la URL de eventos
   (`https://api.<dominio>/webhooks/wompi`): se guarda aparte para cada
   ambiente, y el secreto de eventos de produccion es otro.
5. Redesplegar, mirar la linea del log, y hacer un pago real de punta a punta
   antes de anunciar nada.

`PAYMENT_PROVIDER=fake` enciende una pasarela simulada (una pagina de la API
con "aprobar" y "rechazar") para desarrollo y para los tests de punta a
punta. **Nunca en produccion**: aprueba pagos sin cobrar. La API se niega a
arrancar con ella si hay llaves de produccion de Wompi, pero sin llaves no
tiene como saberlo. En desarrollo va junto con `API_PUBLIC_URL` si la API no
esta en `http://localhost:8000`.

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
usuario que revise esa carpeta. **Vuelto a probar el 2026-10-19**: en Hotmail
el correo de verificacion llego a la bandeja principal.

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
11. **Chequeo externo de disponibilidad.** El 2026-10-07 se decidio no
    tenerlo; **el 2026-10-19 el usuario decidio ponerlo antes del lanzamiento**,
    con UptimeRobot: GlitchTip vive en el mismo VPS, y si el VPS entero se cae,
    se cae con el y nadie recibe aviso. Los pasos estan en "Antes del
    lanzamiento comercial", punto 7.

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

## Antes del lanzamiento comercial (Fase 4, paso 9)

La lista de `PLATAFORMA_COMPLETA.md` §9, con el estado del 2026-10-19 en
`HOJA_DE_RUTA.md` §5. Aqui van los pasos a mano y como comprobar que quedaron
bien. El orden importa: **respaldos, monitor externo y correo primero**, llaves
de produccion al final, cuando lo demas este hecho.

Lo que no es operativo y tambien bloquea (no se resuelve aqui): los textos
legales revisados por el abogado, el responsable del tratamiento, la
facturacion electronica (contador) y lo que exige Wompi, y PCI DSS, con el
formulario de tarjeta propio (`PLATAFORMA_COMPLETA.md` §10 n.º 4, 8, 10 y 15).

### 1. Respaldos de la base y prueba de restauracion

Hoy no hay evidencia de que la base tenga respaldos: Dokploy los hace solo si
se le configura un destino S3. Es lo primero, porque sin respaldo un error de
disco o un borrado no tiene vuelta.

**Destino: un bucket privado de Cloudflare R2.** Gratis hasta 10 GB al mes;
despues, US$0,015 por GB (pagina de precios de R2, leida el 2026-10-19). Los
pasos de los dos lados salen de la guia de Dokploy "Cloudflare R2"
(`docs.dokploy.com/docs/core/cloudflare-r2`, leida el 2026-10-19); si la
version de Dokploy del VPS muestra otros nombres, valen los de la pantalla.

1. **En Cloudflare**: *R2 Object Storage* -> *Create bucket*, con un nombre como
   `sebasanalisis-respaldos`. Sin acceso publico: el respaldo tiene correos,
   pagos y datos personales.
2. *R2 Object Storage* -> *Manage API tokens* -> crear un *User API Token* con
   permiso **Object Read & Write**, **limitado a ese bucket**. Copiar el
   *Access Key ID*, el *Secret Access Key* y el *Endpoint*
   (`https://<id de la cuenta>.r2.cloudflarestorage.com`): el secreto se muestra
   una sola vez. No pegarlos en ningun chat ni archivo del repositorio.
3. **En Dokploy**, en los destinos S3 (`/dashboard/settings/destinations`):
   *Access Key Id*, *Secret Access Key*, *Endpoint*, *Bucket* y *Region*. La
   guia de Dokploy pide la region de R2 (`WNAM`, `ENAM`...); si la prueba de
   conexion falla, probar con `auto`. Probar la conexion antes de guardar.
4. **En la base de Sebasanalisis** (el servicio PostgreSQL de Dokploy, no la de
   GlitchTip) -> pestana *Backup* -> crear el respaldo:
   - *Select Destination S3 Bucket*: el destino del paso 3.
   - *Database Name*: `sebasanalisis`.
   - *Schedule Cron*: `0 8 * * *` (todos los dias a las 8:00 UTC, las 3 a. m.
     en Colombia).
   - *Prefix*: `produccion/`.
   - *Enabled*: encendido.
5. Usar *Test* y comprobar en el bucket de R2 que aparecio un archivo bajo
   `produccion/`.
6. **Cuanto se guarda**: si la pantalla del respaldo tiene un campo para
   conservar las ultimas N copias, poner `14`. Si no lo tiene, en el bucket de
   R2 crear una regla de ciclo de vida que borre los objetos de mas de 30 dias.
   Sin ninguna de las dos, los respaldos se acumulan (es poco espacio, pero son
   datos personales guardados sin plazo).

**Prueba de restauracion, sin tocar la base de produccion.** Se restaura en una
base aparte y se comparan cifras. **Nunca se usa *Restore* desde la pestana
*Backup* de la base de produccion**: restauraria encima de los datos vigentes.

1. En el mismo proyecto de Dokploy, crear un servicio PostgreSQL 16 nuevo,
   `sebasanalisis-restauracion`, con una contrasena cualquiera. No se conecta a
   ninguna aplicacion.
2. En **ese** servicio nuevo: pestana *Backup* -> *Restore*:
   - *Select Source S3 Bucket*: el destino de R2.
   - *Search for Backup File*: escribir `produccion/` y elegir el mas reciente.
   - *Database Name*: `sebasanalisis`.
   - *Restore*.
3. En la terminal de cada una de las dos bases (produccion y la restaurada),
   correr lo mismo y comparar:

   ```
   psql -U <usuario> -d sebasanalisis -c "select version_num from alembic_version;"
   psql -U <usuario> -d sebasanalisis -c "select (select count(*) from users) usuarios, (select count(*) from subscriptions) suscripciones, (select count(*) from payments) pagos, (select count(*) from spins) giros, (select max(created_at) from payments) ultimo_pago;"
   ```

   Tiene que coincidir la version de la migracion, y las cifras tienen que ser
   iguales o un poco menores en la restaurada (lo que entro despues del
   respaldo). Si la restaurada esta vacia o falla, el respaldo no sirve: se
   revisa antes de seguir.
4. Borrar el servicio `sebasanalisis-restauracion`: tiene una copia de los datos
   personales y no hace falta.
5. Anotar la fecha de la prueba en `HOJA_DE_RUTA.md` §5 (paso 9). Repetirla
   cada vez que cambie la version de PostgreSQL o el destino.

### 2. Resend Pro y `EMAIL_DAILY_LIMIT`

Con 300 a 800 registros al abrir, el plan gratuito (100 correos al dia) deja a
gente sin correo de verificacion. Y el aviso legal (§6.7) envia hasta la mitad
del tope por dia.

1. En el panel de Resend, en facturacion, pasar al plan **Pro**: US$20 al mes
   por 50.000 correos, sin tope diario; el excedente se cobra por miles
   (pagina de precios de Resend, leida el 2026-10-19).
2. En *Environment* de la API: `EMAIL_DAILY_LIMIT=1500`. Es un freno ante un
   abuso del registro, no la cuota: 50.000 al mes son unos 1.600 al dia.
   Redesplegar la API. El job de renovaciones lee la misma variable.
3. Comprobacion: registrar una cuenta con un correo propio y ver el correo en la
   tabla *Emails* de Resend; en el log de la API no debe aparecer "Tope diario de
   correos alcanzado". El plan vigente se ve en la facturacion de Resend.

El contador del tope vive en memoria y por proceso: la API y el job llevan cada
uno el suyo y un redespliegue lo pone en cero. Por eso no es un limite exacto.
El aviso legal no depende de ese contador: cuenta sus envios en la base.

### 3. Correo: SPF, DKIM, DMARC y la entrega en Hotmail

Configurados el 2026-10-07 (ver "Correo"). Antes de abrir, comprobar que siguen
asi y repetir la prueba en Hotmail, donde el correo llego a no deseado.

1. En el panel de Resend, *Domains*: `correo.sebasanalisis.com` en *Verified*.
2. Desde cualquier equipo:

   ```
   nslookup -type=TXT _dmarc.sebasanalisis.com
   nslookup -type=TXT resend._domainkey.correo.sebasanalisis.com
   nslookup -type=TXT send.correo.sebasanalisis.com
   ```

   Deben responder `v=DMARC1; p=none;`, la clave `p=...` del panel de Resend y el
   `v=spf1 ...`, respectivamente.
3. Registrar una cuenta con un correo de Gmail y otra con uno de Hotmail u
   Outlook. En Gmail, "Mostrar original": SPF, DKIM y DMARC en `PASS`.
4. En Hotmail, si llega a no deseado: marcarlo como "No es correo no deseado" y
   repetir unos dias despues. Las pantallas ya le dicen al usuario que revise
   esa carpeta. Subir el DMARC a `p=quarantine` solo con reportes (`rua`), que
   hoy no hay.

### 4. Job de renovaciones: comprobar que sigue corriendo

Programado el 2026-10-13 (ver "Job de renovaciones"). Nadie avisa si deja de
correr.

1. Dokploy -> aplicacion API -> *Schedules* -> "Renovaciones": habilitada, con
   `0 * * * *`.
2. Abrir el log de la ultima ejecucion: debe ser de la ultima hora y terminar
   con tres lineas, `Renovaciones: ...`, `Traslados de precio: ...` y, desde el
   paso 9, `Avisos legales: ...`.
3. Correrla una vez a mano desde la lista y ver las mismas tres lineas.

### 5. Formulario de tarjeta y Nequi en el VPS (sandbox)

**Probado el 2026-10-19 por el usuario**: el alta con la tarjeta `4242` quedo
aprobada y el cambio a Nequi funciono. Los pasos, por si hay que repetirlo con
las llaves de sandbox, desde `https://sebasanalisis.com`:

1. Cuenta nueva, correo confirmado -> `/planes` -> "Suscribirme" -> "Renovacion
   automatica" -> aceptar los dos documentos de Wompi -> tarjeta
   `4242 4242 4242 4242`, vencimiento futuro, CVC de 3 digitos. Debe terminar en
   "Pago aprobado" y entrar a la mesa.
2. En `/cuenta`, "Cambiar el medio de pago" con el Nequi `3991111111`: sale la
   espera de la aprobacion y despues la caja verde "Medio de pago actualizado:
   Nequi".
3. En el log de la API no debe aparecer ningun dato de la tarjeta, y en
   GlitchTip tampoco.
4. Esta cuenta es de prueba: se retira con las demas en el paso 6.

### 6. Llaves de produccion de Wompi

**Al final**, con lo anterior hecho, Wompi habiendo aprobado el comercio para
produccion y la respuesta de Wompi sobre PCI DSS (§10 n.º 15). El procedimiento
esta en "Pasar de sandbox a produccion" (seccion "Pagos con Wompi"). Lo que se
agrega:

1. **Listar las suscripciones de prueba**, en la terminal de la base:

   ```
   select u.email, s.status, s.renewal_mode, s.current_period_end
   from subscriptions s join users u on u.id = s.user_id
   where s.status in ('pending', 'active', 'past_due', 'canceled');
   ```

   Con llaves de sandbox todas son de prueba. A cada una: en
   `/admin/suscripciones`, "Cancelar de inmediato", con el motivo "Suscripcion
   de prueba del sandbox". Quita el acceso y la referencia del medio de pago, y
   deja su fila en la bitacora. Repetir la consulta: no debe quedar ninguna
   `active`, `past_due` ni `canceled` con el periodo vigente.
2. Cambiar las cuatro llaves y redesplegar, como dice esa seccion. El log de
   arranque debe decir `Pagos: Wompi, ambiente production
   (https://production.wompi.co/v1)`.
3. `https://api.sebasanalisis.com/billing/availability` debe responder la llave
   `pub_prod_...` y `"api_base_url": "https://production.wompi.co/v1"`.
4. URL de eventos en el panel de Wompi, **en modo produccion**:
   `https://api.sebasanalisis.com/webhooks/wompi`.
5. **Un pago real pequeno de punta a punta.** En `/admin/descuentos`, un cupon
   del 99 % para el plan mensual, con un solo uso: el cobro queda en 1.000 COP.
   La documentacion leida no dice el monto minimo de Wompi: si rechaza uno tan
   bajo, usar un porcentaje menor.
   Suscribirse con una tarjeta propia en renovacion automatica, ver "Pago
   aprobado", el correo de bienvenida y el pago en `/admin/pagos`. Despues:
   desactivar el cupon, cancelar esa suscripcion desde el admin, reembolsar el
   pago en el panel de Wompi y registrarlo en `/admin/pagos`.
6. Mirar el log del webhook en el panel de Wompi: la respuesta debe ser `200`.

### 7. Monitor externo de disponibilidad (UptimeRobot)

Decidido el 2026-10-19. GlitchTip avisa de errores, pero vive en el mismo VPS:
si el VPS se cae, nadie se entera. Un servicio de afuera revisa cada pocos
minutos que la aplicacion responda y avisa por correo si no.

**Plan**: el gratuito de UptimeRobot da 50 monitores, revisa cada 5 minutos y
avisa por correo (pagina de precios, leida el 2026-10-19). La misma pagina lo
describe "para proyectos de hobby y sin fines de lucro": antes de depender de
el, revisar sus terminos de servicio, y si no admiten un producto por
suscripcion, pasar al plan pago mas barato. Los nombres de los campos pueden
variar con la version de su panel.

1. Crear la cuenta en `uptimerobot.com` con el correo que tiene que recibir los
   avisos, y confirmarlo. Si se usa el de soporte
   (`sebas.analisis.ia.com@gmail.com`), el aviso llega al mismo lugar que las
   consultas de los clientes.
2. *Add New Monitor*, tipo **HTTP(s)**:
   - Nombre: `API - health`.
   - URL: `https://api.sebasanalisis.com/health`.
   - Intervalo: 5 minutos.
   - Contacto de alerta: el correo del paso 1.
3. Otro igual para el sitio:
   - Nombre: `Web`.
   - URL: `https://sebasanalisis.com`.
4. No hace falta vigilar `errores.sebasanalisis.com`: si cae solo GlitchTip, la
   aplicacion sigue funcionando.

**Configurado y comprobado el 2026-10-19** por el usuario: los dos monitores quedaron en verde, y con la API detenida llegaron los correos de *Down* y de *Up*. Los terminos de UptimeRobot, revisados por el usuario, admiten el plan gratuito para este uso.

**Comprobacion**:

- Los dos monitores aparecen en verde (*Up*) a los pocos minutos.
- Prueba de una caida, en un horario sin usuarios: en Dokploy, detener la
  aplicacion API (*Stop*). En 5 a 10 minutos tiene que llegar el correo de
  *Down*. Volver a iniciarla (*Start*) y esperar el correo de *Up*. Si no
  llega nada, revisar el contacto de alerta y la carpeta de no deseado.

## Antes del primer despliegue

- El repositorio **no** debe llevar `backend/.env`: tiene la clave JWT y la del
  administrador. Ya esta en `.gitignore`; verificalo con `git status` antes del
  primer commit.
- `docker-compose.yml` de la raiz es solo para desarrollo local. En el VPS no
  se usa.
