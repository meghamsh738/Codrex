@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0..\mobile-launcher.ps1" (
  echo mobile-launcher.ps1 not found in %~dp0..
  pause
  exit /b 1
)
start "" wscript.exe "%~dp0..\powershell-hidden.vbs" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0..\mobile-launcher.ps1"
