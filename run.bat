@echo off
REM AURA AI — one-click start (Windows)
REM First run: pip install -r requirements.txt
REM (and download the Vosk model into models\ — see README.md)
cd /d %~dp0
python main.py
if errorlevel 1 (
    echo.
    echo AURA stopped with an error. If this is your first run, try:
    echo   pip install -r requirements.txt
    pause
)
