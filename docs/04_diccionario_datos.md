# 4. Diccionario de datos y linaje

> Generado con `python scripts/generar_diccionario.py`. Tipos, llaves y nulabilidad salen del catálogo de PostgreSQL; el origen, la regla y la unidad, del linaje declarado en el script.

## Unidades y evidencia

| Variable | Unidad | Evidencia |
|---|---|---|
| `pv1power`, `outw_a`, `linepowerw_a` | W | `documentation/column_dictionary.csv` de los autores; identidad P = V·I (R04); la energía integrada coincide con el contador `usedenergytoday` (kWh) del inversor con −2,5 % |
| `battvolt` · `battcurr` | V · A | Diccionario de los autores; mediana 53,5 V (banco de litio de 48 V nominal) |
| `battcurr` signo | + descarga, − carga | Diccionario: «positive denotes discharge» |
| `battsoc` | % | Rango 6–100; coincide con los umbrales `batsoclowalarm` = 15 y `batstopsoc` = 5 |
| `linevolta` | V | Distribución bimodal: 0 V (sin red) o 230 ± 10 V |
| `read_ts` | s Unix UTC | Diccionario: «fractional Unix timestamp in UTC»; la planta está en Shenzhen (UTC+8) |
| contadores `*today` | kWh | Diccionario; resolución 0,1 kWh |

## `silver.lectura_minuto`

Lecturas eléctricas validadas y agregadas por minuto. **Grano:** inversor × minuto UTC.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `inversor` | smallint | PK | no | analog_measurements.inverter | Directo | — |
| `ts_minuto` | timestamp with time zone | PK | no | analog_measurements.read_ts | Unix UTC → timestamptz, truncado al minuto | UTC |
| `n_lecturas` | smallint |  | no | analog_measurements.* | Conteo de lecturas tras R01–R02 | lecturas |
| `n_validas` | smallint |  | no | analog_measurements.* | Lecturas con solar, carga y red no nulos tras R03–R09 | lecturas |
| `pv_w` | numeric |  | sí | analog_measurements.pv1power | Media de lecturas válidas (R04, R09) | W |
| `carga_w` | numeric |  | sí | analog_measurements.outw_a | Media de lecturas válidas (R05, R09) | W |
| `red_w` | numeric |  | sí | analog_measurements.linepowerw_a | Media; negativos a 0 (R06) | W |
| `bat_w` | numeric |  | sí | analog_measurements.battvolt × analog_measurements.battcurr | V·I; + descarga, − carga (R03) | W |
| `soc_pct` | numeric |  | sí | analog_measurements.battsoc | Media del minuto | % |
| `bat_v` | numeric |  | sí | analog_measurements.battvolt | Media del minuto | V |
| `red_v_min` | numeric |  | sí | analog_measurements.linevolta | Mínimo del minuto (detecta cortes) | V |
| `salida_v` | numeric |  | sí | analog_measurements.outvolta | Media del minuto | V |
| `alarma_activa` | boolean |  | no | status.sysalarmflag | TRUE si la bandera es distinta de [0,…,0] | — |
| `seg_cubiertos` | numeric |  | no | analog_measurements.read_ts | Suma de intervalos ≤ 10 min que cierran en el minuto | s |
| `e_solar_wh` | numeric |  | no | analog_measurements.pv1power | Trapecio por intervalo (≤ 10 min) | Wh |
| `e_carga_wh` | numeric |  | no | analog_measurements.outw_a | Trapecio por intervalo | Wh |
| `e_red_wh` | numeric |  | no | analog_measurements.linepowerw_a | Trapecio por intervalo | Wh |
| `e_bat_carga_wh` | numeric |  | no | battvolt × battcurr | Trapecio, parte negativa | Wh |
| `e_bat_descarga_wh` | numeric |  | no | battvolt × battcurr | Trapecio, parte positiva | Wh |

## `silver.contexto`

