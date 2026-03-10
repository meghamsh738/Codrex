Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

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
    port = 8787
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
  if (-not $Url) { return }
  try { Start-Process $Url | Out-Null } catch {}
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$root = (Resolve-Path (Join-Path $scriptRoot "..\..")).Path
$runtimeDir = Get-CodrexRuntimeDir -RepoRoot $root
$stateDir = Join-Path $runtimeDir "state"
$logsDir = Join-Path $runtimeDir "logs"
$configPath = Join-Path $root "controller.config.json"
$script:LocalConfigPath = Join-Path $stateDir "controller.config.local.json"
$script:LegacyLocalConfigPath = Join-Path $root "controller.config.local.json"
$startMobileScript = Join-Path $scriptRoot "start-mobile.ps1"
$stopMobileScript = Join-Path $scriptRoot "stop-mobile.ps1"
$uiPort = 4312
$controllerPort = 8787
$controllerToken = ""
$pairUrl = ""
$authSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
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
$lblSubtitle.Text = "Launch the stack, open the app, and pair a phone or tablet."
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
$actionsGrid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 54)))
$actionsGrid.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 54)))
$actionsCard.Controls.Add($actionsGrid)

$rowStartStop = New-Object System.Windows.Forms.FlowLayoutPanel
$rowStartStop.Dock = "Fill"
$rowStartStop.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$rowStartStop.WrapContents = $true
$actionsGrid.Controls.Add($rowStartStop, 0, 0)

$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = "Start"
$rowStartStop.Controls.Add($btnStart) | Out-Null

$btnStop = New-Object System.Windows.Forms.Button
$btnStop.Text = "Stop"
$rowStartStop.Controls.Add($btnStop) | Out-Null

$rowOpen = New-Object System.Windows.Forms.FlowLayoutPanel
$rowOpen.Dock = "Fill"
$rowOpen.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$rowOpen.WrapContents = $true
$actionsGrid.Controls.Add($rowOpen, 0, 1)

$btnOpenLocal = New-Object System.Windows.Forms.Button
$btnOpenLocal.Text = "Open App"
$rowOpen.Controls.Add($btnOpenLocal) | Out-Null

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

$btnGenQr = New-Object System.Windows.Forms.Button
$btnGenQr.Text = "Show Pair QR"
$rowPair.Controls.Add($btnGenQr) | Out-Null

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
$lblQrInfo.Text = "Step 1: Show QR. Step 2: Scan on phone/tablet."
$lblQrInfo.Dock = "Fill"
$lblQrInfo.TextAlign = "MiddleLeft"
$right.Controls.Add($lblQrInfo, 0, 2)

