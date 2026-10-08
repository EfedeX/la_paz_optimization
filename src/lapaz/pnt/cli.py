"""Uso:

    python -m lapaz.pnt discover --ejercicio 2026        # abre la PNT, captura endpoints y descargas
    python -m lapaz.pnt scrape                            # pagina los endpoints descubiertos → parquet
    python -m lapaz.pnt ingest ~/Descargas/pnt            # normaliza XLSX/CSV bajados a mano
    python -m lapaz.pnt report                            # escribe data/pnt/hallazgos.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lapaz.data.public import PNT_DIR
from lapaz.pnt.normalize import read_sipot_file, save
from lapaz.pnt.report import build_report, load_tables

OOMSAPAS_LA_PAZ = {"entidad": 3, "sujeto": 782}


def ingest_dir(src: Path, out_dir: Path) -> list[Path]:
    paths = []
    for f in sorted(src.rglob("*")):
        if f.suffix.lower() not in (".xlsx", ".xls", ".csv"):
            continue
        try:
            df = read_sipot_file(f, f.name)
        except Exception as exc:
            print(f"[pnt] no se pudo leer {f.name}: {exc}")
            continue
        df["fuente_label"] = f.stem
        paths.append(save(df, out_dir / "tablas", f.stem))
    return paths


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="lapaz.pnt", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=PNT_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover")
    d.add_argument("--entidad", type=int, default=OOMSAPAS_LA_PAZ["entidad"])
    d.add_argument("--sujeto", type=int, default=OOMSAPAS_LA_PAZ["sujeto"])
    d.add_argument("--ejercicio", type=int, nargs="+", default=[2026])
    d.add_argument("--max-clicks", type=int, default=80)
    d.add_argument("--headed", action="store_true", help="muestra el navegador")

    sc = sub.add_parser("scrape")
    sc.add_argument("--pause", type=float, default=1.0, help="segundos entre peticiones")

    i = sub.add_parser("ingest")
    i.add_argument("carpeta", type=Path)

    sub.add_parser("report")
    args = ap.parse_args(argv)

    if args.cmd == "discover":
        from lapaz.pnt.discover import discover

        for year in args.ejercicio:
            caps = discover(args.entidad, args.sujeto, year, args.out,
                            max_clicks=args.max_clicks, headless=not args.headed)
            useful = [c for c in caps if c.n_records]
            print(f"[pnt] {year}: {len(caps)} respuestas JSON, {len(useful)} con registros")
            for c in useful[:30]:
                print(f"   {c.n_records:>5}  {c.label[:60]!r}  {c.method} {c.url[:90]}")
            ingest_dir(args.out / "raw" / str(year) / "descargas", args.out)
    elif args.cmd == "scrape":
        from lapaz.pnt.scrape import scrape_all

        for p in scrape_all(args.out, pause_s=args.pause):
            print(f"[pnt] guardado {p}")
    elif args.cmd == "ingest":
        for p in ingest_dir(args.carpeta, args.out):
            print(f"[pnt] guardado {p}")
    elif args.cmd == "report":
        path = args.out / "hallazgos.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_report(load_tables(args.out / "tablas")), encoding="utf-8")
        print(f"[pnt] reporte en {path}")
