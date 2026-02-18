Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Coalesce-Value($Value, $Default) {
  if ($null -eq $Value) { return $Default }
  if ($Value -is [string] -and $Value.Trim() -eq "") { return $Default }
  return $Value
}

function Read-ControllerConfig([string]$Root) {
  $path = Join-Path $Root "controller.config.json"
  if (-not (Test-Path $path)) {
    return [pscustomobject]@{
      port = 8787
      token = ""
    }
  }
  try {
    $raw = Get-Content -Path $path -Raw
    if (-not $raw.Trim()) { throw "Empty config" }
    $cfg = $raw | ConvertFrom-Json
    return $cfg
  } catch {
    return [pscustomobject]@{
      port = 8787
      token = ""
    }
  }
}

function Get-LanIPv4 {
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
    if ($line -match ":\s*([0-9\\.]+)\s*$") { return [string]$matches[1] }
  } catch {}
  return ""
}

function Get-TailscaleIPv4 {
  $pf = $env:ProgramFiles
  $pf86 = ${env:ProgramFiles(x86)}
  $candidates = @()
  if ($pf) { $candidates += (Join-Path $pf "Tailscale\\tailscale.exe") }
  if ($pf86) { $candidates += (Join-Path $pf86 "Tailscale\\tailscale.exe") }
  $exe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
  if (-not $exe) {
    try {
      $exe = (Get-Command tailscale.exe -ErrorAction Stop).Source
    } catch {
      return ""
    }
  }
  try {
    $out = & $exe ip -4 2>$null
    $ip = ($out | Select-Object -First 1).Trim()
    if ($ip -match "^\\d+\\.\\d+\\.\\d+\\.\\d+$") { return $ip }
  } catch {}
  return ""
}

function Normalize-BaseUrl([string]$Raw) {
  $base = $Raw
  if ($null -eq $base) { $base = "" }
  $base = $base.Trim()
  if (-not $base) { return "" }
  if ($base -notmatch "^https?://") { $base = "http://$base" }
  $base = $base.TrimEnd("/")
  return $base
}

function Invoke-Json([string]$Url, [string]$Method, [object]$BodyObj, [string]$Token) {
  $headers = @{}
  if ($Token) { $headers["x-auth-token"] = $Token }
  $body = $null
  if ($null -ne $BodyObj) {
    $body = ($BodyObj | ConvertTo-Json -Depth 6)
    $headers["Content-Type"] = "application/json"
  }
  try {
    return Invoke-RestMethod -Uri $Url -Method $Method -Headers $headers -Body $body -TimeoutSec 3
  } catch {
    return $null
  }
}

function Get-QrPngImage([string]$Url, [string]$Token) {
  $headers = @{}
  if ($Token) { $headers["x-auth-token"] = $Token }
  try {
    $resp = Invoke-WebRequest -Uri $Url -Headers $headers -TimeoutSec 6 -UseBasicParsing
    if (-not $resp -or -not $resp.Content) { return $null }
    $ms = New-Object System.IO.MemoryStream
    $ms.Write($resp.Content, 0, $resp.Content.Length) | Out-Null
    $ms.Position = 0
    return [System.Drawing.Image]::FromStream($ms)
  } catch {
    return $null
  }
}

function Open-Url([string]$Url) {
  if (-not $Url) { return }
  try {
    Start-Process $Url | Out-Null
  } catch {}
}

function Color-Html([string]$Hex) {
  return [System.Drawing.ColorTranslator]::FromHtml($Hex)
}

$script:Theme = @{
  Bg = Color-Html "#EDF3FA"
  Panel = Color-Html "#FFFFFF"
  Border = Color-Html "#D7E2EE"
  Text = Color-Html "#0F172A"
  Muted = Color-Html "#5B6473"
  Primary = Color-Html "#0F766E"
  PrimaryBorder = Color-Html "#0B5E57"
  Danger = Color-Html "#B91C1C"
  DangerBorder = Color-Html "#991B1B"
  Neutral = Color-Html "#F8FAFC"
  NeutralBorder = Color-Html "#CBD5E1"
  SuccessBg = Color-Html "#DCFCE7"
  SuccessText = Color-Html "#166534"
  WarnBg = Color-Html "#FEF3C7"
  WarnText = Color-Html "#92400E"
  ErrorBg = Color-Html "#FEE2E2"
  ErrorText = Color-Html "#B91C1C"
}

function Style-Group([System.Windows.Forms.GroupBox]$Box) {
  if ($null -eq $Box) { return }
  $Box.BackColor = $script:Theme.Panel
  $Box.ForeColor = $script:Theme.Text
  $Box.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 9)
  $Box.Padding = New-Object System.Windows.Forms.Padding(8)
}

function Style-Input([System.Windows.Forms.Control]$Ctrl) {
  if ($null -eq $Ctrl) { return }
  $Ctrl.BackColor = [System.Drawing.Color]::White
  $Ctrl.ForeColor = $script:Theme.Text
  if ($Ctrl -is [System.Windows.Forms.TextBox]) {
    $Ctrl.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
    if (-not $Ctrl.Font) {
      $Ctrl.Font = New-Object System.Drawing.Font("Consolas", 9)
    }
  }
}

