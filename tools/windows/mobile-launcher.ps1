Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:DefaultControllerPort = 48787
$script:DefaultDevUiPort = 54312

function Get-PrimaryIPv4 {
  try {
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop |
      Where-Object { $_.NextHop -and $_.NextHop -ne "0.0.0.0" } |
      Sort-Object RouteMetric, ifMetric |
      Select-Object -First 1
    if ($route) {
      $ip = Get-NetIPAddress -InterfaceIndex $route.ifIndex -AddressFamily IPv4 -ErrorAction Stop |
        Where-Object { $_.IPAddress -notlike "169.254*" -and $_.IPAddress -ne "127.0.0.1" } |
        Select-Object -First 1 -ExpandProperty IPAddress
      if ($ip) { return [string]$ip }
    }
  } catch {}
  try {
    $line = (ipconfig | Select-String "IPv4 Address").Line | Select-Object -First 1
    if ($line -match ":\s*([0-9\.]+)\s*$") { return [string]$matches[1] }
  } catch {}
  return "127.0.0.1"
}

function Get-TailscaleIPv4 {
  $exe = ""
  try {
    $cmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($cmd) { $exe = [string]$cmd.Source }
  } catch {}
  if (-not $exe) {
    $pf = $env:ProgramFiles
    $pf86 = ${env:ProgramFiles(x86)}
    $localAppData = $env:LocalAppData
    $candidates = @()
    if ($pf) { $candidates += (Join-Path $pf "Tailscale\\tailscale.exe") }
    if ($pf86) { $candidates += (Join-Path $pf86 "Tailscale\\tailscale.exe") }
    if ($localAppData) { $candidates += (Join-Path $localAppData "Tailscale\\tailscale.exe") }
    $exe = ($candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1)
  }
  if (-not $exe) { return "" }
  try {
    $out = & $exe ip -4 2>$null
    $ip = [string](($out | Select-Object -First 1))
    $ip = $ip.Trim()
    if ($ip -match "^\d+\.\d+\.\d+\.\d+$") { return $ip }
  } catch {}
  return ""
}

function Get-CodrexRuntimeDir {
  param(
    [string]$RepoRoot
  )
  $override = [string]$env:CODEX_RUNTIME_DIR
  if ($override -and $override.Trim()) {
    return $override.Trim()
  }
  $localAppData = [string]$env:LocalAppData
  if ($localAppData -and $localAppData.Trim()) {
    return (Join-Path $localAppData "Codrex\remote-ui")
  }
  return (Join-Path $RepoRoot ".runtime")
}

function Read-ControllerConfig([string]$Path) {
  $cfg = [ordered]@{
    port = $script:DefaultControllerPort
    token = ""
  }
  if (Test-Path $Path) {
    try {
      $loaded = Get-Content -Path $Path -Raw | ConvertFrom-Json
      if ($loaded -and $loaded.port) { $cfg.port = [int]$loaded.port }
      if ($loaded -and $loaded.token) { $cfg.token = [string]$loaded.token }
    } catch {}
  }
  foreach ($localPath in @($script:LocalConfigPath, $script:LegacyLocalConfigPath)) {
    if (-not (Test-Path $localPath)) { continue }
    try {
      $loadedLocal = Get-Content -Path $localPath -Raw | ConvertFrom-Json
      if ($loadedLocal -and $loadedLocal.port) { $cfg.port = [int]$loadedLocal.port }
      if ($loadedLocal -and $loadedLocal.token) { $cfg.token = [string]$loadedLocal.token }
      break
    } catch {}
  }
  return [pscustomobject]$cfg
}

function Test-HttpReady([string]$Url) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
    return ($r.StatusCode -eq 200)
  } catch {}
  return $false
}

function Get-ProcessByPort([int]$Port) {
  try {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  } catch {
    return $null
  }
  if (-not $listeners) { return $null }
  foreach ($entry in ($listeners | Select-Object -Unique OwningProcess)) {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $entry.OwningProcess) -ErrorAction SilentlyContinue
    if ($proc) { return $proc }
  }
  return $null
}

function Get-ListeningStateMap {
  param(
    [int[]]$Ports
  )
  $map = @{}
  foreach ($p in $Ports) {
    $map[[int]$p] = $false
  }
  try {
    $listeners = Get-NetTCPConnection -State Listen -ErrorAction Stop |
      Where-Object { $map.ContainsKey([int]$_.LocalPort) } |
      Select-Object -ExpandProperty LocalPort -Unique
    foreach ($lp in $listeners) {
      $map[[int]$lp] = $true
    }
    return $map
  } catch {
    try {
      $lines = netstat -ano -p tcp | Select-String "LISTENING"
      foreach ($line in $lines) {
        $raw = [string]$line
        if ($raw -match "^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+\d+\s*$") {
          $lp = [int]$matches[1]
          if ($map.ContainsKey($lp)) {
            $map[$lp] = $true
          }
        }
      }
    } catch {}
  }
  return $map
}

function Invoke-Json {
  param(
    [string]$Url,
    [string]$Method,
    [object]$BodyObj,
    [string]$Token,
    [Microsoft.PowerShell.Commands.WebRequestSession]$Session
  )
  $headers = @{}
  if ($Token) { $headers["x-auth-token"] = $Token }
  $body = $null
  if ($null -ne $BodyObj) {
    $body = ($BodyObj | ConvertTo-Json -Depth 6)
    $headers["Content-Type"] = "application/json"
  }
  try {
    $invokeParams = @{
      Uri = $Url
      Method = $Method
      TimeoutSec = 5
    }
    if ($headers.Count -gt 0) { $invokeParams["Headers"] = $headers }
    if ($null -ne $body) { $invokeParams["Body"] = $body }
    if ($Session) { $invokeParams["WebSession"] = $Session }
    return Invoke-RestMethod @invokeParams
  } catch {}
  return $null
}

function Get-AppHealth {
  param(
    [int]$ControllerPort
  )
  return Invoke-Json -Url ("http://127.0.0.1:{0}/app/health" -f $ControllerPort) -Method "GET" -BodyObj $null -Token "" -Session $null
}

function Get-AppRuntime {
  param(
    [int]$ControllerPort
  )
  return Invoke-Json -Url ("http://127.0.0.1:{0}/app/runtime" -f $ControllerPort) -Method "GET" -BodyObj $null -Token "" -Session $null
}

