"""
M4 — Anàlisi quantitatiu.
Calcula mètriques textuals (Flesch, etc.), visuals (contrast, focus)
i integra els resultats d'axe-core.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from .utils import parse_css_color, slug_from_url, timestamp, wcag_contrast_ratio

log = logging.getLogger("aci_pipeline.m4")


def _compute_text_metrics(plain_text: str) -> dict[str, Any]:
    """Calcula mètriques de llegibilitat textual."""
    try:
        import textstat
        textstat.set_lang("es")  # Castellà com a aproximació al català

        flesch = textstat.flesch_reading_ease(plain_text)
        fk_grade = textstat.flesch_kincaid_grade(plain_text)
        num_words = textstat.lexicon_count(plain_text, removepunct=True)
        num_sentences = textstat.sentence_count(plain_text)
        num_syllables = textstat.syllable_count(plain_text)
        difficult_words = textstat.difficult_words(plain_text)
        avg_sentence_length = num_words / num_sentences if num_sentences > 0 else 0
        lexical_density = difficult_words / num_words if num_words > 0 else 0

        return {
            "flesch_reading_ease": round(flesch, 2),
            "flesch_kincaid_grade": round(fk_grade, 2),
            "num_words": num_words,
            "num_sentences": num_sentences,
            "num_syllables": num_syllables,
            "difficult_words": difficult_words,
            "avg_sentence_length": round(avg_sentence_length, 1),
            "lexical_density": round(lexical_density, 3),
        }
    except ImportError:
        log.warning("textstat no disponible; mètriques textuals omeses.")
        words = plain_text.split()
        sentences = plain_text.count(".") + plain_text.count("!") + plain_text.count("?")
        return {
            "flesch_reading_ease": None,
            "flesch_kincaid_grade": None,
            "num_words": len(words),
            "num_sentences": max(sentences, 1),
            "num_syllables": None,
            "difficult_words": None,
            "avg_sentence_length": len(words) / max(sentences, 1),
            "lexical_density": None,
        }


def _analyze_axe_results(axe_result: dict[str, Any]) -> dict[str, Any]:
    """Analitza els resultats d'axe-core i extreu recomptes per severitat."""
    if not axe_result:
        return {
            "violations_count": 0,
            "critical_violations": 0,
            "serious_violations": 0,
            "moderate_violations": 0,
            "minor_violations": 0,
            "violations_by_severity": {},
            "violations_detail": [],
        }

    violations = axe_result.get("violations", [])
    by_severity: dict[str, int] = {}
    details: list[dict[str, Any]] = []

    for v in violations:
        impact = v.get("impact", "unknown")
        by_severity[impact] = by_severity.get(impact, 0) + 1
        details.append({
            "id": v.get("id"),
            "impact": impact,
            "description": v.get("description", "")[:200],
            "help": v.get("help", "")[:200],
            "nodes_affected": len(v.get("nodes", [])),
        })

    return {
        "violations_count": len(violations),
        "critical_violations": by_severity.get("critical", 0),
        "serious_violations": by_severity.get("serious", 0),
        "moderate_violations": by_severity.get("moderate", 0),
        "minor_violations": by_severity.get("minor", 0),
        "violations_by_severity": by_severity,
        "violations_detail": details[:50],
        "passes_count": len(axe_result.get("passes", [])),
        "incomplete_count": len(axe_result.get("incomplete", [])),
    }


def _compute_perf_metrics(perf: dict[str, Any]) -> dict[str, Any]:
    """Normalitza mètriques de rendiment."""
    lcp = perf.get("lcp")
    ttfb = perf.get("ttfb")
    return {
        "lcp_ms": lcp,
        "ttfb_ms": ttfb,
        "total_bytes": perf.get("total_bytes"),
        "lcp_rating": (
            "good" if lcp is not None and lcp < 2500 else
            "needs_improvement" if lcp is not None and lcp < 4000 else
            "poor" if lcp is not None else "unknown"
        ),
    }


