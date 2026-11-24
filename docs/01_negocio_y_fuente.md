# 1. Negocio y diagnóstico de la fuente

## 1.1 Usuarios y preguntas de negocio

| Usuario | Preguntas que necesita responder | Tablero | Frecuencia |
|---|---|---|---|
| Dirección de infraestructura | ¿Cuánta energía aporta el sol y cuánta se compra a la red? ¿Conviene invertir en más paneles o en más batería? ¿Cuánto ahorramos en pesos? | Power BI | Mensual |
| Coordinador de energía | ¿A qué horas dependemos de la red? ¿Cómo trabaja la batería (ciclos, SoC mínimo)? ¿Qué inversor rinde mejor? | Power BI | Semanal |
| Equipo de mantenimiento | ¿Cómo está cada inversor ahora? ¿Se cayó la red? ¿La batería está por agotarse? | Grafana + alertas | Continua (30 s) |
| Usuarios de las estaciones de cómputo (GPU) | ¿Cuánto consumo agregan los entrenamientos? ¿Conviene programarlos en horas de sol? | Power BI | Mensual |
| Analistas de datos | ¿Qué tan confiables son las cifras (disponibilidad, % de datos válidos)? | Power BI / DBeaver | Por corrida |

**Preguntas que guían la solución**

1. ¿De dónde viene la energía que consumen los equipos (sol, batería o red) y a dónde va?
2. ¿Qué parte del consumo cubre la microrred por sí misma (autosuficiencia) y cuánto cuesta lo que se compra a la red?
3. ¿A qué horas y en qué meses depende más de la red?
4. ¿Cómo trabaja la batería y con qué frecuencia llega a niveles críticos?
5. ¿Qué eventos operativos ocurren (cortes de red, batería baja, inversor sin salida) y cuánto duran?
6. ¿Qué cargas de trabajo (entrenamientos en GPU, compilaciones) explican el consumo?
7. En vivo: ¿algún inversor está sin red o con la batería baja ahora mismo?

## 1.2 Verificación e inventario de la fuente (capa Bronze)

**Integridad.** Se verificó el SHA-256 de cada archivo descargado contra `opencem-v1.0.0-SHA256SUMS.txt`:

| Archivo | SHA-256 | Resultado |
|---|---|---|
| `opencem-v1.0.0.sqlite.zst` (302,1 MB) | `8e38f982…7b27517` | Coincide |
| `opencem-v1.0.0-support.zip` (10,0 MB) | `5debdbeb…2f460439` | Coincide |
| `opencem-v1.0.0.sqlite` descomprimido (4,44 GB) | `5fe1f213…2c2d9fbb` | Coincide con `validation_results.json` de los autores; el ETL lo vuelve a verificar en cada corrida |

**Descompresión.** `zstd -d opencem-v1.0.0.sqlite.zst -o data/bronze/opencem-v1.0.0.sqlite` (zstd 1.5). En equipos sin `zstd`, el mismo resultado se obtiene con Python: `pip install zstandard` y `zstandard.ZstdDecompressor().copy_stream(...)`.

**Inventario** (lo imprime el ETL en cada corrida; `docs/generados/inventario_bronze.csv`):

| Tabla | Columnas | Filas | Desde (UTC) | Hasta (UTC) | Uso en el proyecto |
|---|---:|---:|---|---|---|
| `analog_measurements` | 44 | 2 989 759 | 2025-07-12 13:31 | 2026-07-13 05:13 | Fuente principal del balance |
| `status` | 20 | 2 240 052 | 2025-07-12 | 2026-07-13 | Bandera de alarma (`sysalarmflag`) |
| `totals` | 21 | 2 279 918 | 2025-07-12 | 2026-07-13 | No se usa (repite potencias de `analog`) |
| `settings` | 176 | 2 284 775 | 2025-07-12 | 2026-07-13 | Configuración del inversor → SCD tipo 2 |
| `specs` | 16 | 1 333 174 | 2025-07-12 | 2026-02-02 | No se usa (identificación del equipo, casi vacía) |
| `statistics` | 31 | 2 285 904 | 2025-07-12 | 2026-07-13 | Contadores diarios → conciliación |
| `fault_history` | 66 | 2 129 517 | 2025-07-12 | 2026-07-13 | No se usa: códigos de falla en registros propietarios sin mapa público |
| `context` | 5 | 25 178 | 2024-04-30 | 2026-07-19 | Anotaciones JSON → actividad y eventos manuales |

