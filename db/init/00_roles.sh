#!/bin/bash
# Se ejecuta UNA sola vez, cuando PostgreSQL crea el volumen vacío.
# Crea los roles de mínimo privilegio con las contraseñas que llegan del Secret.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE bi_lector  LOGIN PASSWORD '${BI_LECTOR_PASSWORD}';
CREATE ROLE grafana_ro LOGIN PASSWORD '${GRAFANA_DB_PASSWORD}';
CREATE ROLE simulador  LOGIN PASSWORD '${SIM_DB_PASSWORD}';
CREATE SCHEMA IF NOT EXISTS priv;
REVOKE ALL ON SCHEMA priv FROM PUBLIC;
SQL
echo "Roles bi_lector, grafana_ro y simulador creados"