Registros de contexto con el JSON sanitizado. **Grano:** un registro de context.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `id_contexto` | integer | PK | no | context.id | Directo | — |
| `registrado` | timestamp with time zone |  | sí | context.recorded | Unix → timestamptz | UTC |
| `inicio` | timestamp with time zone |  | sí | context.start | Unix → timestamptz | UTC |
| `fin` | timestamp with time zone |  | sí | context.end | Unix → timestamptz (R16) | UTC |
| `fuente` | character varying |  | no | context.value → source | JSON → texto | — |
| `tipo_contexto` | character varying |  | no | context.value → context_type | Si falta, se deriva (R15) | — |
| `dispositivo` | character varying |  | no | context.value → device | Si falta: installation | — |
| `inversor` | smallint |  | sí | context.value → inverter | Directo | — |
| `valor` | jsonb |  | no | context.value | JSONB sin comandos, rutas ni metadatos (R14) | — |

## `silver.contador_diario`

Contadores diarios del propio inversor (fuente independiente). **Grano:** inversor × día local.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `inversor` | smallint | PK | no | — | — | — |
| `fecha_local` | date | PK | no | — | — | — |
| `pv_kwh` | numeric |  | sí | statistics.pvgeneratenergytoday | Máximo del día local (R17) | kWh |
| `carga_kwh` | numeric |  | sí | statistics.usedenergytoday | Máximo del día local | kWh |
| `carga_desde_red_kwh` | numeric |  | sí | statistics.loadconsumlinetday | Máximo del día local | kWh |
| `red_a_bateria_kwh` | numeric |  | sí | statistics.linechgenergytday | Máximo del día local | kWh |
| `bat_carga_kwh` | numeric |  | sí | statistics.batchgenergytoday | Máximo del día local | kWh |
| `bat_descarga_kwh` | numeric |  | sí | statistics.batdischgenergytoday | Máximo del día local | kWh |

## `gold.dim_fecha`

Calendario local (Asia/Shanghai). Dimensión conformada. **Grano:** un día.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `sk_fecha` | integer | PK | no | Generada | Llave sustituta | — |
| `fecha` | date | UQ | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `anio` | smallint |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `trimestre` | smallint |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `mes` | smallint |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `mes_nombre` | character varying |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `anio_mes` | character |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `semana_iso` | smallint |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `dia_mes` | smallint |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `dia_semana_num` | smallint |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `dia_semana` | character varying |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `es_fin_semana` | boolean |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `estacion` | character varying |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `temporada_lluvia` | boolean |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |
| `con_telemetria` | boolean |  | no | Generada por el ETL | Rango = telemetría ∪ contexto | — |

## `gold.dim_hora`

Hora del día con franjas. DIMENSIÓN CONSTRUIDA POR EL EQUIPO. **Grano:** una hora (0–23).

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `sk_hora` | smallint | PK | no | Generada | Llave sustituta | — |
| `hora` | smallint |  | no | Generada por el ETL | Franja, periodo solar y franja tarifaria EPM | — |
| `etiqueta` | character |  | no | Generada por el ETL | Franja, periodo solar y franja tarifaria EPM | — |
| `franja` | character varying |  | no | Generada por el ETL | Franja, periodo solar y franja tarifaria EPM | — |
| `periodo_solar` | character varying |  | no | Generada por el ETL | Franja, periodo solar y franja tarifaria EPM | — |
| `franja_tarifaria` | character varying |  | no | Generada por el ETL | Franja, periodo solar y franja tarifaria EPM | — |

## `gold.dim_inversor`

