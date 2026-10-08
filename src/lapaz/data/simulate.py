"""Telemetría SIMULADA de pozos de La Paz con fallas inyectadas y etiquetadas.

OOMSAPAS no publica datos de sus bombas, así que generamos series horarias realistas
(caudal, presión, nivel dinámico, potencia) calibradas con cifras públicas. Cada falla
queda registrada en una tabla de eventos para poder medir qué tan pronto la detectan
los modelos. El mismo pipeline acepta datos reales (SCADA o bitácoras) con estas columnas.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from lapaz.data.public import CAPACIDAD_TOTAL_LPS, load_sectores

TELEMETRY_COLUMNS = [
    "timestamp", "pozo_id", "programado", "caudal_lps", "presion_kgcm2",
    "nivel_dinamico_m", "potencia_kw", "falla_tipo",
]

FAULT_TYPES = {
    "abatimiento": "Caída gradual de rendimiento (abatimiento del acuífero / desgaste de bomba)",
    "cavitacion": "Cavitación: presión errática y más energía por m³",
    "fuga": "Fuga aguas abajo: más caudal y menos presión",
    "paro": "Paro súbito (falla eléctrica o sabotaje)",
}


@dataclass(frozen=True)
class SimConfig:
    n_pozos: int = 24
    dias: int = 180
    inicio: str = "2026-01-01"
    seed: int = 42
    capacidad_total_lps: float = CAPACIDAD_TOTAL_LPS


def build_pozos(cfg: SimConfig) -> pd.DataFrame:
    """Catálogo de pozos: capacidad, presión nominal, horas de bombeo y sectores que abastece."""
    rng = np.random.default_rng(cfg.seed)
    sectores = load_sectores()
    n_sec = len(sectores)
    raw = rng.uniform(0.6, 1.4, cfg.n_pozos)
    q0 = raw / raw.sum() * cfg.capacidad_total_lps
    rows = []
    for j in range(cfg.n_pozos):
        primary = j % n_sec
        sec = sectores.iloc[primary]
        # Cada pozo alimenta su sector principal y 1-2 vecinos (por cercanía).
        d = np.hypot(sectores.lat - sec.lat, sectores.lon - sec.lon)
        vecinos = list(sectores.sector_id.iloc[np.argsort(d.to_numpy())[: rng.integers(2, 4)]])
        rows.append({
            "pozo_id": f"P{j + 1:02d}",
            "lat": sec.lat - 0.012 + rng.normal(0, 0.004),
            "lon": sec.lon + rng.normal(0, 0.006),
            "caudal_nominal_lps": round(float(q0[j]), 1),
            "presion_nominal_kgcm2": round(float(rng.uniform(2.0, 4.5)), 2),
            "nivel_estatico_m": round(float(rng.uniform(35, 90)), 1),
            "horas_bombeo": int(rng.choice([18, 20, 22, 24])),
            "sectores": vecinos,
        })
    # Garantiza que cada sector reciba agua de al menos dos pozos (redundancia mínima de la red).
    for sec in sectores.itertuples():
        conectados = [r for r in rows if sec.sector_id in r["sectores"]]
        if len(conectados) >= 2:
            continue
        dist = [np.hypot(r["lat"] - sec.lat, r["lon"] - sec.lon) for r in rows]
        for k in np.argsort(dist):
            if sec.sector_id not in rows[k]["sectores"]:
                rows[k]["sectores"].append(sec.sector_id)
                conectados.append(rows[k])
            if len(conectados) >= 2:
                break
    for r in rows:
        r["sectores"] = ",".join(r["sectores"])
    return pd.DataFrame(rows)


def build_events(pozos: pd.DataFrame, cfg: SimConfig) -> pd.DataFrame:
    """Eventos de falla inyectados (verdad de referencia)."""
    rng = np.random.default_rng(cfg.seed + 1)
    start = pd.Timestamp(cfg.inicio)
    plan = [
        ("abatimiento", 21, 4), ("abatimiento", 18, 4), ("abatimiento", 25, 5),
        ("cavitacion", 10, 3), ("cavitacion", 8, 3),
        ("fuga", 0, 10), ("fuga", 0, 7),
        ("paro", 0, 2), ("paro", 0, 1),
    ]
    ids = rng.choice(pozos.pozo_id.to_numpy(), size=len(plan), replace=False)
    rows = []
    for pozo, (tipo, rampa, dur) in zip(ids, plan):
        # Dejamos 30 días de historia sana al inicio para la línea base.
        dia = int(rng.integers(35, cfg.dias - rampa - dur - 5))
        inicio = start + pd.Timedelta(days=dia, hours=int(rng.integers(0, 24)))
        falla = inicio + pd.Timedelta(days=rampa)
        fin = falla + pd.Timedelta(days=dur)
        rows.append({"pozo_id": pozo, "tipo": tipo, "inicio": inicio, "falla": falla, "fin": fin})
    return pd.DataFrame(rows).sort_values("inicio").reset_index(drop=True)


def simulate(cfg: SimConfig = SimConfig()) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Regresa (pozos, telemetria_horaria, eventos)."""
    rng = np.random.default_rng(cfg.seed + 2)
    pozos = build_pozos(cfg)
    events = build_events(pozos, cfg)
    ts = pd.date_range(cfg.inicio, periods=cfg.dias * 24, freq="h")
    t_days = np.arange(len(ts)) / 24.0
    frames = []
    for p in pozos.itertuples():
        n = len(ts)
        off_start = int(rng.integers(0, 24))
        off_hours = 24 - p.horas_bombeo
        hour = ts.hour.to_numpy()
        programado = ((hour - off_start) % 24) >= off_hours
        # Abatimiento estacional lento del acuífero en temporada seca.
        nivel = p.nivel_estatico_m + 0.03 * t_days + rng.normal(0, 0.3, n)
        q_factor = np.ones(n)
        p_factor = np.ones(n)
        p_noise = np.full(n, 0.03)
        eff = np.full(n, 0.68)
        q_running = np.ones(n, dtype=bool)
        etiqueta = np.array([""] * n, dtype=object)

        for ev in events[events.pozo_id == p.pozo_id].itertuples():
            pre = (ts >= ev.inicio) & (ts < ev.falla)
            down = (ts >= ev.falla) & (ts < ev.fin)
            if ev.tipo == "abatimiento":
                frac = np.clip((ts - ev.inicio) / (ev.falla - ev.inicio), 0, 1)
                q_factor[pre] *= 1 - 0.45 * frac[pre]
                p_factor[pre] *= 1 - 0.20 * frac[pre]
                nivel[pre] += 18 * frac[pre]
                eff[pre] -= 0.10 * frac[pre]
                q_running[down] = False
                etiqueta[pre | down] = ev.tipo
            elif ev.tipo == "cavitacion":
                p_noise[pre] = 0.18
                q_factor[pre] *= 0.90
                eff[pre] -= 0.15
                q_running[down] = False
                etiqueta[pre | down] = ev.tipo
            elif ev.tipo == "fuga":
                q_factor[down] *= 1.22
                p_factor[down] *= 0.62
                etiqueta[down] = ev.tipo
            elif ev.tipo == "paro":
                q_running[down] = False
                etiqueta[down] = ev.tipo

        on = programado & q_running
        caudal = np.where(on, p.caudal_nominal_lps * q_factor * (1 + rng.normal(0, 0.02, n)), 0.0)
        presion = np.where(
            on,
            p.presion_nominal_kgcm2 * p_factor * (1 + rng.normal(0, 1, n) * p_noise),
            rng.uniform(0.1, 0.4, n),
        )
        nivel_din = np.where(on, nivel + 0.25 * caudal, nivel - 4)
        carga_m = nivel_din + 10 * presion
        potencia = np.where(on, 9.81 * caudal / 1000 * carga_m / np.clip(eff, 0.3, 1), 0.0)
        frames.append(pd.DataFrame({
            "timestamp": ts,
            "pozo_id": p.pozo_id,
            "programado": programado,
            "caudal_lps": caudal.round(2),
            "presion_kgcm2": np.clip(presion, 0, None).round(3),
            "nivel_dinamico_m": nivel_din.round(2),
            "potencia_kw": potencia.round(2),
            "falla_tipo": etiqueta,
        }))
    telemetria = pd.concat(frames, ignore_index=True)[TELEMETRY_COLUMNS]
    return pozos, telemetria, events
