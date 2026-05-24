"""Tests per a m4_analisi."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aci_pipeline.m4_analisi import (
    _compute_text_metrics,
    _analyze_axe_results,
    _compute_perf_metrics,
    _compute_alt_coverage,
    _compute_accessible_names,
    _compute_aria_validity,
    _compute_landmark_coverage,
    run_m4,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

SIMPLE_TEXT = "The cat sat on the mat. The dog ran fast. It was a sunny day."

COMPLEX_TEXT = (
    "La implementació d'infraestructures tecnoinformàtiques heterogènies en "
    "entorns administrativoinstitucionals requereix una planificació exhaustiva "
    "i sistematitzada que contempli les interdependències multifactorials dels "
    "sistemes d'informació corporatius."
)

AXE_EMPTY = {}

AXE_WITH_VIOLATIONS = {
    "violations": [
        {
            "id": "color-contrast",
            "impact": "serious",
            "description": "Elements must have sufficient color contrast",
            "help": "Fix color contrast",
            "nodes": [{"html": "<p>text</p>"}, {"html": "<span>other</span>"}],
        },
        {
            "id": "image-alt",
            "impact": "critical",
            "description": "Images must have alternate text",
            "help": "Add alt text",
            "nodes": [{"html": "<img src='x.png'>"}],
        },
        {
            "id": "button-name",
            "impact": "critical",
            "description": "Buttons must have discernible text",
            "help": "Add button label",
            "nodes": [{"html": "<button></button>"}],
        },
        {
            "id": "label",
            "impact": "moderate",
            "description": "Form elements must have labels",
            "help": "Add form labels",
            "nodes": [{"html": "<input type='text'>"}],
        },
    ],
    "passes": [
        {"id": "aria-roles", "impact": None},
        {"id": "landmark-one-main", "impact": None},
    ],
    "incomplete": [],
}


# ─── Tests text metrics ──────────────────────────────────────────────────────

class TestComputeTextMetrics:
    def test_returns_dict_with_expected_keys(self):
        result = _compute_text_metrics(SIMPLE_TEXT)
        keys = {"flesch_reading_ease", "num_words", "num_sentences", "avg_sentence_length"}
        assert keys.issubset(result.keys())

    def test_num_words_positive(self):
        result = _compute_text_metrics(SIMPLE_TEXT)
        assert result["num_words"] > 0

    def test_num_sentences_positive(self):
        result = _compute_text_metrics(SIMPLE_TEXT)
        assert result["num_sentences"] > 0

    def test_flesch_range(self):
        result = _compute_text_metrics(SIMPLE_TEXT)
        if result["flesch_reading_ease"] is not None:
            # Flesch pot anar de ~-100 a 121, però típicament 0-100
            assert -200 < result["flesch_reading_ease"] < 200

    def test_avg_sentence_length_computed(self):
        result = _compute_text_metrics(SIMPLE_TEXT)
        assert result["avg_sentence_length"] > 0

    def test_empty_text_no_crash(self):
        result = _compute_text_metrics("")
        assert "num_words" in result
        assert result["num_words"] == 0

    def test_complex_text_lower_flesch(self):
        simple_result = _compute_text_metrics(SIMPLE_TEXT)
        complex_result = _compute_text_metrics(COMPLEX_TEXT)
        # Si tots dos retornen Flesch, el text simple hauria de ser més llegible
        if (simple_result.get("flesch_reading_ease") is not None and
                complex_result.get("flesch_reading_ease") is not None):
            assert simple_result["flesch_reading_ease"] > complex_result["flesch_reading_ease"]


# ─── Tests axe analysis ──────────────────────────────────────────────────────

class TestAnalyzeAxeResults:
    def test_empty_axe_returns_zeros(self):
        result = _analyze_axe_results(AXE_EMPTY)
        assert result["violations_count"] == 0
        assert result["critical_violations"] == 0
        assert result["serious_violations"] == 0
        assert result["moderate_violations"] == 0
        assert result["minor_violations"] == 0

    def test_empty_axe_no_details(self):
        result = _analyze_axe_results(AXE_EMPTY)
        assert result["violations_detail"] == []

    def test_with_violations_counts_correctly(self):
        result = _analyze_axe_results(AXE_WITH_VIOLATIONS)
        assert result["violations_count"] == 4
        assert result["critical_violations"] == 2
        assert result["serious_violations"] == 1
        assert result["moderate_violations"] == 1
        assert result["minor_violations"] == 0

    def test_violations_detail_populated(self):
        result = _analyze_axe_results(AXE_WITH_VIOLATIONS)
        assert len(result["violations_detail"]) == 4

    def test_violations_detail_has_required_fields(self):
        result = _analyze_axe_results(AXE_WITH_VIOLATIONS)
        v = result["violations_detail"][0]
        assert "id" in v
        assert "impact" in v
        assert "nodes_affected" in v

    def test_nodes_affected_counted(self):
        result = _analyze_axe_results(AXE_WITH_VIOLATIONS)
        # color-contrast té 2 nodes
        cc = next(v for v in result["violations_detail"] if v["id"] == "color-contrast")
        assert cc["nodes_affected"] == 2

    def test_passes_counted(self):
        result = _analyze_axe_results(AXE_WITH_VIOLATIONS)
        assert result["passes_count"] == 2


# ─── Tests perf metrics ──────────────────────────────────────────────────────

class TestComputePerfMetrics:
    def test_good_lcp_rating(self):
        result = _compute_perf_metrics({"lcp": 1500, "ttfb": 200})
        assert result["lcp_rating"] == "good"
        assert result["lcp_ms"] == 1500

    def test_needs_improvement_lcp(self):
        result = _compute_perf_metrics({"lcp": 3000, "ttfb": 500})
        assert result["lcp_rating"] == "needs_improvement"

    def test_poor_lcp_rating(self):
        result = _compute_perf_metrics({"lcp": 5000})
        assert result["lcp_rating"] == "poor"

    def test_unknown_lcp_when_none(self):
        result = _compute_perf_metrics({"lcp": None})
        assert result["lcp_rating"] == "unknown"

    def test_empty_perf_no_crash(self):
        result = _compute_perf_metrics({})
        assert "lcp_ms" in result
        assert result["lcp_ms"] is None


# ─── Tests alt coverage ──────────────────────────────────────────────────────

class TestComputeAltCoverage:
    def test_all_with_alt_returns_1(self):
        images = [
            {"meaningful_alt": True, "alt": "desc 1"},
            {"meaningful_alt": True, "alt": "desc 2"},
        ]
        result = _compute_alt_coverage(images)
        assert result["alt_coverage_ratio"] == 1.0

    def test_none_with_alt_returns_0(self):
        images = [
            {"meaningful_alt": False, "alt": None},
            {"meaningful_alt": False, "alt": ""},
        ]
        result = _compute_alt_coverage(images)
        assert result["alt_coverage_ratio"] == 0.0

    def test_partial_alt_coverage(self):
        images = [
            {"meaningful_alt": True, "alt": "good alt"},
            {"meaningful_alt": False, "alt": None},
            {"meaningful_alt": False, "alt": "image"},
            {"meaningful_alt": True, "alt": "another good alt"},
        ]
        result = _compute_alt_coverage(images)
        assert result["alt_coverage_ratio"] == 0.5
        assert result["total_images"] == 4
        assert result["images_with_alt"] == 2

    def test_empty_images_returns_perfect(self):
        result = _compute_alt_coverage([])
        assert result["alt_coverage_ratio"] == 1.0
        assert result["total_images"] == 0

    def test_needs_ai_counted(self):
        images = [
            {"meaningful_alt": False, "alt": "image", "needs_ai": True},
            {"meaningful_alt": True, "alt": "good", "needs_ai": False},
        ]
        result = _compute_alt_coverage(images)
        assert result["images_needing_ai"] == 1


# ─── Tests accessible names ──────────────────────────────────────────────────

class TestComputeAccessibleNames:
    def test_all_with_name_returns_1(self):
        elements = [
            {"has_accessible_name": True},
            {"has_accessible_name": True},
        ]
        result = _compute_accessible_names(elements)
        assert result["accessible_names_coverage"] == 1.0

    def test_none_with_name_returns_0(self):
        elements = [
            {"has_accessible_name": False},
            {"has_accessible_name": False},
        ]
        result = _compute_accessible_names(elements)
        assert result["accessible_names_coverage"] == 0.0

    def test_partial_coverage(self):
        elements = [
            {"has_accessible_name": True},
            {"has_accessible_name": False},
            {"has_accessible_name": True},
            {"has_accessible_name": False},
        ]
        result = _compute_accessible_names(elements)
        assert result["accessible_names_coverage"] == 0.5
        assert result["with_name"] == 2
        assert result["total_interactive"] == 4

    def test_empty_elements_returns_perfect(self):
        result = _compute_accessible_names([])
        assert result["accessible_names_coverage"] == 1.0


# ─── Tests ARIA validity ─────────────────────────────────────────────────────

class TestComputeAriaValidity:
    def test_all_valid(self):
        aria = [{"valid": True}, {"valid": True}]
        result = _compute_aria_validity(aria)
        assert result["aria_roles_valid_ratio"] == 1.0

    def test_none_valid(self):
        aria = [{"valid": False}, {"valid": False}]
        result = _compute_aria_validity(aria)
        assert result["aria_roles_valid_ratio"] == 0.0

    def test_partial_validity(self):
        aria = [{"valid": True}, {"valid": False}, {"valid": True}]
        result = _compute_aria_validity(aria)
        assert abs(result["aria_roles_valid_ratio"] - 2/3) < 0.01

    def test_empty_returns_perfect(self):
        result = _compute_aria_validity([])
        assert result["aria_roles_valid_ratio"] == 1.0


# ─── Tests landmark coverage ─────────────────────────────────────────────────

class TestComputeLandmarkCoverage:
    def test_all_essential_present(self):
        landmarks = {"main": 1, "nav": 1, "header": 1, "footer": 1}
        result = _compute_landmark_coverage(landmarks)
        assert result["landmark_coverage_ratio"] == 1.0
        assert result["essential_missing"] == []

    def test_none_present(self):
        result = _compute_landmark_coverage({})
        assert result["landmark_coverage_ratio"] == 0.0
        assert set(result["essential_missing"]) == {"main", "nav", "header", "footer"}

    def test_partial_coverage(self):
        landmarks = {"main": 1, "nav": 1}
        result = _compute_landmark_coverage(landmarks)
        assert result["landmark_coverage_ratio"] == 0.5
        assert set(result["essential_missing"]) == {"header", "footer"}

    def test_landmarks_present_listed(self):
        landmarks = {"main": 1, "nav": 2, "section": 3}
        result = _compute_landmark_coverage(landmarks)
        assert "main" in result["landmarks_present"]
        assert "nav" in result["landmarks_present"]


# ─── Tests run_m4 integrat ───────────────────────────────────────────────────

class TestRunM4Integration:
    def setup_method(self, tmp_path_factory):
        self.page_structure = {
            "plain_text": SIMPLE_TEXT,
            "images": [
                {"meaningful_alt": True, "alt": "desc", "needs_ai": False},
                {"meaningful_alt": False, "alt": None, "needs_ai": False},
            ],
            "interactive_elements": [
                {"has_accessible_name": True},
                {"has_accessible_name": False},
            ],
            "aria_elements": [
                {"valid": True, "role": "button"},
                {"valid": False, "role": "badrole"},
            ],
            "landmarks": {"main": 1, "nav": 1},
        }
        self.m3_result = {
            "heading_hierarchy": {
                "heading_hierarchy_score": 0.8,
                "has_h1": True,
                "hierarchy_ok": True,
                "violations": [],
            }
        }

    def test_run_m4_returns_metrics_dict(self, tmp_path):
        result = run_m4(
            self.page_structure, self.m3_result, {}, {},
            url="https://example.com", data_dir=tmp_path
        )
        assert "metrics" in result
        assert "aci_score" not in result  # ACI es calcula a M6

    def test_metrics_keys_present(self, tmp_path):
        result = run_m4(
            self.page_structure, self.m3_result, {}, {},
            url="https://example.com", data_dir=tmp_path
        )
        m = result["metrics"]
        assert "aria_roles_valid" in m
        assert "accessible_names_coverage" in m
        assert "alt_text_coverage" in m
        assert "landmark_coverage" in m
        assert "heading_hierarchy" in m

    def test_alt_coverage_computed(self, tmp_path):
        result = run_m4(
            self.page_structure, self.m3_result, {}, {},
            url="https://example.com", data_dir=tmp_path
        )
        assert result["metrics"]["alt_text_coverage"] == 0.5

    def test_aria_validity_computed(self, tmp_path):
        result = run_m4(
            self.page_structure, self.m3_result, {}, {},
            url="https://example.com", data_dir=tmp_path
        )
        assert result["metrics"]["aria_roles_valid"] == 0.5

    def test_output_file_created(self, tmp_path):
        run_m4(
            self.page_structure, self.m3_result, {}, {},
            url="https://example.com", data_dir=tmp_path,
            slug="test_slug", ts=12345
        )
        expected = tmp_path / "processed" / "test_slug_12345_metrics.json"
        assert expected.exists()

    def test_axe_violations_integrated(self, tmp_path):
        result = run_m4(
            self.page_structure, self.m3_result, AXE_WITH_VIOLATIONS, {},
            url="https://example.com", data_dir=tmp_path
        )
        assert result["axe_summary"]["critical_violations"] == 2
        assert result["axe_summary"]["serious_violations"] == 1

    def test_perf_lcp_rating_computed(self, tmp_path):
        result = run_m4(
            self.page_structure, self.m3_result, {}, {"lcp": 1200, "ttfb": 100},
            url="https://example.com", data_dir=tmp_path
        )
        assert result["perf"]["lcp_rating"] == "good"
