param(
  [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$project = Join-Path $root "launcher\Codrex.Launcher\Codrex.Launcher.csproj"

if (-not (Test-Path $project)) {
  throw "Missing launcher project at $project"
}

$dotnet = (Get-Command dotnet -ErrorAction SilentlyContinue).Source
if (-not $dotnet) {
  throw ".NET 8 SDK is required to build the new Codrex desktop launcher. Install it first, then re-run Setup.cmd."
}

$sdkList = @(& $dotnet --list-sdks 2>$null | ForEach-Object { [string]$_ })
$hasDotnet8 = $false
foreach ($sdk in $sdkList) {
  if ($sdk -match "^8\.") {
    $hasDotnet8 = $true
    break
  }
}
if (-not $hasDotnet8) {
  throw ".NET 8 SDK is required to build the new Codrex desktop launcher. Install it first, then re-run Setup.cmd."
}

$arguments = @(
  "publish",
  $project,
  "-c", $Configuration,
  "-r", "win-x64",
  "--self-contained", "false",
  "/nologo"
)

& $dotnet @arguments
if ($LASTEXITCODE -ne 0) {
  throw "dotnet publish failed for the Codrex desktop launcher."
}

$publishedExe = Join-Path $root "launcher\Codrex.Launcher\bin\$Configuration\net8.0-windows\win-x64\publish\Codrex.Launcher.exe"
if (-not (Test-Path $publishedExe)) {
  throw "Desktop launcher publish completed, but the executable was not found at $publishedExe"
}

$currentDir = Join-Path $root "launcher\Codrex.Launcher\bin\current"
New-Item -ItemType Directory -Path $currentDir -Force | Out-Null
$publishDir = Join-Path $root "launcher\Codrex.Launcher\bin\$Configuration\net8.0-windows\win-x64\publish"
$publishItems = Get-ChildItem -Path $publishDir -Force | Where-Object { $_.Name -ne "Codrex.Launcher.exe.WebView2" }
foreach ($item in $publishItems) {
  Copy-Item -Path $item.FullName -Destination $currentDir -Recurse -Force
}
Remove-Item -Path (Join-Path $currentDir "Codrex.Launcher.exe.WebView2") -Recurse -Force -ErrorAction SilentlyContinue

Write-Output $publishedExe
