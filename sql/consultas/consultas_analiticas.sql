-- =====================================================================
-- SolarBI · Consultas analíticas (ejecutar en DBeaver con Ctrl + Enter)
-- Cada consulta responde una pregunta de negocio. Hora local: Asia/Shanghai.
-- Tarifa de referencia: EPM, octubre de 2026, CU nivel I = 991,29 COP/kWh.
-- =====================================================================

-- Q1 · ¿Cómo evoluciona el balance de cada inversor mes a mes?  (LAG: variación vs. mes anterior)
SELECT inversor, anio_mes, solar_kwh, carga_kwh, red_kwh, fraccion_solar,
       LAG(fraccion_solar) OVER w                               AS fraccion_solar_mes_anterior,
       ROUND(fraccion_solar - LAG(fraccion_solar) OVER w, 4)    AS variacion
FROM gold.v_balance_mes
WINDOW w AS (PARTITION BY inversor ORDER BY anio_mes)
ORDER BY inversor, anio_mes;

-- Q2 · Comparativo entre periodos: cada trimestre contra el trimestre anterior (planta completa)
WITH t AS (
  SELECT f.anio, f.trimestre,
         SUM(h.e_solar_kwh) AS solar, SUM(h.e_red_kwh) AS red, SUM(h.e_carga_kwh) AS carga
  FROM gold.fact_energia_hora h JOIN gold.dim_fecha f USING (sk_fecha)
  GROUP BY f.anio, f.trimestre)
SELECT anio, trimestre, ROUND(solar, 1) AS solar_kwh, ROUND(red, 1) AS red_kwh,
       ROUND(100 * (solar / NULLIF(LAG(solar) OVER (ORDER BY anio, trimestre), 0) - 1), 1) AS crec_solar_pct,
       ROUND(100 * (red   / NULLIF(LAG(red)   OVER (ORDER BY anio, trimestre), 0) - 1), 1) AS crec_red_pct
FROM t ORDER BY anio, trimestre;

-- Q3 · Mismo mes, año distinto: julio 2025 vs. julio 2026 (únicos meses repetidos en la fuente)
SELECT f.mes_nombre, f.anio, i.cod_inversor AS inversor,
       ROUND(SUM(h.e_solar_kwh), 1) AS solar_kwh, ROUND(SUM(h.e_red_kwh), 1) AS red_kwh,
       ROUND(SUM(h.e_carga_kwh), 1) AS carga_kwh
FROM gold.fact_energia_hora h
JOIN gold.dim_fecha f USING (sk_fecha) JOIN gold.dim_inversor i USING (sk_inversor)
WHERE f.mes = 7
GROUP BY f.mes_nombre, f.anio, i.cod_inversor ORDER BY inversor, anio;

-- Q4 · ¿De dónde viene la energía a cada hora del día?  (perfil horario y franja)
SELECT d.franja, d.etiqueta AS hora,
       ROUND(SUM(h.e_solar_kwh), 1) AS solar_kwh,
       ROUND(SUM(h.e_red_kwh), 1)   AS red_kwh,
       ROUND(SUM(h.e_bat_descarga_kwh), 1) AS bateria_kwh,
       ROUND(SUM(h.e_carga_kwh), 1) AS carga_kwh,
       ROUND(100 * SUM(h.e_red_kwh) / NULLIF(SUM(SUM(h.e_red_kwh)) OVER (), 0), 1) AS pct_de_la_red_total
FROM gold.fact_energia_hora h JOIN gold.dim_hora d USING (sk_hora)
GROUP BY d.franja, d.etiqueta ORDER BY d.etiqueta;