function Style-Button([System.Windows.Forms.Button]$Btn, [string]$Kind = "neutral") {
  if ($null -eq $Btn) { return }
  $Btn.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
  $Btn.FlatAppearance.BorderSize = 1
  $Btn.FlatAppearance.MouseOverBackColor = Color-Html "#EEF2F7"
  $Btn.FlatAppearance.MouseDownBackColor = Color-Html "#E2E8F0"
  $Btn.ForeColor = $script:Theme.Text
  switch ($Kind) {
    "primary" {
      $Btn.BackColor = $script:Theme.Primary
      $Btn.FlatAppearance.BorderColor = $script:Theme.PrimaryBorder
      $Btn.ForeColor = [System.Drawing.Color]::White
      $Btn.FlatAppearance.MouseOverBackColor = Color-Html "#0E9186"
      $Btn.FlatAppearance.MouseDownBackColor = Color-Html "#0B5E57"
      break
    }
    "danger" {
      $Btn.BackColor = $script:Theme.Danger
      $Btn.FlatAppearance.BorderColor = $script:Theme.DangerBorder
      $Btn.ForeColor = [System.Drawing.Color]::White
      $Btn.FlatAppearance.MouseOverBackColor = Color-Html "#DC2626"
      $Btn.FlatAppearance.MouseDownBackColor = Color-Html "#991B1B"
      break
    }
    default {
      $Btn.BackColor = $script:Theme.Neutral
      $Btn.FlatAppearance.BorderColor = $script:Theme.NeutralBorder
      $Btn.ForeColor = $script:Theme.Text
      break
    }
  }
}

function Set-StatusBadge([System.Windows.Forms.Label]$Label, [string]$State, [string]$Text) {
  if ($null -eq $Label) { return }
  $Label.AutoSize = $false
  $Label.Text = $Text
  $Label.Padding = New-Object System.Windows.Forms.Padding(8, 2, 8, 2)
  $Label.AutoEllipsis = $true
  switch ($State) {
    "on" {
      $Label.BackColor = $script:Theme.SuccessBg
      $Label.ForeColor = $script:Theme.SuccessText
      break
    }
    "warn" {
      $Label.BackColor = $script:Theme.WarnBg
      $Label.ForeColor = $script:Theme.WarnText
      break
    }
    "off" {
      $Label.BackColor = $script:Theme.ErrorBg
      $Label.ForeColor = $script:Theme.ErrorText
      break
    }
    default {
      $Label.BackColor = $script:Theme.Neutral
      $Label.ForeColor = $script:Theme.Text
      break
    }
  }
}

function Get-BaseRouteKind([string]$Base, [string]$LanUrl, [string]$TsUrl) {
  $b = Normalize-BaseUrl $Base
  if (-not $b) { return "unknown" }
  try {
    $host = ([Uri]$b).Host.ToLowerInvariant()
  } catch {
    return "unknown"
  }
  if ($host -eq "localhost" -or $host -eq "127.0.0.1") { return "local" }
  if ($TsUrl) {
    try {
      $tsHost = ([Uri]$TsUrl).Host.ToLowerInvariant()
      if ($host -eq $tsHost) { return "tailscale" }
    } catch {}
  }
  if ($LanUrl) {
    try {
      $lanHost = ([Uri]$LanUrl).Host.ToLowerInvariant()
      if ($host -eq $lanHost) { return "lan" }
    } catch {}
  }
  if ($host -like "100.*" -or $host -like "*.ts.net") { return "tailscale" }
  if ($host -like "192.168.*" -or $host -like "10.*" -or $host -match "^172\.(1[6-9]|2\d|3[01])\.") {
    return "lan"
  }
  return "unknown"
}

$root = Split-Path -Parent $PSCommandPath
$cfg = Read-ControllerConfig -Root $root
$port = [int](Coalesce-Value $cfg.port 8787)
$token = [string](Coalesce-Value $cfg.token "")

$form = New-Object System.Windows.Forms.Form
$form.Text = "Codrex Remote Controller Launcher"
$form.StartPosition = "CenterScreen"
$form.Size = New-Object System.Drawing.Size(940, 600)
$form.MinimumSize = New-Object System.Drawing.Size(760, 500)
$form.BackColor = $script:Theme.Bg
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
try {
  $form.GetType().GetProperty("DoubleBuffered", [System.Reflection.BindingFlags]"NonPublic,Instance").SetValue($form, $true, $null)
} catch {}

$script:IsControllerRunning = $false
$script:QrExpiresAt = $null

$fontMono = New-Object System.Drawing.Font("Consolas", 9)

$panel = New-Object System.Windows.Forms.TableLayoutPanel
$panel.Dock = "Fill"
$panel.Padding = New-Object System.Windows.Forms.Padding(14)
$panel.BackColor = $script:Theme.Bg
$panel.ColumnCount = 2
$panel.RowCount = 1
$panel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 56)))
$panel.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 44)))
$form.Controls.Add($panel)

