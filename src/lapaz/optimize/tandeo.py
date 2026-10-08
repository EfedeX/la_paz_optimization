"""Reparto óptimo del agua disponible entre sectores (tandeo) con programación lineal.

Cada pozo solo puede abastecer a los sectores con los que está conectado. Etapa 1:
maximiza la cobertura mínima (que ningún sector se quede muy atrás). Etapa 2: con esa
equidad garantizada, maximiza el agua total entregada. Se compara contra un reparto
"fijo" en el que cada pozo divide su producción en partes iguales entre sus sectores.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linprog


def _links(pozos: pd.DataFrame, sectores: list[str]) -> list[tuple[int, int]]:
    idx = {s: i for i, s in enumerate(sectores)}
    return [
        (j, idx[s])
        for j, row in enumerate(pozos.itertuples())
        for s in row.sectores.split(",")
        if s in idx
    ]


def well_capacity_m3(pozos: pd.DataFrame, perdidas: float, fuera_servicio: set[str] | None = None) -> np.ndarray:
    """Agua que llega a tomas (m³/día) por pozo, descontando pérdidas y pozos fuera de servicio."""
    fuera_servicio = fuera_servicio or set()
    cap = pozos.caudal_nominal_lps.to_numpy() * 3.6 * pozos.horas_bombeo.to_numpy() * (1 - perdidas)
    activo = ~pozos.pozo_id.isin(fuera_servicio).to_numpy()
    return cap * activo


def reparto_fijo(pozos: pd.DataFrame, demanda: pd.Series, perdidas: float,
                 fuera_servicio: set[str] | None = None) -> pd.Series:
    """Línea base: cada pozo reparte en partes iguales; lo que sobra en un sector se pierde."""
    sectores = list(demanda.index)
    cap = well_capacity_m3(pozos, perdidas, fuera_servicio)
    entregado = pd.Series(0.0, index=sectores)
    for j, i in _links(pozos, sectores):
        n = len([s for s in pozos.sectores.iloc[j].split(",") if s in demanda.index])
        entregado.iloc[i] += cap[j] / n
    return np.minimum(entregado, demanda)


def reparto_optimo(pozos: pd.DataFrame, demanda: pd.Series, perdidas: float,
                   fuera_servicio: set[str] | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """Regresa (entregado por sector, flujos pozo→sector en m³/día)."""
    sectores = list(demanda.index)
    D = demanda.to_numpy(dtype=float)
    cap = well_capacity_m3(pozos, perdidas, fuera_servicio)
    links = _links(pozos, sectores)
    nf = len(links)
    n_s, n_w = len(sectores), len(pozos)

    # Matrices: A_sec[i, k] = 1 si el flujo k llega al sector i; A_well[j, k] = 1 si sale del pozo j.
    A_sec = np.zeros((n_s, nf))
    A_well = np.zeros((n_w, nf))
    for k, (j, i) in enumerate(links):
        A_sec[i, k] = 1
        A_well[j, k] = 1

    # Etapa 1: variables [f, t]; max t  ⇔ min -t
    c1 = np.zeros(nf + 1)
    c1[-1] = -1
    A_ub = np.vstack([
        np.hstack([-A_sec, D[:, None]]),        # t*D_i - sum f <= 0
        np.hstack([A_sec, np.zeros((n_s, 1))]),  # sum f <= D_i
        np.hstack([A_well, np.zeros((n_w, 1))]),  # sum f <= cap_j
    ])
    b_ub = np.concatenate([np.zeros(n_s), D, cap])
    bounds = [(0, None)] * nf + [(0, 1)]
    r1 = linprog(c1, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    if not r1.success:
        raise RuntimeError(f"LP etapa 1 sin solución: {r1.message}")
    t = r1.x[-1] - 1e-7

    # Etapa 2: máximo volumen total manteniendo la cobertura mínima t.
    c2 = -np.ones(nf)
    A_ub2 = np.vstack([-A_sec, A_sec, A_well])
    b_ub2 = np.concatenate([-t * D, D, cap])
    r2 = linprog(c2, A_ub=A_ub2, b_ub=b_ub2, bounds=[(0, None)] * nf, method="highs")
    if not r2.success:
        raise RuntimeError(f"LP etapa 2 sin solución: {r2.message}")
    flows = pd.DataFrame([
        {"pozo_id": pozos.pozo_id.iloc[j], "sector_id": sectores[i], "m3_dia": r2.x[k]}
        for k, (j, i) in enumerate(links)
    ])
    entregado = pd.Series(A_sec @ r2.x, index=sectores)
    return entregado, flows[flows.m3_dia > 1e-6].reset_index(drop=True)


def resumen(demanda: pd.Series, entregado: pd.Series, poblacion: pd.Series, umbral: float = 0.7) -> dict:
    cob = entregado / demanda
    return {
        "entregado_m3": float(entregado.sum()),
        "cobertura_total": float(entregado.sum() / demanda.sum()),
        "cobertura_minima": float(cob.min()),
        "sectores_bajo_umbral": int((cob < umbral).sum()),
        "lhd_promedio": float(entregado.sum() * 1000 / poblacion.sum()),
    }
