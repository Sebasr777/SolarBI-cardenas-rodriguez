"""Configuración del ETL: todo llega por variables de entorno.

En Kubernetes, los valores no sensibles vienen del ConfigMap `solarbi-config`
y las credenciales del Secret `solarbi-secret`. Nada queda dentro de la imagen.
"""
import os

# Fuente (capa Bronze): archivo SQLite de OpenCEM, montado de solo lectura
FUENTE_SQLITE = os.getenv("FUENTE_SQLITE", "/datos/bronze/opencem-v1.0.0.sqlite")
# SHA-256 publicado por los autores para el .sqlite descomprimido (validation_results.json)
SHA256_ESPERADO = os.getenv(
    "SHA256_ESPERADO", "5fe1f213a4a6804cdfc75f6173f437772c918f45dc0f127eb7e8936c2c2d9fbb"
)
VERIFICAR_SHA = os.getenv("VERIFICAR_SHA", "true").lower() == "true"

# Conexión a PostgreSQL (el servicio se encuentra por nombre: "postgres")
PG = dict(
    host=os.getenv("PGHOST", "postgres"),
    port=int(os.getenv("PGPORT", "5432")),
    dbname=os.getenv("PGDATABASE", "solarbi"),
    user=os.getenv("PGUSER", "etl_admin"),
    password=os.getenv("PGPASSWORD", ""),
)

DIR_SQL = os.getenv("DIR_SQL", "/app/sql/ddl")
DIR_CONFIG = os.getenv("DIR_CONFIG", "/app/config")
DIR_REPORTES = os.getenv("DIR_REPORTES", "")  # opcional: carpeta donde escribir los reportes

ZONA_LOCAL = "Asia/Shanghai"  # la microrred está en Shenzhen (UTC+8)

# Umbrales de calidad y de eventos (no sensibles; vienen del ConfigMap)
UMBRAL_RED_V = float(os.getenv("UMBRAL_RED_V", "180"))          # red disponible si V >= 180
UMBRAL_SOC_BAJO = float(os.getenv("UMBRAL_SOC_BAJO", "15"))     # alarma propia del inversor
UMBRAL_SALIDA_V = float(os.getenv("UMBRAL_SALIDA_V", "100"))    # inversor sin salida AC
HUECO_SEG = float(os.getenv("HUECO_SEG", "600"))                # hueco de datos > 10 min
DT_MAX_INTEGRACION = 60.0                                       # s: no se integra a través de huecos
CAPACIDAD_SUPUESTA_AH = float(os.getenv("CAPACIDAD_SUPUESTA_AH", "200"))
TENSION_NOMINAL_BAT_V = float(os.getenv("TENSION_NOMINAL_BAT_V", "51.2"))
