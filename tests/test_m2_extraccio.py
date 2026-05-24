"""Tests unitaris per a m2_extraccio."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aci_pipeline.m2_extraccio import extract_structure, _is_meaningful_alt


# ─── Fixtures HTML ───────────────────────────────────────────────────────────

HTML_HEADINGS = """
<html><body>
  <h1>Titol principal</h1>
  <h2>Subtitol</h2>
  <h3>Subsubtitol</h3>
</body></html>
"""

HTML_IMAGES = """
<html><body>
  <img src="a.png" alt="Grafic de barres de vendes anuals">
  <img src="b.png" alt="image">
  <img src="c.png">
  <img src="d.png" alt="">
  <img src="e.png" alt="Logo empresa">
</body></html>
"""

HTML_INTERACTIVE = """
<html><body>
  <button aria-label="Tancar finestra">X</button>
  <button>Acceptar</button>
  <a href="/page">Anar a la pagina</a>
  <a href="/x"></a>
  <input type="text" id="nom" placeholder="Nom">
  <label for="nom">Nom complert</label>
  <input type="email" placeholder="Email">
</body></html>
"""

HTML_LANDMARKS = """
<html><body>
  <header><h1>Cap</h1></header>
  <nav><a href="/">Inici</a></nav>
  <main><p>Contingut principal.</p></main>
  <footer><p>Peu de pagina</p></footer>
  <aside role="complementary"><p>Lateral</p></aside>
</body></html>
"""

HTML_ARIA = """
<html><body>
  <div role="button" tabindex="0">Click</div>
  <span role="alert">Error!</span>
  <div role="invalidrole">Bad</div>
  <nav role="navigation">Menu</nav>
</body></html>
"""

HTML_FORMS = """
<html><body>
  <form action="/submit" method="post">
    <label for="f1">Nom</label>
    <input type="text" id="f1">
    <input type="email" id="f2" aria-label="Correu electronic">
    <input type="text" id="f3">
    <select id="f4"><option>Opcio</option></select>
    <input type="submit" value="Enviar">
  </form>
</body></html>
"""

HTML_TABLES = """
<html><body>
  <table>
    <caption>Vendes per mes</caption>
    <tr><th>Mes</th><th>Vendes</th></tr>
    <tr><td>Gener</td><td>1000</td></tr>
  </table>
  <table>
    <tr><td>Sense capçaleres</td><td>ni caption</td></tr>
  </table>
