@echo off
rem Lanceur de l interface d analyse - double-clic pour demarrer
cd /d "%~dp0"
python -m interface.app
if errorlevel 1 pause
