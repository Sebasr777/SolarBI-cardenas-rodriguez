"""SolarBI · ETL de OpenCEM (Bronze → Silver → Gold).

Uso:  python -m etl.main
Corre una vez y termina (en Kubernetes es un Job). Es IDEMPOTENTE: recrea silver y gold
dentro de una sola transacción y calcula una huella (md5) de los totales de gold; si se
ejecuta dos veces con la misma fuente, la huella es idéntica.
"""
import hashlib
import logging
import os
import sys
import time

import pandas as pd
import psycopg2

from . import config, extract, gold, transform
from .calidad import Bitacora
from .conciliacion import calcular as conciliar
from .load import copiar, ejecutar_ddl

logging.basicConfig(level=logging.INFO, format="%(asctime)s [etl] %(message)s", stream=sys.stdout)
log = logging.getLogger("etl")


def huella(h, e, act) -> str:
    tot = (round(float(h.e_solar_kwh.sum()), 3), round(float(h.e_carga_kwh.sum()), 3),
           round(float(h.e_red_kwh.sum()), 3), len(h), len(e), len(act))
    return hashlib.md5(str(tot).encode()).hexdigest()


def main():
    t0 = time.time()
    fuente = config.FUENTE_SQLITE
    if not os.path.exists(fuente):
        log.error("No se encuentra la fuente %s (capa Bronze). Revise el montaje del volumen.", fuente)
        sys.exit(2)
    sha = None
    if config.VERIFICAR_SHA:
        log.info("Verificando SHA-256 de la fuente…")
        sha = extract.sha256(fuente)
        if sha != config.SHA256_ESPERADO:
            log.error("SHA-256 no coincide (%s). La fuente está corrupta o es otra versión.", sha)
            sys.exit(3)
        log.info("SHA-256 OK: %s", sha)

    bit = Bitacora()
    con_s = extract.conectar()
    inv = extract.inventario(con_s)
    log.info("Inventario Bronze:\n%s", inv.to_string(index=False))

    # ---------------- Extract + Transform ----------------
    a = extract.leer_analog(con_s)
    n_bronze = len(a)
    a = transform.limpiar_lecturas(a, bit)
    gaps = transform.huecos(a, bit)
    s = transform.agregar_minuto(a, extract.leer_alarmas(con_s))
    ctx = transform.procesar_contexto(extract.leer_contexto(con_s), bit)
    eventos = transform.detectar_eventos(s, gaps, ctx, bit)
    cont = transform.contadores_diarios(extract.leer_contadores(con_s), bit)
    vers = transform.historia_config(extract.leer_settings(con_s), bit)
    con_s.close()

    # ---------------- Gold ----------------
    tel_ini = s.ts_minuto.min().tz_convert(config.ZONA_LOCAL).date()
    tel_fin = s.ts_minuto.max().tz_convert(config.ZONA_LOCAL).date()
    t_ini = min(tel_ini, ctx.inicio.min().tz_convert(config.ZONA_LOCAL).date())
    t_fin = max(tel_fin, ctx.fin.max().tz_convert(config.ZONA_LOCAL).date())
    dfecha = gold.dim_fecha(t_ini, t_fin, tel_ini, tel_fin)
    dhora = gold.dim_hora()
    dinv = gold.dim_inversor(vers, pd.Timestamp('2000-01-01', tz='UTC').timestamp())  # 1.ª versión: desde siempre
    h = gold.fact_energia_hora(s, dinv)
    dte = gold.dim_tipo_evento()
    fe = gold.fact_evento(eventos, dte, dinv)
    dtc, ddisp = gold.dims_contexto(ctx)
    fa = gold.fact_actividad(ctx, dtc, ddisp, dinv)
    fc = gold.fact_contador(cont, dinv)
    concil = conciliar(n_bronze, bit, a, s, h, cont, len(ctx), len(ctx))
    hu = huella(h, fe, fa)

    # ---------------- Load (una sola transacción) ----------------
    pg = psycopg2.connect(**config.PG)
    try:
        with pg:
            with pg.cursor() as cur:
                cur.execute("CREATE SCHEMA IF NOT EXISTS audit")
                cur.execute(open(os.path.join(config.DIR_SQL, "06_auditoria_permisos.sql"), encoding="utf-8").read()
                            .split("-- Permisos")[0])
                cur.execute("INSERT INTO audit.etl_corrida (archivo_fuente, sha256_fuente, filas_leidas) "
                            "VALUES (%s,%s,%s) RETURNING id_corrida", (os.path.basename(fuente), sha, n_bronze))
                id_corrida = cur.fetchone()[0]
        with pg:
            with pg.cursor() as cur:
                ejecutar_ddl(cur, config.DIR_SQL)
                log.info("Cargando Silver…")
                copiar(cur, "silver.lectura_minuto", s,
                       ["inversor", "ts_minuto", "n_lecturas", "n_validas", "pv_w", "carga_w", "red_w", "bat_w",
                        "soc_pct", "bat_v", "red_v_min", "salida_v", "alarma_activa", "seg_cubiertos", "e_solar_wh",
                        "e_carga_wh", "e_red_wh", "e_bat_carga_wh", "e_bat_descarga_wh"])
                copiar(cur, "silver.contexto", ctx,
                       ["id_contexto", "registrado", "inicio", "fin", "fuente", "tipo_contexto", "dispositivo",
                        "inversor", "valor"])
                copiar(cur, "silver.contador_diario", cont,
                       ["inversor", "fecha_local", "pv_kwh", "carga_kwh", "carga_desde_red_kwh", "red_a_bateria_kwh",
                        "bat_carga_kwh", "bat_descarga_kwh"])
                v2 = vers.assign(valido_desde=pd.to_datetime(vers.desde, unit="s", utc=True)).rename(columns={
                    "battpackrateah": "bateria_ah", "maxlinepower": "max_red_w", "chgpriority": "prioridad_carga",
                    "batsoclowalarm": "soc_alarma_pct", "inv2linesoc": "soc_a_red_pct"})
                copiar(cur, "silver.config_inversor", v2,
                       ["inversor", "valido_desde", "bateria_ah", "max_red_w", "prioridad_carga", "soc_alarma_pct",
                        "soc_a_red_pct"])
                log.info("Cargando Gold…")
                copiar(cur, "gold.dim_fecha", dfecha, list(dfecha.columns))
                copiar(cur, "gold.dim_hora", dhora, list(dhora.columns))
                copiar(cur, "gold.dim_inversor", dinv, list(dinv.columns))
                copiar(cur, "gold.dim_tipo_evento", dte, list(dte.columns))
                dtc_ = pd.concat([dtc, pd.DataFrame([dict(sk_tipo_contexto=-1, tipo_contexto="desconocido",
                                                          fuente="n/d", categoria="n/d", es_carga=False)])])
                ddisp_ = pd.concat([ddisp, pd.DataFrame([dict(sk_dispositivo=-1, dispositivo="desconocido",
                                                              tipo="n/d")])])
                copiar(cur, "gold.dim_tipo_contexto", dtc_, list(dtc_.columns))
                copiar(cur, "gold.dim_dispositivo", ddisp_, list(ddisp_.columns))
                copiar(cur, "gold.fact_energia_hora", h,
                       ["sk_fecha", "sk_hora", "sk_inversor", "ts_hora_utc", "e_solar_kwh", "e_carga_kwh",
                        "e_red_kwh", "e_bat_carga_kwh", "e_bat_descarga_kwh", "soc_prom_pct", "soc_min_pct",
                        "minutos_con_dato", "minutos_red_ok", "lecturas_total", "lecturas_validas"])
                copiar(cur, "gold.fact_evento", fe,
                       ["sk_tipo_evento", "sk_inversor", "sk_fecha", "sk_hora", "inicio_utc", "fin_utc",
                        "duracion_min", "valor_extremo", "descripcion"])
                copiar(cur, "gold.fact_actividad", fa,
                       ["id_contexto", "sk_tipo_contexto", "sk_dispositivo", "sk_inversor", "sk_fecha", "sk_hora",
                        "inicio_utc", "fin_utc", "duracion_min", "nucleos_cpu", "es_gpu", "carga_estimada"])
                copiar(cur, "gold.fact_contador_diario", fc,
                       ["sk_fecha", "sk_inversor", "pv_kwh", "carga_kwh", "carga_desde_red_kwh", "bat_carga_kwh",
                        "bat_descarga_kwh"])
                reglas = pd.DataFrame([r.__dict__ for r in bit.reglas]).assign(id_corrida=id_corrida)
                copiar(cur, "audit.regla_calidad", reglas, ["id_corrida", "regla", "descripcion", "dimension_dq",
                                                            "tratamiento", "filas_antes", "afectadas", "filas_despues"])
                copiar(cur, "audit.conciliacion", concil.assign(id_corrida=id_corrida),
                       ["id_corrida", "metrica", "total_fuente", "total_cargado", "diferencia", "diferencia_pct",
                        "explicacion"])
                n_gold = len(h) + len(fe) + len(fa) + len(fc)
                cur.execute("UPDATE audit.etl_corrida SET fin = now(), estado = 'ok', filas_gold = %s, "
                            "huella_resultado = %s, mensaje = %s WHERE id_corrida = %s",
                            (n_gold, hu, f"{time.time() - t0:.0f} s", id_corrida))
    except Exception as exc:  # la transacción de datos se deshace sola; se deja constancia del fallo
        log.exception("ETL falló; se hizo rollback de silver y gold")
        with pg, pg.cursor() as cur:
            cur.execute("UPDATE audit.etl_corrida SET fin = now(), estado = 'error', mensaje = %s "
                        "WHERE id_corrida = (SELECT max(id_corrida) FROM audit.etl_corrida)", (str(exc)[:500],))
        raise
    finally:
        pg.close()

    log.info("Reglas de calidad:\n%s", pd.DataFrame([r.__dict__ for r in bit.reglas])
             [["regla", "tratamiento", "filas_antes", "afectadas", "filas_despues"]].to_string(index=False))
    log.info("Conciliación:\n%s", concil[["metrica", "total_fuente", "total_cargado", "diferencia_pct"]]
             .to_string(index=False))
    log.info("Huella del resultado (idempotencia): %s", hu)
    log.info("ETL terminado en %.0f s", time.time() - t0)
    if config.DIR_REPORTES:
        os.makedirs(config.DIR_REPORTES, exist_ok=True)
        inv.to_csv(os.path.join(config.DIR_REPORTES, "inventario_bronze.csv"), index=False)
        pd.DataFrame([r.__dict__ for r in bit.reglas]).to_csv(
            os.path.join(config.DIR_REPORTES, "reglas_calidad.csv"), index=False)
        concil.to_csv(os.path.join(config.DIR_REPORTES, "conciliacion.csv"), index=False)


if __name__ == "__main__":
    main()
