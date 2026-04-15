@echo off
setlocal
cd /d "%~dp0"
start "" wscript.exe "%~dp0..\powershell-hidden.vbs" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0..\mobile-launcher.ps1"
