# Imagen del simulador: solo necesita psycopg2 → python:3.12-slim (~130 MB).
#   docker build -t solarbi-simulador:1.0 simulador/
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY simulador.py .
RUN useradd --uid 10001 --no-create-home sim
USER 10001
CMD ["python", "simulador.py"]
