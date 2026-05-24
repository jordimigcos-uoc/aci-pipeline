#!/usr/bin/env python3
"""
scripts/build_site.py  —  Genera el lloc estàtic de resultats ACI per a GitHub Pages.

Llegeix la sortida del pipeline (results/<run>/) i genera:
  docs/
    index.html                  — Dashboard comparatiu (dades embegudes, sense fetch)
    results.json                — Dades consolidades
    data/
      reports_manifest.json     — Manifest de navegació entre perfils
      scores.csv                — Exportació CSV
    reports/
      <slug>_<profile>.html     — Informe individual per URL·perfil
      <slug>_comparative.html   — Informe comparatiu (si disponible)
    static/                     — Assets CSS copiats des de static/

Ús:
  python scripts/build_site.py
  python scripts/build_site.py --results results/gh-pages --output docs
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

PIPELINE_VERSION = "0.1.0"

PROFILES = ["wcag_strict", "readability_first", "visual_first"]
PROFILE_LABELS = {
    "wcag_strict":       "WCAG Strict",
    "readability_first": "Readability",
    "visual_first":      "Visual First",
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

# Pesos per perfil (en el mateix ordre que ALL_METRICS)
_W_WCAG = [5, 4, 3, 5, 4, 5, 5, 4, 2, 1, 2, 1, 3, 5, 3, 2]
_W_READ = [2, 1, 1, 1, 1, 2, 3, 2, 1, 0, 5, 5, 5, 3, 2, 1]
_W_VIS  = [4, 2, 3, 1, 2, 3, 2, 2, 1, 0, 2, 2, 2, 5, 2, 4]


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Genera el lloc web estàtic de resultats ACI per a GitHub Pages"
    )
    p.add_argument(
        "--results", default="results/gh-pages",
        help="Directori amb la sortida del pipeline (per defecte: results/gh-pages)",
    )
    p.add_argument(
        "--output", default="docs",
        help="Directori de sortida del lloc web (per defecte: docs)",
    )
    return p.parse_args(argv)


def extract_slug(stem: str, profile: str, ts: int) -> str:
    """Extreu el slug del nom de fitxer '{slug}_{ts}_{profile}'."""
    suffix = f"_{ts}_{profile}"
    if stem.endswith(suffix):
        return stem[: -len(suffix)]
    # Fallback: elimina el darrer segment numèric i el perfil
    parts = stem.split("_")
    n_profile = len(profile.split("_"))
    if parts[-n_profile:] == profile.split("_"):
        parts = parts[:-n_profile]
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return "_".join(parts) or stem


def aci_color(score) -> str:
    if score is None:  return "#888"
    if score >= 3.5:   return "#27ae60"
    if score >= 2.5:   return "#e67e22"
    return "#e74c3c"


# ── Càrrega de mètriques ───────────────────────────────────────────────────────

def load_metrics(results_dir: Path) -> list[dict]:
    """Carrega tots els JSONs de mètriques de {results_dir}/metrics/."""
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
    """
    Agrupa les entrades per URL (la part abans de ';').
    Per a cada URL·perfil, conserva únicament l'entrada amb el timestamp més recent.
    Retorna {clean_url: {"url", "domain", "category", "profiles": {profile: entry}}}
    """
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
                "url":      clean_url,
                "domain":   domain,
                "category": category,
                "profiles": {},
            }

        existing = grouped[clean_url]["profiles"].get(profile)
        if existing is None or entry.get("timestamp", 0) > existing.get("timestamp", 0):
            grouped[clean_url]["profiles"][profile] = entry

    return grouped


# ── Cerca d'informes HTML ─────────────────────────────────────────────────────

def find_report_html(results_dir: Path, slug: str, ts: int, profile: str) -> Path | None:
    """Cerca l'informe HTML generat per M8 per a un slug·ts·perfil concret."""
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
    """Cerca l'informe comparatiu de M8."""
    folder = results_dir / "reports" / slug
    if not folder.is_dir():
        return None
    candidates = sorted(folder.glob("*_comparative.html"))
    return candidates[-1] if candidates else None


# ── Correcció de rutes als informes ───────────────────────────────────────────
# Els templates generen HTML a reports/{slug}/ (2 nivells sota data_dir).
# Nosaltres copiem a docs/reports/ (1 nivell sota docs/).
# Correcció: ../../ → ../

_PATH_SUBS = [
    # CSS extern: ajusta la profunditat
    (re.compile(r'(href|src)="\.\.\/\.\.\/static/'), r'\1="../static/'),
    (re.compile(r"(href|src)='\.\.\/\.\.\/static/"), r"\1='../static/"),
    # index.html i altres pàgines de primer nivell
    (re.compile(r'href="\.\.\/\.\.\/index\.html"'),  'href="../index.html"'),
    (re.compile(r"href='\.\.\/\.\.\/index\.html'"),  "href='../index.html'"),
    # Manifest JSON (fetch)
    (re.compile(r"'\.\.\/\.\.\/data/"),              "'../data/"),
    (re.compile(r'"\.\.\/\.\.\/data/'),              '"../data/'),
    # Screenshots (assets): ajusta la profunditat
    (re.compile(r'src="\.\.\/\.\.\/assets/'),        'src="../assets/'),
]


