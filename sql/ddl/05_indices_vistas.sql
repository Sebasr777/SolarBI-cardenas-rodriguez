-- =====================================================================
-- SolarBI · 05 · Índices y vistas
-- Cada índice responde a un patrón de consulta concreto.
-- =====================================================================

-- Silver: se escribe en orden de tiempo y se consulta por rangos → BRIN (diminuto)
CREATE INDEX lectura_minuto_ts_brin ON silver.lectura_minuto USING BRIN (ts_minuto);

-- Hechos de energía: Power BI filtra por fecha y por hora del día
CREATE INDEX fact_energia_fecha_idx ON gold.fact_energia_hora (sk_fecha);
CREATE INDEX fact_energia_hora_idx  ON gold.fact_energia_hora (sk_hora);

-- Eventos: "eventos de tipo X en el periodo Y"
CREATE INDEX fact_evento_tipo_inicio_idx ON gold.fact_evento (sk_tipo_evento, inicio_utc);

-- Actividad: búsquedas por tipo de contexto y periodo
CREATE INDEX fact_actividad_tipo_idx ON gold.fact_actividad (sk_tipo_contexto, inicio_utc);

-- Streaming: Grafana siempre pide "las últimas N horas" → BRIN + último valor por inversor
CREATE INDEX fact_lectura_rt_ts_brin ON gold.fact_lectura_rt USING BRIN (ts);
CREATE INDEX fact_lectura_rt_ultimo_idx ON gold.fact_lectura_rt (cod_inversor, ts DESC);

-- ---------------------------------------------------------------------
-- Vistas de indicadores (las usan DBeaver, la conciliación y Power BI para validar)
-- ---------------------------------------------------------------------
CREATE VIEW gold.v_balance_dia AS
SELECT f.fecha, i.cod_inversor AS inversor,
       ROUND(SUM(h.e_solar_kwh), 3)        AS solar_kwh,
       ROUND(SUM(h.e_carga_kwh), 3)        AS carga_kwh,
       ROUND(SUM(h.e_red_kwh), 3)          AS red_kwh,
       ROUND(SUM(h.e_bat_carga_kwh), 3)    AS bat_carga_kwh,
       ROUND(SUM(h.e_bat_descarga_kwh), 3) AS bat_descarga_kwh,
       ROUND(1 - LEAST(SUM(h.e_red_kwh), SUM(h.e_carga_kwh)) / NULLIF(SUM(h.e_carga_kwh), 0), 4) AS autosuficiencia,
       ROUND(SUM(h.e_solar_kwh) / NULLIF(SUM(h.e_solar_kwh) + SUM(h.e_red_kwh), 0), 4)           AS fraccion_solar,
       ROUND(SUM(h.minutos_con_dato) / 1440.0, 4)                                                AS disponibilidad_registro,
       ROUND(SUM(h.lecturas_validas)::numeric / NULLIF(SUM(h.lecturas_total), 0), 4)            AS pct_datos_validos
FROM gold.fact_energia_hora h
JOIN gold.dim_fecha f    ON f.sk_fecha = h.sk_fecha
JOIN gold.dim_inversor i ON i.sk_inversor = h.sk_inversor
GROUP BY f.fecha, i.cod_inversor;

CREATE VIEW gold.v_balance_mes AS
SELECT f.anio_mes, i.cod_inversor AS inversor,
       ROUND(SUM(h.e_solar_kwh), 2)        AS solar_kwh,
       ROUND(SUM(h.e_carga_kwh), 2)        AS carga_kwh,
       ROUND(SUM(h.e_red_kwh), 2)          AS red_kwh,
       ROUND(SUM(h.e_bat_descarga_kwh), 2) AS bat_descarga_kwh,
       ROUND(1 - LEAST(SUM(h.e_red_kwh), SUM(h.e_carga_kwh)) / NULLIF(SUM(h.e_carga_kwh), 0), 4) AS autosuficiencia,
       ROUND(SUM(h.e_solar_kwh) / NULLIF(SUM(h.e_solar_kwh) + SUM(h.e_red_kwh), 0), 4)           AS fraccion_solar,
       ROUND(SUM(h.minutos_con_dato) / (COUNT(DISTINCT f.fecha) * 1440.0), 4)                    AS disponibilidad_registro_dias_con_dato
FROM gold.fact_energia_hora h
JOIN gold.dim_fecha f    ON f.sk_fecha = h.sk_fecha
JOIN gold.dim_inversor i ON i.sk_inversor = h.sk_inversor
GROUP BY f.anio_mes, i.cod_inversor;

-- Grafana: última lectura de cada inversor (panel de estado actual)
CREATE VIEW gold.v_rt_estado_actual AS
SELECT DISTINCT ON (cod_inversor)
       cod_inversor, ts, pv_w, carga_w, red_w, bat_w, soc_pct, red_v,
       CASE WHEN red_v < 180 THEN 'Sin red'
            WHEN soc_pct < 20 THEN 'Batería baja'
            WHEN pv_w > 50 THEN 'Generando'
            ELSE 'Normal' END AS estado
FROM gold.fact_lectura_rt
ORDER BY cod_inversor, ts DESC;
