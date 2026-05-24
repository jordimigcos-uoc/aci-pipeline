"""
tests/test_render.py
====================
Tests de la capa de generació de lloc estàtic ACI (site_generation.render_reports).

Execució:
  pytest tests/test_render.py -v
  pytest tests/test_render.py -v --tb=short
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from statistics import mean

import pytest

# Afegeix el directori arrel al PYTHONPATH per importar site_generation
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from site_generation.render_reports import (
    _compute_wcag_principles,
    _metrics_to_100,
    _normalise_type,
    _safe_mean,
    _slug_from_url,
    get_env,
    pipeline_entries_to_slug_results,
    render_comparative_reports,
    render_global_index,
    render_metrics_explanation,
    render_profile_reports,
    save_slug_results,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_RESULT_PATH = ROOT / "data" / "samples" / "results_example.json"

NM_FULL = {
    "color_contrast_ratio":      0.80,
    "focus_visible_ratio":       0.65,
    "target_size_clean":         0.55,
    "keyboard_clean":            0.70,
    "aria_roles_valid":          0.75,
    "accessible_names_coverage": 0.68,
    "audit_critical_violations": 0.85,
    "audit_high_violations":     0.78,
    "audit_medium_violations":   0.90,
    "audit_low_violations":      0.92,
    "page_flesch":               0.58,
    "text_complexity":           0.62,
    "heading_hierarchy":         0.80,
    "alt_text_coverage":         0.60,
    "landmark_coverage":         0.65,
    "performance_lcp":           0.75,
}

SAMPLE_ENTRY = {
    "url":         "https://www.example.com;Educatiu",
    "profile":     "wcag_strict",
    "aci_score":   3.5,
    "aci_normalized": 0.70,
    "timestamp":   0,
    "normalized_metrics": NM_FULL,
    "raw_values":  {k: v for k, v in NM_FULL.items()},
    "sub_scores":  {"wcag": 0.72, "text": 0.67, "elements": 0.65, "performance": 0.75},
    "notes":       "Test entry",
    "_stem":       "example-com_0_wcag_strict",
}


@pytest.fixture
def tmp_output(tmp_path):
    return tmp_path / "site_out"


@pytest.fixture
def sample_site_results():
    """Estructura site_results completa amb les 3 perfils."""
    profiles_data = {}
    for profile in ["wcag_strict", "readability_first", "visual_first"]:
        m100 = _metrics_to_100(NM_FULL)
        wp   = _compute_wcag_principles(NM_FULL)
        profiles_data[profile] = {
            "score_overall":  70.0,
            "metrics":        m100,
            "sub_scores_100": {"wcag": 72.0, "text": 66.7, "elements": 67.0, "performance": 75.0},
            "wcag_principles": wp,
            "notes":          "Test note",
            "raw":            NM_FULL,
        }
    return [
        {
            "url":       "https://www.example.com",
            "slug":      "www-example-com",
            "domain":    "www.example.com",
            "type":      "educatiu",
            "timestamp": "2026-05-24T10:00:00Z",
            "profiles":  profiles_data,
            "comparative": {
                "best_profile":  "wcag_strict",
                "best_score":    70.0,
                "worst_profile": "readability_first",
                "worst_score":   70.0,
                "mean_score":    70.0,
                "score_variance": 0.0,
            },
        }
    ]


# ── Tests utils ───────────────────────────────────────────────────────────────

class TestSafeMean:
    def test_empty(self):
        assert _safe_mean([]) == 0.0

    def test_all_none(self):
        assert _safe_mean([None, None]) == 0.0

    def test_normal(self):
        result = _safe_mean([0.5, 1.0, 0.75])
        assert abs(result - 0.75) < 1e-6

    def test_with_none(self):
        result = _safe_mean([0.5, None, 1.0])
        assert abs(result - 0.75) < 1e-6


class TestNormaliseType:
    @pytest.mark.parametrize("raw, expected", [
        ("Educatiu",     "educatiu"),
        ("educational",  "educatiu"),
        ("universitat",  "universitat"),
        ("University",   "universitat"),
        ("institucional","institucional"),
        ("Institutional","institucional"),
        ("cultural",     "cultural"),
        ("Culture",      "cultural"),
        ("mitjans",      "mitjans"),
        ("Media",        "mitjans"),
        ("comercial",    "comercial"),
        ("Commercial",   "comercial"),
        ("ecommerce",    "ecommerce"),
        ("e-commerce",   "ecommerce"),
        ("blog",         "blog"),
        ("Blog",         "blog"),
        ("independents", "independents"),
        ("",             "independents"),   # default
        ("random_type",  "random_type"),    # unknown → passthrough lowercase
    ])
    def test_type_mapping(self, raw, expected):
        assert _normalise_type(raw) == expected


class TestSlugFromUrl:
    def test_simple(self):
        assert _slug_from_url("https://www.uoc.edu") == "www-uoc-edu"

    def test_with_path(self):
        slug = _slug_from_url("https://example.com/path/page")
        assert "/" not in slug
        assert slug.startswith("example-com")

    def test_trailing_slash(self):
        assert _slug_from_url("https://example.com/") == "example-com"

    def test_max_length(self):
        long_url = "https://" + "a" * 100 + ".com"
        assert len(_slug_from_url(long_url)) <= 60

    def test_http(self):
        assert _slug_from_url("http://example.com") == "example-com"

    def test_no_leading_dash(self):
        slug = _slug_from_url("https://example.com")
        assert not slug.startswith("-")
        assert not slug.endswith("-")


class TestComputeWcagPrinciples:
    def test_keys_present(self):
        wp = _compute_wcag_principles(NM_FULL)
        assert set(wp.keys()) == {"perceptible", "operable", "comprensible", "robust"}

    def test_range_0_100(self):
        wp = _compute_wcag_principles(NM_FULL)
        for k, v in wp.items():
            assert 0 <= v <= 100, f"{k} = {v} out of range"

    def test_perceptible(self):
        """Perceptible = mean(contrast, alt, headings) × 100."""
        nm = {"color_contrast_ratio": 0.80, "alt_text_coverage": 0.60, "heading_hierarchy": 0.80}
        wp = _compute_wcag_principles(nm)
        expected = mean([0.80, 0.60, 0.80]) * 100
        assert abs(wp["perceptible"] - expected) < 0.2

    def test_operable(self):
        """Operable = mean(focus, target, keyboard) × 100."""
        nm = {"focus_visible_ratio": 0.65, "target_size_clean": 0.55, "keyboard_clean": 0.70}
        wp = _compute_wcag_principles(nm)
        expected = mean([0.65, 0.55, 0.70]) * 100
        assert abs(wp["operable"] - expected) < 0.2

    def test_empty_nm(self):
        wp = _compute_wcag_principles({})
        for v in wp.values():
            assert v == 0.0


class TestMetricsTo100:
    def test_all_keys_present(self):
        m100 = _metrics_to_100(NM_FULL)
        expected_keys = {
            "color_contrast", "focus_visibility", "target_size", "keyboard_nav",
            "aria_roles", "accessible_names", "critical_violations", "high_violations",
            "medium_violations", "low_violations", "flesch_reading_ease", "text_complexity",
            "heading_hierarchy", "alt_text_coverage", "landmark_coverage", "performance_lcp",
            "accessibility", "readability", "performance", "seo", "robustness",
        }
        assert expected_keys.issubset(set(m100.keys()))

    def test_range_0_100(self):
        m100 = _metrics_to_100(NM_FULL)
        for k, v in m100.items():
            assert 0 <= v <= 100, f"{k} = {v} out of range"

    def test_color_contrast(self):
        m100 = _metrics_to_100({"color_contrast_ratio": 0.80})
        assert abs(m100["color_contrast"] - 80.0) < 0.1

    def test_empty(self):
        m100 = _metrics_to_100({})
        assert all(v == 0 for v in m100.values())


class TestPipelineEntriesToSlugResults:
    def test_single_entry(self):
        results = pipeline_entries_to_slug_results([SAMPLE_ENTRY])
        assert len(results) == 1
        sr = results[0]
        assert sr["url"] == "https://www.example.com"
        assert sr["type"] == "educatiu"
        assert "wcag_strict" in sr["profiles"]

    def test_type_extracted_from_semicolon(self):
        entry = {**SAMPLE_ENTRY, "url": "https://uoc.edu;Universitat"}
        results = pipeline_entries_to_slug_results([entry])
        assert results[0]["type"] == "universitat"

    def test_multiple_profiles_same_url(self):
        entries = []
        for p in ["wcag_strict", "readability_first", "visual_first"]:
            entries.append({**SAMPLE_ENTRY, "profile": p})
        results = pipeline_entries_to_slug_results(entries)
        assert len(results) == 1
        assert set(results[0]["profiles"].keys()) >= {"wcag_strict"}

    def test_comparative_keys(self):
        results = pipeline_entries_to_slug_results([SAMPLE_ENTRY])
        cmp = results[0]["comparative"]
        for k in ["best_profile", "best_score", "worst_profile", "worst_score", "mean_score"]:
            assert k in cmp, f"Missing key: {k}"

    def test_score_scale_0_100(self):
        results = pipeline_entries_to_slug_results([SAMPLE_ENTRY])
        score = results[0]["profiles"]["wcag_strict"]["score_overall"]
        assert 0 <= score <= 100

    def test_empty_entries(self):
        assert pipeline_entries_to_slug_results([]) == []

    def test_slug_no_special_chars(self):
        results = pipeline_entries_to_slug_results([SAMPLE_ENTRY])
        slug = results[0]["slug"]
        assert not any(c in slug for c in [".", "/", ":", "?", "@", "#"])


# ── Tests de renderitzat ───────────────────────────────────────────────────────

@pytest.mark.skipif(
    not SAMPLE_RESULT_PATH.exists(),
    reason="data/samples/results_example.json no disponible"
)
class TestLoadSampleData:
    def test_sample_json_valid(self):
        data = json.loads(SAMPLE_RESULT_PATH.read_text(encoding="utf-8"))
        assert "url" in data
        assert "profiles" in data
        assert len(data["profiles"]) == 3

    def test_sample_profiles_have_metrics(self):
        data = json.loads(SAMPLE_RESULT_PATH.read_text(encoding="utf-8"))
        for p_name, p_data in data["profiles"].items():
            assert "score_overall" in p_data, f"{p_name} missing score_overall"
            assert "metrics" in p_data, f"{p_name} missing metrics"
            assert 0 <= p_data["score_overall"] <= 100, f"{p_name} score out of range"


class TestJinja2Env:
    def test_env_created(self):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        assert env is not None

    def test_aci_color_filter(self):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        assert env.filters["aci_color"](75) == "#27ae60"   # >= 70
        assert env.filters["aci_color"](55) == "#e67e22"   # >= 50
        assert env.filters["aci_color"](30) == "#e74c3c"   # < 50

    def test_aci_label_filter(self):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        assert env.filters["aci_label"](80)  == "Excel·lent"
        assert env.filters["aci_label"](60)  == "Acceptable"
        assert env.filters["aci_label"](40)  == "Insuficient"

    def test_tojson_filter(self):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        result = env.filters["tojson"]({"a": 1})
        parsed = json.loads(result)
        assert parsed == {"a": 1}


class TestSaveSlugResults:
    def test_creates_results_json(self, tmp_output, sample_site_results):
        save_slug_results(sample_site_results, tmp_output)
        slug = sample_site_results[0]["slug"]
        results_file = tmp_output / "results" / slug / "results.json"
        assert results_file.exists(), f"results.json no creat a {results_file}"

    def test_results_json_valid(self, tmp_output, sample_site_results):
        save_slug_results(sample_site_results, tmp_output)
        slug = sample_site_results[0]["slug"]
        data = json.loads(
            (tmp_output / "results" / slug / "results.json").read_text(encoding="utf-8")
        )
        assert "url" in data
        assert "profiles" in data


class TestRenderProfileReports:
    def test_creates_html_files(self, tmp_output, sample_site_results):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        render_profile_reports(sample_site_results, tmp_output, env)
        slug = sample_site_results[0]["slug"]
        for p in ["wcag_strict", "readability_first", "visual_first"]:
            f = tmp_output / "reports" / f"{slug}_{p}.html"
            assert f.exists(), f"Fitxer HTML no creat: {f.name}"
            assert f.stat().st_size > 1000, f"HTML massa petit: {f.name}"

    def test_html_contains_aci_score(self, tmp_output, sample_site_results):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        render_profile_reports(sample_site_results, tmp_output, env)
        slug = sample_site_results[0]["slug"]
        html = (tmp_output / "reports" / f"{slug}_wcag_strict.html").read_text("utf-8")
        assert "70.0" in html or "70" in html
        assert "chart.js" in html.lower() or "chart.umd" in html.lower()

    def test_adds_report_url_to_context(self, tmp_output, sample_site_results):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        render_profile_reports(sample_site_results, tmp_output, env)
        sr = sample_site_results[0]
        assert "report_url" in sr["profiles"].get("wcag_strict", {})


class TestRenderComparativeReports:
    def test_creates_comparative_html(self, tmp_output, sample_site_results):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        render_comparative_reports(sample_site_results, tmp_output, env)
        slug = sample_site_results[0]["slug"]
        f = tmp_output / "reports" / f"{slug}_comparative.html"
        assert f.exists(), f"Informe comparatiu no creat: {f}"
        assert f.stat().st_size > 2000


class TestRenderGlobalIndex:
    def test_creates_index_html(self, tmp_output, sample_site_results):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        tmp_output.mkdir(parents=True, exist_ok=True)
        render_global_index(sample_site_results, tmp_output, env, "2026-05-24T10:00:00Z")
        f = tmp_output / "index.html"
        assert f.exists(), "index.html no creat"
        assert f.stat().st_size > 5000

    def test_index_contains_d3_data(self, tmp_output, sample_site_results):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        tmp_output.mkdir(parents=True, exist_ok=True)
        render_global_index(sample_site_results, tmp_output, env, "2026-05-24T10:00:00Z")
        html = (tmp_output / "index.html").read_text("utf-8")
        assert "D3_DATA" in html
        assert "TABLE_ROWS" in html
        assert "global_charts.js" in html


class TestRenderMetricsExplanation:
    def test_creates_metrics_html(self, tmp_output, sample_site_results):
        templates_dir = ROOT / "templates"
        if not templates_dir.exists():
            pytest.skip("Directori templates/ no disponible")
        env = get_env(templates_dir)
        tmp_output.mkdir(parents=True, exist_ok=True)
        render_metrics_explanation(tmp_output, env)
        f = tmp_output / "metrics.html"
        if f.exists():  # opcional: la funció no falla si la plantilla no existeix
            assert f.stat().st_size > 1000
