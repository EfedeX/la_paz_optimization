"""Descubrimiento de endpoints de la consulta pública de la PNT con Playwright.

La consulta pública es una aplicación web que carga los datos por XHR. En lugar de
adivinar su API, abrimos la página como lo haría una persona, hacemos clic en cada
obligación/fracción y guardamos todas las respuestas JSON que pasan por la red. El
resultado (``discovery.json``) lo usa ``scrape.py`` para paginar sin navegador.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lapaz.pnt.normalize import records_from_json

DEFAULT_URL = "https://consultapublicamx.plataformadetransparencia.org.mx/buscar?entidad={entidad}&sujeto={sujeto}&ejercicio={ejercicio}"
USER_AGENT = "LaPazProactiva/0.1 (investigacion de datos publicos; contacto en README)"
HOST_HINT = "plataformadetransparencia"
# Texto típico de las obligaciones del SIPOT que vale la pena abrir primero.
CLICK_TEXT = re.compile(
    r"art[ií]culo|fracci[oó]n|contrat|adjudicaci|licitaci|gasto|presupuest|indicador|"
    r"estad[ií]stic|inventario|auditor|servicio|tr[aá]mite|programa|tarifa|cuota|informe",
    re.I,
)
DOWNLOAD_TEXT = re.compile(r"descargar|exportar|excel|xlsx|csv", re.I)


@dataclass
class Captured:
    label: str
    url: str
    method: str
    post_data: str | None
    status: int
    n_records: int
    keys: list[str] = field(default_factory=list)
    file: str = ""


def _chromium_path() -> str | None:
    p = os.environ.get("PNT_CHROMIUM") or "/opt/pw-browsers/chromium"
    return p if Path(p).exists() and Path(p).is_file() else None


def discover(entidad: int, sujeto: int, ejercicio: int, out_dir: Path, max_clicks: int = 80,
             headless: bool = True, pause_s: float = 1.0, download: bool = True) -> list[Captured]:
    from playwright.sync_api import sync_playwright

    raw_dir = out_dir / "raw" / str(ejercicio)
    raw_dir.mkdir(parents=True, exist_ok=True)
    captured: list[Captured] = []
    current = {"label": "inicio"}

    def on_response(resp):
        if HOST_HINT not in resp.url:
            return
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype:
            return
        try:
            payload = resp.json()
        except Exception:
            return
        recs = records_from_json(payload)
        digest = hashlib.sha1((resp.url + (resp.request.post_data or "")).encode()).hexdigest()[:12]
        fname = raw_dir / f"{digest}.json"
        fname.write_text(json.dumps(payload, ensure_ascii=False))
        captured.append(Captured(
            label=current["label"], url=resp.url, method=resp.request.method,
            post_data=resp.request.post_data, status=resp.status, n_records=len(recs),
            keys=sorted(recs[0].keys())[:40] if recs else [], file=str(fname),
        ))

    url = DEFAULT_URL.format(entidad=entidad, sujeto=sujeto, ejercicio=ejercicio)
    with sync_playwright() as pw:
        kwargs = {"headless": headless}
        if _chromium_path():
            kwargs["executable_path"] = _chromium_path()
        browser = pw.chromium.launch(**kwargs)
        ctx = browser.new_context(user_agent=USER_AGENT, accept_downloads=True, locale="es-MX")
        page = ctx.new_page()
        page.on("response", on_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=90_000)
        except Exception as exc:
            browser.close()
            raise RuntimeError(
                f"No se pudo abrir {url}: {exc}. Revisa tu conexión o si la red permite ese dominio."
            ) from exc
        time.sleep(pause_s)

        seen: set[str] = set()
        clicks = 0
        while clicks < max_clicks:
            candidates = page.locator("a, button, [role=button], li, .card, .list-group-item")
            target = None
            for i in range(min(candidates.count(), 600)):
                el = candidates.nth(i)
                try:
                    text = (el.inner_text(timeout=500) or "").strip()
                except Exception:
                    continue
                key = text[:120]
                if not text or len(text) > 200 or key in seen or not CLICK_TEXT.search(text):
                    continue
                if not el.is_visible():
                    continue
                target, seen_key = el, key
                break
            if target is None:
                break
            seen.add(seen_key)
            current["label"] = seen_key
            before = page.url
            try:
                target.click(timeout=5_000)
                page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            time.sleep(pause_s)
            if download:
                _try_downloads(page, raw_dir / "descargas", seen_key)
            if page.url != before:
                page.go_back(wait_until="networkidle")
            clicks += 1

        ctx.storage_state(path=str(out_dir / "storage_state.json"))
        browser.close()

    (out_dir / "discovery.json").write_text(
        json.dumps([asdict(c) for c in captured], ensure_ascii=False, indent=2)
    )
    return captured


def _try_downloads(page, dest: Path, label: str) -> None:
    buttons = page.locator("a, button").filter(has_text=DOWNLOAD_TEXT)
    for i in range(min(buttons.count(), 3)):
        try:
            with page.expect_download(timeout=20_000) as dl:
                buttons.nth(i).click(timeout=5_000)
            dest.mkdir(parents=True, exist_ok=True)
            d = dl.value
            safe = re.sub(r"[^\w.-]+", "_", f"{label[:50]}_{d.suggested_filename}")
            d.save_as(dest / safe)
        except Exception:
            continue
