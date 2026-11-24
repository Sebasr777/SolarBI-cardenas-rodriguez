"""Genera powerbi/modelo_solarbi.tmdl a partir del catálogo de la base (esquema gold).

El archivo se pega en la vista TMDL de Power BI Desktop y crea en un paso: las tablas conectadas
a PostgreSQL, las relaciones, las jerarquías, la tabla de fechas, los parámetros what-if y las medidas.
Uso: python scripts/generar_modelo_powerbi.py   (requiere conexión a la base con el ETL ya corrido)
"""
import os
from pathlib import Path

import psycopg2

c = psycopg2.connect(host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "30432")),
                     user=os.getenv("PGUSER", "etl_admin"), password=os.getenv("PGPASSWORD", ""),
                     dbname="solarbi")
cur = c.cursor()
TABLAS = ["dim_fecha", "dim_hora", "dim_inversor", "dim_tipo_evento", "dim_tipo_contexto", "dim_dispositivo",
          "fact_energia_hora", "fact_evento", "fact_actividad", "fact_contador_diario"]
TIPOS = {"integer": "int64", "smallint": "int64", "bigint": "int64", "numeric": "double",
         "character varying": "string", "character": "string", "text": "string", "date": "dateTime",
         "boolean": "boolean", "timestamp with time zone": "dateTime"}
T = "\t"
out = ["createOrReplace", "",
       T + 'expression ServidorPostgres = "localhost:30432" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]', "",
       T + 'expression BaseDatos = "solarbi" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]', ""]
JER = {
    "dim_fecha": [("Calendario", [("Año", "anio"), ("Trimestre", "trimestre"), ("Mes", "mes_nombre"), ("Día", "fecha")])],
    "dim_hora": [("Día solar", [("Franja", "franja"), ("Hora", "etiqueta")])],
    "dim_tipo_evento": [("Evento", [("Categoría", "categoria"), ("Tipo", "nombre")])],
    "dim_tipo_contexto": [("Contexto", [("Categoría", "categoria"), ("Tipo", "tipo_contexto")])],
}
OCULTAS = ("sk_", "id_", "ts_hora_utc", "valido_desde", "valido_hasta", "lecturas_", "minutos_")
for t in TABLAS:
    cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='gold' AND table_name=%s ORDER BY ordinal_position", (t,))
    out.append(f"{T}table {t}")
    if t == "dim_fecha":
        out.append(f"{T*2}dataCategory: Time")
    out.append("")
    for n, dt in cur.fetchall():
        tipo = TIPOS[dt]
        out += [f"{T*2}column {n}", f"{T*3}dataType: {tipo}"]
        if t == "dim_fecha" and n == "fecha":
            out += [f"{T*3}isKey", f"{T*3}formatString: dd/mm/yyyy"]
        if n.startswith(OCULTAS) or (t.startswith("fact") and n.startswith(("e_", "soc_"))):
            out.append(f"{T*3}isHidden")
        num = tipo in ("int64", "double")
        out.append(f"{T*3}summarizeBy: " + ("sum" if num and t.startswith("fact") and n.startswith("e_") else "none"))
        if n == "mes_nombre":
            out.append(f"{T*3}sortByColumn: mes")
        if n == "dia_semana":
            out.append(f"{T*3}sortByColumn: dia_semana_num")
        out += [f"{T*3}sourceColumn: {n}", ""]
    for h, niveles in JER.get(t, []):
        out.append(f"{T*2}hierarchy '{h}'")
        for i, (ln, col) in enumerate(niveles):
            out += [f"{T*3}level '{ln}'", f"{T*4}ordinal: {i}", f"{T*4}column: {col}"]
        out.append("")
    out += [f"{T*2}partition {t} = m", f"{T*3}mode: import", f"{T*3}source =", f"{T*5}let",
            f"{T*5}    Origen = PostgreSQL.Database(ServidorPostgres, BaseDatos),",
            f'{T*5}    Tabla = Origen{{[Schema="gold",Item="{t}"]}}[Data]', f"{T*5}in", f"{T*5}    Tabla", ""]

