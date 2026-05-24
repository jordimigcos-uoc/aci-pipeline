"""
tests/test_pipeline.py

Tests per a:
  - Esborrat pre-run (TestPreRunCleanup)
  - Filtrat per perfil (TestProfileFiltering)
  - Absència de duplicats (TestNoDuplicates)
"""

from __future__ import annotations

import csv
import json
import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Assegura que src/ és al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Directori data/ temporal per a cada test."""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture()
def populated_data_dir(data_dir: Path) -> Path:
    """data_dir amb fitxers simulats de runs anteriors."""
    (data_dir / "assets").mkdir()
    (data_dir / "assets" / "example_com_123.html").write_text("<html/>")
    (data_dir / "processed").mkdir()
    (data_dir / "processed" / "example_com_123_metrics.json").write_text("{}")
    reports = data_dir / "reports" / "example_com"
    reports.mkdir(parents=True)
    (reports / "example_com_123_wcag_strict.html").write_text("<html/>")
    metrics = data_dir / "metrics"
    metrics.mkdir()
    (metrics / "perf").mkdir()
    (metrics / "perf" / "example_com_123_perf.json").write_text("{}")
    (metrics / "score_summary.csv").write_text(
        "url,timestamp,profile,aci_score,aci_normalized,metrics_evaluated,metrics_na\n"
        "https://example.com,123,wcag_strict,3.5,0.7,10,2\n"
    )
    (metrics / "metrics_full.csv").write_text("url,timestamp\nhttps://example.com,123\n")
    return data_dir


# ══════════════════════════════════════════════════════════════════════
# 1. TestPreRunCleanup
# ══════════════════════════════════════════════════════════════════════

class TestPreRunCleanup:
    """Verifica que cleanup_previous_run elimina tots els artefactes anteriors."""

    def _run_cleanup(self, data_dir: Path):
        import logging
        # Import inline to avoid circular deps at module level
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from aci_run import cleanup_previous_run
        log = logging.getLogger("test_cleanup")
        cleanup_previous_run(data_dir, log)

    def test_removes_assets_dir(self, populated_data_dir: Path):
        self._run_cleanup(populated_data_dir)
        assert not (populated_data_dir / "assets").exists()

    def test_removes_processed_dir(self, populated_data_dir: Path):
        self._run_cleanup(populated_data_dir)
        assert not (populated_data_dir / "processed").exists()

    def test_removes_reports_dir(self, populated_data_dir: Path):
        self._run_cleanup(populated_data_dir)
        assert not (populated_data_dir / "reports").exists()

    def test_removes_score_summary_csv(self, populated_data_dir: Path):
        self._run_cleanup(populated_data_dir)
        assert not (populated_data_dir / "metrics" / "score_summary.csv").exists()

    def test_removes_metrics_full_csv(self, populated_data_dir: Path):
        self._run_cleanup(populated_data_dir)
        assert not (populated_data_dir / "metrics" / "metrics_full.csv").exists()

    def test_noop_when_already_clean(self, data_dir: Path):
        """No ha de llençar excepció si ja no hi ha fitxers."""
        self._run_cleanup(data_dir)  # no error expected

    def test_metrics_dir_itself_preserved(self, populated_data_dir: Path):
        """El directori data/metrics/ roman (però buit de fitxers de run)."""
        self._run_cleanup(populated_data_dir)
        assert (populated_data_dir / "metrics").exists()


# ══════════════════════════════════════════════════════════════════════
# 2. TestProfileFiltering
# ══════════════════════════════════════════════════════════════════════

SAMPLE_MANIFEST = [
    {
        "id": "site_a_123",
        "url": "https://site-a.cat",
        "domain": "site-a.cat",
        "type": "educatiu",
        "aci": 3.0,
        "profile_scores": {
            "wcag_strict": 2.5,
            "readability_first": 3.8,
            "visual_first": 3.1,
        },
        "profile_reports": {
            "wcag_strict": "data/reports/site_a/report_wcag.html",
            "readability_first": "data/reports/site_a/report_read.html",
            "visual_first": "data/reports/site_a/report_vis.html",
        },
        "comparative_report": "data/reports/site_a/comparative.html",
    },
    {
        "id": "site_b_456",
        "url": "https://site-b.cat",
        "domain": "site-b.cat",
        "type": "institucional",
        "aci": 4.1,
        "profile_scores": {
            "wcag_strict": 4.2,
        },
        "profile_reports": {
            "wcag_strict": "data/reports/site_b/report_wcag.html",
        },
        "comparative_report": None,
    },
    {
        "id": "site_c_789",
        "url": "https://site-c.cat",
        "domain": "site-c.cat",
        "type": "cultural",
        "aci": 2.1,
        "profile_scores": {},
        "profile_reports": {},
        "comparative_report": None,
    },
]


class TestProfileFiltering:
    """Verifica la lògica de filtrat per perfil del manifest."""

    def _filter(self, manifest: list[dict], profile: str) -> list[dict]:
        """Replica la lògica d'applyFilters() de index.html en Python."""
        result = []
        for item in manifest:
            if profile == "comparative":
                if not item.get("comparative_report"):
                    continue
            elif profile:
                has_report = bool(item.get("profile_reports", {}).get(profile))
                has_score = item.get("profile_scores", {}).get(profile) is not None
                if not (has_report or has_score):
                    continue
            result.append(item)
        return result

    def _effective_aci(self, item: dict, profile: str) -> float:
        if profile and profile != "comparative":
            ps = item.get("profile_scores", {})
            if ps.get(profile) is not None:
                return ps[profile]
        return item["aci"]

    def test_no_filter_returns_all(self):
        assert len(self._filter(SAMPLE_MANIFEST, "")) == 3

    def test_wcag_filter_excludes_site_c(self):
        result = self._filter(SAMPLE_MANIFEST, "wcag_strict")
        domains = [r["domain"] for r in result]
        assert "site-c.cat" not in domains
        assert "site-a.cat" in domains
        assert "site-b.cat" in domains

    def test_readability_filter_returns_only_site_a(self):
        result = self._filter(SAMPLE_MANIFEST, "readability_first")
        assert len(result) == 1
        assert result[0]["domain"] == "site-a.cat"

    def test_comparative_filter_returns_only_site_a(self):
        result = self._filter(SAMPLE_MANIFEST, "comparative")
        assert len(result) == 1
        assert result[0]["domain"] == "site-a.cat"

    def test_wcag_aci_uses_profile_score(self):
        item = SAMPLE_MANIFEST[0]
        assert self._effective_aci(item, "wcag_strict") == 2.5

    def test_readability_aci_uses_profile_score(self):
        item = SAMPLE_MANIFEST[0]
        assert self._effective_aci(item, "readability_first") == 3.8

    def test_empty_profile_uses_global_aci(self):
        item = SAMPLE_MANIFEST[0]
        assert self._effective_aci(item, "") == 3.0

    def test_missing_profile_score_falls_back_to_global(self):
        item = SAMPLE_MANIFEST[2]  # profile_scores = {}
        assert self._effective_aci(item, "wcag_strict") == 2.1


