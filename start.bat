@echo off
REM ==========================================================================
REM  Start PaperOrchestra Studio (Streamlit UI)
REM  Usage:  start.bat            -> http://localhost:8501
REM          start.bat 8600       -> custom port
REM ==========================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title PaperOrchestra Studio

if not exist ".venv\Scripts\python.exe" (
    echo The virtual environment is missing. Run install.bat first.
    pause
    exit /b 1
)

set "PORT=8501"
if not "%~1"=="" set "PORT=%~1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

".venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo Streamlit is not installed in .venv. Run install.bat again.
    pause
    exit /b 1
)

echo.
echo   PaperOrchestra Studio is starting on http://localhost:%PORT%
echo   Close this window (or press Ctrl+C) to stop the server.
echo.
".venv\Scripts\python.exe" -m streamlit run ui\app.py ^
    --server.port %PORT% ^
    --server.headless false ^
    --server.maxUploadSize 500 ^
    --browser.gatherUsageStats false ^
    --theme.base light
if errorlevel 1 pause