# ---------------- Parámetros what-if (tablas calculadas desconectadas) ----------------
for nombre, col, expr, fmt in [
    ("Tarifa", "Tarifa COP por kWh", "GENERATESERIES ( 500, 1500, 10 )", "#,0"),
    ("Paneles adicionales", "Paneles adicionales %", "GENERATESERIES ( 0, 1, 0.05 )", "0%"),
]:
    out += [f"{T}table '{nombre}'", "",
            f"{T*2}column '{col}'", f"{T*3}dataType: double", f"{T*3}formatString: {fmt}",
            f"{T*3}summarizeBy: none", f"{T*3}sourceColumn: [Value]", "",
            f"{T*2}partition '{nombre}' = calculated", f"{T*3}mode: import", f"{T*3}source = {expr}", ""]

# ---------------- Tabla del balance (entradas vs. salidas) ----------------
out += [f"{T}table Balance", "",
        f"{T*2}column Lado", f"{T*3}dataType: string", f"{T*3}summarizeBy: none", f"{T*3}sourceColumn: [Lado]", "",
        f"{T*2}column Componente", f"{T*3}dataType: string", f"{T*3}summarizeBy: none",
        f"{T*3}sortByColumn: Orden", f"{T*3}sourceColumn: [Componente]", "",
        f"{T*2}column Orden", f"{T*3}dataType: int64", f"{T*3}isHidden", f"{T*3}summarizeBy: none", f"{T*3}sourceColumn: [Orden]", "",
        f"{T*2}partition Balance = calculated", f"{T*3}mode: import", f"{T*3}source = ```",
        f'{T*4}DATATABLE ( "Lado", STRING, "Componente", STRING, "Orden", INTEGER, {{',
        f'{T*5}{{ "1 · De dónde viene", "Sol", 1 }}, {{ "1 · De dónde viene", "Red pública", 2 }}, {{ "1 · De dónde viene", "Batería (descarga)", 3 }},',
        f'{T*5}{{ "2 · A dónde va", "Carga (equipos)", 4 }}, {{ "2 · A dónde va", "Batería (carga)", 5 }}, {{ "2 · A dónde va", "Pérdidas de conversión", 6 }} }} )',
        f"{T*4}```", ""]

