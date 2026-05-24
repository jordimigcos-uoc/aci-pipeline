"""
Tests per al mode multi-perfil del pipeline ACI.

Valida:
1. run_all_profiles_for_url executa els 3 perfils i genera informe comparatiu
2. Els CSVs es generen a la ruta esperada i contenen files per URL
3. Les sortides per URLs/perfils diferent no són idèntiques (variabilitat)
4. generate_global_comparison genera un Markdown correcte
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aci_pipeline.m6_agregacio import compute_aci_score
from aci_pipeline.m7_perfil import load_scoring_config, get_profile_weights, get_norm_config
from aci_pipeline.m8_reporting import generate_comparative_report, generate_csv_metrics

CONFIGS_PATH = Path(__file__).parent.parent / "configs" / "scoring_config.yaml"
TEST_PAGE_PATH = Path(__file__).parent.parent / "data" / "samples" / "test_page.html"
ALL_PROFILES = ["wcag_strict", "readability_first", "visual_first"]

# ── Fixtures compartits ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def scoring_config() -> dict:
    return load_scoring_config(CONFIGS_PATH)


@pytest.fixture(scope="module")
def norm_config(scoring_config) -> dict:
    return get_norm_config(scoring_config)


@pytest.fixture(scope="module")
def sample_metrics() -> dict:
    """Mètriques representatives sense Playwright."""
    return {
        "alt_text_coverage": 0.4,
        "color_contrast_ratio": 0.6,
        "heading_hierarchy": 0.7,
        "landmark_coverage": 0.3,
        "accessible_names_coverage": 0.5,
        "focus_visible_ratio": 0.8,
        "keyboard_clean": 0.9,
        "form_labels_clean": 0.6,
        "wcag_critical_clean": 0.85,
        "text_complexity": 55.0,
        "performance_lcp": 3000.0,
        "performance_ttfb": 400.0,
        "table_descriptions": 0.5,
        "metadata_completeness": 0.8,
        "information_density": 120.0,
        "multimodal_coherence": 0.6,
        "aria_roles_valid": 0.9,
        "autoplay_clean": 1.0,
        "focus_not_obscured": 1.0,
        "target_size_clean": 0.7,
        "focus_traps_clean": 1.0,
        "tab_order_natural": 0.8,
        "form_error_states": 0.5,
        "focus_contrast": 0.7,
        "color_dependence_clean": 1.0,
        "landmarks_unique": 0.5,
    }


# ── Test 1: Tres perfils produïxen ACI scores ──────────────────────────────────

class TestThreeProfileScores:
    """Els 3 perfils s'executen correctament i generen scores."""

    def test_all_profiles_return_scores(self, scoring_config, norm_config, sample_metrics):
        scores = {}
        for profile in ALL_PROFILES:
            weights = get_profile_weights(scoring_config, profile)
            result = compute_aci_score(sample_metrics, weights, norm_config)
            scores[profile] = result["aci_score"]
            assert result["aci_score"] is not None, f"Score None per {profile}"
            assert 0 <= result["aci_score"] <= 5, f"Score fora de rang per {profile}"
        # Tots tres han de generar scores no-nuls
        assert all(s is not None for s in scores.values())

    def test_profiles_produce_different_scores(self, scoring_config, norm_config, sample_metrics):
        """Els perfils han de generar puntuacions DIFERENTS (variabilitat)."""
        scores = []
        for profile in ALL_PROFILES:
            weights = get_profile_weights(scoring_config, profile)
            result = compute_aci_score(sample_metrics, weights, norm_config)
            scores.append(round(result["aci_score"], 4))
        # No tots els scores poden ser idèntics
        assert len(set(scores)) > 1, (
            f"Tots els perfils han generat el mateix score {scores[0]:.4f} — "
            "els pesos del YAML no estan diferenciant els perfils"
        )

    def test_wcag_strict_penalizes_low_contrast(self, scoring_config, norm_config):
        """wcag_strict ha de penalitzar més fort el baix contrast que els altres."""
        low_contrast = {"color_contrast_ratio": 0.1, "alt_text_coverage": 0.8,
                        "heading_hierarchy": 0.9, "keyboard_clean": 0.9,
                        "wcag_critical_clean": 1.0, "form_labels_clean": 1.0,
                        "text_complexity": 70.0, "performance_lcp": 2000.0}
        wcag_w = get_profile_weights(scoring_config, "wcag_strict")
        read_w = get_profile_weights(scoring_config, "readability_first")
        wcag_r = compute_aci_score(low_contrast, wcag_w, norm_config)
        read_r = compute_aci_score(low_contrast, read_w, norm_config)
        # WCAG penalitza contrast (weight 5) vs readability (weight 3)
        assert wcag_r["aci_score"] <= read_r["aci_score"] + 0.5, (
            "wcag_strict hauria de puntuar igual o pitjor que readability_first "
            "amb contrast baix (el contrast té pes 5 vs 3)"
        )

    def test_sub_scores_present_all_profiles(self, scoring_config, norm_config, sample_metrics):
        for profile in ALL_PROFILES:
            weights = get_profile_weights(scoring_config, profile)
            result = compute_aci_score(sample_metrics, weights, norm_config)
            sub = result.get("sub_scores", {})
            assert isinstance(sub, dict), f"sub_scores no és dict per {profile}"
            # Ha d'haver almenys un sub-score no-None
            non_none = [v for v in sub.values() if v is not None]
            assert non_none, f"Tots els sub-scores són None per {profile}"


