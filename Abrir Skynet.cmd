@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0herramientas\pi\abrir.ps1"
if errorlevel 1 pause