def fix_paths(html: str) -> str:
    """Corregeix les rutes relatives per a la ubicació docs/reports/<slug>.html."""
    for pattern, replacement in _PATH_SUBS:
        html = pattern.sub(replacement, html)
    return html


# ── Còpia d'informes HTML ─────────────────────────────────────────────────────

def copy_reports(
    grouped: dict[str, dict],
    results_dir: Path,
    output_dir: Path,
) -> list[dict]:
    """
    Copia els informes HTML a docs/reports/ amb rutes corregides.
    Retorna el manifest per a la navegació entre perfils (reports_manifest.json).
    """
    reports_out = output_dir / "reports"
    reports_out.mkdir(parents=True, exist_ok=True)

    manifest = []

    for clean_url, data in grouped.items():
        entry = {
            "url":               clean_url,
            "domain":            data["domain"],
            "profile_reports":   {},
            "comparative_report": None,
        }

        first_slug = None
        for profile, metrics in data["profiles"].items():
            ts   = metrics.get("timestamp", 0)
            stem = metrics.get("_stem", "")
            slug = extract_slug(stem, profile, ts) if stem else data["domain"].replace(".", "_")[:40]
            if first_slug is None:
                first_slug = slug

            src = find_report_html(results_dir, slug, ts, profile)
            if src:
                dst_name = f"{slug}_{profile}.html"
                dst = reports_out / dst_name
                html = fix_paths(src.read_text(encoding="utf-8"))
                dst.write_text(html, encoding="utf-8")
                entry["profile_reports"][profile] = f"reports/{dst_name}"
                data["profiles"][profile]["_report_url"] = f"reports/{dst_name}"
                print(f"    ✓  {dst_name}")
            else:
                print(f"    –  [{profile}] HTML no trobat per slug={slug}")

        # Informe comparatiu
        if first_slug:
            src_cmp = find_comparative_html(results_dir, first_slug)
            if src_cmp:
                dst_name = f"{first_slug}_comparative.html"
                dst = reports_out / dst_name
                html = fix_paths(src_cmp.read_text(encoding="utf-8"))
                dst.write_text(html, encoding="utf-8")
                entry["comparative_report"] = f"reports/{dst_name}"
                print(f"    ✓  {dst_name} (comparative)")

        manifest.append(entry)

    return manifest


# ── Generació de fitxers de dades ─────────────────────────────────────────────

def generate_results_json(grouped: dict[str, dict], output_dir: Path, ts_build: str) -> None:
    """Genera docs/results.json amb les dades consolidades."""
    results = []
    for clean_url, data in grouped.items():
        item = {
            "url":      clean_url,
            "domain":   data["domain"],
            "category": data["category"],
            "profiles": {},
        }
        for profile, metrics in data["profiles"].items():
            item["profiles"][profile] = {
                "aci_score":          metrics.get("aci_score"),
                "sub_scores":         metrics.get("sub_scores", {}),
                "normalized_metrics": metrics.get("normalized_metrics", {}),
                "report":             metrics.get("_report_url"),
            }
        acis = [v.get("aci_score", 0) for v in item["profiles"].values()
                if v.get("aci_score") is not None]
        item["aci_best"] = round(max(acis), 3) if acis else None
        results.append(item)

    results.sort(key=lambda r: r.get("aci_best") or 0, reverse=True)

    out = {
        "generated_at":     ts_build,
        "pipeline_version": PIPELINE_VERSION,
        "n_urls":           len(results),
        "results":          results,
    }
    (output_dir / "results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  results.json: {len(results)} URL(s)")


def generate_scores_csv(grouped: dict[str, dict], output_dir: Path) -> None:
    """Genera docs/data/scores.csv per a descàrrega."""
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = ["url", "domain", "category"]
    for p in PROFILES:
        fieldnames.append(f"aci_{p}")
    for m in ALL_METRICS:
        for p in PROFILES:
            fieldnames.append(f"{m}_{p}")

    rows = []
    for clean_url, data in grouped.items():
        row: dict = {
            "url":      clean_url,
            "domain":   data["domain"],
            "category": data["category"],
        }
        for p in PROFILES:
            metrics = data["profiles"].get(p, {})
            row[f"aci_{p}"] = metrics.get("aci_score", "")
            nm = metrics.get("normalized_metrics", {})
            for m in ALL_METRICS:
                row[f"{m}_{p}"] = nm.get(m, "")
        rows.append(row)

    csv_path = data_dir / "scores.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  scores.csv: {len(rows)} fila(es), {len(fieldnames)} columnes")