Inversor con historia de configuración (SCD tipo 2). **Grano:** una versión de configuración.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `sk_inversor` | integer | PK | no | Generada | Llave sustituta | — |
| `cod_inversor` | smallint |  | no | settings.inverter | Llave natural | — |
| `nombre` | character varying |  | no | — | — | — |
| `subsistema` | character varying |  | no | — | — | — |
| `bateria_ah` | numeric |  | sí | settings.battpackrateah | Versión ≥ 24 h (R18) | Ah |
| `bateria_kwh` | numeric |  | sí | settings.battpackrateah | Ah × 51,2 V / 1000; 0 Ah → 200 Ah supuesto (R19) | kWh |
| `capacidad_supuesta` | boolean |  | no | — | — | — |
| `max_red_w` | integer |  | sí | settings.maxlinepower | Directo | W |
| `prioridad_carga` | character varying |  | sí | settings.chgpriority | Código → texto | — |
| `soc_alarma_pct` | smallint |  | sí | settings.batsoclowalarm | Directo | % |
| `valido_desde` | timestamp with time zone |  | no | settings.read_ts | Inicio de la versión | UTC |
| `valido_hasta` | timestamp with time zone |  | sí | settings.read_ts | Inicio de la versión siguiente | UTC |
| `es_actual` | boolean |  | no | — | TRUE en la última versión | — |

## `gold.dim_tipo_evento`

Catálogo de eventos operativos (categoría › tipo). **Grano:** un tipo de evento.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `sk_tipo_evento` | smallint | PK | no | Generada | Llave sustituta | — |
| `cod_evento` | character varying | UQ | no | Definido por el equipo | Ver regla de detección | — |
| `nombre` | character varying |  | no | Definido por el equipo | Ver regla de detección | — |
| `categoria` | character varying |  | no | Definido por el equipo | Ver regla de detección | — |
| `severidad` | character varying |  | no | Definido por el equipo | Ver regla de detección | — |
| `origen` | character varying |  | no | Definido por el equipo | Ver regla de detección | — |
| `regla` | text |  | no | Definido por el equipo | Ver regla de detección | — |

## `gold.dim_tipo_contexto`

Tipos de contexto (categoría › tipo). **Grano:** un tipo de contexto.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `sk_tipo_contexto` | smallint | PK | no | Generada | Llave sustituta | — |
| `tipo_contexto` | character varying | UQ | no | context.value → context_type / source | Categorizado por el ETL | — |
| `fuente` | character varying |  | no | context.value → context_type / source | Categorizado por el ETL | — |
| `categoria` | character varying |  | no | context.value → context_type / source | Categorizado por el ETL | — |
| `es_carga` | boolean |  | no | context.value → context_type / source | Categorizado por el ETL | — |

## `gold.dim_dispositivo`

Dispositivo que originó el contexto. **Grano:** un dispositivo.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `sk_dispositivo` | smallint | PK | no | Generada | Llave sustituta | — |
| `dispositivo` | character varying | UQ | no | context.value → device | Directo | — |
| `tipo` | character varying |  | no | context.value → device | Directo | — |

## `gold.fact_energia_hora`

Balance energético. **Grano:** inversor × hora local.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `sk_fecha` | integer | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_hora` | smallint | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_inversor` | integer | PK,FK | no | Generada | Búsqueda en la dimensión | — |
| `ts_hora_utc` | timestamp with time zone | PK | no | — | — | — |
| `e_solar_kwh` | numeric |  | no | silver.lectura_minuto.e_solar_wh | Σ / 1000 | kWh |
| `e_carga_kwh` | numeric |  | no | silver.lectura_minuto.e_carga_wh | Σ / 1000 | kWh |
| `e_red_kwh` | numeric |  | no | silver.lectura_minuto.e_red_wh | Σ / 1000 | kWh |
| `e_bat_carga_kwh` | numeric |  | no | silver.lectura_minuto.e_bat_carga_wh | Σ / 1000 | kWh |
| `e_bat_descarga_kwh` | numeric |  | no | silver.lectura_minuto.e_bat_descarga_wh | Σ / 1000 | kWh |
| `soc_prom_pct` | numeric |  | sí | silver.lectura_minuto.soc_pct | Promedio | % |
| `soc_min_pct` | numeric |  | sí | silver.lectura_minuto.soc_pct | Mínimo | % |
| `minutos_con_dato` | smallint |  | no | silver.lectura_minuto.seg_cubiertos | Σ / 60, tope 60 | min |
| `minutos_red_ok` | smallint |  | no | silver.lectura_minuto.red_v_min | Minutos con V ≥ 180 | min |
| `lecturas_total` | integer |  | no | silver.lectura_minuto.n_lecturas | Σ | lecturas |
| `lecturas_validas` | integer |  | no | silver.lectura_minuto.n_validas | Σ | lecturas |

