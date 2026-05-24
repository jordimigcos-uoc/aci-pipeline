#!/usr/bin/env bash
# =============================================================================
# run_local.sh — Configura i executa el pipeline ACI en local (Unix / macOS)
#
# Ús:
#   ./scripts/run_local.sh                        # paràmetres per defecte
#   URL_FILE=data/inputs/urls.txt ./scripts/run_local.sh
#   PROFILE=readability_first ./scripts/run_local.sh
#
# Variables d'entorn configurables:
#   URL_FILE   (per defecte: data/inputs/urls.sample.txt)
#   PROFILE    (per defecte: wcag_strict)
#   OUTPUT     (per defecte: results/local)
# =============================================================================
set -euo pipefail

VENV_DIR="${VENV_DIR:-.venv}"
URL_FILE="${URL_FILE:-data/inputs/urls.sample.txt}"
PROFILE="${PROFILE:-wcag_strict}"
OUTPUT="${OUTPUT:-results/local}"

# Ens situem sempre a l'arrel del projecte
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  ACI Pipeline v0.1.0 — Execució local                          ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo "  URL file : $URL_FILE"
echo "  Profile  : $PROFILE"
echo "  Output   : $OUTPUT"
echo ""

# ── Pas 1: Crea entorn virtual ─────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/5] Creant entorn virtual a $VENV_DIR/ ..."
    python3 -m venv "$VENV_DIR"
else
    echo "[1/5] Entorn virtual existent: $VENV_DIR/"
fi

# ── Pas 2: Activa l'entorn virtual ────────────────────────────────────────
echo "[2/5] Activant entorn virtual..."
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── Pas 3: Instal·la dependències ─────────────────────────────────────────
echo "[3/5] Instal·lant dependències Python..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ── Pas 4: Instal·la navegadors Playwright ────────────────────────────────
echo "[4/5] Instal·lant navegador Chromium (Playwright)..."
playwright install chromium --with-deps

# ── Pas 5: Executa el pipeline ────────────────────────────────────────────
echo "[5/5] Executant pipeline..."
echo ""

# Carrega variables d'entorn si existeix .env
if [ -f ".env" ]; then
    echo "  → Carregant .env ..."
    # shellcheck disable=SC2046
    export $(grep -v '^#' .env | xargs)
fi

python -m aci_pipeline.cli \
    --url-file "$URL_FILE" \
    --profile  "$PROFILE" \
    --output   "$OUTPUT" \
    --log-level INFO

# ── Resum ─────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  Execució completada!                                           ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo "  Resultats  : $(realpath "$OUTPUT" 2>/dev/null || echo "$OUTPUT")"
echo "  Logs       : $(realpath logs/ 2>/dev/null || echo "logs/")"
echo ""
echo "  Per obrir l'informe (exemple):"
echo "    open $OUTPUT/reports/*.html     # macOS"
echo "    xdg-open $OUTPUT/reports/*.html # Linux"
echo ""