def generate_manifest(manifest: list[dict], output_dir: Path) -> None:
    """Desa docs/data/reports_manifest.json per a la navegació entre perfils."""
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "reports_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  reports_manifest.json: {len(manifest)} entrada(es)")


# ── Generació de index.html ───────────────────────────────────────────────────

def _build_tbody(rows: list[dict]) -> str:
    """Genera el contingut <tbody> de la taula de resultats (HTML estàtic inicial)."""
    buf = io.StringIO()
    for i, row in enumerate(rows):
        cells = []
        cells.append(f'<td class="num">{i + 1}</td>')
        cells.append(
            f'<td>'
            f'<strong>{_esc(row["domain"])}</strong>'
            f'<br><small class="url-small">'
            f'<a href="{_esc(row["url"])}" target="_blank" rel="noopener">{_esc(row["url"])}</a>'
            f'</small></td>'
        )
        cells.append(f'<td><span class="cat-chip">{_esc(row["category"] or "—")}</span></td>')

        for p in PROFILES:
            pdata = row["profiles"].get(p, {})
            aci   = pdata.get("aci")
            rep   = pdata.get("report")
            if aci is not None:
                pct   = int(aci / 5 * 100)
                color = aci_color(aci)
                link  = f' <a href="{rep}" title="Informe {PROFILE_LABELS[p]}">📄</a>' if rep else ""
                cells.append(
                    f'<td data-val="{aci:.3f}">'
                    f'<span class="aci-num" style="color:{color}">{aci:.3f}</span>'
                    f'<div class="mini-bar"><div style="width:{pct}%;background:{color}"></div></div>'
                    f'{link}</td>'
                )
            else:
                cells.append('<td data-val="0"><span class="aci-dash">—</span></td>')

        buf.write(
            f'<tr data-cat="{_esc(row["category"])}" data-url="{_esc(row["url"])}">'
            + "".join(cells)
            + "</tr>\n"
        )
    return buf.getvalue()


def _build_metrics_table() -> str:
    """Genera la taula HTML de les 16 mètriques per a la secció de metodologia."""
    buf = io.StringIO()
    buf.write(
        '<table class="met-table" aria-label="Descripció de les 16 mètriques ACI">'
        "<thead><tr>"
        "<th>#</th><th>Mètrica</th><th>Nom</th><th>WCAG</th>"
        "<th title='WCAG Strict'>W</th>"
        "<th title='Readability First'>R</th>"
        "<th title='Visual First'>V</th>"
        "</tr></thead><tbody>\n"
    )
    for i, m in enumerate(ALL_METRICS):
        buf.write(
            f"<tr>"
            f'<td class="num">{i + 1}</td>'
            f"<td><code>{m}</code></td>"
            f"<td>{METRIC_LABELS.get(m, m)}</td>"
            f"<td><small>{METRIC_WCAG.get(m, '—')}</small></td>"
            f'<td class="num">{_W_WCAG[i]}</td>'
            f'<td class="num">{_W_READ[i]}</td>'
            f'<td class="num">{_W_VIS[i]}</td>'
            f"</tr>\n"
        )
    buf.write("</tbody></table>\n")
    return buf.getvalue()


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_index_html(
    grouped: dict[str, dict],
    output_dir: Path,
    ts_build: str,
) -> None:
    """
    Genera docs/index.html: dashboard complet, dades embegudes (sense fetch),
    taula ordenable/filtrable, secció de metodologia, i descàrregues.
    """
    # Prepara les dades per al JS
    rows_js: list[dict] = []
    for clean_url, data in grouped.items():
        row = {
            "url":      clean_url,
            "domain":   data["domain"],
            "category": data["category"],
            "profiles": {},
        }
        for p in PROFILES:
            m = data["profiles"].get(p, {})
            row["profiles"][p] = {
                "aci":    m.get("aci_score"),
                "report": m.get("_report_url"),
            }
        acis = [v["aci"] for v in row["profiles"].values() if v["aci"] is not None]
        row["aci_max"] = max(acis) if acis else None
        rows_js.append(row)

    rows_js.sort(key=lambda r: r["aci_max"] or 0, reverse=True)

    all_acis = [r["aci_max"] for r in rows_js if r["aci_max"] is not None]
    kpi_n    = len(rows_js)
    kpi_mean = f"{sum(all_acis) / len(all_acis):.3f}" if all_acis else "—"
    kpi_max  = f"{max(all_acis):.3f}" if all_acis else "—"
    kpi_min  = f"{min(all_acis):.3f}" if all_acis else "—"
    cats     = sorted({r["category"] for r in rows_js if r["category"]})
    cat_opts = "\n".join(f'<option value="{c}">{c}</option>' for c in cats)

    tbody_html    = _build_tbody(rows_js)
    metrics_table = _build_metrics_table()
    rows_json_str = json.dumps(rows_js, ensure_ascii=False)

    # Carrega el template (fitxer separat) o usa el inline
    tpl_path = Path(__file__).parent / "_index_template.html"
    if tpl_path.exists():
        template = tpl_path.read_text(encoding="utf-8")
    else:
        template = _INDEX_TEMPLATE

    html = (template
        .replace("__TS_BUILD__",      ts_build)
        .replace("__PIPELINE_VER__",  PIPELINE_VERSION)
        .replace("__KPI_N__",         str(kpi_n))
        .replace("__KPI_MEAN__",      kpi_mean)
        .replace("__KPI_MAX__",       kpi_max)
        .replace("__KPI_MIN__",       kpi_min)
        .replace("__CAT_OPTIONS__",   cat_opts)
        .replace("__TBODY__",         tbody_html)
        .replace("__METRICS_TABLE__", metrics_table)
        .replace("__ROWS_JSON__",     rows_json_str)
    )

    (output_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"  index.html: {kpi_n} URL(s)")


