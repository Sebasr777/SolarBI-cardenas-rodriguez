"""Genera docs/04_diccionario_datos.md desde el catálogo de PostgreSQL + el linaje declarado aquí.

Tipos, llaves y nulabilidad salen de information_schema (no se escriben a mano);
el origen (data lineage), la regla y la unidad de cada campo se declaran en LINAJE.
"""
import os
from pathlib import Path

import psycopg2

B = "analog_measurements"
LINAJE = {
    # tabla: (descripción, grano, {columna: (origen en Bronze, regla de transformación, unidad)})
    "silver.lectura_minuto": ("Lecturas eléctricas validadas y agregadas por minuto.", "inversor × minuto UTC", {
        "inversor": (f"{B}.inverter", "Directo", "—"),
        "ts_minuto": (f"{B}.read_ts", "Unix UTC → timestamptz, truncado al minuto", "UTC"),
        "n_lecturas": (f"{B}.*", "Conteo de lecturas tras R01–R02", "lecturas"),
        "n_validas": (f"{B}.*", "Lecturas con solar, carga y red no nulos tras R03–R09", "lecturas"),
        "pv_w": (f"{B}.pv1power", "Media de lecturas válidas (R04, R09)", "W"),
        "carga_w": (f"{B}.outw_a", "Media de lecturas válidas (R05, R09)", "W"),
        "red_w": (f"{B}.linepowerw_a", "Media; negativos a 0 (R06)", "W"),
        "bat_w": (f"{B}.battvolt × {B}.battcurr", "V·I; + descarga, − carga (R03)", "W"),
        "soc_pct": (f"{B}.battsoc", "Media del minuto", "%"),
        "bat_v": (f"{B}.battvolt", "Media del minuto", "V"),
        "red_v_min": (f"{B}.linevolta", "Mínimo del minuto (detecta cortes)", "V"),
        "salida_v": (f"{B}.outvolta", "Media del minuto", "V"),
        "alarma_activa": ("status.sysalarmflag", "TRUE si la bandera es distinta de [0,…,0]", "—"),
        "seg_cubiertos": (f"{B}.read_ts", "Suma de intervalos ≤ 10 min que cierran en el minuto", "s"),
        "e_solar_wh": (f"{B}.pv1power", "Trapecio por intervalo (≤ 10 min)", "Wh"),
        "e_carga_wh": (f"{B}.outw_a", "Trapecio por intervalo", "Wh"),
        "e_red_wh": (f"{B}.linepowerw_a", "Trapecio por intervalo", "Wh"),
        "e_bat_carga_wh": ("battvolt × battcurr", "Trapecio, parte negativa", "Wh"),
        "e_bat_descarga_wh": ("battvolt × battcurr", "Trapecio, parte positiva", "Wh"),
    }),
    "silver.contexto": ("Registros de contexto con el JSON sanitizado.", "un registro de context", {
        "id_contexto": ("context.id", "Directo", "—"), "registrado": ("context.recorded", "Unix → timestamptz", "UTC"),
        "inicio": ("context.start", "Unix → timestamptz", "UTC"), "fin": ("context.end", "Unix → timestamptz (R16)", "UTC"),
        "fuente": ("context.value → source", "JSON → texto", "—"),
        "tipo_contexto": ("context.value → context_type", "Si falta, se deriva (R15)", "—"),
        "dispositivo": ("context.value → device", "Si falta: installation", "—"),
        "inversor": ("context.value → inverter", "Directo", "—"),
        "valor": ("context.value", "JSONB sin comandos, rutas ni metadatos (R14)", "—"),
    }),
    "silver.contador_diario": ("Contadores diarios del propio inversor (fuente independiente).", "inversor × día local", {
        "pv_kwh": ("statistics.pvgeneratenergytoday", "Máximo del día local (R17)", "kWh"),
        "carga_kwh": ("statistics.usedenergytoday", "Máximo del día local", "kWh"),
        "carga_desde_red_kwh": ("statistics.loadconsumlinetday", "Máximo del día local", "kWh"),
        "red_a_bateria_kwh": ("statistics.linechgenergytday", "Máximo del día local", "kWh"),
        "bat_carga_kwh": ("statistics.batchgenergytoday", "Máximo del día local", "kWh"),
        "bat_descarga_kwh": ("statistics.batdischgenergytoday", "Máximo del día local", "kWh"),
    }),
    "gold.dim_fecha": ("Calendario local (Asia/Shanghai). Dimensión conformada.", "un día", {
        "*": ("Generada por el ETL", "Rango = telemetría ∪ contexto", "—")}),
    "gold.dim_hora": ("Hora del día con franjas. DIMENSIÓN CONSTRUIDA POR EL EQUIPO.", "una hora (0–23)", {
        "*": ("Generada por el ETL", "Franja, periodo solar y franja tarifaria EPM", "—")}),
    "gold.dim_inversor": ("Inversor con historia de configuración (SCD tipo 2).", "una versión de configuración", {
        "cod_inversor": ("settings.inverter", "Llave natural", "—"),
        "bateria_ah": ("settings.battpackrateah", "Versión ≥ 24 h (R18)", "Ah"),
        "bateria_kwh": ("settings.battpackrateah", "Ah × 51,2 V / 1000; 0 Ah → 200 Ah supuesto (R19)", "kWh"),
        "max_red_w": ("settings.maxlinepower", "Directo", "W"),
        "prioridad_carga": ("settings.chgpriority", "Código → texto", "—"),
        "soc_alarma_pct": ("settings.batsoclowalarm", "Directo", "%"),
        "valido_desde": ("settings.read_ts", "Inicio de la versión", "UTC"),
        "valido_hasta": ("settings.read_ts", "Inicio de la versión siguiente", "UTC"),
        "es_actual": ("—", "TRUE en la última versión", "—"),
    }),
    "gold.dim_tipo_evento": ("Catálogo de eventos operativos (categoría › tipo).", "un tipo de evento", {
        "*": ("Definido por el equipo", "Ver regla de detección", "—")}),
    "gold.dim_tipo_contexto": ("Tipos de contexto (categoría › tipo).", "un tipo de contexto", {
        "*": ("context.value → context_type / source", "Categorizado por el ETL", "—")}),
    "gold.dim_dispositivo": ("Dispositivo que originó el contexto.", "un dispositivo", {
        "*": ("context.value → device", "Directo", "—")}),
    "gold.fact_energia_hora": ("Balance energético.", "inversor × hora local", {
        "e_solar_kwh": ("silver.lectura_minuto.e_solar_wh", "Σ / 1000", "kWh"),
        "e_carga_kwh": ("silver.lectura_minuto.e_carga_wh", "Σ / 1000", "kWh"),
        "e_red_kwh": ("silver.lectura_minuto.e_red_wh", "Σ / 1000", "kWh"),
        "e_bat_carga_kwh": ("silver.lectura_minuto.e_bat_carga_wh", "Σ / 1000", "kWh"),
        "e_bat_descarga_kwh": ("silver.lectura_minuto.e_bat_descarga_wh", "Σ / 1000", "kWh"),
        "soc_prom_pct": ("silver.lectura_minuto.soc_pct", "Promedio", "%"),
        "soc_min_pct": ("silver.lectura_minuto.soc_pct", "Mínimo", "%"),
        "minutos_con_dato": ("silver.lectura_minuto.seg_cubiertos", "Σ / 60, tope 60", "min"),
        "minutos_red_ok": ("silver.lectura_minuto.red_v_min", "Minutos con V ≥ 180", "min"),
        "lecturas_total": ("silver.lectura_minuto.n_lecturas", "Σ", "lecturas"),
        "lecturas_validas": ("silver.lectura_minuto.n_validas", "Σ", "lecturas"),
    }),
    "gold.fact_evento": ("Eventos operativos (intervalos).", "un evento de un tipo en un inversor", {
        "inicio_utc": ("silver.lectura_minuto / context", "Minutos consecutivos que cumplen la regla (R11–R13)", "UTC"),
        "fin_utc": ("silver.lectura_minuto / context", "Último minuto + 1", "UTC"),
        "duracion_min": ("—", "fin − inicio", "min"),
        "valor_extremo": ("silver.lectura_minuto.soc_pct", "SoC mínimo (solo SOC_BAJO)", "%"),
    }),
    "gold.fact_actividad": ("Actividad y contexto (qué cargas explican el consumo).", "un registro de contexto", {
        "id_contexto": ("context.id", "Dimensión degenerada", "—"),
        "duracion_min": ("context.end − context.start", "En minutos", "min"),
        "nucleos_cpu": ("context.value → cpu_cores_active", "Texto → entero", "núcleos"),
        "es_gpu": ("context.value → task_type", "Contiene 'GPU'", "—"),
        "carga_estimada": ("context.value → llm_estimated_task_effort", "Directo", "—"),
    }),
    "gold.fact_contador_diario": ("Contadores diarios del inversor.", "inversor × día local", {
        "*": ("silver.contador_diario", "Directo", "kWh")}),
    "gold.fact_lectura_rt": ("Monitoreo casi en tiempo real.", "inversor × minuto (solo inserción)", {
        "*": ("silver.lectura_minuto desplazado 365 días", "Lo escribe el simulador (CronJob)", "W, %, V")}),
}

