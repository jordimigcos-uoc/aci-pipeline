@echo off
REM =============================================================================
REM run_local.bat — Configura i executa el pipeline ACI en local (Windows)
REM
REM Us:
REM   scripts\run_local.bat
REM
REM Variables configurables (edita les linies SET si cal):
REM   VENV_DIR   (per defecte: .venv)
REM   URL_FILE   (per defecte: data\inputs\urls.sample.txt)
REM   PROFILE    (per defecte: wcag_strict)
REM   OUTPUT     (per defecte: results\local)
REM =============================================================================
setlocal EnableDelayedExpansion

if "%VENV_DIR%"==""  set VENV_DIR=.venv
if "%URL_FILE%"==""  set URL_FILE=data\inputs\urls.sample.txt
if "%PROFILE%"==""   set PROFILE=wcag_strict
if "%OUTPUT%"==""    set OUTPUT=results\local

REM Ens situem a l'arrel del projecte (un nivell sobre scripts\)
cd /d "%~dp0.."

echo.
echo =================================================================
echo   ACI Pipeline v0.1.0 -- Execucio local (Windows)
echo =================================================================
echo   URL file : %URL_FILE%
echo   Profile  : %PROFILE%
echo   Output   : %OUTPUT%
echo.

REM ── Pas 1: Crea entorn virtual ───────────────────────────────────────────
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [1/5] Creant entorn virtual a %VENV_DIR%\ ...
    python -m venv %VENV_DIR%
    if errorlevel 1 (
        echo ERROR: no s'ha pogut crear el venv. Assegura't que Python 3.10+ esta instal·lat.
        exit /b 1
    )
) else (
    echo [1/5] Entorn virtual existent: %VENV_DIR%\
)

REM ── Pas 2: Activa l'entorn virtual ───────────────────────────────────────
echo [2/5] Activant entorn virtual...
call %VENV_DIR%\Scripts\activate.bat

REM ── Pas 3: Instal·la dependències ────────────────────────────────────────
echo [3/5] Instal·lant dependencies Python...
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo ERROR: ha fallat pip install. Revisa requirements.txt i la connexio a Internet.
    exit /b 1
)

REM ── Pas 4: Instal·la navegadors Playwright ───────────────────────────────
echo [4/5] Instal·lant navegador Chromium (Playwright)...
playwright install chromium --with-deps
if errorlevel 1 (
    echo AVIS: no s'ha pogut instal·lar Chromium. El pipeline usara fallback HTTP.
)

REM ── Pas 5: Carrega .env si existeix ──────────────────────────────────────
if exist ".env" (
    echo   -^> Carregant .env ...
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set line=%%A
        if not "!line:~0,1!"=="#" (
            set %%A=%%B
        )
    )
)

REM ── Pas 5: Executa el pipeline ───────────────────────────────────────────
echo [5/5] Executant pipeline...
echo.

python -m aci_pipeline.cli ^
    --url-file %URL_FILE% ^
    --profile  %PROFILE% ^
    --output   %OUTPUT% ^
    --log-level INFO

if errorlevel 1 (
    echo.
    echo AVIS: el pipeline ha acabat amb errors. Revisa els logs a logs\
    exit /b 1
)

REM ── Resum ─────────────────────────────────────────────────────────────────
echo.
echo =================================================================
echo   Execucio completada!
echo =================================================================
echo   Resultats  : %CD%\%OUTPUT%
echo   Logs       : %CD%\logs\
echo.
echo   Per obrir l'informe: explora la carpeta %OUTPUT%\reports\
echo.

endlocal
