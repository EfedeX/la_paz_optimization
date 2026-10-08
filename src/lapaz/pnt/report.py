"""Resumen de lo encontrado en la PNT y qué falta pedir por solicitud de información."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from lapaz.pnt.normalize import amount_column, categorize

FALTANTES = [
    "Bitácoras de operación por pozo (horas de bombeo, caudal, presión) de los últimos 3 años.",
    "Recibos de CFE por pozo/servicio (kWh y monto mensual) — permiten estimar caudal y eficiencia.",
    "Programa de tandeo vigente por colonia/sector y su histórico de cambios.",
    "Reportes ciudadanos de falta de agua y fugas por colonia (fecha, ubicación, tiempo de atención).",
    "Catálogo de pozos con ubicación, profundidad, nivel estático/dinámico y fecha de última rehabilitación.",
    "Volumen anual concesionado vs. extraído por pozo (títulos REPDA ante CONAGUA).",
    "Gasto anual en pipas (contratos y litros entregados) por colonia.",
]


def load_tables(tables_dir: Path) -> dict[str, pd.DataFrame]:
    return {p.stem: pd.read_parquet(p) for p in sorted(tables_dir.glob("*.parquet"))}


def build_report(tables: dict[str, pd.DataFrame]) -> str:
    lines = ["# Hallazgos: OOMSAPAS La Paz en la Plataforma Nacional de Transparencia", ""]
    if not tables:
        lines += ["No hay tablas descargadas todavía. Corre `python -m lapaz.pnt discover` o "
                  "`python -m lapaz.pnt ingest <carpeta>` con los XLSX bajados de la PNT.", ""]
    else:
        lines += ["| Tabla | Registros | Columnas | Monto relacionado con agua (MXN) |", "|---|---:|---:|---:|"]
        cat_totals = []
        for name, df in tables.items():
            df = categorize(df)
            col = amount_column(df)
            agua = df[df.categoria != "otros"]
            monto = agua[col].sum() if col else float("nan")
            lines.append(f"| {name} | {len(df):,} | {df.shape[1]} | {monto:,.0f} |")
            if col:
                cat_totals.append(df.groupby("categoria")[col].agg(["count", "sum"]))
        if cat_totals:
            tot = pd.concat(cat_totals).groupby(level=0).sum().sort_values("sum", ascending=False)
            lines += ["", "## Gasto por categoría hidráulica", "", "| Categoría | Registros | Monto (MXN) |",
                      "|---|---:|---:|"]
            lines += [f"| {c} | {int(r['count']):,} | {r['sum']:,.0f} |" for c, r in tot.iterrows()]
            lines += ["", "Pregunta clave para el pitch: ¿cuánto se gasta en **pipas** y reparaciones "
                      "de emergencia vs. **mantenimiento preventivo** y **medición**?"]
    lines += ["", "## Datos que no se publican y conviene solicitar (PNT → Solicitudes)", ""]
    lines += [f"- {x}" for x in FALTANTES]
    return "\n".join(lines) + "\n"