function Read-MobileSession {
  foreach ($candidate in @($script:SessionPath, $script:LegacySessionPath)) {
    if (-not (Test-Path $candidate)) { continue }
    try {
      $session = Get-Content -Path $candidate -Raw | ConvertFrom-Json
      if ($session) {
        return $session
      }
    } catch {}
  }
  return $null
}

function Get-QrPngImage {
  param(
    [string]$Url,
    [string]$Token,
    [Microsoft.PowerShell.Commands.WebRequestSession]$Session
  )
  $headers = @{}
  if ($Token) { $headers["x-auth-token"] = $Token }
  try {
    $invokeParams = @{
      UseBasicParsing = $true
      Uri = $Url
      TimeoutSec = 8
    }
    if ($headers.Count -gt 0) { $invokeParams["Headers"] = $headers }
    if ($Session) { $invokeParams["WebSession"] = $Session }
    $resp = Invoke-WebRequest @invokeParams
    if (-not $resp -or -not $resp.Content) { return $null }
    $ms = New-Object System.IO.MemoryStream
    $ms.Write($resp.Content, 0, $resp.Content.Length) | Out-Null
    $ms.Position = 0
    return [System.Drawing.Image]::FromStream($ms)
  } catch {}
  return $null
}

function Open-Url([string]$Url) {
  if (-not $Url) { return $false }
  try {
    $null = Start-Process -FilePath "explorer.exe" -ArgumentList @($Url) -PassThru
    return $true
  } catch {}
  try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Url
    $psi.UseShellExecute = $true
    $null = [System.Diagnostics.Process]::Start($psi)
    return $true
  } catch {}
  try {
    $null = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", "start", "", $Url) -WindowStyle Hidden -PassThru
    return $true
  } catch {}
  return $false
}

function Invoke-HiddenPowerShellScript {
  param(
    [string]$ScriptPath,
    [string[]]$Arguments = @()
  )
  if (-not (Test-Path $ScriptPath)) {
    throw "Missing $ScriptPath"
  }
  $invokeArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $ScriptPath
  )
  if ($Arguments) {
    $invokeArgs += $Arguments
  }
  $script:lastHelperOutput = ""
  $capturedOutput = @(& powershell.exe @invokeArgs 2>&1 | ForEach-Object { [string]$_ })
  if ($capturedOutput.Count -gt 0) {
    $script:lastHelperOutput = ($capturedOutput -join "`n").Trim()
  }
  if ($LASTEXITCODE -is [int]) {
    return [int]$LASTEXITCODE
  }
  return 0
}

function Invoke-RuntimeAction {
  param(
    [string]$ActionName
  )
  $args = @("-Action", $ActionName, "-UiPort", [string]$uiPort)
  if ($ActionName -eq "start" -and $script:applyFirewallOnStart) {
    $args += "-OpenFirewall"
  }
  $exitCode = Invoke-HiddenPowerShellScript -ScriptPath $runtimeScript -Arguments $args
  $jsonText = [string]$script:lastHelperOutput
  if (-not $jsonText) {
    throw "Codrex runtime '$ActionName' returned no output."
  }
  try {
    $payload = $jsonText | ConvertFrom-Json
  } catch {
    throw "Codrex runtime '$ActionName' returned invalid JSON. Output: $jsonText"
  }
  if (-not $payload) {
    throw "Codrex runtime '$ActionName' returned an empty payload."
  }
  if ($exitCode -ne 0 -or (-not $payload.ok)) {
    $detail = if ($payload.detail) { [string]$payload.detail } else { $jsonText }
    throw "Codrex runtime '$ActionName' failed. $detail"
  }
  return $payload
}

function Start-DetachedRuntimeAction {
  param(
    [string]$ActionName
  )
  if (-not (Test-Path $runtimeScript)) {
    throw "Missing $runtimeScript"
  }
  $invokeArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $runtimeScript,
    "-Action", $ActionName,
    "-UiPort", [string]$uiPort
  )
  if ($ActionName -eq "start" -and $script:applyFirewallOnStart) {
    $invokeArgs += "-OpenFirewall"
  }
  $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $invokeArgs -WindowStyle Hidden -PassThru
  return [int]$proc.Id
}

function Wait-ForPortsReleased {
  param(
    [int[]]$Ports,
    [int]$Attempts = 24,
    [int]$DelayMs = 250
  )
  $filtered = @($Ports | Where-Object { $_ -gt 0 } | Select-Object -Unique)
  if (-not $filtered -or $filtered.Count -eq 0) {
    return $true
  }
  for ($i = 0; $i -lt $Attempts; $i++) {
    $listening = Get-ListeningStateMap -Ports $filtered
    $hasListeners = $false
    foreach ($port in $filtered) {
      if ([bool]$listening[[int]$port]) {
        $hasListeners = $true
        break
      }
    }
    if (-not $hasListeners) {
      return $true
    }
    Start-Sleep -Milliseconds $DelayMs
  }
  return $false
}

function Wait-ForSessionCleared {
  param(
    [int]$Attempts = 20,
    [int]$DelayMs = 200
  )
  for ($i = 0; $i -lt $Attempts; $i++) {
    if (-not (Read-MobileSession)) {
      return $true
    }
    Start-Sleep -Milliseconds $DelayMs
  }
  return $false
}

function Get-LauncherStatusSnapshot {
  $payload = Invoke-RuntimeAction -ActionName "status"
  $repoRoot = if ($payload.repo_root) { [string]$payload.repo_root } else { "" }
  $repoLabel = if ($repoRoot) { Split-Path -Leaf $repoRoot } else { "n/a" }
  return [pscustomobject]@{
    session = $payload.session
    controller_port = [int]$payload.controller_port
    controller_on = [bool]$payload.controller_pid
    app_runtime = $null
    app_health = $null
    app_built = [bool]$payload.app_ready
    app_mode = if ($payload.ui_mode) { [string]$payload.ui_mode } else { "offline" }
    version = if ($payload.app_version) { [string]$payload.app_version } else { "n/a" }
    repo_root = $repoRoot
    repo_label = $repoLabel
    repo_rev = if ($payload.repo_rev) { [string]$payload.repo_rev } else { "" }
    session_state = if ($payload.session_present) { "present" } else { "missing" }
    local_url = if ($payload.local_url) { [string]$payload.local_url } else { "offline" }
    network_url = if ($payload.network_url) { [string]$payload.network_url } else { "n/a" }
    status = if ($payload.status) { [string]$payload.status } else { "stopped" }
    lan_ip = Get-CachedLanIp
    detail = if ($payload.detail) { [string]$payload.detail } else { "" }
  }
}