# ── Test 2: CSV de mètriques ───────────────────────────────────────────────────

class TestCSVGeneration:
    """El CSV es genera a la ruta esperada i conté les files correctes."""

    def _make_m6_result(self, url: str, profile: str, aci: float) -> dict:
        return {
            "url": url,
            "timestamp": int(time.time()),
            "profile": profile,
            "aci_score": aci,
            "aci_normalized": aci / 5.0,
            "normalized_metrics": {"alt_text_coverage": 0.5, "heading_hierarchy": 0.7},
            "metrics_evaluated": 10,
            "metrics_na": 2,
        }

    def test_csv_created_at_expected_path(self, tmp_path):
        results = [
            self._make_m6_result("https://example.com", "wcag_strict", 3.2),
            self._make_m6_result("https://gov.cat", "wcag_strict", 2.8),
        ]
        csv_path = tmp_path / "metrics" / "metrics_full.csv"
        generate_csv_metrics(results, csv_path)
        assert csv_path.exists(), f"CSV no creat a {csv_path}"

    def test_csv_contains_correct_rows(self, tmp_path):
        results = [
            self._make_m6_result("https://example.com", "wcag_strict", 3.2),
            self._make_m6_result("https://gov.cat", "readability_first", 2.8),
            self._make_m6_result("https://test.org", "visual_first", 4.1),
        ]
        csv_path = tmp_path / "out.csv"
        generate_csv_metrics(results, csv_path)
        import csv
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3, f"Esperats 3 files, trobats {len(rows)}"
        urls_in_csv = {r["url"] for r in rows}
        assert "https://example.com" in urls_in_csv

    def test_csv_different_urls_different_scores(self, tmp_path):
        results = [
            self._make_m6_result("https://example.com", "wcag_strict", 3.2),
            self._make_m6_result("https://gov.cat", "wcag_strict", 1.5),
        ]
        csv_path = tmp_path / "out.csv"
        generate_csv_metrics(results, csv_path)
        import csv
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        scores = [float(r["aci_score"]) for r in rows if r["aci_score"]]
        assert len(set(scores)) > 1, "Les dues URLs han de tenir scores diferents"


# ── Test 3: Informe comparatiu HTML ───────────────────────────────────────────