$leftHost = New-Object System.Windows.Forms.Panel
$leftHost.Dock = "Fill"
$leftHost.AutoScroll = $true
$leftHost.BackColor = $script:Theme.Bg
$leftHost.Padding = New-Object System.Windows.Forms.Padding(0, 0, 8, 0)
$panel.Controls.Add($leftHost, 0, 0)

$rightHost = New-Object System.Windows.Forms.Panel
$rightHost.Dock = "Fill"
$rightHost.AutoScroll = $true
$rightHost.BackColor = $script:Theme.Bg
$rightHost.Padding = New-Object System.Windows.Forms.Padding(8, 0, 0, 0)
$panel.Controls.Add($rightHost, 1, 0)

# Left column: server + links + token
$left = New-Object System.Windows.Forms.TableLayoutPanel
$left.Dock = "Top"
$left.AutoSize = $true
$left.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink
$left.RowCount = 6
$left.ColumnCount = 1
$left.Padding = New-Object System.Windows.Forms.Padding(0)
$left.BackColor = $script:Theme.Bg
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 220)))
$left.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 34)))
$leftHost.Controls.Add($left)

$statusBox = New-Object System.Windows.Forms.GroupBox
$statusBox.Text = "Server"
$statusBox.Dock = "Fill"
$left.Controls.Add($statusBox, 0, 0)

$statusLayout = New-Object System.Windows.Forms.TableLayoutPanel
$statusLayout.Dock = "Fill"
$statusLayout.ColumnCount = 2
$statusLayout.RowCount = 3
$statusLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 70)))
$statusLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 30)))
$statusLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$statusLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$statusLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$statusBox.Controls.Add($statusLayout)

$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = "Controller: checking"
$lblStatus.Dock = "Fill"
$lblStatus.TextAlign = "MiddleLeft"
$statusLayout.Controls.Add($lblStatus, 0, 0)

$btnRefresh = New-Object System.Windows.Forms.Button
$btnRefresh.Text = "Refresh"
$btnRefresh.Dock = "Fill"
$btnRefresh.MinimumSize = New-Object System.Drawing.Size(90, 30)
$statusLayout.Controls.Add($btnRefresh, 1, 0)

$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = "Turn On"
$btnStart.Dock = "Fill"
$btnStart.MinimumSize = New-Object System.Drawing.Size(90, 32)
$statusLayout.Controls.Add($btnStart, 0, 1)

$btnStop = New-Object System.Windows.Forms.Button
$btnStop.Text = "Turn Off"
$btnStop.Dock = "Fill"
$btnStop.MinimumSize = New-Object System.Drawing.Size(90, 32)
$statusLayout.Controls.Add($btnStop, 1, 1)

$chkFirewall = New-Object System.Windows.Forms.CheckBox
$chkFirewall.Text = "Open Windows Firewall rule (port)"
$chkFirewall.Dock = "Fill"
$chkFirewall.Checked = $false
$statusLayout.Controls.Add($chkFirewall, 0, 2)
$statusLayout.SetColumnSpan($chkFirewall, 2)

$linksBox = New-Object System.Windows.Forms.GroupBox
$linksBox.Text = "Open Controller"
$linksBox.Dock = "Fill"
$left.Controls.Add($linksBox, 0, 1)

$linksLayout = New-Object System.Windows.Forms.TableLayoutPanel
$linksLayout.Dock = "Fill"
$linksLayout.ColumnCount = 1
$linksLayout.RowCount = 2
$linksLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$linksLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$linksBox.Controls.Add($linksLayout)

$linksRow = New-Object System.Windows.Forms.FlowLayoutPanel
$linksRow.Dock = "Fill"
$linksRow.WrapContents = $true
$linksRow.AutoScroll = $false
$linksRow.AutoSize = $true
$linksRow.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink
$linksLayout.Controls.Add($linksRow, 0, 0)

$btnOpenLocal = New-Object System.Windows.Forms.Button
$btnOpenLocal.Text = "Open Local"
$linksRow.Controls.Add($btnOpenLocal)

$btnOpenLan = New-Object System.Windows.Forms.Button
$btnOpenLan.Text = "Open LAN"
$linksRow.Controls.Add($btnOpenLan)

$btnOpenTailscale = New-Object System.Windows.Forms.Button
$btnOpenTailscale.Text = "Open Tailscale"
$linksRow.Controls.Add($btnOpenTailscale)

$lblNetSummary = New-Object System.Windows.Forms.Label
$lblNetSummary.Text = "LAN: -- | Tailscale: --"
$lblNetSummary.Dock = "Fill"
$lblNetSummary.TextAlign = "MiddleLeft"
$lblNetSummary.AutoEllipsis = $true
$linksLayout.Controls.Add($lblNetSummary, 0, 1)

$tokenBox = New-Object System.Windows.Forms.GroupBox
$tokenBox.Text = "Access Token"
$tokenBox.Dock = "Fill"
$left.Controls.Add($tokenBox, 0, 2)

$tokenLayout = New-Object System.Windows.Forms.TableLayoutPanel
$tokenLayout.Dock = "Fill"
$tokenLayout.ColumnCount = 3
$tokenLayout.RowCount = 1
$tokenLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 70)))
$tokenLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 15)))
$tokenLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 15)))
$tokenLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
$tokenBox.Controls.Add($tokenLayout)

