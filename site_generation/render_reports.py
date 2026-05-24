#!/usr/bin/env python3
"""
site_generation/render_reports.py
==================================
Genera el lloc estàtic complet de resultats ACI (Jinja2 + D3.js).

Per a cada URL analitzada:
  - Llegeix la sortida del pipeline (results/{run}/metrics/*.json)
    O fitxers results/<slug>/results.json ja existents
  - Crea/actualitza results/<slug>/results.json  (nou format unificat)
  - Renderitza reports/<slug>_<profile>.html      (informe per perfil)
  - Renderitza reports/<slug>_comparative.html    (informe comparatiu)
  - Genera site_output/index.html                 (índex global D3)
  - Crea site_output/figures/ (placeholders; export real via export_charts.py)

CLI:
  python site_generation/render_reports.py
  python site_generation/render_reports.py \\
      --results-dir results/gh-pages \\
      --output-dir  site_output \\
      --templates-dir templates \\
      --profiles wcag_strict readability_first visual_first
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

try:
    import jinja2
except ImportError:
    print("ERROR: jinja2 no instal·lat — pip install jinja2", file=sys.stderr)
    sys.exit(1)

log = logging.getLogger("render_reports")

# ── Constants ──────────────────────────────────────────────────────────────────

VERSION = "0.2.0"

PROFILES = ["wcag_strict", "readability_first", "visual_first"]
PROFILE_LABELS = {
    "wcag_strict":       "WCAG Strict",
    "readability_first": "Readability First",
    "visual_first":      "Visual First",
}
PROFILE_COLORS = {
    "wcag_strict":       "#1d4ed8",
    "readability_first": "#15803d",
    "visual_first":      "#be123c",
}

ALL_METRICS = [
    "color_contrast_ratio", "focus_visible_ratio", "target_size_clean",
    "keyboard_clean", "aria_roles_valid", "accessible_names_coverage",
    "audit_critical_violations", "audit_high_violations",
    "audit_medium_violations", "audit_low_violations",
    "page_flesch", "text_complexity", "heading_hierarchy",
    "alt_text_coverage", "landmark_coverage", "performance_lcp",
]

METRIC_LABELS = {
    "color_contrast_ratio":      "Contrast de color",
    "focus_visible_ratio":       "Visibilitat del focus",
    "target_size_clean":         "Mida objectiu tàctil",
    "keyboard_clean":            "Navegació per teclat",
    "aria_roles_valid":          "Rols ARIA vàlids",
    "accessible_names_coverage": "Noms accessibles",
    "audit_critical_violations": "Violacions crítiques",
    "audit_high_violations":     "Violacions altes",
    "audit_medium_violations":   "Violacions mitjanes",
    "audit_low_violations":      "Violacions baixes",
    "page_flesch":               "Llegibilitat Flesch",
    "text_complexity":           "Complexitat textual",
    "heading_hierarchy":         "Jerarquia capçaleres",
    "alt_text_coverage":         "Alt text imatges",
    "landmark_coverage":         "Landmarks nav",
    "performance_lcp":           "LCP (Core Web Vitals)",
}

METRIC_WCAG = {
    "color_contrast_ratio":      "1.4.3 AA",
    "focus_visible_ratio":       "2.4.7 AA",
    "target_size_clean":         "2.5.8 AA",
    "keyboard_clean":            "2.1.1 A",
    "aria_roles_valid":          "4.1.2 AA",
    "accessible_names_coverage": "4.1.2 AA",
    "audit_critical_violations": "Múltiples",
    "audit_high_violations":     "Múltiples",
    "audit_medium_violations":   "Múltiples",
    "audit_low_violations":      "Múltiples",
    "page_flesch":               "3.1.5 AAA",
    "text_complexity":           "3.1 AA",
    "heading_hierarchy":         "1.3.1 A",
    "alt_text_coverage":         "1.1.1 A",
    "landmark_coverage":         "1.3.6 AAA",
    "performance_lcp":           "EN 301 549",
}

TYPE_ORDER = ["institucional", "universitat", "educatiu", "cultural",
              "mitjans", "comercial", "ecommerce", "blog", "independents"]

TYPE_COLORS = {
    "institucional": "#1d4ed8",
    "universitat":   "#7c3aed",
    "educatiu":      "#15803d",
    "cultural":      "#d97706",
    "mitjans":       "#c2410c",
    "comercial":     "#0e7490",
    "ecommerce":     "#0e7490",
    "blog":          "#4b5563",
    "independents":  "#374151",
}

# Recomanacions per al gràfic d'impacte-esforç
RECOMMENDATIONS = [
    {"id": "contrast",    "name": "Corregir contrast de color",    "effort": 0.30, "impact": 0.90, "priority": 5, "metric": "color_contrast_ratio",      "wcag": "1.4.3 AA"},
    {"id": "alt",         "name": "Afegir alt text a imatges",     "effort": 0.40, "impact": 0.85, "priority": 5, "metric": "alt_text_coverage",           "wcag": "1.1.1 A"},
    {"id": "labels",      "name": "Etiquetar controls formulari",  "effort": 0.35, "impact": 0.80, "priority": 4, "metric": "accessible_names_coverage",   "wcag": "4.1.2 AA"},
    {"id": "focus",       "name": "Afegir focus visible",          "effort": 0.40, "impact": 0.75, "priority": 4, "metric": "focus_visible_ratio",          "wcag": "2.4.7 AA"},
    {"id": "headings",    "name": "Estructura de capçaleres",      "effort": 0.30, "impact": 0.70, "priority": 4, "metric": "heading_hierarchy",            "wcag": "1.3.1 A"},
    {"id": "keyboard",    "name": "Millorar navegació teclat",     "effort": 0.65, "impact": 0.85, "priority": 4, "metric": "keyboard_clean",               "wcag": "2.1.1 A"},
    {"id": "text",        "name": "Simplificar textos",            "effort": 0.70, "impact": 0.65, "priority": 3, "metric": "text_complexity",              "wcag": "3.1.5 AAA"},
    {"id": "landmarks",   "name": "Afegir landmarks HTML5",        "effort": 0.25, "impact": 0.60, "priority": 3, "metric": "landmark_coverage",            "wcag": "1.3.6 AAA"},
    {"id": "target",      "name": "Augmentar mida objectius",      "effort": 0.45, "impact": 0.55, "priority": 3, "metric": "target_size_clean",            "wcag": "2.5.8 AA"},
    {"id": "lcp",         "name": "Optimitzar rendiment LCP",      "effort": 0.80, "impact": 0.70, "priority": 3, "metric": "performance_lcp",              "wcag": "EN 301 549"},
    {"id": "aria",        "name": "Corregir rols ARIA",            "effort": 0.50, "impact": 0.60, "priority": 3, "metric": "aria_roles_valid",             "wcag": "4.1.2 AA"},
    {"id": "axe_crit",   "name": "Corregir violacions crítiques",  "effort": 0.60, "impact": 0.95, "priority": 5, "metric": "audit_critical_violations",   "wcag": "Múltiples"},
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_mean(values: list[float]) -> float:
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else 0.0


def _extract_slug(stem: str, profile: str, ts: int) -> str:
    suffix = f"_{ts}_{profile}"
    if stem.endswith(suffix):
        return stem[: -len(suffix)]
    parts = stem.split("_")
    n_p = len(profile.split("_"))
    if parts[-n_p:] == profile.split("_"):
        parts = parts[:-n_p]
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return "_".join(parts) or stem


def _normalise_type(raw_type: str) -> str:
    t = raw_type.lower().strip()
    aliases = {
        "educatiu": "educatiu", "educational": "educatiu",
        "universitat": "universitat", "university": "universitat",
        "institucional": "institucional", "institutional": "institucional",
        "cultural": "cultural", "culture": "cultural",
        "mitjans": "mitjans", "media": "mitjans",
        "comercial": "comercial", "commercial": "comercial",
        "ecommerce": "ecommerce", "e-commerce": "ecommerce",
        "blog": "blog",
        "independents": "independents",
    }
    for key, val in aliases.items():
        if key in t:
            return val
    return t or "independents"


def _slug_from_url(url: str) -> str:
    s = url.replace("https://", "").replace("http://", "")
    s = s.rstrip("/")
    for ch in [".", "/", ":", "?", "=", "&", "#", "@"]:
        s = s.replace(ch, "-")
    return s[:60].strip("-")


def _compute_wcag_principles(nm: dict[str, float]) -> dict[str, float]:
    """Agrega les 16 mètriques als 4 principis WCAG (escala 0-100)."""
    perceptible = _safe_mean([
        nm.get("color_contrast_ratio", 0),
        nm.get("alt_text_coverage", 0),
        nm.get("heading_hierarchy", 0),
    ]) * 100

    operable = _safe_mean([
        nm.get("focus_visible_ratio", 0),
        nm.get("target_size_clean", 0),
        nm.get("keyboard_clean", 0),
    ]) * 100

    comprensible = _safe_mean([
        nm.get("page_flesch", 0),
        nm.get("text_complexity", 0),
        nm.get("heading_hierarchy", 0),
    ]) * 100

    robust = _safe_mean([
        nm.get("aria_roles_valid", 0),
        nm.get("accessible_names_coverage", 0),
        nm.get("audit_critical_violations", 0),
        nm.get("audit_high_violations", 0),
    ]) * 100

    return {
        "perceptible":  round(perceptible, 1),
        "operable":     round(operable, 1),
        "comprensible": round(comprensible, 1),
        "robust":       round(robust, 1),
    }


def _metrics_to_100(nm: dict[str, float]) -> dict[str, float]:
    """Converteix mètriques normalitzades [0-1] a escala [0-100]."""
    return {
        "color_contrast":        round((nm.get("color_contrast_ratio", 0)) * 100, 1),
        "focus_visibility":      round((nm.get("focus_visible_ratio", 0)) * 100, 1),
        "target_size":           round((nm.get("target_size_clean", 0)) * 100, 1),
        "keyboard_nav":          round((nm.get("keyboard_clean", 0)) * 100, 1),
        "aria_roles":            round((nm.get("aria_roles_valid", 0)) * 100, 1),
        "accessible_names":      round((nm.get("accessible_names_coverage", 0)) * 100, 1),
        "critical_violations":   round((nm.get("audit_critical_violations", 0)) * 100, 1),
        "high_violations":       round((nm.get("audit_high_violations", 0)) * 100, 1),
        "medium_violations":     round((nm.get("audit_medium_violations", 0)) * 100, 1),
        "low_violations":        round((nm.get("audit_low_violations", 0)) * 100, 1),
        "flesch_reading_ease":   round((nm.get("page_flesch", 0)) * 100, 1),
        "text_complexity":       round((nm.get("text_complexity", 0)) * 100, 1),
        "heading_hierarchy":     round((nm.get("heading_hierarchy", 0)) * 100, 1),
        "alt_text_coverage":     round((nm.get("alt_text_coverage", 0)) * 100, 1),
        "landmark_coverage":     round((nm.get("landmark_coverage", 0)) * 100, 1),
        "performance_lcp":       round((nm.get("performance_lcp", 0)) * 100, 1),
        # Agregats
        "accessibility": round(_safe_mean([
            nm.get("color_contrast_ratio", 0),
            nm.get("focus_visible_ratio", 0),
            nm.get("keyboard_clean", 0),
            nm.get("aria_roles_valid", 0),
            nm.get("accessible_names_coverage", 0),
            nm.get("audit_critical_violations", 0),
        ]) * 100, 1),
        "readability": round(_safe_mean([
            nm.get("page_flesch", 0),
            nm.get("text_complexity", 0),
            nm.get("heading_hierarchy", 0),
        ]) * 100, 1),
        "performance":  round((nm.get("performance_lcp", 0)) * 100, 1),
        "seo": round(_safe_mean([
            nm.get("heading_hierarchy", 0),
            nm.get("landmark_coverage", 0),
        ]) * 100, 1),
        "robustness": round(_safe_mean([
            nm.get("aria_roles_valid", 0),
            nm.get("accessible_names_coverage", 0),
            nm.get("audit_critical_violations", 0),
        ]) * 100, 1),
    }


# ── Càrrega de dades ───────────────────────────────────────────────────────────

def load_pipeline_metrics(results_dir: Path) -> list[dict]:
    """Carrega tots els JSONs de mètriques del pipeline ACI."""
    metrics_dir = results_dir / "metrics"
    if not metrics_dir.exists():
        # Prova directament a results_dir
        metrics_dir = results_dir
    entries = []
    for f in sorted(metrics_dir.rglob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "aci_score" in data and "profile" in data:
                data["_stem"] = f.stem
                entries.append(data)
        except Exception as e:
            log.warning("Ignorat %s: %s", f.name, e)
    log.info("%d fitxer(s) de mètriques carregat(s)", len(entries))
    return entries


def load_slug_results(slug_results_dir: Path) -> list[dict]:
    """Carrega fitxers results/<slug>/results.json ja existents."""
    loaded = []
    for f in sorted(slug_results_dir.rglob("results.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "url" in data and "profiles" in data:
                loaded.append(data)
        except Exception as e:
            log.warning("Ignorat %s: %s", f, e)
    log.info("%d fitxer(s) results.json carregat(s)", len(loaded))
    return loaded


def pipeline_entries_to_slug_results(entries: list[dict]) -> list[dict]:
    """Converteix la sortida del pipeline al nou format per slug."""
    # Agrupa per clean_url
    by_url: dict[str, dict] = {}
    for entry in entries:
        raw_url   = entry.get("url", "")
        clean_url = raw_url.split(";")[0].strip()
        category  = raw_url.split(";")[1].strip() if ";" in raw_url else ""
        domain    = clean_url.replace("https://", "").replace("http://", "").split("/")[0]
        profile   = entry.get("profile", "")
        ts        = entry.get("timestamp", 0)

        if not clean_url or not profile:
            continue

        if clean_url not in by_url:
            by_url[clean_url] = {
                "url":      clean_url,
                "slug":     _slug_from_url(clean_url),
                "domain":   domain,
                "type":     _normalise_type(category),
                "profiles": {},
            }

        existing = by_url[clean_url]["profiles"].get(profile)
        if existing is None or ts > existing.get("_ts", 0):
            by_url[clean_url]["profiles"][profile] = {**entry, "_ts": ts}

    results = []
    for clean_url, data in by_url.items():
        slug = data["slug"]
        profiles_out: dict[str, Any] = {}

        for profile, entry in data["profiles"].items():
            nm  = entry.get("normalized_metrics", {})
            raw = entry.get("raw_values", {})
            ts  = entry.get("timestamp", 0)
            aci_norm = entry.get("aci_normalized") or (entry.get("aci_score", 0) / 5.0)

            ts_iso = (
                datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                if ts else datetime.now(timezone.utc).isoformat()
            )

            sub = entry.get("sub_scores", {})
            sub100 = {k: round(v * 20, 1) for k, v in sub.items() if v is not None}

            profiles_out[profile] = {
                "score_overall": round(aci_norm * 100, 1),
                "metrics":       _metrics_to_100(nm),
                "sub_scores_100": sub100,
                "wcag_principles": _compute_wcag_principles(nm),
                "notes":         entry.get("notes", ""),
                "raw":           raw,
                "_ts":           ts,
                "_ts_iso":       ts_iso,
            }

        if not profiles_out:
            continue

        scores = [v["score_overall"] for v in profiles_out.values()]
        best   = max(profiles_out, key=lambda p: profiles_out[p]["score_overall"])
        worst  = min(profiles_out, key=lambda p: profiles_out[p]["score_overall"])

        first_ts = next(iter(profiles_out.values())).get("_ts_iso", "")

        results.append({
            "url":       clean_url,
            "slug":      slug,
            "domain":    data["domain"],
            "type":      data["type"],
            "timestamp": first_ts,
            "profiles":  profiles_out,
            "comparative": {
                "best_profile":  best,
                "best_score":    round(max(scores), 1),
                "worst_profile": worst,
                "worst_score":   round(min(scores), 1),
                "mean_score":    round(mean(scores), 1),
                "score_variance": round(max(scores) - min(scores), 1),
            },
        })

    results.sort(key=lambda r: r["comparative"]["best_score"], reverse=True)
    return results


# ── Persistència results.json ──────────────────────────────────────────────────

def save_slug_results(site_results: list[dict], output_dir: Path) -> None:
    """Desa results/<slug>/results.json per a cada site."""
    for sr in site_results:
        slug_dir = output_dir / "results" / sr["slug"]
        slug_dir.mkdir(parents=True, exist_ok=True)
        # Elimina camps interns _ts, _ts_iso
        clean = json.loads(json.dumps(sr, default=str))
        for p_data in clean.get("profiles", {}).values():
            p_data.pop("_ts", None)
            p_data.pop("_ts_iso", None)
        (slug_dir / "results.json").write_text(
            json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    log.info("results/ per %d slug(s) desats", len(site_results))


# ── Entorn Jinja2 ──────────────────────────────────────────────────────────────

def get_env(templates_dir: Path) -> jinja2.Environment:
    loader = jinja2.FileSystemLoader([
        str(templates_dir),
        str(templates_dir / "_partials"),
    ])
    env = jinja2.Environment(
        loader=loader,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson"]    = lambda obj: json.dumps(obj, ensure_ascii=False)
    env.filters["aci_color"] = lambda s: "#27ae60" if s >= 70 else ("#e67e22" if s >= 50 else "#e74c3c")
    env.filters["aci_label"] = lambda s: "Excel·lent" if s >= 70 else ("Acceptable" if s >= 50 else "Insuficient")
    return env


# ── Renderitzat de plantilles ──────────────────────────────────────────────────

def _base_ctx(sr: dict, version: str) -> dict:
    """Context base comú a totes les plantilles."""
    return {
        "url":              sr["url"],
        "slug":             sr["slug"],
        "domain":           sr["domain"],
        "web_type":         sr["type"],
        "timestamp":        sr["timestamp"],
        "pipeline_version": version,
        "profiles_list":    PROFILES,
        "profile_labels":   PROFILE_LABELS,
        "profile_colors":   PROFILE_COLORS,
        "type_colors":      TYPE_COLORS,
        "all_metrics":      ALL_METRICS,
        "metric_labels":    METRIC_LABELS,
        "metric_wcag":      METRIC_WCAG,
    }


def render_profile_reports(
    site_results: list[dict],
    output_dir: Path,
    env: jinja2.Environment,
) -> None:
    tpl = env.get_template("report_profile.html.j2")
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for sr in site_results:
        slug = sr["slug"]
        for profile in PROFILES:
            pd = sr["profiles"].get(profile)
            if not pd:
                continue
            ctx = {
                **_base_ctx(sr, VERSION),
                "profile":         profile,
                "profile_label":   PROFILE_LABELS.get(profile, profile),
                "profile_color":   PROFILE_COLORS.get(profile, "#333"),
                "score_overall":   pd["score_overall"],
                "metrics":         pd["metrics"],
                "sub_scores_100":  pd["sub_scores_100"],
                "wcag_principles": pd["wcag_principles"],
                "notes":           pd.get("notes", ""),
                "raw":             pd.get("raw", {}),
                "comparative":     sr["comparative"],
                "profiles_data":   {p: sr["profiles"][p] for p in sr["profiles"]},
                # JSON per Chart.js
                "radar_json": json.dumps({
                    "labels": ["Perceptible", "Operable", "Comprensible", "Robust"],
                    "datasets": [{
                        "label": PROFILE_LABELS.get(profile, profile),
                        "data": [
                            pd["wcag_principles"]["perceptible"],
                            pd["wcag_principles"]["operable"],
                            pd["wcag_principles"]["comprensible"],
                            pd["wcag_principles"]["robust"],
                        ],
                        "backgroundColor": PROFILE_COLORS.get(profile, "#333") + "33",
                        "borderColor": PROFILE_COLORS.get(profile, "#333"),
                    }],
                }, ensure_ascii=False),
                "bar_json": json.dumps({
                    "labels": [METRIC_LABELS.get(m, m) for m in ALL_METRICS],
                    "datasets": [{
                        "label": PROFILE_LABELS.get(profile, profile),
                        "data": [pd["metrics"].get(
                            m.replace("_ratio", "").replace("_clean", "").replace("_coverage", "").replace("audit_", "").replace("_violations", "_violations").replace("page_", "flesch_"), 0)
                            for m in [
                                "color_contrast", "focus_visibility", "target_size",
                                "keyboard_nav", "aria_roles", "accessible_names",
                                "critical_violations", "high_violations",
                                "medium_violations", "low_violations",
                                "flesch_reading_ease", "text_complexity",
                                "heading_hierarchy", "alt_text_coverage",
                                "landmark_coverage", "performance_lcp",
                            ]
                        ],
                        "backgroundColor": PROFILE_COLORS.get(profile, "#333") + "99",
                        "borderColor": PROFILE_COLORS.get(profile, "#333"),
                    }],
                }, ensure_ascii=False),
            }
            dst = reports_dir / f"{slug}_{profile}.html"
            dst.write_text(tpl.render(**ctx), encoding="utf-8")
            sr["profiles"][profile]["report_url"] = f"reports/{slug}_{profile}.html"
            n += 1
            log.debug("  ✓ %s", dst.name)
    log.info("%d informe(s) de perfil renderitzat(s)", n)


def render_comparative_reports(
    site_results: list[dict],
    output_dir: Path,
    env: jinja2.Environment,
) -> None:
    tpl = env.get_template("report_comparative.html.j2")
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for sr in site_results:
        if len(sr["profiles"]) < 2:
            continue
        slug = sr["slug"]

        # Dades per a Chart.js (bar comparatiu per mètrica)
        metric_keys = [
            "color_contrast", "focus_visibility", "target_size",
            "keyboard_nav", "aria_roles", "accessible_names",
            "critical_violations", "high_violations",
            "medium_violations", "low_violations",
            "flesch_reading_ease", "text_complexity",
            "heading_hierarchy", "alt_text_coverage",
            "landmark_coverage", "performance_lcp",
        ]
        metric_labels_chart = [
            "Contrast", "Focus", "Mida", "Teclat", "ARIA", "Noms",
            "Crít.", "Alt.", "Mod.", "Baix",
            "Flesch", "Compl.", "Jerarq.", "AltTx", "Land.", "LCP",
        ]
        cmp_bar_json = {
            "labels": metric_labels_chart,
            "datasets": [
                {
                    "label": PROFILE_LABELS.get(p, p),
                    "data": [sr["profiles"].get(p, {}).get("metrics", {}).get(k, 0)
                             for k in metric_keys],
                    "backgroundColor": PROFILE_COLORS.get(p, "#888") + "99",
                    "borderColor": PROFILE_COLORS.get(p, "#888"),
                }
                for p in PROFILES
                if p in sr["profiles"]
            ],
        }

        # Radar per principis
        principles_radar_json = {
            "labels": ["Perceptible", "Operable", "Comprensible", "Robust"],
            "datasets": [
                {
                    "label": PROFILE_LABELS.get(p, p),
                    "data": [
                        sr["profiles"][p]["wcag_principles"]["perceptible"],
                        sr["profiles"][p]["wcag_principles"]["operable"],
                        sr["profiles"][p]["wcag_principles"]["comprensible"],
                        sr["profiles"][p]["wcag_principles"]["robust"],
                    ],
                    "backgroundColor": PROFILE_COLORS.get(p, "#888") + "22",
                    "borderColor": PROFILE_COLORS.get(p, "#888"),
                }
                for p in PROFILES
                if p in sr["profiles"]
            ],
        }

        ctx = {
            **_base_ctx(sr, VERSION),
            "profiles_data":           {p: sr["profiles"][p] for p in sr["profiles"]},
            "comparative":             sr["comparative"],
            "cmp_bar_json":            json.dumps(cmp_bar_json, ensure_ascii=False),
            "principles_radar_json":   json.dumps(principles_radar_json, ensure_ascii=False),
        }
        dst = reports_dir / f"{slug}_comparative.html"
        dst.write_text(tpl.render(**ctx), encoding="utf-8")
        sr["comparative_url"] = f"reports/{slug}_comparative.html"
        n += 1
        log.debug("  ✓ %s", dst.name)
    log.info("%d informe(s) comparatiu(s) renderitzat(s)", n)


def render_global_index(
    site_results: list[dict],
    output_dir: Path,
    env: jinja2.Environment,
    ts_build: str,
) -> None:
    tpl = env.get_template("global_index.html.j2")

    all_types = sorted({sr["type"] for sr in site_results})

    # Dades lleugeres per a la taula i filtres JS
    table_rows = []
    for sr in site_results:
        row = {
            "url":         sr["url"],
            "slug":        sr["slug"],
            "domain":      sr["domain"],
            "type":        sr["type"],
            "profiles":    {},
            "comparative": sr.get("comparative_url"),
        }
        for p in PROFILES:
            pd = sr["profiles"].get(p)
            row["profiles"][p] = {
                "score":  pd["score_overall"] if pd else None,
                "report": pd.get("report_url") if pd else None,
            }
        row["best_score"] = sr["comparative"]["best_score"]
        table_rows.append(row)

    # Dades per a tots els gràfics D3
    d3_data = []
    for sr in site_results:
        entry = {
            "url":    sr["url"],
            "slug":   sr["slug"],
            "domain": sr["domain"],
            "type":   sr["type"],
            "comparative_url": sr.get("comparative_url"),
            "profiles": {},
        }
        for p in PROFILES:
            pd = sr["profiles"].get(p)
            if pd:
                entry["profiles"][p] = {
                    "score_overall":  pd["score_overall"],
                    "sub_scores_100": pd["sub_scores_100"],
                    "wcag_principles": pd["wcag_principles"],
                    "metrics":        {k: v for k, v in pd["metrics"].items()
                                       if k in [
                                           "color_contrast", "focus_visibility", "target_size",
                                           "keyboard_nav", "aria_roles", "accessible_names",
                                           "critical_violations", "high_violations",
                                           "flesch_reading_ease", "text_complexity",
                                           "heading_hierarchy", "alt_text_coverage",
                                           "landmark_coverage", "performance_lcp",
                                           "accessibility", "readability", "performance",
                                       ]},
                    "report_url": pd.get("report_url"),
                }
        d3_data.append(entry)

    all_acis = [r["best_score"] for r in table_rows if r["best_score"] is not None]

    ctx = {
        "ts_build":         ts_build,
        "pipeline_version": VERSION,
        "n_urls":           len(site_results),
        "n_types":          len(all_types),
        "kpi_max":          round(max(all_acis), 1) if all_acis else None,
        "kpi_mean":         round(mean(all_acis), 1) if all_acis else None,
        "kpi_min":          round(min(all_acis), 1) if all_acis else None,
        "web_types":        all_types,
        "type_colors":      TYPE_COLORS,
        "profiles_list":    PROFILES,
        "profile_labels":   PROFILE_LABELS,
        "profile_colors":   PROFILE_COLORS,
        "all_metrics":      ALL_METRICS,
        "metric_labels":    METRIC_LABELS,
        "metric_wcag":      METRIC_WCAG,
        "recommendations":  RECOMMENDATIONS,
        "table_rows_json":  json.dumps(table_rows, ensure_ascii=False),
        "d3_data_json":     json.dumps(d3_data, ensure_ascii=False),
        "type_colors_json": json.dumps(TYPE_COLORS, ensure_ascii=False),
        "recommendations_json": json.dumps(RECOMMENDATIONS, ensure_ascii=False),
    }

    (output_dir / "index.html").write_text(tpl.render(**ctx), encoding="utf-8")
    log.info("index.html generat (%d URLs)", len(site_results))


def render_metrics_explanation(output_dir: Path, env: jinja2.Environment) -> None:
    try:
        tpl = env.get_template("metrics_explanation.html.j2")
        ctx = {
            "pipeline_version": VERSION,
            "all_metrics":      ALL_METRICS,
            "metric_labels":    METRIC_LABELS,
            "metric_wcag":      METRIC_WCAG,
            "profiles_list":    PROFILES,
            "profile_labels":   PROFILE_LABELS,
            "recommendations":  RECOMMENDATIONS,
        }
        (output_dir / "metrics.html").write_text(tpl.render(**ctx), encoding="utf-8")
        log.info("metrics.html generat")
    except jinja2.TemplateNotFound:
        log.warning("metrics_explanation.html.j2 no trobat; s'omet")


# ── Còpia d'assets ─────────────────────────────────────────────────────────────

def copy_assets(output_dir: Path) -> None:
    for candidate in [Path("static"), Path(__file__).parent.parent / "static"]:
        if candidate.is_dir():
            dst = output_dir / "static"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(candidate, dst)
            log.info("static/ → %s/static/", output_dir.name)
            return
    log.warning("static/ no trobat; s'omet")


def create_figures_placeholder(output_dir: Path, site_results: list[dict]) -> None:
    """Crea el directori figures/ amb un README de com generar els JPG."""
    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    chart_names = [
        "comparison", "principles", "boxplot", "stacked",
        "topbottom", "radar_readability", "heatmap",
        "lollipop", "scatter", "impact_effort",
    ]
    readme_lines = [
        "# figures/ — Exportació JPG dels gràfics D3\n",
        "Genera les imatges amb:\n",
        "  python scripts/export_charts.py --input site_output/index.html --output site_output/figures\n\n",
        "Fitxers esperats per URL:\n",
    ]
    for sr in site_results[:5]:
        for cn in chart_names:
            readme_lines.append(f"  {sr['slug']}_{cn}.jpg\n")
    (fig_dir / "README.md").write_text("".join(readme_lines), encoding="utf-8")
    log.info("figures/ creat (placeholder)")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Genera el lloc estàtic ACI amb Jinja2 + D3.js"
    )
    p.add_argument("--results-dir",   default="results/gh-pages",
                   help="Directori amb la sortida del pipeline (per defecte: results/gh-pages)")
    p.add_argument("--output-dir",    default="site_output",
                   help="Directori de sortida (per defecte: site_output)")
    p.add_argument("--templates-dir", default=None,
                   help="Directori de templates Jinja2 (per defecte: templates/)")
    p.add_argument("--profiles",      nargs="+", default=PROFILES,
                   help="Perfils a renderitzar")
    p.add_argument("--log-level",     default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    results_dir   = Path(args.results_dir)
    output_dir    = Path(args.output_dir)
    templates_dir = (
        Path(args.templates_dir) if args.templates_dir
        else Path(__file__).parent.parent / "templates"
    )

    log.info("render_reports.py — ACI Pipeline v%s", VERSION)
    log.info("  results-dir  : %s", results_dir.resolve())
    log.info("  output-dir   : %s", output_dir.resolve())
    log.info("  templates-dir: %s", templates_dir.resolve())

    output_dir.mkdir(parents=True, exist_ok=True)
    ts_build = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Carrega dades
    log.info("[1] Carregant dades del pipeline…")
    entries = load_pipeline_metrics(results_dir)
    if not entries:
        log.warning("Cap mètrica trobada a %s — intentant llegir results.json…", results_dir)
        site_results = load_slug_results(results_dir)
    else:
        site_results = pipeline_entries_to_slug_results(entries)

    if not site_results:
        log.error("Cap dada disponible. Comprova --results-dir")
        return 1

    log.info("%d URL(s) úniques", len(site_results))

    # 2. Desa results/<slug>/results.json
    log.info("[2] Desant results.json per slug…")
    save_slug_results(site_results, output_dir)

    # 3. Env Jinja2
    log.info("[3] Preparant entorn Jinja2…")
    env = get_env(templates_dir)

    # 4. Informes individuals
    log.info("[4] Renderitzant informes de perfil…")
    render_profile_reports(site_results, output_dir, env)

    # 5. Informes comparatius
    log.info("[5] Renderitzant informes comparatius…")
    render_comparative_reports(site_results, output_dir, env)

    # 6. Índex global
    log.info("[6] Renderitzant índex global D3…")
    render_global_index(site_results, output_dir, env, ts_build)

    # 7. Pàgina de metodologia
    log.info("[7] Renderitzant metrics.html…")
    render_metrics_explanation(output_dir, env)

    # 8. Assets estàtics
    log.info("[8] Copiant assets estàtics…")
    copy_assets(output_dir)

    # 9. Placeholder figures/
    log.info("[9] Creant figures/ (placeholder)…")
    create_figures_placeholder(output_dir, site_results)

    n_rep = len(list((output_dir / "reports").glob("*.html")))
    log.info("\n✓  Lloc generat: %s", output_dir.resolve())
    log.info("   %d URL(s) · %d informe(s) HTML", len(site_results), n_rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
