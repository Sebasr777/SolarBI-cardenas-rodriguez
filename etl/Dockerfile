# Imagen del ETL. Contexto de construcción: la raíz del repositorio.
#   docker build -f etl/Dockerfile -t solarbi-etl:1.0 .
# Base python:3.12-slim (Debian): ~130 MB. Se descarta python:3.12 (~1 GB, trae compiladores
# que no se usan) y python:3.12-alpine (musl: pandas/numpy no tienen ruedas listas y habría
# que compilarlos, lo que hace la imagen más grande y lenta de construir).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DIR_SQL=/app/sql/ddl

WORKDIR /app
COPY etl/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY etl/src/ /app/
COPY sql/ddl/ /app/sql/ddl/

# Usuario sin privilegios: el contenedor no corre como root
RUN useradd --uid 10001 --no-create-home etl
USER 10001

# La fuente (capa Bronze) NO va dentro de la imagen: se monta en /datos/bronze (solo lectura)
CMD ["python", "-m", "etl.main"]
