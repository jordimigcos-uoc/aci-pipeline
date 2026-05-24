#!/usr/bin/env python3
"""
scripts/export_charts.py
=========================
Exporta els gràfics D3.js del lloc estàtic ACI com a fitxers JPG/PNG.
Utilitza Playwright (headless Chromium).

Ús:
  python scripts/export_charts.py \
      --input  site_output/index.html \
      --output site_output/figures \
      [--width 1400] [--quality 90] [--format jpg]

Els fitxers generats es nomenen:
  <slug>_<chartname>.jpg   (o .png)

Si --slugs no s'especifica, s'usa "global" com a prefix.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print(
        "ERROR: playwright no instal·lat — pip install playwright && playwright install chromium",
        file=sys.stderr,
    )
    sys.exit(1)

log = logging.getLogger("export_charts")

# ── IDs dels contenidors dels gràfics D3 ─────────────────────────────────────
CHART_CONTAINERS = [
    ("chart-comparison",        "comparison"),
    ("chart-principles",        "principles"),
    ("chart-boxplot",           "boxplot"),
    ("chart-stacked",           "stacked"),
    ("chart-top10",             "top10"),
    ("chart-bottom10",          "bottom10"),
    ("chart-radar-readability", "radar_readability"),
    ("chart-heatmap",           "heatmap"),
    ("chart-lollipop",          "lollipop"),
    ("chart-scatter",           "scatter"),
    ("chart-impact-effort",     "impact_effort"),
]


async def _export(
    input_path: Path,
    output_dir: Path,
    prefix: str,
    width: int,
    quality: int,
    fmt: str,
) -> list[Path]:
    """Obre la pàgina HTML i exporta cada gràfic com a imatge."""
    url = input_path.resolve().as_uri()
    log.info("Carregant: %s", url)

    saved: list[Path] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": width, "height": 900})

        try:
            await page.goto(url, wait_until="networkidle", timeout=60_000)
        except Exception as exc:
            log.error("No s'ha pogut carregar la pàgina: %s", exc)
            await browser.close()
            return saved

        # Espera que D3 hagi dibuixat (almenys 1 SVG)
        try:
            await page.wait_for_selector("svg", timeout=15_000)
        except Exception:
            log.warning("No s'han detectat SVGs; pot ser que D3 no s'hagi carregat.")

        # Dona un marge extra per a les animacions D3
        await page.wait_for_timeout(1_500)

        for container_id, chart_name in CHART_CONTAINERS:
            locator = page.locator(f"#{container_id}")
            if await locator.count() == 0:
                log.debug("  Contenidor #%s no trobat; s'omet.", container_id)
                continue

            fname = output_dir / f"{prefix}_{chart_name}.{fmt}"
            try:
                screenshot_opts: dict = {"path": str(fname)}
                if fmt == "jpg" or fmt == "jpeg":
                    screenshot_opts["type"] = "jpeg"
                    screenshot_opts["quality"] = quality
                else:
                    screenshot_opts["type"] = "png"

                await locator.screenshot(**screenshot_opts)
                saved.append(fname)
                log.info("  ✓  %s", fname.name)
            except Exception as exc:
                log.warning("  ✗  #%s: %s", container_id, exc)

        await browser.close()

    return saved


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Exporta els gràfics D3 del lloc ACI com a JPG/PNG."
    )
    p.add_argument(
        "--input", default="site_output/index.html",
        help="Fitxer HTML de l'índex global (per defecte: site_output/index.html)",
    )
    p.add_argument(
        "--output", default="site_output/figures",
        help="Directori de sortida per als fitxers d'imatge (per defecte: site_output/figures)",
    )
    p.add_argument(
        "--prefix", default="global",
        help="Prefix dels fitxers de sortida (per defecte: global)",
    )
    p.add_argument(
        "--width", type=int, default=1440,
        help="Amplada de la finestra del navegador (per defecte: 1440)",
    )
    p.add_argument(
        "--quality", type=int, default=90,
        help="Qualitat JPEG 1–100 (per defecte: 90)",
    )
    p.add_argument(
        "--format", default="jpg", choices=["jpg", "jpeg", "png"],
        help="Format de sortida: jpg o png (per defecte: jpg)",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    input_path = Path(args.input)
    output_dir = Path(args.output)

    if not input_path.exists():
        log.error("Fitxer d'entrada no trobat: %s", input_path)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Exportant gràfics de: %s", input_path.resolve())
    log.info("Directori de sortida: %s", output_dir.resolve())

    saved = asyncio.run(
        _export(
            input_path=input_path,
            output_dir=output_dir,
            prefix=args.prefix,
            width=args.width,
            quality=args.quality,
            fmt=args.format,
        )
    )

    log.info("\n✓  %d gràfic(s) exportat(s) a %s", len(saved), output_dir.resolve())
    if not saved:
        log.warning("Cap gràfic exportat. Comprova que el fitxer HTML és vàlid.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
