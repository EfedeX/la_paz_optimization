import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from lapaz.data.simulate import FAULT_TYPES  # noqa: E402
from lapaz.models.anomaly import FEATURE_LABELS  # noqa: E402
from lapaz.ui import NEUTRAL, PLOT_LAYOUT, SERIES, STATUS, get_eval, get_pozos, nivel_riesgo, simulado  # noqa: E402

st.set_page_config(page_title="Alerta temprana de pozos", page_icon="🚨", layout="wide")
st.title("🚨 Alerta temprana de fallas en pozos")
simulado(
    "OOMSAPAS no publica telemetría. Simulamos 24 pozos (capacidad total calibrada a los 1,060 l/s "
    "del Tercer Informe 2024) con 9 fallas inyectadas para medir qué tan pronto las detecta el sistema."
)

pozos, tel, events, alerts = get_pozos()
fechas = sorted(alerts.fecha.unique())

# Por defecto, una semana antes de que falle el primer pozo con degradación gradual: el momento
# en que el sistema ya avisa y el operador todavía no se entera.
grad = events[events.tipo == "abatimiento"].sort_values("falla")
inicio_demo = pd.Timestamp(grad.falla.iloc[0]).normalize() - pd.Timedelta(days=7) if len(grad) else pd.Timestamp(fechas[-1])
hoy = st.select_slider(
    "▶️ Modo repetición: elige el día (simulado) para ver qué hubiera visto el operador",
    options=fechas, value=min(fechas, key=lambda d: abs(pd.Timestamp(d) - inicio_demo)),
    format_func=lambda d: pd.Timestamp(d).strftime("%d %b %Y"),
)
hoy = pd.Timestamp(hoy)

# --- Ranking del día ----------------------------------------------------------
dia = alerts[alerts.fecha == hoy].copy()
dia[["estado", "_color"]] = dia.apply(lambda r: pd.Series(nivel_riesgo(r.riesgo, r.alerta)), axis=1)
dia["Señal principal"] = dia.indicador_principal.map(FEATURE_LABELS)
dia = dia.sort_values("riesgo", ascending=False)

_, resumen = get_eval()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Pozos en alerta este día", int(dia.alerta.sum()), help="Cualquier detector disparó")
k2.metric("Fallas detectadas", f"{resumen['detectados']} de {resumen['eventos']}")
k3.metric("Aviso previo (fallas graduales)", f"{resumen['anticipacion_mediana_graduales']:.0f} días",
          help="Mediana de días entre la primera alerta y el momento en que el pozo deja de dar agua")
k4.metric("Falsas alarmas", f"{resumen['tasa_falsas_alarmas']:.1%}",
          help="Porcentaje de días-pozo sanos en los que el sistema alertó sin motivo")

left, right = st.columns([2, 3])
with left:
    st.subheader("Prioridad de revisión")
    st.caption("Riesgo = desviación robusta máxima respecto al comportamiento normal del propio pozo.")
    st.dataframe(
        dia[["pozo_id", "estado", "riesgo", "Señal principal"]].rename(
            columns={"pozo_id": "Pozo", "estado": "Estado", "riesgo": "Riesgo"}),
        hide_index=True, width="stretch", height=420,
        column_config={"Riesgo": st.column_config.ProgressColumn(min_value=0, max_value=15, format="%.1f")},
    )

