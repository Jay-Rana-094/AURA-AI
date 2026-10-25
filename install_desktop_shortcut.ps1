# AURA AI — creates a Desktop shortcut (one-time setup).
# The shortcut launches AURA with pythonw.exe, so no console window
# appears: double-clicking the Desktop icon just shows the pill.
# Run via create_desktop_shortcut.bat (it bypasses the execution
# policy for this script only).

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $pythonw) {
    # Fallback: plain python.exe works too, but shows a console window.
    $pythonw = Get-Command python.exe -ErrorAction SilentlyContinue
}
if (-not $pythonw) {
    Write-Host "Python not found. Install Python 3.10+ with 'Add Python to PATH' and try again."
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut("$desktop\AURA.lnk")
$link.TargetPath = $pythonw.Source
$link.Arguments = "`"$projectDir\main.py`""
$link.WorkingDirectory = $projectDir
# Use AURA's own icon when present, else fall back to Python's.
$iconFile = Join-Path $projectDir "aura-icon.ico"
if (Test-Path $iconFile) {
    $link.IconLocation = $iconFile
} else {
    $link.IconLocation = $pythonw.Source
}
$link.Description = "AURA AI voice assistant"
$link.Save()

Write-Host "Done! An 'AURA' icon is now on your Desktop."
Write-Host "Double-click it anytime to start AURA (no VS Code, no terminal)."
