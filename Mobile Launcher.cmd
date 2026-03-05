@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0mobile-launcher.ps1" (
  echo mobile-launcher.ps1 not found in %~dp0
  pause
  exit /b 1
)
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0mobile-launcher.ps1"
