"""Detección temprana de fallas en pozos a partir de telemetría horaria.

Tres detectores complementarios sobre indicadores diarios por pozo:

* ``robust_z``: desviación robusta (mediana/MAD) contra la línea base del propio pozo.
* ``cusum``: suma acumulada para cambios lentos de caudal (el abatimiento no salta, se arrastra).
* ``iforest``: Isolation Forest sobre las desviaciones, para combinaciones raras.

La línea base de cada día usa la ventana [t-37, t-7]: la semana más reciente queda fuera
para que una degradación gradual no "contamine" su propia referencia.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

FEATURES = ["caudal_medio", "presion_media", "presion_cv", "kwh_m3", "horas_sin_flujo"]
# Dirección que indica problema: -1 bajo es malo, +1 alto es malo, 0 ambos.
DIRECTION = {"caudal_medio": 0, "presion_media": -1, "presion_cv": 1, "kwh_m3": 1, "horas_sin_flujo": 1}
FEATURE_LABELS = {
    "caudal_medio": "Caudal medio (l/s)",
    "presion_media": "Presión media (kg/cm²)",
    "presion_cv": "Variabilidad de presión",
    "kwh_m3": "Energía por m³ (kWh/m³)",
    "horas_sin_flujo": "Horas programadas sin flujo",
}


def daily_features(telemetria: pd.DataFrame) -> pd.DataFrame:
    """Agrega la telemetría horaria a indicadores diarios por pozo (solo horas programadas)."""
    t = telemetria[telemetria.programado].copy()
    t["fecha"] = t.timestamp.dt.normalize()
    t["volumen_m3"] = t.caudal_lps * 3.6
    flowing = t.caudal_lps > 0.5
    t["presion_on"] = t.presion_kgcm2.where(flowing)
    t["caudal_on"] = t.caudal_lps.where(flowing)
    t["sin_flujo"] = (~flowing).astype(int)
    g = t.groupby(["pozo_id", "fecha"])
    df = pd.DataFrame({
        "caudal_medio": g.caudal_on.mean(),
        "presion_media": g.presion_on.mean(),
        "presion_cv": g.presion_on.std() / g.presion_on.mean(),
        "kwh_m3": g.potencia_kw.sum() / g.volumen_m3.sum().replace(0, np.nan),
        "horas_sin_flujo": g.sin_flujo.sum(),
        "volumen_m3": g.volumen_m3.sum(),
    }).reset_index()
    return df.sort_values(["pozo_id", "fecha"]).reset_index(drop=True)


def _baseline(s: pd.Series, lag: int = 7, window: int = 30) -> tuple[pd.Series, pd.Series]:
    shifted = s.shift(lag)
    med = shifted.rolling(window, min_periods=14).median()
    mad = (shifted - med).abs().rolling(window, min_periods=14).median()
    return med, mad


def robust_scores(daily: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas ``z_<feature>`` con la desviación robusta respecto a la línea base."""
    out = daily.copy()
    for f in FEATURES:
        med = pd.Series(index=out.index, dtype=float)
        mad = pd.Series(index=out.index, dtype=float)
        for _, idx in out.groupby("pozo_id").groups.items():
            m, d = _baseline(out.loc[idx, f])
            med.loc[idx], mad.loc[idx] = m, d
        floor = med.abs() * 0.02 + 1e-3  # evita z enormes si la serie es casi constante
        z = (out[f] - med) / np.maximum(1.4826 * mad, floor)
        out[f"z_{f}"] = z
    return out


