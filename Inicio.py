import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

from lapaz.data.public import (  # noqa: E402
    CAPACIDAD_TOTAL_LPS, DOTACION_ESTIMADA_LHD, PERDIDAS_ESTIMADAS, POZOS_MUNICIPIO,
)
from lapaz.ui import get_eval, get_sectores  # noqa: E402

st.set_page_config(page_title="La Paz Proactiva", page_icon="💧", layout="wide")

st.title("💧 La Paz Proactiva")
st.markdown(
    "#### De apagar incendios a prevenirlos: datos y modelos para el agua de La Paz, BCS"
)
st.markdown(
    """
Hoy el agua en La Paz se gestiona **reaccionando**: las bombas se prenden y apagan con
bitácoras manuales, una falla en un pozo se descubre cuando las colonias ya se quedaron sin
agua, y el tandeo se ajusta por intuición. Este prototipo muestra cómo cambiar eso con
herramientas baratas y de código abierto:
"""
)

sectores = get_sectores()
_, resumen = get_eval()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Pozos en el municipio", f"{POZOS_MUNICIPIO}", help="Director de OOMSAPAS, 2026")
c2.metric("Capacidad reportada", f"{CAPACIDAD_TOTAL_LPS:,.0f} l/s", help="Tercer Informe 2024")
c3.metric("Pérdidas estimadas por fugas", f"{PERDIDAS_ESTIMADAS:.0%}", help="Exdirector de OOMSAPAS")
c4.metric("Anticipación de fallas (simulado)", f"{resumen['anticipacion_mediana_graduales']:.0f} días",
          help="Mediana de días de aviso antes de que un pozo deje de funcionar, en fallas graduales simuladas")

st.markdown(
    f"""
| Módulo | Pregunta que responde | Tipo de datos |
|---|---|---|
| **1 · Alerta temprana de pozos** | ¿Qué pozo va a fallar y con cuántos días de aviso? | 🧪 Telemetría simulada |
| **2 · Demanda de agua** | ¿Cuánta agua necesitará cada sector en las próximas 2 semanas? | 🧪 Simulada, calibrada con población y clima |
| **3 · Tandeo optimizado** | ¿Cómo repartir el agua disponible de forma más justa? | Capacidad pública + modelo |
| **4 · Mapa de la ciudad** | ¿Dónde está el déficit y qué pozos están en riesgo? | Aproximación por sector |
| **5 · Transparencia OOMSAPAS** | ¿Qué publica el organismo y en qué gasta? | 📊 Datos públicos de la PNT |

**Honestidad ante todo:** OOMSAPAS no publica telemetría de sus bombas ni micromedición, así
que los módulos 1 y 2 usan datos simulados con fallas inyectadas y etiquetadas. El código está
listo para conectarse a datos reales (SCADA, bitácoras o recibos de CFE) en cuanto existan.
Las cifras públicas usadas: {POZOS_MUNICIPIO} pozos, {CAPACIDAD_TOTAL_LPS:,.0f} l/s, ~{DOTACION_ESTIMADA_LHD} l/hab/día,
~{PERDIDAS_ESTIMADAS:.0%} de pérdidas; {len(sectores)} sectores aproximados con {sectores.poblacion.sum():,} habitantes.

👈 Usa el menú lateral para recorrer los módulos.
"""
)