</body></html>
"""


# ─── Tests _is_meaningful_alt ─────────────────────────────────────────────────

class TestIsMeaningfulAlt:
    def test_none_returns_false(self):
        assert _is_meaningful_alt(None) is False

    def test_empty_string_returns_false(self):
        assert _is_meaningful_alt("") is False

    def test_whitespace_returns_false(self):
        assert _is_meaningful_alt("   ") is False

    def test_generic_image_returns_false(self):
        assert _is_meaningful_alt("image") is False
        assert _is_meaningful_alt("IMAGE") is False
        assert _is_meaningful_alt("img") is False
        assert _is_meaningful_alt("photo") is False
        assert _is_meaningful_alt("foto") is False
        assert _is_meaningful_alt("logo") is False
        assert _is_meaningful_alt("icon") is False
        assert _is_meaningful_alt("banner") is False

    def test_numeric_returns_false(self):
        assert _is_meaningful_alt("123") is False

    def test_too_short_returns_false(self):
        assert _is_meaningful_alt("ab") is False

    def test_meaningful_text_returns_true(self):
        assert _is_meaningful_alt("Grafic de barres de vendes anuals") is True
        assert _is_meaningful_alt("Fotografia del director general") is True
        assert _is_meaningful_alt("Mapa de localitzacio") is True

    def test_minimum_length_boundary(self):
        assert _is_meaningful_alt("abc") is True
        assert _is_meaningful_alt("ab") is False


# ─── Tests extract_structure ─────────────────────────────────────────────────

class TestExtractHeadings:
    def test_extracts_all_heading_levels(self):
        result = extract_structure(HTML_HEADINGS)
        headings = result["headings"]
        assert len(headings) == 3
        assert headings[0]["level"] == 1
        assert headings[1]["level"] == 2
        assert headings[2]["level"] == 3

    def test_heading_text_extracted(self):
        result = extract_structure(HTML_HEADINGS)
        assert result["headings"][0]["text"] == "Titol principal"

    def test_stats_num_headings(self):
        result = extract_structure(HTML_HEADINGS)
        assert result["stats"]["num_headings"] == 3

    def test_empty_page_no_headings(self):
        result = extract_structure("<html><body></body></html>")
        assert result["headings"] == []
        assert result["stats"]["num_headings"] == 0


class TestExtractImages:
    def setup_method(self):
        self.result = extract_structure(HTML_IMAGES)
        self.images = self.result["images"]

    def test_total_images_count(self):
        assert len(self.images) == 5

    def test_meaningful_alt_detected(self):
        # Primera imatge: alt significatiu
        img_a = next(i for i in self.images if i["src"] == "a.png")
        assert img_a["meaningful_alt"] is True

    def test_generic_alt_not_meaningful(self):
        img_b = next(i for i in self.images if i["src"] == "b.png")
        assert img_b["meaningful_alt"] is False

    def test_missing_alt_not_meaningful(self):
        img_c = next(i for i in self.images if i["src"] == "c.png")
        assert img_c["meaningful_alt"] is False
        assert img_c["alt"] is None

    def test_empty_alt_not_meaningful(self):
        img_d = next(i for i in self.images if i["src"] == "d.png")
        assert img_d["meaningful_alt"] is False
        assert img_d["alt"] == ""

    def test_stats_images_with_meaningful_alt(self):
        assert self.result["stats"]["images_with_meaningful_alt"] == 1

    def test_stats_images_needing_ai(self):
        # Imatges amb alt no significatiu però alt present (no buit, no None)
        # "image" i "Logo empresa" → needs_ai = True
        assert self.result["stats"]["images_needing_ai"] >= 1


class TestExtractInteractiveElements:
    def setup_method(self):
        self.result = extract_structure(HTML_INTERACTIVE)
        self.elements = self.result["interactive_elements"]

    def test_detects_buttons(self):
        buttons = [e for e in self.elements if e["tag"] == "button"]
        assert len(buttons) == 2

    def test_button_with_aria_label_has_name(self):
        btn = next(e for e in self.elements if e.get("aria_label") == "Tancar finestra")
        assert btn["has_accessible_name"] is True

    def test_button_with_text_has_name(self):
        btn = next(e for e in self.elements if e["tag"] == "button" and e["text"] == "Acceptar")
        assert btn["has_accessible_name"] is True

    def test_link_with_text_has_name(self):
        link = next(e for e in self.elements if e["tag"] == "a" and "pagina" in e["text"])
        assert link["has_accessible_name"] is True

    def test_link_without_text_no_name(self):
        link = next(e for e in self.elements if e["tag"] == "a" and not e["text"])
        assert link["has_accessible_name"] is False

    def test_input_with_label_has_name(self):
        # L'input #nom te label associada
        inp = next(e for e in self.elements if e["tag"] == "input" and e.get("id") == "nom")
        assert inp["has_accessible_name"] is True

    def test_stats_interactive_with_name(self):
        assert self.result["stats"]["interactive_with_name"] >= 4


class TestExtractLandmarks:
    def setup_method(self):
        self.result = extract_structure(HTML_LANDMARKS)
        self.landmarks = self.result["landmarks"]

    def test_detects_main(self):
        assert "main" in self.landmarks

    def test_detects_nav(self):
        assert "nav" in self.landmarks

    def test_detects_header(self):
        assert "header" in self.landmarks

    def test_detects_footer(self):
        assert "footer" in self.landmarks

    def test_detects_aside(self):
        assert "aside" in self.landmarks

    def test_detects_role_complementary(self):
        assert "role:complementary" in self.landmarks

    def test_no_landmarks_empty_page(self):
        result = extract_structure("<html><body><p>Text</p></body></html>")
        assert result["landmarks"] == {}


class TestExtractAriaElements:
    def setup_method(self):
        self.result = extract_structure(HTML_ARIA)
        self.aria = self.result["aria_elements"]

    def test_detects_aria_elements(self):
        assert len(self.aria) >= 3

    def test_valid_roles_marked(self):
        valid_roles = [a for a in self.aria if a["valid"]]
        assert len(valid_roles) >= 3  # button, alert, navigation

    def test_invalid_role_detected(self):
        invalid = [a for a in self.aria if not a["valid"]]
        assert len(invalid) >= 1
        assert any(a["role"] == "invalidrole" for a in invalid)

    def test_stats_aria_valid(self):
        total = self.result["stats"]["num_aria_elements"]
        valid = self.result["stats"]["aria_valid"]
        assert valid <= total
        assert valid >= 3


class TestExtractForms:
    def setup_method(self):
        self.result = extract_structure(HTML_FORMS)
        self.forms = self.result["forms"]

    def test_detects_one_form(self):
        assert len(self.forms) == 1

    def test_form_action_extracted(self):
        assert self.forms[0]["action"] == "/submit"

    def test_form_method_extracted(self):
        assert self.forms[0]["method"] == "post"

    def test_labeled_inputs_counted(self):
        # f1 te label, f2 te aria-label → 2 etiquetats de 5 inputs (incl. submit)
        assert self.forms[0]["labeled_inputs"] >= 2

    def test_total_inputs_counted(self):
        assert self.forms[0]["total_inputs"] >= 4


class TestExtractTables:
    def setup_method(self):
        self.result = extract_structure(HTML_TABLES)
        self.tables = self.result["tables"]

    def test_detects_two_tables(self):
        assert len(self.tables) == 2

    def test_first_table_has_caption(self):
        assert self.tables[0]["caption"] == "Vendes per mes"

    def test_first_table_has_headers(self):
        assert self.tables[0]["has_headers"] is True

    def test_second_table_no_caption(self):
        assert self.tables[1]["caption"] is None

    def test_second_table_no_headers(self):
        assert self.tables[1]["has_headers"] is False


class TestPlainText:
    def test_plain_text_extracted(self):
        html = "<html><body><p>Hola mon</p><script>var x=1;</script></body></html>"
        result = extract_structure(html)
        assert "Hola mon" in result["plain_text"]
        assert "var x=1" not in result["plain_text"]

    def test_text_length_computed(self):
        html = "<html><body><p>Paraules de text per a la prova</p></body></html>"
        result = extract_structure(html)
        assert result["text_length"] > 0

    def test_metadata_populated(self):
        result = extract_structure("<html><body></body></html>", url="https://example.com")
        assert result["meta"]["url"] == "https://example.com"
        assert result["meta"]["mode"] == "bs4"
