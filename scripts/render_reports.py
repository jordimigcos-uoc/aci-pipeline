#!/usr/bin/env python3
"""
scripts/render_reports.py — Generació completa del lloc estàtic ACI amb Jinja2 + D3.

Per a cada URL analitzada genera:
  - 3 informes HTML individuals (un per perfil: wcag_strict, readability_first, visual_first)
  - 1 informe comparatiu HTML entre els 3 perfils amb gràfics D3
  - 1 índex global HTML amb gràfics D3 per secció del TFM
  - docs/results.json, docs/data/scores.csv, docs/data/reports_manifest.json

Ús:
  python scripts/render_reports.py
  python scripts/render_reports.py --results results/gh-pages --output docs
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jinja2
except ImportError:
    print("ERROR: jinja2 no instal·lat. Executa: pip install jinja2", file=sys.stderr)
    sys.exit(1)

# ── Constants ──────────────────────────────────────────────────────────────────

PIPELINE_VERSION = "0.1.0"

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
PROFILE_BG = {
    "wcag_strict":       "#dbeafe",
    "readability_first": "#dcfce7",
    "visual_first":      "#ffe4e6",
}
PROFILE_BORDER = {
    "wcag_strict":       "#93c5fd",
    "readability_first": "#86efac",
    "visual_first":      "#fca5a5",
}

SUBGROUPS = ["wcag", "text", "elements", "performance"]
SUBGROUP_LABELS = {
    "wcag":        "WCAG",
    "text":        "Text",
    "elements":    "Elements",
    "performance": "Rendiment",
}

ALL_METRICS = [
    "color_contrast_ratio", "focus_visible_ratio", "target_size_clean",
    "keyboard_clean", "aria_roles_valid", "accessible_names_coverage",
    "audit_critical_violations", "audit_high_violations",
    "audit_medium_violations", "audit_low_violations",
    "page_flesch", "text_complexity", "heading_hierarchy",
    "alt_text_coverage", "landmark_coverage", "performance_lcp",
]

METRIC_GROUPS = {
    "wcag": [
        "color_contrast_ratio", "focus_visible_ratio", "target_size_clean",
        "keyboard_clean", "audit_critical_violations", "audit_high_violations",
        "audit_medium_violations", "audit_low_violations",
    ],
    "text":     ["page_flesch", "text_complexity", "heading_hierarchy"],
    "elements": ["aria_roles_valid", "accessible_names_coverage", "alt_text_coverage", "landmark_coverage"],
    "performance": ["performance_lcp"],
}
METRIC_GROUP_MAP = {m: g for g, ms in METRIC_GROUPS.items() for m in ms}

METRIC_LABELS = {
    "color_contrast_ratio":      "Contrast de color",
    "focus_visible_ratio":       "Visibilitat del focus",
    "target_size_clean":         "Mida objectiu tàctil",
    "keyboard_clean":            "Navegació per teclat",
    "aria_roles_valid":          "Rols ARIA vàlids",
    "accessible_names_coverage": "Noms accessibles",
    "audit_critical_violations": "Violacions crítiques (axe)",
    "audit_high_violations":     "Violacions altes (axe)",
    "audit_medium_violations":   "Violacions mitjanes (axe)",
    "audit_low_violations":      "Violacions baixes (axe)",
    "page_flesch":               "Llegibilitat Flesch",
    "text_complexity":           "Complexitat textual",
    "heading_hierarchy":         "Jerarquia de capçaleres",
    "alt_text_coverage":         "Alt text d'imatges",
    "landmark_coverage":         "Landmarks de navegació",
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

PROFILE_WEIGHTS = {
    "wcag_strict":       [5, 4, 3, 5, 4, 5, 5, 4, 2, 1, 2, 1, 3, 5, 3, 2],
    "readability_first": [2, 1, 1, 1, 1, 2, 3, 2, 1, 0, 5, 5, 5, 3, 2, 1],
    "visual_first":      [4, 2, 3, 1, 2, 3, 2, 2, 1, 0, 2, 2, 2, 5, 2, 4],
}

CATEGORY_ORDER = ["Institucional", "Educatiu", "Cultural", "Mitjans", "Comercial"]
CATEGORY_COLORS = {
    "Institucional": "#1d4ed8",
    "Educatiu":      "#15803d",
    "Cultural":      "#7c3aed",
    "Mitjans":       "#c2410c",
    "Comercial":     "#0e7490",
}

# Notes interpretatives per a les 16 mètriques (TFM Capítol 4)
METRIC_NOTES: dict[str, dict[str, str]] = {
    "color_contrast_ratio": {
        "description": "Proporció de contrast entre el text/elements d'interfície i el fons de la pàgina.",
        "good": "Excel·lent contrast (ràtio ≥ 7:1). Text clarament llegible, incloent persones amb baixa visió.",
        "mid":  "Contrast acceptable però millorable. Algunes combinacions poden dificultar la lectura en dispositius mòbils o en condicions de llum adversa.",
        "bad":  "Contrast insuficient (< 4.5:1). Dificulta greument la lectura per a persones amb baixa visió, dèficit de percepció de color o en pantalla de baix contrast.",
        "wcag": "WCAG 1.4.3 AA: mínim 4.5:1 per a text normal; 3:1 per a text gran (≥ 18 pt o 14 pt negreta).",
    },
    "focus_visible_ratio": {
        "description": "Fracció d'elements interactius amb indicador de focus visible en la navegació per teclat.",
        "good": "Focus visible en gairebé tots els elements. Navegació per teclat plenament funcional i confortable.",
        "mid":  "Focus parcialment visible. Alguns elements són difícils d'identificar sense ús del ratolí.",
        "bad":  "Focus invisible o quasi absent. La navegació per teclat és inviable per a usuaris amb discapacitat motriu.",
        "wcag": "WCAG 2.4.7 AA: tot element interactiu ha de tenir un indicador de focus clarament visible.",
    },
    "target_size_clean": {
        "description": "Proporció d'elements interactius (botons, enllaços, formularis) que superen la mida mínima de 24×24 px.",
        "good": "La majoria d'elements tàctils superen la mida mínima. Adequat per a pantalles tàctils i usuaris amb tremolor.",
        "mid":  "Alguns elements massa petits per a una interacció tàctil confortable, especialment en dispositius mòbils.",
        "bad":  "Nombrosos elements per sota del mínim de 24 px. Dificulta l'ús per a persones amb tremolor o dificultats motrius.",
        "wcag": "WCAG 2.5.8 AA (2.2): mida mínima de 24×24 CSS px per als objectius tàctils.",
    },
    "keyboard_clean": {
        "description": "Ràtio d'elements interactius navegables per teclat sense trampes ni bloqueigs de focus.",
        "good": "Navegació per teclat completament funcional. Tots els elements accessibles sense necessitat de ratolí.",
        "mid":  "Navegació bàsica per teclat, però amb algunes limitacions o trampes de focus intermitents.",
        "bad":  "Trampes de focus o elements no accessibles per teclat. Bloqueja completament usuaris amb discapacitat motriu.",
        "wcag": "WCAG 2.1.1 A: tota funcionalitat disponible per ratolí ha de ser operable per teclat.",
    },
    "aria_roles_valid": {
        "description": "Proporció de rols i atributs ARIA correctament implementats respecte al total detectat.",
        "good": "ARIA usat correctament i coherentment. Les tecnologies d'assistència reben informació semàntica precisa.",
        "mid":  "Alguns rols ARIA mal formats o redundants que poden confondre els lectors de pantalla.",
        "bad":  "ARIA mal implementat o contradictori amb el HTML nadiu. Crea barreres greus per a lectors de pantalla.",
        "wcag": "WCAG 4.1.2 AA: els components de la IU han de tenir nom, rol i valor correctament exposats.",
    },
    "accessible_names_coverage": {
        "description": "Fracció d'elements interactius i imatges amb nom accessible (label, aria-label, aria-labelledby, alt).",
        "good": "Cobertura gairebé total. Els lectors de pantalla identifiquen correctament tots els elements.",
        "mid":  "Cobertura parcial. Alguns elements sense nom accessible dificulten la navegació amb lector de pantalla.",
        "bad":  "Molts elements sense nom accessible. Barreres greus i sistemàtiques per a usuaris de lectors de pantalla.",
        "wcag": "WCAG 4.1.2 AA + 1.1.1 A: tots els elements d'IU i imatges informatives han de tenir nom accessible.",
    },
    "audit_critical_violations": {
        "description": "Nombre de violacions WCAG de nivell crític detectades per axe-core. Penalització: −0.15 per violació.",
        "good": "Cap violació crítica. La pàgina compleix els requisits bàsics d'accessibilitat normativa.",
        "mid":  "Algunes violacions crítiques presents. Cal corregir-les per assolir conformitat WCAG 2.1 AA.",
        "bad":  "Múltiples violacions crítiques. La pàgina incompleix greument els requisits obligatoris d'accessibilitat.",
        "wcag": "Les violacions crítiques d'axe-core corresponen a criteris WCAG nivell A/AA obligatoris per EN 301 549.",
    },
    "audit_high_violations": {
        "description": "Nombre de violacions WCAG greus detectades per axe-core. Penalització: −0.05 per violació.",
        "good": "Cap violació greu. Excel·lent conformitat amb els criteris WCAG principals.",
        "mid":  "Algunes violacions greus. Recomanable resoldre-les per millorar l'accessibilitat global.",
        "bad":  "Múltiples violacions greus. Impacte significatiu en la usabilitat per a usuaris amb discapacitat.",
        "wcag": "Les violacions greus corresponen majoritàriament a criteris WCAG AA que afecten directament la usabilitat.",
    },
    "audit_medium_violations": {
        "description": "Nombre de violacions WCAG moderades detectades per axe-core. Penalització: −0.02 per violació.",
        "good": "Cap violació moderada. Molt bon nivell d'accessibilitat en els criteris d'avaluació automàtica.",
        "mid":  "Violacions moderades presents però manejables. Recomanable atendre-les en el cicle de millora.",
        "bad":  "Nombroses violacions moderades. Indiquen patrons problemàtics sistemàtics en el disseny de la pàgina.",
        "wcag": "Les violacions moderades afecten criteris de suport d'accessibilitat i bones pràctiques WCAG.",
    },
    "audit_low_violations": {
        "description": "Nombre de violacions WCAG de baixa severitat per axe-core. Penalització: −0.01 per violació.",
        "good": "Cap violació de baixa severitat. Excel·lent adherència als criteris WCAG menors i bones pràctiques.",
        "mid":  "Poques violacions de baixa severitat. Impacte limitat però recomanable revisar-les.",
        "bad":  "Moltes violacions de baixa severitat. Tot i l'impacte individual reduït, indiquen manca d'atenció al detall.",
        "wcag": "Les violacions de baixa severitat corresponen a bones pràctiques i criteris WCAG AAA opcionals.",
    },
    "page_flesch": {
        "description": "Índex Flesch Reading Ease del contingut textual principal. Escala 0–100: >60 llegible; >80 molt fàcil.",
        "good": "Text molt llegible (Flesch > 60). Adequat per a audiències generals, dislèxia i cognició reduïda.",
        "mid":  "Llegibilitat acceptable però textos complexos. Recomanable simplificar algunes seccions clau.",
        "bad":  "Text massa complex (Flesch < 30). Barreres cognitives importants per a usuaris amb dificultats lectores.",
        "wcag": "WCAG 3.1.5 AAA: contingut comprensible sense educació secundària. Flesch > 60 com a referència operativa.",
    },
    "text_complexity": {
        "description": "Mesura composta de complexitat textual: longitud de frases, proporció de paraules difícils i estructura.",
        "good": "Baixa complexitat. Text directe, concís i accessible per a la majoria d'usuaris.",
        "mid":  "Complexitat moderada. Algunes frases llargues o vocabulari especialitzat que pot dificultar la comprensió.",
        "bad":  "Alta complexitat textual. Barreres cognitives significatives per a persones amb discapacitat cognitiva o baixa alfabetització.",
        "wcag": "WCAG 3.1 AA + principi de comprensibilitat POUR: el contingut textual ha de ser clar i concís.",
    },
    "heading_hierarchy": {
        "description": "Correctesa de la jerarquia de capçaleres HTML (H1 → H2 → H3... sense salts ni redundàncies).",
        "good": "Jerarquia de capçaleres perfecta. Estructura lògica i navegació eficient per a lectors de pantalla.",
        "mid":  "Jerarquia majoritàriament correcta però amb algunes anomalies o salts de nivell.",
        "bad":  "Jerarquia de capçaleres trencada. Desorientació per a usuaris de lectors de pantalla i cercadors.",
        "wcag": "WCAG 1.3.1 A: la informació i l'estructura han de poder determinar-se programàticament.",
    },
    "alt_text_coverage": {
        "description": "Fracció d'imatges i SVGs informatius amb text alternatiu significatiu i no genèric.",
        "good": "Cobertura total o gairebé total d'alt text. Imatges plenament accessibles per a usuaris invidents.",
        "mid":  "Cobertura parcial. Algunes imatges informatives sense descripció accessible o amb alt text genèric.",
        "bad":  "Moltes imatges sense alt text o amb alt text buit/genèric. Pèrdua crítica d'informació per a lectors de pantalla.",
        "wcag": "WCAG 1.1.1 A: tot contingut no textual informatiu ha de tenir una alternativa textual equivalent.",
    },
    "landmark_coverage": {
        "description": "Presència i cobertura dels landmarks HTML5/ARIA principals (main, nav, header, footer, aside).",
        "good": "Tots els landmarks principals presents. Navegació regional eficient per als lectors de pantalla.",
        "mid":  "Alguns landmarks presents però cobertura incompleta. Navegació regional parcialment limitada.",
        "bad":  "Absència de landmarks estructurals. Els lectors de pantalla han de llegir la pàgina sencera linealment.",
        "wcag": "WCAG 1.3.6 AAA + bones pràctiques ARIA Landmarks: estructurar el contingut per a navegació eficient.",
    },
    "performance_lcp": {
        "description": "Largest Contentful Paint (LCP): temps fins al renderitzat de l'element principal visible (en ms).",
        "good": "LCP ≤ 2.5 s. Càrrega ràpida. Bona experiència percebuda, fins i tot en connexions lentes o dispositius modestos.",
        "mid":  "LCP entre 2.5 s i 4 s. Càrrega acceptable però pot frustrar usuaris amb connexions limitades.",
        "bad":  "LCP > 4 s. Càrrega molt lenta. Barreres d'accessibilitat per a usuaris amb connexions lentes o dispositius antics.",
        "wcag": "EN 301 549 §9.1.4.4 + Core Web Vitals Google: LCP < 2.5 s com a referència de rendiment accessible.",
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Genera el lloc web estàtic complet de resultats ACI (Jinja2 + D3)"
    )
    p.add_argument("--results",   default="results/gh-pages",
                   help="Directori amb la sortida del pipeline (per defecte: results/gh-pages)")
    p.add_argument("--output",    default="docs",
                   help="Directori de sortida (per defecte: docs)")
    p.add_argument("--templates", default=None,
                   help="Directori de templates Jinja2 (per defecte: templates/ a l'arrel del projecte)")
    return p.parse_args(argv)


def metric_level(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 0.70:
        return "good"
    if value >= 0.40:
        return "mid"
    return "bad"


def aci_level(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 4.0:
        return "excellent"
    if score >= 3.0:
        return "good"
    if score >= 2.5:
        return "acceptable"
    return "poor"


def aci_label(score: float | None) -> str:
    return {
        "excellent": "Excel·lent",
        "good":      "Bo",
        "acceptable": "Acceptable",
        "poor":      "Insuficient",
        "unknown":   "—",
    }.get(aci_level(score), "—")


def aci_color(score: float | None) -> str:
    if score is None:
        return "#888"
    if score >= 3.5:
        return "#27ae60"
    if score >= 2.5:
        return "#e67e22"
    return "#e74c3c"


def extract_slug(stem: str, profile: str, ts: int) -> str:
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


# ── Càrrega i agrupació ────────────────────────────────────────────────────────

def load_metrics(results_dir: Path) -> list[dict]:
    metrics_dir = results_dir / "metrics"
    if not metrics_dir.exists():
        print(f"  [WARN] Carpeta de mètriques no trobada: {metrics_dir}", file=sys.stderr)
        return []
    entries = []
    for f in sorted(metrics_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "aci_score" in data and "profile" in data:
                data["_file"] = f
                data["_stem"] = f.stem
                entries.append(data)
        except Exception as exc:
            print(f"  [WARN] Ignorat {f.name}: {exc}", file=sys.stderr)
    print(f"  {len(entries)} fitxer(s) de mètriques carregat(s)")
    return entries


def group_entries(entries: list[dict]) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for entry in entries:
        raw_url   = entry.get("url", "")
        clean_url = raw_url.split(";")[0].strip()
        category  = raw_url.split(";")[1].strip() if ";" in raw_url else ""
        domain    = clean_url.replace("https://", "").replace("http://", "").split("/")[0]
        profile   = entry.get("profile", "")
        if not clean_url or not profile:
            continue
        if clean_url not in grouped:
            grouped[clean_url] = {
                "url": clean_url, "domain": domain, "category": category, "profiles": {}
            }
        existing = grouped[clean_url]["profiles"].get(profile)
        if existing is None or entry.get("timestamp", 0) > existing.get("timestamp", 0):
            grouped[clean_url]["profiles"][profile] = entry
    return grouped


# ── Anotació de mètriques ──────────────────────────────────────────────────────

def annotate_metrics(
    normalized_metrics: dict[str, float],
    raw_values: dict[str, Any],
    weights: dict[str, int],
) -> list[dict]:
    result = []
    for m in ALL_METRICS:
        norm  = normalized_metrics.get(m)
        raw   = (raw_values or {}).get(m)
        w     = weights.get(m, 0)
        lvl   = metric_level(norm)
        notes = METRIC_NOTES.get(m, {})
        result.append({
            "key":         m,
            "label":       METRIC_LABELS.get(m, m),
            "normalized":  norm,
            "pct":         int((norm or 0) * 100),
            "raw":         raw,
            "weight":      w,
            "level":       lvl,
            "description": notes.get("description", ""),
            "note":        notes.get(lvl) or notes.get("mid", ""),
            "wcag":        METRIC_WCAG.get(m, "—"),
            "group":       METRIC_GROUP_MAP.get(m, ""),
        })
    return result


# ── Cerca d'HTML del pipeline ──────────────────────────────────────────────────

def find_report_html(results_dir: Path, slug: str, ts: int, profile: str) -> Path | None:
    exact = results_dir / "reports" / slug / f"{slug}_{ts}_{profile}.html"
    if exact.exists():
        return exact
    folder = results_dir / "reports" / slug
    if folder.is_dir():
        candidates = sorted(folder.glob(f"*_{profile}.html"))
        if candidates:
            return candidates[-1]
    return None


def find_comparative_html(results_dir: Path, slug: str) -> Path | None:
    folder = results_dir / "reports" / slug
    if not folder.is_dir():
        return None
    candidates = sorted(folder.glob("*_comparative.html"))
    return candidates[-1] if candidates else None


# ── Construcció de l'estructura de dades ──────────────────────────────────────

def build_sites(grouped: dict[str, dict], results_dir: Path) -> list[dict]:
    sites = []
    for clean_url, data in grouped.items():
        site: dict[str, Any] = {
            "url": clean_url, "domain": data["domain"],
            "category": data["category"], "profiles": {},
        }
        first_slug = None
        for profile, entry in data["profiles"].items():
            ts   = entry.get("timestamp", 0)
            stem = entry.get("_stem", "")
            slug = extract_slug(stem, profile, ts) if stem else data["domain"].replace(".", "_")[:40]
            if first_slug is None:
                first_slug = slug
                site["slug"] = slug

            nm  = entry.get("normalized_metrics", {})
            raw = entry.get("raw_values", {})
            wts = entry.get("weights", {})
            if not wts:
                wts = {m: w for m, w in zip(ALL_METRICS, PROFILE_WEIGHTS.get(profile, [0] * 16))}

            ts_human = (
                datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                if ts else "—"
            )

            site["profiles"][profile] = {
                "aci_score":          entry.get("aci_score"),
                "aci_normalized":     entry.get("aci_normalized"),
                "sub_scores":         entry.get("sub_scores", {}),
                "normalized_metrics": nm,
                "raw_values":         raw,
                "weights":            wts,
                "interventions":      entry.get("top_interventions", []),
                "axe_violations":     entry.get("axe_violations", []),
                "text_metrics":       entry.get("text_metrics", {}),
                "perf":               entry.get("performance", {}),
                "screenshot_path":    entry.get("screenshot_path"),
                "timestamp":          ts,
                "timestamp_human":    ts_human,
                "slug":               slug,
                "annotated_metrics":  annotate_metrics(nm, raw, wts),
            }

        acis = [v["aci_score"] for v in site["profiles"].values() if v.get("aci_score") is not None]
        site["aci_best"]  = max(acis) if acis else None
        site["aci_worst"] = min(acis) if acis else None
        site["aci_mean"]  = round(sum(acis) / len(acis), 3) if acis else None
        site["slug"]      = site.get("slug") or data["domain"].replace(".", "_")[:40]
        sites.append(site)

    sites.sort(key=lambda s: s["aci_best"] or 0, reverse=True)
    return sites


# ── Entorn Jinja2 ──────────────────────────────────────────────────────────────

def get_jinja_env(templates_dir: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson"]    = lambda obj: json.dumps(obj, ensure_ascii=False)
    env.filters["aci_color"] = aci_color
    env.filters["aci_label"] = aci_label
    env.filters["aci_level"] = aci_level
    return env


# ── Renderitzat d'informes individuals ────────────────────────────────────────

def render_individual_reports(
    sites: list[dict], output_dir: Path, env: jinja2.Environment
) -> None:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    template = env.get_template("report.html.j2")
    n = 0
    for site in sites:
        slug = site["slug"]
        for profile, pd in site["profiles"].items():
            am = pd["annotated_metrics"]
            ctx = {
                "url":               site["url"],
                "clean_url":         site["url"],
                "domain":            site["domain"],
                "category":          site["category"],
                "slug":              slug,
                "profile":           profile,
                "profile_label":     PROFILE_LABELS.get(profile, profile),
                "profile_color":     PROFILE_COLORS.get(profile, "#333"),
                "profile_bg":        PROFILE_BG.get(profile, "#f8f9fa"),
                "timestamp":         pd["timestamp_human"],
                "pipeline_version":  PIPELINE_VERSION,
                "aci_score":         pd["aci_score"] or 0,
                "aci_normalized":    pd["aci_normalized"] or 0,
                "aci_label":         aci_label(pd["aci_score"]),
                "aci_color":         aci_color(pd["aci_score"]),
                "sub_scores":        pd["sub_scores"],
                "normalized_metrics": pd["normalized_metrics"],
                "raw_values":        pd["raw_values"],
                "weights":           pd["weights"],
                "annotated_metrics": am,
                "interventions":     pd["interventions"],
                "axe_violations":    pd["axe_violations"],
                "text_metrics":      pd["text_metrics"],
                "perf":              pd["perf"],
                "screenshot_path":   pd["screenshot_path"],
                "web_type":          site["category"],
                "all_profiles":      site["profiles"],
                "profiles_list":     PROFILES,
                "profile_labels":    PROFILE_LABELS,
                "profile_colors":    PROFILE_COLORS,
                "profile_bg":        PROFILE_BG,
                "profile_border":    PROFILE_BORDER,
                "subgroups":         SUBGROUPS,
                "subgroup_labels":   SUBGROUP_LABELS,
                "comparative_url":   site.get("comparative_url", ""),
                "metrics_json": json.dumps(
                    [{"key": a["key"], "label": a["label"],
                      "normalized": a["normalized"] or 0,
                      "weight": a["weight"], "group": a["group"], "level": a["level"]}
                     for a in am], ensure_ascii=False
                ),
                "sub_scores_json": json.dumps(
                    [{"name": g, "label": SUBGROUP_LABELS[g],
                      "value": pd["sub_scores"].get(g) or 0}
                     for g in SUBGROUPS], ensure_ascii=False
                ),
            }
            dst = reports_dir / f"{slug}_{profile}.html"
            dst.write_text(template.render(**ctx), encoding="utf-8")
            site["profiles"][profile]["report_url"] = f"reports/{slug}_{profile}.html"
            n += 1
            print(f"    ✓  {dst.name}")
    print(f"  {n} informe(s) individual(s)")


# ── Renderitzat d'informes comparatius ────────────────────────────────────────

def render_comparative_reports(
    sites: list[dict], output_dir: Path, env: jinja2.Environment
) -> None:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    template = env.get_template("comparative.html.j2")
    n = 0
    for site in sites:
        if len(site["profiles"]) < 2:
            continue
        slug = site["slug"]

        # Radar data: [{profile, label, color, wcag, text, elements, performance}]
        radar_data = []
        for p in PROFILES:
            pd = site["profiles"].get(p)
            if pd:
                ss = pd["sub_scores"]
                radar_data.append({
                    "profile": p, "label": PROFILE_LABELS[p], "color": PROFILE_COLORS[p],
                    "wcag": ss.get("wcag") or 0, "text": ss.get("text") or 0,
                    "elements": ss.get("elements") or 0, "performance": ss.get("performance") or 0,
                })

        # Bar data: [{metric, label, group, wcag_strict, readability_first, visual_first}]
        ref_am = (site["profiles"].get(PROFILES[0]) or next(iter(site["profiles"].values()), {})).get(
            "annotated_metrics", []
        )
        bar_data = []
        for a in ref_am:
            entry = {"metric": a["key"], "label": a["label"], "group": a["group"]}
            for p in PROFILES:
                pd = site["profiles"].get(p, {})
                entry[p] = (pd.get("normalized_metrics") or {}).get(a["key"]) or 0
            bar_data.append(entry)

        ctx = {
            "url": site["url"], "clean_url": site["url"], "domain": site["domain"],
            "category": site["category"], "slug": slug,
            "timestamp": next((v["timestamp_human"] for v in site["profiles"].values()), "—"),
            "pipeline_version": PIPELINE_VERSION,
            "profiles":         site["profiles"],
            "profiles_list":    PROFILES,
            "profile_labels":   PROFILE_LABELS,
            "profile_colors":   PROFILE_COLORS,
            "profile_bg":       PROFILE_BG,
            "profile_border":   PROFILE_BORDER,
            "subgroups":        SUBGROUPS,
            "subgroup_labels":  SUBGROUP_LABELS,
            "all_metrics":      ALL_METRICS,
            "metric_labels":    METRIC_LABELS,
            "web_type":         site["category"],
            "aci_label_fn":     aci_label,
            "aci_color_fn":     aci_color,
            "radar_data_json":  json.dumps(radar_data, ensure_ascii=False),
            "bar_data_json":    json.dumps(bar_data, ensure_ascii=False),
        }
        dst = reports_dir / f"{slug}_comparative.html"
        dst.write_text(template.render(**ctx), encoding="utf-8")
        site["comparative_url"] = f"reports/{slug}_comparative.html"
        n += 1
        print(f"    ✓  {dst.name}")
    print(f"  {n} informe(s) comparatiu(s)")


# ── Renderitzat de l'índex global ─────────────────────────────────────────────

def render_index(
    sites: list[dict], output_dir: Path, env: jinja2.Environment, ts_build: str
) -> None:
    template = env.get_template("index.html.j2")

    all_acis = [s["aci_best"] for s in sites if s["aci_best"] is not None]
    kpi_n    = len(sites)
    kpi_mean = round(sum(all_acis) / len(all_acis), 3) if all_acis else None
    kpi_max  = round(max(all_acis), 3) if all_acis else None
    kpi_min  = round(min(all_acis), 3) if all_acis else None

    # Dades per a la taula JS
    table_rows = []
    for s in sites:
        table_rows.append({
            "url": s["url"], "domain": s["domain"], "category": s["category"],
            "aci_best": s["aci_best"],
            "profiles": {
                p: {
                    "aci":    s["profiles"][p]["aci_score"] if p in s["profiles"] else None,
                    "report": s["profiles"][p].get("report_url") if p in s["profiles"] else None,
                }
                for p in PROFILES
            },
            "comparative": s.get("comparative_url"),
        })

    # Ranking per D3 (totes les URLs)
    ranking_data = [
        {
            "domain":   s["domain"],
            "category": s["category"],
            "color":    CATEGORY_COLORS.get(s["category"], "#888"),
            "aci":      s["aci_best"] or 0,
            "url":      s.get("comparative_url") or next(
                (v.get("report_url") for v in s["profiles"].values() if v.get("report_url")), "#"
            ),
        }
        for s in sites
    ]

    # Mitjanes per categoria i perfil
    cat_lists: dict[str, dict[str, list]] = {c: {p: [] for p in PROFILES} for c in CATEGORY_ORDER}
    for s in sites:
        cat = s["category"]
        if cat in cat_lists:
            for p in PROFILES:
                pd = s["profiles"].get(p)
                if pd and pd["aci_score"] is not None:
                    cat_lists[cat][p].append(pd["aci_score"])
    category_data = []
    for cat in CATEGORY_ORDER:
        entry = {"category": cat, "color": CATEGORY_COLORS.get(cat, "#888")}
        for p in PROFILES:
            vals = cat_lists[cat][p]
            entry[p] = round(sum(vals) / len(vals), 3) if vals else None
        if any(entry.get(p) is not None for p in PROFILES):
            category_data.append(entry)

    # Heatmap: flatten a [{domain, metric, value, category}]
    heatmap_data = []
    for s in sites:
        pd = s["profiles"].get("wcag_strict") or next(iter(s["profiles"].values()), None)
        if not pd:
            continue
        nm = pd.get("normalized_metrics", {})
        for m in ALL_METRICS:
            heatmap_data.append({
                "domain":   s["domain"],
                "metric":   m,
                "value":    nm.get(m),
                "category": s["category"],
            })

    ctx = {
        "ts_build":           ts_build,
        "pipeline_version":   PIPELINE_VERSION,
        "n_urls":             kpi_n,
        "kpi_mean":           kpi_mean,
        "kpi_max":            kpi_max,
        "kpi_min":            kpi_min,
        "categories":         [c for c in CATEGORY_ORDER if any(s["category"] == c for s in sites)],
        "category_colors":    CATEGORY_COLORS,
        "sites":              sites,
        "profiles":           PROFILES,
        "profile_labels":     PROFILE_LABELS,
        "profile_colors":     PROFILE_COLORS,
        "all_metrics":        ALL_METRICS,
        "metric_labels":      METRIC_LABELS,
        "metric_wcag":        METRIC_WCAG,
        "metric_notes":       METRIC_NOTES,
        "subgroups":          SUBGROUPS,
        "subgroup_labels":    SUBGROUP_LABELS,
        "profile_weights":    PROFILE_WEIGHTS,
        "table_rows_json":    json.dumps(table_rows, ensure_ascii=False),
        "ranking_data_json":  json.dumps(ranking_data, ensure_ascii=False),
        "category_data_json": json.dumps(category_data, ensure_ascii=False),
        "heatmap_data_json":  json.dumps(heatmap_data, ensure_ascii=False),
    }
    (output_dir / "index.html").write_text(template.render(**ctx), encoding="utf-8")
    print(f"  index.html: {kpi_n} URL(s)")


# ── Generació de fitxers de dades ─────────────────────────────────────────────

def generate_results_json(sites: list[dict], output_dir: Path, ts_build: str) -> None:
    results = []
    for s in sites:
        item = {
            "url": s["url"], "domain": s["domain"], "category": s["category"],
            "aci_best": s["aci_best"], "profiles": {},
            "comparative": s.get("comparative_url"),
        }
        for p, pd in s["profiles"].items():
            item["profiles"][p] = {
                "aci_score": pd["aci_score"], "sub_scores": pd["sub_scores"],
                "normalized_metrics": pd["normalized_metrics"], "report": pd.get("report_url"),
            }
        results.append(item)
    out = {
        "generated_at": ts_build, "pipeline_version": PIPELINE_VERSION,
        "n_urls": len(results), "results": results,
    }
    (output_dir / "results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  results.json: {len(results)} URL(s)")


def generate_scores_csv(sites: list[dict], output_dir: Path) -> None:
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = ["url", "domain", "category"]
    for p in PROFILES:
        fieldnames.append(f"aci_{p}")
    for m in ALL_METRICS:
        for p in PROFILES:
            fieldnames.append(f"{m}_{p}")
    rows = []
    for s in sites:
        row = {"url": s["url"], "domain": s["domain"], "category": s["category"]}
        for p in PROFILES:
            pd = s["profiles"].get(p, {})
            row[f"aci_{p}"] = pd.get("aci_score", "")
            nm = pd.get("normalized_metrics", {})
            for m in ALL_METRICS:
                row[f"{m}_{p}"] = nm.get(m, "")
        rows.append(row)
    with open(data_dir / "scores.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  scores.csv: {len(rows)} fila(es)")


def generate_manifest(sites: list[dict], output_dir: Path) -> None:
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest = [
        {
            "url": s["url"], "domain": s["domain"],
            "profile_reports": {p: pd.get("report_url") for p, pd in s["profiles"].items()
                                if pd.get("report_url")},
            "comparative_report": s.get("comparative_url"),
        }
        for s in sites
    ]
    (data_dir / "reports_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  reports_manifest.json: {len(manifest)} entrada(es)")


def copy_static(output_dir: Path) -> None:
    for candidate in [Path("static"), Path(__file__).parent.parent / "static"]:
        if candidate.is_dir():
            dst = output_dir / "static"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(candidate, dst)
            print(f"  static/ → docs/static/")
            return
    print("  [INFO] static/ no trobat; s'omet la còpia")


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    args = parse_args(argv)
    results_dir   = Path(args.results)
    output_dir    = Path(args.output)
    templates_dir = (
        Path(args.templates) if args.templates
        else Path(__file__).parent.parent / "templates"
    )

    print(f"\nrender_reports.py — ACI Pipeline v{PIPELINE_VERSION}")
    print(f"  Resultats  : {results_dir.resolve()}")
    print(f"  Sortida    : {output_dir.resolve()}")
    print(f"  Templates  : {templates_dir.resolve()}\n")

    if not templates_dir.is_dir():
        print(f"ERROR: directori de templates no trobat: {templates_dir}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    ts_build = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("[1] Carregant mètriques…")
    entries = load_metrics(results_dir)

    print("[2] Agrupant per URL…")
    grouped = group_entries(entries)
    print(f"  {len(grouped)} URL(s) úniques")

    if not grouped:
        print("\n  [WARN] Cap resultat. Comprova que el pipeline ha generat JSONs.")
        return 0

    print("[3] Construint estructura de dades…")
    sites = build_sites(grouped, results_dir)

    print("[4] Preparant entorn Jinja2…")
    env = get_jinja_env(templates_dir)

    print("[5] Renderitzant informes individuals…")
    render_individual_reports(sites, output_dir, env)

    print("[6] Renderitzant informes comparatius…")
    render_comparative_reports(sites, output_dir, env)

    print("[7] Renderitzant índex global…")
    render_index(sites, output_dir, env, ts_build)

    print("[8] Generant manifest…")
    generate_manifest(sites, output_dir)

    print("[9] Generant results.json…")
    generate_results_json(sites, output_dir, ts_build)

    print("[10] Generant scores.csv…")
    generate_scores_csv(sites, output_dir)

    print("[11] Copiant assets estàtics…")
    copy_static(output_dir)

    n_rep = len(list((output_dir / "reports").glob("*.html")))
    print(f"\n✓  Lloc generat: {output_dir.resolve()}")
    print(f"   {len(sites)} URL(s) · {n_rep} informe(s) HTML\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