def _compute_alt_coverage(images: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcula la cobertura d'alt text."""
    if not images:
        return {"alt_coverage_ratio": 1.0, "total_images": 0, "images_with_alt": 0}
    total = len(images)
    with_meaningful_alt = sum(1 for i in images if i.get("meaningful_alt", False))
    with_any_alt = sum(1 for i in images if i.get("alt") is not None or i.get("aria_label"))
    return {
        "alt_coverage_ratio": round(with_meaningful_alt / total, 3),
        "alt_any_ratio": round(with_any_alt / total, 3),
        "total_images": total,
        "images_with_alt": with_meaningful_alt,
        "images_needing_ai": sum(1 for i in images if i.get("needs_ai", False)),
    }


def _compute_accessible_names(interactive_elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcula la cobertura de noms accessibles."""
    if not interactive_elements:
        return {"accessible_names_coverage": 1.0, "total_interactive": 0, "with_name": 0}
    total = len(interactive_elements)
    with_name = sum(1 for e in interactive_elements if e.get("has_accessible_name", False))
    return {
        "accessible_names_coverage": round(with_name / total, 3),
        "total_interactive": total,
        "with_name": with_name,
    }


def _compute_aria_validity(aria_elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcula el ratio de rols ARIA vàlids."""
    if not aria_elements:
        return {"aria_roles_valid_ratio": 1.0, "total_aria": 0, "valid_aria": 0}
    total = len(aria_elements)
    valid = sum(1 for a in aria_elements if a.get("valid", False))
    return {
        "aria_roles_valid_ratio": round(valid / total, 3),
        "total_aria": total,
        "valid_aria": valid,
    }


def _compute_landmark_coverage(landmarks: dict[str, int]) -> dict[str, Any]:
    """Evalua la cobertura de landmarks ARIA/HTML5."""
    essential = {"main", "nav", "header", "footer"}
    present = set(landmarks.keys())
    coverage = len(essential & present) / len(essential)
    return {
        "landmark_coverage_ratio": round(coverage, 3),
        "landmarks_present": list(present),
        "essential_missing": list(essential - present),
    }


def run_m4(
    page_structure: dict[str, Any],
    m3_result: dict[str, Any],
    axe_result: dict[str, Any],
    perf: dict[str, Any],
    url: str,
    data_dir: Path = Path("data"),
    slug: str | None = None,
    ts: int | None = None,
) -> dict[str, Any]:
    """Executa M4: anàlisi quantitatiu complet."""
    slug = slug or slug_from_url(url)
    ts = ts or timestamp()

    plain_text = page_structure.get("plain_text", "")
    images = page_structure.get("images", [])
    interactive_elements = page_structure.get("interactive_elements", [])
    aria_elements = page_structure.get("aria_elements", [])
    landmarks = page_structure.get("landmarks", {})

    text_metrics = _compute_text_metrics(plain_text)
    axe_metrics = _analyze_axe_results(axe_result)
    perf_metrics = _compute_perf_metrics(perf)
    alt_coverage = _compute_alt_coverage(images)
    names_coverage = _compute_accessible_names(interactive_elements)
    aria_validity = _compute_aria_validity(aria_elements)
    landmark_cov = _compute_landmark_coverage(landmarks)
    heading_info = m3_result.get("heading_hierarchy", {})

    # Mètriques compostes
    text_complexity_score = None
    if text_metrics.get("flesch_reading_ease") is not None:
        flesch = text_metrics["flesch_reading_ease"]
        text_complexity_score = round(min(1.0, max(0.0, flesch / 100.0)), 3)

    result: dict[str, Any] = {
        "url": url,
        "text_metrics": text_metrics,
        "axe_summary": axe_metrics,
        "perf": perf_metrics,
        "alt_coverage": alt_coverage,
        "accessible_names": names_coverage,
        "aria_validity": aria_validity,
        "landmark_coverage": landmark_cov,
        "heading_hierarchy_score": heading_info.get("heading_hierarchy_score", 1.0),
        "text_complexity_score": text_complexity_score,
        # Mètriques planes per M6
        "metrics": {
            "color_contrast_ratio": None,  # Calculat per axe-core; si NA → 0.5
            "focus_visible_ratio": None,   # Requereix Playwright; si NA → 0.5
            "target_size_clean": None,      # Requereix Playwright; si NA → 0.5
            "keyboard_clean": None,         # Requereix Playwright; si NA → 0.5
            "aria_roles_valid": aria_validity["aria_roles_valid_ratio"],
            "accessible_names_coverage": names_coverage["accessible_names_coverage"],
            "audit_critical_violations": axe_metrics["critical_violations"],
            "audit_high_violations": axe_metrics["serious_violations"],
            "audit_medium_violations": axe_metrics["moderate_violations"],
            "audit_low_violations": axe_metrics["minor_violations"],
            "page_flesch": text_metrics.get("flesch_reading_ease"),
            "text_complexity": text_complexity_score,
            "heading_hierarchy": heading_info.get("heading_hierarchy_score", 1.0),
            "alt_text_coverage": alt_coverage["alt_coverage_ratio"],
            "landmark_coverage": landmark_cov["landmark_coverage_ratio"],
            "performance_lcp": perf_metrics.get("lcp_ms"),
        },
    }

    # Intenta extreure contrast des d'axe si disponible
    if axe_result:
        for violation in axe_result.get("violations", []):
            if violation.get("id") == "color-contrast":
                total_nodes = len(axe_result.get("passes", []))
                contrast_passes = sum(
                    1 for p in axe_result.get("passes", [])
                    if p.get("id") == "color-contrast"
                )
                # Estimació heurística
                failing_nodes = len(violation.get("nodes", []))
                if total_nodes + failing_nodes > 0:
                    result["metrics"]["color_contrast_ratio"] = round(
                        contrast_passes / (contrast_passes + failing_nodes + 1e-9), 3
                    )
                break

    out_dir = data_dir / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_{ts}_metrics.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("M4 completat per %s", url)
    return result