$txtToken = New-Object System.Windows.Forms.TextBox
$txtToken.Dock = "Fill"
$txtToken.ReadOnly = $true
$txtToken.UseSystemPasswordChar = $true
$txtToken.Font = $fontMono
$tokenLayout.Controls.Add($txtToken, 0, 0)

$btnReveal = New-Object System.Windows.Forms.Button
$btnReveal.Text = "Reveal"
$btnReveal.Dock = "Fill"
$tokenLayout.Controls.Add($btnReveal, 1, 0)

$btnCopyToken = New-Object System.Windows.Forms.Button
$btnCopyToken.Text = "Copy"
$btnCopyToken.Dock = "Fill"
$tokenLayout.Controls.Add($btnCopyToken, 2, 0)

$pairBox = New-Object System.Windows.Forms.GroupBox
$pairBox.Text = "Pair Phone (QR)"
$pairBox.Dock = "Fill"
$pairBox.MinimumSize = New-Object System.Drawing.Size(0, 148)
$left.Controls.Add($pairBox, 0, 3)

$pairLayout = New-Object System.Windows.Forms.TableLayoutPanel
$pairLayout.Dock = "Fill"
$pairLayout.Padding = New-Object System.Windows.Forms.Padding(0)
$pairLayout.ColumnCount = 3
$pairLayout.RowCount = 4
$pairLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 50)))
$pairLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 25)))
$pairLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 25)))
$pairLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 24)))
$pairLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 32)))
$pairLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 42)))
$pairLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 24)))
$pairBox.Controls.Add($pairLayout)

$lblPair = New-Object System.Windows.Forms.Label
$lblPair.Text = "Base URL:"
$lblPair.Dock = "Fill"
$lblPair.TextAlign = "MiddleLeft"
$pairLayout.Controls.Add($lblPair, 0, 0)

$txtBase = New-Object System.Windows.Forms.TextBox
$txtBase.Dock = "Fill"
$txtBase.Font = $fontMono
$txtBase.Margin = New-Object System.Windows.Forms.Padding(0, 2, 0, 2)
$pairLayout.Controls.Add($txtBase, 0, 1)
$pairLayout.SetColumnSpan($txtBase, 3)

$btnUseLan = New-Object System.Windows.Forms.Button
$btnUseLan.Text = "Use LAN"
$btnUseLan.Dock = "Fill"
$btnUseLan.MinimumSize = New-Object System.Drawing.Size(90, 32)
$btnUseLan.Margin = New-Object System.Windows.Forms.Padding(0, 4, 4, 2)
$pairLayout.Controls.Add($btnUseLan, 0, 2)

$btnUseTs = New-Object System.Windows.Forms.Button
$btnUseTs.Text = "Use Tailscale"
$btnUseTs.Dock = "Fill"
$btnUseTs.MinimumSize = New-Object System.Drawing.Size(90, 32)
$btnUseTs.Margin = New-Object System.Windows.Forms.Padding(2, 4, 2, 2)
$pairLayout.Controls.Add($btnUseTs, 1, 2)

$btnGenQr = New-Object System.Windows.Forms.Button
$btnGenQr.Text = "Generate QR"
$btnGenQr.Dock = "Fill"
$btnGenQr.MinimumSize = New-Object System.Drawing.Size(110, 32)
$btnGenQr.Margin = New-Object System.Windows.Forms.Padding(4, 4, 0, 2)
$pairLayout.Controls.Add($btnGenQr, 2, 2)

$lblBaseRoute = New-Object System.Windows.Forms.Label
$lblBaseRoute.Text = "Route: unknown"
$lblBaseRoute.Dock = "Fill"
$lblBaseRoute.TextAlign = "MiddleLeft"
$lblBaseRoute.Margin = New-Object System.Windows.Forms.Padding(0, 2, 0, 0)
$pairLayout.Controls.Add($lblBaseRoute, 0, 3)
$pairLayout.SetColumnSpan($lblBaseRoute, 3)

$pairOutBox = New-Object System.Windows.Forms.GroupBox
$pairOutBox.Text = "Pairing Link"
$pairOutBox.Dock = "Fill"
$left.Controls.Add($pairOutBox, 0, 4)

$pairOutLayout = New-Object System.Windows.Forms.TableLayoutPanel
$pairOutLayout.Dock = "Fill"
$pairOutLayout.ColumnCount = 2
$pairOutLayout.RowCount = 2
$pairOutLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 80)))
$pairOutLayout.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 20)))
$pairOutLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 30)))
$pairOutLayout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
$pairOutBox.Controls.Add($pairOutLayout)

$txtPairLink = New-Object System.Windows.Forms.TextBox
$txtPairLink.Dock = "Fill"
$txtPairLink.ReadOnly = $true
$txtPairLink.Font = $fontMono
$pairOutLayout.Controls.Add($txtPairLink, 0, 0)

$btnCopyLink = New-Object System.Windows.Forms.Button
$btnCopyLink.Text = "Copy Link"
$btnCopyLink.Dock = "Fill"
$pairOutLayout.Controls.Add($btnCopyLink, 1, 0)