with right:
    default = grad.pozo_id.iloc[0] if len(grad) and hoy < grad.falla.iloc[0] else dia.pozo_id.iloc[0]
    pozo = st.selectbox("Pozo a inspeccionar", pozos.pozo_id, index=list(pozos.pozo_id).index(default))
    a = alerts[alerts.pozo_id == pozo]
    ev = events[events.pozo_id == pozo]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=("Caudal medio (l/s)", "Presión media (kg/cm²)", "Energía por m³ (kWh/m³)"))
    for r, col in enumerate(["caudal_medio", "presion_media", "kwh_m3"], start=1):
        fig.add_trace(go.Scatter(x=a.fecha, y=a[col], mode="lines", line=dict(color=SERIES[0], width=2),
                                 name=FEATURE_LABELS[col], showlegend=False), row=r, col=1)
        hits = a[a.alerta]
        fig.add_trace(go.Scatter(x=hits.fecha, y=hits[col], mode="markers", name="Día con alerta",
                                 marker=dict(color=STATUS["critico"], size=8, symbol="diamond",
                                             line=dict(color="white", width=2)),
                                 showlegend=(r == 1)), row=r, col=1)
    for e in ev.itertuples():
        fig.add_vrect(x0=e.inicio, x1=e.fin, fillcolor=NEUTRAL, opacity=0.18, line_width=0)
        if e.falla != e.inicio:
            fig.add_vline(x=e.falla, line=dict(color=NEUTRAL, dash="dot", width=2))
    fig.add_vline(x=hoy, line=dict(color=SERIES[1], width=2))
    fig.update_layout(height=520, **PLOT_LAYOUT)
    st.plotly_chart(fig, width="stretch")
    if len(ev):
        st.markdown("**Falla real en este pozo:** " + "; ".join(
            f"{FAULT_TYPES[e.tipo]} (del {e.inicio:%d %b} al {e.fin:%d %b})" for e in ev.itertuples()))
    st.caption("Zona gris = falla inyectada (verdad de referencia, el modelo no la ve). Línea punteada = "
               "momento en que el pozo deja de dar agua. Línea naranja = día seleccionado.")

# --- Evaluación ------------------------------------------------------------------
st.subheader("¿Qué tan bien funciona?")
res, _ = get_eval()
res = res.assign(tipo=res.tipo.map(lambda t: f"{t} — {FAULT_TYPES[t]}"))
st.dataframe(
    res[["pozo_id", "tipo", "inicio", "falla", "primera_alerta", "dias_anticipacion"]].rename(columns={
        "pozo_id": "Pozo", "tipo": "Tipo de falla", "inicio": "Empieza", "falla": "Deja de dar agua",
        "primera_alerta": "Primera alerta", "dias_anticipacion": "Días de aviso",
    }), hide_index=True, width="stretch",
)
comp = []
for flag, name in [("alerta_z", "Z robusto"), ("alerta_cusum", "CUSUM (cambios lentos)"),
                   ("alerta_iforest", "Isolation Forest"), ("alerta", "Combinado")]:
    _, s = get_eval(flag=flag)
    comp.append({"Detector": name, "Fallas detectadas": f"{s['detectados']}/{s['eventos']}",
                 "Aviso mediano (días)": s["anticipacion_mediana_graduales"],
                 "Precisión (días de alerta correctos)": f"{s['precision_dias']:.0%}",
                 "Falsas alarmas / 100 pozo-días": round(s["tasa_falsas_alarmas"] * 100, 2)})
st.dataframe(pd.DataFrame(comp), hide_index=True, width="stretch")

with st.expander("¿Cómo funciona y qué se necesita para usarlo con datos reales?"):
    st.markdown(
        """
* **Indicadores diarios por pozo:** caudal medio, presión media, variabilidad de presión,
  energía por m³ y horas programadas sin flujo.
* **Línea base propia de cada pozo:** mediana de los días t-37 a t-7. La última semana se excluye
  para que una degradación lenta no se vuelva "lo normal".
* **Tres detectores:** desviación robusta (mediana/MAD), CUSUM para cambios lentos de caudal, e
  Isolation Forest para combinaciones raras de indicadores.
* **Datos reales mínimos:** caudalímetro y manómetro a la salida de cada pozo (lectura cada hora,
  o incluso cada turno en bitácora) + recibo de CFE. Con solo **kWh de CFE y horas de bombeo** ya
  se puede estimar la eficiencia y detectar desgaste de la bomba.
* **Limitación:** las fallas simuladas son más "limpias" que las reales; con datos reales hay que
  recalibrar umbrales con el equipo de operación.
"""
    )
