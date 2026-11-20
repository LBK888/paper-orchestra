@echo off
REM ==========================================================================
REM  PaperOrchestra installer for Windows
REM  - checks the environment (Python, pip, LaTeX, Node.js, Graphviz, pandoc)
REM  - creates a virtual environment in .venv and installs requirements.txt
REM  - optionally installs MiKTeX / Node.js (winget) and the Remotion workspace
REM
REM  Usage:  install.bat            interactive
REM          install.bat /y         answer "yes" to every optional install
REM          install.bat /minimal   Python packages only, skip optional tools
REM ==========================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title PaperOrchestra installer

set "AUTO=0"
set "MINIMAL=0"
if /I "%~1"=="/y" set "AUTO=1"
if /I "%~1"=="/minimal" set "MINIMAL=1"

set "HAS_WINGET=0"
where winget >nul 2>nul && set "HAS_WINGET=1"

echo.
echo ==========================================================
echo   PaperOrchestra installer
echo ==========================================================

REM --------------------------------------------------------------------------
echo.
echo [1/7] Looking for Python 3.10 - 3.13 ...
REM --------------------------------------------------------------------------
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
    for %%V in (3.12 3.11 3.13 3.10) do (
        if not defined PY (
            py -%%V -c "import sys" >nul 2>nul
            if not errorlevel 1 set "PY=py -%%V"
        )
    )
)
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY=python"
    )
)
if not defined PY (
    echo   Python 3.10-3.13 was not found.
    if "%HAS_WINGET%"=="1" (
        call :ask "Install Python 3.12 with winget now" || goto :no_python
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        py -3.12 -c "import sys" >nul 2>nul
        if not errorlevel 1 set "PY=py -3.12"
    )
)
if not defined PY goto :no_python
for /f "delims=" %%I in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%I"
echo   OK: using "%PY%" (Python %PYVER%)
%PY% -c "import sys; sys.exit(0 if sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul
if errorlevel 1 echo   WARNING: Python %PYVER% is very new; some packages may lack wheels. 3.12 is recommended.

REM --------------------------------------------------------------------------
echo.
echo [2/7] Creating virtual environment in .venv ...
REM --------------------------------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo   Existing .venv is broken, recreating it.
        rmdir /s /q ".venv"
    ) else (
        echo   .venv already exists, reusing it.
    )
)
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   ERROR: could not create the virtual environment.
        goto :fail
    )
)
set "VPY=%~dp0.venv\Scripts\python.exe"
set "PYTHONUTF8=1"

REM --------------------------------------------------------------------------
echo.
echo [3/7] Installing Python packages (this can take several minutes) ...
REM --------------------------------------------------------------------------
"%VPY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :pip_fail
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_fail

echo   Verifying imports ...
"%VPY%" -c "import google.genai, openai, streamlit, matplotlib, seaborn, pandas, pymupdf, mcp, pypandoc, docx; print('  OK: core packages import fine')"
if errorlevel 1 goto :pip_fail

REM --------------------------------------------------------------------------
echo.
echo [4/7] Configuration files ...
REM --------------------------------------------------------------------------
if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo   Created .env from .env.example - add your API keys there or in the UI Settings page.
) else (
    echo   .env already exists, leaving it untouched.
)
if not exist "projects" mkdir "projects"

if "%MINIMAL%"=="1" goto :summary

REM --------------------------------------------------------------------------
echo.
echo [5/7] LaTeX (needed to compile PDFs and for the review/refine loop) ...
REM --------------------------------------------------------------------------
where pdflatex >nul 2>nul
if not errorlevel 1 (
    echo   OK: pdflatex found.
) else (
    echo   pdflatex not found. Without LaTeX the pipeline still writes the paper,
    echo   but skips the review/refine loop and PDF compilation (DOCX/MD export still works^).
    if "%HAS_WINGET%"=="1" (
        call :ask "Install MiKTeX with winget now (about 1 GB)" && (
            winget install -e --id MiKTeX.MiKTeX --accept-package-agreements --accept-source-agreements
            echo   MiKTeX installed. Open a NEW terminal so PATH picks it up.
        )
    ) else (
        echo   Install MiKTeX from https://miktex.org/download or TeX Live.
    )
)
where initexmf >nul 2>nul
if not errorlevel 1 (
    initexmf --set-config-value=[MPM]AutoInstall=1 >nul 2>nul
    echo   MiKTeX: enabled automatic installation of missing LaTeX packages.
)

