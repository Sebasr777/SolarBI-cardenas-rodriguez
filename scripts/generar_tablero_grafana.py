"""Genera grafana/dashboards/microrred.json (el tablero se versiona como JSON).

Se escribe con un script para que cada panel tenga su SQL legible y revisable en Git.
Uso: python scripts/generar_tablero_grafana.py
"""
import json
from pathlib import Path

DS = {"type": "grafana-postgresql-datasource", "uid": "pg-solarbi"}
FILTRO = "cod_inversor IN (${inversor:csv}) AND $__timeFilter(ts)"


def q(sql, fmt="time_series", ref="A"):
    return {"refId": ref, "datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True, "rawSql": sql}


def panel(pid, titulo, tipo, x, y, w, h, targets, **extra):
    p = {"id": pid, "title": titulo, "type": tipo, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets}
    p.update(extra)
    return p


def stat(pid, titulo, col, unidad, x, umbrales, decimales=0):
    sql = (f"SELECT ts AS time, 'Inversor ' || cod_inversor AS metric, {col} AS value "
           f"FROM gold.fact_lectura_rt WHERE {FILTRO} ORDER BY ts")
    return panel(pid, titulo, "stat", x, 0, 4, 5, [q(sql)],
                 options={"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background",
                          "graphMode": "area", "textMode": "value_and_name"},
                 fieldConfig={"defaults": {"unit": unidad, "decimals": decimales,
                                           "thresholds": {"mode": "absolute", "steps": umbrales}},
                              "overrides": []})


verde, amarillo, rojo, azul = "green", "#EAB839", "red", "blue"
paneles = [
    stat(1, "SoC de la batería", "soc_pct", "percent", 0,
         [{"color": rojo, "value": None}, {"color": amarillo, "value": 20}, {"color": verde, "value": 40}]),
    stat(2, "Potencia solar", "pv_w", "watt", 4, [{"color": "#5a6b7d", "value": None}, {"color": amarillo, "value": 50}]),
    stat(3, "Consumo de la carga", "carga_w", "watt", 8, [{"color": azul, "value": None}]),
    stat(4, "Importación de red", "red_w", "watt", 12,
         [{"color": verde, "value": None}, {"color": amarillo, "value": 500}, {"color": rojo, "value": 1500}]),
    panel(5, "Alertas activas", "alertlist", 16, 0, 8, 10, [],
          options={"viewMode": "list", "showOptions": "current", "maxItems": 10,
                   "stateFilter": {"firing": True, "pending": True, "normal": True, "error": True, "noData": False},
                   "alertInstanceLabelFilter": "", "groupMode": "default"}),
    panel(6, "Estado actual por inversor", "table", 0, 5, 16, 5,
          [q("SELECT 'Inversor ' || cod_inversor AS inversor, ts AS ultima_lectura, estado, "
             "soc_pct AS soc, pv_w AS solar_w, carga_w, red_w, red_v FROM gold.v_rt_estado_actual "
             "WHERE cod_inversor IN (${inversor:csv})", fmt="table")],
          fieldConfig={"defaults": {}, "overrides": [
              {"matcher": {"id": "byName", "options": "estado"},
               "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background"}},
                              {"id": "mappings", "value": [{"type": "value", "options": {
                                  "Normal": {"color": "green", "index": 0},
                                  "Generando": {"color": "#EAB839", "index": 1},
                                  "Batería baja": {"color": "red", "index": 2},
                                  "Sin red": {"color": "orange", "index": 3}}}]}]}]}),
    panel(7, "Balance de potencia: de dónde viene y a dónde va (W)", "timeseries", 0, 10, 24, 9,
          [q("SELECT ts AS time, 'Inv ' || cod_inversor || ' · solar' AS metric, pv_w AS value "
             f"FROM gold.fact_lectura_rt WHERE {FILTRO} "
             "UNION ALL SELECT ts, 'Inv ' || cod_inversor || ' · red', red_w "
             f"FROM gold.fact_lectura_rt WHERE {FILTRO} "
             "UNION ALL SELECT ts, 'Inv ' || cod_inversor || ' · batería', bat_w "
             f"FROM gold.fact_lectura_rt WHERE {FILTRO} "
             "UNION ALL SELECT ts, 'Inv ' || cod_inversor || ' · carga', carga_w "
             f"FROM gold.fact_lectura_rt WHERE {FILTRO} ORDER BY 1")],
          fieldConfig={"defaults": {"unit": "watt", "custom": {"lineWidth": 2, "fillOpacity": 8}}, "overrides": []}),
    panel(8, "Estado de carga de la batería (SoC %)", "timeseries", 0, 19, 12, 8,
          [q("SELECT ts AS time, 'Inversor ' || cod_inversor AS metric, soc_pct AS value "
             f"FROM gold.fact_lectura_rt WHERE {FILTRO} ORDER BY 1")],
          fieldConfig={"defaults": {"unit": "percent", "min": 0, "max": 100,
                                    "custom": {"thresholdsStyle": {"mode": "line+area"}},
                                    "thresholds": {"mode": "absolute", "steps": [
                                        {"color": "rgba(255,0,0,0.15)", "value": None},
                                        {"color": "transparent", "value": 20}]}}, "overrides": []}),
    panel(9, "Tensión de la red pública (V)", "timeseries", 12, 19, 12, 8,
          [q("SELECT ts AS time, 'Inversor ' || cod_inversor AS metric, red_v AS value "
             f"FROM gold.fact_lectura_rt WHERE {FILTRO} ORDER BY 1")],
          fieldConfig={"defaults": {"unit": "volt", "min": 0,
                                    "custom": {"thresholdsStyle": {"mode": "line"}},
                                    "thresholds": {"mode": "absolute", "steps": [
                                        {"color": "red", "value": None}, {"color": "green", "value": 180}]}},
                       "overrides": []}),
    panel(10, "Energía de la última hora por fuente (kWh)", "bargauge", 0, 27, 12, 7,
          [q("SELECT 'Solar' AS fuente, SUM(pv_w) / 60000.0 AS kwh FROM gold.fact_lectura_rt "
             "WHERE cod_inversor IN (${inversor:csv}) AND ts > now() - interval '1 hour' "
             "UNION ALL SELECT 'Red', SUM(red_w) / 60000.0 FROM gold.fact_lectura_rt "
             "WHERE cod_inversor IN (${inversor:csv}) AND ts > now() - interval '1 hour' "
             "UNION ALL SELECT 'Batería (descarga)', SUM(GREATEST(bat_w, 0)) / 60000.0 FROM gold.fact_lectura_rt "
             "WHERE cod_inversor IN (${inversor:csv}) AND ts > now() - interval '1 hour'", fmt="table")],
          options={"orientation": "horizontal", "displayMode": "gradient",
                   "reduceOptions": {"values": True, "calcs": [], "fields": "/kwh/"}},
          fieldConfig={"defaults": {"unit": "kwatth", "decimals": 2}, "overrides": []}),
    panel(11, "Fracción solar de la última hora", "gauge", 12, 27, 12, 7,
          [q("SELECT SUM(pv_w) / NULLIF(SUM(pv_w) + SUM(red_w), 0) AS fraccion_solar FROM gold.fact_lectura_rt "
             "WHERE cod_inversor IN (${inversor:csv}) AND ts > now() - interval '1 hour'", fmt="table")],
          fieldConfig={"defaults": {"unit": "percentunit", "min": 0, "max": 1, "decimals": 0,
                                    "thresholds": {"mode": "absolute", "steps": [
                                        {"color": "red", "value": None}, {"color": "#EAB839", "value": 0.3},
                                        {"color": "green", "value": 0.6}]}}, "overrides": []}),
]

tablero = {
    "uid": "solarbi-microrred", "title": "SolarBI · Monitoreo de la microrred",
    "tags": ["solarbi", "microrred"], "timezone": "browser", "schemaVersion": 39,
    "refresh": "30s", "time": {"from": "now-3h", "to": "now"}, "editable": False,
    "templating": {"list": [{
        "name": "inversor", "label": "Inversor", "type": "query", "datasource": DS,
        "query": "SELECT cod_inversor AS __value, nombre AS __text FROM gold.dim_inversor WHERE es_actual ORDER BY 1",
        "definition": "SELECT cod_inversor AS __value, nombre AS __text FROM gold.dim_inversor WHERE es_actual",
        "multi": True, "includeAll": True, "current": {"selected": True, "text": "All", "value": "$__all"},
        "refresh": 1}]},
    "panels": paneles,
}

salida = Path(__file__).resolve().parents[1] / "grafana" / "dashboards" / "microrred.json"
salida.write_text(json.dumps(tablero, ensure_ascii=False, indent=2), encoding="utf-8")
print("Tablero escrito en", salida)
