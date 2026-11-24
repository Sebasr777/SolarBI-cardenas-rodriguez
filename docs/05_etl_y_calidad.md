# 5. ETL y calidad de datos

## 5.1 Herramienta

**Python 3.12 + pandas + psycopg2**, empaquetado en la imagen `solarbi-etl:1.0` y ejecutado como **Job** de Kubernetes.

| Alternativa | Por qué no |
|---|---|
| Power Query (Power BI) | Los datos limpios quedarían dentro del archivo de Power BI: Grafana no los vería, no corre en un contenedor y no se versiona con diferencias legibles |
| Solo SQL en PostgreSQL | PostgreSQL no lee un `.sqlite` sin extensiones adicionales; la detección de intervalos y el JSON son más claros en Python |
| Python (elegido) | Lee SQLite con la biblioteca estándar, cada regla queda como función revisable en Git, corre igual en cualquier clúster y escribe su bitácora en la misma base |

## 5.2 Flujo y capas

```
Bronze  opencem-v1.0.0.sqlite (solo lectura, SHA-256 verificado, modo immutable)
  │  extract.py   lee solo las columnas necesarias de 5 tablas
  ▼
Silver  silver.lectura_minuto · silver.contexto (JSONB) · silver.contador_diario · silver.config_inversor
  │  transform.py reglas R01–R19, energía por trapecio, eventos, SCD 2
  ▼
Gold    6 dimensiones + 5 hechos (gold.*)            audit.etl_corrida · regla_calidad · conciliacion
```

Todo el proceso de carga corre en **una sola transacción**: si algo falla, PostgreSQL deshace todo y la corrida queda registrada con estado `error` en `audit.etl_corrida`.

## 5.3 Frecuencia de agregación de Silver: 1 minuto

| Opción | Filas | Qué se gana | Qué se pierde |
|---|---:|---|---|
| Lectura cruda (~12,6 s) | 2,9 M | Todo el detalle | Volumen 4×, cadencia irregular (12 s, 60 s, 120 s según el periodo), difícil de comparar |
| **1 minuto (elegida)** | **727 mil** | Uniformiza la cadencia; conserva eventos cortos (un corte de red de 2 min sigue visible); es la misma resolución que usa el simulador y Grafana | Picos de menos de 1 min (arranque de un compresor) quedan promediados |
| 15 minutos | ~48 mil | Volumen mínimo; estándar de facturación | Un corte de 5 min o una caída de SoC desaparecen dentro del promedio; no sirve para detectar eventos |

La **energía no se calcula promediando potencias**: se integra lectura a lectura (regla del trapecio) y se acumula en el minuto. Así la energía es exacta aunque la cadencia cambie. Intervalos de más de 10 min son **huecos** y no se integran (no se inventa energía).

## 5.4 Reglas de limpieza y su efecto

| Regla | Problema | Tratamiento | Antes | Afectadas | Después |
|---|---|---|---:|---:|---:|
| R01 | Lectura sin ninguna medición | Descartar | 2 989 759 | 55 658 | 2 934 101 |
| R02 | Lectura repetida (< 1 s) | Descartar | 2 934 101 | 20 379 | 2 913 722 |
| R03 | Batería en 0 V con SoC > 0 % | Anular campos de batería | 2 913 722 | 5 | 2 913 722 |
| R04 | P_FV ≠ V·I (> 20 % o > 50 W) | Anular potencia FV | 2 913 722 | 2 230 | 2 913 722 |
| R05 | W de salida > VA + 50 | Anular potencia de carga | 2 913 722 | 3 799 | 2 913 722 |
| R06 | Potencia de red negativa | Corregir a 0 | 2 913 722 | 9 | 2 913 722 |
| R07 | Columna `gridpowerw_a` ambigua | Excluir columna | 2 913 722 | 2 910 423 | 2 913 722 |
| R08 | Temperatura centinela 120 °C | Excluir del análisis térmico | 2 913 722 | 2 911 323 | 2 913 722 |
| R09 | Fuera de rango físico | Anular campo | 2 913 722 | 0 | 2 913 722 |
| R10 | Hueco > 10 min | Convertir en evento | 2 913 722 | 149 | 2 913 722 |
| R11 | Red < 180 V | **Evento** (no es error) | 726 876 min | 110 199 min → 20 eventos | — |
| R12 | SoC ≤ 15 % | **Evento** (no es error) | 726 876 min | 7 050 min → 26 eventos | — |
| R13 | Salida AC < 100 V | **Evento** (no es error) | 726 876 min | 29 712 min → 62 eventos | — |
| R14 | JSON con comandos, rutas y archivos | Sanitizar (Ley 1581) | 25 178 | 12 183 | 25 178 |
| R15 | JSON sin `context_type` | Derivar el tipo | 25 178 | 61 | 25 178 |
| R16 | Contexto con fin < inicio | Corregir | 25 178 | 0 | 25 178 |
| R17 | Contador diario | Máximo del día local; omitir vacíos | 542 | 44 | 498 |
| R18 | Configuración que parpadea | Versiones < 24 h = ruido | 109 339 | 109 334 | 5 |
| R19 | Inversor sin capacidad configurada | Suponer 200 Ah y marcar | 5 | 3 | 5 |

