# API de Sebasanalisis.
#
# Imagen slim + wheels: psycopg[binary], numpy y scipy traen binarios
# precompilados, asi que no hace falta cadena de compilacion en la imagen.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Las dependencias van en su propia capa: cambian mucho menos que el codigo,
# asi un despliegue normal no reinstala scipy.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El bit de ejecucion se pone aqui y no se hereda del repositorio: Git en
# Windows no guarda permisos, asi que el archivo llega al build sin +x.
RUN chmod +x ./docker-entrypoint.sh

# Usuario sin privilegios: si la API se ve comprometida, no es root en el contenedor.
RUN useradd --create-home --uid 1000 sebas && chown -R sebas:sebas /app
USER sebas

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