$lblHint = New-Object System.Windows.Forms.Label
$lblHint.Text = "No manual token typing needed on phone. QR performs one-time auth."
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
Set-LauncherButtonStyle -Button $btnStop -Danger $true
Set-LauncherButtonStyle -Button $btnOpenLocal
Set-LauncherButtonStyle -Button $btnOpenNetwork
Set-LauncherButtonStyle -Button $btnOpenController
Set-LauncherButtonStyle -Button $btnGenQr -Primary $true
Set-LauncherButtonStyle -Button $btnCopyPair
Set-LauncherButtonStyle -Button $btnOpenPair
@(
  $btnStart,
  $btnStop,
  $btnOpenLocal,
  $btnOpenNetwork,
  $btnOpenController,
  $btnGenQr,
  $btnCopyPair,
  $btnOpenPair
) | ForEach-Object { Register-LauncherButtonFeedback -Button $_ }
$script:launcherButtons = @(
  $btnStart,
  $btnStop,
  $btnOpenLocal,
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

function Refresh-State {
  if ($script:refreshInProgress -or $script:actionInProgress) { return }
  $script:refreshInProgress = $true
  try {
    $cfg = Get-CachedControllerConfig
    $controllerPort = if ($cfg.port) { [int]$cfg.port } else { 8787 }
    $controllerToken = [string]$cfg.token
    $lanIp = Get-CachedLanIp

    $listening = Get-ListeningStateMap -Ports @($controllerPort, $uiPort)
    $controllerOn = [bool]$listening[[int]$controllerPort]
    $appHealth = if ($controllerOn) { Get-AppHealth -ControllerPort $controllerPort } else { $null }
    $appBuilt = [bool]($appHealth -and $appHealth.ok -and $appHealth.ui_mode -eq "built")
    $appMode = if ($appHealth -and $appHealth.ui_mode) { [string]$appHealth.ui_mode } else { "offline" }
    $status = if ($appBuilt) { "running" } elseif ($controllerOn) { "error" } else { "stopped" }
    $lblStatus.Text = "State: $status`r`nController:$controllerPort  App:$controllerPort  LAN:$lanIp  Mode:$appMode"
    if ($appBuilt) {
      $statusCard.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#0d2f53")
      $lblStatus.ForeColor = $colorAccent
    } elseif ($controllerOn) {
      $statusCard.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#3a1620")
      $lblStatus.ForeColor = $colorDanger
    } else {
      $statusCard.BackColor = $colorSurfaceSoft
      $lblStatus.ForeColor = $colorText
    }

    $busy = $script:actionInProgress
    $btnStop.Enabled = (-not $busy) -and $controllerOn
    $btnStart.Enabled = (-not $busy) -and (-not $appBuilt)
    $btnOpenLocal.Enabled = (-not $busy) -and $controllerOn
    $btnOpenNetwork.Enabled = (-not $busy) -and $controllerOn -and ($lanIp -ne "127.0.0.1")
    $btnOpenController.Enabled = (-not $busy) -and $controllerOn
    $btnGenQr.Enabled = (-not $busy) -and $appBuilt
    $hasPair = [bool]$pairUrl
    $btnCopyPair.Enabled = (-not $busy) -and $hasPair
    $btnOpenPair.Enabled = (-not $busy) -and $hasPair
  } finally {
    $script:refreshInProgress = $false
  }
}

function Start-Stack {
  if (-not (Test-Path $startMobileScript)) {
    throw "Missing $startMobileScript"
  }
  $cfg = Get-CachedControllerConfig
  $controllerPort = if ($cfg.port) { [int]$cfg.port } else { 8787 }
  Append-Log "Starting mobile stack..."
  # Request firewall rules on start so LAN pairing/open-app links are reachable from Android.
  $p = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File",$startMobileScript,"-UiPort",[string]$uiPort,"-OpenFirewall") -WorkingDirectory $root -WindowStyle Hidden -PassThru
  $appReady = $false
  $appHealth = $null
  for ($i = 0; $i -lt 70; $i++) {
    Start-Sleep -Milliseconds 250
    [System.Windows.Forms.Application]::DoEvents()
    $listening = Get-ListeningStateMap -Ports @($controllerPort)
    $okController = [bool]$listening[[int]$controllerPort]
    if ($okController) {
      $appHealth = Get-AppHealth -ControllerPort $controllerPort
      if ($appHealth -and $appHealth.ok -and $appHealth.ui_mode -eq "built") {
        $appReady = $true
        break
      }
    }
    if ($p.HasExited -and $p.ExitCode -ne 0) { break }
  }
  # Force refresh of cached network/config for next paint.
  $script:cachedControllerConfigAt = [DateTime]::MinValue
  $script:cachedLanIpAt = [DateTime]::MinValue
  Refresh-State
  if (-not $appReady) {
    $detail = if ($appHealth -and $appHealth.detail) { [string]$appHealth.detail } else { "Run Setup.cmd if this is a fresh checkout. Use Open Fallback for the legacy controller." }
    throw "Codrex app did not reach running state. $detail"
  }
  Open-Url ("http://127.0.0.1:{0}/" -f $controllerPort)
  Append-Log "Start complete."
}

function Stop-Stack {
  if (-not (Test-Path $stopMobileScript)) {
    throw "Missing $stopMobileScript"
  }
  $cfg = Get-CachedControllerConfig
  $controllerPort = if ($cfg.port) { [int]$cfg.port } else { 8787 }
  Append-Log "Stopping mobile stack..."
  Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File",$stopMobileScript,"-UiPort",[string]$uiPort) -WorkingDirectory $root -WindowStyle Hidden | Out-Null
  for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Milliseconds 250
    [System.Windows.Forms.Application]::DoEvents()
    $listening = Get-ListeningStateMap -Ports @($controllerPort, $uiPort)
    $okController = [bool]$listening[[int]$controllerPort]
    $okUi = [bool]$listening[[int]$uiPort]
    if ((-not $okController) -and (-not $okUi)) { break }
  }
  $script:cachedControllerConfigAt = [DateTime]::MinValue
  $script:cachedLanIpAt = [DateTime]::MinValue
  Refresh-State
  Append-Log "Stop complete."
}

function Generate-PairQr {
  $cfg = Get-CachedControllerConfig
  $controllerPort = if ($cfg.port) { [int]$cfg.port } else { 8787 }
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
  $pairUrl = "$base/auth/pair/consume?code=$([Uri]::EscapeDataString([string]$create.code))"
  $txtPair.Text = $pairUrl

  $qrEndpoint = "http://127.0.0.1:$controllerPort/auth/pair/qr.png?data=$([Uri]::EscapeDataString($pairUrl))&ts=$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
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

$btnStart.Add_Click({ Safe-Action -Action { Start-Stack } -Button $btnStart })
$btnStop.Add_Click({ Safe-Action -Action { Stop-Stack } -Button $btnStop })
$btnOpenLocal.Add_Click({
  $cfg = Get-CachedControllerConfig
  $port = if ($cfg.port) { [int]$cfg.port } else { 8787 }
  Open-Url ("http://127.0.0.1:{0}/" -f $port)
})
$btnOpenNetwork.Add_Click({
  $cfg = Get-CachedControllerConfig
  $port = if ($cfg.port) { [int]$cfg.port } else { 8787 }
  $ip = Get-CachedLanIp
  Open-Url ("http://{0}:{1}/" -f $ip, $port)
})
$btnOpenController.Add_Click({
  $cfg = Get-CachedControllerConfig
  $port = if ($cfg.port) { [int]$cfg.port } else { 8787 }
  Open-Url ("http://127.0.0.1:{0}/legacy" -f $port)
})
$btnGenQr.Add_Click({ Safe-Action -Action { Generate-PairQr } -Button $btnGenQr })
$btnCopyPair.Add_Click({
  if ($pairUrl) {
    try { [System.Windows.Forms.Clipboard]::SetText($pairUrl) } catch {}
    Append-Log "Pair link copied to clipboard."
  }
})
$btnOpenPair.Add_Click({
  if ($pairUrl) {
    Open-Url $pairUrl
    Append-Log "Opened pair link."
  }
})

$form.Add_Shown({
  Set-SplitLayout
})

$script:refreshTimer = New-Object System.Windows.Forms.Timer
$script:refreshTimer.Interval = 2000
$script:refreshTimer.Add_Tick({ Refresh-State })
$script:refreshTimer.Start()

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
