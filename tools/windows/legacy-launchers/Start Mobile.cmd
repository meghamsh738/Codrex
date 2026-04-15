@echo off
setlocal
cd /d "%~dp0"
start "" wscript.exe "%~dp0..\powershell-hidden.vbs" -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\start-mobile.ps1"
