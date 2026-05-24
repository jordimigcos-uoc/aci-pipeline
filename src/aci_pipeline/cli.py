#!/usr/bin/env python3
"""
cli.py — Entrypoint principal del pipeline ACI v0.1.0.

Ús bàsic:
    python -m aci_pipeline.cli --url-file data/inputs/urls.sample.txt
    python -m aci_pipeline.cli --urls https://example.com --profile wcag_strict
    python -m aci_pipeline.cli --url-file urls.txt --all-profiles --output results/

Opcions:
    --urls URL [URL ...]   URLs a analitzar (separades per espais)
    --url-file FILE        Fitxer de text amb una URL per línia
    --profile PROFILE      wcag_strict | readability_first | visual_first
    --all-profiles         Executa els 3 perfils i genera informe comparatiu
    --output DIR           Directori de sortida (per defecte: results/)
    --config FILE          Fitxer YAML de configuració (per defecte: configs/scoring_config.yaml)
    --log-level LEVEL      DEBUG | INFO | WARNING | ERROR (per defecte: INFO)
    --log-dir DIR          Directori de logs (per defecte: logs/)
    --no-browser           Usa fallback HTTP en lloc de Playwright
    --zip                  Genera un paquet ZIP per cada URL
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# ── Imports relatius dins del paquet aci_pipeline ─────────────────────────────
from .utils import setup_logging, timestamp
from .m1_ingesta import ingest_url
from .m2_extraccio import run_m2
from .m3_segmentacio import run_m3
from .m4_analisi import run_m4
from .m5_ia import process_page_visuals
from .m6_agregacio import run_m6
from .m7_perfil import (
    load_scoring_config,
    get_profile_weights,
    get_norm_config,
    run_m7,
)
from .m8_reporting import run_m8, generate_comparative_report

ALL_PROFILES: list[str] = ["wcag_strict", "readability_first", "visual_first"]

log = logging.getLogger("aci_pipeline.cli")


# ── Parsing d'arguments ────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parseja i retorna els arguments de la línia de comandes."""
    parser = argparse.ArgumentParser(
        prog="python -m aci_pipeline.cli",
        description=(
            "ACI Pipeline v0.1.0 — Avaluació automatitzada d'accessibilitat web.\n"
            "Genera informes HTML, CSV i JSON basats en WCAG 2.1 AA / EN 301 549."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Grup mutuament exclusiu: URLs inline o fitxer
    url_group = parser.add_mutually_exclusive_group(required=True)
    url_group.add_argument(
        "--urls", nargs="+", metavar="URL",
        help="Una o més URLs a analitzar",
    )
    url_group.add_argument(
        "--url-file", metavar="FILE",
        help="Fitxer de text: una URL per línia, # per a comentaris, ; per al tipus",
    )

    # Grup mutuament exclusiu: un perfil o tots
    profile_group = parser.add_mutually_exclusive_group()
    profile_group.add_argument(
        "--profile", default="wcag_strict",
        choices=ALL_PROFILES,
        help="Perfil de puntuació (per defecte: wcag_strict)",
    )
    profile_group.add_argument(
        "--all-profiles", action="store_true",
        help="Executa tots els perfils per cada URL",
    )

    parser.add_argument(
        "--output", default="results", metavar="DIR",
        help="Directori de sortida (per defecte: results/)",
    )
    parser.add_argument(
        "--config", default="configs/scoring_config.yaml", metavar="FILE",
        help="Fitxer YAML de pesos i normalitzacions",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Nivell de log (per defecte: INFO o $LOG_LEVEL)",
    )
    parser.add_argument(
        "--log-dir", default="logs", metavar="DIR",
        help="Directori on es desen els fitxers de log",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Desactiva Playwright i usa fallback HTTP (útil en CI sense display)",
    )
    parser.add_argument(
        "--zip", action="store_true",
        help="Genera un paquet ZIP per cada URL analitzada",
    )

    return parser.parse_args(argv)


# ── Validació ──────────────────────────────────────────────────────────────────

def _validate(args: argparse.Namespace) -> None:
    """
    Valida els arguments crítics i atura amb missatge clar si hi ha errors.
    Usa sys.exit(2) (codi UNIX per ús incorrecte de comanda).
    """
    if args.url_file:
        p = Path(args.url_file)
        if not p.exists():
            sys.exit(
                f"\n[ERROR] Fitxer d'URLs no trobat: {p.resolve()}\n"
                f"  Solució: crea el fitxer o usa --urls URL1 URL2 ...\n"
                f"  Exemple: data/inputs/urls.sample.txt"
            )
        if not p.is_file():
            sys.exit(f"\n[ERROR] La ruta no és un fitxer vàlid: {p.resolve()}")
        try:
            p.read_text(encoding="utf-8")
        except PermissionError:
            sys.exit(
                f"\n[ERROR] Sense permisos de lectura: {p.resolve()}\n"
                f"  Solució (Unix): chmod +r {p}"
            )

    cfg = Path(args.config)
    if not cfg.exists():
        sys.exit(
            f"\n[ERROR] Fitxer de configuració no trobat: {cfg.resolve()}\n"
            f"  Ruta per defecte: configs/scoring_config.yaml\n"
            f"  Usa --config per especificar una ruta diferent."
        )


# ── Logging a fitxer ───────────────────────────────────────────────────────────

def _add_file_handler(log_dir: str, run_id: int) -> Path:
    """Afegeix un FileHandler al logger arrel; retorna la ruta del fitxer de log."""
    log_path = Path(log_dir) / f"pipeline_{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(fh)
    return log_path


# ── Càrrega d'URLs ─────────────────────────────────────────────────────────────

def _load_urls(args: argparse.Namespace) -> list[str]:
    """
    Llegeix URLs de la línia de comandes o d'un fitxer.
    Elimina línies buides, comentaris (#) i duplicats.
    Retorna la llista neta (pot contenir '; categoria' opcionalment).
    """
    if args.urls:
        raw: list[str] = list(args.urls)
    else:
        raw = [
            line.strip()
            for line in Path(args.url_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    seen: dict[str, str] = {}
    for line in raw:
        key = line.split(";")[0].strip().rstrip("/").lower()
        if key in seen:
            log.warning("URL duplicada ignorada: %s", line.split(";")[0].strip())
        else:
            seen[key] = line

    urls = list(seen.values())
    if not urls:
        sys.exit(
            "\n[ERROR] La llista d'URLs és buida.\n"
            "  Comprova que el fitxer té línies vàlides (no comentaris amb #)."
        )
    n_total = len(raw)
    n_unique = len(urls)
    if n_total != n_unique:
        print(f"  [dedup] {n_total - n_unique} URL(s) duplicada(es) eliminada(es) → {n_unique} úniques")

    log.info(
        "URLs carregades (%d): %s",
        len(urls),
        [u.split(";")[0].strip() for u in urls],
    )
    return urls


# ── Execució del pipeline per a una URL i un perfil ───────────────────────────

def _run_one(
    url: str,
    profile: str,
    weights: dict,
    norm_cfg: dict,
    data_dir: Path,
    args: argparse.Namespace,
    *,
    m1: dict | None = None,
    m2: dict | None = None,
    m3: dict | None = None,
    m4: dict | None = None,
) -> dict:
    """
    Executa M1–M8 per a una URL i un perfil de puntuació.
    Si m1/m2/m3/m4 ja estan calculats (mode --all-profiles), els reutilitza.
    """
    raw_url = url.split(";")[0].strip()
    log.info("── Pipeline: %s [perfil=%s] ──", raw_url, profile)

    # ─ M1: Ingesta i renderització ─
    if m1 is None:
        m1 = ingest_url(url, data_dir=data_dir)

    # ─ M2: Extracció d'estructura HTML ─
    if m2 is None:
        m2 = run_m2(m1["html"], url, data_dir=data_dir, slug=m1["slug"], ts=m1["timestamp"])

    # ─ M3: Segmentació de contingut ─
    if m3 is None:
        m3 = run_m3(m2, url, data_dir=data_dir, slug=m1["slug"], ts=m1["timestamp"])

    # ─ M4: Anàlisi de mètriques ─
    if m4 is None:
        m4 = run_m4(
            m2, m3, m1["axe_result"], m1["perf"],
            url, data_dir=data_dir, slug=m1["slug"], ts=m1["timestamp"],
        )
        # ─ M5: Processament per IA (opcional, no bloqueja el flux) ─
        try:
            ia_out = process_page_visuals(m2)
            if ia_out:
                log.info("M5-IA: %d element(s) processats", len(ia_out))
        except Exception as exc:  # noqa: BLE001
            log.warning("M5-IA: omès per error (%s)", exc)

    # ─ M6: Agregació i càlcul ACI ─
    m6 = run_m6(
        m4, profile, weights, norm_cfg,
        url, data_dir=data_dir, slug=m1["slug"], ts=m1["timestamp"],
    )

    # ─ M7: Perfil de prioritats ─
    m7 = run_m7(m6, m4, url, data_dir=data_dir, slug=m1["slug"], ts=m1["timestamp"])

    # ─ M8: Generació d'informe HTML ─
    m8 = run_m8(
        url, m1, m4, m6, m7,
        data_dir=data_dir, slug=m1["slug"], ts=m1["timestamp"],
        create_zip=args.zip,
    )

    aci = m6.get("aci_score", 0.0)
    log.info("ACI=%.3f/5.0 [%s] → %s", aci, profile, m8.get("html_report_path", ""))
    print(f"  ✓  {raw_url:<60}  ACI={aci:.3f}  [{profile}]")

    return {
        "url": url,
        "profile": profile,
        "aci_score": aci,
        "m6": m6,
        "m7": m7,
        "_m1": m1,
        "_m2": m2,
        "_m3": m3,
        "_m4": m4,
    }


# ── Entrypoint ─────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """
    Entrypoint del pipeline ACI.
    Retorna 0 si tot ha anat bé, 1 si hi ha hagut errors parcials.
    """
    args = parse_args(argv)

    # Configura logging (consola)
    setup_logging(args.log_level)
    _validate(args)

    # Configura logging (fitxer)
    run_id = timestamp()
    log_path = _add_file_handler(args.log_dir, run_id)

    # Prepara directori de sortida
    data_dir = Path(args.output)
    data_dir.mkdir(parents=True, exist_ok=True)

    log.info("ACI Pipeline v0.1.0 · run_id=%d · output=%s", run_id, data_dir)
    print(f"\nACI Pipeline v0.1.0")
    print(f"  Sortida  : {data_dir.resolve()}")
    print(f"  Log      : {log_path.resolve()}\n")

    # Carrega configuració de puntuació
    scoring_cfg = load_scoring_config(Path(args.config))
    norm_cfg = get_norm_config(scoring_cfg)

    urls = _load_urls(args)
    profiles = ALL_PROFILES if args.all_profiles else [args.profile]

    all_results: list[dict] = []
    errors: list[str] = []

    for url in urls:
        raw_url = url.split(";")[0].strip()
        try:
            if args.all_profiles:
                # Reutilitza M1–M4 per als 3 perfils (evita re-descàrrega)
                m1 = m2 = m3 = m4 = None
                for profile in profiles:
                    weights = get_profile_weights(scoring_cfg, profile)
                    res = _run_one(
                        url, profile, weights, norm_cfg, data_dir, args,
                        m1=m1, m2=m2, m3=m3, m4=m4,
                    )
                    m1, m2, m3, m4 = res["_m1"], res["_m2"], res["_m3"], res["_m4"]
                    all_results.append(res)
            else:
                weights = get_profile_weights(scoring_cfg, args.profile)
                res = _run_one(url, args.profile, weights, norm_cfg, data_dir, args)
                all_results.append(res)

        except Exception as exc:  # noqa: BLE001
            log.error("Error a %s: %s", raw_url, exc, exc_info=True)
            errors.append(f"{raw_url}: {exc}")
            print(f"  ✗  {raw_url:<60}  ERROR: {exc}")

    # ── Genera informe comparatiu si s'han executat tots els perfils ──
    if args.all_profiles and all_results:
        try:
            generate_comparative_report(all_results, data_dir=data_dir)
            log.info("Informe comparatiu generat a %s", data_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("No s'ha pogut generar l'informe comparatiu: %s", exc)

    # ── Resum final ────────────────────────────────────────────────────────────
    sep = "─" * 65
    print(f"\n{sep}")
    print(f"  Processades : {len(urls)} URL(s)  ·  {len(profiles)} perfil(s)")
    print(f"  Correctes   : {len(all_results)}")
    if errors:
        print(f"  Errors      : {len(errors)}")
        for e in errors:
            print(f"                {e}")
    print(f"  Sortida     : {data_dir.resolve()}")
    print(f"  Log         : {log_path.resolve()}")
    print(f"{sep}\n")

    if errors:
        log.warning("Finalitzat amb %d error(s): %s", len(errors), errors)
        return 1
    log.info("Pipeline completat sense errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