Inversor 1: 1 610 276 lecturas (12-jul-2025 a 13-jul-2026). Inversor 2: 1 379 483 lecturas (14-jul-2025 a **22-jun-2026**, deja de reportar tres semanas antes).

## 1.3 Problemas de calidad de datos

| # | Problema | Evidencia | Dimensión | Regla |
|---|---|---|---|---|
| 1 | Lecturas con la marca de tiempo pero sin ninguna medición | 55 658 filas (1,9 %) | Completitud | R01 |
| 2 | Lecturas repetidas con menos de 1 s de diferencia | 20 379 | Unicidad | R02 |
| 3 | Batería en 0 V reportando SoC > 0 % | 5 | Validez | R03 |
| 4 | Potencia FV que no cumple P = V·I | 2 230 | Exactitud | R04 |
| 5 | Potencia activa de salida mayor que la aparente | 3 799 | Exactitud | R05 |
| 6 | Potencia de red negativa (el equipo no exporta) | 9 | Validez | R06 |
| 7 | Columna `gridpowerw_a` de semántica ambigua (≈ 60 W casi constantes) | 2,9 M valores | Consistencia | R07 |
| 8 | Temperaturas dominadas por un valor centinela de 120 °C (los autores lo advierten) | 2,9 M lecturas | Validez | R08 |
| 9 | Huecos de registro de más de 10 min, el más largo de 26 días | 149 huecos | Completitud | R10 |
| 10 | Cadencia de muestreo cambiante: ~12,6 s en unos periodos y 1–2 min en otros | 2 651 h con intervalos de 60–120 s | Consistencia | Conciliación |
| 11 | Contexto JSON con 7 «formas» distintas y 61 registros sin `context_type` | 25 178 registros | Consistencia | R15 |
| 12 | Contexto con comandos de consola, rutas de directorios y nombres de archivos | 12 183 registros | Privacidad | R14 |
| 13 | Inversor 2 sin capacidad de batería configurada (0 Ah) | 3 versiones | Completitud | R19 |
| 14 | Configuración que "parpadea" entre lecturas (109 339 cambios en un año) | `settings` | Consistencia | R18 |
| 15 | Marcas de tiempo en UTC para una planta en UTC+8 | todas | Consistencia | Conversión a Asia/Shanghai |
| 16 | No hay irradiancia ni potencia instalada de los paneles (kWp) | — | Completitud | Análisis crítico (doc. 2) |

## 1.4 Limitaciones para el análisis

- **Cobertura desigual:** disponibilidad del registro de 79,4 % en el año; el inversor 2 se apaga el 22 de junio de 2026.
- **Dos regímenes de muestreo:** con muestreo de 1–2 min la energía integrada subestima ≈ 23 % frente al contador del propio inversor (ver conciliación). Los totales diarios de esos días son menos confiables.
- **Sin irradiancia ni kWp:** no se pueden calcular indicadores clásicos de rendimiento fotovoltaico (ver doc. 2, análisis crítico).
- **Capacidad de batería del inversor 2 supuesta** (200 Ah, igual al inversor 1).
- **Códigos de falla propietarios:** `fault_history` y `sysalarmflag` son registros sin mapa público; solo se usa "alarma activa sí/no".
- **Operación cambiante:** desde mayo de 2026 la red casi no se usa (prioridad «Solo solar» y cortes largos); la comparación entre meses debe leerse con ese cambio en mente.