function Apply-LauncherStatus {
  param(
    [object]$Snapshot
  )
  if (-not $Snapshot) {
    return
  }
  $revSuffix = if ($Snapshot.repo_rev) { " | Rev: $($Snapshot.repo_rev)" } else { "" }
  $lblStatus.Text = "Launcher shell | State: $($Snapshot.status) | Mode: $($Snapshot.app_mode)`r`nBuild: v$($Snapshot.version)$revSuffix | Port: $($Snapshot.controller_port) | Session: $($Snapshot.session_state)`r`nApp: $($Snapshot.local_url)`r`nLAN: $($Snapshot.network_url) | Repo: $($Snapshot.repo_label)`r`nDetail: $($Snapshot.detail)"
  switch ([string]$Snapshot.status) {
    "running" {
      $statusCard.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#0d2f53")
      $lblStatus.ForeColor = $colorAccent
    }
    "checking" {
      $statusCard.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#3c3110")
      $lblStatus.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#ffd166")
    }
    "recovering" {
      $statusCard.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#2f2b0d")
      $lblStatus.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#ffd166")
    }
    "error" {
      $statusCard.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#3a1620")
      $lblStatus.ForeColor = $colorDanger
    }
    default {
      $statusCard.BackColor = $colorSurfaceSoft
      $lblStatus.ForeColor = $colorText
    }
  }
}

function Set-ActionStatus {
  param(
    [string]$State,
    [string]$Detail,
    [int]$ControllerPort = 0
  )
  $portText = if ($ControllerPort -gt 0) { [string]$ControllerPort } else { "pending" }
  $lblStatus.Text = "Launcher shell | State: $State | Mode: action`r`nPort: $portText | Detail: $Detail`r`nLogs: $logsDir"
  if ($State -eq "error") {
    $statusCard.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#3a1620")
    $lblStatus.ForeColor = $colorDanger
  } else {
    $statusCard.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#3c3110")
    $lblStatus.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#ffd166")
  }
}

function Clear-PendingStart {
  $script:pendingStart = $false
  $script:pendingStartAt = [DateTime]::MinValue
  $script:pendingStartPort = 0
  $script:pendingStartResultRead = $false
  if ($script:pendingStartWorker) {
    try { $script:pendingStartWorker.Dispose() } catch {}
  }
  $script:pendingStartWorker = $null
  $script:pendingStartAsync = $null
}

function Start-PowerShellScriptTask {
  param(
    [string]$ScriptPath,
    [int]$LaunchUiPort
  )
  if (-not (Test-Path $ScriptPath)) {
    throw "Missing $ScriptPath"
  }
  $ps = [powershell]::Create()
  $null = $ps.AddScript({
    param(
      [string]$TaskScriptPath,
      [int]$TaskUiPort
    )
    & $TaskScriptPath -UiPort $TaskUiPort
  }).AddArgument($ScriptPath).AddArgument($LaunchUiPort)
  return [pscustomobject]@{
    worker = $ps
    async = $ps.BeginInvoke()
  }
}

