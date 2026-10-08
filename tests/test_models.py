import pandas as pd
import pytest

from lapaz.data.simulate import SimConfig, simulate
from lapaz.models.anomaly import daily_features, detect, evaluate
from lapaz.models.demand import backtest, simulate_demand
from lapaz.optimize.tandeo import reparto_fijo, reparto_optimo, resumen


@pytest.fixture(scope="module")
def sim():
    return simulate(SimConfig(dias=150, seed=5))


def test_simulation_is_deterministic(sim):
    pozos, tel, events = sim
    _, tel2, events2 = simulate(SimConfig(dias=150, seed=5))
    pd.testing.assert_frame_equal(tel, tel2)
    pd.testing.assert_frame_equal(events, events2)
    assert pozos.caudal_nominal_lps.sum() == pytest.approx(1059.7, abs=0.5)


def test_detector_finds_injected_faults(sim):
    _, tel, events = sim
    alerts = detect(daily_features(tel))
    res, summary = evaluate(alerts, events)
    assert summary["recall"] >= 0.8
    assert summary["tasa_falsas_alarmas"] < 0.02
    graduales = res[res.tipo == "abatimiento"]
    assert (graduales.dias_anticipacion > 3).all(), "debe avisar días antes de que el pozo falle"


def test_demand_model_beats_naive():
    _, metrics = backtest(simulate_demand(dias=500))
    assert metrics["mape_modelo"] < metrics["mape_ingenuo"]


def test_lp_is_feasible_and_fairer(sim):
    pozos = sim[0]
    from lapaz.data.public import load_sectores

    sectores = load_sectores().set_index("sector_id")
    demanda = sectores.poblacion * 0.3  # m³/día
    fijo = reparto_fijo(pozos, demanda, 0.4)
    opt, flujos = reparto_optimo(pozos, demanda, 0.4)
    assert (opt <= demanda + 1e-6).all()
    assert resumen(demanda, opt, sectores.poblacion)["cobertura_minima"] >= \
        resumen(demanda, fijo, sectores.poblacion)["cobertura_minima"] - 1e-9
    # Ningún pozo entrega más que su capacidad.
    cap = pozos.set_index("pozo_id").eval("caudal_nominal_lps * 3.6 * horas_bombeo * 0.6")
    assert (flujos.groupby("pozo_id").m3_dia.sum() <= cap.reindex(flujos.pozo_id.unique()) + 1e-6).all()
