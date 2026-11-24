-- =====================================================================
-- SolarBI · 03 · Capa Gold · Dimensiones
-- Todas tienen un miembro desconocido con sk = -1.
-- La hora local de la instalación es Asia/Shanghai (UTC+8, sin horario de verano).
-- =====================================================================

-- Fecha local de la instalación (dimensión conformada)
CREATE TABLE gold.dim_fecha (
    sk_fecha          INTEGER     PRIMARY KEY,           -- AAAAMMDD
    fecha             DATE        NOT NULL UNIQUE,
    anio              SMALLINT    NOT NULL,
    trimestre         SMALLINT    NOT NULL,
    mes               SMALLINT    NOT NULL,
    mes_nombre        VARCHAR(12) NOT NULL,
    anio_mes          CHAR(7)     NOT NULL,              -- '2025-07'
    semana_iso        SMALLINT    NOT NULL,
    dia_mes           SMALLINT    NOT NULL,
    dia_semana_num    SMALLINT    NOT NULL,              -- 1 = lunes
    dia_semana        VARCHAR(10) NOT NULL,
    es_fin_semana     BOOLEAN     NOT NULL,
    estacion          VARCHAR(10) NOT NULL,              -- hemisferio norte (Shenzhen)
    temporada_lluvia  BOOLEAN     NOT NULL,              -- abril a septiembre en Shenzhen
    con_telemetria    BOOLEAN     NOT NULL               -- fecha dentro del periodo con lecturas eléctricas
);

-- Hora del día: DIMENSIÓN CONSTRUIDA POR EL EQUIPO (no existe en la fuente)
CREATE TABLE gold.dim_hora (
    sk_hora          SMALLINT    PRIMARY KEY CHECK (sk_hora BETWEEN -1 AND 23),
    hora             SMALLINT    NOT NULL,
    etiqueta         CHAR(5)     NOT NULL,              -- '13:00'
    franja           VARCHAR(12) NOT NULL,              -- Madrugada / Mañana / Tarde / Noche
    periodo_solar    VARCHAR(16) NOT NULL,              -- Pico solar / Hombro solar / Sin sol
    franja_tarifaria VARCHAR(16) NOT NULL               -- Punta / Fuera de punta (franjas EPM)
);

-- Inversor con historia de configuración: SCD TIPO 2
CREATE TABLE gold.dim_inversor (
    sk_inversor       INTEGER     PRIMARY KEY,
    cod_inversor      SMALLINT    NOT NULL,              -- llave natural (1 o 2)
    nombre            VARCHAR(20) NOT NULL,
    subsistema        VARCHAR(20) NOT NULL,
    bateria_ah        NUMERIC(6,1),                      -- configurado en el inversor
    bateria_kwh       NUMERIC(6,2),                      -- capacidad nominal usada en los indicadores
    capacidad_supuesta BOOLEAN    NOT NULL DEFAULT FALSE,-- TRUE si el inversor no la reporta
    max_red_w         INTEGER,
    prioridad_carga   VARCHAR(30),
    soc_alarma_pct    SMALLINT,
    valido_desde      TIMESTAMPTZ NOT NULL,
    valido_hasta      TIMESTAMPTZ,
    es_actual         BOOLEAN     NOT NULL
);
CREATE UNIQUE INDEX dim_inversor_actual_uq ON gold.dim_inversor (cod_inversor) WHERE es_actual;

-- Tipo de evento operativo (jerarquía: categoría › tipo)
CREATE TABLE gold.dim_tipo_evento (
    sk_tipo_evento   SMALLINT    PRIMARY KEY,
    cod_evento       VARCHAR(30) NOT NULL UNIQUE,
    nombre           VARCHAR(60) NOT NULL,
    categoria        VARCHAR(30) NOT NULL,              -- Red / Batería / Inversor / Datos / Operación manual
    severidad        VARCHAR(15) NOT NULL,              -- Info / Advertencia / Crítica
    origen           VARCHAR(30) NOT NULL,              -- Detectado en lecturas / Registro manual / Bandera del inversor
    regla            TEXT        NOT NULL
);

-- Tipo de contexto (jerarquía: categoría › tipo)
CREATE TABLE gold.dim_tipo_contexto (
    sk_tipo_contexto SMALLINT    PRIMARY KEY,
    tipo_contexto    VARCHAR(80) NOT NULL UNIQUE,
    fuente           VARCHAR(60) NOT NULL,
    categoria        VARCHAR(30) NOT NULL,              -- Carga de cómputo / Sistema operativo / Calendario / Solar / Nota manual / Telemetría
    es_carga         BOOLEAN     NOT NULL               -- TRUE si describe una carga que consume energía
);

-- Dispositivo que originó el contexto
CREATE TABLE gold.dim_dispositivo (
    sk_dispositivo   SMALLINT    PRIMARY KEY,
    dispositivo      VARCHAR(40) NOT NULL UNIQUE,
    tipo             VARCHAR(30) NOT NULL               -- Estación de trabajo / Inversor / Instalación
);