$lblPairStatus = New-Object System.Windows.Forms.Label
$lblPairStatus.Text = "Tip: start server, choose base URL, then Generate QR."
$lblPairStatus.Dock = "Fill"
$lblPairStatus.TextAlign = "TopLeft"
$pairOutLayout.Controls.Add($lblPairStatus, 0, 1)
$pairOutLayout.SetColumnSpan($lblPairStatus, 2)

$footer = New-Object System.Windows.Forms.Label
$footer.Text = "Launcher reads controller.config.json for port/token and route defaults."
$footer.Dock = "Fill"
$footer.TextAlign = "MiddleLeft"
$left.Controls.Add($footer, 0, 5)

# Right column: QR image
$right = New-Object System.Windows.Forms.TableLayoutPanel
$right.Dock = "Top"
$right.AutoSize = $true
$right.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink
$right.Padding = New-Object System.Windows.Forms.Padding(0)
$right.BackColor = $script:Theme.Bg
$right.RowCount = 4
$right.ColumnCount = 1
$right.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 26)))
$right.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 460)))
$right.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 24)))
$right.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 24)))
$rightHost.Controls.Add($right)

$lblQrTitle = New-Object System.Windows.Forms.Label
$lblQrTitle.Text = "QR Code"
$lblQrTitle.Dock = "Fill"
$lblQrTitle.TextAlign = "MiddleLeft"
$right.Controls.Add($lblQrTitle, 0, 0)

$picQr = New-Object System.Windows.Forms.PictureBox
$picQr.Dock = "Fill"
$picQr.SizeMode = "Zoom"
$picQr.BorderStyle = "FixedSingle"
$right.Controls.Add($picQr, 0, 1)

$lblQrInfo = New-Object System.Windows.Forms.Label
$lblQrInfo.Text = "Scan with phone camera (code expires quickly)."
$lblQrInfo.Dock = "Fill"
$lblQrInfo.TextAlign = "MiddleLeft"
$right.Controls.Add($lblQrInfo, 0, 2)

$lblQrCountdown = New-Object System.Windows.Forms.Label
$lblQrCountdown.Text = "Expires in: --"
$lblQrCountdown.Dock = "Fill"
$lblQrCountdown.TextAlign = "MiddleLeft"
$right.Controls.Add($lblQrCountdown, 0, 3)

$toastLabel = New-Object System.Windows.Forms.Label
$toastLabel.Visible = $false
$toastLabel.AutoSize = $true
$toastLabel.MaximumSize = New-Object System.Drawing.Size(380, 0)
$toastLabel.Padding = New-Object System.Windows.Forms.Padding(12, 8, 12, 8)
$toastLabel.BackColor = $script:Theme.SuccessBg
$toastLabel.ForeColor = $script:Theme.SuccessText
$toastLabel.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$toastLabel.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 9)
$toastLabel.Anchor = [System.Windows.Forms.AnchorStyles]"Top,Right"
$toastLabel.Location = New-Object System.Drawing.Point(640, 16)
$form.Controls.Add($toastLabel)
$toastLabel.BringToFront()

$toastTimer = New-Object System.Windows.Forms.Timer
$toastTimer.Interval = 1700
$toastTimer.Add_Tick({
  $toastTimer.Stop()
  $toastLabel.Visible = $false
})

$copyLinkTimer = New-Object System.Windows.Forms.Timer
$copyLinkTimer.Interval = 1500
$copyLinkTimer.Add_Tick({
  $copyLinkTimer.Stop()
  $btnCopyLink.Text = "Copy Link"
  Update-ActionAvailability
})

function Apply-UiTheme {
  Style-Group $statusBox
  Style-Group $linksBox
  Style-Group $tokenBox
  Style-Group $pairBox
  Style-Group $pairOutBox

  Style-Input $txtToken
  Style-Input $txtBase
  Style-Input $txtPairLink

  Style-Button $btnStart "primary"
  Style-Button $btnStop "danger"
  Style-Button $btnRefresh "neutral"
  Style-Button $btnOpenLocal "neutral"
  Style-Button $btnOpenLan "neutral"
  Style-Button $btnOpenTailscale "neutral"
  Style-Button $btnReveal "neutral"
  Style-Button $btnCopyToken "neutral"
  Style-Button $btnUseLan "neutral"
  Style-Button $btnUseTs "neutral"
  Style-Button $btnGenQr "primary"
  Style-Button $btnCopyLink "neutral"

  foreach ($btn in @($btnOpenLocal, $btnOpenLan, $btnOpenTailscale)) {
    $btn.AutoSize = $true
    $btn.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink
    $btn.Margin = New-Object System.Windows.Forms.Padding(0, 0, 8, 6)
    $btn.Padding = New-Object System.Windows.Forms.Padding(10, 3, 10, 3)
  }

  foreach ($lbl in @($lblPairStatus, $lblQrInfo, $footer, $lblNetSummary, $lblBaseRoute)) {
    $lbl.ForeColor = $script:Theme.Muted
  }
  $lblQrCountdown.ForeColor = $script:Theme.Muted
  $lblQrTitle.ForeColor = $script:Theme.Text
  $lblQrTitle.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 10)
  $panel.CellBorderStyle = [System.Windows.Forms.TableLayoutPanelCellBorderStyle]::None

  $chkFirewall.ForeColor = $script:Theme.Muted
  $picQr.BackColor = [System.Drawing.Color]::White
  Set-StatusBadge -Label $lblStatus -State "neutral" -Text "Controller: checking"
}