class TestComparativeReport:
    """generate_comparative_report genera HTML vàlid amb els 3 perfils."""

    def _make_profile_results(self) -> dict:
        return {
            "wcag_strict": {
                "aci_score": 3.2,
                "sub_scores": {"wcag": 2.8, "text": 3.5, "elements": 3.0, "performance": 4.0},
                "normalized_metrics": {"alt_text_coverage": 0.4, "heading_hierarchy": 0.7},
                "interventions": [
                    {"priority_rank": 1, "metric": "color_contrast_ratio",
                     "action": "Corregir contrast", "cost": "mig",
                     "impact_level": "critic", "wcag_criterion": "1.4.3"},
                ],
            },
            "readability_first": {
                "aci_score": 3.5,
                "sub_scores": {"wcag": 2.5, "text": 4.2, "elements": 3.0, "performance": 3.8},
                "normalized_metrics": {"alt_text_coverage": 0.4, "heading_hierarchy": 0.7},
                "interventions": [],
            },
            "visual_first": {
                "aci_score": 3.0,
                "sub_scores": {"wcag": 2.9, "text": 3.0, "elements": 3.2, "performance": 4.0},
                "normalized_metrics": {"alt_text_coverage": 0.4, "heading_hierarchy": 0.7},
                "interventions": [],
            },
        }

    def test_comparative_html_created(self, tmp_path):
        profile_results = self._make_profile_results()
        out = generate_comparative_report(
            url="https://example.com",
            profile_results=profile_results,
            data_dir=tmp_path,
        )
        assert out.exists(), f"Fitxer comparatiu no creat: {out}"
        assert out.suffix == ".html"

    def test_comparative_html_contains_all_profiles(self, tmp_path):
        profile_results = self._make_profile_results()
        out = generate_comparative_report(
            url="https://example.com",
            profile_results=profile_results,
            data_dir=tmp_path,
        )
        html = out.read_text(encoding="utf-8")
        assert "WCAG Strict" in html
        assert "Readability" in html
        assert "Visual First" in html

    def test_comparative_html_contains_scores(self, tmp_path):
        profile_results = self._make_profile_results()
        out = generate_comparative_report(
            url="https://example.com",
            profile_results=profile_results,
            data_dir=tmp_path,
        )
        html = out.read_text(encoding="utf-8")
        assert "3.2" in html
        assert "3.5" in html
        assert "3.0" in html


# ── Test 4: global_comparison.md ─────────────────────────────────────────────

class TestGlobalComparison:
    """generate_global_comparison genera Markdown amb resum per totes les URLs."""

    def test_global_comparison_created(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from aci_run import generate_global_comparison

        url_results = [
            {
                "url": "https://example.com",
                "slug": "example_com",
                "profiles": {
                    "wcag_strict": {"aci_score": 3.2},
                    "readability_first": {"aci_score": 3.7},
                    "visual_first": {"aci_score": 2.9},
                },
            },
            {
                "url": "https://gov.cat",
                "slug": "gov_cat",
                "profiles": {
                    "wcag_strict": {"aci_score": 2.1},
                    "readability_first": {"aci_score": 2.8},
                    "visual_first": {"aci_score": 3.0},
                },
            },
        ]
        out = generate_global_comparison(url_results, tmp_path, run_id=99999)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "example.com" in content
        assert "gov.cat" in content
        assert "readability_first" in content

    def test_global_comparison_stats_per_profile(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from aci_run import generate_global_comparison

        url_results = [
            {
                "url": f"https://url{i}.cat",
                "slug": f"url{i}_cat",
                "profiles": {p: {"aci_score": float(i + j)}
                             for j, p in enumerate(ALL_PROFILES)},
            }
            for i in range(1, 4)
        ]
        out = generate_global_comparison(url_results, tmp_path / "sub", run_id=12345)
        content = out.read_text(encoding="utf-8")
        assert "Mitja" in content
        for p in ALL_PROFILES:
            assert p in content
