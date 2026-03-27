@echo off
setlocal
cd /d "%~dp0"
set "LAUNCHER_CURRENT_EXE=%~dp0launcher\Codrex.Launcher\bin\current\Codrex.Launcher.exe"
set "LAUNCHER_CURRENT_DLL=%~dp0launcher\Codrex.Launcher\bin\current\Codrex.Launcher.dll"
set "LAUNCHER_RELEASE=%~dp0launcher\Codrex.Launcher\bin\Release\net8.0-windows\Codrex.Launcher.exe"
set "LAUNCHER_PUBLISH=%~dp0launcher\Codrex.Launcher\bin\Release\net8.0-windows\win-x64\publish\Codrex.Launcher.exe"
set "LAUNCHER_DEBUG=%~dp0launcher\Codrex.Launcher\bin\Debug\net8.0-windows\Codrex.Launcher.exe"

if exist "%LAUNCHER_CURRENT_EXE%" (
  start "" "%LAUNCHER_CURRENT_EXE%"
  exit /b 0
)

if exist "%LAUNCHER_CURRENT_DLL%" (
  start "" dotnet "%LAUNCHER_CURRENT_DLL%"
  exit /b 0
)

if exist "%LAUNCHER_RELEASE%" (
  start "" "%LAUNCHER_RELEASE%"
  exit /b 0
)

if exist "%LAUNCHER_PUBLISH%" (
  start "" "%LAUNCHER_PUBLISH%"
  exit /b 0
)

if exist "%LAUNCHER_DEBUG%" (
  start "" "%LAUNCHER_DEBUG%"
  exit /b 0
)

echo Codrex desktop launcher is not built yet. Falling back to the legacy PowerShell launcher.
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0tools\windows\mobile-launcher.ps1"