function Read-PendingStartTaskResult {
  if (-not $script:pendingStartWorker -or -not $script:pendingStartAsync) {
    return [pscustomobject]@{
      completed = $false
      ok = $false
      detail = ""
    }
  }
  if (-not $script:pendingStartAsync.IsCompleted) {
    return [pscustomobject]@{
      completed = $false
      ok = $false
      detail = ""
    }
  }
  if ($script:pendingStartResultRead) {
    return [pscustomobject]@{
      completed = $true
      ok = ($script:lastHelperOutput -eq "")
      detail = $script:lastHelperOutput
    }
  }
  $detailLines = New-Object System.Collections.Generic.List[string]
  $ok = $true
  try {
    $output = @($script:pendingStartWorker.EndInvoke($script:pendingStartAsync) | ForEach-Object { [string]$_ })
    foreach ($line in $output) {
      if ($line -and $line.Trim()) {
        $detailLines.Add($line.Trim())
      }
    }
  } catch {
    $ok = $false
    if ($_.Exception -and $_.Exception.Message) {
      $detailLines.Add([string]$_.Exception.Message)
    }
  }
  foreach ($err in $script:pendingStartWorker.Streams.Error) {
    $errText = [string]$err
    if ($errText -and $errText.Trim()) {
      $detailLines.Add($errText.Trim())
      $ok = $false
    }
  }
  $script:lastHelperOutput = ($detailLines | Select-Object -Unique) -join " | "
  $script:pendingStartResultRead = $true
  return [pscustomobject]@{
    completed = $true
    ok = $ok
    detail = $script:lastHelperOutput
  }
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $root
$stateDir = Join-Path $runtimeDir "state"
$logsDir = Join-Path $runtimeDir "logs"
$configPath = Join-Path $root "controller.config.json"
$script:LocalConfigPath = Join-Path $stateDir "controller.config.local.json"
$script:LegacyLocalConfigPath = Join-Path $root "controller.config.local.json"
$script:SessionPath = Join-Path $stateDir "mobile.session.json"
$script:LegacySessionPath = Join-Path (Join-Path $root "logs") "mobile.session.json"
$startMobileScript = Join-Path $scriptRoot "start-mobile.ps1"
$stopMobileScript = Join-Path $scriptRoot "stop-mobile.ps1"
$runtimeScript = Join-Path $scriptRoot "codrex-runtime.ps1"
$uiPort = $script:DefaultDevUiPort
$controllerPort = $script:DefaultControllerPort
$controllerToken = ""
$script:pairUrl = ""
$authSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$script:applyFirewallOnStart = $false
$colorBg = [System.Drawing.ColorTranslator]::FromHtml("#040915")
$colorSurface = [System.Drawing.ColorTranslator]::FromHtml("#0a1426")
$colorSurfaceSoft = [System.Drawing.ColorTranslator]::FromHtml("#0e1b33")
$colorBorder = [System.Drawing.ColorTranslator]::FromHtml("#274a75")
$colorText = [System.Drawing.ColorTranslator]::FromHtml("#e8f4ff")
$colorMuted = [System.Drawing.ColorTranslator]::FromHtml("#9cb8d6")
$colorAccent = [System.Drawing.ColorTranslator]::FromHtml("#1cc8ff")
$colorAccentSoft = [System.Drawing.ColorTranslator]::FromHtml("#0d2f53")
$colorDanger = [System.Drawing.ColorTranslator]::FromHtml("#ff5f7d")
$script:cachedControllerConfig = $null
$script:cachedControllerConfigAt = [DateTime]::MinValue
$script:cachedLanIp = "127.0.0.1"
$script:cachedLanIpAt = [DateTime]::MinValue
$script:refreshInProgress = $false
$script:actionInProgress = $false
$script:refreshTimer = $null
$script:launcherButtons = @()
$script:lastHelperOutput = ""
$script:pendingRuntimeAction = ""
$script:pendingRuntimeActionAt = [DateTime]::MinValue
$script:pendingRuntimeTimeoutSec = 45
$script:advancedVisible = $false
$script:pendingStart = $false
$script:pendingStartAt = [DateTime]::MinValue
$script:pendingStartTimeoutSec = 45
$script:pendingStartPort = 0
$script:pendingStartWorker = $null
$script:pendingStartAsync = $null
$script:pendingStartResultRead = $false

function Set-LauncherButtonStyle {
  param(
    [System.Windows.Forms.Button]$Button,
    [bool]$Primary = $false,
    [bool]$Danger = $false
  )
  if (-not $Button) { return }
  $Button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
  $Button.FlatAppearance.BorderSize = 1
  $Button.FlatAppearance.MouseOverBackColor = [System.Drawing.ColorTranslator]::FromHtml("#15466f")
  $Button.FlatAppearance.MouseDownBackColor = [System.Drawing.ColorTranslator]::FromHtml("#0b3556")
  $Button.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 9.5)
  $Button.MinimumSize = New-Object System.Drawing.Size(150, 38)
  $Button.Margin = New-Object System.Windows.Forms.Padding(0, 0, 10, 10)
  $Button.AutoSize = $false
  $Button.Size = New-Object System.Drawing.Size(168, 38)
  $kind = "default"
  $normalBack = $colorAccentSoft
  $normalFore = $colorText
  $normalBorder = $colorBorder
  $pressedBack = [System.Drawing.ColorTranslator]::FromHtml("#0b3556")
  $pressedFore = $colorText
  $pressedBorder = [System.Drawing.ColorTranslator]::FromHtml("#4ea8dc")
  if ($Danger) {
    $kind = "danger"
    $normalBack = [System.Drawing.ColorTranslator]::FromHtml("#2a121d")
    $normalFore = $colorDanger
    $normalBorder = [System.Drawing.ColorTranslator]::FromHtml("#6d2d43")
    $pressedBack = [System.Drawing.ColorTranslator]::FromHtml("#4b1d2d")
    $pressedFore = [System.Drawing.ColorTranslator]::FromHtml("#ffd9e1")
    $pressedBorder = [System.Drawing.ColorTranslator]::FromHtml("#ff9ab1")
  } elseif ($Primary) {
    $kind = "primary"
    $normalBack = [System.Drawing.ColorTranslator]::FromHtml("#0c3f63")
    $normalFore = $colorText
    $normalBorder = [System.Drawing.ColorTranslator]::FromHtml("#2b7cb2")
    $pressedBack = [System.Drawing.ColorTranslator]::FromHtml("#136094")
    $pressedFore = [System.Drawing.ColorTranslator]::FromHtml("#f3fbff")
    $pressedBorder = [System.Drawing.ColorTranslator]::FromHtml("#63cfff")
  }
  $Button.BackColor = $normalBack
  $Button.ForeColor = $normalFore
  $Button.FlatAppearance.BorderColor = $normalBorder
  $Button.Tag = @{
    kind = $kind
    normalBack = $normalBack
    normalFore = $normalFore
    normalBorder = $normalBorder
    pressedBack = $pressedBack
    pressedFore = $pressedFore
    pressedBorder = $pressedBorder
  }
}

function Reset-LauncherButtonVisual {
  param(
    [System.Windows.Forms.Button]$Button
  )
  if (-not $Button) { return }
  $meta = $Button.Tag
  if ($meta -is [hashtable]) {
    $Button.BackColor = $meta["normalBack"]
    $Button.ForeColor = $meta["normalFore"]
    $Button.FlatAppearance.BorderColor = $meta["normalBorder"]
  }
}

function Register-LauncherButtonFeedback {
  param(
    [System.Windows.Forms.Button]$Button
  )
  if (-not $Button) { return }
  $Button.Add_MouseDown({
    param($sender, $eventArgs)
    $meta = $sender.Tag
    if ($meta -is [hashtable]) {
      $sender.BackColor = $meta["pressedBack"]
      $sender.ForeColor = $meta["pressedFore"]
      $sender.FlatAppearance.BorderColor = $meta["pressedBorder"]
    }
  })
  $Button.Add_MouseUp({
    param($sender, $eventArgs)
    Reset-LauncherButtonVisual -Button $sender
  })
  $Button.Add_MouseLeave({
    param($sender, $eventArgs)
    Reset-LauncherButtonVisual -Button $sender
  })
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "Codrex"
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.Size = New-Object System.Drawing.Size(1120, 760)
$form.MinimumSize = New-Object System.Drawing.Size(1000, 700)
$form.Icon = [System.Drawing.SystemIcons]::Shield
$form.BackColor = $colorBg
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

$split = New-Object System.Windows.Forms.SplitContainer
$split.Dock = "Fill"
$split.Orientation = [System.Windows.Forms.Orientation]::Vertical
$split.SplitterDistance = 660
$split.SplitterWidth = 6
$split.IsSplitterFixed = $false
$form.Controls.Add($split)

$left = New-Object System.Windows.Forms.TableLayoutPanel
$left.Dock = "Fill"
$left.Padding = New-Object System.Windows.Forms.Padding(14)
$left.ColumnCount = 1
$left.RowCount = 7
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 84)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 50)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 180)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 24)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 40)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 24)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
$split.Panel1.Controls.Add($left)

$right = New-Object System.Windows.Forms.TableLayoutPanel
$right.Dock = "Fill"
$right.Padding = New-Object System.Windows.Forms.Padding(14)
$right.ColumnCount = 1
$right.RowCount = 4
$right.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 28)))
$right.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
$right.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 34)))
$right.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 68)))
$split.Panel2.Controls.Add($right)

$titleCard = New-Object System.Windows.Forms.Panel
$titleCard.Dock = "Fill"
$titleCard.Padding = New-Object System.Windows.Forms.Padding(12, 10, 12, 8)
$titleCard.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$left.Controls.Add($titleCard, 0, 0)