-- Q5 · ¿La fracción solar mejora?  Promedio móvil de 7 días (ventana deslizante)
SELECT inversor, fecha, fraccion_solar,
       ROUND(AVG(fraccion_solar) OVER (PARTITION BY inversor ORDER BY fecha
                                       ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 4) AS fraccion_solar_movil_7d
FROM gold.v_balance_dia
WHERE disponibilidad_registro >= 0.9
ORDER BY inversor, fecha;

-- Q6 · Los 5 días con más energía comprada a la red en cada mes (RANK)
SELECT * FROM (
  SELECT anio_mes, fecha, inversor, red_kwh,
         RANK() OVER (PARTITION BY f.anio_mes ORDER BY red_kwh DESC) AS puesto
  FROM gold.v_balance_dia b JOIN gold.dim_fecha f USING (fecha)) x
WHERE puesto <= 5 ORDER BY anio_mes, puesto;

-- Q7 · Cortes de red más largos por inversor (ROW_NUMBER) y cómo los cubrió la batería
SELECT * FROM (
  SELECT i.cod_inversor AS inversor, e.inicio_utc AT TIME ZONE 'Asia/Shanghai' AS inicio_local,
         ROUND(e.duracion_min / 60, 1) AS horas,
         ROW_NUMBER() OVER (PARTITION BY i.cod_inversor ORDER BY e.duracion_min DESC) AS n
  FROM gold.fact_evento e
  JOIN gold.dim_tipo_evento t USING (sk_tipo_evento)
  JOIN gold.dim_inversor i USING (sk_inversor)
  WHERE t.cod_evento = 'RED_NO_DISPONIBLE') x
WHERE n <= 3;

-- Q8 · JSON (operadores nativos): ¿qué modelos de red neuronal se entrenaron en GPU?
--      ->> extrae texto, @> busca por contenido (usa el índice GIN), ? verifica que exista la clave
SELECT valor->>'model'                     AS modelo,
       valor->>'dataset'                   AS dataset,
       COUNT(*)                            AS entrenamientos,
       ROUND(AVG((valor->>'epochs')::int), 1) AS epocas_promedio
FROM silver.contexto
WHERE valor @> '{"context_type": "gpu_cnn_training_workload"}'
  AND valor ? 'model'
GROUP BY 1, 2 ORDER BY entrenamientos DESC;

-- Q9 · JSON + energía: ¿cuánta energía consume la carga cuando hay entrenamiento en GPU?
WITH gpu AS (
  SELECT DISTINCT date_trunc('hour', inicio) AS hora
  FROM silver.contexto
  WHERE valor->>'context_type' = 'gpu_cnn_training_workload')
SELECT CASE WHEN g.hora IS NULL THEN 'Sin entrenamiento GPU' ELSE 'Con entrenamiento GPU' END AS condicion,
       COUNT(*) AS horas,
       ROUND(AVG(h.e_carga_kwh) * 1000) AS carga_media_wh_por_hora
FROM gold.fact_energia_hora h
JOIN gold.dim_inversor i USING (sk_inversor)
LEFT JOIN gpu g ON g.hora = h.ts_hora_utc
WHERE i.cod_inversor = 1 AND h.minutos_con_dato >= 55
GROUP BY 1;

-- Q10 · Indicador económico: ahorro mensual en COP por la energía solar (tarifa EPM)
SELECT anio_mes, inversor, solar_kwh,
       ROUND(solar_kwh * 991.29) AS ahorro_cop,
       ROUND(red_kwh   * 991.29) AS costo_red_cop
FROM gold.v_balance_mes ORDER BY anio_mes, inversor;

-- Q11 · Batería: ciclos equivalentes por mes (energía descargada / capacidad nominal) y SoC mínimo
SELECT f.anio_mes, i.cod_inversor AS inversor,
       ROUND(SUM(h.e_bat_descarga_kwh) / MAX(i.bateria_kwh), 2) AS ciclos_equivalentes,
       MIN(h.soc_min_pct) AS soc_minimo
FROM gold.fact_energia_hora h
JOIN gold.dim_fecha f USING (sk_fecha) JOIN gold.dim_inversor i USING (sk_inversor)
GROUP BY f.anio_mes, i.cod_inversor ORDER BY 1, 2;

-- Q12 · Calidad: disponibilidad del registro y % de lecturas válidas por mes e inversor
SELECT f.anio_mes, i.cod_inversor AS inversor,
       ROUND(SUM(h.minutos_con_dato) / (EXTRACT(DAY FROM (date_trunc('month', MIN(f.fecha)) + INTERVAL '1 month - 1 day')) * 1440), 4)
             AS disponibilidad_registro,
       ROUND(SUM(h.lecturas_validas)::numeric / NULLIF(SUM(h.lecturas_total), 0), 4) AS pct_datos_validos
FROM gold.fact_energia_hora h
JOIN gold.dim_fecha f USING (sk_fecha) JOIN gold.dim_inversor i USING (sk_inversor)
GROUP BY f.anio_mes, i.cod_inversor ORDER BY 1, 2;

-- Q13 · Auditoría: ¿qué hizo cada corrida del ETL?  (huella igual = carga idempotente)
SELECT id_corrida, inicio, estado, filas_leidas, filas_gold, huella_resultado FROM audit.etl_corrida ORDER BY 1;
SELECT * FROM audit.regla_calidad WHERE id_corrida = (SELECT MAX(id_corrida) FROM audit.regla_calidad) ORDER BY regla;
SELECT * FROM audit.conciliacion  WHERE id_corrida = (SELECT MAX(id_corrida) FROM audit.conciliacion);
