"""SolarBI · Simulador de telemetría (streaming).

Corre como CronJob de Kubernetes cada minuto. En cada ejecución:
  1. Busca el último minuto insertado en gold.fact_lectura_rt.
  2. Inserta todos los minutos que falten hasta "ahora" (si una ejecución se pierde, la
     siguiente se pone al día). Si la tabla está vacía, rellena BACKFILL_MIN minutos.
  3. Cada minuto nuevo es una REPETICIÓN de un minuto real del histórico (silver.lectura_minuto)
     desplazado DESFASE_DIAS hacia atrás: los datos tienen el comportamiento real de la microrred.
  4. Si el ConfigMap trae MODO_FALLA, altera los datos para demostrar las alertas:
       - corte_red : tensión de red 0 V y la batería asume la carga
       - soc_bajo  : el SoC cae por debajo del umbral de alerta
Todos los parámetros llegan por variables de entorno (ConfigMap + Secret).
Es idempotente: UNIQUE (cod_inversor, ts) + ON CONFLICT DO NOTHING.
"""
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [simulador] %(message)s", stream=sys.stdout)
log = logging.getLogger("sim")

DESFASE_DIAS = int(os.getenv("DESFASE_DIAS", "365"))
BACKFILL_MIN = int(os.getenv("BACKFILL_MIN", "180"))
MAX_MIN_POR_CORRIDA = int(os.getenv("MAX_MIN_POR_CORRIDA", "240"))
MODO_FALLA = os.getenv("MODO_FALLA", "ninguno").strip().lower()
INVERSOR_FALLA = int(os.getenv("INVERSOR_FALLA", "1"))
SOC_FALLA = float(os.getenv("SOC_FALLA", "12"))


def conectar():
    return psycopg2.connect(host=os.getenv("PGHOST", "postgres"), port=int(os.getenv("PGPORT", "5432")),
                            dbname=os.getenv("PGDATABASE", "solarbi"), user=os.getenv("PGUSER", "simulador"),
                            password=os.getenv("PGPASSWORD", ""))


def minuto_historico(cur, inversor: int, ts_destino: datetime):
    """Busca el minuto real más cercano (hasta 10 min antes) un año atrás; si no hay, intenta 2 años."""
    for dias in (DESFASE_DIAS, DESFASE_DIAS + 7, DESFASE_DIAS - 7):
        origen = ts_destino - timedelta(days=dias)
        cur.execute(
            """SELECT pv_w, carga_w, red_w, bat_w, soc_pct, red_v_min
               FROM silver.lectura_minuto
               WHERE inversor = %s AND ts_minuto BETWEEN %s - INTERVAL '10 minutes' AND %s
                 AND pv_w IS NOT NULL
               ORDER BY ts_minuto DESC LIMIT 1""", (inversor, origen, origen))
        fila = cur.fetchone()
        if fila:
            return list(fila)
    return None


def aplicar_falla(inversor: int, f: list) -> list:
    if MODO_FALLA == "ninguno" or inversor != INVERSOR_FALLA:
        return f
    pv, carga, red, bat, soc, red_v = f
    if MODO_FALLA == "corte_red":
        red, red_v = 0.0, 0.0
        bat = max(0.0, float(carga or 0) - float(pv or 0))  # la batería cubre lo que el sol no alcanza
    elif MODO_FALLA == "soc_bajo":
        soc = SOC_FALLA
    return [pv, carga, red, bat, soc, red_v]


def main():
    ahora = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    con = conectar()
    insertadas = 0
    with con, con.cursor() as cur:
        for inversor in (1, 2):
            cur.execute("SELECT MAX(ts) FROM gold.fact_lectura_rt WHERE cod_inversor = %s", (inversor,))
            ultimo = cur.fetchone()[0]
            desde = (ahora - timedelta(minutes=BACKFILL_MIN)) if ultimo is None else ultimo + timedelta(minutes=1)
            desde = max(desde, ahora - timedelta(minutes=MAX_MIN_POR_CORRIDA))
            ts = desde
            while ts <= ahora:
                f = minuto_historico(cur, inversor, ts)
                if f:
                    # la falla solo afecta los minutos recientes (no reescribe el relleno inicial)
                    origen = "simulador"
                    if ts >= ahora - timedelta(minutes=5):
                        f2 = aplicar_falla(inversor, f)
                        if f2 is not f:
                            f, origen = f2, f"falla:{MODO_FALLA}"
                    cur.execute(
                        """INSERT INTO gold.fact_lectura_rt
                           (cod_inversor, ts, pv_w, carga_w, red_w, bat_w, soc_pct, red_v, origen)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (inversor, ts, *f, origen))
                    insertadas += cur.rowcount
                ts += timedelta(minutes=1)
    con.close()
    log.info("Minutos insertados: %d · hasta %s · modo de falla: %s (inversor %s)",
             insertadas, ahora.isoformat(), MODO_FALLA, INVERSOR_FALLA)


if __name__ == "__main__":
    main()