# ══════════════════════════════════════════════════════════════════════
# 3. TestNoDuplicates
# ══════════════════════════════════════════════════════════════════════

class TestNoDuplicates:
    """Verifica que load_urls() elimina duplicats i que M6 no escriu files dobles."""

    def _load_urls_from_text(self, text: str, tmp_path: Path) -> list[str]:
        import logging
        import types
        import argparse

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from aci_run import load_urls

        url_file = tmp_path / "urls.txt"
        url_file.write_text(text, encoding="utf-8")
        args = argparse.Namespace(urls=None, url_file=str(url_file))
        return load_urls(args)

    def test_exact_duplicates_removed(self, tmp_path: Path):
        text = "https://example.com\nhttps://example.com\nhttps://other.com\n"
        urls = self._load_urls_from_text(text, tmp_path)
        assert len(urls) == 2

    def test_trailing_slash_treated_as_duplicate(self, tmp_path: Path):
        text = "https://example.com\nhttps://example.com/\n"
        urls = self._load_urls_from_text(text, tmp_path)
        assert len(urls) == 1

    def test_type_suffix_does_not_prevent_dedup(self, tmp_path: Path):
        text = "https://example.com; Educatiu\nhttps://example.com; Institucional\n"
        urls = self._load_urls_from_text(text, tmp_path)
        assert len(urls) == 1

    def test_unique_urls_preserved(self, tmp_path: Path):
        text = "https://a.com\nhttps://b.com\nhttps://c.com\n"
        urls = self._load_urls_from_text(text, tmp_path)
        assert len(urls) == 3

    def test_comments_ignored(self, tmp_path: Path):
        text = "# comentari\nhttps://example.com\n# altre\nhttps://other.com\n"
        urls = self._load_urls_from_text(text, tmp_path)
        assert len(urls) == 2

    def test_m6_csv_dedup_guard(self, data_dir: Path):
        """M6 no escriu la mateixa fila (url, ts, profile) dues vegades."""
        import importlib
        import aci_pipeline.m6_agregacio as m6_mod

        # Reset the module-level dedup set before test
        m6_mod._csv_written_keys.clear()

        metrics_dir = data_dir / "metrics"
        metrics_dir.mkdir(exist_ok=True)
        csv_path = metrics_dir / "score_summary.csv"

        fake_score = {
            "aci_score": 3.0,
            "aci_normalized": 0.6,
            "metrics_evaluated": 5,
            "metrics_na": 1,
            "normalized_metrics": {},
            "sub_scores": {},
            "weights": {},
            "total_weight": 1,
        }

        url = "https://dup-test.com"
        ts = 111222333

        # Patch compute_aci_score and file I/O to simulate two calls with same key
        with patch.object(m6_mod, "compute_aci_score", return_value=fake_score), \
             patch.object(m6_mod, "slug_from_url", return_value="dup_test_com"), \
             patch.object(m6_mod, "timestamp", return_value=ts):
            m4_stub = {"metrics": {}}
            m6_mod.run_m6(m4_stub, "wcag_strict", {}, {}, url, data_dir=data_dir,
                          slug="dup_test_com", ts=ts)
            m6_mod.run_m6(m4_stub, "wcag_strict", {}, {}, url, data_dir=data_dir,
                          slug="dup_test_com", ts=ts)

        # CSV must have exactly 1 data row (+ 1 header)
        rows = csv_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 2, f"Esperava 2 línies (cap+fila), tenia {len(rows)}"
