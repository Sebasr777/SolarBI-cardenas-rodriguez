-- =====================================================================
-- SolarBI · 01 · Esquemas por capa
-- Bronze = el archivo opencem-v1.0.0.sqlite (no se modifica, no entra aquí)
-- silver = lecturas limpias agregadas por minuto, contexto JSONB, eventos
-- gold   = modelo dimensional (dimensiones + hechos) que leen Power BI y Grafana
-- audit  = bitácora del ETL: corridas, reglas de calidad y conciliación
-- priv   = reservado para datos sensibles (hoy vacío: la fuente ya viene anonimizada)
-- El ETL recrea silver y gold en cada corrida (carga idempotente).
-- audit NO se borra: guarda la historia de todas las corridas.
-- =====================================================================
DROP SCHEMA IF EXISTS silver CASCADE;
DROP SCHEMA IF EXISTS gold   CASCADE;
CREATE SCHEMA silver;
CREATE SCHEMA gold;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS priv;

COMMENT ON SCHEMA silver IS 'Capa Silver: lecturas validadas y agregadas a 1 minuto, contexto JSONB y eventos detectados';
COMMENT ON SCHEMA gold   IS 'Capa Gold: modelo dimensional en estrella para Power BI y Grafana';
COMMENT ON SCHEMA audit  IS 'Bitácora del ETL (no se borra entre corridas)';
