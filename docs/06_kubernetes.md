# 6. Despliegue: Docker + Kubernetes

## 6.1 Contenedores (K.1)

| Imagen | Base | Tamaño aprox. | Justificación |
|---|---|---|---|
| `solarbi-etl:1.0` (propia, `etl/Dockerfile`) | `python:3.12-slim` | ~300 MB (130 MB base + pandas/numpy) | `slim` evita compiladores y documentación de `python:3.12` (~1 GB). `alpine` usa musl: pandas y numpy no tienen ruedas precompiladas y habría que compilarlos (imagen más grande y lenta de construir) |
| `solarbi-simulador:1.0` (propia, `simulador/Dockerfile`) | `python:3.12-slim` | ~150 MB | Solo necesita psycopg2 |
| PostgreSQL | `postgres:16.4-alpine` (oficial, versión fija) | ~240 MB | Alpine es suficiente: no se compila nada |
| Grafana | `grafana/grafana-oss:11.2.0` (oficial, versión fija) | ~450 MB | Versión con provisioning de alertas estable |

Las dos imágenes propias corren con un **usuario sin privilegios** (uid 10001) y no contienen datos ni contraseñas. `docker-compose.yml` sirve para desarrollo local antes del clúster.

## 6.2 Clúster local (K.2)

**Distribución: Kubernetes de Docker Desktop** (modo *kubeadm*, un nodo).

| Opción | Por qué sí / no |
|---|---|
| **Docker Desktop (elegida)** | Ya lo tenemos instalado (Mac y Windows); se activa con una casilla; los NodePort quedan en `localhost` (Power BI y DBeaver se conectan sin túneles); **comparte el almacén de imágenes con Docker** |
| minikube | Necesita su propia VM y `minikube image load` para cada imagen |
| kind / k3d | Muy livianos, pero las imágenes se cargan con `kind load` / `k3d image import` y hay que mapear puertos al crear el clúster |

**Cómo llegan nuestras imágenes al clúster:** el script construye las imágenes con `docker build` en el mismo motor que usa Kubernetes de Docker Desktop. Los manifiestos usan `imagePullPolicy: IfNotPresent`, así que el nodo encuentra la imagen localmente y **no se necesita un registro** (Docker Hub). En Docker Desktop hay que elegir el tipo de clúster *kubeadm*; con el tipo *kind* habría que cargar las imágenes con `kind load docker-image`.

## 6.3 Objeto de Kubernetes para cada necesidad (K.3)

| Necesidad | Objeto elegido | Por qué (frente a las alternativas) |
|---|---|---|
| Aislar el proyecto | **Namespace** `solarbi` | Agrupa todo; `kubectl delete namespace solarbi` lo elimina de una vez. Alternativa: etiquetas, que no aíslan nombres ni permiten borrar en bloque |
| Base que no pierda datos | **StatefulSet** `postgres` + **PersistentVolumeClaim** (`volumeClaimTemplates`, 5 GiB) | El pod tiene identidad estable (`postgres-0`) y siempre vuelve a montar **su** volumen. Un Deployment con PVC también funcionaría con 1 réplica, pero no garantiza identidad ni orden, y con `emptyDir` los datos se pierden al borrar el pod |
| Grafana siempre disponible | **Deployment** `grafana` + **ConfigMaps** de provisioning | Grafana no guarda estado propio: todo llega por ConfigMaps. Si el pod muere, el Deployment crea otro igual. No necesita StatefulSet |
| Credenciales fuera del código | **Secret** `solarbi-secret` | Lo genera Kustomize desde el `.env` local (no versionado). Las contraseñas llegan como variables de entorno con `secretKeyRef`. En el repositorio solo está `.env.example` |
| Configuración separada del código | **ConfigMap** `solarbi-config` | Umbrales, intervalos, modo de falla y nombres de host como variables de entorno (`envFrom`). Cambiarlos no requiere reconstruir imágenes |
| Comunicación entre servicios | **Service** `postgres` (headless, DNS) | El ETL, el simulador y Grafana usan el nombre `postgres`; el DNS del clúster lo resuelve. Las IP de los pods cambian en cada reinicio |
| Carga histórica | **Job** `etl` | Corre una vez, termina (`Complete`) y deja evidencia: logs, estado del Job y tablas `audit.*`. Un Deployment lo reiniciaría sin fin |
| Datos nuevos cada cierto tiempo | **CronJob** `simulador` (`* * * * *`) | Kubernetes maneja el reloj, impide ejecuciones simultáneas (`concurrencyPolicy: Forbid`) y guarda el historial. Alternativa: Deployment con un bucle `sleep`, que esconde el reloj dentro del código |
| Saber si un servicio está sano | **Sondas** `readinessProbe` y `livenessProbe` | PostgreSQL: `pg_isready`. Grafana: `GET /api/health`. *Readiness* decide si el Service le envía tráfico; *liveness* reinicia el contenedor si se cuelga |
| No agotar el equipo | `resources.requests` y `limits` en **cada** contenedor | Por ejemplo PostgreSQL 250m/512Mi → 1 CPU/1Gi; ETL 500m/1.5Gi → 2 CPU/3Gi |
| Acceso desde el anfitrión | **Service NodePort** | `postgres-externo` 30432 (DBeaver, Power BI) y `grafana` 30300 (navegador). En Docker Desktop los NodePort se publican en `localhost`. Alternativa: `kubectl port-forward`, que hay que dejar abierto en una terminal |

