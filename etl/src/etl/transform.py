"""Transformaciones Bronze → Silver → Gold y reglas de calidad R01–R18.

Criterio central: un DATO INVÁLIDO es una lectura físicamente imposible o incoherente
consigo misma (se descarta o se anula el campo). Un EVENTO OPERATIVO es una situación
real y coherente (la red se cae, la batería se descarga): NO se borra, se convierte en
un registro de la tabla de eventos.
"""
import json
import logging

import numpy as np
import pandas as pd

from . import config

log = logging.getLogger("etl")
TZ = config.ZONA_LOCAL

CAMPOS_ELECTRICOS = ["battvolt", "battcurr", "battsoc", "pv1volt", "pv1curr", "pv1power",
                     "outvolta", "outw_a", "outva_a", "linevolta", "linepowerw_a"]


# ---------------------------------------------------------------------------
# Lecturas eléctricas (analog_measurements)
# ---------------------------------------------------------------------------
def limpiar_lecturas(a: pd.DataFrame, bit) -> pd.DataFrame:
    a = a.sort_values(["inverter", "read_ts"]).reset_index(drop=True)
    n0 = len(a)

    # R01 · fila sin ninguna medición eléctrica (el registrador escribió solo la marca de tiempo)
    vacia = a[CAMPOS_ELECTRICOS].isna().all(axis=1)
    a = a[~vacia].copy()
    bit.registrar("R01", "Lectura sin ninguna medición eléctrica (todas las columnas NULL)",
                  "Completitud", "Descartar", n0, vacia.sum(), len(a))

    # R02 · casi-duplicado: misma lectura escrita dos veces con menos de 1 s de diferencia
    n = len(a)
    dt_prev = a.groupby("inverter").read_ts.diff()
    dup = dt_prev < 1.0
    a = a[~dup].copy()
    bit.registrar("R02", "Lectura repetida del mismo inversor con < 1 s de diferencia",
                  "Unicidad", "Descartar", n, dup.sum(), len(a))
    n = len(a)

    # R03 · batería imposible: 0 V (o < 30 V) reportando a la vez un SoC > 0 %
    m = (a.battvolt < 30) & (a.battsoc > 0)
    a.loc[m, ["battvolt", "battcurr", "battsoc"]] = np.nan
    bit.registrar("R03", "Batería en 0 V reportando SoC > 0 % (sensor sin dato)",
                  "Validez", "Anular campos de batería", n, m.sum())

    # R04 · identidad fotovoltaica P = V·I (tolerancia 20 % o 50 W)
    calc = a.pv1volt * a.pv1curr
    m = (a.pv1power >= 100) & ((a.pv1power - calc).abs() > np.maximum(50, 0.2 * a.pv1power))
    a.loc[m, ["pv1power"]] = np.nan
    bit.registrar("R04", "Potencia FV incoherente con tensión × corriente (> 20 % o > 50 W)",
                  "Exactitud", "Anular potencia FV", n, m.sum())

    # R05 · identidad AC: la potencia activa no puede superar la aparente
    m = a.outw_a > a.outva_a + 50
    a.loc[m, ["outw_a"]] = np.nan
    bit.registrar("R05", "Potencia activa de salida mayor que la aparente (W > VA + 50)",
                  "Exactitud", "Anular potencia de carga", n, m.sum())

    # R06 · importación de red negativa: este inversor no inyecta a la red; valores < 0 son ruido
    m = a.linepowerw_a < 0
    a.loc[m, "linepowerw_a"] = 0
    bit.registrar("R06", "Potencia de red negativa (el inversor no exporta): ruido del medidor",
                  "Validez", "Corregir a 0", n, m.sum())

    # R07 · columna ambigua gridpowerw_a: ~60 W casi constantes, no cuadra con ninguna energía
    m = a.gridpowerw_a.notna()
    bit.registrar("R07", "Columna gridpowerw_a de semántica ambigua (≈ 60 W constantes); se usa linepowerw_a",
                  "Consistencia", "Excluir columna", n, m.sum())

    # R08 · temperatura centinela de 120 °C (documentado por los autores)
    temp = a[["temper1", "temper2", "temper3", "temper4"]]
    m = (temp == 120).any(axis=1)
    bit.registrar("R08", "Canal de temperatura con valor centinela de 120 °C",
                  "Validez", "Excluir del análisis térmico", n, m.sum())

    # R09 · fuera de rango físico (potencias negativas o > 6 500 W, SoC fuera de 0–100)
    fuera = ((a.pv1power < 0) | (a.pv1power > 6500) | (a.outw_a < 0) | (a.outw_a > 6500)
             | (a.battsoc < 0) | (a.battsoc > 100))
    a.loc[fuera, ["pv1power", "outw_a"]] = np.nan
    bit.registrar("R09", "Valores fuera de rango físico del equipo",
                  "Validez", "Anular campo", n, fuera.sum())

    # Lectura válida = tiene los tres flujos del balance (solar, carga, red)
    a["valida"] = a[["pv1power", "outw_a", "linepowerw_a"]].notna().all(axis=1)
    a["bat_w"] = a.battvolt * a.battcurr  # + descarga, - carga (convención de la fuente)
    return a