$titleWrap = New-Object System.Windows.Forms.TableLayoutPanel
$titleWrap.Dock = "Fill"
$titleWrap.ColumnCount = 2
$titleWrap.RowCount = 1
$titleWrap.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 56)))
$titleWrap.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
$titleCard.Controls.Add($titleWrap)

$picTitle = New-Object System.Windows.Forms.PictureBox
$picTitle.Dock = "Fill"
$picTitle.Margin = New-Object System.Windows.Forms.Padding(0, 2, 0, 2)
$picTitle.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
$picTitle.Image = [System.Drawing.SystemIcons]::Shield.ToBitmap()
$titleWrap.Controls.Add($picTitle, 0, 0)

$titleStack = New-Object System.Windows.Forms.TableLayoutPanel
$titleStack.Dock = "Fill"
$titleStack.ColumnCount = 1
$titleStack.RowCount = 2
$titleStack.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 30)))
$titleStack.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
$titleWrap.Controls.Add($titleStack, 1, 0)

$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "Codrex"
$lblTitle.Dock = "Fill"
$lblTitle.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 13)
$lblTitle.TextAlign = "MiddleLeft"
$titleStack.Controls.Add($lblTitle, 0, 0)

$lblSubtitle = New-Object System.Windows.Forms.Label
$lblSubtitle.Text = "Launcher shell only. Start/stop Codrex here, then use the browser app for sessions, files, notes, and remote control."
$lblSubtitle.Dock = "Fill"
$lblSubtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$lblSubtitle.TextAlign = "TopLeft"
$titleStack.Controls.Add($lblSubtitle, 0, 1)

$statusCard = New-Object System.Windows.Forms.Panel
$statusCard.Dock = "Fill"
$statusCard.Padding = New-Object System.Windows.Forms.Padding(12, 6, 12, 6)
$statusCard.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$left.Controls.Add($statusCard, 0, 1)

$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = "State: checking..."
$lblStatus.Dock = "Fill"
$lblStatus.TextAlign = "MiddleLeft"
$statusCard.Controls.Add($lblStatus)

$actionsCard = New-Object System.Windows.Forms.Panel
$actionsCard.Dock = "Fill"
$actionsCard.Padding = New-Object System.Windows.Forms.Padding(12, 10, 12, 4)
$actionsCard.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$left.Controls.Add($actionsCard, 0, 2)

$actionsGrid = New-Object System.Windows.Forms.TableLayoutPanel
$actionsGrid.Dock = "Fill"
$actionsGrid.ColumnCount = 1
$actionsGrid.RowCount = 3
$actionsGrid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 54)))
$actionsGrid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 0)))
$actionsGrid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 0)))
$actionsCard.Controls.Add($actionsGrid)

$rowStartStop = New-Object System.Windows.Forms.FlowLayoutPanel
$rowStartStop.Dock = "Fill"
$rowStartStop.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$rowStartStop.WrapContents = $true
$actionsGrid.Controls.Add($rowStartStop, 0, 0)

$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = "Start"
$rowStartStop.Controls.Add($btnStart) | Out-Null

$btnOpenLocal = New-Object System.Windows.Forms.Button
$btnOpenLocal.Text = "Open App"
$rowStartStop.Controls.Add($btnOpenLocal) | Out-Null

$btnGenQr = New-Object System.Windows.Forms.Button
$btnGenQr.Text = "Show Pair QR"
$rowStartStop.Controls.Add($btnGenQr) | Out-Null

$btnAdvanced = New-Object System.Windows.Forms.Button
$btnAdvanced.Text = "Advanced"
$rowStartStop.Controls.Add($btnAdvanced) | Out-Null

$rowOpen = New-Object System.Windows.Forms.FlowLayoutPanel
$rowOpen.Dock = "Fill"
$rowOpen.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$rowOpen.WrapContents = $true
$actionsGrid.Controls.Add($rowOpen, 0, 1)

$btnOpenNetwork = New-Object System.Windows.Forms.Button
$btnOpenNetwork.Text = "Open Network App"
$rowOpen.Controls.Add($btnOpenNetwork) | Out-Null

$btnOpenController = New-Object System.Windows.Forms.Button
$btnOpenController.Text = "Open Fallback"
$rowOpen.Controls.Add($btnOpenController) | Out-Null

$rowPair = New-Object System.Windows.Forms.FlowLayoutPanel
$rowPair.Dock = "Fill"
$rowPair.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$rowPair.WrapContents = $true
$actionsGrid.Controls.Add($rowPair, 0, 2)

$btnCopyPair = New-Object System.Windows.Forms.Button
$btnCopyPair.Text = "Copy Pair Link"
$rowPair.Controls.Add($btnCopyPair) | Out-Null

$btnOpenPair = New-Object System.Windows.Forms.Button
$btnOpenPair.Text = "Open Pair Link"
$rowPair.Controls.Add($btnOpenPair) | Out-Null

$lblPairLink = New-Object System.Windows.Forms.Label
$lblPairLink.Text = "Pair Link"
$lblPairLink.Dock = "Fill"
$lblPairLink.TextAlign = "BottomLeft"
$lblPairLink.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 9)
$left.Controls.Add($lblPairLink, 0, 3)

$txtPair = New-Object System.Windows.Forms.TextBox
$txtPair.Dock = "Fill"
$txtPair.ReadOnly = $true
$txtPair.Font = New-Object System.Drawing.Font("Consolas", 9)
$left.Controls.Add($txtPair, 0, 4)

$lblLog = New-Object System.Windows.Forms.Label
$lblLog.Text = "Activity Log"
$lblLog.Dock = "Fill"
$lblLog.TextAlign = "BottomLeft"
$lblLog.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 9)
$left.Controls.Add($lblLog, 0, 5)

$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Multiline = $true
$txtLog.ScrollBars = "Vertical"
$txtLog.Dock = "Fill"
$txtLog.ReadOnly = $true
$txtLog.Font = New-Object System.Drawing.Font("Consolas", 9)
$left.Controls.Add($txtLog, 0, 6)

$lblQr = New-Object System.Windows.Forms.Label
$lblQr.Text = "Pairing QR"
$lblQr.Dock = "Fill"
$lblQr.TextAlign = "MiddleLeft"
$lblQr.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 10)
$right.Controls.Add($lblQr, 0, 0)

$qrCard = New-Object System.Windows.Forms.Panel
$qrCard.Dock = "Fill"
$qrCard.Padding = New-Object System.Windows.Forms.Padding(10)
$qrCard.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$right.Controls.Add($qrCard, 0, 1)

