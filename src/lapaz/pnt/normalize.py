"""Normaliza datos del SIPOT / Plataforma Nacional de Transparencia.

Sirve tanto para respuestas JSON capturadas por el scraper como para los archivos
XLSX/CSV que se descargan a mano desde la consulta pública. Los formatos del SIPOT traen
renglones de metadatos (título, nombre corto, ids de campo) antes del encabezado real; el
encabezado se detecta buscando la columna "Ejercicio", común a todos los formatos.
"""

from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path

import pandas as pd

# Palabras clave para clasificar contratos/gastos relacionados con la operación hidráulica.
CATEGORIAS = {
    "pozos_y_bombas": r"pozo|bomba|equipo de bombeo|motor|rebobinad|perforaci",
    "pipas": r"pipa|carro ?tanque|acarreo de agua",
    "energia": r"\bcfe\b|energ[ií]a el[eé]ctrica|comisi[oó]n federal de electricidad|subestaci",
    "redes_y_fugas": r"fuga|tuber[ií]a|red de (?:agua|distribuci)|rehabilitaci[oó]n de (?:la )?red|v[aá]lvula",
    "medicion": r"medidor|micromedici|macromedici|telemetr|scada|caudal[ií]metro",
    "potabilizacion": r"potabiliza|desaladora|desalinizadora|cloro|hipoclorito|[oó]smosis",
    "drenaje_saneamiento": r"drenaje|alcantarill|saneamiento|planta de tratamiento|aguas residuales",
}

AMOUNT_HINTS = ("monto", "importe", "total", "precio", "costo")
DATE_HINTS = ("fecha",)


def snake(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    return s[:80] or "col"


def _dedupe(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out


def find_header_row(raw: pd.DataFrame, max_rows: int = 30) -> int:
    for i in range(min(max_rows, len(raw))):
        vals = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "ejercicio" in vals:
            return i
    return 0


def read_sipot_file(path_or_buffer, name: str | None = None) -> pd.DataFrame:
    """Lee un XLSX/CSV del SIPOT y regresa un DataFrame con encabezados limpios."""
    name = name or str(path_or_buffer)
    if name.lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(path_or_buffer, header=None, dtype=str)
    else:
        data = path_or_buffer.read() if hasattr(path_or_buffer, "read") else Path(path_or_buffer).read_bytes()
        text = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        raw = pd.read_csv(io.StringIO(text), header=None, dtype=str)
    h = find_header_row(raw)
    df = raw.iloc[h + 1:].reset_index(drop=True)
    df.columns = _dedupe([snake(c) for c in raw.iloc[h].tolist()])
    df = df.dropna(how="all")
    return coerce_types(df)


def records_from_json(payload) -> list[dict]:
    """Encuentra la lista de registros más grande dentro de una respuesta JSON arbitraria."""
    best: list[dict] = []

    def walk(node):
        nonlocal best
        if isinstance(node, list) and node and all(isinstance(x, dict) for x in node):
            if len(node) > len(best):
                best = node
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)

    walk(payload)
    return best


def _is_text(s: pd.Series) -> bool:
    return not (pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s)
                or pd.api.types.is_bool_dtype(s))


def coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if not _is_text(out[c]):
            continue
        if any(h in c for h in AMOUNT_HINTS):
            nums = pd.to_numeric(out[c].astype(str).str.replace(r"[$,\s]", "", regex=True), errors="coerce")
            if nums.notna().mean() > 0.5:
                out[c] = nums
        elif any(h in c for h in DATE_HINTS):
            dates = pd.to_datetime(out[c], errors="coerce", dayfirst=True)
            if dates.notna().mean() > 0.5:
                out[c] = dates
    return out


def records_to_frame(records: list[dict]) -> pd.DataFrame:
    df = pd.json_normalize(records)
    df.columns = _dedupe([snake(c) for c in df.columns])
    return coerce_types(df)


def text_blob(df: pd.DataFrame) -> pd.Series:
    obj = df[[c for c in df.columns if _is_text(df[c])]]
    if obj.empty:
        return pd.Series("", index=df.index)
    return obj.fillna("").astype(str).agg(" ".join, axis=1).str.lower()


def categorize(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega columna ``categoria`` con la primera categoría hidráulica que coincida."""
    out = df.copy()
    blob = text_blob(out)
    out["categoria"] = "otros"
    for cat, pattern in reversed(list(CATEGORIAS.items())):
        out.loc[blob.str.contains(pattern, regex=True), "categoria"] = cat
    return out


def amount_column(df: pd.DataFrame) -> str | None:
    """Columna de monto más probable (la numérica con mayor suma entre las que parecen montos)."""
    cands = [c for c in df.columns if any(h in c for h in AMOUNT_HINTS) and pd.api.types.is_numeric_dtype(df[c])]
    if not cands:
        return None
    return max(cands, key=lambda c: df[c].abs().sum())


def save(df: pd.DataFrame, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{snake(name)}.parquet"
    df.astype({c: str for c in df.columns if _is_text(df[c])}).to_parquet(path, index=False)
    return path
