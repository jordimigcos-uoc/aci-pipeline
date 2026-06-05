# ACI Pipeline v0.1.0

> **Pipeline automatitzat d'avaluació d'accessibilitat web**
> Genera un índex d'accessibilitat cognitiva i visual (ACI, escala 0–5) per a qualsevol URL,
> basat en WCAG 2.1 AA, EN 301 549 v3.2.1 i la Llei 11/2023 (transposició espanyola de la Directiva UE 2019/882).

[![CI](https://github.com/TBD/aci-pipeline/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Llicència MIT](https://img.shields.io/badge/llicència-MIT-green.svg)](LICENSE)

---

## Taula de continguts

1. [Descripció](#descripció)
2. [Arquitectura del pipeline](#arquitectura-del-pipeline)
3. [Estructura del repositori](#estructura-del-repositori)
4. [Requisits](#requisits)
5. [Instal·lació local](#instalació-local)
6. [Execució local](#execució-local)
7. [Execució via GitHub Actions](#execució-via-github-actions)
8. [Publicació a GitHub Pages](#publicació-a-github-pages)
9. [Com pujar a GitHub](#com-pujar-a-github)
10. [Configuració de scoring](#configuració-de-scoring)
11. [Seguretat i dades sensibles](#seguretat-i-dades-sensibles)
12. [Versió i changelog](#versió-i-changelog)

---

## Descripció

**ACI Pipeline** és un pipeline Python modular que analitza l'accessibilitat d'un lloc web en tres fases:

| Fase | Mòduls | Descripció |
|------|--------|------------|
| **Ingesta**   | M1, M2, M3 | Renderitza la pàgina (Playwright), extreu l'estructura HTML i segmenta el contingut |
| **Anàlisi**   | M4, M5, M6 | Calcula 16 mètriques, processa imatges per IA (M5) i agrega l'índex ACI |
| **Reporting** | M7, M8     | Genera prioritats d'intervenció i informes HTML/JSON/CSV |

**Fórmula ACI:**

```
ACI = (Σ nᵢ · wᵢ / Σ wᵢ) × 5.0   ∈ [0, 5]
```

On `nᵢ` és el valor normalitzat de la mètrica *i* i `wᵢ` el seu pes segons el perfil actiu.

**Tres perfils de puntuació disponibles:**

| Perfil              | Prioritat                                 |
|---------------------|-------------------------------------------|
| `wcag_strict`       | Conformitat WCAG 2.1 AA (pes màxim a AXE) |
| `readability_first` | Llegibilitat i complexitat textual         |
| `visual_first`      | Rendiment visual i Core Web Vitals         |

---

## Arquitectura del pipeline

```
URL d'entrada
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  M1 — Ingesta        Playwright/Chromium + axe-core     │
│  M2 — Extracció      BeautifulSoup4 + lxml              │
│  M3 — Segmentació    Anàlisi jeràrquica de contingut    │
│  M4 — Anàlisi        16 mètriques (WCAG → ACI)          │
│  M5 — IA             Alt text automàtic (Anthropic API) │
│  M6 — Agregació      Càlcul ACI ponderat                 │
│  M7 — Perfil         Prioritats d'intervenció            │
│  M8 — Reporting      HTML + JSON + CSV                   │
└─────────────────────────────────────────────────────────┘
    │
    ▼
 results/{slug}/
   ├── reports/report.html
   ├── metrics/score.json
   └── metrics/score_summary.csv
```

---

## Estructura del repositori

```
aci-pipeline/
├── .github/
│   └── workflows/
│       ├── ci.yml                   # CI: tests + execució de mostra
│       └── publish_results.yml      # Publica resultats a GitHub Pages
│
├── configs/
│   └── scoring_config.yaml          # Pesos i normalitzacions de les 16 mètriques
│
├── data/
│   └── inputs/
│       ├── urls.sample.txt          # 3 URLs de mostra (per a CI i proves)
│       └── urls.txt                 # URLs complertes del corpus TFM (no obligatori)
│
├── docs/
│   └── index.html                   # Dashboard estàtic de GitHub Pages
│
├── i18n/
│   ├── ca.json                      # Traduccions en català
│   ├── en.json                      # Traduccions en anglès
│   └── es.json                      # Traduccions en castellà
│
├── scripts/
│   ├── run_local.sh                 # Execució local (Unix / macOS)
│   ├── run_local.bat                # Execució local (Windows)
│   ├── plot_aci_categories.py       # Genera gràfic de barres per categoria
│   └── plot_aci_profiles.py         # Genera histograma i boxplot ACI
│
├── src/
│   └── aci_pipeline/
│       ├── __init__.py              # Versió del paquet
│       ├── cli.py                   # Entrypoint: python -m aci_pipeline.cli
│       ├── m1_ingesta.py            # M1: Renderització i ingesta
│       ├── m2_extraccio.py          # M2: Extracció HTML
│       ├── m3_segmentacio.py        # M3: Segmentació de contingut
│       ├── m4_analisi.py            # M4: Anàlisi de mètriques
│       ├── m5_ia.py                 # M5: IA per alt text
│       ├── m6_agregacio.py          # M6: Càlcul ACI
│       ├── m7_perfil.py             # M7: Perfil de prioritats
│       ├── m8_reporting.py          # M8: Generació d'informes
│       └── utils.py                 # Utilitats compartides
│
├── templates/
│   ├── report.html.j2               # Plantilla Jinja2 informe individual
│   ├── batch_report.html.j2         # Plantilla informe per lots
│   └── comparative.html.j2          # Plantilla informe comparatiu
│
├── tests/
│   ├── __init__.py
│   ├── test_m2_extraccio.py
│   ├── test_m4_analisi.py
│   ├── test_m6_agregacio.py
│   ├── test_multi_profile.py
│   ├── test_pipeline.py
│   ├── test_integracio.py
│   └── urls_sample.txt              # URLs per als tests d'integració
│
├── .env.example                     # Plantilla de variables d'entorn (sense secrets)
├── .gitignore                       # Exclou dades generades, .venv, secrets
├── Dockerfile                       # Imatge Docker (opcional)
├── pyproject.toml                   # Configuració del paquet (PEP 517/518)
├── requirements.txt                 # Dependències Python
└── README.md                        # Aquest fitxer
```

---

## Requisits

| Requisit | Versió mínima | Notes |
|----------|---------------|-------|
| Python   | 3.10+         | Recomanat: 3.11 |
| Git      | 2.x           | Per a control de versions |
| RAM      | 2 GB          | Playwright necessita ~500 MB per a Chromium |
| Internet | —             | Necessari per renderitzar les URLs |

> **Opcional:** Clau API d'Anthropic (`ANTHROPIC_API_KEY`) per al mòdul M5 (generació automàtica d'alt text per IA). Sense la clau, M5 s'omet i el pipeline continua normalment.

---

## Instal·lació local

### Windows (PowerShell o CMD)

```powershell
# 1. Clona el repositori
git clone https://github.com/EL-TEU-USUARI/aci-pipeline.git
cd aci-pipeline

# 2. Crea i activa l'entorn virtual
python -m venv .venv
.venv\Scripts\activate

# 3. Instal·la les dependències
pip install --upgrade pip
pip install -r requirements.txt

# 4. Instal·la el paquet en mode editable (opcional però recomanat)
pip install -e .

# 5. Instal·la Chromium per a Playwright
playwright install chromium --with-deps

# 6. Copia i edita les variables d'entorn
copy .env.example .env
# Edita .env i afegeix la teva ANTHROPIC_API_KEY si en tens una
```

### Unix / macOS (bash / zsh)

```bash
# 1. Clona el repositori
git clone https://github.com/EL-TEU-USUARI/aci-pipeline.git
cd aci-pipeline

# 2. Crea i activa l'entorn virtual
python3 -m venv .venv
source .venv/bin/activate

# 3. Instal·la les dependències
pip install --upgrade pip
pip install -r requirements.txt

# 4. Instal·la el paquet en mode editable (opcional però recomanat)
pip install -e .

# 5. Instal·la Chromium per a Playwright
playwright install chromium --with-deps

# 6. Copia i edita les variables d'entorn
cp .env.example .env
# Edita .env amb el teu editor preferit
```

---

## Execució local

### Opció A — Script automatitzat (recomanada)

```bash
# Unix / macOS
chmod +x scripts/run_local.sh
./scripts/run_local.sh

# Windows
scripts\run_local.bat
```

> El script crea el venv, instal·la deps i executa el pipeline en un sol pas.
> Variables configurables: `URL_FILE`, `PROFILE`, `OUTPUT` (vegeu comentaris dins del script).

### Opció B — Comanda directa

```bash
# Analitza 3 URLs de mostra amb el perfil per defecte (wcag_strict)
python -m aci_pipeline.cli \
    --url-file data/inputs/urls.sample.txt \
    --profile wcag_strict \
    --output results/local/

# Analitza una URL concreta
python -m aci_pipeline.cli \
    --urls https://www.gencat.cat/ca/ciutadania/inici \
    --profile readability_first \
    --output results/prova/

# Executa els 3 perfils per a cada URL (informe comparatiu)
python -m aci_pipeline.cli \
    --url-file data/inputs/urls.sample.txt \
    --all-profiles \
    --output results/complet/

# Ajuda completa
python -m aci_pipeline.cli --help
```

### Estructura dels resultats

Després de l'execució trobaràs:

```
results/local/
├── reports/
│   ├── {slug}_report.html           # Informe HTML individual per URL
│   └── comparative_report.html      # Informe comparatiu (si --all-profiles)
├── metrics/
│   ├── {slug}_{ts}.json             # Mètriques completes en JSON
│   └── score_summary.csv            # Resum ACI de totes les URLs
└── assets/
    └── {slug}_screenshot.png        # Captura de pantalla (si disponible)

logs/
└── pipeline_{timestamp}.log         # Log detallat de l'execució
```

### Tests

```bash
# Executa tots els tests
python -m pytest tests/ -v

# Executa un test específic
python -m pytest tests/test_m6_agregacio.py -v

# Executa amb cobertura
pip install pytest-cov
python -m pytest tests/ --cov=src/aci_pipeline --cov-report=term-missing
```

---

## Execució via GitHub Actions

### Execució automàtica (CI)

El workflow `ci.yml` s'executa automàticament en cada `push` o `pull_request` a `main`.
Comprova tests i executa el pipeline amb les 3 URLs de mostra.

### Execució manual (workflow_dispatch)

Per executar el pipeline manualment des de GitHub:

1. Ves al teu repositori a **GitHub.com**
2. Fes clic a la pestanya **Actions**
3. Selecciona **"Publica resultats a GitHub Pages"** al menú esquerre
4. Fes clic al botó **"Run workflow"** (boto verd a la dreta)
5. Configura els paràmetres:
   - **Fitxer d'URLs**: `data/inputs/urls.sample.txt` (o un fitxer personalitzat)
   - **Perfil**: `wcag_strict`, `readability_first` o `visual_first`
   - **Tots els perfils**: `true` per generar informe comparatiu
6. Fes clic a **"Run workflow"**

Els resultats apareixeran a GitHub Pages en 2–5 minuts.

### Descarregar artifacts de CI

Cada execució de CI desa els resultats com a **artifact**:

1. Ves a **Actions** → selecciona una execució
2. A la part inferior de la pàgina, trobaràs **"Artifacts"**
3. Descarrega `ci-results-{run_id}` per veure els informes HTML i CSV

---

### Configura secrets de GitHub

Per a M5-IA (alt text automàtic) necessites la clau Anthropic:

1. Al repositori → **Settings → Secrets and variables → Actions**
2. **New repository secret**:
   - Name: `ANTHROPIC_API_KEY`
   - Secret: `sk-ant-XXXXXXXXXX...`
3. Fes clic a **Add secret**

> El `GITHUB_TOKEN` ja és disponible automàticament; no cal configurar-lo.

---


---

## Configuració de scoring

El fitxer `configs/scoring_config.yaml` defineix els pesos per a cada perfil.
Pots ajustar-los sense tocar el codi Python:

```yaml
profiles:
  wcag_strict:
    weights:
      alt_text_coverage: 5
      color_contrast_ratio: 5
      audit_critical_violations: 5
      # ... 13 mètriques més ...
    normalization:
      penalty_per_violation: 0.15
      lcp_good_threshold: 2500    # ms: LCP bo → score 1.0
      lcp_poor_threshold: 4000    # ms: LCP dolent → score 0.0
```

Per afegir un perfil nou: copia un bloc existent i ajusta els pesos.
El codi Python detecta automàticament qualsevol perfil definit al YAML.

---

## Seguretat i dades sensibles

> ⚠️ **Mai no pugis al repositori:**
> - El fitxer `.env` (pot contenir `ANTHROPIC_API_KEY`)
> - Captures de pantalla de webs (`data/assets/*.png`)
> - CSVs/JSONs amb resultats complets (`data/metrics/`)
> - Paquets ZIP generats (`data/*.zip`)
> - Logs amb URLs i dades de tercers (`logs/`)

Tots aquests fitxers estan exclosos al `.gitignore`.

**Si has pujat accidentalment un secret:**
1. Rota immediatament la clau a https://console.anthropic.com/
2. Elimina'l de l'historial: `git filter-branch` o [BFG Repo Cleaner](https://rtyley.github.io/bfg-repo-cleaner/)
3. Força el push: `git push --force`

---

## Versió i changelog

### v0.1.0 (Maig 2026) — Primera versió pública

- ✅ 8 mòduls seqüencials M1–M8
- ✅ 16 mètriques d'accessibilitat (WCAG 2.1 AA / EN 301 549)
- ✅ 3 perfils de puntuació: `wcag_strict`, `readability_first`, `visual_first`
- ✅ Informes HTML individual i comparatiu (Jinja2)
- ✅ Export JSON i CSV
- ✅ CI amb GitHub Actions + publicació automàtica a GitHub Pages
- ✅ Corpus de 36 URLs analitzades (5 categories)
- ⚠️ 4 mètriques stub retornen 0.5 per limitació tècnica (v0.2.0 les implementarà)

**Línies futures (v0.2.0):**
- Implementació de `keyboard_clean` i `focus_visible_ratio` via Playwright
- Anàlisi multi-pàgina (crawling de subpàgines)
- API REST per a integració amb eines externes

---

## Llicència

MIT © 2026 Jordi Miguel i Costal · Treball de Fi de Màster

---

*ACI Pipeline v0.1.0 · Universitat · Maig 2026*
