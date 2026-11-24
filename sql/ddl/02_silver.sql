-- =====================================================================
-- SolarBI · 02 · Capa Silver
-- =====================================================================

-- Lecturas eléctricas agregadas a 1 minuto (grano: inversor × minuto UTC)
CREATE TABLE silver.lectura_minuto (
    inversor            SMALLINT     NOT NULL CHECK (inversor IN (1, 2)),
    ts_minuto           TIMESTAMPTZ  NOT NULL,           -- inicio del minuto (UTC)
    n_lecturas          SMALLINT     NOT NULL CHECK (n_lecturas > 0),
    n_validas           SMALLINT     NOT NULL CHECK (n_validas >= 0),
    pv_w                NUMERIC(8,1),                    -- potencia solar media (W)
    carga_w             NUMERIC(8,1),                    -- potencia entregada a la carga (W)
    red_w               NUMERIC(8,1),                    -- potencia importada de la red (W)
    bat_w               NUMERIC(8,1),                    -- potencia de batería (+ descarga, - carga) (W)
    soc_pct             NUMERIC(5,1) CHECK (soc_pct BETWEEN 0 AND 100),
    bat_v               NUMERIC(5,2),
    red_v_min           NUMERIC(5,1),                    -- tensión mínima de red en el minuto (V)
    salida_v            NUMERIC(5,1),
    alarma_activa       BOOLEAN      NOT NULL DEFAULT FALSE,
    seg_cubiertos       NUMERIC(8,3) NOT NULL,           -- segundos cubiertos por intervalos <= 10 min
    e_solar_wh          NUMERIC(10,3) NOT NULL,          -- energía integrada (trapecio) que cierra en este minuto
    e_carga_wh          NUMERIC(10,3) NOT NULL,
    e_red_wh            NUMERIC(10,3) NOT NULL,
    e_bat_carga_wh      NUMERIC(10,3) NOT NULL,
    e_bat_descarga_wh   NUMERIC(10,3) NOT NULL,
    PRIMARY KEY (inversor, ts_minuto)
);
COMMENT ON TABLE silver.lectura_minuto IS 'Lecturas de analog_measurements agregadas por minuto: potencias medias y energía integrada por trapecio. Grano: inversor × minuto.';

-- Contexto (anotaciones de estaciones de trabajo y personal) con el JSON original en JSONB
CREATE TABLE silver.contexto (
    id_contexto     INTEGER     PRIMARY KEY,
    registrado      TIMESTAMPTZ,
    inicio          TIMESTAMPTZ,
    fin             TIMESTAMPTZ,
    fuente          VARCHAR(60) NOT NULL,
    tipo_contexto   VARCHAR(80) NOT NULL,
    dispositivo     VARCHAR(40) NOT NULL,
    inversor        SMALLINT,
    valor           JSONB       NOT NULL,                -- payload sanitizado (ver regla R14)
    CHECK (fin IS NULL OR inicio IS NULL OR fin >= inicio)
);
CREATE INDEX contexto_valor_gin ON silver.contexto USING GIN (valor jsonb_path_ops);
CREATE INDEX contexto_tipo_inicio ON silver.contexto (tipo_contexto, inicio);

-- Contadores diarios del propio inversor (tabla statistics): fuente independiente para conciliar
CREATE TABLE silver.contador_diario (
    inversor              SMALLINT NOT NULL,
    fecha_local           DATE     NOT NULL,
    pv_kwh                NUMERIC(8,2),
    carga_kwh             NUMERIC(8,2),
    carga_desde_red_kwh   NUMERIC(8,2),
    red_a_bateria_kwh     NUMERIC(8,2),
    bat_carga_kwh         NUMERIC(8,2),
    bat_descarga_kwh      NUMERIC(8,2),
    PRIMARY KEY (inversor, fecha_local)
);

-- Historia de configuración del inversor (insumo de la SCD tipo 2)
CREATE TABLE silver.config_inversor (
    inversor            SMALLINT    NOT NULL,
    valido_desde        TIMESTAMPTZ NOT NULL,
    bateria_ah          NUMERIC(6,1),
    max_red_w           INTEGER,
    prioridad_carga     SMALLINT,
    soc_alarma_pct      SMALLINT,
    soc_a_red_pct       SMALLINT,
    PRIMARY KEY (inversor, valido_desde)
);