Lectura **válida** = tiene los tres flujos del balance (solar, carga y red) después de R03–R09: **99,53 %**.

## 5.5 Dato inválido frente a evento operativo

| Situación | ¿Inválido o evento? | Criterio |
|---|---|---|
| Red en 0 V durante horas mientras la batería se descarga | **Evento** (corte de red) | Coherente con las demás variables y con las notas del personal (tifón) |
| SoC en 8 % con tensión de batería cayendo | **Evento** (batería baja) | La física cuadra: menos carga, menos tensión |
| Batería en 0 V y SoC en 80 % al mismo tiempo | **Inválido** | Imposible: un banco de litio no reporta 80 % sin tensión |
| P_FV = 1 500 W con 0 V en el panel | **Inválido** | Viola P = V·I |
| Sin lecturas durante 3 días | Ni lo uno ni lo otro: **hueco** | Se registra como evento de categoría Datos y baja la disponibilidad |

## 5.6 Conciliación

`SELECT * FROM audit.conciliacion;` (última corrida):

| Métrica | Fuente | Cargado | Diferencia |
|---|---:|---:|---:|
| Lecturas Bronze vs. Silver + descartadas | 2 989 759 | 2 989 759 | **0** |
| Lecturas válidas Silver vs. Gold | 2 899 937 | 2 899 937 | **0** |
| Energía solar: integración sobre Bronze vs. Gold | 2 333,203 kWh | 2 333,202 kWh | **0,000 %** (redondeo) |
| Energía a la carga: Bronze vs. Gold | 5 973,210 kWh | 5 973,209 kWh | **0,000 %** |
| Energía de la red: Bronze vs. Gold | 4 730,270 kWh | 4 730,271 kWh | **0,000 %** |
| Contexto JSON Bronze vs. Silver | 25 178 | 25 178 | **0** |
| Solar Gold vs. **contador del inversor** · muestreo rápido (286 días) | 972,2 kWh | 897,7 kWh | −7,7 % |
| Carga Gold vs. contador · muestreo rápido | 2 454,1 kWh | 2 392,8 kWh | **−2,5 %** |
| Solar Gold vs. contador · muestreo lento 1–2 min (164 días) | 1 010,7 kWh | 780,9 kWh | −22,7 % |
| Carga Gold vs. contador · muestreo lento | 2 358,9 kWh | 1 817,7 kWh | −22,9 % |

**Explicación.** Las seis primeras filas prueban que el modelo no pierde ni duplica nada. Las cuatro últimas comparan con una **fuente independiente**: el contador de energía del propio inversor. Con muestreo rápido (~12 s) la diferencia es pequeña (−2,5 % en la carga valida la unidad W y el signo). Con muestreo lento (1–2 min) la integración se queda corta ≈ 23 % en todas las variables por igual: las variaciones entre lecturas espaciadas se pierden. Es un **hallazgo de calidad**: para totales diarios de esos días el contador del inversor es más confiable, y la recomendación es fijar la cadencia del registrador.

## 5.7 Idempotencia

El ETL borra y recrea `silver` y `gold` dentro de la transacción y vuelve a cargar todo desde Bronze, que no cambia. Al final calcula una **huella MD5** de los totales de Gold. Dos corridas seguidas producen exactamente la misma huella:

```sql
SELECT id_corrida, estado, filas_gold, huella_resultado FROM audit.etl_corrida ORDER BY 1;
--  6 | ok | 40633 | bcb1ad2a34ed2606147929c4c4f354f8
--  7 | ok | 40633 | bcb1ad2a34ed2606147929c4c4f354f8   ← mismo resultado
```

`audit` no se borra: guarda la historia de todas las corridas.
