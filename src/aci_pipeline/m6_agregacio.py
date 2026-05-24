"""
M6 — Agregació i normalització de mètriques.
Calcula el score ACI (0-5) aplicant la fórmula ponderada.
"""

from __future__ import annotations

import csv
import json
import logging
import math
from pathlib import Path
from typing import Any

from .utils import base_metadata, slug_from_url, timestamp

log = logging.getLogger("aci_pipeline.m6")

DEFAULT_NA_VALUE = 0.5  # Valor per a mètriques no disponibles

# Claus de files ja escrites al CSV en aquest procés (dedup intra-run)
_csv_written_keys: set[tuple[str, str, str]] = set()


def _normalize_metric(metric_name: str, value: Any, norm_config: dict[str, Any]) -> float:
    """
    Normalitza una mètrica a [0.0, 1.0] segons la configuració.
    Si value és None/NA, retorna DEFAULT_NA_VALUE.
    """
    if value is None:
        return DEFAULT_NA_VALUE

    norm_type = norm_config.get("norm", "ratio")

    if norm_type == "ratio":
        return float(max(0.0, min(1.0, value)))

    elif norm_type == "bool":
        return 1.0 if value else 0.0

    elif norm_type == "flesch":
        # Flesch va de ~0 (molt difícil) a ~100 (molt fàcil)
        # Normalitzem: ≥60 → 1.0, 0 → 0.0
        return float(max(0.0, min(1.0, value / 100.0)))

    elif norm_type == "inverse_count":
        # 0 violations = 1.0; cada violació redueix el score
        penalty = norm_config.get("penalty_per_violation", 0.1)
        return float(max(0.0, 1.0 - (value * penalty)))

    elif norm_type == "lcp":
        # LCP en ms: <2500 = 1.0, >4000 = 0.0
        threshold_good = norm_config.get("threshold_good", 2500)
        threshold_poor = norm_config.get("threshold_poor", 4000)
        if value <= threshold_good:
            return 1.0
        elif value >= threshold_poor:
            return 0.0
        else:
            return float((threshold_poor - value) / (threshold_poor - threshold_good))

    return DEFAULT_NA_VALUE


def compute_aci_score(
    metrics: dict[str, Any],
    profile_weights: dict[str, int],
    norm_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Calcula l'Accessibility Computation Index (ACI) en escala 0-5.

    Fórmula: ACI = (Σ norm_i × w_i) / (Σ w_i) × 5.0

    Retorna scores normalitzats, pesos, sub-scores i l'ACI final.
    """
    normalized: dict[str, float] = {}
    raw_values: dict[str, Any] = {}
    weights_used: dict[str, int] = {}

    total_weighted_score = 0.0
    total_weight = 0

    for metric_name, weight in profile_weights.items():
        if weight == 0:
            continue

        raw_val = metrics.get(metric_name)
        metric_norm_config = norm_config.get(metric_name, {"norm": "ratio"})

        norm_val = _normalize_metric(metric_name, raw_val, metric_norm_config)

        normalized[metric_name] = round(norm_val, 4)
        raw_values[metric_name] = raw_val
        weights_used[metric_name] = weight

        total_weighted_score += norm_val * weight
        total_weight += weight

    if total_weight == 0:
        aci_normalized = 0.0
        aci_score = 0.0
    else:
        aci_normalized = total_weighted_score / total_weight
        aci_score = round(aci_normalized * 5.0, 3)

    # Sub-scores per grup
    groups = {
        "wcag": ["color_contrast_ratio", "focus_visible_ratio", "target_size_clean",
                 "keyboard_clean", "audit_critical_violations", "audit_high_violations"],
        "text": ["page_flesch", "text_complexity", "heading_hierarchy"],
        "elements": ["aria_roles_valid", "accessible_names_coverage", "alt_text_coverage",
                     "landmark_coverage"],
        "performance": ["performance_lcp"],
    }

    sub_scores: dict[str, float] = {}
    for group_name, group_metrics in groups.items():
        group_vals = [normalized[m] for m in group_metrics if m in normalized]
        group_weights = [weights_used.get(m, 1) for m in group_metrics if m in normalized]
        if group_vals and sum(group_weights) > 0:
            weighted_sum = sum(v * w for v, w in zip(group_vals, group_weights))
            sub_scores[group_name] = round(weighted_sum / sum(group_weights) * 5.0, 3)
        else:
            sub_scores[group_name] = None

    return {
        "aci_score": aci_score,
        "aci_normalized": round(aci_normalized, 4),
        "sub_scores": sub_scores,
        "normalized_metrics": normalized,
        "raw_values": raw_values,
        "weights": weights_used,
        "total_weight": total_weight,
        "metrics_evaluated": len(weights_used),
        "metrics_na": sum(1 for v in raw_values.values() if v is None),
    }


def run_m6(
    m4_result: dict[str, Any],
    profile_name: str,
    profile_weights: dict[str, int],
    norm_config: dict[str, dict[str, Any]],
    url: str,
    data_dir: Path = Path("data"),
    slug: str | None = None,
    ts: int | None = None,
) -> dict[str, Any]:
    """Executa M6: agregació i normalització."""
    slug = slug or slug_from_url(url)
    ts = ts or timestamp()

    metrics = m4_result.get("metrics", {})
    score_result = compute_aci_score(metrics, profile_weights, norm_config)

    result: dict[str, Any] = {
        **base_metadata(url),
        "profile": profile_name,
        **score_result,
    }

    # Desa JSON complet
    out_dir = data_dir / "metrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_{ts}_{profile_name}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    # Desa CSV resum — mode append amb protecció contra files duplicades
    csv_path = out_dir / "score_summary.csv"
    row_key = (url.split(";")[0].strip(), str(result["timestamp"]), profile_name)
    if row_key not in _csv_written_keys:
        file_exists = csv_path.exists()
        with open(csv_path, "a", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["url", "timestamp", "profile", "aci_score", "aci_normalized",
                          "metrics_evaluated", "metrics_na"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "url": url,
                "timestamp": result["timestamp"],
                "profile": profile_name,
                "aci_score": score_result["aci_score"],
                "aci_normalized": score_result["aci_normalized"],
                "metrics_evaluated": score_result["metrics_evaluated"],
                "metrics_na": score_result["metrics_na"],
            })
        _csv_written_keys.add(row_key)
    else:
        log.warning("CSV: fila duplicada omesa per %s / %s / %s", url, result["timestamp"], profile_name)

    log.info("M6 completat per %s (profil=%s, ACI=%.2f)", url, profile_name, score_result["aci_score"])
    return result
