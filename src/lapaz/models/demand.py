"""Pronóstico de demanda diaria de agua por sector.

La serie histórica es SIMULADA (no hay micromedición pública): población del sector ×
dotación × efecto de temperatura, día de la semana y temporadas turísticas. El modelo
(Gradient Boosting) usa solo información disponible con 14 días de anticipación, de modo
que sirve para planear el tandeo de las próximas dos semanas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from lapaz.data.public import DOTACION_ESTIMADA_LHD, daily_temperature, load_sectores

HORIZON_DAYS = 14
FEATURES = ["temp_c", "dow", "doy_sin", "doy_cos", "temporada_alta", "sector_code", "nivel_previo"]
NSE_FACTOR = {"alto": 1.30, "medio": 1.0, "medio-bajo": 0.90, "bajo": 0.80}


def temporada_alta(dates: pd.DatetimeIndex) -> np.ndarray:
    """Vacaciones de verano, Semana Santa aproximada, invierno y Carnaval de La Paz."""
    m, d = dates.month, dates.day
    verano = (m == 7) | ((m == 8) & (d <= 20))
    invierno = ((m == 12) & (d >= 18)) | ((m == 1) & (d <= 6))
    santa = (m == 4) & (d <= 20)
    carnaval = (m == 2) & (d >= 10) & (d <= 20)
    return (verano | invierno | santa | carnaval).astype(int)


def simulate_demand(inicio: str = "2024-10-01", dias: int = 730, seed: int = 3) -> pd.DataFrame:
    """Demanda diaria (m³) por sector. Regresa formato largo: fecha, sector_id, demanda_m3, ..."""
    rng = np.random.default_rng(seed)
    sectores = load_sectores()
    dates = pd.date_range(inicio, periods=dias, freq="D")
    temp = daily_temperature(dates)
    alta = temporada_alta(dates)
    dow_factor = np.where(dates.dayofweek >= 5, 1.06, 1.0)
    rows = []
    for s in sectores.itertuples():
        growth = 1 + 0.02 * np.arange(dias) / 365  # crecimiento poblacional ~2% anual
        per_cap = (
            DOTACION_ESTIMADA_LHD * NSE_FACTOR[s.nivel_socioeconomico]
            * (1 + 0.025 * (temp.to_numpy() - 24))
            * dow_factor * (1 + 0.08 * alta)
        )
        noise = rng.normal(0, 0.04, dias)
        dem = s.poblacion * growth * per_cap * (1 + noise) / 1000
        rows.append(pd.DataFrame({
            "fecha": dates, "sector_id": s.sector_id, "poblacion": s.poblacion * growth,
            "temp_c": temp.to_numpy(), "temporada_alta": alta, "demanda_m3": dem,
        }))
    return pd.concat(rows, ignore_index=True)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.sort_values(["sector_id", "fecha"]).copy()
    out["dow"] = out.fecha.dt.dayofweek
    doy = out.fecha.dt.dayofyear
    out["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    out["sector_code"] = out.sector_id.astype("category").cat.codes
    out["per_capita"] = out.demanda_m3 * 1000 / out.poblacion
    # Nivel reciente conocido con HORIZON_DAYS de anticipación (sin fuga de información).
    out["nivel_previo"] = out.groupby("sector_id").per_capita.transform(
        lambda s: s.shift(HORIZON_DAYS).rolling(28, min_periods=14).mean()
    )
    out["naive_m3"] = out.groupby("sector_id").demanda_m3.shift(HORIZON_DAYS)
    return out


def mape(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.mean(np.abs((y - yhat) / y)) * 100)


def backtest(df: pd.DataFrame, test_days: int = 90, seed: int = 0) -> tuple[pd.DataFrame, dict]:
    """Entrena con el pasado y evalúa los últimos ``test_days`` días vs. un baseline ingenuo."""
    feat = build_features(df).dropna(subset=["nivel_previo", "naive_m3"])
    cutoff = feat.fecha.max() - pd.Timedelta(days=test_days)
    train, test = feat[feat.fecha <= cutoff], feat[feat.fecha > cutoff].copy()
    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=seed)
    model.fit(train[FEATURES], train.per_capita)
    test["pred_m3"] = model.predict(test[FEATURES]) * test.poblacion / 1000
    metrics = {
        "mape_modelo": mape(test.demanda_m3.to_numpy(), test.pred_m3.to_numpy()),
        "mape_ingenuo": mape(test.demanda_m3.to_numpy(), test.naive_m3.to_numpy()),
        "corte": cutoff,
    }
    return test, metrics


def forecast_next(df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Pronóstico de los próximos HORIZON_DAYS días por sector (temperatura = normal climatológica)."""
    feat = build_features(df).dropna(subset=["nivel_previo"])
    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=seed)
    model.fit(feat[FEATURES], feat.per_capita)
    last = df.fecha.max()
    future_dates = pd.date_range(last + pd.Timedelta(days=1), periods=HORIZON_DAYS, freq="D")
    temp = daily_temperature(future_dates, seed=99)
    hist = build_features(df)
    rows = []
    codes = dict(zip(hist.sector_id, hist.sector_code))
    for sid, g in df.groupby("sector_id"):
        pc = g.sort_values("fecha").set_index("fecha").demanda_m3 * 1000 / g.set_index("fecha").poblacion
        pop = g.poblacion.iloc[-1]
        for d in future_dates:
            window = pc[(pc.index <= d - pd.Timedelta(days=HORIZON_DAYS))].tail(28)
            rows.append({
                "fecha": d, "sector_id": sid, "poblacion": pop, "temp_c": temp[d],
                "temporada_alta": int(temporada_alta(pd.DatetimeIndex([d]))[0]),
                "dow": d.dayofweek, "doy_sin": np.sin(2 * np.pi * d.dayofyear / 365.25),
                "doy_cos": np.cos(2 * np.pi * d.dayofyear / 365.25),
                "sector_code": codes[sid], "nivel_previo": window.mean(),
            })
    fut = pd.DataFrame(rows)
    fut["pred_m3"] = model.predict(fut[FEATURES]) * fut.poblacion / 1000
    return fut
