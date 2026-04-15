$ErrorActionPreference = "Stop"

$argsList = @(
  "-d", "Ubuntu",
  "bash", "-lc",
  "cd ~ && exec codex"
)

Start-Process -FilePath "wsl.exe" -ArgumentList $argsList | Out-Null

