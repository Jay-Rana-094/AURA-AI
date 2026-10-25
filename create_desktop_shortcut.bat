@echo off
REM AURA AI — double-click this once to put an AURA icon on your Desktop.
REM It runs install_desktop_shortcut.ps1 (bypasses the execution policy
REM for that script only). No console window appears when you later
REM launch AURA from the Desktop icon.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_desktop_shortcut.ps1"
pause