# ---------------- Medidas ----------------
H = "fact_energia_hora"
M = [
    ("1 Energía", "Energía Solar (kWh)", f"SUM ( {H}[e_solar_kwh] )", "#,0.0"),
    ("1 Energía", "Energía a la Carga (kWh)", f"SUM ( {H}[e_carga_kwh] )", "#,0.0"),
    ("1 Energía", "Energía de la Red (kWh)", f"SUM ( {H}[e_red_kwh] )", "#,0.0"),
    ("1 Energía", "Batería Carga (kWh)", f"SUM ( {H}[e_bat_carga_kwh] )", "#,0.0"),
    ("1 Energía", "Batería Descarga (kWh)", f"SUM ( {H}[e_bat_descarga_kwh] )", "#,0.0"),
    ("1 Energía", "Pérdidas de Conversión (kWh)",
     "MAX ( 0, [Energía Solar (kWh)] + [Energía de la Red (kWh)] + [Batería Descarga (kWh)] - [Energía a la Carga (kWh)] - [Batería Carga (kWh)] )", "#,0.0"),
    ("2 Balance", "Autosuficiencia", "1 - DIVIDE ( MIN ( [Energía de la Red (kWh)], [Energía a la Carga (kWh)] ), [Energía a la Carga (kWh)] )", "0.0%"),
    ("2 Balance", "Fracción Solar", "DIVIDE ( [Energía Solar (kWh)], [Energía Solar (kWh)] + [Energía de la Red (kWh)] )", "0.0%"),
    ("2 Balance", "Dependencia de la Red", "DIVIDE ( [Energía de la Red (kWh)], [Energía Solar (kWh)] + [Energía de la Red (kWh)] )", "0.0%"),
    ("2 Balance", "Eficiencia del Sistema", "DIVIDE ( [Energía a la Carga (kWh)], [Energía Solar (kWh)] + [Energía de la Red (kWh)] )", "0.0%"),
    ("2 Balance", "Balance (kWh)", ["SWITCH ( SELECTEDVALUE ( Balance[Componente] ),",
                                   '    "Sol", [Energía Solar (kWh)],', '    "Red pública", [Energía de la Red (kWh)],',
                                   '    "Batería (descarga)", [Batería Descarga (kWh)],', '    "Carga (equipos)", [Energía a la Carga (kWh)],',
                                   '    "Batería (carga)", [Batería Carga (kWh)],', '    "Pérdidas de conversión", [Pérdidas de Conversión (kWh)] )'], "#,0.0"),
    ("3 Batería", "Ciclos Equivalentes",
     ["SUMX ( VALUES ( dim_inversor[cod_inversor] ),",
      "    DIVIDE ( CALCULATE ( [Batería Descarga (kWh)] ), CALCULATE ( MAX ( dim_inversor[bateria_kwh] ) ) ) )"], "#,0.0"),
    ("3 Batería", "SoC Promedio", f"AVERAGE ( {H}[soc_prom_pct] ) / 100", "0.0%"),
    ("3 Batería", "SoC Mínimo", f"MIN ( {H}[soc_min_pct] ) / 100", "0.0%"),
    ("4 Economía", "Tarifa Seleccionada", "SELECTEDVALUE ( Tarifa[Tarifa COP por kWh], 991.29 )", "#,0.00"),
    ("4 Economía", "Ahorro Solar (COP)", "[Energía Solar (kWh)] * [Tarifa Seleccionada]", "$ #,0"),
    ("4 Economía", "Costo de la Red (COP)", "[Energía de la Red (kWh)] * [Tarifa Seleccionada]", "$ #,0"),
    ("4 Economía", "Paneles Adicionales Seleccionados", "SELECTEDVALUE ( 'Paneles adicionales'[Paneles adicionales %], 0 )", "0%"),
    ("4 Economía", "Energía Solar Escenario (kWh)", "[Energía Solar (kWh)] * ( 1 + [Paneles Adicionales Seleccionados] )", "#,0.0"),
    ("4 Economía", "Ahorro Escenario (COP)",
     "MIN ( [Energía Solar Escenario (kWh)], [Energía a la Carga (kWh)] + [Batería Carga (kWh)] ) * [Tarifa Seleccionada]", "$ #,0"),
    ("5 Calidad de datos", "Horas Posibles",
     "CALCULATE ( COUNTROWS ( dim_fecha ), dim_fecha[con_telemetria] = TRUE () ) * 24 * CALCULATE ( DISTINCTCOUNT ( dim_inversor[cod_inversor] ), dim_inversor[cod_inversor] > 0 )", "#,0"),
    ("5 Calidad de datos", "Disponibilidad del Registro", f"DIVIDE ( SUM ( {H}[minutos_con_dato] ) / 60, [Horas Posibles] )", "0.0%"),
    ("5 Calidad de datos", "% Datos Válidos", f"DIVIDE ( SUM ( {H}[lecturas_validas] ), SUM ( {H}[lecturas_total] ) )", "0.00%"),
    ("5 Calidad de datos", "Horas con Red Disponible", f"SUM ( {H}[minutos_red_ok] ) / 60", "#,0"),
    ("6 Eventos", "Eventos", "COUNTROWS ( fact_evento )", "#,0"),
    ("6 Eventos", "Horas en Evento", "SUM ( fact_evento[duracion_min] ) / 60", "#,0.0"),
    ("6 Eventos", "Cortes de Red", 'CALCULATE ( [Eventos], dim_tipo_evento[cod_evento] = "RED_NO_DISPONIBLE" )', "#,0"),
    ("6 Eventos", "Horas sin Red", 'CALCULATE ( [Horas en Evento], dim_tipo_evento[cod_evento] = "RED_NO_DISPONIBLE" )', "#,0.0"),
    ("6 Eventos", "Episodios de Batería Baja", 'CALCULATE ( [Eventos], dim_tipo_evento[cod_evento] = "SOC_BAJO" )', "#,0"),
    ("7 Inteligencia de tiempo", "Solar Mes Anterior (kWh)", "CALCULATE ( [Energía Solar (kWh)], DATEADD ( dim_fecha[fecha], -1, MONTH ) )", "#,0.0"),
    ("7 Inteligencia de tiempo", "Var Solar vs Mes Anterior", "DIVIDE ( [Energía Solar (kWh)] - [Solar Mes Anterior (kWh)], [Solar Mes Anterior (kWh)] )", "+0.0%;-0.0%;0.0%"),
    ("7 Inteligencia de tiempo", "Fracción Solar Mes Anterior", "CALCULATE ( [Fracción Solar], DATEADD ( dim_fecha[fecha], -1, MONTH ) )", "0.0%"),
    ("7 Inteligencia de tiempo", "Solar Año Anterior (kWh)", "CALCULATE ( [Energía Solar (kWh)], SAMEPERIODLASTYEAR ( dim_fecha[fecha] ) )", "#,0.0"),
    ("7 Inteligencia de tiempo", "Solar Acumulado del Año (kWh)", "TOTALYTD ( [Energía Solar (kWh)], dim_fecha[fecha] )", "#,0.0"),
    ("7 Inteligencia de tiempo", "Fracción Solar Móvil 7 Días",
     "CALCULATE ( [Fracción Solar], DATESINPERIOD ( dim_fecha[fecha], MAX ( dim_fecha[fecha] ), -7, DAY ) )", "0.0%"),
    ("8 Actividad", "Registros de Contexto", "COUNTROWS ( fact_actividad )", "#,0"),
    ("8 Actividad", "Entrenamientos en GPU", "CALCULATE ( [Registros de Contexto], fact_actividad[es_gpu] = TRUE () )", "#,0"),
    ("8 Actividad", "Horas de Carga de Cómputo",
     'CALCULATE ( SUM ( fact_actividad[duracion_min] ) / 60, dim_tipo_contexto[es_carga] = TRUE () )', "#,0.0"),
]
out += [f"{T}table _Medidas", ""]
for carpeta, nombre, expr, fmt in M:
    if isinstance(expr, list):
        out.append(f"{T*2}measure '{nombre}' = ```")
        out += [f"{T*4}{l}" for l in expr]
        out.append(f"{T*4}```")
    else:
        out.append(f"{T*2}measure '{nombre}' = {expr}")
    if fmt:
        out.append(f"{T*3}formatString: {fmt}")
    out += [f"{T*3}displayFolder: {carpeta}", ""]
