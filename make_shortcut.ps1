# Creates a "Capillary Flow Porometry Analyzer" shortcut on your Desktop and in the Start menu
# (and removes the old "Porometry Analyzer" shortcuts from before the rename).
# Run once after the first launch of "Capillary Flow Porometry Analyzer.bat" (which creates .venv),
# and again whenever the repo folder moves:
#   powershell -ExecutionPolicy Bypass -File make_shortcut.ps1
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw  = Join-Path $repo ".venv\Scripts\pythonw.exe"
$icon = Join-Path $repo "src\porometry\gui\resources\porometry.ico"
$name = "Capillary Flow Porometry Analyzer"
if (-not (Test-Path $pyw)) { Write-Error "Run '$name.bat' once first to set up .venv"; exit 1 }
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $old = Join-Path $dir "Porometry Analyzer.lnk"
    if (Test-Path $old) { Remove-Item $old; Write-Output "Removed old $old" }
    $t = Join-Path $dir "$name.lnk"
    $s = $shell.CreateShortcut($t)
    $s.TargetPath = $pyw
    $s.Arguments = "-m porometry"
    $s.WorkingDirectory = $repo
    $s.IconLocation = "$icon,0"
    $s.Description = "Capillary flow porometry analysis (CapWin .CFT files)"
    $s.Save()
    Write-Output "Created $t"
}
