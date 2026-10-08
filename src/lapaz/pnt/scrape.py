"""Repite (sin navegador) las peticiones descubiertas y pagina hasta agotar los registros."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
import requests

from lapaz.pnt.discover import USER_AGENT
from lapaz.pnt.normalize import records_from_json, records_to_frame, save

PAGE_KEYS = ("pagina", "page", "numeroPagina", "numPagina", "pageNumber", "start", "offset", "inicio", "desde")


def find_page_key(params: dict) -> str | None:
    lowered = {k.lower(): k for k in params}
    for k in PAGE_KEYS:
        if k.lower() in lowered:
            return lowered[k.lower()]
    return None


def next_params(params: dict, key: str, page_size: int) -> dict:
    """Siguiente página: los parámetros tipo offset avanzan por tamaño de página, el resto en 1."""
    nxt = dict(params)
    cur = int(float(params[key] or 0))
    step = page_size if key.lower() in ("start", "offset", "inicio", "desde") else 1
    nxt[key] = cur + step
    return nxt


def _session(out_dir: Path) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    state = out_dir / "storage_state.json"
    if state.exists():
        for c in json.loads(state.read_text()).get("cookies", []):
            s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
    return s


def _send(s: requests.Session, method: str, url: str, body, as_json: bool):
    if method.upper() == "GET":
        return s.get(url, timeout=60)
    if as_json:
        return s.post(url, json=body, timeout=60)
    return s.post(url, data=body, timeout=60)


def scrape_endpoint(s: requests.Session, cap: dict, max_pages: int = 500, pause_s: float = 1.0) -> pd.DataFrame:
    method, url, post = cap["method"], cap["url"], cap.get("post_data")
    as_json = False
    params: dict = {}
    if method.upper() == "GET":
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query))
    elif post:
        try:
            params, as_json = json.loads(post), True
        except json.JSONDecodeError:
            params = dict(parse_qsl(post))
    if not isinstance(params, dict):
        params = {}
    key = find_page_key(params)

    all_recs: list[dict] = []
    seen_first: set[str] = set()
    for _ in range(max_pages):
        if method.upper() == "GET":
            parts = urlsplit(url)
            req_url = urlunsplit(parts._replace(query=urlencode(params)))
            resp = _send(s, "GET", req_url, None, False)
        else:
            resp = _send(s, method, url, params, as_json)
        resp.raise_for_status()
        recs = records_from_json(resp.json())
        if not recs:
            break
        fingerprint = json.dumps(recs[0], sort_keys=True, ensure_ascii=False)
        if fingerprint in seen_first:  # el servidor ignoró la paginación
            break
        seen_first.add(fingerprint)
        all_recs.extend(recs)
        if key is None:
            break
        params = next_params(params, key, len(recs))
        time.sleep(pause_s)
    return records_to_frame(all_recs) if all_recs else pd.DataFrame()


def scrape_all(out_dir: Path, min_records: int = 1, pause_s: float = 1.0) -> list[Path]:
    caps = json.loads((out_dir / "discovery.json").read_text())
    useful = [c for c in caps if c["n_records"] >= min_records and c["status"] == 200]
    # Una sola vez por endpoint+payload.
    unique = {(c["url"], c.get("post_data")): c for c in useful}.values()
    s = _session(out_dir)
    paths = []
    for cap in unique:
        try:
            df = scrape_endpoint(s, cap, pause_s=pause_s)
        except Exception as exc:  # seguimos con los demás endpoints
            print(f"[pnt] falló {cap['label']!r}: {exc}")
            continue
        if not df.empty:
            df["fuente_label"] = cap["label"]
            paths.append(save(df, out_dir / "tablas", cap["label"] or "sin_nombre"))
    return paths