def huecos(a: pd.DataFrame, bit) -> pd.DataFrame:
    """R10 · huecos de registro > 10 min: no se imputan; quedan como evento de categoría Datos."""
    a = a.sort_values(["inverter", "read_ts"])
    sig = a.groupby("inverter").read_ts.shift(-1)
    gap = sig - a.read_ts
    h = a.loc[gap > config.HUECO_SEG, ["inverter", "read_ts"]].copy()
    h["fin"] = sig[gap > config.HUECO_SEG]
    bit.registrar("R10", f"Hueco de registro mayor a {int(config.HUECO_SEG / 60)} min (no se imputa)",
                  "Completitud", "Convertir en evento", len(a), len(h))
    return h.rename(columns={"inverter": "inversor", "read_ts": "inicio"})


def energia_por_intervalo(a: pd.DataFrame) -> pd.DataFrame:
    """Energía de cada intervalo entre dos lecturas consecutivas (regla del trapecio).

    Solo se integran intervalos de hasta HUECO_SEG (10 min): un intervalo más largo es un
    hueco y no se inventa energía. Cada flujo se integra por separado, solo si sus dos
    extremos tienen dato (una batería sin dato no anula la energía solar del mismo intervalo).
    La energía se asigna al minuto de la lectura que cierra el intervalo.
    """
    a = a.sort_values(["inverter", "read_ts"]).copy()
    g = a.groupby("inverter")
    dt = a.read_ts - g.read_ts.shift()
    ok = dt <= config.HUECO_SEG
    a["seg_cubiertos"] = np.where(ok, dt, 0.0)
    for col, nombre in [("pv1power", "e_solar_wh"), ("outw_a", "e_carga_wh"), ("linepowerw_a", "e_red_wh")]:
        prom = (a[col] + g[col].shift()) / 2
        a[nombre] = np.where(ok, prom * dt / 3600, 0.0)
        a[nombre] = a[nombre].fillna(0.0)
    pb = ((a.bat_w + g.bat_w.shift()) / 2 * dt / 3600).where(ok).fillna(0.0)
    a["e_bat_descarga_wh"] = pb.clip(lower=0)
    a["e_bat_carga_wh"] = (-pb).clip(lower=0)
    return a


