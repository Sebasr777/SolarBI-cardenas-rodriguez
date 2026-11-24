-- =====================================================================
-- SolarBI · 06 · Auditoría y permisos
-- Las tablas de audit NO se borran: acumulan la historia de corridas.
-- =====================================================================
CREATE TABLE IF NOT EXISTS audit.etl_corrida (
    id_corrida        SERIAL PRIMARY KEY,
    inicio            TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin               TIMESTAMPTZ,
    estado            VARCHAR(20) NOT NULL DEFAULT 'en curso',
    archivo_fuente    VARCHAR(200),
    sha256_fuente     CHAR(64),
    filas_leidas      BIGINT,
    filas_gold        BIGINT,
    huella_resultado  CHAR(32),       -- md5 de los totales de gold: igual en cada corrida = idempotente
    mensaje           TEXT
);

CREATE TABLE IF NOT EXISTS audit.regla_calidad (
    id_corrida     INTEGER     NOT NULL REFERENCES audit.etl_corrida,
    regla          VARCHAR(10) NOT NULL,
    descripcion    TEXT        NOT NULL,
    dimension_dq   VARCHAR(30) NOT NULL,
    tratamiento    VARCHAR(30) NOT NULL,   -- Descartar / Marcar / Convertir en evento / Corregir
    filas_antes    BIGINT      NOT NULL,
    afectadas      BIGINT      NOT NULL,
    filas_despues  BIGINT      NOT NULL,
    PRIMARY KEY (id_corrida, regla)
);

CREATE TABLE IF NOT EXISTS audit.conciliacion (
    id_corrida     INTEGER       NOT NULL REFERENCES audit.etl_corrida,
    metrica        VARCHAR(120)  NOT NULL,
    total_fuente   NUMERIC(16,3) NOT NULL,
    total_cargado  NUMERIC(16,3) NOT NULL,
    diferencia     NUMERIC(16,3) NOT NULL,
    diferencia_pct NUMERIC(8,3),
    explicacion    TEXT,
    PRIMARY KEY (id_corrida, metrica)
);

-- Permisos de mínimo privilegio (los roles los crea el contenedor de PostgreSQL al iniciar)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bi_lector') THEN
    GRANT USAGE ON SCHEMA gold, audit TO bi_lector;
    GRANT SELECT ON ALL TABLES IN SCHEMA gold, audit TO bi_lector;
    GRANT USAGE ON SCHEMA silver TO bi_lector;
    GRANT SELECT ON silver.contexto TO bi_lector;   -- JSON ya sanitizado (R14)
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
    GRANT USAGE ON SCHEMA gold TO grafana_ro;
    GRANT SELECT ON ALL TABLES IN SCHEMA gold TO grafana_ro;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'simulador') THEN
    GRANT USAGE ON SCHEMA gold, silver TO simulador;
    GRANT SELECT ON silver.lectura_minuto TO simulador;
    GRANT SELECT, INSERT ON gold.fact_lectura_rt TO simulador;
  END IF;
END $$;
REVOKE ALL ON SCHEMA priv FROM PUBLIC;
