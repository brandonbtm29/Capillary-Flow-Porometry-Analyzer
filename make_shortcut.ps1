# Creates a "Porometry Analyzer" shortcut on your Desktop and in the Start menu.
# Run once after the first launch of "Porometry Analyzer.bat" (which creates .venv):
#   powershell -ExecutionPolicy Bypass -File make_shortcut.ps1
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw  = Join-Path $repo ".venv\Scripts\pythonw.exe"
$icon = Join-Path $repo "src\porometry\gui\resources\porometry.ico"
if (-not (Test-Path $pyw)) { Write-Error "Run 'Porometry Analyzer.bat' once first to set up .venv"; exit 1 }
$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "Porometry Analyzer.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "Porometry Analyzer.lnk")
)
foreach ($t in $targets) {
    $s = $shell.CreateShortcut($t)
    $s.TargetPath = $pyw
    $s.Arguments = "-m porometry"
    $s.WorkingDirectory = $repo
    $s.IconLocation = "$icon,0"
    $s.Description = "Capillary flow porometry analysis (CapWin .CFT files)"
    $s.Save()
    Write-Output "Created $t"
}
