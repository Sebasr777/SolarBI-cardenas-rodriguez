#!/usr/bin/env bash
# SolarBI · despliegue en Kubernetes (Docker Desktop) con UN solo comando.
#   ./scripts/solarbi.sh up      [dev|demo]   construye imágenes y levanta todo
#   ./scripts/solarbi.sh down                 elimina todo (namespace completo, incluido el volumen)
#   ./scripts/solarbi.sh estado               kubectl get de los recursos
#   ./scripts/solarbi.sh falla corte_red|soc_bajo|ninguno [inversor]
#   ./scripts/solarbi.sh etl                  vuelve a correr el ETL (idempotente)
set -euo pipefail
cd "$(dirname "$0")/.."
RAIZ="$(pwd)"
NS=solarbi
OVERLAY="${2:-dev}"

requisitos() {
  command -v kubectl >/dev/null || { echo "Falta kubectl (viene con Docker Desktop)"; exit 1; }
  [ -f .env ] || { echo "Falta .env: cp .env.example .env y cambie las contraseñas"; exit 1; }
  [ -f data/bronze/opencem-v1.0.0.sqlite ] || { echo "Falta data/bronze/opencem-v1.0.0.sqlite (ver README)"; exit 1; }
  kubectl config use-context docker-desktop >/dev/null 2>&1 || true
}

parche_ruta() {
  cat > k8s/overlays/dev/ruta-datos.local.yaml <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: etl
spec:
  template:
    spec:
      volumes:
        - name: bronze
          hostPath:
            path: ${RAIZ}/data/bronze
            type: Directory
YAML
}

aplicar() {
  kubectl kustomize --load-restrictor LoadRestrictionsNone "k8s/overlays/${OVERLAY}" | kubectl apply -f -
}

case "${1:-}" in
  up)
    requisitos
    echo "==> Construyendo imágenes propias"
    docker build -q -f etl/Dockerfile -t solarbi-etl:1.0 .
    docker build -q -t solarbi-simulador:1.0 simulador
    echo "==> Aplicando manifiestos (overlay ${OVERLAY})"
    parche_ruta
    kubectl delete job etl -n "$NS" --ignore-not-found >/dev/null
    aplicar
    echo "==> Esperando PostgreSQL";  kubectl rollout status statefulset/postgres -n "$NS" --timeout=180s
    echo "==> Esperando el ETL";       kubectl wait --for=condition=complete job/etl -n "$NS" --timeout=900s
    echo "==> Esperando Grafana";     kubectl rollout status deployment/grafana -n "$NS" --timeout=180s
    kubectl get all,pvc,configmap,secret -n "$NS"
    echo; echo "Grafana:    http://localhost:30300"
    echo "PostgreSQL: localhost:30432 (DBeaver / Power BI)"
    ;;
  down)
    kubectl delete namespace "$NS" --ignore-not-found
    ;;
  estado)
    kubectl get all,pvc,configmap,secret -n "$NS"
    ;;
  falla)
    MODO="${2:-ninguno}"; INV="${3:-1}"
    kubectl patch configmap solarbi-config -n "$NS" --type merge \
      -p "{\"data\":{\"MODO_FALLA\":\"${MODO}\",\"INVERSOR_FALLA\":\"${INV}\"}}"
    echo "Modo de falla = ${MODO} (inversor ${INV}). La próxima ejecución del CronJob lo aplica (≤ 1 min)."
    ;;
  etl)
    kubectl delete job etl -n "$NS" --ignore-not-found
    parche_ruta; aplicar
    kubectl wait --for=condition=complete job/etl -n "$NS" --timeout=900s
    kubectl logs job/etl -n "$NS" | tail -25
    ;;
  *)
    sed -n '2,8p' "$0"; exit 1 ;;
esac