function Show-Toast([string]$Message, [string]$Kind = "ok") {
  if (-not $Message) { return }
  $toastLabel.Text = $Message
  switch ($Kind) {
    "warn" {
      $toastLabel.BackColor = $script:Theme.WarnBg
      $toastLabel.ForeColor = $script:Theme.WarnText
      break
    }
    "error" {
      $toastLabel.BackColor = $script:Theme.ErrorBg
      $toastLabel.ForeColor = $script:Theme.ErrorText
      break
    }
    default {
      $toastLabel.BackColor = $script:Theme.SuccessBg
      $toastLabel.ForeColor = $script:Theme.SuccessText
      break
    }
  }
  $margin = 24
  $x = [Math]::Max(16, $form.ClientSize.Width - $toastLabel.PreferredSize.Width - $margin)
  $toastLabel.Location = New-Object System.Drawing.Point($x, 16)
  $toastLabel.Visible = $true
  $toastLabel.BringToFront()
  $toastTimer.Stop()
  $toastTimer.Start()
}

function Update-QrCountdown {
  if ($null -eq $script:QrExpiresAt) {
    $lblQrCountdown.Text = "Expires in: --"
    $lblQrCountdown.ForeColor = $script:Theme.Muted
    return
  }
  $remaining = [int][Math]::Floor(($script:QrExpiresAt - [DateTimeOffset]::UtcNow).TotalSeconds)
  if ($remaining -le 0) {
    $lblQrCountdown.Text = "Expires in: 0s (expired)"
    $lblQrCountdown.ForeColor = $script:Theme.ErrorText
    return
  }
  $lblQrCountdown.Text = "Expires in: ${remaining}s"
  if ($remaining -le 15) {
    $lblQrCountdown.ForeColor = $script:Theme.WarnText
  } else {
    $lblQrCountdown.ForeColor = $script:Theme.Muted
  }
}

$qrCountdownTimer = New-Object System.Windows.Forms.Timer
$qrCountdownTimer.Interval = 1000
$qrCountdownTimer.Add_Tick({
  Update-QrCountdown
})

function Update-ActionAvailability {
  $baseOk = [bool](Normalize-BaseUrl $txtBase.Text)
  $canGenerate = $script:IsControllerRunning -and $baseOk
  $btnGenQr.Enabled = $canGenerate
  if ($canGenerate) {
    Style-Button $btnGenQr "primary"
  } else {
    Style-Button $btnGenQr "neutral"
  }
  $hasLink = [bool]$txtPairLink.Text
  $btnCopyLink.Enabled = $hasLink
  if (-not $hasLink) {
    $copyLinkTimer.Stop()
    $btnCopyLink.Text = "Copy Link"
  }
}

function Update-NetworkAndRoute {
  $urls = Base-Urls

  $lanText = "not detected"
  if ($urls.lan) {
    try { $lanText = ([Uri]$urls.lan).Host } catch { $lanText = $urls.lan }
  }
  $tsText = "not detected"
  if ($urls.tailscale) {
    try { $tsText = ([Uri]$urls.tailscale).Host } catch { $tsText = $urls.tailscale }
  }

  $lblNetSummary.Text = "LAN: $lanText | Tailscale: $tsText"
  $btnOpenLan.Enabled = [bool]$urls.lan
  $btnOpenTailscale.Enabled = [bool]$urls.tailscale

  $kind = Get-BaseRouteKind -Base $txtBase.Text -LanUrl $urls.lan -TsUrl $urls.tailscale
  switch ($kind) {
    "tailscale" {
      $lblBaseRoute.Text = "Route: Tailscale (recommended off-campus/college Wi-Fi)"
      $lblBaseRoute.ForeColor = $script:Theme.SuccessText
      break
    }
    "lan" {
      $lblBaseRoute.Text = "Route: LAN (works when phone and laptop share same local network)"
      $lblBaseRoute.ForeColor = $script:Theme.WarnText
      break
    }
    "local" {
      $lblBaseRoute.Text = "Route: Localhost (not reachable from phone)"
      $lblBaseRoute.ForeColor = $script:Theme.ErrorText
      break
    }
    default {
      $lblBaseRoute.Text = "Route: unknown (verify base URL reachability)"
      $lblBaseRoute.ForeColor = $script:Theme.Muted
      break
    }
  }
}

function Base-Urls {
  $cfg = Read-ControllerConfig -Root $root
  $p = [int](Coalesce-Value $cfg.port 8787)
  $lan = Get-LanIPv4
  $ts = Get-TailscaleIPv4
  return [pscustomobject]@{
    port = $p
    lan = ($(if ($lan) { "http://${lan}:$p" } else { "" }))
    tailscale = ($(if ($ts) { "http://${ts}:$p" } else { "" }))
    local = "http://127.0.0.1:$p"
  }
}