Además: la fuente Bronze llega al Job por un volumen **hostPath de solo lectura** (la ruta depende del equipo y la genera el script). En producción sería un volumen de red o almacenamiento de objetos.

## 6.4 Un comando para levantar y otro para eliminar (K.4)

```bash
cp .env.example .env                 # y cambiar contraseñas (una sola vez)
./scripts/solarbi.sh up              # Windows: .\scripts\solarbi.ps1 up
./scripts/solarbi.sh down            # elimina el namespace completo
```

`up` construye las dos imágenes, genera el parche con la ruta de los datos, aplica los manifiestos con **Kustomize** (`kubectl kustomize … | kubectl apply -f -`) y espera a que PostgreSQL esté listo, el ETL termine y Grafana responda.

## 6.5 Resiliencia (demostración en vivo)

```bash
kubectl -n solarbi delete pod postgres-0          # el StatefulSet lo recrea…
kubectl -n solarbi get pods -w                    # …postgres-0 vuelve a Running
# en DBeaver: SELECT COUNT(*) FROM gold.fact_energia_hora;   → sigue en 14 077 (los datos están en el PVC)

kubectl -n solarbi delete pod -l app=grafana      # el Deployment crea otro pod
# http://localhost:30300 → el tablero y las 2 alertas vuelven solos (provisioning)
```

## 6.6 Cambios en vivo sin reconstruir imágenes

| Pedido | Comando |
|---|---|
| Cambiar un umbral de alerta | `kubectl -n solarbi patch configmap solarbi-config --type merge -p '{"data":{"UMBRAL_SOC_ALERTA":"30"}}'` y `kubectl -n solarbi rollout restart deployment/grafana` |
| Forzar una falla para ver la alerta | `./scripts/solarbi.sh falla corte_red 1` (o `soc_bajo`); para volver: `falla ninguno` |
| Volver a correr el ETL | `./scripts/solarbi.sh etl` (idempotente) |
| Ver la evidencia | `kubectl -n solarbi get all,pvc,configmap,secret` · `kubectl -n solarbi describe statefulset postgres` · `kubectl -n solarbi logs job/etl` |

## 6.7 Bonificación

- **Kustomize con dos ambientes:** `k8s/overlays/dev` y `k8s/overlays/demo` (Grafana con 2 réplicas y 6 h de relleno inicial): `./scripts/solarbi.sh up demo`.
- **Escalar una réplica:** `kubectl -n solarbi scale deployment grafana --replicas=2` funciona porque Grafana no guarda estado propio. **PostgreSQL no se escala igual:** cada réplica de un StatefulSet tendría su **propio** volumen y su propia copia de los datos, sin sincronización; escalar una base requiere replicación (un primario que escribe y réplicas de solo lectura, p. ej. con un operador como CloudNativePG), no solo subir `replicas`.