$picQr = New-Object System.Windows.Forms.PictureBox
$picQr.Dock = "Fill"
$picQr.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$picQr.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
$qrCard.Controls.Add($picQr)

$lblQrInfo = New-Object System.Windows.Forms.Label
$lblQrInfo.Text = "Press Show Pair QR, then scan on phone/tablet."
$lblQrInfo.Dock = "Fill"
$lblQrInfo.TextAlign = "MiddleLeft"
$right.Controls.Add($lblQrInfo, 0, 2)

$lblHint = New-Object System.Windows.Forms.Label
$lblHint.Text = "Browser app opens only when you click Open App. This window is the local launcher and status shell."
$lblHint.Dock = "Fill"
$lblHint.TextAlign = "TopLeft"
$right.Controls.Add($lblHint, 0, 3)

$split.BackColor = $colorBg
$split.Panel1.BackColor = $colorBg
$split.Panel2.BackColor = $colorBg
$left.BackColor = $colorBg
$right.BackColor = $colorBg
$titleCard.BackColor = $colorSurface
$titleWrap.BackColor = $colorSurface
$titleStack.BackColor = $colorSurface
$statusCard.BackColor = $colorSurfaceSoft
$actionsCard.BackColor = $colorSurface
$actionsGrid.BackColor = $colorSurface
$rowStartStop.BackColor = $colorSurface
$rowOpen.BackColor = $colorSurface
$rowPair.BackColor = $colorSurface
$qrCard.BackColor = $colorSurface

$lblTitle.ForeColor = $colorText
$lblSubtitle.ForeColor = $colorMuted
$lblStatus.ForeColor = $colorText
$lblPairLink.ForeColor = $colorMuted
$lblLog.ForeColor = $colorMuted
$lblQr.ForeColor = $colorAccent
$lblQrInfo.ForeColor = $colorText
$lblHint.ForeColor = $colorMuted
$txtPair.BackColor = $colorSurfaceSoft
$txtPair.ForeColor = $colorText
$txtPair.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$txtLog.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#071225")
$txtLog.ForeColor = $colorText
$txtLog.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$picQr.BackColor = $colorSurfaceSoft
$picQr.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle

Set-LauncherButtonStyle -Button $btnStart -Primary $true
Set-LauncherButtonStyle -Button $btnOpenLocal
Set-LauncherButtonStyle -Button $btnAdvanced
Set-LauncherButtonStyle -Button $btnOpenNetwork
Set-LauncherButtonStyle -Button $btnOpenController
Set-LauncherButtonStyle -Button $btnGenQr -Primary $true
Set-LauncherButtonStyle -Button $btnCopyPair
Set-LauncherButtonStyle -Button $btnOpenPair
@(
  $btnStart,
  $btnOpenLocal,
  $btnAdvanced,
  $btnOpenNetwork,
  $btnOpenController,
  $btnGenQr,
  $btnCopyPair,
  $btnOpenPair
) | ForEach-Object { Register-LauncherButtonFeedback -Button $_ }
$script:launcherButtons = @(
  $btnStart,
  $btnOpenLocal,
  $btnAdvanced,
  $btnOpenNetwork,
  $btnOpenController,
  $btnGenQr,
  $btnCopyPair,
  $btnOpenPair
)

function Set-SplitLayout {
  try {
    $split.Panel1MinSize = 520
    $split.Panel2MinSize = 280
    $totalWidth = [int]$split.ClientSize.Width
    if ($totalWidth -le ($split.Panel1MinSize + $split.Panel2MinSize + 8)) {
      return
    }
    $target = [int][Math]::Round($totalWidth * 0.62)
    $maxAllowed = $totalWidth - $split.Panel2MinSize
    if ($target -lt $split.Panel1MinSize) { $target = $split.Panel1MinSize }
    if ($target -gt $maxAllowed) { $target = $maxAllowed }
    if ($target -gt 0) {
      $split.SplitterDistance = $target
    }
  } catch {}
}

function Set-PrimaryActionStyle {
  param(
    [bool]$IsRunning
  )
  if ($IsRunning) {
    Set-LauncherButtonStyle -Button $btnStart -Danger $true
  } else {
    Set-LauncherButtonStyle -Button $btnStart -Primary $true
  }
  Reset-LauncherButtonVisual -Button $btnStart
}

function Set-AdvancedVisibility {
  param(
    [bool]$Visible
  )
  $script:advancedVisible = $Visible
  $rowOpen.Visible = $Visible
  $rowPair.Visible = $Visible
  $lblPairLink.Visible = $Visible
  $txtPair.Visible = $Visible
  $actionsGrid.RowStyles[1].Height = if ($Visible) { 54 } else { 0 }
  $actionsGrid.RowStyles[2].Height = if ($Visible) { 54 } else { 0 }
  $left.RowStyles[2].Height = if ($Visible) { 180 } else { 76 }
  $left.RowStyles[3].Height = if ($Visible) { 24 } else { 0 }
  $left.RowStyles[4].Height = if ($Visible) { 40 } else { 0 }
  $btnAdvanced.Text = if ($Visible) { "Hide Advanced" } else { "Advanced" }
}

function Clear-PairingState {
  $script:pairUrl = ""
  $txtPair.Text = ""
  if ($picQr.Image) {
    try { $picQr.Image.Dispose() } catch {}
  }
  $picQr.Image = $null
  $lblQrInfo.Text = "Press Show Pair QR, then scan on phone/tablet."
  $lblHint.Text = "Browser app opens only when you click Open App. This window is the local launcher and status shell."
}

function Append-Log([string]$Line) {
  $ts = (Get-Date).ToString("HH:mm:ss")
  $txtLog.AppendText("[$ts] $Line`r`n")
}