function Refresh-UiStatus {
  $cfg = Read-ControllerConfig -Root $root
  $p = [int](Coalesce-Value $cfg.port 8787)
  $t = [string](Coalesce-Value $cfg.token "")
  $txtToken.Text = $t

  Update-NetworkAndRoute

  $local = "http://127.0.0.1:$p/auth/status"
  $j = Invoke-Json -Url $local -Method "GET" -BodyObj $null -Token $t
  if ($null -eq $j) {
    $script:IsControllerRunning = $false
    Set-StatusBadge -Label $lblStatus -State "off" -Text "Controller: OFF (no response on 127.0.0.1:$p)"
    $btnStart.Enabled = $true
    $btnStop.Enabled = $false
    Style-Button $btnStart "primary"
    Style-Button $btnStop "neutral"
    Update-ActionAvailability
    return
  }
  if ($j.ok -and $j.auth_required -and -not $j.authenticated) {
    $script:IsControllerRunning = $true
    Set-StatusBadge -Label $lblStatus -State "warn" -Text "Controller: ON (token mismatch)"
    $btnStart.Enabled = $false
    $btnStop.Enabled = $true
    Style-Button $btnStart "neutral"
    Style-Button $btnStop "danger"
  } else {
    $script:IsControllerRunning = $true
    Set-StatusBadge -Label $lblStatus -State "on" -Text "Controller: ON (port $p)"
    $btnStart.Enabled = $false
    $btnStop.Enabled = $true
    Style-Button $btnStart "neutral"
    Style-Button $btnStop "danger"
  }
  Update-ActionAvailability
}

function Run-Start {
  $script = Join-Path $root "start-controller.ps1"
  if (-not (Test-Path $script)) {
    [System.Windows.Forms.MessageBox]::Show("Missing start-controller.ps1 in $root", "Error") | Out-Null
    return
  }
  Set-StatusBadge -Label $lblStatus -State "warn" -Text "Controller: starting..."
  $script:IsControllerRunning = $false
  $btnStart.Enabled = $false
  $btnStop.Enabled = $false
  Update-ActionAvailability
  $psArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $script
  )
  if ($chkFirewall.Checked) {
    $psArgs += "-OpenFirewall"
  }
  Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $root -WindowStyle Hidden | Out-Null

  # Poll until alive.
  for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Milliseconds 250
    [System.Windows.Forms.Application]::DoEvents()
    $cfg = Read-ControllerConfig -Root $root
    $p = [int](Coalesce-Value $cfg.port 8787)
    $t = [string](Coalesce-Value $cfg.token "")
    $j = Invoke-Json -Url "http://127.0.0.1:$p/auth/status" -Method "GET" -BodyObj $null -Token $t
    if ($j -and $j.ok) { break }
  }
  Refresh-UiStatus
}

function Run-Stop {
  $script = Join-Path $root "stop-controller.ps1"
  if (-not (Test-Path $script)) {
    [System.Windows.Forms.MessageBox]::Show("Missing stop-controller.ps1 in $root", "Error") | Out-Null
    return
  }
  Set-StatusBadge -Label $lblStatus -State "warn" -Text "Controller: stopping..."
  $script:IsControllerRunning = $false
  $btnStart.Enabled = $false
  $btnStop.Enabled = $false
  Update-ActionAvailability
  Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $script
  ) -WorkingDirectory $root -WindowStyle Hidden | Out-Null

  # Poll until down.
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 250
    [System.Windows.Forms.Application]::DoEvents()
    $cfg = Read-ControllerConfig -Root $root
    $p = [int](Coalesce-Value $cfg.port 8787)
    $t = [string](Coalesce-Value $cfg.token "")
    $j = Invoke-Json -Url "http://127.0.0.1:$p/auth/status" -Method "GET" -BodyObj $null -Token $t
    if ($null -eq $j) { break }
  }
  Refresh-UiStatus
}

function Ensure-BaseUrl {
  $b = Normalize-BaseUrl $txtBase.Text
  if (-not $b) {
    $urls = Base-Urls
    if ($urls.tailscale) { $b = $urls.tailscale }
    elseif ($urls.lan) { $b = $urls.lan }
    else { $b = $urls.local }
    $txtBase.Text = $b
  }
  Update-NetworkAndRoute
  return $b
}

