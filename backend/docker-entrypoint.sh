#!/bin/sh
# Arranque de la API en produccion.
#
# Las migraciones corren aqui y no en un paso aparte porque Dokploy despliega
# el contenedor sin darnos un hook previo: si el codigo nuevo espera una columna
# nueva, la unica forma de garantizar que existe antes del primer request es
# aplicarla justo antes de levantar el servidor. `alembic upgrade head` es
# idempotente: si no hay nada pendiente, no hace nada.
set -e

echo "Aplicando migraciones..."
alembic upgrade head

# El seed NO corre solo en cada despliegue: reactiva (`active=True`) las
# variantes de ruleta, asi que pisaria en silencio una variante que el
# administrador haya desactivado a proposito. Se corre a mano la primera vez,
# o poniendo RUN_SEED=1 de forma deliberada.
if [ "$RUN_SEED" = "1" ]; then
  echo "Corriendo seed..."
  python -m app.db.seed
fi

echo "Levantando API en el puerto 8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
