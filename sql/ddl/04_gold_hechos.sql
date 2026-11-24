-- =====================================================================
-- SolarBI · 04 · Capa Gold · Tablas de hechos
-- =====================================================================

-- Proceso 1: BALANCE ENERGÉTICO
-- Grano: un inversor × una hora local. Hechos aditivos en kWh.
CREATE TABLE gold.fact_energia_hora (
    sk_fecha            INTEGER  NOT NULL REFERENCES gold.dim_fecha,
    sk_hora             SMALLINT NOT NULL REFERENCES gold.dim_hora,
    sk_inversor         INTEGER  NOT NULL REFERENCES gold.dim_inversor,
    ts_hora_utc         TIMESTAMPTZ NOT NULL,
    e_solar_kwh         NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (e_solar_kwh >= 0),
    e_carga_kwh         NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (e_carga_kwh >= 0),
    e_red_kwh           NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (e_red_kwh >= 0),
    e_bat_carga_kwh     NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (e_bat_carga_kwh >= 0),
    e_bat_descarga_kwh  NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (e_bat_descarga_kwh >= 0),
    soc_prom_pct        NUMERIC(5,1),
    soc_min_pct         NUMERIC(5,1),
    minutos_con_dato    SMALLINT NOT NULL CHECK (minutos_con_dato BETWEEN 0 AND 60),
    minutos_red_ok      SMALLINT NOT NULL CHECK (minutos_red_ok BETWEEN 0 AND 60),
    lecturas_total      INTEGER  NOT NULL,
    lecturas_validas    INTEGER  NOT NULL,
    PRIMARY KEY (sk_inversor, ts_hora_utc),
    CHECK (lecturas_validas <= lecturas_total)
);

-- Proceso 2: EVENTOS OPERATIVOS
-- Grano: un evento (intervalo continuo) de un tipo en un inversor.
CREATE TABLE gold.fact_evento (
    id_evento           BIGSERIAL PRIMARY KEY,
    sk_tipo_evento      SMALLINT NOT NULL REFERENCES gold.dim_tipo_evento,
    sk_inversor         INTEGER  NOT NULL REFERENCES gold.dim_inversor,
    sk_fecha            INTEGER  NOT NULL REFERENCES gold.dim_fecha,
    sk_hora             SMALLINT NOT NULL REFERENCES gold.dim_hora,
    inicio_utc          TIMESTAMPTZ NOT NULL,
    fin_utc             TIMESTAMPTZ NOT NULL,
    duracion_min        NUMERIC(10,1) NOT NULL CHECK (duracion_min >= 0),
    valor_extremo       NUMERIC(8,1),        -- p. ej. SoC mínimo durante el evento
    descripcion         VARCHAR(200),
    CHECK (fin_utc >= inicio_utc)
);

-- Proceso 3: ACTIVIDAD Y CONTEXTO (qué cargas explican el consumo)
-- Grano: un registro de contexto (anotación) con su intervalo.
CREATE TABLE gold.fact_actividad (
    id_contexto         INTEGER  PRIMARY KEY,   -- dimensión degenerada (id de la fuente)
    sk_tipo_contexto    SMALLINT NOT NULL REFERENCES gold.dim_tipo_contexto,
    sk_dispositivo      SMALLINT NOT NULL REFERENCES gold.dim_dispositivo,
    sk_inversor         INTEGER  NOT NULL REFERENCES gold.dim_inversor,
    sk_fecha            INTEGER  NOT NULL REFERENCES gold.dim_fecha,
    sk_hora             SMALLINT NOT NULL REFERENCES gold.dim_hora,
    inicio_utc          TIMESTAMPTZ,
    fin_utc             TIMESTAMPTZ,
    duracion_min        NUMERIC(10,1),
    nucleos_cpu         SMALLINT,
    es_gpu              BOOLEAN NOT NULL DEFAULT FALSE,
    carga_estimada      VARCHAR(20)
);

-- Proceso 4: CONTADORES DIARIOS DEL INVERSOR (validación independiente)
-- Grano: un inversor × un día local.
CREATE TABLE gold.fact_contador_diario (
    sk_fecha            INTEGER  NOT NULL REFERENCES gold.dim_fecha,
    sk_inversor         INTEGER  NOT NULL REFERENCES gold.dim_inversor,
    pv_kwh              NUMERIC(8,2),
    carga_kwh           NUMERIC(8,2),
    carga_desde_red_kwh NUMERIC(8,2),
    bat_carga_kwh       NUMERIC(8,2),
    bat_descarga_kwh    NUMERIC(8,2),
    PRIMARY KEY (sk_inversor, sk_fecha)
);

-- Proceso 5: MONITOREO CASI EN TIEMPO REAL (lo alimenta el simulador)
-- Grano: un inversor × un minuto. Solo inserción.
CREATE TABLE gold.fact_lectura_rt (
    cod_inversor        SMALLINT     NOT NULL CHECK (cod_inversor IN (1, 2)),
    ts                  TIMESTAMPTZ  NOT NULL,
    pv_w                NUMERIC(8,1),
    carga_w             NUMERIC(8,1),
    red_w               NUMERIC(8,1),
    bat_w               NUMERIC(8,1),
    soc_pct             NUMERIC(5,1) CHECK (soc_pct BETWEEN 0 AND 100),
    red_v               NUMERIC(5,1),
    origen              VARCHAR(20)  NOT NULL DEFAULT 'simulador',
    UNIQUE (cod_inversor, ts)
);
