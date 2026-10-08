import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from lapaz.data.public import PERDIDAS_ESTIMADAS  # noqa: E402
from lapaz.optimize.tandeo import reparto_optimo  # noqa: E402
from lapaz.ui import SEQ_BLUE, get_demanda, get_pozos, get_sectores, nivel_riesgo, publico  # noqa: E402

st.set_page_config(page_title="Mapa de La Paz", page_icon="🗺️", layout="wide")
st.title("🗺️ Mapa: déficit por sector y pozos en riesgo")
publico("sectores")
st.caption("🧪 Ubicación y estado de pozos: simulados.")

pozos, _, _, alerts = get_pozos()
_, _, _, fut = get_demanda()
sectores = get_sectores().set_index("sector_id")

ultimo = alerts[alerts.fecha == alerts.fecha.max()].set_index("pozo_id")
fuera = set(ultimo.index[ultimo.alerta])
demanda = fut[fut.fecha == fut.fecha.min()].set_index("sector_id").pred_m3.reindex(sectores.index)
entregado, _ = reparto_optimo(pozos, demanda, PERDIDAS_ESTIMADAS, fuera)
sectores["cobertura"] = (entregado / demanda).clip(0, 1)
sectores["lhd"] = entregado * 1000 / sectores.poblacion

p = pozos.set_index("pozo_id").join(ultimo[["riesgo", "alerta", "indicador_principal"]])
p[["estado", "color"]] = [nivel_riesgo(r, a) for r, a in zip(p.riesgo, p.alerta)]

fig = go.Figure()
fig.add_trace(go.Scattermap(
    lat=sectores.lat, lon=sectores.lon, mode="markers+text",
    marker=dict(size=(sectores.poblacion / 600).clip(12, 40), color=sectores.cobertura,
                colorscale=[[i / (len(SEQ_BLUE) - 1), c] for i, c in enumerate(reversed(SEQ_BLUE))],
                cmin=0.3, cmax=1.0, opacity=0.8,
                colorbar=dict(title="Demanda<br>cubierta", tickformat=".0%")),
    text=sectores.nombre, textposition="top center",
    customdata=sectores[["poblacion", "cobertura", "lhd"]].to_numpy(),
    hovertemplate="<b>%{text}</b><br>%{customdata[0]:,.0f} hab.<br>Cobertura: %{customdata[1]:.0%}"
                  "<br>%{customdata[2]:.0f} l/hab/día<extra></extra>",
    name="Sectores",
))
fig.add_trace(go.Scattermap(
    lat=p.lat, lon=p.lon, mode="markers",
    marker=dict(size=12, color=p.color),
    text=p.index, customdata=p[["estado", "caudal_nominal_lps"]].to_numpy(),
    hovertemplate="<b>Pozo %{text}</b><br>%{customdata[0]}<br>%{customdata[1]:.0f} l/s nominal<extra></extra>",
    name="Pozos",
))
sin_base = st.toggle("Sin mapa base (si no carga el fondo por falta de internet)", value=False)
fig.update_layout(map=dict(style="white-bg" if sin_base else "carto-positron", center=dict(lat=24.125, lon=-110.315), zoom=11.6),
                  height=620, margin=dict(l=0, r=0, t=0, b=0),
                  legend=dict(orientation="h", yanchor="bottom", y=0.01, x=0.01))
st.plotly_chart(fig, width="stretch")
st.caption("Círculo = sector (tamaño ∝ habitantes, más oscuro = peor cobertura). Punto = pozo, con color de "
           "estado: ✅ normal · ⚠️ atención · 🔶 alerta · ⛔ crítico (detalle en la tabla).")

c1, c2 = st.columns(2)
c1.subheader("Sectores con menor cobertura")
c1.dataframe(sectores.sort_values("cobertura")[["nombre", "poblacion", "cobertura", "lhd"]].head(8)
             .rename(columns={"nombre": "Sector", "poblacion": "Habitantes", "cobertura": "Cobertura",
                              "lhd": "l/hab/día"}),
             width="stretch",
             column_config={"Cobertura": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
                            "l/hab/día": st.column_config.NumberColumn(format="%.0f")})
c2.subheader("Pozos que requieren atención")
c2.dataframe(p.sort_values("riesgo", ascending=False)[["estado", "riesgo", "sectores"]].head(8),
             width="stretch")
