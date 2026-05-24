"""
M3 — Segmentació i construcció de la jerarquia de blocs.
Agrupa elements en blocs semàntics i construeix una jerarquia.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .utils import slug_from_url, timestamp

log = logging.getLogger("aci_pipeline.m3")


def _build_heading_hierarchy(headings: list[dict[str, Any]]) -> dict[str, Any]:
    """Construeix una jerarquia d'encapçalaments i detecta violacions."""
    violations: list[str] = []
    prev_level = 0
    hierarchy_ok = True

    for h in headings:
        level = h["level"]
        if prev_level > 0 and level > prev_level + 1:
            violations.append(f"Salt de H{prev_level} a H{level}: '{h['text'][:50]}'")
            hierarchy_ok = False
        prev_level = level

    has_h1 = any(h["level"] == 1 for h in headings)
    if not has_h1 and headings:
        violations.append("No s'ha trobat cap H1 a la pàgina")
        hierarchy_ok = False

    multiple_h1 = sum(1 for h in headings if h["level"] == 1) > 1
    if multiple_h1:
        violations.append("Múltiples H1 detectats")

    return {
        "headings": headings,
        "has_h1": has_h1,
        "hierarchy_ok": hierarchy_ok,
        "multiple_h1": multiple_h1,
        "violations": violations,
        "depth": max((h["level"] for h in headings), default=0),
        "heading_hierarchy_score": 1.0 if hierarchy_ok else max(0.0, 1.0 - 0.2 * len(violations)),
    }


def _segment_text_blocks(text_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segmenta i classifica blocs de text per tipus i mida."""
    segments: list[dict[str, Any]] = []
    for block in text_blocks:
        char_count = block.get("char_count", len(block.get("text", "")))
        text = block.get("text", "")
        block_type = block.get("type", "p")

        segment: dict[str, Any] = {
            "type": block_type,
            "text_preview": text[:100],
            "char_count": char_count,
            "word_count": len(text.split()),
        }

        if block_type in ("figcaption",):
            segment["segment_role"] = "caption"
        elif block_type == "blockquote":
            segment["segment_role"] = "quote"
        elif block_type in ("td", "dd"):
            segment["segment_role"] = "data"
        elif block_type == "li":
            segment["segment_role"] = "list_item"
        else:
            segment["segment_role"] = "paragraph"

        segments.append(segment)

    return segments


def _analyze_figures(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Analitza imatges i genera informació de segmentació visual."""
    figures: list[dict[str, Any]] = []
    for img in images:
        fig: dict[str, Any] = {
            "type": img.get("type", "img"),
            "has_alt": img.get("meaningful_alt", False),
            "needs_ai": img.get("needs_ai", False),
            "alt_text": img.get("alt") or img.get("aria_label") or "",
        }
        figures.append(fig)
    return figures


def run_m3(
    page_structure: dict[str, Any],
    url: str,
    data_dir: Path = Path("data"),
    slug: str | None = None,
    ts: int | None = None,
) -> dict[str, Any]:
    """Executa M3: segmentació i construcció de jerarquia."""
    slug = slug or slug_from_url(url)
    ts = ts or timestamp()

    headings = page_structure.get("headings", [])
    text_blocks = page_structure.get("text_blocks", [])
    images = page_structure.get("images", [])

    hierarchy = _build_heading_hierarchy(headings)
    segments = _segment_text_blocks(text_blocks)
    figures = _analyze_figures(images)

    total_words = sum(s.get("word_count", 0) for s in segments)
    avg_words_per_block = total_words / len(segments) if segments else 0

    result: dict[str, Any] = {
        "url": url,
        "heading_hierarchy": hierarchy,
        "segments": segments,
        "figures": figures,
        "stats": {
            "total_segments": len(segments),
            "total_words": total_words,
            "avg_words_per_block": round(avg_words_per_block, 1),
            "figures_needing_ai": sum(1 for f in figures if f["needs_ai"]),
            "heading_depth": hierarchy.get("depth", 0),
        },
    }

    out_dir = data_dir / "processed" / "structure"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_{ts}_segments.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("M3 completat per %s", url)
    return result
