"""
M5 — Interfície IA generativa (stub + integració Claude).
Genera alt texts, descripcions i recomanacions via LLM.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

log = logging.getLogger("aci_pipeline.m5")

# Prompt optimitzat per generar alt text i descripcions
IA_PROMPT_TEMPLATE = """Ets un expert en accessibilitat web (WCAG 2.1/2.2) i descripció d'imatges.
Analitza l'element visual descrit i genera:
1. Un alt text curt (màx 125 caràcters) per a screen readers
2. Un alt text llarg (1-3 frases) per a imatges complexes
3. Una descripció estructurada per a documents

Retorna SEMPRE un JSON vàlid amb aquest format exacte:
{{
  "id_element": "{id_element}",
  "alt_short": "<text curt per screen reader>",
  "alt_long": "<descripció d'1-3 frases>",
  "long_description": "<descripció estructurada completa>",
  "recommendations": [
    {{"action": "<acció concreta>", "impact": "<baix|mig|alt>", "cost": "<baix|mig|alt>"}}
  ],
  "confidence": <float 0.0-1.0>,
  "cues": ["<pista visual 1>", "<pista visual 2>"]
}}

Element a analitzar:
ID: {id_element}
Tipus: {element_type}
Text OCR detectat: {ocr_text}
Context textual: {context_text}
Pistes visuals: {visual_cues}
"""


def _stub_response(element: dict[str, Any]) -> dict[str, Any]:
    """
    Retorna una resposta stub quan no hi ha API key configurada.
    Útil per provar el pipeline sense accés a l'API.
    """
    elem_id = element.get("id_element", "unknown")
    elem_type = element.get("type", "image")
    ocr_text = element.get("ocr_text", "")
    context = element.get("context_text", "")[:100]

    alt_short = f"[STUB] {elem_type.capitalize()}"
    if ocr_text:
        alt_short = f"[STUB] {ocr_text[:80]}"
    elif context:
        alt_short = f"[STUB] Imatge relacionada amb: {context[:60]}"

    return {
        "id_element": elem_id,
        "alt_short": alt_short,
        "alt_long": f"[STUB - requereix revisió humana] Element visual de tipus {elem_type}. {context}",
        "long_description": f"[STUB] Descripció generada automàticament pendent de revisió. Context: {context}",
        "recommendations": [
            {
                "action": "Revisar i completar el text alternatiu generat",
                "impact": "alt",
                "cost": "baix",
            }
        ],
        "confidence": 0.0,
        "cues": [],
        "generated_by": "stub",
        "needs_human_review": True,
    }


def generate_alt_text(element: dict[str, Any]) -> dict[str, Any]:
    """
    Genera alt text i descripcions per a un element visual.
    Usa Claude si ANTHROPIC_API_KEY està configurada; sinó usa el stub.

    Entrada esperada:
    {
        "id_element": "img_123",
        "type": "svg",
        "ocr_text": "...",
        "context_text": "...",
        "visual_cues": ["bar chart", "legend", "colors: red, blue"]
    }

    Sortida:
    {
        "id_element": "img_123",
        "alt_short": "Gràfic de barres comparant X i Y",
        "alt_long": "...",
        "long_description": "...",
        "recommendations": [...],
        "confidence": 0.87,
        "cues": ["legend", "axis", "values"]
    }
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        log.debug("ANTHROPIC_API_KEY no configurada; usant stub per element %s", element.get("id_element"))
        return _stub_response(element)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = IA_PROMPT_TEMPLATE.format(
            id_element=element.get("id_element", ""),
            element_type=element.get("type", "image"),
            ocr_text=element.get("ocr_text", "cap text OCR detectat"),
            context_text=element.get("context_text", "cap context disponible"),
            visual_cues=", ".join(element.get("visual_cues", [])),
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text.strip()
        # Extreu el JSON de la resposta
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            result["generated_by"] = "claude"
            result["needs_human_review"] = result.get("confidence", 0) < 0.7
            return result
        else:
            log.warning("Resposta Claude sense JSON vàlid per %s", element.get("id_element"))
            return _stub_response(element)

    except Exception as exc:
        log.error("Error cridant Claude per element %s: %s", element.get("id_element"), exc)
        return _stub_response(element)


def process_page_visuals(page_structure: dict[str, Any]) -> list[dict[str, Any]]:
    """Processa totes les imatges que necessiten IA d'una pàgina."""
    images = page_structure.get("images", [])
    results: list[dict[str, Any]] = []

    for i, img in enumerate(images):
        if not img.get("needs_ai", False):
            continue

        element = {
            "id_element": f"img_{i}",
            "type": img.get("type", "img"),
            "ocr_text": "",
            "context_text": img.get("alt", "") or "",
            "visual_cues": [],
        }
        result = generate_alt_text(element)
        results.append(result)

    log.info("M5: processats %d elements visuals", len(results))
    return results
