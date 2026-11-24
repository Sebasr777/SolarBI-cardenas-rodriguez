# 2. Catálogo de indicadores

Fuente de todos los indicadores: `gold.fact_energia_hora` (balance), `gold.fact_evento` (eventos) y `gold.fact_lectura_rt` (en vivo). Hora local: Asia/Shanghai.

## 2.1 Indicadores mínimos del enunciado

| Indicador | Fórmula | Unidad | Granularidad | Meta / umbral | Fuente (DAX / SQL) | Usuario |
|---|---|---|---|---|---|---|
| Energía solar generada | Σ trapecio de `pv1power` · Δt (Δt ≤ 10 min) | kWh | Inversor × hora → día, mes, periodo | ↑ | `[Energía Solar (kWh)]` · `e_solar_kwh` | Dirección |
| Energía entregada a la carga | Σ trapecio de `outw_a` · Δt | kWh | Ídem | — | `[Energía a la Carga (kWh)]` | Dirección, coordinador |
| Energía importada de la red | Σ trapecio de `linepowerw_a` · Δt | kWh | Ídem | ↓ | `[Energía de la Red (kWh)]` | Dirección |
| Disponibilidad del registro | tiempo cubierto por lecturas / tiempo del periodo | % | Ídem | ≥ 95 % | `[Disponibilidad del Registro]` | Analistas, mantenimiento |
| % de datos válidos | lecturas válidas / lecturas tras R01–R02 | % | Ídem | ≥ 99 % | `[% Datos Válidos]` | Analistas |

## 2.2 Indicadores propios de un sistema híbrido (no los pide el enunciado)

| Indicador | Fórmula | Unidad | Meta | Por qué se propone |
|---|---|---|---|---|
| **Autosuficiencia** (*self-sufficiency*) | 1 − mín(E_red, E_carga) / E_carga | % | ≥ 50 % | Es la pregunta central del balance: ¿qué parte del consumo cubre la microrred sin comprar energía? |
| **Fracción solar** | E_solar / (E_solar + E_red) | % | ≥ 50 % | Mide la participación del sol en la energía que entra al sistema |
| **Ciclos equivalentes de batería** | E_descarga / capacidad nominal (kWh) | ciclos | ≤ 250 por año | La vida útil del litio se mide en ciclos (≈ 3 000–6 000); permite prever el reemplazo |
| **Eficiencia del sistema** | E_carga / (E_solar + E_red) | % | ≥ 85 % | Revela pérdidas de conversión y consumo propio del inversor |
| SoC mínimo y episodios de batería baja | mín(SoC); n.º de eventos SOC_BAJO | %, n.º | SoC ≥ 20 % | Riesgo de quedarse sin respaldo |
| Horas sin red | Σ duración de eventos RED_NO_DISPONIBLE | h | — | Mide la resiliencia: cuánto tiempo opera en isla |

## 2.3 Indicador económico (COP)

| Indicador | Fórmula | Tarifa |
|---|---|---|
| **Ahorro por energía solar** | E_solar × tarifa | **991,29 COP/kWh** |
| Costo de la energía comprada | E_red × tarifa | Ídem |

**Tarifa elegida:** costo unitario (CU) de EPM, nivel de tensión I, propiedad EPM, publicado para octubre de 2026 (991,29 COP/kWh). **Justificación:** un campus universitario público es un usuario «oficial», que paga el CU sin subsidio ni contribución, igual que el estrato 4; es el valor de referencia de la tarifa plena en Medellín. En Power BI la tarifa es un **parámetro what-if** (500–1 500 COP/kWh) para ver la sensibilidad del ahorro.

## 2.4 Umbrales de las alertas (Grafana)

| Alerta | Condición | Umbral | Justificación |
|---|---|---|---|
| **Batería con carga baja** | SoC promedio de 5 min < umbral, sostenido 2 min | **20 %** | El inversor tiene configurado: alarma propia al 15 % (`batsoclowalarm`), paso a red al 10 % (`inv2linesoc`) y apagado al 5 % (`batstopsoc`). El 20 % avisa *antes* de la alarma del equipo. En el histórico el SoC está bajo 20 % solo el 0,2 % (inversor 1) y el 3 % (inversor 2) del tiempo: la alerta no genera fatiga. |
| **Corte de la red pública** | tensión mínima de red de 3 min < umbral, sostenido 1 min | **180 V** | Nominal 230 V. La tensión de red en la fuente es bimodal (0 V o 230 ± 10 V; solo 105 lecturas entre 1 y 180 V): cualquier valor < 180 V (−22 %) es una red ausente, no una fluctuación. |

Los dos umbrales están en el ConfigMap (`UMBRAL_SOC_ALERTA`, `UMBRAL_RED_V_ALERTA`): se cambian sin reconstruir imágenes.

## 2.5 Análisis crítico: lo que esta fuente NO permite calcular

El indicador clásico de una planta fotovoltaica es el **Performance Ratio (PR)** = rendimiento real / rendimiento de referencia = (E_FV / P_instalada) / (H_irradiación / 1 kW/m²). Junto con él tampoco se pueden calcular el **rendimiento específico** (kWh/kWp) ni el **factor de planta**. Faltan dos datos:

1. **Irradiancia en el plano de los paneles** (W/m²): no hay piranómetro. Las imágenes de cielo de OpenCEM muestran nubes, pero no miden irradiancia.
2. **Potencia nominal instalada** (kWp): no está en ninguna tabla.

**Qué haríamos:** (a) pedir a los autores o a la placa de los módulos la potencia instalada; (b) estimar la irradiancia con una fuente satelital pública para las coordenadas que trae el contexto (22,693° N, 114,211° E), por ejemplo NASA POWER o PVGIS, y documentar la incertidumbre; (c) a mediano plazo, instalar un piranómetro y registrarlo con el mismo Modbus. Mientras tanto usamos la **fracción solar** y la **autosuficiencia**, que no dependen de esos datos.
