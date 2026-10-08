"""Utilidades compartidas por las páginas de Streamlit: caché, colores y avisos de procedencia."""

from __future__ import annotations

import streamlit as st

from lapaz.data.public import FUENTES, load_sectores
from lapaz.data.simulate import SimConfig, simulate
from lapaz.models.anomaly import daily_features, detect, evaluate
from lapaz.models.demand import backtest, forecast_next, simulate_demand

# Paleta validada (skill dataviz, paleta de referencia).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
NEUTRAL = "#9a9893"
STATUS = {"ok": "#0ca30c", "atencion": "#fab219", "alerta": "#ec835a", "critico": "#d03b3b"}
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
PLOT_LAYOUT = dict(
    margin=dict(l=10, r=10, t=40, b=10),
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    font=dict(size=13),
)


def simulado(texto: str = "") -> None:
    st.warning(f"🧪 **Datos simulados.** {texto}".strip(), icon=None)


def publico(clave: str) -> None:
    st.caption(f"📊 Fuente: {FUENTES[clave]}")


@st.cache_data(show_spinner="Simulando telemetría de pozos…")
def get_pozos(seed: int = 42):
    pozos, tel, events = simulate(SimConfig(seed=seed))
    daily = daily_features(tel)
    alerts = detect(daily)
    return pozos, tel, events, alerts


@st.cache_data
def get_eval(seed: int = 42, flag: str = "alerta"):
    _, _, events, alerts = get_pozos(seed)
    return evaluate(alerts, events, flag)


@st.cache_data(show_spinner="Entrenando modelo de demanda…")
def get_demanda():
    df = simulate_demand()
    test, metrics = backtest(df)
    fut = forecast_next(df)
    return df, test, metrics, fut


@st.cache_data
def get_sectores():
    return load_sectores()


def nivel_riesgo(riesgo: float, alerta: bool) -> tuple[str, str]:
    """(etiqueta con ícono, color de estado) — el color nunca va solo."""
    if alerta and riesgo > 8:
        return "⛔ Crítico", STATUS["critico"]
    if alerta:
        return "🔶 Alerta", STATUS["alerta"]
    if riesgo > 2.5:
        return "⚠️ Atención", STATUS["atencion"]
    return "✅ Normal", STATUS["ok"]
