@echo off
cd /d "%~dp0"
if "%~1"=="" (python -m comparador ejecutar) else (python -m comparador %*)
pause
