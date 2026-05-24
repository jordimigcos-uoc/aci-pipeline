"""Utilitats compartides per al pipeline aci_pipeline."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import yaml


PIPELINE_VERSION = "0.1.0"
USER_AGENT = f"aci_pipeline/{PIPELINE_VERSION} (accessibilitat-web-tfm)"


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configura el logging del pipeline."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    return logging.getLogger("aci_pipeline")


def slug_from_url(url: str) -> str:
    """Genera un identificador segur de fitxer a partir d'una URL."""
    slug = re.sub(r"https?://", "", url)
    slug = re.sub(r"[^\w\-]", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:80]


def timestamp() -> int:
    """Retorna el timestamp Unix actual com a enter."""
    return int(time.time())


def load_yaml(path: Path) -> dict[str, Any]:
    """Carrega un fitxer YAML i retorna el contingut com a dict."""
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def wcag_contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """
    Calcula la relació de contrast WCAG entre dos colors RGB.
    Retorna un valor entre 1.0 (sense contrast) i 21.0 (màxim contrast).
    """
    def relative_luminance(rgb: tuple[int, int, int]) -> float:
        vals = []
        for c in rgb:
            srgb = c / 255.0
            vals.append(srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4)
        r, g, b = vals
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def parse_css_color(color_str: str) -> tuple[int, int, int] | None:
    """
    Parseja una cadena CSS de color (rgb(...) o #rrggbb) i retorna una tupla RGB.
    Retorna None si no es pot parsejar.
    """
    if not color_str:
        return None
    color_str = color_str.strip()
    # rgb(r, g, b) o rgba(r, g, b, a)
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", color_str)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # #rrggbb o #rgb
    m = re.match(r"#([0-9a-fA-F]{3,6})$", color_str)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = h[0]*2 + h[1]*2 + h[2]*2
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return None


def base_metadata(url: str) -> dict[str, Any]:
    """Genera metadades base per a tots els artefactes del pipeline."""
    return {
        "url": url,
        "timestamp": timestamp(),
        "pipeline_version": PIPELINE_VERSION,
        "user_agent": USER_AGENT,
    }