# ── Template inline de index.html ─────────────────────────────────────────────
# Uses __PLACEHOLDER__ substitutions (not f-strings) to allow literal CSS/JS braces.

_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ca">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ACI Pipeline — Dashboard de resultats</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f0f2f5; color: #1a1a2e; line-height: 1.5;
    }
    /* Header */
    header {
      background: linear-gradient(135deg, #001f3f 0%, #0056b3 100%);
      color: #fff; padding: 1.75rem 2rem 1.5rem;
    }
    header h1 { font-size: 1.65rem; font-weight: 800; letter-spacing: -0.5px; }
    header p  { margin-top: 0.35rem; opacity: 0.85; font-size: 0.93rem; }
    .header-meta {
      display: flex; gap: 1.5rem; flex-wrap: wrap;
      margin-top: 0.9rem; font-size: 0.78rem; opacity: 0.7;
    }
    /* Layout */
    main { max-width: 1200px; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
    /* Cards */
    .card {
      background: #fff; border-radius: 10px;
      box-shadow: 0 1px 8px rgba(0,0,0,.07); margin-bottom: 1.5rem; overflow: hidden;
    }
    .card-hd {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0.9rem 1.25rem; border-bottom: 1px solid #eee; background: #fafafa;
    }
    .card-hd h2 { font-size: 0.95rem; font-weight: 700; color: #333; }
    .card-body  { padding: 1.25rem; }
    /* KPIs */
    .kpi-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 1rem; margin-bottom: 1.5rem;
    }
    .kpi {
      background: #fff; border-radius: 10px; padding: 1.1rem 1rem; text-align: center;
      box-shadow: 0 1px 8px rgba(0,0,0,.07); border-top: 4px solid var(--kc, #0056b3);
    }
    .kpi-val { font-size: 2rem; font-weight: 800; color: var(--kc, #0056b3); }
    .kpi-lbl { font-size: 0.72rem; color: #777; margin-top: 0.3rem; text-transform: uppercase; letter-spacing: .5px; }
    /* Filtres */
    .filters {
      display: flex; gap: 0.75rem; flex-wrap: wrap; padding: 0.9rem 1.25rem;
      border-bottom: 1px solid #f0f0f0; align-items: center;
    }
    .filters input, .filters select {
      padding: 0.4rem 0.75rem; border: 1px solid #ddd; border-radius: 6px;
      font-size: 0.85rem; background: #fafafa; outline: none;
    }
    .filters input:focus, .filters select:focus { border-color: #0056b3; background: #fff; }
    .filters label { font-size: 0.78rem; color: #666; font-weight: 600; }
    .btn-reset {
      padding: 0.4rem 0.8rem; border: 1px solid #ddd; border-radius: 6px;
      font-size: 0.78rem; background: none; cursor: pointer; color: #666;
    }
    .btn-reset:hover { background: #f0f0f0; }
    /* Taula */
    .tbl-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; min-width: 560px; }
    thead { background: #f0f4f8; }
    th {
      padding: 0.65rem 0.85rem; text-align: left; font-size: 0.72rem;
      font-weight: 700; color: #444; text-transform: uppercase;
      letter-spacing: .5px; cursor: pointer; user-select: none; white-space: nowrap;
    }
    th:hover { background: #e2eaf3; }
    th.sort-asc::after  { content: " ▲"; opacity: .6; }
    th.sort-desc::after { content: " ▼"; opacity: .6; }
    td { padding: 0.55rem 0.85rem; border-bottom: 1px solid #f0f0f0; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #f5f9ff; }
    td.num { text-align: right; color: #999; font-size: 0.8rem; font-variant-numeric: tabular-nums; }
    .url-small { font-size: 0.72rem; color: #888; }
    .url-small a { color: #0056b3; text-decoration: none; }
    .url-small a:hover { text-decoration: underline; }
    .cat-chip {
      display: inline-block; padding: 0.15rem 0.5rem; border-radius: 12px;
      background: #e8f0fe; color: #1a56b3; font-size: 0.72rem;
      font-weight: 600; white-space: nowrap;
    }
    .aci-num  { font-size: 0.92rem; font-weight: 700; }
    .aci-dash { color: #bbb; }
    .mini-bar { height: 4px; background: #eee; border-radius: 2px; margin: 3px 0; overflow: hidden; }
    .mini-bar div { height: 100%; border-radius: 2px; }
    td a { color: #0056b3; text-decoration: none; }
    td a:hover { text-decoration: underline; }
    .no-results { padding: 2rem; text-align: center; color: #aaa; }
    /* Metodologia */
    .method-section { margin-bottom: 2rem; }
    .method-section h3 {
      font-size: 1rem; color: #001f3f; margin-bottom: 0.75rem;
      padding-bottom: 0.4rem; border-bottom: 2px solid #e0e8f0;
    }
    .formula-box {
      background: #f0f4f8; border-left: 4px solid #0056b3;
      padding: 0.9rem 1.2rem; border-radius: 0 8px 8px 0;
      font-family: 'Consolas', 'Courier New', monospace; font-size: 1rem; margin: 0.75rem 0;
    }
    .profiles-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1rem; margin: 0.75rem 0;
    }
    .profile-card { border-radius: 8px; padding: 1rem; border: 2px solid #ddd; }
    .profile-card.wcag        { background: #dbeafe; border-color: #1d4ed8; }
    .profile-card.readability { background: #dcfce7; border-color: #15803d; }
    .profile-card.visual      { background: #ffe4e6; border-color: #be123c; }
    .profile-card h4 { font-size: 0.88rem; font-weight: 700; margin-bottom: 0.35rem; }
    .profile-card.wcag h4        { color: #1d4ed8; }
    .profile-card.readability h4 { color: #15803d; }
    .profile-card.visual h4      { color: #be123c; }
    .profile-card p { font-size: 0.8rem; color: #444; line-height: 1.5; }
    .met-table { font-size: 0.82rem; width: 100%; border-collapse: collapse; }
    .met-table thead th { background: #001f3f; color: #fff; padding: 0.5rem 0.75rem; text-align: left; }
    .met-table td { padding: 0.4rem 0.75rem; border-bottom: 1px solid #eee; }
    .met-table tr:nth-child(even) td { background: #f8f9fa; }
    .met-table code { font-size: 0.76rem; background: #f0f0f0; padding: 1px 4px; border-radius: 3px; }
    .met-table td.num { text-align: right; font-variant-numeric: tabular-nums; color: #333; }
    /* Descàrregues */
    .dl-grid { display: flex; gap: 0.75rem; flex-wrap: wrap; }
    .dl-btn {
      display: inline-flex; align-items: center; gap: 0.4rem;
      padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.85rem; font-weight: 600;
      text-decoration: none; border: 2px solid #0056b3; color: #0056b3;
      background: #fff; transition: background 0.15s;
    }
    .dl-btn:hover { background: #0056b3; color: #fff; }
    /* Botó execució */
    .btn-run {
      display: inline-flex; align-items: center; gap: 0.4rem;
      padding: 0.45rem 1rem; border-radius: 6px; font-size: 0.83rem;
      font-weight: 600; text-decoration: none; background: #27ae60;
      color: #fff; border: none; cursor: pointer; transition: background 0.15s;
    }
    .btn-run:hover { background: #1e8449; color: #fff; }
    /* Footer */
    footer { text-align: center; padding: 2rem 1rem; font-size: 0.78rem; color: #aaa; }
    footer a { color: #0056b3; text-decoration: none; }
    @media (max-width: 700px) { header h1 { font-size: 1.3rem; } }
  </style>
</head>
<body>

<header role="banner">
  <h1>&#127760; ACI Pipeline &#8212; Dashboard de resultats</h1>
  <p>Avaluació automatitzada d&#39;accessibilitat web &middot; WCAG 2.1 AA / EN 301 549</p>
  <div class="header-meta">
    <span>Generat: __TS_BUILD__</span>
    <span>Pipeline v__PIPELINE_VER__</span>
    <span>__KPI_N__ URLs analitzades</span>
  </div>
</header>

<main>

  <!-- KPIs -->
  <div class="kpi-grid" role="region" aria-label="Indicadors clau de rendiment">
    <div class="kpi" style="--kc:#0056b3">
      <div class="kpi-val">__KPI_N__</div>
      <div class="kpi-lbl">URLs analitzades</div>
    </div>
    <div class="kpi" style="--kc:#27ae60">
      <div class="kpi-val">__KPI_MAX__</div>
      <div class="kpi-lbl">ACI m&agrave;xim</div>
    </div>
    <div class="kpi" style="--kc:#e67e22">
      <div class="kpi-val">__KPI_MEAN__</div>
      <div class="kpi-lbl">ACI mitj&agrave;</div>
    </div>
    <div class="kpi" style="--kc:#e74c3c">
      <div class="kpi-val">__KPI_MIN__</div>
      <div class="kpi-lbl">ACI m&iacute;nim</div>
    </div>
  </div>

  <!-- Taula de resultats -->
  <div class="card" role="region" aria-labelledby="tbl-title">
    <div class="card-hd">
      <h2 id="tbl-title">&#128202; Resultats per URL</h2>
      <a id="btn-run" class="btn-run" href="#" target="_blank" rel="noopener"
         aria-label="Executa el pipeline des de GitHub Actions">
        &#9654; Executa pipeline
      </a>
    </div>

    <div class="filters" role="search" aria-label="Filtres">
      <label for="f-text">Cerca:</label>
      <input type="search" id="f-text" placeholder="domini, URL&hellip;"
             aria-label="Cerca per domini o URL">

      <label for="f-cat">Categoria:</label>
      <select id="f-cat" aria-label="Filtra per categoria">
        <option value="">Totes</option>
        __CAT_OPTIONS__
      </select>

      <label for="f-min">ACI &ge;:</label>
      <input type="number" id="f-min" min="0" max="5" step="0.1" value="0"
             style="width:70px" aria-label="Puntuaci&oacute; ACI m&iacute;nima">

      <button class="btn-reset" onclick="resetFilters()"
              aria-label="Reinicia els filtres">&#10005; Reinicia</button>
      <span id="f-count" style="font-size:0.78rem;color:#888;margin-left:auto"
            aria-live="polite"></span>
    </div>

    <div class="tbl-wrap">
      <table aria-label="Resultats d'accessibilitat per URL">
        <thead>
          <tr>
            <th onclick="sortBy(0)" aria-sort="none">#</th>
            <th onclick="sortBy(1)" aria-sort="none">Domini / URL</th>
            <th onclick="sortBy(2)" aria-sort="none">Categoria</th>
            <th onclick="sortBy(3)" aria-sort="none"
                title="WCAG Strict">WCAG</th>
            <th onclick="sortBy(4)" aria-sort="none"
                title="Readability First">Read.</th>
            <th onclick="sortBy(5)" aria-sort="none"
                title="Visual First">Visual</th>
          </tr>
        </thead>
        <tbody id="tbody">
          __TBODY__
        </tbody>
      </table>
    </div>
    <p class="no-results" id="no-results" role="status" style="display:none">
      Cap resultat correspon als filtres aplicats.
    </p>
  </div>

  <!-- Metodologia -->
  <div class="card" role="region" aria-labelledby="method-title">
    <div class="card-hd">
      <h2 id="method-title">&#128208; Metodologia &#8212; &Iacute;ndex ACI</h2>
    </div>
    <div class="card-body">

      <div class="method-section">
        <h3>F&oacute;rmula de l&#39;ACI</h3>
        <p>L&#39;<strong>Accessibility Computation Index (ACI)</strong> pondera 16 m&egrave;triques
           normalitzades amb els pesos del perfil actiu:</p>
        <div class="formula-box" role="math" aria-label="F&oacute;rmula ACI">
          ACI = (&Sigma; n&shy;&sup1; &middot; w&shy;&sup1;) / (&Sigma; w&shy;&sup1;) &times; 5.0
          &nbsp;&isin; [0, 5]
        </div>
        <p style="font-size:0.85rem;color:#555;margin-top:0.5rem">
          On <em>n&#7522; &isin; [0,1]</em> &eacute;s el valor normalitzat de la m&egrave;trica
          <em>i</em> i <em>w&#7522;</em> &eacute;s el seu pes en el perfil seleccionat.
          Escala de qualitat:
          <span style="color:#27ae60">&#10003; Excel&middot;lent &ge; 4.0</span> &nbsp;&#183;&nbsp;
          <span style="color:#e67e22">&#9650; Acceptable &ge; 2.5</span> &nbsp;&#183;&nbsp;
          <span style="color:#e74c3c">&#10007; Insuficient &lt; 2.5</span>
        </p>
      </div>

      <div class="method-section">
        <h3>Perfils de puntuaci&oacute;</h3>
        <div class="profiles-grid">
          <div class="profile-card wcag">
            <h4>WCAG Strict (&Sigma;w&nbsp;=&nbsp;54)</h4>
            <p>M&agrave;xima prioritat per a conformitat normativa WCAG 2.1 AA i EN&nbsp;301&nbsp;549.
               Pes fort a contrast, teclat, noms accessibles i violacions cr&iacute;tiques.
               Recomanat per a webs institucionals i administracions p&uacute;bliques.</p>
          </div>
          <div class="profile-card readability">
            <h4>Readability First (&Sigma;w&nbsp;=&nbsp;35)</h4>
            <p>Prioritza la llegibilitat i comprens&iacute; del contingut textual.
               Pes fort a Flesch, complexitat textual i jerarquia de cap&ccedil;aleres.
               Recomanat per a portals educatius i editorials.</p>
          </div>
          <div class="profile-card visual">
            <h4>Visual First (&Sigma;w&nbsp;=&nbsp;37)</h4>
            <p>Prioritza la qualitat visual i l&#39;accessibilitat d&#39;imatges.
               Pes fort a contrast, alt text i LCP de rendiment.
               Recomanat per a webs multim&egrave;dia i comercials.</p>
          </div>
        </div>
      </div>

      <div class="method-section">
        <h3>Les 16 m&egrave;triques del pipeline</h3>
        <p style="font-size:0.8rem;color:#666;margin-bottom:0.6rem">
          W&nbsp;=&nbsp;WCAG Strict &nbsp;|&nbsp;
          R&nbsp;=&nbsp;Readability First &nbsp;|&nbsp;
          V&nbsp;=&nbsp;Visual First
        </p>
        __METRICS_TABLE__
      </div>

    </div>
  </div>

  <!-- Desc&#224;rregues -->
  <div class="card" role="region" aria-labelledby="dl-title">
    <div class="card-hd"><h2 id="dl-title">&#8595; Desc&agrave;rregues</h2></div>
    <div class="card-body">
      <div class="dl-grid">
        <a class="dl-btn" href="data/scores.csv" download
           aria-label="Descarrega les puntuacions en format CSV">
          &#128196; scores.csv
        </a>
        <a class="dl-btn" href="results.json" download
           aria-label="Descarrega les dades consolidades en format JSON">
          &#x7B;&#x7D; results.json
        </a>
        <a class="dl-btn" href="data/reports_manifest.json" download
           aria-label="Descarrega el manifest d'informes">
          &#128203; reports_manifest.json
        </a>
      </div>
    </div>
  </div>

</main>

<footer role="contentinfo">
  <p>ACI Pipeline v__PIPELINE_VER__ &middot; Jordi Miguel i Costal &middot; TFM 2026 &middot;
     <a id="repo-link" href="https://github.com" rel="noopener">Repositori GitHub</a></p>
  <p>Basat en WCAG 2.1/2.2, EN 301 549 i axe-core</p>
</footer>

<script>
// Dades embegudes (generades per build_site.py — no cal fetch)
const ALL_ROWS = __ROWS_JSON__;
const PROFILES = ["wcag_strict", "readability_first", "visual_first"];
let sortCol = -1, sortAsc = true;

// Detecta repo GitHub des de l'URL de Pages
(function () {
  var h = window.location.hostname;
  var p = (window.location.pathname.split('/')[1] || '');
  if (h.endsWith('github.io') && p) {
    var owner = h.replace('.github.io', '');
    var repo  = 'https://github.com/' + owner + '/' + p;
    document.getElementById('repo-link').href = repo;
    document.getElementById('btn-run').href   =
      repo + '/actions/workflows/publish_results.yml';
  }
}());

// Filtrat
function getFilters() {
  return {
    text:   document.getElementById('f-text').value.toLowerCase().trim(),
    cat:    document.getElementById('f-cat').value,
    minAci: parseFloat(document.getElementById('f-min').value) || 0,
  };
}

function applyFilters() {
  var f = getFilters();
  var filtered = ALL_ROWS.filter(function (r) {
    if (f.text && !r.domain.toLowerCase().includes(f.text) &&
        !r.url.toLowerCase().includes(f.text)) return false;
    if (f.cat && r.category !== f.cat) return false;
    var best = r.aci_max;
    if (best !== null && best < f.minAci) return false;
    return true;
  });
  renderRows(filtered);
}

function aciColor(s) {
  if (s === null) return '#888';
  return s >= 3.5 ? '#27ae60' : s >= 2.5 ? '#e67e22' : '#e74c3c';
}

function esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderRows(rows) {
  var tbody  = document.getElementById('tbody');
  var noRes  = document.getElementById('no-results');
  var fCount = document.getElementById('f-count');
  fCount.textContent = rows.length + ' resultat' + (rows.length !== 1 ? 's' : '');

  if (!rows.length) { tbody.innerHTML = ''; noRes.style.display = ''; return; }
  noRes.style.display = 'none';

  tbody.innerHTML = rows.map(function (r, i) {
    var cells = [
      '<td class="num">' + (i + 1) + '</td>',
      '<td><strong>' + esc(r.domain) + '</strong><br>' +
        '<small class="url-small"><a href="' + esc(r.url) + '" target="_blank" rel="noopener">' +
        esc(r.url) + '</a></small></td>',
      '<td><span class="cat-chip">' + esc(r.category || '—') + '</span></td>',
    ];
    PROFILES.forEach(function (p) {
      var pd    = r.profiles[p] || {};
      var aci   = pd.aci !== undefined ? pd.aci : null;
      var rep   = pd.report || null;
      if (aci !== null) {
        var pct   = Math.round(aci / 5 * 100);
        var color = aciColor(aci);
        var link  = rep ? ' <a href="' + rep + '" title="Informe">&#128196;</a>' : '';
        cells.push(
          '<td data-val="' + aci.toFixed(3) + '">' +
          '<span class="aci-num" style="color:' + color + '">' + aci.toFixed(3) + '</span>' +
          '<div class="mini-bar"><div style="width:' + pct + '%;background:' + color + '"></div></div>' +
          link + '</td>'
        );
      } else {
        cells.push('<td data-val="0"><span class="aci-dash">—</span></td>');
      }
    });
    return '<tr>' + cells.join('') + '</tr>';
  }).join('');
}

// Ordenació
function sortBy(col) {
  var ths = document.querySelectorAll('thead th');
  ths.forEach(function (th) {
    th.classList.remove('sort-asc', 'sort-desc');
    th.removeAttribute('aria-sort');
  });
  if (sortCol === col) { sortAsc = !sortAsc; } else { sortCol = col; sortAsc = (col < 3); }
  ths[col].classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
  ths[col].setAttribute('aria-sort', sortAsc ? 'ascending' : 'descending');

  var rows = Array.from(document.querySelectorAll('#tbody tr'));
  rows.sort(function (a, b) {
    var av, bv, cmp;
    if (col >= 3) {
      av  = parseFloat(a.cells[col] && a.cells[col].dataset.val) || 0;
      bv  = parseFloat(b.cells[col] && b.cells[col].dataset.val) || 0;
      cmp = av - bv;
    } else {
      av  = (a.cells[col] && a.cells[col].textContent.trim()) || '';
      bv  = (b.cells[col] && b.cells[col].textContent.trim()) || '';
      cmp = av.localeCompare(bv, 'ca');
    }
    return sortAsc ? cmp : -cmp;
  });
  var tbody = document.getElementById('tbody');
  rows.forEach(function (r) { tbody.appendChild(r); });
}

function resetFilters() {
  document.getElementById('f-text').value = '';
  document.getElementById('f-cat').value  = '';
  document.getElementById('f-min').value  = '0';
  applyFilters();
}

// Inicialitza
document.getElementById('f-text').addEventListener('input',  applyFilters);
document.getElementById('f-cat').addEventListener('change',  applyFilters);
document.getElementById('f-min').addEventListener('input',   applyFilters);
document.getElementById('f-count').textContent =
  ALL_ROWS.length + ' resultat' + (ALL_ROWS.length !== 1 ? 's' : '');
</script>
</body>
</html>
"""


# ── Còpia d'assets estàtics ────────────────────────────────────────────────────

def copy_static(output_dir: Path) -> None:
    """Copia static/ → docs/static/ si existeix."""
    # Cerca static/ relativa al directori arrel del projecte
    for candidate in [
        Path("static"),
        Path(__file__).parent.parent / "static",
    ]:
        if candidate.is_dir():
            dst = output_dir / "static"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(candidate, dst)
            print(f"  static/ → docs/static/ ({candidate.resolve()})")
            return
    print("  [INFO] static/ no trobat; s'omet la còpia d'assets")


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    args = parse_args(argv)
    results_dir = Path(args.results)
    output_dir  = Path(args.output)

    print(f"\nbuild_site.py — ACI Pipeline v{PIPELINE_VERSION}")
    print(f"  Resultats : {results_dir.resolve()}")
    print(f"  Sortida   : {output_dir.resolve()}\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reports").mkdir(parents=True, exist_ok=True)
    (output_dir / "data").mkdir(parents=True, exist_ok=True)

    ts_build = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print("[1] Carregant mètriques…")
    entries = load_metrics(results_dir)

    print("[2] Agrupant per URL…")
    grouped = group_entries(entries)
    print(f"  {len(grouped)} URL(s) úniques trobades")

    if not grouped:
        print("\n  [WARN] Cap resultat trobat. Comprova que el pipeline ha generat JSONs a:")
        print(f"         {results_dir / 'metrics'}")
        # Genera index.html buit igualment
        generate_index_html({}, output_dir, ts_build)
        return 0

    print("[3] Copiant informes HTML…")
    manifest = copy_reports(grouped, results_dir, output_dir)

    print("[4] Generant manifest…")
    generate_manifest(manifest, output_dir)

    print("[5] Generant results.json…")
    generate_results_json(grouped, output_dir, ts_build)

    print("[6] Generant scores.csv…")
    generate_scores_csv(grouped, output_dir)

    print("[7] Copiant assets estàtics…")
    copy_static(output_dir)

    print("[8] Generant index.html…")
    generate_index_html(grouped, output_dir, ts_build)

    n_reports = len(list((output_dir / "reports").glob("*.html")))
    print(f"\n✓  Lloc estàtic generat a: {output_dir.resolve()}")
    print(f"   {len(grouped)} URL(s) · {n_reports} informe(s) HTML\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
