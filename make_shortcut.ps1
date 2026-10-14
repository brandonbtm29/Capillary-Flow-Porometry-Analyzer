# Creates (or refreshes) the "Capillary Flow Porometry Analyzer" shortcuts on your Desktop and in the
# Start menu, with the app icon. Same as Settings > Create app icon in the app; the .bat launcher also
# does this once on first start. Run again whenever the repo folder moves:
#   powershell -ExecutionPolicy Bypass -File make_shortcut.ps1
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$py   = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "Run 'Capillary Flow Porometry Analyzer.bat' once first to set up .venv"; exit 1 }
& $py -m porometry.shortcuts
