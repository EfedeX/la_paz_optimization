import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from lapaz.ui import PLOT_LAYOUT, SERIES, get_demanda, get_sectores, publico, simulado  # noqa: E402

st.set_page_config(page_title="Demanda de agua", page_icon="📈", layout="wide")
st.title("📈 Pronóstico de demanda de agua por sector")
simulado(
    "No hay micromedición pública. La demanda histórica se simula con población por sector × "
    "dotación de ~300 l/hab/día × efecto de calor, fines de semana y temporadas turísticas."
)
publico("clima")

df, test, metrics, fut = get_demanda()
sectores = get_sectores()
nombres = dict(zip(sectores.sector_id, sectores.nombre))

k1, k2, k3 = st.columns(3)
k1.metric("Error del modelo (MAPE, 14 días antes)", f"{metrics['mape_modelo']:.1f}%")
k2.metric("Error de 'lo mismo que hace 2 semanas'", f"{metrics['mape_ingenuo']:.1f}%")
k3.metric("Demanda total próximas 2 semanas", f"{fut.pred_m3.sum() / 1000:,.0f} mil m³")

opciones = ["Toda la ciudad"] + [f"{s} · {nombres[s]}" for s in sectores.sector_id]
sel = st.selectbox("Sector", opciones)
if sel == "Toda la ciudad":
    hist = df.groupby("fecha").demanda_m3.sum()
    bt = test.groupby("fecha")[["demanda_m3", "pred_m3"]].sum()
    fc = fut.groupby("fecha").pred_m3.sum()
else:
    sid = sel.split(" · ")[0]
    hist = df[df.sector_id == sid].set_index("fecha").demanda_m3
    bt = test[test.sector_id == sid].set_index("fecha")[["demanda_m3", "pred_m3"]]
    fc = fut[fut.sector_id == sid].set_index("fecha").pred_m3

hist = hist[hist.index >= hist.index.max() - pd.Timedelta(days=270)]
fig = go.Figure()
fig.add_trace(go.Scatter(x=hist.index, y=hist.values, name="Demanda (simulada)",
                         line=dict(color=SERIES[0], width=2)))
fig.add_trace(go.Scatter(x=bt.index, y=bt.pred_m3, name="Pronóstico en prueba (backtest)",
                         line=dict(color=SERIES[1], width=2, dash="dot")))
fig.add_trace(go.Scatter(x=fc.index, y=fc.values, name="Pronóstico próximas 2 semanas",
                         line=dict(color=SERIES[1], width=3)))
fig.update_layout(height=440, yaxis_title="m³ por día", **PLOT_LAYOUT)
st.plotly_chart(fig, width="stretch")

st.subheader("Pronóstico por sector (promedio diario, próximas 2 semanas)")
tabla = (fut.groupby("sector_id").agg(m3_dia=("pred_m3", "mean"), poblacion=("poblacion", "last"))
         .assign(l_hab_dia=lambda d: d.m3_dia * 1000 / d.poblacion).reset_index())
tabla.insert(1, "Sector", tabla.sector_id.map(nombres))
st.dataframe(
    tabla.drop(columns="sector_id").rename(columns={"m3_dia": "m³/día", "poblacion": "Habitantes",
                                                    "l_hab_dia": "l/hab/día"}),
    hide_index=True, width="stretch",
    column_config={"m³/día": st.column_config.NumberColumn(format="%.0f"),
                   "Habitantes": st.column_config.NumberColumn(format="%.0f"),
                   "l/hab/día": st.column_config.NumberColumn(format="%.0f")},
)

with st.expander("¿Para qué sirve esto en la operación diaria?"):
    st.markdown(
        """
* El pronóstico de 14 días alimenta el **módulo de tandeo**: si viene una ola de calor o una
  temporada vacacional, el reparto se ajusta *antes* de que falte el agua.
* Variables: temperatura (normal climatológica o pronóstico del SMN), día de la semana,
  estacionalidad, temporadas altas y el nivel reciente de consumo del sector.
* Con datos reales (macromedidores por sector o facturación), basta reemplazar
  `simulate_demand()` por la serie histórica; el resto del pipeline no cambia.
"""
    )
