"""
M1 — Ingesta i CLI.
Renderitza la pàgina amb Playwright (o fallback requests+BS4).
Genera page_raw.html, screenshot.png i perf.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import requests

from .utils import base_metadata, slug_from_url, timestamp

log = logging.getLogger("aci_pipeline.m1")

AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"

_AXE_JS_CACHE: str | None = None


def _get_axe_js() -> str:
    """Baixa i fa caché del JS d'axe-core."""
    global _AXE_JS_CACHE
    if _AXE_JS_CACHE is None:
        try:
            resp = requests.get(AXE_CDN, timeout=15)
            resp.raise_for_status()
            _AXE_JS_CACHE = resp.text
        except Exception as exc:
            log.warning("No s'ha pogut baixar axe-core: %s. S'usarà stub buit.", exc)
            _AXE_JS_CACHE = ""
    return _AXE_JS_CACHE


async def _render_playwright(
    url: str,
    output_dir: Path,
    slug: str,
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    """Renderitza la URL amb Playwright i captura HTML, screenshot i mètriques."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("Playwright no disponible; usant fallback HTTP.")
        return await _render_fallback(url, output_dir, slug)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="aci_pipeline/0.1")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception as exc:
            log.warning("Timeout/error Playwright per %s: %s", url, exc)
            await browser.close()
            return await _render_fallback(url, output_dir, slug)

        html_content = await page.content()

        # Mètriques de rendiment via JS
        perf: dict[str, Any] = {}
        try:
            perf = await page.evaluate("""() => {
                const nav = performance.getEntriesByType('navigation')[0] || {};
                const lcp_entries = performance.getEntriesByType('largest-contentful-paint');
                const lcp = lcp_entries.length ? lcp_entries[lcp_entries.length-1].startTime : null;
                return {
                    ttfb: nav.responseStart || null,
                    dom_content_loaded: nav.domContentLoadedEventEnd || null,
                    load_event: nav.loadEventEnd || null,
                    lcp: lcp,
                    total_bytes: nav.transferSize || null
                };
            }""")
        except Exception as exc:
            log.warning("Error capturant mètriques de rendiment: %s", exc)

        # Screenshot full-page
        screenshot_path = output_dir / f"{slug}_screenshot.png"
        try:
            await page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception as exc:
            log.warning("Error capturant screenshot: %s", exc)
            screenshot_path = None

        # Axe-core audit
        axe_result: dict[str, Any] = {}
        axe_js = _get_axe_js()
        if axe_js:
            try:
                await page.evaluate(axe_js)
                axe_result = await page.evaluate("async () => await axe.run()")
            except Exception as exc:
                log.warning("Error executant axe-core: %s", exc)

        await browser.close()

    return {
        "html": html_content,
        "perf": perf,
        "screenshot_path": str(screenshot_path) if screenshot_path else None,
        "axe_result": axe_result,
        "mode": "playwright",
    }


async def _render_fallback(
    url: str, output_dir: Path, slug: str
) -> dict[str, Any]:
    """Fallback amb requests per a entorns sense Playwright."""
    log.info("Fallback HTTP per %s", url)
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "aci_pipeline/0.1"})
        resp.raise_for_status()
        html_content = resp.text
        perf = {"ttfb": None, "lcp": None, "total_bytes": len(resp.content)}
    except Exception as exc:
        log.error("Error HTTP per %s: %s", url, exc)
        html_content = f"<html><body>Error: {exc}</body></html>"
        perf = {}

    return {
        "html": html_content,
        "perf": perf,
        "screenshot_path": None,
        "axe_result": {},
        "mode": "fallback",
    }


def ingest_url(
    url: str,
    data_dir: Path = Path("data"),
    keep_history: bool = False,
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    """
    Punt d'entrada principal de M1.
    Renderitza la URL i desa artefactes a data_dir.
    Retorna un dict amb html, perf, axe_result i metadades.
    """
    slug = slug_from_url(url)
    ts = timestamp()

    assets_dir = data_dir / "assets"
    metrics_dir = data_dir / "metrics"
    assets_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if keep_history:
        from datetime import datetime, timezone
        archive_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_dir = data_dir / "archive" / archive_ts
        archive_dir.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(_render_playwright(url, assets_dir, slug, timeout_ms))

    # Desa HTML
    html_path = assets_dir / f"{slug}_{ts}.html"
    html_path.write_text(result["html"], encoding="utf-8")

    # Desa mètriques de rendiment
    perf_path = metrics_dir / "perf"
    perf_path.mkdir(parents=True, exist_ok=True)
    perf_file = perf_path / f"{slug}_{ts}.json"
    perf_data = {**base_metadata(url), "perf": result["perf"]}
    perf_file.write_text(json.dumps(perf_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Desa audit axe
    audit_path = metrics_dir / "audit"
    audit_path.mkdir(parents=True, exist_ok=True)
    audit_file = audit_path / f"{slug}_{ts}.json"
    audit_file.write_text(
        json.dumps({**base_metadata(url), "axe": result["axe_result"]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log.info("M1 completat per %s (mode=%s)", url, result["mode"])

    return {
        "url": url,
        "slug": slug,
        "timestamp": ts,
        "html": result["html"],
        "perf": result["perf"],
        "axe_result": result["axe_result"],
        "screenshot_path": result.get("screenshot_path"),
        "mode": result["mode"],
        "html_path": str(html_path),
        "perf_path": str(perf_file),
        "audit_path": str(audit_file),
    }
