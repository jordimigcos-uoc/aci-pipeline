"""Tests per a m6_agregacio."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aci_pipeline.m6_agregacio import _normalize_metric, compute_aci_score, run_m6, DEFAULT_NA_VALUE


# ─── Fixtures ────────────────────────────────────────────────────────────────

NORM_CONFIG_RATIO = {"norm": "ratio"}
NORM_CONFIG_BOOL = {"norm": "bool"}
NORM_CONFIG_FLESCH = {"norm": "flesch"}
NORM_CONFIG_INVERSE = {"norm": "inverse_count", "penalty_per_violation": 0.1}
NORM_CONFIG_LCP = {"norm": "lcp", "threshold_good": 2500, "threshold_poor": 4000}

PROFILE_WEIGHTS_SIMPLE = {
    "metric_a": 1,
    "metric_b": 2,
    "metric_c": 3,
}

NORM_CONFIG_SIMPLE = {
    "metric_a": {"norm": "ratio"},
    "metric_b": {"norm": "ratio"},
    "metric_c": {"norm": "ratio"},
}

FULL_PROFILE_WEIGHTS = {
    "color_contrast_ratio": 5,
    "focus_visible_ratio": 4,
    "target_size_clean": 3,
    "keyboard_clean": 5,
    "aria_roles_valid": 4,
    "accessible_names_coverage": 5,
    "audit_critical_violations": 5,
    "audit_high_violations": 4,
    "audit_medium_violations": 2,
    "audit_low_violations": 1,
    "page_flesch": 2,
    "text_complexity": 1,
    "heading_hierarchy": 3,
    "alt_text_coverage": 5,
    "landmark_coverage": 3,
    "performance_lcp": 2,
}

FULL_NORM_CONFIG = {
    "color_contrast_ratio": {"norm": "ratio"},
    "focus_visible_ratio": {"norm": "ratio"},
    "target_size_clean": {"norm": "ratio"},
    "keyboard_clean": {"norm": "bool"},
    "aria_roles_valid": {"norm": "ratio"},
    "accessible_names_coverage": {"norm": "ratio"},
    "audit_critical_violations": {"norm": "inverse_count", "penalty_per_violation": 0.15},
    "audit_high_violations": {"norm": "inverse_count", "penalty_per_violation": 0.05},
    "audit_medium_violations": {"norm": "inverse_count", "penalty_per_violation": 0.02},
    "audit_low_violations": {"norm": "inverse_count", "penalty_per_violation": 0.01},
    "page_flesch": {"norm": "flesch"},
    "text_complexity": {"norm": "ratio"},
    "heading_hierarchy": {"norm": "ratio"},
    "alt_text_coverage": {"norm": "ratio"},
    "landmark_coverage": {"norm": "ratio"},
    "performance_lcp": {"norm": "lcp", "threshold_good": 2500, "threshold_poor": 4000},
}


# ─── Tests _normalize_metric ─────────────────────────────────────────────────

class TestNormalizeMetric:
    # Ratio
    def test_normalize_ratio_zero(self):
        assert _normalize_metric("m", 0.0, NORM_CONFIG_RATIO) == 0.0

    def test_normalize_ratio_one(self):
        assert _normalize_metric("m", 1.0, NORM_CONFIG_RATIO) == 1.0

    def test_normalize_ratio_mid(self):
        assert _normalize_metric("m", 0.5, NORM_CONFIG_RATIO) == 0.5

    def test_normalize_ratio_clips_above_1(self):
        assert _normalize_metric("m", 1.5, NORM_CONFIG_RATIO) == 1.0

    def test_normalize_ratio_clips_below_0(self):
        assert _normalize_metric("m", -0.5, NORM_CONFIG_RATIO) == 0.0

    # Bool
    def test_normalize_bool_true(self):
        assert _normalize_metric("m", True, NORM_CONFIG_BOOL) == 1.0

    def test_normalize_bool_false(self):
        assert _normalize_metric("m", False, NORM_CONFIG_BOOL) == 0.0

    def test_normalize_bool_truthy_int(self):
        assert _normalize_metric("m", 1, NORM_CONFIG_BOOL) == 1.0

    def test_normalize_bool_zero_int(self):
        assert _normalize_metric("m", 0, NORM_CONFIG_BOOL) == 0.0

    # Flesch
    def test_normalize_flesch_100(self):
        assert _normalize_metric("m", 100.0, NORM_CONFIG_FLESCH) == 1.0

    def test_normalize_flesch_0(self):
        assert _normalize_metric("m", 0.0, NORM_CONFIG_FLESCH) == 0.0

    def test_normalize_flesch_60(self):
        result = _normalize_metric("m", 60.0, NORM_CONFIG_FLESCH)
        assert abs(result - 0.6) < 0.001

    def test_normalize_flesch_clips_negative(self):
        assert _normalize_metric("m", -10.0, NORM_CONFIG_FLESCH) == 0.0

    def test_normalize_flesch_clips_above_100(self):
        assert _normalize_metric("m", 120.0, NORM_CONFIG_FLESCH) == 1.0

    # Inverse count
    def test_normalize_inverse_count_zero_violations(self):
        assert _normalize_metric("m", 0, NORM_CONFIG_INVERSE) == 1.0

    def test_normalize_inverse_count_one_violation(self):
        result = _normalize_metric("m", 1, NORM_CONFIG_INVERSE)
        assert abs(result - 0.9) < 0.001

    def test_normalize_inverse_count_ten_violations(self):
        result = _normalize_metric("m", 10, NORM_CONFIG_INVERSE)
        assert result == 0.0  # max(0, 1 - 1.0) = 0.0

    def test_normalize_inverse_count_clips_to_zero(self):
        result = _normalize_metric("m", 100, NORM_CONFIG_INVERSE)
        assert result == 0.0

    def test_normalize_inverse_count_custom_penalty(self):
        config = {"norm": "inverse_count", "penalty_per_violation": 0.15}
        result = _normalize_metric("m", 2, config)
        assert abs(result - 0.7) < 0.001

    # LCP
    def test_normalize_lcp_good(self):
        assert _normalize_metric("m", 1000, NORM_CONFIG_LCP) == 1.0

    def test_normalize_lcp_exactly_good_threshold(self):
        assert _normalize_metric("m", 2500, NORM_CONFIG_LCP) == 1.0

    def test_normalize_lcp_poor(self):
        assert _normalize_metric("m", 4000, NORM_CONFIG_LCP) == 0.0

    def test_normalize_lcp_above_poor(self):
        assert _normalize_metric("m", 6000, NORM_CONFIG_LCP) == 0.0

    def test_normalize_lcp_midpoint(self):
        result = _normalize_metric("m", 3250, NORM_CONFIG_LCP)
        assert abs(result - 0.5) < 0.01

    def test_normalize_lcp_interpolation(self):
        # (4000 - 3000) / (4000 - 2500) = 1000/1500 = 0.667
        result = _normalize_metric("m", 3000, NORM_CONFIG_LCP)
        expected = (4000 - 3000) / (4000 - 2500)
        assert abs(result - expected) < 0.001

    # NA value
    def test_normalize_na_none_returns_default(self):
        assert _normalize_metric("m", None, NORM_CONFIG_RATIO) == DEFAULT_NA_VALUE

    def test_normalize_na_default_value(self):
        assert DEFAULT_NA_VALUE == 0.5


# ─── Tests compute_aci_score ─────────────────────────────────────────────────

class TestComputeAciScore:
    def test_perfect_score_all_ones(self):
        metrics = {"metric_a": 1.0, "metric_b": 1.0, "metric_c": 1.0}
        result = compute_aci_score(metrics, PROFILE_WEIGHTS_SIMPLE, NORM_CONFIG_SIMPLE)
        assert result["aci_score"] == 5.0

    def test_zero_score_all_zeros(self):
        metrics = {"metric_a": 0.0, "metric_b": 0.0, "metric_c": 0.0}
        result = compute_aci_score(metrics, PROFILE_WEIGHTS_SIMPLE, NORM_CONFIG_SIMPLE)
        assert result["aci_score"] == 0.0

    def test_partial_score_computed_correctly(self):
        # Pesos: a=1, b=2, c=3. Valors: a=1.0, b=0.5, c=0.0
        # Score = (1.0*1 + 0.5*2 + 0.0*3) / (1+2+3) = 2.0/6 = 0.333...
        # ACI = 0.333 * 5 = 1.667
        metrics = {"metric_a": 1.0, "metric_b": 0.5, "metric_c": 0.0}
        result = compute_aci_score(metrics, PROFILE_WEIGHTS_SIMPLE, NORM_CONFIG_SIMPLE)
        assert abs(result["aci_score"] - 1.667) < 0.01

    def test_aci_normalized_range(self):
        metrics = {"metric_a": 0.7, "metric_b": 0.3, "metric_c": 0.5}
        result = compute_aci_score(metrics, PROFILE_WEIGHTS_SIMPLE, NORM_CONFIG_SIMPLE)
        assert 0.0 <= result["aci_normalized"] <= 1.0

    def test_aci_score_range(self):
        metrics = {"metric_a": 0.7, "metric_b": 0.3, "metric_c": 0.5}
        result = compute_aci_score(metrics, PROFILE_WEIGHTS_SIMPLE, NORM_CONFIG_SIMPLE)
        assert 0.0 <= result["aci_score"] <= 5.0

    def test_zero_weight_metric_ignored(self):
        weights = {"metric_a": 0, "metric_b": 1, "metric_c": 1}
        metrics = {"metric_a": 0.0, "metric_b": 1.0, "metric_c": 1.0}
        result = compute_aci_score(metrics, weights, NORM_CONFIG_SIMPLE)
        assert result["aci_score"] == 5.0  # metric_a ignorada

    def test_missing_metric_uses_na_value(self):
        metrics = {}  # Cap mètrica present
        result = compute_aci_score(metrics, PROFILE_WEIGHTS_SIMPLE, NORM_CONFIG_SIMPLE)
        # Totes NA → 0.5 * 5 = 2.5
        assert abs(result["aci_score"] - 2.5) < 0.01

    def test_sub_scores_computed(self):
        metrics = {
            "color_contrast_ratio": 1.0, "focus_visible_ratio": 1.0,
            "target_size_clean": 1.0, "keyboard_clean": True,
            "audit_critical_violations": 0, "audit_high_violations": 0,
            "page_flesch": 80.0, "text_complexity": 0.8, "heading_hierarchy": 1.0,
            "aria_roles_valid": 1.0, "accessible_names_coverage": 1.0,
            "alt_text_coverage": 1.0, "landmark_coverage": 1.0,
            "performance_lcp": 1500,
        }
        result = compute_aci_score(metrics, FULL_PROFILE_WEIGHTS, FULL_NORM_CONFIG)
        assert "sub_scores" in result
        assert "wcag" in result["sub_scores"]
        assert "text" in result["sub_scores"]
        assert "elements" in result["sub_scores"]

    def test_metrics_evaluated_count(self):
        result = compute_aci_score(
            {"metric_a": 0.5, "metric_b": 0.5, "metric_c": 0.5},
            PROFILE_WEIGHTS_SIMPLE,
            NORM_CONFIG_SIMPLE,
        )
        assert result["metrics_evaluated"] == 3

    def test_metrics_na_count(self):
        metrics = {"metric_a": None, "metric_b": 0.5, "metric_c": None}
        result = compute_aci_score(metrics, PROFILE_WEIGHTS_SIMPLE, NORM_CONFIG_SIMPLE)
        assert result["metrics_na"] == 2

    def test_weights_preserved_in_result(self):
        result = compute_aci_score(
            {"metric_a": 0.5, "metric_b": 0.5, "metric_c": 0.5},
            PROFILE_WEIGHTS_SIMPLE,
            NORM_CONFIG_SIMPLE,
        )
        assert result["weights"]["metric_a"] == 1
        assert result["weights"]["metric_b"] == 2
        assert result["weights"]["metric_c"] == 3

    def test_normalized_metrics_in_range(self):
        metrics = {"metric_a": 0.3, "metric_b": 0.7, "metric_c": 0.5}
        result = compute_aci_score(metrics, PROFILE_WEIGHTS_SIMPLE, NORM_CONFIG_SIMPLE)
        for k, v in result["normalized_metrics"].items():
            assert 0.0 <= v <= 1.0, f"Normalized metric {k} = {v} out of range"

    def test_empty_weights_returns_zero(self):
        result = compute_aci_score({"metric_a": 1.0}, {}, {})
        assert result["aci_score"] == 0.0
        assert result["total_weight"] == 0


# ─── Tests run_m6 integrat ───────────────────────────────────────────────────

class TestRunM6Integration:
    def _make_m4_result(self, **overrides):
        base = {
            "metrics": {
                "color_contrast_ratio": 0.8,
                "focus_visible_ratio": 0.7,
                "target_size_clean": 0.9,
                "keyboard_clean": True,
                "aria_roles_valid": 1.0,
                "accessible_names_coverage": 0.9,
                "audit_critical_violations": 0,
                "audit_high_violations": 1,
                "audit_medium_violations": 2,
                "audit_low_violations": 0,
                "page_flesch": 65.0,
                "text_complexity": 0.65,
                "heading_hierarchy": 1.0,
                "alt_text_coverage": 0.8,
                "landmark_coverage": 1.0,
                "performance_lcp": 2000,
            }
        }
        base["metrics"].update(overrides)
        return base

    def test_run_m6_returns_aci_score(self, tmp_path):
        m4 = self._make_m4_result()
        result = run_m6(m4, "wcag_strict", FULL_PROFILE_WEIGHTS, FULL_NORM_CONFIG,
                        "https://example.com", data_dir=tmp_path)
        assert "aci_score" in result
        assert 0.0 <= result["aci_score"] <= 5.0

    def test_run_m6_creates_json_file(self, tmp_path):
        m4 = self._make_m4_result()
        run_m6(m4, "wcag_strict", FULL_PROFILE_WEIGHTS, FULL_NORM_CONFIG,
               "https://example.com", data_dir=tmp_path, slug="test", ts=99999)
        expected = tmp_path / "metrics" / "test_99999_wcag_strict.json"
        assert expected.exists()

    def test_run_m6_creates_csv_file(self, tmp_path):
        m4 = self._make_m4_result()
        run_m6(m4, "wcag_strict", FULL_PROFILE_WEIGHTS, FULL_NORM_CONFIG,
               "https://example.com", data_dir=tmp_path, slug="test", ts=99999)
        csv_path = tmp_path / "metrics" / "score_summary.csv"
        assert csv_path.exists()

    def test_run_m6_profile_in_result(self, tmp_path):
        m4 = self._make_m4_result()
        result = run_m6(m4, "readability_first", FULL_PROFILE_WEIGHTS, FULL_NORM_CONFIG,
                        "https://example.com", data_dir=tmp_path)
        assert result["profile"] == "readability_first"

    def test_run_m6_good_metrics_high_score(self, tmp_path):
        m4 = self._make_m4_result(
            color_contrast_ratio=1.0, focus_visible_ratio=1.0,
            alt_text_coverage=1.0, landmark_coverage=1.0,
            audit_critical_violations=0, audit_high_violations=0,
        )
        result = run_m6(m4, "wcag_strict", FULL_PROFILE_WEIGHTS, FULL_NORM_CONFIG,
                        "https://example.com", data_dir=tmp_path)
        assert result["aci_score"] > 3.0

    def test_run_m6_bad_metrics_low_score(self, tmp_path):
        m4 = self._make_m4_result(
            color_contrast_ratio=0.0, focus_visible_ratio=0.0,
            alt_text_coverage=0.0, landmark_coverage=0.0,
            audit_critical_violations=5, audit_high_violations=5,
            accessible_names_coverage=0.0, aria_roles_valid=0.0,
        )
        result = run_m6(m4, "wcag_strict", FULL_PROFILE_WEIGHTS, FULL_NORM_CONFIG,
                        "https://example.com", data_dir=tmp_path)
        assert result["aci_score"] < 2.5

    def test_run_m6_url_in_result(self, tmp_path):
        m4 = self._make_m4_result()
        result = run_m6(m4, "wcag_strict", FULL_PROFILE_WEIGHTS, FULL_NORM_CONFIG,
                        "https://mysite.com", data_dir=tmp_path)
        assert result["url"] == "https://mysite.com"
