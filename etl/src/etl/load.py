"""Carga en PostgreSQL con COPY (rápido) dentro de una sola transacción."""
import io
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("etl")


def ejecutar_ddl(cur, carpeta: str):
    for f in sorted(Path(carpeta).glob("*.sql")):
        log.info("DDL %s", f.name)
        cur.execute(f.read_text(encoding="utf-8"))


def copiar(cur, tabla: str, df: pd.DataFrame, columnas: list):
    """COPY de un DataFrame a una tabla; NaN/None se escriben como NULL."""
    buf = io.StringIO()
    d = df[columnas].copy()
    for c in d.columns:  # enteros guardados como float por los NULL (1.0 → 1)
        if d[c].dtype.kind == "f":
            v = d[c].dropna()
            if len(v) and (v == v.round()).all():
                d[c] = d[c].astype("Int64")
        elif d[c].dtype == object:
            v = d[c].dropna()
            if len(v) and v.map(lambda x: isinstance(x, float) and x == int(x)).all():
                d[c] = d[c].astype("Float64").astype("Int64")
    d.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cur.copy_expert(
        f"COPY {tabla} ({', '.join(columnas)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf
    )
    log.info("  %-32s %9d filas", tabla, len(df))
