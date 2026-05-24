"""
M8 — Generació d'informes.
Genera HTML (Jinja2), CSV, JSON i ZIP amb tots els artefactes.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

from .utils import slug_from_url, timestamp

log = logging.getLogger("aci_pipeline.m8")

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def _load_template(template_name: str) -> str:
    """Carrega una plantilla Jinja2."""
    template_path = TEMPLATES_DIR / template_name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    log.warning("Plantilla no trobada: %s; usant plantilla mínima.", template_path)
    return _minimal_html_template()


def _minimal_html_template() -> str:
    """Plantilla HTML mínima de fallback."""
    return """<!DOCTYPE html>
<html lang="ca">
<head><meta charset="UTF-8"><title>Informe ACI - {{ url }}</title>
<style>
body{font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#333}
.score-box{padding:20px;border-radius:8px;text-align:center;margin:20px 0}
.score{font-size:3em;font-weight:bold}
.score-green{background:#d4edda;color:#28a745}
.score-yellow{background:#fff3cd;color:#856404}
.score-red{background:#f8d7da;color:#dc3545}
.metric{display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid #eee}
.bar{background:#e9ecef;height:20px;border-radius:3px;overflow:hidden;width:200px}
.bar-fill{height:100%;background:#007bff;transition:width 0.3s}
table{width:100%;border-collapse:collapse;margin:10px 0}
th,td{padding:8px;text-align:left;border:1px solid #dee2e6}
th{background:#f8f9fa}
.critical{color:#dc3545}.serious{color:#fd7e14}.moderate{color:#ffc107}
h1,h2{color:#2c3e50}
footer{margin-top:40px;padding-top:10px;border-top:1px solid #eee;color:#888;font-size:0.85em}
</style>
</head>
<body>
<h1>Informe d'Accessibilitat ACI</h1>
<p><strong>URL:</strong> <a href="{{ url }}">{{ url }}</a></p>
<p><strong>Perfil:</strong> {{ profile }}</p>
<p><strong>Data:</strong> {{ timestamp }}</p>

{% set score_class = "score-green" if aci_score >= 4 else ("score-yellow" if aci_score >= 2.5 else "score-red") %}
<div class="score-box {{ score_class }}">
  <div class="score">ACI: {{ aci_score | round(2) }} / 5.0</div>
  <div>{{ "Excel·lent" if aci_score >= 4 else ("Acceptable" if aci_score >= 2.5 else "Insuficient") }}</div>
</div>

<h2>Sub-scores per categoria</h2>
{% for group, score in sub_scores.items() %}
{% if score is not none %}
<div class="metric">
  <span><strong>{{ group | upper }}</strong></span>
  <div class="bar"><div class="bar-fill" style="width:{{ ((score / 5) * 100) | int }}%"></div></div>
  <span>{{ score | round(2) }} / 5.0</span>
</div>
{% endif %}
{% endfor %}

<h2>Top intervencions prioritzades</h2>
<table>
<tr><th>#</th><th>Metrica</th><th>Accio recomanada</th><th>Cost</th><th>Impacte</th><th>WCAG</th></tr>
{% for interv in interventions[:10] %}
<tr>
  <td><strong>{{ interv.priority_rank }}</strong></td>
  <td>{{ interv.metric }}</td>
  <td>{{ interv.action }}</td>
  <td>{{ interv.cost }}</td>
  <td>{{ interv.impact_level }}</td>
  <td>{{ interv.wcag_criterion }}</td>
</tr>
{% endfor %}
</table>

<h2>Metriques detallades</h2>
<table>
<tr><th>Metrica</th><th>Valor raw</th><th>Normalitzat (0-1)</th><th>Pes</th></tr>
{% for metric, norm_val in normalized_metrics.items() %}
<tr>
  <td>{{ metric }}</td>
  <td>{{ raw_values.get(metric, "N/A") }}</td>
  <td>{{ norm_val | round(3) }}</td>
  <td>{{ weights.get(metric, "-") }}</td>
</tr>
{% endfor %}
</table>

{% if axe_violations %}
<h2>Violacions axe-core ({{ axe_violations | length }})</h2>
<table>
<tr><th>ID</th><th>Impacte</th><th>Descripcio</th><th>Elements afectats</th></tr>
{% for v in axe_violations[:20] %}
<tr class="{{ v.impact }}">
  <td><code>{{ v.id }}</code></td>
  <td><strong>{{ v.impact }}</strong></td>
  <td>{{ v.description }}</td>
  <td>{{ v.nodes_affected }}</td>
</tr>
{% endfor %}
</table>
{% endif %}

{% if text_metrics %}
<h2>Metriques textuals</h2>
<table>
<tr><th>Metrica</th><th>Valor</th></tr>
{% for key, val in text_metrics.items() %}
{% if val is not none %}
<tr><td>{{ key }}</td><td>{{ val }}</td></tr>
{% endif %}
{% endfor %}
</table>
{% endif %}

{% if perf.lcp_ms is not none %}
<h2>Rendiment (Web Vitals)</h2>
<table>
<tr><th>Metrica</th><th>Valor</th><th>Rating</th></tr>
<tr><td>LCP (Largest Contentful Paint)</td><td>{{ perf.lcp_ms | round(0) }} ms</td><td>{{ perf.lcp_rating }}</td></tr>
{% if perf.ttfb_ms is not none %}<tr><td>TTFB</td><td>{{ perf.ttfb_ms | round(0) }} ms</td><td>-</td></tr>{% endif %}
</table>
{% endif %}

<footer>
  <p>Generat per aci_pipeline v{{ pipeline_version }} | {{ timestamp }}</p>
  <p>Pipeline d'accessibilitat cognitiva i visual (ACI) — TFM Jordi Miguel i Costal</p>
</footer>
</body></html>"""


def generate_html_report(
    url: str,
    m4_result: dict[str, Any],
    m6_result: dict[str, Any],
    m7_result: dict[str, Any],
    screenshot_path: str | None = None,
    output_path: Path | None = None,
) -> str:
    """Genera un informe HTML complet per a una URL."""
    from jinja2 import Environment, BaseLoader
    env = Environment(loader=BaseLoader())
    template_str = _load_template("report.html.j2")
    template = env.from_string(template_str)

    from datetime import datetime, timezone
    ts_human = datetime.fromtimestamp(
        m6_result.get("timestamp", timestamp()), tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    context = {
        "url": url,
        "profile": m6_result.get("profile", ""),
        "timestamp": ts_human,
        "aci_score": m6_result.get("aci_score", 0),
        "aci_normalized": m6_result.get("aci_normalized", 0),
        "sub_scores": m6_result.get("sub_scores", {}),
        "normalized_metrics": m6_result.get("normalized_metrics", {}),
        "raw_values": m6_result.get("raw_values", {}),
        "weights": m6_result.get("weights", {}),
        "interventions": m7_result.get("interventions", []),
        "axe_violations": m4_result.get("axe_summary", {}).get("violations_detail", []),
        "text_metrics": m4_result.get("text_metrics", {}),
        "perf": m4_result.get("perf", {}),
        "screenshot_path": screenshot_path,
        "pipeline_version": "0.1.0",
    }

    html_content = template.render(**context)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_content, encoding="utf-8")
        log.info("Informe HTML desat a: %s", output_path)

    return html_content


def generate_csv_metrics(
    results: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Genera un CSV amb totes les mètriques de múltiples URLs."""
    if not results:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Recopila totes les columnes possibles
    all_metrics: set[str] = set()
    for r in results:
        all_metrics.update(r.get("normalized_metrics", {}).keys())

    fieldnames = ["url", "timestamp", "profile", "aci_score"] + sorted(all_metrics)

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row: dict[str, Any] = {
                "url": r.get("url", ""),
                "timestamp": r.get("timestamp", ""),
                "profile": r.get("profile", ""),
                "aci_score": r.get("aci_score", ""),
            }
            for metric in all_metrics:
                row[metric] = r.get("normalized_metrics", {}).get(metric, "")
            writer.writerow(row)

    log.info("CSV metriques desat a: %s", output_path)


def create_zip_package(
    url: str,
    data_dir: Path,
    slug: str,
    ts: int,
    output_path: Path | None = None,
) -> Path:
    """Crea un paquet ZIP amb tots els artefactes d'una URL."""
    output_path = output_path or (data_dir / f"{slug}_{ts}_package.zip")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Busca tots els fitxers relacionats amb el slug
        for pattern in [
            f"assets/{slug}*",
            f"metrics/{slug}*",
            f"metrics/perf/{slug}*",
            f"metrics/audit/{slug}*",
            f"processed/{slug}*",
            f"processed/structure/{slug}*",
            f"reports/**/{slug}*",
        ]:
            for fpath in data_dir.glob(pattern):
                if fpath.is_file():
                    arcname = fpath.relative_to(data_dir)
                    zf.write(fpath, arcname)

    log.info("Paquet ZIP creat: %s", output_path)
    return output_path


def run_m8(
    url: str,
    m1_result: dict[str, Any],
    m4_result: dict[str, Any],
    m6_result: dict[str, Any],
    m7_result: dict[str, Any],
    data_dir: Path = Path("data"),
    slug: str | None = None,
    ts: int | None = None,
    create_zip: bool = False,
) -> dict[str, Any]:
    """Executa M8: generació d'informes i artefactes."""
    slug = slug or slug_from_url(url)
    ts = ts or timestamp()
    profile = m6_result.get("profile", "default")

    reports_dir = data_dir / "reports" / slug
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Informe HTML — ruta relativa captura: report és 2 nivells sota data/
    raw_screenshot = m1_result.get("screenshot_path")
    if raw_screenshot:
        screenshot_name = Path(raw_screenshot).name
        rel_screenshot = f"../../assets/{screenshot_name}"
    else:
        rel_screenshot = None

    html_path = reports_dir / f"{slug}_{ts}_{profile}.html"
    html_content = generate_html_report(
        url=url,
        m4_result=m4_result,
        m6_result=m6_result,
        m7_result=m7_result,
        screenshot_path=rel_screenshot,
        output_path=html_path,
    )

    # ZIP (opcional)
    zip_path = None
    if create_zip:
        zip_path = create_zip_package(url, data_dir, slug, ts)

    result = {
        "url": url,
        "html_report_path": str(html_path),
        "zip_path": str(zip_path) if zip_path else None,
    }

    log.info("M8 completat per %s -> %s", url, html_path)
    return result


def generate_comparative_report(
    url: str,
    profile_results: dict[str, Any],
    data_dir: Path,
    slug: str | None = None,
    ts: int | None = None,
) -> Path:
    """Genera un informe HTML comparatiu entre perfils per a una URL.

    profile_results: {profile_name: {aci_score, sub_scores, normalized_metrics,
                                     interventions, ...}}
    """
    from jinja2 import Environment, BaseLoader
    from datetime import datetime, timezone

    slug = slug or slug_from_url(url)
    ts = ts or timestamp()

    clean_url = url.split(";")[0].strip()
    web_type = url.split(";")[1].strip() if ";" in url else ""
    ts_human = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    template_path = TEMPLATES_DIR / "comparative.html.j2"
    if template_path.exists():
        template_str = template_path.read_text(encoding="utf-8")
    else:
        log.error("Plantilla comparative.html.j2 no trobada a %s", TEMPLATES_DIR)
        raise FileNotFoundError(f"comparative.html.j2 not found at {TEMPLATES_DIR}")

    env = Environment(loader=BaseLoader())
    template = env.from_string(template_str)

    context = {
        "url": url,
        "clean_url": clean_url,
        "web_type": web_type,
        "timestamp": ts_human,
        "profiles": profile_results,
        "pipeline_version": "0.1.0",
    }

    html_content = template.render(**context)

    reports_dir = data_dir / "reports" / slug
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"{slug}_{ts}_comparative.html"
    out_path.write_text(html_content, encoding="utf-8")
    log.info("Informe comparatiu desat a: %s", out_path)
    return out_path


def write_profile_yaml_summary(
    url: str,
    profile_name: str,
    m6_result: dict[str, Any],
    m7_result: dict[str, Any],
    data_dir: Path,
    slug: str | None = None,
    ts: int | None = None,
) -> Path:
    """Desa un resum YAML per a una URL + perfil."""
    import yaml  # type: ignore[import-untyped]

    slug = slug or slug_from_url(url)
    ts = ts or timestamp()
    reports_dir = data_dir / "reports" / slug
    reports_dir.mkdir(parents=True, exist_ok=True)

    clean_url = url.split(";")[0].strip()
    summary = {
        "url": clean_url,
        "profile": profile_name,
        "timestamp": ts,
        "aci_score": m6_result.get("aci_score"),
        "aci_normalized": m6_result.get("aci_normalized"),
        "sub_scores": m6_result.get("sub_scores", {}),
        "normalized_metrics": m6_result.get("normalized_metrics", {}),
        "top_interventions": [
            {k: iv.get(k) for k in ("priority_rank", "metric", "action", "cost",
                                    "impact_level", "wcag_criterion")}
            for iv in m7_result.get("interventions", [])[:10]
        ],
    }
    out_path = reports_dir / f"{profile_name}.yaml"
    out_path.write_text(yaml.dump(summary, allow_unicode=True, sort_keys=False), encoding="utf-8")
    log.info("YAML perfil desat: %s", out_path)
    return out_path
