import io

import pandas as pd

from lapaz.pnt.normalize import amount_column, categorize, read_sipot_file, records_from_json, snake
from lapaz.pnt.scrape import find_page_key, next_params


def _sipot_xlsx() -> io.BytesIO:
    """Imita un formato del SIPOT: renglones de metadatos antes del encabezado real."""
    rows = [
        ["43335", None, None, None],
        ["TITULO", "NOMBRE CORTO", "DESCRIPCION", None],
        ["Contratos", "LTAIPBCS", "Procedimientos de adjudicación", None],
        ["1", "4", "9", "6"],
        ["Tabla Campos", None, None, None],
        ["Ejercicio", "Fecha de inicio del periodo que se informa", "Descripción de las obras",
         "Monto total del contrato"],
        ["2026", "01/01/2026", "Mantenimiento de bomba sumergible pozo 17R", "$1,250,000.00"],
        ["2026", "01/01/2026", "Renta de pipas para abasto en colonias", "980,000"],
        ["2026", "01/04/2026", "Papelería", "15,000"],
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    buf.seek(0)
    return buf


def test_read_sipot_detects_header_and_types():
    df = read_sipot_file(_sipot_xlsx(), "contratos.xlsx")
    assert list(df.columns)[:2] == ["ejercicio", "fecha_de_inicio_del_periodo_que_se_informa"]
    assert len(df) == 3
    assert df.monto_total_del_contrato.sum() == 2_245_000
    assert pd.api.types.is_datetime64_any_dtype(df.fecha_de_inicio_del_periodo_que_se_informa)


def test_categorize_contracts():
    df = categorize(read_sipot_file(_sipot_xlsx(), "contratos.xlsx"))
    assert df.categoria.tolist() == ["pozos_y_bombas", "pipas", "otros"]
    assert amount_column(df) == "monto_total_del_contrato"


def test_records_from_nested_json():
    payload = {"meta": {"total": 2}, "data": {"items": [{"a": 1}, {"a": 2}], "otros": [{"b": 1}]}}
    assert records_from_json(payload) == [{"a": 1}, {"a": 2}]


def test_pagination_helpers():
    assert find_page_key({"idSujeto": 782, "pagina": 1}) == "pagina"
    assert next_params({"pagina": 1}, "pagina", 50)["pagina"] == 2
    assert next_params({"start": 0}, "start", 50)["start"] == 50
    assert snake("Fecha de término del periodo") == "fecha_de_termino_del_periodo"