function Ensure-LauncherAuth {
  param(
    [int]$ControllerPort,
    [string]$FallbackToken
  )
  $statusUrl = ("http://127.0.0.1:{0}/auth/status" -f $ControllerPort)
  $bootstrapUrl = ("http://127.0.0.1:{0}/auth/bootstrap/local" -f $ControllerPort)
  $loginUrl = ("http://127.0.0.1:{0}/auth/login" -f $ControllerPort)

  $status = Invoke-Json -Url $statusUrl -Method "GET" -BodyObj $null -Token "" -Session $authSession
  if ($status -and $status.ok -and ((-not $status.auth_required) -or $status.authenticated)) {
    return $true
  }

  $bootstrap = Invoke-Json -Url $bootstrapUrl -Method "POST" -BodyObj @{} -Token "" -Session $authSession
  if ($bootstrap -and $bootstrap.ok) {
    $status = Invoke-Json -Url $statusUrl -Method "GET" -BodyObj $null -Token "" -Session $authSession
    if ($status -and $status.ok -and ((-not $status.auth_required) -or $status.authenticated)) {
      return $true
    }
  }

  if ($FallbackToken) {
    $login = Invoke-Json -Url $loginUrl -Method "POST" -BodyObj @{ token = $FallbackToken } -Token "" -Session $authSession
    if ($login -and $login.ok) {
      $status = Invoke-Json -Url $statusUrl -Method "GET" -BodyObj $null -Token "" -Session $authSession
      if ($status -and $status.ok -and ((-not $status.auth_required) -or $status.authenticated)) {
        return $true
      }
    }
  }

  return $false
}

function Get-CachedControllerConfig {
  $now = Get-Date
  if (($null -eq $script:cachedControllerConfig) -or ($now -ge $script:cachedControllerConfigAt)) {
    $script:cachedControllerConfig = Read-ControllerConfig -Path $configPath
    $script:cachedControllerConfigAt = $now.AddSeconds(5)
  }
  return $script:cachedControllerConfig
}

function Get-CachedLanIp {
  $now = Get-Date
  if ((-not $script:cachedLanIp) -or ($now -ge $script:cachedLanIpAt)) {
    $script:cachedLanIp = Get-PrimaryIPv4
    $script:cachedLanIpAt = $now.AddSeconds(15)
  }
  return $script:cachedLanIp
}

function Resolve-LauncherControllerPort {
  $snapshot = Get-LauncherStatusSnapshot
  return [int]$snapshot.controller_port
}

function Refresh-State {
  param(
    [switch]$Force
  )
  if ($script:refreshInProgress -or ($script:actionInProgress -and -not $Force)) { return }
  $script:refreshInProgress = $true
  try {
    $snapshot = Get-LauncherStatusSnapshot
    $stackActive = ($snapshot.controller_on -or $snapshot.session_state -eq "present")
    $pendingAction = [string]$script:pendingRuntimeAction
    if ($pendingAction) {
      $ageSeconds = [int]([DateTime]::UtcNow - $script:pendingRuntimeActionAt).TotalSeconds
      if ($pendingAction -eq "start") {
        if ($snapshot.status -eq "running") {
          $script:pendingRuntimeAction = ""
          Append-Log ("Start complete. App ready on port {0} (v{1}). Click Open App to launch the browser UI." -f $snapshot.controller_port, $(if ($snapshot.version) { $snapshot.version } else { "n/a" }))
        } elseif ($ageSeconds -le $script:pendingRuntimeTimeoutSec) {
          $snapshot.status = "starting"
          $snapshot.detail = "Waiting for Codrex runtime to report ready..."
        } else {
          Append-Log "Start request timed out while waiting for runtime readiness."
          $script:pendingRuntimeAction = ""
        }
      } elseif ($pendingAction -eq "stop") {
        if ($snapshot.status -eq "stopped") {
          $script:pendingRuntimeAction = ""
          Clear-PairingState
          Append-Log "Stop complete."
        } elseif ($ageSeconds -le $script:pendingRuntimeTimeoutSec) {
          $snapshot.status = "checking"
          $snapshot.detail = "Waiting for Codrex runtime to stop..."
        } else {
          Append-Log "Stop request timed out while waiting for runtime shutdown."
          $script:pendingRuntimeAction = ""
        }
      }
    }
    if (-not $stackActive) {
      Clear-PairingState
    }
    Apply-LauncherStatus -Snapshot $snapshot
    $busy = ($script:actionInProgress -or [bool]$script:pendingRuntimeAction)
    $btnStart.Enabled = (-not $busy)
    $btnStart.Text = if ($stackActive) { "Stop" } else { "Start" }
    Set-PrimaryActionStyle -IsRunning:$stackActive
    $btnOpenLocal.Enabled = (-not $busy) -and $snapshot.controller_on
    $btnOpenNetwork.Enabled = (-not $busy) -and $snapshot.controller_on -and ($snapshot.lan_ip -ne "127.0.0.1")
    $btnOpenController.Enabled = (-not $busy) -and $snapshot.controller_on
    $btnGenQr.Enabled = (-not $busy) -and $snapshot.app_built
    $btnAdvanced.Enabled = (-not $busy)
    $hasPair = [bool]$script:pairUrl
    $btnCopyPair.Enabled = (-not $busy) -and $hasPair
    $btnOpenPair.Enabled = (-not $busy) -and $hasPair
  } catch {
    $msg = [string]$_.Exception.Message
    if (-not $msg) { $msg = "Could not refresh launcher state." }
    Set-ActionStatus -State "error" -Detail $msg
  } finally {
    $script:refreshInProgress = $false
  }
}

function Start-Stack {
  $existingSnapshot = Get-LauncherStatusSnapshot
  if ($existingSnapshot.app_built) {
    Append-Log ("Codrex is already running on port {0}." -f $existingSnapshot.controller_port)
    return
  }
  Append-Log "Starting mobile stack..."
  Set-ActionStatus -State "starting" -Detail "Launching Codrex runtime..." -ControllerPort $existingSnapshot.controller_port
  $procId = Start-DetachedRuntimeAction -ActionName "start"
  $script:pendingRuntimeAction = "start"
  $script:pendingRuntimeActionAt = [DateTime]::UtcNow
  Append-Log ("Start requested via runtime helper PID {0}." -f $procId)
}

function Stop-Stack {
  Append-Log "Stopping mobile stack..."
  $procId = Start-DetachedRuntimeAction -ActionName "stop"
  $script:pendingRuntimeAction = "stop"
  $script:pendingRuntimeActionAt = [DateTime]::UtcNow
  Append-Log ("Stop requested via runtime helper PID {0}." -f $procId)
}

function Toggle-AdvancedActions {
  Set-AdvancedVisibility -Visible:(-not $script:advancedVisible)
}