REM --------------------------------------------------------------------------
echo.
echo [6/7] Node.js + Remotion (optional: code-defined animated figures) ...
REM --------------------------------------------------------------------------
where node >nul 2>nul
if errorlevel 1 (
    echo   Node.js not found. Remotion figures will be unavailable.
    if "%HAS_WINGET%"=="1" (
        call :ask "Install Node.js LTS with winget now" && (
            winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
            echo   Node.js installed. Re-run install.bat in a NEW terminal to set up Remotion.
        )
    ) else (
        echo   Install Node.js 18+ from https://nodejs.org
    )
) else (
    for /f "delims=" %%N in ('node --version') do echo   OK: node %%N
    call :ask "Install the Remotion workspace (npm install, ~200 MB incl. headless Chrome)" && (
        pushd "tools\remotion"
        call npm install --no-audit --no-fund
        if errorlevel 1 (
            echo   WARNING: npm install failed; Remotion figures will be unavailable.
        ) else (
            call node node_modules\@remotion\cli\remotion-cli.js browser ensure
        )
        popd
    )
)

REM --------------------------------------------------------------------------
echo.
echo [7/7] Optional extras ...
REM --------------------------------------------------------------------------
where dot >nul 2>nul
if not errorlevel 1 (
    echo   OK: Graphviz found.
) else (
    echo   Graphviz not found (optional diagram engine^).
    if "%HAS_WINGET%"=="1" (
        call :ask "Install Graphviz with winget now" && winget install -e --id Graphviz.Graphviz --accept-package-agreements --accept-source-agreements
    )
)
call :ask "Download a headless Chrome for plotly static export (only needed if Google Chrome is not installed)" && (
    "%VPY%" -c "import kaleido; kaleido.get_chrome_sync()"
)

:summary
echo.
echo ==========================================================
echo   Environment summary
echo ==========================================================
"%VPY%" -c "import sys; print('  Python      :', sys.version.split()[0], sys.executable)"
call :check pdflatex "LaTeX       "
call :check bibtex   "BibTeX      "
call :check node     "Node.js     "
call :check dot      "Graphviz    "
if exist "tools\remotion\node_modules\@remotion\cli\remotion-cli.js" (echo   Remotion    : installed) else (echo   Remotion    : not installed)
"%VPY%" -c "import pypandoc; print('  pandoc      :', pypandoc.get_pandoc_version())" 2>nul || echo   pandoc      : not available
echo.
echo   Done. Start the UI with:  start.bat
echo   Command line:            .venv\Scripts\python paper_writing_cli.py -h
echo.
if not "%AUTO%"=="1" pause
exit /b 0

REM ==========================================================================
:ask
REM  :ask "question"  -> errorlevel 0 = yes, 1 = no
if "%AUTO%"=="1" exit /b 0
choice /C YN /N /T 60 /D N /M "  %~1? [Y/N] "
if errorlevel 2 exit /b 1
exit /b 0

:check
where %1 >nul 2>nul
if errorlevel 1 (echo   %~2: not found) else (echo   %~2: found)
exit /b 0

:no_python
echo.
echo   ERROR: Python 3.10-3.13 is required.
echo   Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH")
echo   or run:  winget install -e --id Python.Python.3.12
goto :fail

:pip_fail
echo.
echo   ERROR: installing Python packages failed. Check your network / proxy and retry.
echo   Tip: Python 3.12 has the best wheel coverage for these packages.
goto :fail

:fail
echo.
echo   Installation did not complete.
if not "%AUTO%"=="1" pause
exit /b 1