c = psycopg2.connect(host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "30432")),
                     user=os.getenv("PGUSER", "etl_admin"), password=os.getenv("PGPASSWORD", ""), dbname="solarbi")
cur = c.cursor()
md = ["# 4. Diccionario de datos y linaje", "",
      "> Generado con `python scripts/generar_diccionario.py`. Tipos, llaves y nulabilidad salen del catálogo de "
      "PostgreSQL; el origen, la regla y la unidad, del linaje declarado en el script.", "",
      "## Unidades y evidencia", "",
      "| Variable | Unidad | Evidencia |", "|---|---|---|",
      "| `pv1power`, `outw_a`, `linepowerw_a` | W | `documentation/column_dictionary.csv` de los autores; identidad P = V·I (R04); "
      "la energía integrada coincide con el contador `usedenergytoday` (kWh) del inversor con −2,5 % |",
      "| `battvolt` · `battcurr` | V · A | Diccionario de los autores; mediana 53,5 V (banco de litio de 48 V nominal) |",
      "| `battcurr` signo | + descarga, − carga | Diccionario: «positive denotes discharge» |",
      "| `battsoc` | % | Rango 6–100; coincide con los umbrales `batsoclowalarm` = 15 y `batstopsoc` = 5 |",
      "| `linevolta` | V | Distribución bimodal: 0 V (sin red) o 230 ± 10 V |",
      "| `read_ts` | s Unix UTC | Diccionario: «fractional Unix timestamp in UTC»; la planta está en Shenzhen (UTC+8) |",
      "| contadores `*today` | kWh | Diccionario; resolución 0,1 kWh |", ""]
