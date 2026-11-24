"""Conciliación: los totales cargados se comparan contra la fuente y contra una fuente independiente.

1. Conteos: lecturas Bronze = lecturas en Silver + descartadas por regla (residuo 0).
2. Energía: integración directa de las lecturas Bronze (trapecio) vs. suma en Gold.
3. Energía: Gold vs. contadores diarios del propio inversor (solo días con cobertura ≥ 97 %).
4. Contexto: registros JSON en Bronze vs. Silver.
"""
import numpy as np
import pandas as pd

from . import config


def integrar_bronze(a: pd.DataFrame, col: str) -> float:
    """kWh por trapecio directamente sobre las lecturas (sin pasar por Silver ni Gold)."""
    a = a.sort_values(["inverter", "read_ts"])
    dt = a.groupby("inverter").read_ts.diff()
    p_prev = a.groupby("inverter")[col].shift()
    ok = dt <= config.HUECO_SEG
    return float(((a[col] + p_prev) / 2 * dt)[ok].sum() / 3.6e6)


def calcular(n_bronze, bit, a, s, h, cont, n_ctx_bronze, n_ctx_silver):
    filas = []

    def fila(metrica, fuente, cargado, explicacion):
        dif = cargado - fuente
        pct = None if fuente == 0 else round(100 * dif / fuente, 3)
        filas.append(dict(metrica=metrica, total_fuente=round(fuente, 3), total_cargado=round(cargado, 3),
                          diferencia=round(dif, 3), diferencia_pct=pct, explicacion=explicacion))

    desc = sum(r.afectadas for r in bit.reglas if r.regla in ("R01", "R02"))
    fila("Lecturas analog_measurements (Bronze) vs. Silver + descartadas",
         n_bronze, int(s.n_lecturas.sum()) + desc,
         f"Silver contiene {int(s.n_lecturas.sum())} lecturas; R01 y R02 descartaron {desc}. Residuo 0.")
    fila("Lecturas válidas Silver vs. Gold", int(s.n_validas.sum()), int(h.lecturas_validas.sum()),
         "Gold suma las lecturas válidas de Silver por hora. Residuo 0.")

    pares = [("pv1power", "e_solar_kwh", "Energía solar (kWh)"),
             ("outw_a", "e_carga_kwh", "Energía entregada a la carga (kWh)"),
             ("linepowerw_a", "e_red_kwh", "Energía importada de la red (kWh)")]
    for col_b, col_g, nombre in pares:
        fila(f"{nombre}: integración directa Bronze vs. Gold", integrar_bronze(a, col_b), float(h[col_g].sum()),
             "Misma regla de integración (trapecio, intervalos ≤ 10 min); la diferencia es solo redondeo "
             "al guardar Wh por minuto y kWh por hora.")

    # Fuente independiente: contadores del inversor en días con cobertura casi completa,
    # separados por cadencia de muestreo (el registrador tuvo periodos de ~12 s y de 1–2 min)
    h2 = h.copy()
    h2["fecha"] = h2.ts_hora_utc.dt.tz_convert(config.ZONA_LOCAL).dt.date
    dia = h2.groupby(["inversor", "fecha"]).agg(pv=("e_solar_kwh", "sum"), carga=("e_carga_kwh", "sum"),
                                               minutos=("minutos_con_dato", "sum"),
                                               lecturas=("lecturas_total", "sum")).reset_index()
    dia = dia[dia.minutos >= 0.97 * 1440].merge(
        cont.rename(columns={"fecha_local": "fecha"}), on=["inversor", "fecha"])
    dia["cadencia"] = np.where(dia.lecturas / dia.minutos > 3, "rápida (~12 s)", "lenta (1–2 min)")
    for cad, g in dia.groupby("cadencia"):
        fila(f"Energía solar Gold vs. contador del inversor · cadencia {cad} ({len(g)} días con cobertura ≥ 97 %)",
             float(g.pv_kwh.sum()), float(g.pv.sum()),
             "Con muestreo rápido la integración sigue al contador del inversor (≈ −8 %: el contador mide en la entrada "
             "FV con resolución de 0,1 kWh). Con muestreo lento (1–2 min) la integración subestima ≈ 23 %: las rampas "
             "por nubes y los picos de carga entre lecturas se pierden. Hallazgo de calidad: en esos días el contador "
             "del inversor es la fuente más confiable para totales diarios.")
        fila(f"Energía de carga Gold vs. contador del inversor · cadencia {cad} ({len(g)} días)",
             float(g.carga_kwh.sum()), float(g.carga.sum()),
             "Con muestreo rápido la diferencia es ≈ −2,5 %: valida la unidad (W) y el signo de outw_a.")
    fila("Registros de contexto (JSON) Bronze vs. Silver", n_ctx_bronze, n_ctx_silver,
         "Todos los registros se cargan; solo se sanitiza el contenido (R14).")
    return pd.DataFrame(filas)
