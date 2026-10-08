import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from lapaz.data.public import PNT_DIR  # noqa: E402
from lapaz.pnt.normalize import amount_column, categorize, read_sipot_file  # noqa: E402
from lapaz.pnt.report import FALTANTES, load_tables  # noqa: E402
from lapaz.ui import PLOT_LAYOUT, SERIES  # noqa: E402

st.set_page_config(page_title="Transparencia OOMSAPAS", page_icon="🔎", layout="wide")
st.title("🔎 Transparencia: qué publica OOMSAPAS La Paz y en qué gasta")
st.markdown(
    "Datos de la [Plataforma Nacional de Transparencia]"
    "(https://consultapublicamx.plataformadetransparencia.org.mx/buscar?entidad=3&sujeto=782&ejercicio=2026) "
    "(sujeto obligado 782). Se cargan con el scraper (`python -m lapaz.pnt discover`) o subiendo aquí "
    "los XLSX/CSV que descargas de la PNT."
)

tablas = load_tables(PNT_DIR / "tablas")
subidos = st.file_uploader("Sube formatos descargados de la PNT (XLSX o CSV)", type=["xlsx", "xls", "csv"],
                           accept_multiple_files=True)
for f in subidos or []:
    try:
        tablas[Path(f.name).stem] = read_sipot_file(f, f.name)
    except Exception as exc:
        st.error(f"No se pudo leer {f.name}: {exc}")

if not tablas:
    st.info("Aún no hay datos de la PNT. Corre el scraper o sube archivos para ver el análisis.")
else:
    nombre = st.selectbox("Tabla", list(tablas))
    df = categorize(tablas[nombre])
    col = amount_column(df)
    k1, k2, k3 = st.columns(3)
    k1.metric("Registros", f"{len(df):,}")
    k2.metric("Relacionados con agua", f"{(df.categoria != 'otros').sum():,}")
    if col:
        k3.metric("Monto relacionado con agua", f"${df.loc[df.categoria != 'otros', col].sum():,.0f}")
        agg = df.groupby("categoria")[col].sum().sort_values()
        fig = go.Figure(go.Bar(x=agg.values, y=agg.index, orientation="h",
                               marker=dict(color=SERIES[0]),
                               hovertemplate="%{y}: $%{x:,.0f}<extra></extra>"))
        fig.update_layout(height=360, xaxis_title=f"Suma de {col} (MXN)",
                          **{**PLOT_LAYOUT, "hovermode": "closest"})
        st.plotly_chart(fig, width="stretch")
        st.caption("Pregunta clave: ¿cuánto se va en **pipas** y reparaciones de emergencia frente a "
                   "**mantenimiento preventivo** y **medición**?")
    cats = st.multiselect("Filtrar por categoría", sorted(df.categoria.unique()))
    vista = df[df.categoria.isin(cats)] if cats else df
    st.dataframe(vista, width="stretch", height=420)
    st.download_button("Descargar CSV limpio", vista.to_csv(index=False).encode("utf-8"),
                       file_name=f"{nombre}_limpio.csv", mime="text/csv")

st.subheader("Lo que no se publica y conviene pedir por solicitud de información")
st.markdown("\n".join(f"- {x}" for x in FALTANTES))
st.caption("Las solicitudes de información en la PNT son gratuitas. Con estas bitácoras, los módulos 1 a 3 "
           "pasan de simulados a reales.")