for tabla, (desc, grano, lin) in LINAJE.items():
    esq, t = tabla.split(".")
    cur.execute("""SELECT c.column_name, c.data_type, c.is_nullable,
                     (SELECT string_agg(tc.constraint_type, ',') FROM information_schema.key_column_usage k
                      JOIN information_schema.table_constraints tc USING (constraint_schema, constraint_name)
                      WHERE k.table_schema=c.table_schema AND k.table_name=c.table_name AND k.column_name=c.column_name)
                   FROM information_schema.columns c WHERE c.table_schema=%s AND c.table_name=%s
                   ORDER BY c.ordinal_position""", (esq, t))
    md += [f"## `{tabla}`", "", f"{desc} **Grano:** {grano}.", "",
           "| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |", "|---|---|---|---|---|---|---|"]
    for col, tipo, nulo, llave in cur.fetchall():
        o, r, u = lin.get(col, lin.get("*", ("—", "—", "—")))
        if col.startswith("sk_"):
            o, r, u = ("Generada", "Llave sustituta" if not llave or "FOREIGN" not in llave else "Búsqueda en la dimensión", "—")
        llave = (llave or "").replace("PRIMARY KEY", "PK").replace("FOREIGN KEY", "FK").replace("UNIQUE", "UQ")
        md.append(f"| `{col}` | {tipo} | {llave} | {'sí' if nulo == 'YES' else 'no'} | {o} | {r} | {u} |")
    md.append("")
dest = Path(__file__).resolve().parents[1] / "docs" / "04_diccionario_datos.md"
dest.write_text("\n".join(md), encoding="utf-8")
print("Escrito", dest)