## `gold.fact_evento`

Eventos operativos (intervalos). **Grano:** un evento de un tipo en un inversor.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `id_evento` | bigint | PK | no | — | — | — |
| `sk_tipo_evento` | smallint | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_inversor` | integer | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_fecha` | integer | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_hora` | smallint | FK | no | Generada | Búsqueda en la dimensión | — |
| `inicio_utc` | timestamp with time zone |  | no | silver.lectura_minuto / context | Minutos consecutivos que cumplen la regla (R11–R13) | UTC |
| `fin_utc` | timestamp with time zone |  | no | silver.lectura_minuto / context | Último minuto + 1 | UTC |
| `duracion_min` | numeric |  | no | — | fin − inicio | min |
| `valor_extremo` | numeric |  | sí | silver.lectura_minuto.soc_pct | SoC mínimo (solo SOC_BAJO) | % |
| `descripcion` | character varying |  | sí | — | — | — |

## `gold.fact_actividad`

Actividad y contexto (qué cargas explican el consumo). **Grano:** un registro de contexto.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `id_contexto` | integer | PK | no | context.id | Dimensión degenerada | — |
| `sk_tipo_contexto` | smallint | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_dispositivo` | smallint | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_inversor` | integer | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_fecha` | integer | FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_hora` | smallint | FK | no | Generada | Búsqueda en la dimensión | — |
| `inicio_utc` | timestamp with time zone |  | sí | — | — | — |
| `fin_utc` | timestamp with time zone |  | sí | — | — | — |
| `duracion_min` | numeric |  | sí | context.end − context.start | En minutos | min |
| `nucleos_cpu` | smallint |  | sí | context.value → cpu_cores_active | Texto → entero | núcleos |
| `es_gpu` | boolean |  | no | context.value → task_type | Contiene 'GPU' | — |
| `carga_estimada` | character varying |  | sí | context.value → llm_estimated_task_effort | Directo | — |

## `gold.fact_contador_diario`

Contadores diarios del inversor. **Grano:** inversor × día local.

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `sk_fecha` | integer | PK,FK | no | Generada | Búsqueda en la dimensión | — |
| `sk_inversor` | integer | PK,FK | no | Generada | Búsqueda en la dimensión | — |
| `pv_kwh` | numeric |  | sí | silver.contador_diario | Directo | kWh |
| `carga_kwh` | numeric |  | sí | silver.contador_diario | Directo | kWh |
| `carga_desde_red_kwh` | numeric |  | sí | silver.contador_diario | Directo | kWh |
| `bat_carga_kwh` | numeric |  | sí | silver.contador_diario | Directo | kWh |
| `bat_descarga_kwh` | numeric |  | sí | silver.contador_diario | Directo | kWh |

## `gold.fact_lectura_rt`

Monitoreo casi en tiempo real. **Grano:** inversor × minuto (solo inserción).

| Columna | Tipo | Llave | Nulo | Origen (linaje) | Regla | Unidad |
|---|---|---|---|---|---|---|
| `cod_inversor` | smallint | UQ | no | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
| `ts` | timestamp with time zone | UQ | no | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
| `pv_w` | numeric |  | sí | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
| `carga_w` | numeric |  | sí | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
| `red_w` | numeric |  | sí | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
| `bat_w` | numeric |  | sí | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
| `soc_pct` | numeric |  | sí | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
| `red_v` | numeric |  | sí | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
| `origen` | character varying |  | no | silver.lectura_minuto desplazado 365 días | Lo escribe el simulador (CronJob) | W, %, V |
