@echo off
setlocal
cd /d "%~dp0"
set "LAUNCHER_CURRENT_EXE=%~dp0launcher\Codrex.Launcher\bin\current\Codrex.Launcher.exe"
set "LAUNCHER_CURRENT_DLL=%~dp0launcher\Codrex.Launcher\bin\current\Codrex.Launcher.dll"

if exist "%LAUNCHER_CURRENT_EXE%" (
  start "" "%LAUNCHER_CURRENT_EXE%"
  exit /b 0
)

if exist "%LAUNCHER_CURRENT_DLL%" (
  start "" dotnet "%LAUNCHER_CURRENT_DLL%"
  exit /b 0
)

echo Codrex current launcher build is missing.
exit /b 1
