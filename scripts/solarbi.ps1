# SolarBI · despliegue en Kubernetes (Docker Desktop) desde Windows PowerShell.
#   .\scripts\solarbi.ps1 up        construye imágenes y levanta todo
#   .\scripts\solarbi.ps1 down      elimina todo
#   .\scripts\solarbi.ps1 estado
#   .\scripts\solarbi.ps1 falla corte_red 1
#   .\scripts\solarbi.ps1 etl
param([string]$Accion = "", [string]$Arg1 = "", [string]$Arg2 = "1")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Raiz = (Get-Location).Path
$NS = "solarbi"
$Overlay = if ($Accion -eq "up" -and $Arg1) { $Arg1 } else { "dev" }

function Parche-Ruta {
  # Docker Desktop en Windows ve el disco C: como /run/desktop/mnt/host/c
  $unidad = $Raiz.Substring(0,1).ToLower()
  $resto = $Raiz.Substring(2) -replace '\\','/'
  $ruta = "/run/desktop/mnt/host/$unidad$resto/data/bronze"
  @"
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
            path: $ruta
            type: Directory
"@ | Set-Content -Encoding utf8 "k8s/overlays/dev/ruta-datos.local.yaml"
}
function Aplicar { kubectl kustomize --load-restrictor LoadRestrictionsNone "k8s/overlays/$Overlay" | kubectl apply -f - }

switch ($Accion) {
  "up" {
    if (-not (Test-Path .env)) { throw "Falta .env: copie .env.example a .env" }
    if (-not (Test-Path data/bronze/opencem-v1.0.0.sqlite)) { throw "Falta data/bronze/opencem-v1.0.0.sqlite" }
    kubectl config use-context docker-desktop | Out-Null
    docker build -q -f etl/Dockerfile -t solarbi-etl:1.0 .
    docker build -q -t solarbi-simulador:1.0 simulador
    Parche-Ruta
    kubectl delete job etl -n $NS --ignore-not-found | Out-Null
    Aplicar
    kubectl rollout status statefulset/postgres -n $NS --timeout=180s
    kubectl wait --for=condition=complete job/etl -n $NS --timeout=900s
    kubectl rollout status deployment/grafana -n $NS --timeout=180s
    kubectl get all,pvc,configmap,secret -n $NS
    Write-Host "`nGrafana:    http://localhost:30300`nPostgreSQL: localhost:30432"
  }
  "down"   { kubectl delete namespace $NS --ignore-not-found }
  "estado" { kubectl get all,pvc,configmap,secret -n $NS }
  "falla"  {
    $modo = if ($Arg1) { $Arg1 } else { "ninguno" }
    kubectl patch configmap solarbi-config -n $NS --type merge -p "{`"data`":{`"MODO_FALLA`":`"$modo`",`"INVERSOR_FALLA`":`"$Arg2`"}}"
  }
  "etl" {
    kubectl delete job etl -n $NS --ignore-not-found
    Parche-Ruta; Aplicar
    kubectl wait --for=condition=complete job/etl -n $NS --timeout=900s
    kubectl logs job/etl -n $NS
  }
  default { Get-Content $PSCommandPath -TotalCount 7 }
}
