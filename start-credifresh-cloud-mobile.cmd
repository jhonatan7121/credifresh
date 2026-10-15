@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-credifresh-cloud-mobile.ps1"
if errorlevel 1 pause
endlocal
