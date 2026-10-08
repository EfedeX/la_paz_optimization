import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from lapaz.data.public import PERDIDAS_ESTIMADAS  # noqa: E402
from lapaz.optimize.tandeo import reparto_fijo, reparto_optimo, resumen  # noqa: E402
from lapaz.ui import NEUTRAL, PLOT_LAYOUT, SERIES, get_demanda, get_pozos, get_sectores, publico  # noqa: E402

st.set_page_config(page_title="Tandeo optimizado", page_icon="🔀", layout="wide")
st.title("🔀 Tandeo optimizado: repartir mejor el agua que sí hay")
publico("capacidad")
publico("perdidas")
st.caption("🧪 Red pozo→sector y demanda por sector: simuladas/aproximadas.")

pozos, _, _, alerts = get_pozos()
_, _, _, fut = get_demanda()
sectores = get_sectores().set_index("sector_id")

ultimo = alerts[alerts.fecha == alerts.fecha.max()]
en_alerta = sorted(ultimo.loc[ultimo.alerta, "pozo_id"])

c1, c2 = st.columns([1, 2])
perdidas = c1.slider("Pérdidas por fugas", 0.0, 0.6, PERDIDAS_ESTIMADAS, 0.05, format="%.2f",
                     help="Reducir fugas es la forma más barata de 'producir' agua.")
fuera = c2.multiselect("Pozos fuera de servicio (por defecto: los que el sistema marcó en alerta)",
                       pozos.pozo_id, default=en_alerta)
umbral = st.slider("Cobertura mínima aceptable por sector", 0.5, 1.0, 0.7, 0.05, format="%.2f")

demanda = fut[fut.fecha == fut.fecha.min()].set_index("sector_id").pred_m3.reindex(sectores.index)
pob = sectores.poblacion
fijo = reparto_fijo(pozos, demanda, perdidas, set(fuera))
opt, flujos = reparto_optimo(pozos, demanda, perdidas, set(fuera))
rf, ro = resumen(demanda, fijo, pob, umbral), resumen(demanda, opt, pob, umbral)

k1, k2, k3 = st.columns(3)
k1.metric("Cobertura del sector peor atendido", f"{ro['cobertura_minima']:.0%}",
          f"{(ro['cobertura_minima'] - rf['cobertura_minima']) * 100:+.0f} pts vs. reparto fijo")
k2.metric("Agua entregada", f"{ro['entregado_m3']:,.0f} m³/día",
          f"{ro['entregado_m3'] - rf['entregado_m3']:+,.0f} m³/día")
k3.metric(f"Sectores bajo {umbral:.0%} de cobertura", ro["sectores_bajo_umbral"],
          f"{ro['sectores_bajo_umbral'] - rf['sectores_bajo_umbral']:+d}", delta_color="inverse")

comp = pd.DataFrame({
    "sector": [f"{s} · {sectores.nombre[s]}" for s in demanda.index],
    "Reparto fijo": (fijo / demanda).values,
    "Optimizado": (opt / demanda).values,
}).sort_values("Optimizado")
fig = go.Figure()
fig.add_trace(go.Bar(y=comp.sector, x=comp["Reparto fijo"], name="Reparto fijo (actual)", orientation="h",
                     marker=dict(color=NEUTRAL, line=dict(color="white", width=2))))
fig.add_trace(go.Bar(y=comp.sector, x=comp["Optimizado"], name="Optimizado", orientation="h",
                     marker=dict(color=SERIES[0], line=dict(color="white", width=2))))
fig.add_vline(x=umbral, line=dict(color=SERIES[1], dash="dash", width=2),
              annotation_text=f"umbral {umbral:.0%}")
fig.update_layout(barmode="group", height=560, xaxis=dict(tickformat=".0%", title="Demanda cubierta"),
                  **{**PLOT_LAYOUT, "hovermode": "y unified"})
st.plotly_chart(fig, width="stretch")

limitados = comp[comp.Optimizado < umbral].sector.tolist()
if limitados:
    st.info(
        "🔧 **Hallazgo de infraestructura:** aun con el reparto óptimo, estos sectores no alcanzan el "
        f"umbral porque los pozos conectados a ellos no dan más: {', '.join(limitados)}. "
        "La solución ahí no es operativa sino de obra (interconexión, tanque o pozo nuevo) — y el "
        "modelo dice exactamente dónde invertir."
    )

with st.expander("Plan de bombeo sugerido (m³/día por pozo → sector)"):
    st.dataframe(flujos.assign(sector=flujos.sector_id.map(sectores.nombre)).round(0),
                 hide_index=True, width="stretch")

with st.expander("¿Cómo funciona?"):
    st.markdown(
        """
Programación lineal en dos etapas (`scipy.optimize.linprog`, solver HiGHS):

1. **Equidad:** maximizar la cobertura del sector peor atendido, respetando la capacidad de cada
   pozo, las pérdidas y qué sectores puede abastecer cada pozo.
2. **Eficiencia:** con esa equidad garantizada, maximizar el agua total entregada.

El **reparto fijo** imita la práctica actual: cada pozo divide su agua en partes iguales y lo que
le sobra a un sector no se redirige. Conectado al módulo de alertas, el plan se recalcula en
cuanto un pozo sale de servicio.
"""
    )