def detect(daily: pd.DataFrame, z_thr: float = 4.0, cusum_k: float = 1.0, cusum_h: float = 8.0,
           contamination: float = 0.03, seed: int = 0) -> pd.DataFrame:
    """Corre los tres detectores. Regresa un renglón por pozo-día con banderas y score de riesgo."""
    df = robust_scores(daily)
    zcols = [f"z_{f}" for f in FEATURES]

    # 1) z robusto con dirección del problema.
    signed = []
    for f in FEATURES:
        z = df[f"z_{f}"]
        signed.append(z.abs() if DIRECTION[f] == 0 else (z * DIRECTION[f]).clip(lower=0))
    signed = pd.concat(signed, axis=1).fillna(0)
    signed.columns = FEATURES
    df["riesgo"] = signed.max(axis=1)
    df["indicador_principal"] = signed.idxmax(axis=1)
    df["alerta_z"] = (df.riesgo > z_thr) | (df.horas_sin_flujo >= 3)

    # 2) CUSUM bilateral sobre el caudal estandarizado (cambios lentos).
    df["cusum"] = 0.0
    df["alerta_cusum"] = False
    for _, idx in df.groupby("pozo_id").groups.items():
        z = df.loc[idx, "z_caudal_medio"].fillna(0).clip(-10, 10).to_numpy()
        lo = hi = 0.0
        vals, flags = [], []
        for v in z:
            lo = max(0.0, lo - v - cusum_k)
            hi = max(0.0, hi + v - cusum_k)
            vals.append(max(lo, hi))
            flags.append(max(lo, hi) > cusum_h)
            if flags[-1]:  # se reinicia tras alarmar, como en operación real (alerta atendida)
                lo = hi = 0.0
        df.loc[idx, "cusum"] = vals
        df.loc[idx, "alerta_cusum"] = flags

    # 3) Isolation Forest sobre las desviaciones (z), entrenado con todos los pozos.
    X = df[zcols].fillna(0).clip(-20, 20).to_numpy()
    valid = df[zcols].notna().all(axis=1).to_numpy()
    df["alerta_iforest"] = False
    if valid.sum() > 50:
        model = IsolationForest(n_estimators=200, contamination=contamination, random_state=seed)
        model.fit(X[valid])
        pred = model.predict(X) == -1
        df["alerta_iforest"] = pred & valid

    df["alerta"] = df.alerta_z | df.alerta_cusum | df.alerta_iforest
    return df


def evaluate(alerts: pd.DataFrame, events: pd.DataFrame, flag: str = "alerta",
             grace_days: int = 2) -> tuple[pd.DataFrame, dict]:
    """Compara alertas contra las fallas inyectadas.

    ``dias_anticipacion`` > 0 significa que la alerta llegó antes de que el pozo dejara de
    funcionar; para fugas y paros (súbitos) se reporta el retraso como valor negativo o cero.
    """
    rows = []
    in_event = pd.Series(False, index=alerts.index)
    for ev in events.itertuples():
        w = alerts.pozo_id == ev.pozo_id
        lo = ev.inicio.normalize()
        hi = ev.fin.normalize() + pd.Timedelta(days=grace_days)
        mask = w & (alerts.fecha >= lo) & (alerts.fecha <= hi)
        in_event |= mask
        hits = alerts.loc[mask & alerts[flag], "fecha"]
        first = hits.min() if len(hits) else pd.NaT
        lead = (ev.falla.normalize() - first).days if pd.notna(first) else np.nan
        rows.append({
            "pozo_id": ev.pozo_id, "tipo": ev.tipo, "inicio": ev.inicio, "falla": ev.falla,
            "primera_alerta": first, "detectada": pd.notna(first), "dias_anticipacion": lead,
        })
    res = pd.DataFrame(rows)
    alert_days = int(alerts[flag].sum())
    false_alarms = int((alerts[flag] & ~in_event).sum())
    healthy_days = int((~in_event).sum())
    summary = {
        "eventos": len(res),
        "detectados": int(res.detectada.sum()),
        "recall": float(res.detectada.mean()) if len(res) else 0.0,
        "dias_alerta": alert_days,
        "falsas_alarmas": false_alarms,
        "precision_dias": (alert_days - false_alarms) / alert_days if alert_days else 0.0,
        "tasa_falsas_alarmas": false_alarms / healthy_days if healthy_days else 0.0,
        "anticipacion_mediana_graduales": float(
            res.loc[res.tipo.isin(["abatimiento", "cavitacion"]), "dias_anticipacion"].median()
        ),
    }
    return res, summary
