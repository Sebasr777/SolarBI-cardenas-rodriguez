# 8. Hallazgos y recomendaciones (historia para la sustentación)

> Periodo: 12-jul-2025 a 13-jul-2026 · dos inversores · tarifa EPM 991,29 COP/kWh.
> Cada cifra se reproduce con `sql/consultas/consultas_analiticas.sql`.

## La historia en una frase

**El sol produce, pero de día; la microrred consume a toda hora. Como la batería es pequeña, casi 9 de cada 10 kWh que se compran a la red se compran de noche.**

## Hallazgos

1. **La microrred cubre por sí misma solo el 21 % de su consumo** (autosuficiencia). En el año entraron 2 333 kWh del sol y 4 730 kWh de la red, para 5 973 kWh entregados a los equipos: fracción solar de **33 %**.
2. **El problema es de horario, no de paneles (Q4).** El 88 % de la energía de la red se compra en horas sin sol (18:00–6:00). En el pico solar (10:00–14:00) la red aporta solo el 2,6 %. Más paneles no resuelven la noche.
3. **La batería trabaja poco y se queda corta.** ~62 (inversor 1) y ~92 (inversor 2) ciclos equivalentes en un año, frente a miles de ciclos de vida útil: hay espacio para usarla más. Con ~10 kWh por inversor no alcanza a cubrir una noche de ~4 kWh de carga más el consumo propio.
4. **Las cargas de cómputo pesan (Q9).** En las horas con entrenamiento de redes neuronales en GPU, la carga del inversor 1 sube de 228 a 312 Wh por hora (**+37 %**). Hoy esos entrenamientos se lanzan a cualquier hora.
5. **El cambio de configuración se nota.** Desde enero de 2026 los inversores pasaron a prioridad «Solo solar» y desde mayo la red casi no se usa (cortes largos de 17, 10 y 7 días en el inversor 1): la fracción solar sube a 80–100 %, pero el consumo cae de ~800 a ~140 kWh/mes, es decir, se apagaron cargas.
6. **En pesos:** el sol ahorró **≈ 2,3 millones de COP** en el año y la red costó **≈ 4,7 millones** (tarifa de referencia EPM).
7. **Calidad de datos:** la disponibilidad del registro fue de **79,4 %** y el 99,5 % de las lecturas son válidas, pero en los periodos con muestreo de 1–2 min la energía integrada se queda corta ≈ 23 % frente al contador del inversor. Además, el inversor 2 no tiene configurada la capacidad de su batería.

## Recomendaciones a la dirección de infraestructura

| # | Recomendación | Indicador de seguimiento | Meta |
|---|---|---|---|
| 1 | **Ampliar la batería antes que los paneles**: el excedente de mediodía ya existe, falta guardarlo para la noche (usar el parámetro what-if de Power BI para dimensionar) | Autosuficiencia | De 21 % a ≥ 50 % |
| 2 | **Programar los entrenamientos en GPU entre 10:00 y 15:00** (gestión de cargas) | % de la carga de cómputo en horas de sol | ≥ 70 % |
| 3 | Mantener la alerta de **SoC < 20 %** y la de **corte de red** en Grafana, con un responsable por turno | Tiempo de respuesta a la alerta | < 15 min |
| 4 | Configurar en el inversor 2 la capacidad real de su batería | Versiones de `dim_inversor` con capacidad supuesta | 0 |
| 5 | Fijar la cadencia del registrador en ≤ 15 s y vigilar los huecos | Disponibilidad del registro | ≥ 95 % |
| 6 | Instalar un piranómetro y documentar la potencia instalada (kWp) | Performance Ratio calculable | Sí |
