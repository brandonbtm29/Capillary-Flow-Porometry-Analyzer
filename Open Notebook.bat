@echo off
rem Opens your working copy of the comparison notebook in JupyterLab.
rem The working copy (with your plots and numbers) lives in SyncThing, not in this public repo:
rem   %USERPROFILE%\SyncThing\UAkron Playground\Capillary Flow Porometer\Notebooks\compare_conditions.ipynb
rem It is copied from examples\compare_conditions.ipynb the first time. Set UAKRON_DATA_DIR to use another root.
set "REPO=%~dp0"
set "ROOT=%USERPROFILE%\SyncThing\UAkron Playground"
if defined UAKRON_DATA_DIR set "ROOT=%UAKRON_DATA_DIR%"
set "NBDIR=%ROOT%\Capillary Flow Porometer\Notebooks"
if not exist "%REPO%.venv\Scripts\jupyter-lab.exe" (
    if not exist "%REPO%.venv\Scripts\python.exe" py -3 -m venv "%REPO%.venv"
    "%REPO%.venv\Scripts\python.exe" -m pip install -e "%REPO%.[notebook]"
)
if not exist "%NBDIR%" mkdir "%NBDIR%"
if not exist "%NBDIR%\compare_conditions.ipynb" copy "%REPO%examples\compare_conditions.ipynb" "%NBDIR%\" >nul
cd /d "%NBDIR%"
"%REPO%.venv\Scripts\jupyter-lab.exe" compare_conditions.ipynb