def agregar_minuto(a: pd.DataFrame, alarmas: pd.DataFrame) -> pd.DataFrame:
    """Silver a 1 minuto: energía integrada, potencias medias válidas y mínimo de tensión de red."""
    a = energia_por_intervalo(a)
    a["minuto"] = (a.read_ts // 60).astype("int64")
    v = a[a.valida]
    g_all = a.groupby(["inverter", "minuto"])
    s = pd.DataFrame({
        "n_lecturas": g_all.size(),
        "red_v_min": g_all.linevolta.min(),
        "salida_v": g_all.outvolta.mean(),
        "soc_pct": g_all.battsoc.mean(),
        "bat_v": g_all.battvolt.mean(),
        "bat_w": g_all.bat_w.mean(),
        "seg_cubiertos": g_all.seg_cubiertos.sum(),
        "e_solar_wh": g_all.e_solar_wh.sum(),
        "e_carga_wh": g_all.e_carga_wh.sum(),
        "e_red_wh": g_all.e_red_wh.sum(),
        "e_bat_carga_wh": g_all.e_bat_carga_wh.sum(),
        "e_bat_descarga_wh": g_all.e_bat_descarga_wh.sum(),
    })
    gv = v.groupby(["inverter", "minuto"])
    s["n_validas"] = gv.size()
    s["pv_w"] = gv.pv1power.mean()
    s["carga_w"] = gv.outw_a.mean()
    s["red_w"] = gv.linepowerw_a.mean()
    s["n_validas"] = s.n_validas.fillna(0).astype(int)

    al = alarmas.dropna(subset=["sysalarmflag"]).copy()
    al["activa"] = ~al.sysalarmflag.isin(["[0,0,0,0,0,0,0,0]", "[null]"])
    al["minuto"] = (al.read_ts // 60).astype("int64")
    al = al.groupby(["inverter", "minuto"]).activa.any()
    s = s.join(al.rename("alarma_activa"), how="left")
    s["alarma_activa"] = s.alarma_activa.fillna(False).astype(bool)
    s = s.reset_index().rename(columns={"inverter": "inversor"})
    s["ts_minuto"] = pd.to_datetime(s.minuto * 60, unit="s", utc=True)
    for c in ["e_solar_wh", "e_carga_wh", "e_red_wh", "e_bat_carga_wh", "e_bat_descarga_wh", "seg_cubiertos"]:
        s[c] = s[c].round(3)
    return s


# ---------------------------------------------------------------------------
# Eventos operativos (a partir de la serie por minuto)
# ---------------------------------------------------------------------------
TIPOS_EVENTO = [
    # cod, nombre, categoría, severidad, origen, regla
    ("RED_NO_DISPONIBLE", "Red pública no disponible", "Red", "Advertencia", "Detectado en lecturas",
     f"Tensión mínima de red < {config.UMBRAL_RED_V:.0f} V durante ≥ 2 minutos seguidos"),
    ("SOC_BAJO", "Batería con carga baja", "Batería", "Crítica", "Detectado en lecturas",
     f"SoC ≤ {config.UMBRAL_SOC_BAJO:.0f} % (umbral de alarma configurado en el inversor)"),
    ("INVERSOR_SIN_SALIDA", "Inversor sin salida AC", "Inversor", "Crítica", "Detectado en lecturas",
     f"Tensión de salida < {config.UMBRAL_SALIDA_V:.0f} V durante ≥ 2 minutos"),
    ("ALARMA_INVERSOR", "Bandera de alarma del inversor", "Inversor", "Advertencia", "Bandera del inversor",
     "sysalarmflag distinto de cero en la tabla status"),
    ("HUECO_DATOS", "Hueco en el registro de datos", "Datos", "Info", "Detectado en lecturas",
     f"Más de {int(config.HUECO_SEG / 60)} minutos sin lecturas"),
    ("APAGADO_MANUAL", "Apagado manual del sistema", "Operación manual", "Crítica", "Registro manual",
     "Nota manual del personal que reporta apagado (p. ej., tifón)"),
]


def _intervalos(serie_min: pd.DataFrame, cond: pd.Series, min_dur: int, tolerancia: int = 1):
    """Convierte minutos que cumplen `cond` en intervalos [inicio, fin].

    `tolerancia`: minutos de separación que aún se consideran el mismo evento
    (evita partir un evento en cientos de pedazos por una bandera que parpadea).
    """
    d = serie_min.loc[cond, ["inversor", "minuto", "soc_pct"]].sort_values(["inversor", "minuto"])
    if d.empty:
        return pd.DataFrame(columns=["inversor", "inicio_min", "fin_min", "dur", "extremo"])
    corte = (d.minuto.diff() > tolerancia) | (d.inversor != d.inversor.shift())
    d["grupo"] = corte.cumsum()
    r = d.groupby("grupo").agg(inversor=("inversor", "first"), inicio_min=("minuto", "min"),
                               fin_min=("minuto", "max"), extremo=("soc_pct", "min"))
    r["dur"] = r.fin_min - r.inicio_min + 1
    return r[r.dur >= min_dur]


def detectar_eventos(s: pd.DataFrame, gaps: pd.DataFrame, contexto: pd.DataFrame, bit) -> pd.DataFrame:
    ev = []
    n = len(s)
    reglas = [
        ("R11", "RED_NO_DISPONIBLE", s.red_v_min < config.UMBRAL_RED_V, 2,
         "Tensión de red < 180 V: NO es dato inválido, es un corte real de red"),
        ("R12", "SOC_BAJO", s.soc_pct <= config.UMBRAL_SOC_BAJO, 1,
         "SoC ≤ 15 %: NO es dato inválido, es una descarga real de la batería"),
        ("R13", "INVERSOR_SIN_SALIDA", s.salida_v < config.UMBRAL_SALIDA_V, 2,
         "Salida AC < 100 V: inversor apagado o en falla (evento real)"),
    ]
    for regla, cod, cond, dmin, desc in reglas:
        r = _intervalos(s, cond.fillna(False), dmin, tolerancia=5)
        bit.registrar(regla, desc + f" → {len(r)} eventos", "Validez (evento vs. error)",
                      "Convertir en evento", n, int(cond.sum()))
        for x in r.itertuples():
            ev.append((cod, x.inversor, x.inicio_min * 60, (x.fin_min + 1) * 60,
                       x.extremo if cod == "SOC_BAJO" else None, None))
    r = _intervalos(s, s.alarma_activa, 2, tolerancia=15)
    for x in r.itertuples():
        ev.append(("ALARMA_INVERSOR", x.inversor, x.inicio_min * 60, (x.fin_min + 1) * 60, None, None))
    for x in gaps.itertuples():
        ev.append(("HUECO_DATOS", x.inversor, x.inicio, x.fin, None, None))
    manual = contexto[(contexto.fuente == "manual entry")
                      & contexto.texto.str.contains("shut down|shutdown|power off", case=False, na=False)]
    for x in manual.itertuples():
        ini = x.inicio_ts if pd.notna(x.inicio_ts) else x.registrado_ts
        fin = x.fin_ts if pd.notna(x.fin_ts) else ini
        ev.append(("APAGADO_MANUAL", int(x.inversor or 1), ini, fin, None, x.texto[:200]))
    e = pd.DataFrame(ev, columns=["cod_evento", "inversor", "inicio", "fin", "valor_extremo", "descripcion"])
    e["inicio_utc"] = pd.to_datetime(e.inicio, unit="s", utc=True)
    e["fin_utc"] = pd.to_datetime(e.fin, unit="s", utc=True)
    e["duracion_min"] = ((e.fin - e.inicio) / 60).round(1)
    return e


# ---------------------------------------------------------------------------
# Contexto JSON
# ---------------------------------------------------------------------------
CLAVES_SENSIBLES = {"command", "directory", "example_commands_redacted", "command_hints_redacted",
                    "metadata", "task_files", "sanitized_message", "record_id"}


def _categoria(fuente, tipo, d):
    t = (tipo or "").lower()
    if "workload" in t or d.get("task_type") or t in ("build_or_test_activity", "interactive_development"):
        return "Carga de cómputo", True
    if fuente == "windows_event_log":
        return "Sistema operativo", False
    if t == "calendar_day":
        return "Calendario", False
    if t.startswith("solar_") or t == "installation_location":
        return "Solar / ubicación", False
    if fuente in ("manual entry", "manual_workload_entry"):
        return "Nota manual", "workload" in fuente
    if fuente == "wsl_bash_history":
        return "Carga de cómputo", True
    return "Telemetría derivada", False


def procesar_contexto(c: pd.DataFrame, bit):
    n = len(c)
    filas, removidas, sin_tipo = [], 0, 0
    for r in c.itertuples():
        d = json.loads(r.value)
        fuente = d.get("source", "desconocida")
        tipo = d.get("context_type")
        if not tipo:
            sin_tipo += 1
            tipo = "manual_note" if fuente == "manual entry" else (
                "gpu_cnn_training_workload" if "GPU" in str(d.get("task_type", "")) else "cpu_compilation_workload"
                if d.get("task_type") else "manual_note")
        limpio = {k: v for k, v in d.items() if k not in CLAVES_SENSIBLES}
        if len(limpio) != len(d):
            removidas += 1
        cat, es_carga = _categoria(fuente, tipo, d)
        nucleos = pd.to_numeric(d.get("cpu_cores_active"), errors="coerce")
        filas.append(dict(
            id_contexto=r.id, registrado_ts=r.recorded, inicio_ts=r.start, fin_ts=r.fin,
            fuente=fuente, tipo_contexto=tipo, dispositivo=d.get("device", "installation"),
            inversor=d.get("inversor") or d.get("inverter"), valor=json.dumps(limpio, ensure_ascii=False),
            texto=d.get("textual_description") or d.get("summary") or "", categoria=cat, es_carga=es_carga,
            nucleos=None if pd.isna(nucleos) else int(nucleos),
            es_gpu="GPU" in str(d.get("task_type", "")) or "gpu" in tipo,
            carga_estimada=d.get("llm_estimated_task_effort"),
        ))
    out = pd.DataFrame(filas)
    bit.registrar("R14", "Contexto: se eliminan del JSON comandos, rutas y metadatos de archivos (Ley 1581: minimización)",
                  "Privacidad", "Corregir (sanitizar JSON)", n, removidas)
    bit.registrar("R15", "Contexto sin campo context_type: se deriva de source/task_type",
                  "Completitud", "Corregir", n, sin_tipo)
    inv = (out.fin_ts.notna() & out.inicio_ts.notna() & (out.fin_ts < out.inicio_ts))
    out.loc[inv, "fin_ts"] = out.loc[inv, "inicio_ts"]
    bit.registrar("R16", "Contexto con fin anterior al inicio", "Validez", "Corregir fin = inicio", n, inv.sum())
    for col in ["registrado", "inicio", "fin"]:
        out[col] = pd.to_datetime(out[col + "_ts"], unit="s", utc=True)
    return out


# ---------------------------------------------------------------------------
# Contadores diarios y configuración (SCD 2)
# ---------------------------------------------------------------------------
def contadores_diarios(st: pd.DataFrame, bit) -> pd.DataFrame:
    st = st.copy()
    st["fecha_local"] = pd.to_datetime(st.read_ts, unit="s", utc=True).dt.tz_convert(TZ).dt.date
    cols = {"pvgeneratenergytoday": "pv_kwh", "usedenergytoday": "carga_kwh",
            "loadconsumlinetday": "carga_desde_red_kwh", "linechgenergytday": "red_a_bateria_kwh",
            "batchgenergytoday": "bat_carga_kwh", "batdischgenergytoday": "bat_descarga_kwh"}
    d = st.groupby(["inverter", "fecha_local"])[list(cols)].max().rename(columns=cols).reset_index()
    vacios = d[list(cols.values())].isna().all(axis=1)
    bit.registrar("R17", "Contador diario: se toma el máximo del día local (el contador se reinicia a medianoche); días sin contador se omiten",
                  "Consistencia", "Agregar / Descartar vacíos", len(d), vacios.sum(), len(d) - vacios.sum())
    return d[~vacios].rename(columns={"inverter": "inversor"})


def historia_config(se: pd.DataFrame, bit) -> pd.DataFrame:
    """Versiones de configuración que duran al menos 1 día (los cambios de minutos son ruido de lectura)."""
    se = se.dropna(subset=["battpackrateah", "maxlinepower", "chgpriority"]).sort_values(["inverter", "read_ts"])
    clave = ["battpackrateah", "maxlinepower", "chgpriority", "batsoclowalarm", "inv2linesoc"]
    se["cambio"] = (se[clave] != se.groupby("inverter")[clave].shift()).any(axis=1)
    se["v"] = se.groupby("inverter").cambio.cumsum()
    v = se.groupby(["inverter", "v"]).agg(desde=("read_ts", "min"), hasta=("read_ts", "max"),
                                          **{c: (c, "first") for c in clave}).reset_index()
    v["dur_h"] = (v.hasta - v.desde) / 3600
    bruto = len(v)
    v = v[v.dur_h >= 24].copy()
    # fusionar versiones consecutivas iguales tras quitar las cortas
    v["cambio"] = (v[clave] != v.groupby("inverter")[clave].shift()).any(axis=1)
    v = v[v.cambio]
    bit.registrar("R18", "Configuración del inversor: versiones que duran < 24 h se tratan como ruido de lectura (SCD 2)",
                  "Consistencia", "Descartar", bruto, bruto - len(v), len(v))
    sin_cap = (v.battpackrateah == 0).sum()
    bit.registrar("R19", f"Inversor sin capacidad de batería configurada (0 Ah): se supone {config.CAPACIDAD_SUPUESTA_AH:.0f} Ah, igual al inversor 1",
                  "Completitud", "Imputar y marcar", len(v), sin_cap)
    return v.rename(columns={"inverter": "inversor"})
