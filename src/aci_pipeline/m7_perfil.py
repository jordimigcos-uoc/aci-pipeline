"""
M7 — Selecció de perfil de puntuació i priorització d'intervencions.
Carrega perfils YAML i genera llista prioritzada d'intervencions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .utils import load_yaml, slug_from_url, timestamp

log = logging.getLogger("aci_pipeline.m7")

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "configs" / "scoring_config.yaml"


def load_scoring_config(config_path: Path | None = None) -> dict[str, Any]:
    """Carrega la configuració de perfils de puntuació."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        log.warning("Fitxer de configuració no trobat: %s; usant configuració per defecte.", path)
        return _default_config()
    return load_yaml(path)


def _default_config() -> dict[str, Any]:
    """Configuració mínima per defecte si no hi ha fitxer YAML."""
    return {
        "profiles": {
            "wcag_strict": {
                "metrics": {
                    "color_contrast_ratio": 5,
                    "focus_visible_ratio": 4,
                    "audit_critical_violations": 5,
                    "audit_high_violations": 4,
                    "accessible_names_coverage": 5,
                    "alt_text_coverage": 5,
                    "page_flesch": 2,
                    "heading_hierarchy": 3,
                    "landmark_coverage": 3,
                    "performance_lcp": 2,
                }
            }
        },
        "normalization": {}
    }


def get_profile_weights(config: dict[str, Any], profile_name: str) -> dict[str, int]:
    """Extreu els pesos d'un perfil concret."""
    profiles = config.get("profiles", {})
    if profile_name not in profiles:
        available = list(profiles.keys())
        log.warning("Perfil '%s' no trobat. Disponibles: %s", profile_name, available)
        profile_name = available[0] if available else "wcag_strict"
    return profiles[profile_name].get("metrics", {})


def get_norm_config(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extreu la configuració de normalització."""
    return config.get("normalization", {})


def prioritize_interventions(
    m6_result: dict[str, Any],
    m4_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Genera una llista prioritzada d'intervencions basada en:
    - Score normalitzat de la mètrica (menor score = major prioritat)
    - Pes de la mètrica en el perfil actiu
    - Estimació de cost (heurística)
    """
    normalized = m6_result.get("normalized_metrics", {})
    weights = m6_result.get("weights", {})
    raw = m6_result.get("raw_values", {})

    # Heurístiques de cost i accions per mètrica
    metric_actions: dict[str, dict[str, Any]] = {
        "color_contrast_ratio": {
            "action": "Corregir contrast de color text/fons",
            "cost": "mig",
            "wcag": "1.4.3",
            "impact_level": "alt",
        },
        "focus_visible_ratio": {
            "action": "Afegir indicadors de focus visibles (CSS :focus)",
            "cost": "baix",
            "wcag": "2.4.7/2.4.11",
            "impact_level": "alt",
        },
        "target_size_clean": {
            "action": "Ampliar àrees d'interacció (mínim 24x24 px WCAG 2.5.8)",
            "cost": "mig",
            "wcag": "2.5.8",
            "impact_level": "mig",
        },
        "keyboard_clean": {
            "action": "Eliminar trampes de focus i assegurar navegació per teclat",
            "cost": "alt",
            "wcag": "2.1.1/2.1.2",
            "impact_level": "critic",
        },
        "aria_roles_valid": {
            "action": "Corregir atributs ARIA invàlids o incorrectes",
            "cost": "baix",
            "wcag": "4.1.2",
            "impact_level": "mig",
        },
        "accessible_names_coverage": {
            "action": "Afegir aria-label/aria-labelledby als elements interactius sense nom",
            "cost": "baix",
            "wcag": "4.1.2/1.1.1",
            "impact_level": "alt",
        },
        "audit_critical_violations": {
            "action": "Resoldre violacions critiques d'axe-core (nivell A)",
            "cost": "alt",
            "wcag": "multiples",
            "impact_level": "critic",
        },
        "audit_high_violations": {
            "action": "Resoldre violacions greus d'axe-core (nivell AA)",
            "cost": "mig",
            "wcag": "multiples",
            "impact_level": "alt",
        },
        "audit_medium_violations": {
            "action": "Revisar i corregir violacions moderades d'axe-core",
            "cost": "mig",
            "wcag": "multiples",
            "impact_level": "mig",
        },
        "page_flesch": {
            "action": "Simplificar el text per millorar la llegibilitat (Flesch > 60)",
            "cost": "alt",
            "wcag": "3.1.5",
            "impact_level": "mig",
        },
        "text_complexity": {
            "action": "Reduir frases llargues i vocabulari complex",
            "cost": "alt",
            "wcag": "3.1.5",
            "impact_level": "mig",
        },
        "heading_hierarchy": {
            "action": "Corregir la jerarquia d'encapcalaments (H1->H2->H3...)",
            "cost": "baix",
            "wcag": "1.3.1/2.4.6",
            "impact_level": "mig",
        },
        "alt_text_coverage": {
            "action": "Afegir text alternatiu a totes les imatges informatives",
            "cost": "mig",
            "wcag": "1.1.1",
            "impact_level": "alt",
        },
        "landmark_coverage": {
            "action": "Afegir landmarks semantics (main, nav, header, footer)",
            "cost": "baix",
            "wcag": "1.3.1/4.1.2",
            "impact_level": "mig",
        },
        "performance_lcp": {
            "action": "Optimitzar LCP: imatges, fonts i recursos bloquejants",
            "cost": "alt",
            "wcag": "N/A (Web Vitals)",
            "impact_level": "mig",
        },
    }

    interventions: list[dict[str, Any]] = []

    for metric_name, norm_val in normalized.items():
        if metric_name not in metric_actions:
            continue

        weight = weights.get(metric_name, 1)
        gap = 1.0 - norm_val  # Distància fins al valor òptim
        priority_score = gap * weight  # Major gap + major pes = major prioritat

        action_info = metric_actions[metric_name]

        interventions.append({
            "metric": metric_name,
            "current_value": raw.get(metric_name),
            "normalized_score": norm_val,
            "gap": round(gap, 3),
            "weight": weight,
            "priority_score": round(priority_score, 3),
            "action": action_info["action"],
            "cost": action_info["cost"],
            "impact_level": action_info["impact_level"],
            "wcag_criterion": action_info["wcag"],
        })

    # Ordena per priority_score descendent
    interventions.sort(key=lambda x: x["priority_score"], reverse=True)

    # Afegeix rang de prioritat
    for i, interv in enumerate(interventions):
        interv["priority_rank"] = i + 1

    return interventions


def run_m7(
    m6_result: dict[str, Any],
    m4_result: dict[str, Any],
    url: str,
    data_dir: Path = Path("data"),
    slug: str | None = None,
    ts: int | None = None,
) -> dict[str, Any]:
    """Executa M7: priorització d'intervencions."""
    slug = slug or slug_from_url(url)
    ts = ts or timestamp()

    interventions = prioritize_interventions(m6_result, m4_result)

    result: dict[str, Any] = {
        "url": url,
        "timestamp": ts,
        "profile": m6_result.get("profile"),
        "aci_score": m6_result.get("aci_score"),
        "interventions": interventions,
        "top_3": interventions[:3],
    }

    out_dir = data_dir / "reports" / "interventions"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_{ts}_interventions.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("M7 completat per %s: %d intervencions prioritzades", url, len(interventions))
    return result
