"""
Test d'integració que processa data/samples/test_page.html.
Executa M2 + M3 + M4 (sense Playwright) + M6 i verifica resultats de qualitat.
"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aci_pipeline.m2_extraccio import extract_structure, run_m2
from aci_pipeline.m3_segmentacio import run_m3
from aci_pipeline.m4_analisi import run_m4
from aci_pipeline.m6_agregacio import compute_aci_score
from aci_pipeline.m7_perfil import load_scoring_config, get_profile_weights, get_norm_config

# Path al fitxer de prova
TEST_PAGE_PATH = Path(__file__).parent.parent / "data" / "samples" / "test_page.html"
CONFIGS_PATH = Path(__file__).parent.parent / "configs" / "scoring_config.yaml"


@pytest.fixture(scope="module")
def test_html() -> str:
    """Carrega la pàgina HTML de prova."""
    assert TEST_PAGE_PATH.exists(), f"Fitxer de prova no trobat: {TEST_PAGE_PATH}"
    return TEST_PAGE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def m2_result(test_html) -> dict:
    """Executa M2 sobre la pàgina de prova."""
    return extract_structure(test_html, url="file://test_page.html")


@pytest.fixture(scope="module")
def m3_result(m2_result) -> dict:
    """Executa M3 sobre el resultat de M2."""
    from aci_pipeline.m3_segmentacio import _build_heading_hierarchy, _segment_text_blocks, _analyze_figures
    headings = m2_result.get("headings", [])
    text_blocks = m2_result.get("text_blocks", [])
    images = m2_result.get("images", [])
    hierarchy = _build_heading_hierarchy(headings)
    segments = _segment_text_blocks(text_blocks)
    figures = _analyze_figures(images)
    return {
        "url": "file://test_page.html",
        "heading_hierarchy": hierarchy,
        "segments": segments,
        "figures": figures,
        "stats": {
            "total_segments": len(segments),
            "total_words": sum(s.get("word_count", 0) for s in segments),
            "avg_words_per_block": 0,
            "figures_needing_ai": sum(1 for f in figures if f["needs_ai"]),
            "heading_depth": hierarchy.get("depth", 0),
        },
    }


@pytest.fixture(scope="module")
def m4_result(m2_result, m3_result, tmp_path_factory) -> dict:
    """Executa M4 sense axe-core ni perf (fallback)."""
    tmp = tmp_path_factory.mktemp("integration_m4")
    return run_m4(
        page_structure=m2_result,
        m3_result=m3_result,
        axe_result={},
        perf={},
        url="file://test_page.html",
        data_dir=tmp,
    )


@pytest.fixture(scope="module")
def scoring_config() -> dict:
    """Carrega la configuració de puntuació."""
    return load_scoring_config(CONFIGS_PATH)


@pytest.fixture(scope="module")
def aci_result_wcag(m4_result, scoring_config) -> dict:
    """Calcula ACI amb el perfil wcag_strict."""
    profile_weights = get_profile_weights(scoring_config, "wcag_strict")
    norm_config = get_norm_config(scoring_config)
    metrics = m4_result.get("metrics", {})
    return compute_aci_score(metrics, profile_weights, norm_config)


# ─── Tests M2 sobre test_page.html ───────────────────────────────────────────

class TestM2OnTestPage:
    def test_html_loaded_successfully(self, test_html):
        assert len(test_html) > 100

    def test_extracts_headings(self, m2_result):
        headings = m2_result["headings"]
        assert len(headings) >= 2  # H1 i H3 com a mínim

    def test_detects_multiple_h1(self, m2_result):
        h1_count = sum(1 for h in m2_result["headings"] if h["level"] == 1)
        assert h1_count >= 2  # La pàgina de prova té 2 H1 intencionats

    def test_extracts_images(self, m2_result):
        images = m2_result["images"]
        assert len(images) >= 3  # logo.png, chart.png, decoration.jpg

    def test_images_missing_alt(self, m2_result):
        images_without_alt = [i for i in m2_result["images"]
                              if i.get("alt") is None and i.get("type") == "img"]
        assert len(images_without_alt) >= 1  # decoration.jpg sense alt

    def test_low_alt_coverage(self, m2_result):
        images = [i for i in m2_result["images"] if i.get("type") == "img"]
        if images:
            meaningful = sum(1 for i in images if i["meaningful_alt"])
            ratio = meaningful / len(images)
            assert ratio < 0.5  # Menys de la meitat amb alt significatiu

    def test_extracts_form(self, m2_result):
        assert len(m2_result["forms"]) >= 1

    def test_form_has_unlabeled_inputs(self, m2_result):
        form = m2_result["forms"][0]
        unlabeled = form["total_inputs"] - form["labeled_inputs"]
        assert unlabeled >= 1  # El formulari de prova té inputs sense etiqueta

    def test_detects_interactive_elements(self, m2_result):
        assert len(m2_result["interactive_elements"]) >= 3

    def test_detects_table(self, m2_result):
        assert len(m2_result["tables"]) >= 1

    def test_table_no_headers(self, m2_result):
        table_without_headers = [t for t in m2_result["tables"] if not t["has_headers"]]
        assert len(table_without_headers) >= 1

    def test_detects_svg(self, m2_result):
        svgs = [i for i in m2_result["images"] if i.get("type") == "svg"]
        assert len(svgs) >= 1

    def test_svg_no_description(self, m2_result):
        svgs = [i for i in m2_result["images"] if i.get("type") == "svg"]
        svg_without_desc = [s for s in svgs if not s["meaningful_alt"]]
        assert len(svg_without_desc) >= 1

    def test_no_landmark_main(self, m2_result):
        # La pàgina de prova no té <main>
        landmarks = m2_result["landmarks"]
        assert "main" not in landmarks

    def test_no_landmark_nav(self, m2_result):
        landmarks = m2_result["landmarks"]
        assert "nav" not in landmarks

    def test_plain_text_extracted(self, m2_result):
        assert len(m2_result["plain_text"]) > 100

    def test_text_length_positive(self, m2_result):
        assert m2_result["text_length"] > 100


# ─── Tests M3 sobre test_page.html ───────────────────────────────────────────

class TestM3OnTestPage:
    def test_heading_hierarchy_violations_detected(self, m3_result):
        hierarchy = m3_result["heading_hierarchy"]
        assert len(hierarchy["violations"]) >= 1  # Salt H1→H3

    def test_heading_hierarchy_ok_false(self, m3_result):
        hierarchy = m3_result["heading_hierarchy"]
        assert hierarchy["hierarchy_ok"] is False

    def test_multiple_h1_detected(self, m3_result):
        hierarchy = m3_result["heading_hierarchy"]
        assert hierarchy["multiple_h1"] is True

    def test_heading_hierarchy_score_penalised(self, m3_result):
        score = m3_result["heading_hierarchy"]["heading_hierarchy_score"]
        assert score < 1.0  # Ha de tenir penalització

    def test_segments_extracted(self, m3_result):
        assert m3_result["stats"]["total_segments"] >= 1

    def test_figures_analyzed(self, m3_result):
        assert len(m3_result["figures"]) >= 1

    def test_figures_needing_ai(self, m3_result):
        assert m3_result["stats"]["figures_needing_ai"] >= 1


# ─── Tests M4 sobre test_page.html ───────────────────────────────────────────

class TestM4OnTestPage:
    def test_alt_text_coverage_low(self, m4_result):
        alt_cov = m4_result["metrics"]["alt_text_coverage"]
        assert alt_cov < 0.5  # La pàgina té moltes imatges sense alt

    def test_landmark_coverage_low(self, m4_result):
        landmark_cov = m4_result["metrics"]["landmark_coverage"]
        assert landmark_cov < 0.5  # Sense main, nav, header, footer

    def test_heading_hierarchy_penalised(self, m4_result):
        hh = m4_result["metrics"]["heading_hierarchy"]
        assert hh < 1.0

    def test_accessible_names_coverage_low(self, m4_result):
        names_cov = m4_result["metrics"]["accessible_names_coverage"]
        # Botons sense nom + inputs sense etiqueta → cobertura baixa
        assert names_cov < 0.9

    def test_metrics_dict_present(self, m4_result):
        assert "metrics" in m4_result
        assert len(m4_result["metrics"]) >= 10

    def test_text_metrics_computed(self, m4_result):
        tm = m4_result["text_metrics"]
        assert tm["num_words"] > 0

    def test_aria_elements_analyzed(self, m4_result):
        assert "aria_validity" in m4_result


# ─── Tests ACI sobre test_page.html ──────────────────────────────────────────

class TestACIOnTestPage:
    def test_aci_score_below_threshold(self, aci_result_wcag):
        """La pàgina de prova té molts problemes; ACI ha de ser < 3.0."""
        aci = aci_result_wcag["aci_score"]
        assert aci < 3.0, f"ACI = {aci:.2f} hauria de ser < 3.0 per a la pàgina de prova"

    def test_aci_score_not_zero(self, aci_result_wcag):
        """ACI > 0 perquè algunes mètriques estan bé."""
        assert aci_result_wcag["aci_score"] > 0.0

    def test_aci_score_range(self, aci_result_wcag):
        assert 0.0 <= aci_result_wcag["aci_score"] <= 5.0

    def test_normalized_metrics_computed(self, aci_result_wcag):
        assert len(aci_result_wcag["normalized_metrics"]) >= 5

    def test_sub_scores_present(self, aci_result_wcag):
        assert "sub_scores" in aci_result_wcag

    def test_elements_subscore_low(self, aci_result_wcag):
        """Sub-score d'elements hauria de ser baix per la falta d'alt i landmarks."""
        elements_score = aci_result_wcag["sub_scores"].get("elements")
        if elements_score is not None:
            assert elements_score < 3.5

    def test_metrics_evaluated_count(self, aci_result_wcag):
        assert aci_result_wcag["metrics_evaluated"] >= 5


# ─── Tests M7 intervencions ──────────────────────────────────────────────────

class TestInterventionsOnTestPage:
    def test_at_least_5_interventions(self, m4_result, aci_result_wcag, tmp_path):
        from aci_pipeline.m7_perfil import prioritize_interventions
        interventions = prioritize_interventions(aci_result_wcag, m4_result)
        assert len(interventions) >= 5

    def test_interventions_sorted_by_priority(self, m4_result, aci_result_wcag):
        from aci_pipeline.m7_perfil import prioritize_interventions
        interventions = prioritize_interventions(aci_result_wcag, m4_result)
        scores = [i["priority_score"] for i in interventions]
        assert scores == sorted(scores, reverse=True)

    def test_interventions_have_required_fields(self, m4_result, aci_result_wcag):
        from aci_pipeline.m7_perfil import prioritize_interventions
        interventions = prioritize_interventions(aci_result_wcag, m4_result)
        for interv in interventions:
            assert "metric" in interv
            assert "action" in interv
            assert "priority_rank" in interv
            assert "cost" in interv
            assert "wcag_criterion" in interv

    def test_landmark_or_alt_in_top_interventions(self, m4_result, aci_result_wcag):
        from aci_pipeline.m7_perfil import prioritize_interventions
        interventions = prioritize_interventions(aci_result_wcag, m4_result)
        top5_metrics = {i["metric"] for i in interventions[:5]}
        # Com a mínim una de landmark_coverage o alt_text_coverage ha d'estar al top 5
        relevant = {"landmark_coverage", "alt_text_coverage", "accessible_names_coverage"}
        assert len(top5_metrics & relevant) >= 1


# ─── Test de generació de fitxer ─────────────────────────────────────────────

class TestPipelineOutputFiles:
    def test_m2_creates_json_file(self, test_html, tmp_path):
        run_m2(test_html, url="file://test_page.html",
               data_dir=tmp_path, slug="test", ts=111)
        expected = tmp_path / "processed" / "structure" / "test_111.json"
        assert expected.exists()

    def test_m2_json_valid(self, test_html, tmp_path):
        run_m2(test_html, url="file://test_page.html",
               data_dir=tmp_path, slug="test2", ts=222)
        json_path = tmp_path / "processed" / "structure" / "test2_222.json"
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "headings" in data
        assert "images" in data
        assert "landmarks" in data

    def test_m3_creates_json_file(self, m2_result, tmp_path):
        run_m3(m2_result, url="file://test_page.html",
               data_dir=tmp_path, slug="test3", ts=333)
        expected = tmp_path / "processed" / "structure" / "test3_333_segments.json"
        assert expected.exists()

    def test_m4_creates_metrics_file(self, m2_result, m3_result, tmp_path):
        run_m4(m2_result, m3_result, {}, {},
               url="file://test_page.html",
               data_dir=tmp_path, slug="test4", ts=444)
        expected = tmp_path / "processed" / "test4_444_metrics.json"
        assert expected.exists()