function Generate-Qr {
  $cfg = Read-ControllerConfig -Root $root
  $p = [int](Coalesce-Value $cfg.port 8787)
  $t = [string](Coalesce-Value $cfg.token "")

  $base = Ensure-BaseUrl
  if (-not $base) { return }
  $copyLinkTimer.Stop()
  $btnCopyLink.Text = "Copy Link"
  if (-not $script:IsControllerRunning) {
    $lblPairStatus.Text = "Controller is off. Turn it on before generating QR."
    $lblPairStatus.ForeColor = $script:Theme.ErrorText
    Show-Toast -Message "Controller is off. Turn it on first." -Kind "warn"
    return
  }

  $lblPairStatus.Text = "Generating pairing code…"
  $lblPairStatus.ForeColor = $script:Theme.WarnText
  [System.Windows.Forms.Application]::DoEvents()

  $create = Invoke-Json -Url "http://127.0.0.1:$p/auth/pair/create" -Method "POST" -BodyObj @{} -Token $t
  if (-not $create -or -not $create.ok) {
    $lblPairStatus.Text = "Failed to create pairing code. Is the server running?"
    $lblPairStatus.ForeColor = $script:Theme.ErrorText
    Show-Toast -Message "Failed to create pairing code." -Kind "error"
    return
  }
  $code = [string](Coalesce-Value $create.code "")
  $expires = [int](Coalesce-Value $create.expires_in 0)
  if (-not $code) {
    $lblPairStatus.Text = "Pairing code missing in response."
    $lblPairStatus.ForeColor = $script:Theme.ErrorText
    Show-Toast -Message "Pairing code missing in response." -Kind "error"
    return
  }

  $pairUrl = "$base/auth/pair/consume?code=$([Uri]::EscapeDataString($code))"
  $txtPairLink.Text = $pairUrl
  $lblPairStatus.Text = "Fetching QR image (expires in ~${expires}s)…"
  $lblPairStatus.ForeColor = $script:Theme.WarnText
  [System.Windows.Forms.Application]::DoEvents()

  $qrEndpoint = "http://127.0.0.1:$p/auth/pair/qr.png?data=$([Uri]::EscapeDataString($pairUrl))&ts=$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
  $img = Get-QrPngImage -Url $qrEndpoint -Token $t
  if ($null -eq $img) {
    $lblPairStatus.Text = "Failed to load QR image. You can still copy the link."
    $lblPairStatus.ForeColor = $script:Theme.ErrorText
    $picQr.Image = $null
    Show-Toast -Message "QR image failed; link is still available." -Kind "warn"
    return
  }
  $picQr.Image = $img
  $lblPairStatus.Text = "QR ready. Scan with phone camera (expires quickly)."
  $lblPairStatus.ForeColor = $script:Theme.SuccessText
  $script:QrExpiresAt = [DateTimeOffset]::UtcNow.AddSeconds([Math]::Max(0, $expires))
  Update-QrCountdown
  $qrCountdownTimer.Start()
  Update-ActionAvailability
  Show-Toast -Message "QR ready. Scan now." -Kind "ok"
}

$btnRefresh.Add_Click({ Refresh-UiStatus })
$btnStart.Add_Click({ Run-Start })
$btnStop.Add_Click({ Run-Stop })
$btnOpenLocal.Add_Click({
  $urls = Base-Urls
  Open-Url $urls.local
})
$btnOpenLan.Add_Click({
  $urls = Base-Urls
  if (-not $urls.lan) { return }
  Open-Url $urls.lan
})
$btnOpenTailscale.Add_Click({
  $urls = Base-Urls
  if (-not $urls.tailscale) { return }
  Open-Url $urls.tailscale
})
$btnCopyToken.Add_Click({
  if ($txtToken.Text) {
    [System.Windows.Forms.Clipboard]::SetText($txtToken.Text)
    Show-Toast -Message "Access token copied." -Kind "ok"
  }
})
$btnReveal.Add_Click({
  $txtToken.UseSystemPasswordChar = -not $txtToken.UseSystemPasswordChar
  $btnReveal.Text = $(if ($txtToken.UseSystemPasswordChar) { "Reveal" } else { "Hide" })
})
$btnUseLan.Add_Click({
  $urls = Base-Urls
  if ($urls.lan) { $txtBase.Text = $urls.lan }
  Update-NetworkAndRoute
})
$btnUseTs.Add_Click({
  $urls = Base-Urls
  if ($urls.tailscale) { $txtBase.Text = $urls.tailscale }
  Update-NetworkAndRoute
})
$btnGenQr.Add_Click({ Generate-Qr })
$btnCopyLink.Add_Click({
  if ($txtPairLink.Text) {
    [System.Windows.Forms.Clipboard]::SetText($txtPairLink.Text)
    $btnCopyLink.Text = "Copied [OK]"
    $copyLinkTimer.Stop()
    $copyLinkTimer.Start()
    Show-Toast -Message "Pair link copied." -Kind "ok"
  } else {
    Show-Toast -Message "No pair link to copy yet." -Kind "warn"
  }
})

$txtBase.Add_TextChanged({ Update-NetworkAndRoute })
$txtBase.Add_TextChanged({ Update-ActionAvailability })
$txtPairLink.Add_TextChanged({ Update-ActionAvailability })

# Initial base URL preference: Tailscale if available, else LAN, else local.
$initial = Base-Urls
if ($initial.tailscale) { $txtBase.Text = $initial.tailscale }
elseif ($initial.lan) { $txtBase.Text = $initial.lan }
else { $txtBase.Text = $initial.local }

Apply-UiTheme
Update-ActionAvailability
Update-QrCountdown
Refresh-UiStatus

[void]$form.Add_Resize({
  try {
    if ($toastLabel.Visible) {
      $margin = 24
      $x = [Math]::Max(16, $form.ClientSize.Width - $toastLabel.Width - $margin)
      $toastLabel.Location = New-Object System.Drawing.Point($x, 16)
    }
  } catch {}
})

[void]$form.ShowDialog()