out += [f"{T*2}column Columna", f"{T*3}dataType: int64", f"{T*3}isHidden", f"{T*3}isNameInferred",
        f"{T*3}summarizeBy: none", f"{T*3}sourceColumn: [Columna]", "",
        f"{T*2}partition _Medidas = calculated", f"{T*3}mode: import", f'{T*3}source = ROW ( "Columna", 1 )', ""]

# ---------------- Relaciones (varios a uno, de la dimensión al hecho) ----------------
R = []
for f, dims in [("fact_energia_hora", ["fecha", "hora", "inversor"]),
                ("fact_evento", ["fecha", "hora", "inversor", "tipo_evento"]),
                ("fact_actividad", ["fecha", "hora", "inversor", "tipo_contexto", "dispositivo"]),
                ("fact_contador_diario", ["fecha", "inversor"])]:
    for d in dims:
        R.append((f, f"sk_{d}", f"dim_{d}", f"sk_{d}"))
for f, fc, d, dc in R:
    out += [f"{T}relationship rel_{f}_{fc}", f"{T*2}fromColumn: {f}.{fc}", f"{T*2}toColumn: {d}.{dc}", ""]

dest = Path(__file__).resolve().parents[1] / "powerbi" / "modelo_solarbi.tmdl"
dest.write_text("\n".join(out), encoding="utf-8")
print(f"{dest}: {len(out)} líneas, {len(R)} relaciones, {len(M)} medidas")
