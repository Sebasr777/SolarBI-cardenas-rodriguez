"""Construcción de la capa Gold (dimensiones y hechos) a partir de Silver."""
import numpy as np
import pandas as pd

from . import config
from .transform import TIPOS_EVENTO

TZ = config.ZONA_LOCAL
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
PRIORIDAD = {0: "Solar primero", 1: "Solar y red", 2: "Solar y red", 3: "Solo solar"}


def dim_fecha(desde, hasta, tel_ini, tel_fin) -> pd.DataFrame:
    f = pd.date_range(desde, hasta, freq="D")
    d = pd.DataFrame({"fecha": f.date})
    d["sk_fecha"] = f.strftime("%Y%m%d").astype(int)
    d["anio"], d["mes"], d["dia_mes"] = f.year, f.month, f.day
    d["trimestre"] = f.quarter
    d["mes_nombre"] = [MESES[m - 1] for m in f.month]
    d["anio_mes"] = f.strftime("%Y-%m")
    d["semana_iso"] = f.isocalendar().week.values
    d["dia_semana_num"] = f.dayofweek + 1
    d["dia_semana"] = [DIAS[x] for x in f.dayofweek]
    d["es_fin_semana"] = f.dayofweek >= 5
    d["estacion"] = np.select([f.month.isin([12, 1, 2]), f.month.isin([3, 4, 5]), f.month.isin([6, 7, 8])],
                              ["invierno", "primavera", "verano"], "otoño")
    d["temporada_lluvia"] = f.month.isin(range(4, 10))
    d["con_telemetria"] = (d.fecha >= tel_ini) & (d.fecha <= tel_fin)
    d.loc[len(d)] = dict(fecha=pd.Timestamp("1900-01-01").date(), sk_fecha=-1, anio=1900, mes=1, dia_mes=1,
                         trimestre=1, mes_nombre="desconocido", anio_mes="1900-01", semana_iso=1,
                         dia_semana_num=1, dia_semana="lunes", es_fin_semana=False, estacion="n/d",
                         temporada_lluvia=False, con_telemetria=False)
    return d


def dim_hora() -> pd.DataFrame:
    h = pd.DataFrame({"sk_hora": range(24)})
    h["hora"] = h.sk_hora
    h["etiqueta"] = h.hora.map(lambda x: f"{x:02d}:00")
    h["franja"] = pd.cut(h.hora, [-1, 5, 11, 17, 23], labels=["Madrugada", "Mañana", "Tarde", "Noche"]).astype(str)
    h["periodo_solar"] = np.select([h.hora.between(10, 14), h.hora.between(7, 17)],
                                   ["Pico solar", "Hombro solar"], "Sin sol")
    h["franja_tarifaria"] = np.where(h.hora.between(9, 11) | h.hora.between(18, 20), "Punta", "Fuera de punta")
    h.loc[len(h)] = dict(sk_hora=-1, hora=-1, etiqueta="--:--", franja="n/d", periodo_solar="n/d",
                         franja_tarifaria="n/d")
    return h


def dim_inversor(versiones: pd.DataFrame, inicio_datos: float) -> pd.DataFrame:
    filas, sk = [], 1
    for inv, g in versiones.groupby("inversor"):
        g = g.sort_values("desde").reset_index(drop=True)
        for i, x in g.iterrows():
            ah = x.battpackrateah
            supuesta = not ah or ah == 0
            ah_usado = config.CAPACIDAD_SUPUESTA_AH if supuesta else ah
            desde = inicio_datos if i == 0 else x.desde  # la primera versión cubre todo lo anterior
            hasta = g.desde.iloc[i + 1] if i + 1 < len(g) else None
            filas.append(dict(
                sk_inversor=sk, cod_inversor=int(inv), nombre=f"Inversor {int(inv)}",
                subsistema=f"Subsistema {'A' if inv == 1 else 'B'}", bateria_ah=ah,
                bateria_kwh=round(ah_usado * config.TENSION_NOMINAL_BAT_V / 1000, 2),
                capacidad_supuesta=bool(supuesta), max_red_w=int(x.maxlinepower),
                prioridad_carga=PRIORIDAD.get(int(x.chgpriority), str(x.chgpriority)),
                soc_alarma_pct=None if pd.isna(x.batsoclowalarm) else int(x.batsoclowalarm),
                valido_desde=pd.to_datetime(desde, unit="s", utc=True),
                valido_hasta=None if hasta is None else pd.to_datetime(hasta, unit="s", utc=True),
                es_actual=hasta is None))
            sk += 1
    d = pd.DataFrame(filas)
    d.loc[len(d)] = dict(sk_inversor=-1, cod_inversor=0, nombre="Desconocido", subsistema="n/d",
                         bateria_ah=None, bateria_kwh=None, capacidad_supuesta=False, max_red_w=None,
                         prioridad_carga="n/d", soc_alarma_pct=None,
                         valido_desde=pd.Timestamp("1900-01-01", tz="UTC"), valido_hasta=None, es_actual=False)
    return d


