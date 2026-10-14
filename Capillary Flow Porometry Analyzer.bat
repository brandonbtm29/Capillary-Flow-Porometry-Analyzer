@echo off
rem Double-click to start Capillary Flow Porometry Analyzer. First run sets up a private Python environment (.venv).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up Capillary Flow Porometry Analyzer for the first time - this takes about a minute...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo Could not create the environment. Install Python 3.10+ from python.org and tick "Add python.exe to PATH".
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 (
        echo Installing dependencies failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
)
rem Desktop + Start menu icon, made once (Settings > Create app icon remakes it)
if not exist ".venv\.shortcut-made" ".venv\Scripts\python.exe" -m porometry.shortcuts
start "" ".venv\Scripts\pythonw.exe" -m porometry %*
