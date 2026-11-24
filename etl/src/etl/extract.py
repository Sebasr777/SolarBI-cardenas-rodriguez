"""Extracción desde la capa Bronze (SQLite de OpenCEM).

El archivo se abre en modo solo lectura (`mode=ro`): la capa Bronze nunca se modifica.
Solo se leen las columnas que el modelo necesita.
"""
import hashlib
import logging
import sqlite3

import pandas as pd

from . import config

log = logging.getLogger("etl")

COLUMNAS_ANALOG = [
    "read_ts", "inverter", "battvolt", "battcurr", "battsoc", "pv1volt", "pv1curr", "pv1power",
    "outvolta", "outw_a", "outva_a", "linevolta", "linepowerw_a", "gridpowerw_a",
    "temper1", "temper2", "temper3", "temper4",
]


def sha256(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def conectar() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{config.FUENTE_SQLITE}?mode=ro&immutable=1", uri=True)


def inventario(con) -> pd.DataFrame:
    """Tablas, filas y periodo que cubre cada una (evidencia para el informe)."""
    filas = []
    for (tabla,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        n = con.execute(f'SELECT COUNT(*) FROM "{tabla}"').fetchone()[0]
        cols = [r[1] for r in con.execute(f'PRAGMA table_info("{tabla}")')]
        campo_t = "read_ts" if "read_ts" in cols else ("start" if "start" in cols else None)
        ini = fin = None
        if campo_t:
            ini, fin = con.execute(
                f'SELECT datetime(MIN("{campo_t}"),"unixepoch"), datetime(MAX("{campo_t}"),"unixepoch") FROM "{tabla}"'
            ).fetchone()
        filas.append(dict(tabla=tabla, columnas=len(cols), filas=n, desde_utc=ini, hasta_utc=fin))
    return pd.DataFrame(filas)


def leer_analog(con) -> pd.DataFrame:
    log.info("Leyendo analog_measurements…")
    return pd.read_sql(f"SELECT {', '.join(COLUMNAS_ANALOG)} FROM analog_measurements", con)


def leer_alarmas(con) -> pd.DataFrame:
    log.info("Leyendo status (banderas de alarma)…")
    return pd.read_sql("SELECT read_ts, inverter, sysalarmflag FROM status", con)


def leer_contadores(con) -> pd.DataFrame:
    log.info("Leyendo statistics (contadores diarios)…")
    return pd.read_sql(
        "SELECT read_ts, inverter, pvgeneratenergytoday, usedenergytoday, loadconsumlinetday, "
        "linechgenergytday, batchgenergytoday, batdischgenergytoday FROM statistics",
        con,
    )


def leer_settings(con) -> pd.DataFrame:
    log.info("Leyendo settings (configuración del inversor)…")
    return pd.read_sql(
        "SELECT read_ts, inverter, battpackrateah, maxlinepower, chgpriority, batsoclowalarm, inv2linesoc "
        "FROM settings",
        con,
    )


def leer_contexto(con) -> pd.DataFrame:
    log.info("Leyendo context (JSON)…")
    return pd.read_sql('SELECT id, recorded, start, "end" AS fin, value FROM context', con)