def sk_inversor_en(dim: pd.DataFrame, inversor: pd.Series, ts: pd.Series) -> pd.Series:
    """Busca la versión de la dimensión vigente en cada instante (SCD 2)."""
    out = pd.Series(-1, index=inversor.index, dtype="int64")
    for inv, g in dim[dim.sk_inversor > 0].groupby("cod_inversor"):
        g = g.sort_values("valido_desde")
        m = inversor == inv
        if not m.any():
            continue
        pos = np.searchsorted(g.valido_desde.values.astype("datetime64[ns]"),
                              ts[m].values.astype("datetime64[ns]"), side="right") - 1
        out[m] = np.where(pos >= 0, g.sk_inversor.values[np.clip(pos, 0, None)], -1)
    return out


def _sk_tiempo(ts_utc: pd.Series):
    local = ts_utc.dt.tz_convert(TZ)
    return local.dt.strftime("%Y%m%d").astype(int), local.dt.hour.astype(int)


def fact_energia_hora(s: pd.DataFrame, dinv: pd.DataFrame) -> pd.DataFrame:
    s = s.copy()
    s["ts_hora_utc"] = s.ts_minuto.dt.floor("h")
    s["red_ok"] = s.red_v_min >= config.UMBRAL_RED_V
    g = s.groupby(["inversor", "ts_hora_utc"])
    h = g.agg(e_solar_kwh=("e_solar_wh", "sum"), e_carga_kwh=("e_carga_wh", "sum"), e_red_kwh=("e_red_wh", "sum"),
              e_bat_carga_kwh=("e_bat_carga_wh", "sum"), e_bat_descarga_kwh=("e_bat_descarga_wh", "sum"),
              soc_prom_pct=("soc_pct", "mean"), soc_min_pct=("soc_pct", "min"),
              seg=("seg_cubiertos", "sum"), minutos_red_ok=("red_ok", "sum"),
              lecturas_total=("n_lecturas", "sum"), lecturas_validas=("n_validas", "sum")).reset_index()
    for c in ["e_solar_kwh", "e_carga_kwh", "e_red_kwh", "e_bat_carga_kwh", "e_bat_descarga_kwh"]:
        h[c] = (h[c] / 1000).round(4)
    h["minutos_con_dato"] = (h.seg / 60).round().clip(upper=60).astype(int)
    h["minutos_red_ok"] = h.minutos_red_ok.clip(upper=60)
    h["sk_fecha"], h["sk_hora"] = _sk_tiempo(h.ts_hora_utc)
    h["sk_inversor"] = sk_inversor_en(dinv, h.inversor, h.ts_hora_utc)
    h[["soc_prom_pct", "soc_min_pct"]] = h[["soc_prom_pct", "soc_min_pct"]].round(1)
    return h


def dim_tipo_evento() -> pd.DataFrame:
    d = pd.DataFrame(TIPOS_EVENTO, columns=["cod_evento", "nombre", "categoria", "severidad", "origen", "regla"])
    d.insert(0, "sk_tipo_evento", range(1, len(d) + 1))
    return d


def fact_evento(e: pd.DataFrame, dte: pd.DataFrame, dinv: pd.DataFrame) -> pd.DataFrame:
    f = e.merge(dte[["sk_tipo_evento", "cod_evento"]], on="cod_evento")
    f["sk_fecha"], f["sk_hora"] = _sk_tiempo(f.inicio_utc)
    f["sk_inversor"] = sk_inversor_en(dinv, f.inversor, f.inicio_utc)
    return f


def dims_contexto(c: pd.DataFrame):
    t = c.groupby("tipo_contexto").agg(fuente=("fuente", "first"), categoria=("categoria", "first"),
                                       es_carga=("es_carga", "max")).reset_index()
    t.insert(0, "sk_tipo_contexto", range(1, len(t) + 1))
    d = pd.DataFrame({"dispositivo": sorted(c.dispositivo.unique())})
    d["tipo"] = np.select([d.dispositivo.str.startswith("workstation"), d.dispositivo == "inverter"],
                          ["Estación de trabajo", "Inversor"], "Instalación")
    d.insert(0, "sk_dispositivo", range(1, len(d) + 1))
    return t, d


def fact_actividad(c: pd.DataFrame, dtc, ddisp, dinv) -> pd.DataFrame:
    f = c.merge(dtc[["sk_tipo_contexto", "tipo_contexto"]], on="tipo_contexto") \
         .merge(ddisp[["sk_dispositivo", "dispositivo"]], on="dispositivo")
    ref = f.inicio.fillna(f.registrado)
    f["sk_fecha"], f["sk_hora"] = _sk_tiempo(ref)
    f["sk_inversor"] = sk_inversor_en(dinv, f.inversor.fillna(1).astype(int), ref)
    f["duracion_min"] = ((f.fin - f.inicio).dt.total_seconds() / 60).round(1)
    f["inicio_utc"], f["fin_utc"] = f.inicio, f.fin
    f["nucleos_cpu"] = f.nucleos
    return f


def fact_contador(d: pd.DataFrame, dinv) -> pd.DataFrame:
    d = d.copy()
    ts = pd.to_datetime(d.fecha_local).dt.tz_localize(TZ).dt.tz_convert("UTC") + pd.Timedelta(hours=12)
    d["sk_fecha"] = pd.to_datetime(d.fecha_local).dt.strftime("%Y%m%d").astype(int)
    d["sk_inversor"] = sk_inversor_en(dinv, d.inversor, ts)
    return d
