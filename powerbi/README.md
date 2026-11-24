# Power BI · tablero analítico SolarBI

## Formato: Power BI Project (`.pbip`) con el modelo en TMDL

El `.pbix` es un binario con los datos adentro: Git no puede mostrar diferencias. El `.pbip` guarda el modelo (TMDL) y el informe (JSON) como **texto**: cada medida nueva aparece como una línea en el `git diff` y **no se suben datos**. `.gitignore` excluye `cache.abf` y `localSettings.json`.

## Crear el modelo en un paso

1. Levantar el clúster (`./scripts/solarbi.sh up`).
2. Power BI Desktop → vista **TMDL** → pegar `modelo_solarbi.tmdl` → **Aplicar**.
3. **Actualizar**. Credenciales: *Base de datos*, usuario `bi_lector`, contraseña `BI_LECTOR_PASSWORD` del `.env`. Si pregunta por cifrado: sin cifrado.
4. Si Power BI corre en otra máquina (p. ej. una VM), cambiar el parámetro *Transformar datos → Editar parámetros → ServidorPostgres* (por defecto `localhost:30432`).
5. Guardar como `.pbip` en esta carpeta.

El script crea: 10 tablas del esquema `gold` (conexión a la base, **no a los archivos**), 14 relaciones de varios a uno, `dim_fecha` marcada como tabla de fechas, 4 jerarquías (Calendario, Día solar, Evento, Contexto), 2 parámetros what-if (`Tarifa`, `Paneles adicionales`), la tabla `Balance` y 38 medidas en 8 carpetas.

## Páginas (mínimo 3, con navegación por pestañas o botones)

| Página | Pregunta | Visuales sugeridos |
|---|---|---|
| **1. Balance energético** | ¿De dónde viene la energía y a dónde va? | Tarjetas: Energía Solar, Red, Carga, Autosuficiencia, Fracción Solar · **Barras apiladas** `Balance[Lado]` × `Balance[Componente]` con `[Balance (kWh)]` (entradas vs. salidas) · Columnas por mes: Solar vs. Red · Segmentaciones: Inversor, Año/Mes |
| **2. Perfil horario y batería** | ¿A qué horas dependemos de la red? ¿Cómo trabaja la batería? | Área por `dim_hora[etiqueta]`: Solar, Red, Batería Descarga · Matriz con jerarquía **Día solar** (franja › hora) con *drill-down* · Línea mensual de Ciclos Equivalentes y SoC Mínimo |
| **3. Eventos y calidad** | ¿Qué pasó y qué tan confiables son los datos? | Matriz con jerarquía **Evento** (categoría › tipo) con *drill-down*: Eventos, Horas en Evento · Tarjetas: Disponibilidad del Registro, % Datos Válidos · Línea de Fracción Solar vs. Fracción Solar Mes Anterior (**inteligencia de tiempo**) |
| **4. Economía y escenarios** | ¿Cuánto ahorramos y qué pasa si cambian la tarifa o los paneles? | Segmentadores de los parámetros **Tarifa** y **Paneles adicionales** · Tarjetas: Ahorro Solar (COP), Costo de la Red (COP), Ahorro Escenario (COP) · Columnas mensuales de ahorro |

## Valores de control (sin filtros)

| Medida | Valor |
|---|---|
| Energía Solar | 2 333,2 kWh |
| Energía a la Carga | 5 973,2 kWh |
| Energía de la Red | 4 730,3 kWh |
| Autosuficiencia | 20,8 % |
| Fracción Solar | 33,0 % |
| % Datos Válidos | 99,53 % |
| Ahorro Solar (tarifa 991,29) | $ 2 312 880 |

Deben coincidir con `SELECT * FROM gold.v_balance_mes` en DBeaver.
