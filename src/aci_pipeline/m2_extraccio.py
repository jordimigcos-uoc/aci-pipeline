"""
M2 — Extracció estructural i semàntica.
Parseja el HTML amb BeautifulSoup i genera page_structure.json.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from .utils import base_metadata, slug_from_url, timestamp

log = logging.getLogger("aci_pipeline.m2")

LANDMARK_TAGS = {"main", "nav", "header", "footer", "aside", "section", "article", "form"}
LANDMARK_ROLES = {"main", "navigation", "banner", "contentinfo", "complementary", "search", "form", "region"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "details", "summary"}


def _is_meaningful_alt(alt: str | None) -> bool:
    """Comprova si un text alt és significatiu (no buit ni genèric)."""
    if alt is None:
        return False
    alt = alt.strip()
    if not alt:
        return False
    generic = re.compile(r"^(image|img|photo|foto|picture|icon|logo|banner|\d+)$", re.IGNORECASE)
    if generic.match(alt):
        return False
    return len(alt) >= 3


def extract_structure(html: str, url: str = "") -> dict[str, Any]:
    """
    Extreu l'estructura semàntica del HTML.
    Retorna un dict normalitzat amb text_blocks, images, landmarks, etc.
    """
    soup = BeautifulSoup(html, "lxml")

    # Elimina scripts i styles del text pla
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # --- Headings ---
    headings: list[dict[str, Any]] = []
    for tag in soup.find_all(HEADING_TAGS):
        level = int(tag.name[1])
        text = tag.get_text(separator=" ", strip=True)
        headings.append({
            "level": level,
            "text": text,
            "id": tag.get("id"),
        })

    # --- Imatges ---
    images: list[dict[str, Any]] = []
    for img in soup.find_all(["img", "svg"]):
        if img.name == "img":
            alt = img.get("alt")
            images.append({
                "type": "img",
                "src": img.get("src", ""),
                "alt": alt,
                "role": img.get("role"),
                "aria_label": img.get("aria-label"),
                "meaningful_alt": _is_meaningful_alt(alt),
                "needs_ai": not _is_meaningful_alt(alt) and alt != "",
            })
        elif img.name == "svg":
            title = img.find("title")
            desc = img.find("desc")
            has_desc = bool(title or desc or img.get("aria-label"))
            images.append({
                "type": "svg",
                "alt": title.get_text(strip=True) if title else None,
                "aria_label": img.get("aria-label"),
                "role": img.get("role"),
                "meaningful_alt": has_desc,
                "needs_ai": not has_desc,
            })

    # --- Landmarks ---
    landmarks: dict[str, int] = {}
    for tag in soup.find_all(True):
        name = tag.name.lower() if isinstance(tag, Tag) else ""
        role = tag.get("role", "").lower()
        if name in LANDMARK_TAGS:
            landmarks[name] = landmarks.get(name, 0) + 1
        if role in LANDMARK_ROLES:
            landmarks[f"role:{role}"] = landmarks.get(f"role:{role}", 0) + 1

    # --- Elements interactius ---
    interactive_elements: list[dict[str, Any]] = []
    for tag in soup.find_all(INTERACTIVE_TAGS):
        name = tag.name.lower()
        elem = {
            "tag": name,
            "id": tag.get("id"),
            "role": tag.get("role"),
            "aria_label": tag.get("aria-label"),
            "aria_labelledby": tag.get("aria-labelledby"),
            "title": tag.get("title"),
            "text": tag.get_text(strip=True)[:100],
        }
        # Accessible name heurística
        has_name = bool(
            elem["aria_label"] or elem["aria_labelledby"] or
            elem["title"] or (elem["text"] and len(elem["text"]) > 0)
        )
        if name == "input":
            input_id = tag.get("id")
            label = soup.find("label", attrs={"for": input_id}) if input_id else None
            has_name = has_name or bool(label) or bool(tag.get("placeholder"))
        elem["has_accessible_name"] = has_name
        interactive_elements.append(elem)

    # --- Taules ---
    tables: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        caption = table.find("caption")
        has_headers = bool(table.find("th"))
        tables.append({
            "caption": caption.get_text(strip=True) if caption else None,
            "has_headers": has_headers,
            "rows": len(table.find_all("tr")),
        })

    # --- Formularis ---
    forms: list[dict[str, Any]] = []
    for form in soup.find_all("form"):
        inputs = form.find_all(["input", "select", "textarea"])
        labeled_inputs = 0
        for inp in inputs:
            inp_id = inp.get("id")
            label = soup.find("label", attrs={"for": inp_id}) if inp_id else None
            if label or inp.get("aria-label") or inp.get("aria-labelledby"):
                labeled_inputs += 1
        forms.append({
            "action": form.get("action", ""),
            "method": form.get("method", "get"),
            "total_inputs": len(inputs),
            "labeled_inputs": labeled_inputs,
        })

    # --- Blocs de text ---
    text_blocks: list[dict[str, Any]] = []
    for tag in soup.find_all(["p", "li", "td", "dd", "blockquote", "figcaption"]):
        text = tag.get_text(separator=" ", strip=True)
        if len(text) > 20:
            text_blocks.append({
                "type": tag.name,
                "text": text[:500],
                "char_count": len(text),
            })

    # --- Text pla agregat ---
    plain_text = soup.get_text(separator=" ", strip=True)
    plain_text = re.sub(r"\s+", " ", plain_text)

    # --- ARIA elements ---
    aria_elements: list[dict[str, Any]] = []
    for tag in soup.find_all(True):
        role = tag.get("role")
        if role:
            valid_aria_roles = {
                "alert", "alertdialog", "application", "article", "banner", "button", "cell",
                "checkbox", "columnheader", "combobox", "complementary", "contentinfo",
                "definition", "dialog", "directory", "document", "feed", "figure", "form",
                "grid", "gridcell", "group", "heading", "img", "link", "list", "listbox",
                "listitem", "log", "main", "marquee", "math", "menu", "menubar", "menuitem",
                "menuitemcheckbox", "menuitemradio", "navigation", "none", "note", "option",
                "presentation", "progressbar", "radio", "radiogroup", "region", "row",
                "rowgroup", "rowheader", "scrollbar", "search", "searchbox", "separator",
                "slider", "spinbutton", "status", "switch", "tab", "table", "tablist",
                "tabpanel", "term", "textbox", "timer", "toolbar", "tooltip", "tree",
                "treegrid", "treeitem",
            }
            aria_elements.append({
                "tag": tag.name,
                "role": role,
                "valid": role.lower() in valid_aria_roles,
            })

    # Metadades
    meta = base_metadata(url)
    meta["mode"] = "bs4"
    meta["lang"] = soup.html.get("lang") if soup.html else None

    result = {
        "meta": meta,
        "plain_text": plain_text[:10000],
        "text_length": len(plain_text),
        "headings": headings,
        "images": images,
        "landmarks": landmarks,
        "interactive_elements": interactive_elements,
        "tables": tables,
        "forms": forms,
        "text_blocks": text_blocks[:100],
        "aria_elements": aria_elements,
        "stats": {
            "num_headings": len(headings),
            "num_images": len(images),
            "images_with_meaningful_alt": sum(1 for i in images if i["meaningful_alt"]),
            "images_needing_ai": sum(1 for i in images if i["needs_ai"]),
            "num_interactive": len(interactive_elements),
            "interactive_with_name": sum(1 for e in interactive_elements if e["has_accessible_name"]),
            "num_tables": len(tables),
            "num_forms": len(forms),
            "num_aria_elements": len(aria_elements),
            "aria_valid": sum(1 for a in aria_elements if a["valid"]),
        },
    }
    return result


def run_m2(
    html: str,
    url: str,
    data_dir: Path = Path("data"),
    slug: str | None = None,
    ts: int | None = None,
) -> dict[str, Any]:
    """Executa M2 i desa page_structure.json."""
    slug = slug or slug_from_url(url)
    ts = ts or timestamp()
    structure = extract_structure(html, url)

    out_dir = data_dir / "processed" / "structure"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}_{ts}.json"
    out_path.write_text(json.dumps(structure, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("M2 completat per %s → %s", url, out_path)
    return structure
