"""Datos públicos (o aproximaciones documentadas) de La Paz, BCS.

Todo lo que se carga aquí declara su procedencia en ``FUENTES`` para que el dashboard
pueda mostrarla. Cuando no hay acceso a la fuente oficial, se usan valores de muestra en
``data/sample`` marcados como aproximados; reemplázalos con la descarga oficial.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DIR = ROOT / "data" / "sample"
PNT_DIR = ROOT / "data" / "pnt"

# Cifras públicas usadas para calibrar el modelo.
CAPACIDAD_INICIAL_LPS = 716.4  # Tercer Informe 2024, Ayuntamiento de La Paz
INCREMENTO_LPS = 343.3  # idem
CAPACIDAD_TOTAL_LPS = CAPACIDAD_INICIAL_LPS + INCREMENTO_LPS
DOTACION_ESTIMADA_LHD = 300  # litros/hab/día estimados por OOMSAPAS (Zeta, 2026)
PERDIDAS_ESTIMADAS = 0.40  # fugas estimadas por exdirector de OOMSAPAS
POZOS_MUNICIPIO = 70

# Normales climatológicas aproximadas de La Paz (temperatura media mensual, °C).
# Fuente de referencia: normales SMN/CONAGUA estación La Paz; valores redondeados.
TEMP_MEDIA_MENSUAL = {
    1: 18.0, 2: 19.0, 3: 20.5, 4: 22.5, 5: 25.0, 6: 28.0,
    7: 30.0, 8: 30.5, 9: 29.5, 10: 27.0, 11: 23.0, 12: 19.5,
}

FUENTES = {
    "sectores": (
        "Aproximación: población por sector redondeada a partir del Censo 2020 (INEGI) y "
        "coordenadas aproximadas. Reemplazar con AGEB urbanas del Censo 2020."
    ),
    "clima": "Normales climatológicas aproximadas SMN/CONAGUA (La Paz) + variación simulada.",
    "capacidad": "Tercer Informe de Gobierno 2024, Ayuntamiento de La Paz (716.4 + 343.3 l/s).",
    "dotacion": "Declaraciones del director de OOMSAPAS (Zeta Tijuana, 2026): ~300 l/hab/día, ~70 pozos.",
    "perdidas": "Exdirector de OOMSAPAS: pérdidas cercanas al 40% por fugas.",
}


def load_sectores() -> pd.DataFrame:
    """Sectores hidráulicos aproximados de la ciudad de La Paz."""
    return pd.read_csv(SAMPLE_DIR / "sectores.csv")


def daily_temperature(dates: pd.DatetimeIndex, seed: int = 7) -> pd.Series:
    """Temperatura diaria: normal mensual interpolada + ruido autocorrelacionado."""
    rng = np.random.default_rng(seed)
    doy = dates.dayofyear.to_numpy()
    months = np.arange(1, 13)
    mid_doy = (months - 0.5) * 365.25 / 12
    temps = np.array([TEMP_MEDIA_MENSUAL[m] for m in months])
    # Interpolación circular para que diciembre conecte con enero.
    x = np.concatenate([mid_doy - 365.25, mid_doy, mid_doy + 365.25])
    y = np.concatenate([temps, temps, temps])
    base = np.interp(doy, x, y)
    noise = np.zeros(len(dates))
    for i in range(1, len(dates)):
        noise[i] = 0.7 * noise[i - 1] + rng.normal(0, 0.9)
    return pd.Series(base + noise, index=dates, name="temp_c")


def fetch_denue(keyword: str, lat: float, lon: float, radius_m: int = 1000) -> pd.DataFrame:
    """Consulta opcional a la API del DENUE (INEGI). Requiere ``INEGI_TOKEN`` en el entorno.

    Útil en fase 2 para estimar demanda comercial (hoteles, lavanderías, purificadoras).
    """
    import requests

    token = os.environ.get("INEGI_TOKEN")
    if not token:
        raise RuntimeError("Define INEGI_TOKEN (se obtiene gratis en inegi.org.mx/servicios/api_denue.html)")
    url = (
        "https://www.inegi.org.mx/app/api/denue/v1/consulta/Buscar/"
        f"{keyword}/{lat},{lon}/{radius_m}/{token}"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())