function Generate-PairQr {
  $cfg = Get-CachedControllerConfig
  $controllerPort = Resolve-LauncherControllerPort
  $controllerToken = [string]$cfg.token

  $listening = Get-ListeningStateMap -Ports @($controllerPort)
  if (-not [bool]$listening[[int]$controllerPort]) {
    throw "Controller is not reachable."
  }
  if (-not (Ensure-LauncherAuth -ControllerPort $controllerPort -FallbackToken $controllerToken)) {
    throw "Could not authenticate launcher session. Open the app locally once, or start the controller so it writes the runtime token file."
  }

  $tailscale = Get-TailscaleIPv4
  $lan = Get-CachedLanIp
  $pairHost = if ($tailscale) { $tailscale } elseif ($lan) { $lan } else { "127.0.0.1" }
  $route = if ($tailscale) { "Tailscale" } elseif ($lan -and $lan -ne "127.0.0.1") { "LAN" } else { "Localhost" }
  $confidence = if ($tailscale) { "high confidence" } elseif ($lan -and $lan -ne "127.0.0.1") { "medium confidence" } else { "low confidence" }

  Append-Log "Creating pairing code ($route)..."
  $create = Invoke-Json -Url ("http://127.0.0.1:{0}/auth/pair/create" -f $controllerPort) -Method "POST" -BodyObj @{} -Token "" -Session $authSession
  if (-not $create -or -not $create.ok -or -not $create.code) {
    throw "Could not create pairing code."
  }

  $base = ("http://{0}:{1}" -f $pairHost, $controllerPort)
  $script:pairUrl = "$base/auth/pair/consume?code=$([Uri]::EscapeDataString([string]$create.code))"
  $txtPair.Text = $script:pairUrl

  $qrEndpoint = "http://127.0.0.1:$controllerPort/auth/pair/qr.png?data=$([Uri]::EscapeDataString($script:pairUrl))&ts=$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
  $img = Get-QrPngImage -Url $qrEndpoint -Token "" -Session $authSession
  if ($null -eq $img) {
    throw "Could not render QR image."
  }
  if ($picQr.Image) {
    try { $picQr.Image.Dispose() } catch {}
  }
  $picQr.Image = $img
  $expires = if ($create.expires_in) { [int]$create.expires_in } else { 0 }
  $lblQrInfo.Text = "Route: $route ($confidence) | Expires in: ${expires}s"
  $lblHint.Text = "Scan now. If the phone cannot open it, retry with Tailscale route."
  Append-Log "QR ready. Scan from phone/tablet."
}

function Safe-Action {
  param(
    [scriptblock]$Action,
    [System.Windows.Forms.Button]$Button
  )
  $savedText = ""
  $activeButton = $null
  $wasTimerRunning = $false
  try {
    if ($script:actionInProgress) { return }
    $script:actionInProgress = $true
    foreach ($b in $script:launcherButtons) {
      if ($b) { $b.Enabled = $false }
    }
    $activeButton = $Button
    if ($activeButton) {
      $savedText = [string]$activeButton.Text
      $activeButton.Text = "Working..."
      $activeButton.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#1a4a73")
      $activeButton.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#f3fbff")
    }
    if ($script:refreshTimer) {
      $wasTimerRunning = $script:refreshTimer.Enabled
      if ($wasTimerRunning) { $script:refreshTimer.Stop() }
    }
    $form.UseWaitCursor = $true
    [System.Windows.Forms.Application]::DoEvents()
    & $Action
  } catch {
    $msg = [string]$_.Exception.Message
    if (-not $msg) { $msg = "Unknown error" }
    Append-Log "Error: $msg"
    [System.Windows.Forms.MessageBox]::Show(
      $msg,
      "Codrex",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
  } finally {
    if ($activeButton) {
      $activeButton.Text = $savedText
      Reset-LauncherButtonVisual -Button $activeButton
    }
    $form.UseWaitCursor = $false
    $script:actionInProgress = $false
    if ($script:refreshTimer -and $wasTimerRunning) {
      $script:refreshTimer.Start()
    }
    Refresh-State
  }
}

$btnStart.Add_Click({
  Safe-Action -Action {
    $snapshot = Get-LauncherStatusSnapshot
    if ($snapshot.controller_on -or $snapshot.session_state -eq "present") {
      Stop-Stack
    } else {
      Start-Stack
    }
  } -Button $btnStart
})
$btnOpenLocal.Add_Click({
  $port = Resolve-LauncherControllerPort
  $url = ("http://127.0.0.1:{0}/" -f $port)
  if (Open-Url $url) {
    Append-Log ("Opened app: {0}" -f $url)
  } else {
    Append-Log ("Could not open app: {0}" -f $url)
  }
})
$btnAdvanced.Add_Click({ Toggle-AdvancedActions })
$btnOpenNetwork.Add_Click({
  $port = Resolve-LauncherControllerPort
  $ip = Get-CachedLanIp
  $url = ("http://{0}:{1}/" -f $ip, $port)
  if (Open-Url $url) {
    Append-Log ("Opened network app: {0}" -f $url)
  } else {
    Append-Log ("Could not open network app: {0}" -f $url)
  }
})
$btnOpenController.Add_Click({
  $port = Resolve-LauncherControllerPort
  $url = ("http://127.0.0.1:{0}/legacy" -f $port)
  if (Open-Url $url) {
    Append-Log ("Opened fallback page: {0}" -f $url)
  } else {
    Append-Log ("Could not open fallback page: {0}" -f $url)
  }
})
$btnGenQr.Add_Click({ Safe-Action -Action { Generate-PairQr } -Button $btnGenQr })
$btnCopyPair.Add_Click({
  if ($script:pairUrl) {
    try { [System.Windows.Forms.Clipboard]::SetText($script:pairUrl) } catch {}
    Append-Log "Pair link copied to clipboard."
  }
})
$btnOpenPair.Add_Click({
  if ($script:pairUrl) {
    if (Open-Url $script:pairUrl) {
      Append-Log "Opened pair link."
    } else {
      Append-Log ("Could not open pair link: {0}" -f $script:pairUrl)
    }
  }
})

$form.Add_Shown({
  Set-SplitLayout
})

$script:refreshTimer = New-Object System.Windows.Forms.Timer
$script:refreshTimer.Interval = 2000
$script:refreshTimer.Add_Tick({ Refresh-State })
$script:refreshTimer.Start()

Set-AdvancedVisibility -Visible:$false
Clear-PairingState

$form.Add_FormClosed({
  try { $script:refreshTimer.Stop() } catch {}
  try { $script:refreshTimer.Dispose() } catch {}
  try { if ($picTitle.Image) { $picTitle.Image.Dispose() } } catch {}
  try { if ($picQr.Image) { $picQr.Image.Dispose() } } catch {}
  try { $form.Dispose() } catch {}
})

Append-Log "Launcher ready."
Refresh-State
[System.Windows.Forms.Application]::Run($form)
