Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Codrex.MobileTray.Singleton", [ref]$createdNew)
if (-not $createdNew) {
  [System.Windows.Forms.MessageBox]::Show(
    "Codrex Mobile Tray is already running.",
    "Codrex",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
  ) | Out-Null
  exit 0
}

$script:Root = Split-Path -Parent $PSCommandPath
$script:LogsDir = Join-Path $script:Root "logs"
$script:StartScript = Join-Path $script:Root "start-mobile.ps1"
$script:StopScript = Join-Path $script:Root "stop-mobile.ps1"
$script:ConfigPath = Join-Path $script:Root "controller.config.json"
$script:UiPort = 4312
$script:PendingAction = ""
$script:PendingProc = $null
$script:BalloonQueue = @()
$script:LastStatus = $null

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

function Read-ControllerConfig {
  if (-not (Test-Path $script:ConfigPath)) {
    return [pscustomobject]@{
      port = 8787
      token = ""
    }
  }
  try {
    $cfg = Get-Content -Path $script:ConfigPath -Raw | ConvertFrom-Json
    if ($cfg) { return $cfg }
  } catch {}
  return [pscustomobject]@{
    port = 8787
    token = ""
  }
}

function Read-ControllerPort {
  $cfg = Read-ControllerConfig
  if ($cfg -and $cfg.port) { return [int]$cfg.port }
  return 8787
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
    if ($ip -match "^\d+\.\d+\.\d+\.\d+$") {
      return $ip
    }
  } catch {}
  return ""
}

function Invoke-Json {
  param(
    [string]$Url,
    [string]$Method,
    [object]$BodyObj,
    [string]$Token
  )
  $headers = @{}
  if ($Token) { $headers["x-auth-token"] = $Token }
  $body = $null
  if ($null -ne $BodyObj) {
    $body = ($BodyObj | ConvertTo-Json -Depth 6)
    $headers["Content-Type"] = "application/json"
  }
  try {
    return Invoke-RestMethod -Uri $Url -Method $Method -Headers $headers -Body $body -TimeoutSec 5
  } catch {}
  return $null
}

function Get-QrPngImage {
  param(
    [string]$Url,
    [string]$Token
  )
  $headers = @{}
  if ($Token) { $headers["x-auth-token"] = $Token }
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $Url -Headers $headers -TimeoutSec 8
    if (-not $resp -or -not $resp.Content) { return $null }
    $ms = New-Object System.IO.MemoryStream
    $ms.Write($resp.Content, 0, $resp.Content.Length) | Out-Null
    $ms.Position = 0
    return [System.Drawing.Image]::FromStream($ms)
  } catch {}
  return $null
}

function Show-PairQrWindow {
  $status = Get-StackStatus
  if (-not $status.controller_running -or -not $status.ui_running) {
    [System.Windows.Forms.MessageBox]::Show(
      "Start Mobile Stack first, then try Show Pair QR.",
      "Codrex",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
    return
  }

  $cfg = Read-ControllerConfig
  $token = [string]$cfg.token
  if (-not $token) {
    [System.Windows.Forms.MessageBox]::Show(
      "No token found in controller.config.json. Pairing requires token auth enabled.",
      "Codrex",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Warning
    ) | Out-Null
    return
  }

  $tailscaleIp = Get-TailscaleIPv4
  $lanIp = [string]$status.lan_ip
  $pairHost = ""
  $routeLabel = ""
  $routeConfidence = ""
  if ($tailscaleIp) {
    $pairHost = $tailscaleIp
    $routeLabel = "Tailscale"
    $routeConfidence = "high confidence"
  } elseif ($lanIp -and $lanIp -ne "127.0.0.1") {
    $pairHost = $lanIp
    $routeLabel = "LAN"
    $routeConfidence = "medium confidence"
  } else {
    $pairHost = "127.0.0.1"
    $routeLabel = "Localhost"
    $routeConfidence = "low confidence"
  }

  $controllerPort = [int]$status.controller_port
  $createUrl = "http://127.0.0.1:$controllerPort/auth/pair/create"
  $create = Invoke-Json -Url $createUrl -Method "POST" -BodyObj @{} -Token $token
  if (-not $create -or -not $create.ok -or -not $create.code) {
    [System.Windows.Forms.MessageBox]::Show(
      "Could not create pairing code. Check logs and make sure controller is running.",
      "Codrex",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    return
  }

  $baseUrl = ("http://{0}:{1}" -f $pairHost, $script:UiPort)
  $pairUrl = "$baseUrl/auth/pair/consume?code=$([Uri]::EscapeDataString([string]$create.code))"
  $qrEndpoint = "http://127.0.0.1:$controllerPort/auth/pair/qr.png?data=$([Uri]::EscapeDataString($pairUrl))&ts=$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
  $img = Get-QrPngImage -Url $qrEndpoint -Token $token
  if ($null -eq $img) {
    [System.Windows.Forms.MessageBox]::Show(
      "Could not render QR image from controller.",
      "Codrex",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    return
  }

  $form = New-Object System.Windows.Forms.Form
  $form.Text = "Codrex Pair QR"
  $form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
  $form.Size = New-Object System.Drawing.Size(520, 650)
  $form.MinimumSize = New-Object System.Drawing.Size(520, 650)
  $form.MaximizeBox = $false
  $form.MinimizeBox = $false

  $layout = New-Object System.Windows.Forms.TableLayoutPanel
  $layout.Dock = "Fill"
  $layout.Padding = New-Object System.Windows.Forms.Padding(12)
  $layout.ColumnCount = 1
  $layout.RowCount = 6
  $layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 34)))
  $layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 420)))
  $layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 24)))
  $layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 34)))
  $layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 36)))
  $layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100)))
  $form.Controls.Add($layout)

  $lblTop = New-Object System.Windows.Forms.Label
  $lblTop.Text = "Step 1: scan on phone/tablet. Step 2: finish login in the mobile app."
  $lblTop.Dock = "Fill"
  $lblTop.TextAlign = "MiddleLeft"
  $layout.Controls.Add($lblTop, 0, 0)

  $pic = New-Object System.Windows.Forms.PictureBox
  $pic.Dock = "Fill"
  $pic.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
  $pic.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
  $pic.Image = $img
  $layout.Controls.Add($pic, 0, 1)

  $expires = if ($create.expires_in) { [int]$create.expires_in } else { 0 }
  $lblRoute = New-Object System.Windows.Forms.Label
  $lblRoute.Text = "Route: $routeLabel ($routeConfidence) | Expires in: ${expires}s"
  $lblRoute.Dock = "Fill"
  $lblRoute.TextAlign = "MiddleLeft"
  $layout.Controls.Add($lblRoute, 0, 2)

  $txt = New-Object System.Windows.Forms.TextBox
  $txt.Dock = "Fill"
  $txt.ReadOnly = $true
  $txt.Text = $pairUrl
  $layout.Controls.Add($txt, 0, 3)

  $btnRow = New-Object System.Windows.Forms.FlowLayoutPanel
  $btnRow.Dock = "Fill"
  $btnRow.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
  $btnRow.WrapContents = $false
  $layout.Controls.Add($btnRow, 0, 4)

  $btnCopy = New-Object System.Windows.Forms.Button
  $btnCopy.Text = "Copy Link"
  $btnCopy.AutoSize = $true
  $btnCopy.Add_Click({
    try {
      [System.Windows.Forms.Clipboard]::SetText($pairUrl)
    } catch {}
  })
  $btnRow.Controls.Add($btnCopy) | Out-Null

  $btnOpen = New-Object System.Windows.Forms.Button
  $btnOpen.Text = "Open Link"
  $btnOpen.AutoSize = $true
  $btnOpen.Add_Click({
    Open-Url $pairUrl
  })
  $btnRow.Controls.Add($btnOpen) | Out-Null

  $btnClose = New-Object System.Windows.Forms.Button
  $btnClose.Text = "Close"
  $btnClose.AutoSize = $true
  $btnClose.Add_Click({ $form.Close() })
  $btnRow.Controls.Add($btnClose) | Out-Null

  $form.Add_FormClosed({
    try { if ($pic.Image) { $pic.Image.Dispose() } } catch {}
    try { $form.Dispose() } catch {}
  })

  $form.ShowDialog() | Out-Null
}

function Get-ControllerProcess {
  $port = Read-ControllerPort
  $pattern = "--port\s+$port\b"
  $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "app\.server:app" -and $_.CommandLine -match $pattern }
  if ($procs) {
    return ($procs | Select-Object -First 1)
  }
  return $null
}

function Get-UiProcess {
  try {
    $listeners = Get-NetTCPConnection -LocalPort $script:UiPort -State Listen -ErrorAction SilentlyContinue
  } catch {
    return $null
  }
  if (-not $listeners) {
    return $null
  }

  foreach ($entry in ($listeners | Select-Object -Unique OwningProcess)) {
    $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $entry.OwningProcess) -ErrorAction SilentlyContinue
    if (-not $proc) { continue }
    $cmd = [string]$proc.CommandLine
    if (($proc.Name -match "node") -or ($cmd -match "vite")) {
      return $proc
    }
  }
  return $null
}

function Get-StackStatus {
  $controller = Get-ControllerProcess
  $ui = Get-UiProcess
  $controllerPort = Read-ControllerPort
  $lanIp = Get-PrimaryIPv4
  return [pscustomobject]@{
    controller_running = ($null -ne $controller)
    controller_pid = $(if ($controller) { [int]$controller.ProcessId } else { 0 })
    controller_port = $controllerPort
    ui_running = ($null -ne $ui)
    ui_pid = $(if ($ui) { [int]$ui.ProcessId } else { 0 })
    ui_port = $script:UiPort
    lan_ip = $lanIp
  }
}

function Open-Url {
  param([string]$Url)
  if (-not $Url) { return }
  try {
    Start-Process $Url | Out-Null
  } catch {}
}

function Enqueue-Balloon {
  param(
    [string]$Title,
    [string]$Text,
    [System.Windows.Forms.ToolTipIcon]$Icon = [System.Windows.Forms.ToolTipIcon]::Info
  )
  $script:BalloonQueue += [pscustomobject]@{
    title = $Title
    text = $Text
    icon = $Icon
  }
}

function Flush-BalloonQueue {
  if ($script:BalloonQueue.Count -eq 0) { return }
  $next = $script:BalloonQueue[0]
  if ($script:BalloonQueue.Count -gt 1) {
    $script:BalloonQueue = $script:BalloonQueue[1..($script:BalloonQueue.Count - 1)]
  } else {
    $script:BalloonQueue = @()
  }
  $script:NotifyIcon.BalloonTipIcon = $next.icon
  $script:NotifyIcon.BalloonTipTitle = $next.title
  $script:NotifyIcon.BalloonTipText = $next.text
  $script:NotifyIcon.ShowBalloonTip(2500)
}

function Start-ActionProcess {
  param([ValidateSet("start", "stop")] [string]$Action)

  if ($script:PendingProc -and -not $script:PendingProc.HasExited) {
    Enqueue-Balloon -Title "Codrex" -Text "Another action is already running." -Icon ([System.Windows.Forms.ToolTipIcon]::Warning)
    return
  }

  $targetScript = if ($Action -eq "start") { $script:StartScript } else { $script:StopScript }
  if (-not (Test-Path $targetScript)) {
    Enqueue-Balloon -Title "Codrex" -Text "Missing script: $targetScript" -Icon ([System.Windows.Forms.ToolTipIcon]::Error)
    return
  }

  $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $targetScript, "-UiPort", [string]$script:UiPort)
  try {
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WorkingDirectory $script:Root -WindowStyle Hidden -PassThru
    $script:PendingAction = $Action
    $script:PendingProc = $proc
    Update-UiState
  } catch {
    Enqueue-Balloon -Title "Codrex" -Text ("Could not run action: " + $_.Exception.Message) -Icon ([System.Windows.Forms.ToolTipIcon]::Error)
  }
}

function Handle-PendingAction {
  if (-not $script:PendingProc) { return }

  try {
    $null = $script:PendingProc.HasExited
  } catch {
    $script:PendingProc = $null
    $script:PendingAction = ""
    return
  }

  if (-not $script:PendingProc.HasExited) {
    return
  }

  $action = $script:PendingAction
  $exitCode = [int]$script:PendingProc.ExitCode
  $script:PendingProc = $null
  $script:PendingAction = ""

  if ($exitCode -eq 0) {
    if ($action -eq "start") {
      Enqueue-Balloon -Title "Codrex" -Text "Mobile stack started. Open UI or Show Pair QR from this menu." -Icon ([System.Windows.Forms.ToolTipIcon]::Info)
    } else {
      Enqueue-Balloon -Title "Codrex" -Text "Mobile stack stopped. Start again when remote control is needed." -Icon ([System.Windows.Forms.ToolTipIcon]::Info)
    }
  } else {
    Enqueue-Balloon -Title "Codrex" -Text ("Action failed (exit code " + $exitCode + "). Check logs.") -Icon ([System.Windows.Forms.ToolTipIcon]::Error)
  }
}

function Update-UiState {
  $status = Get-StackStatus
  $script:LastStatus = $status

  $stateText = if ($status.controller_running -and $status.ui_running) { "Running" } else { "Stopped" }
  if ($script:PendingAction) {
    if ($script:PendingAction -eq "start") {
      $stateText = "Starting..."
    } elseif ($script:PendingAction -eq "stop") {
      $stateText = "Stopping..."
    }
  }

  $script:StatusItem.Text = "Status: $stateText"
  $script:StatusDetailsItem.Text = "Controller $($status.controller_port) (PID $($status.controller_pid)) | UI $($status.ui_port) (PID $($status.ui_pid)) | LAN $($status.lan_ip)"

  $isBusy = [bool]$script:PendingAction
  $script:StartItem.Enabled = (-not $isBusy) -and (-not ($status.controller_running -and $status.ui_running))
  $script:StopItem.Enabled = (-not $isBusy) -and ($status.controller_running -or $status.ui_running)

  $script:OpenUiLocalItem.Enabled = $status.ui_running
  $script:OpenUiNetworkItem.Enabled = $status.ui_running -and $status.lan_ip -and $status.lan_ip -ne "127.0.0.1"
  $script:OpenControllerItem.Enabled = $status.controller_running
  $script:PairQrItem.Enabled = (-not $isBusy) -and $status.controller_running -and $status.ui_running

  $tooltipState = if ($status.controller_running -and $status.ui_running) { "Running" } else { "Stopped" }
  $tip = "Codrex Mobile ($tooltipState)"
  if ($tip.Length -gt 62) {
    $tip = $tip.Substring(0, 62)
  }
  $script:NotifyIcon.Text = $tip
}

function Cleanup-And-Exit {
  try { $script:Timer.Stop() } catch {}
  try { $script:NotifyIcon.Visible = $false } catch {}
  try { $script:NotifyIcon.Dispose() } catch {}
  try { $script:Timer.Dispose() } catch {}
  try { $script:ContextMenu.Dispose() } catch {}
  try {
    if ($null -ne $mutex) {
      $mutex.ReleaseMutex() | Out-Null
      $mutex.Dispose()
    }
  } catch {}
  $script:AppContext.ExitThread()
}

if (-not (Test-Path $script:LogsDir)) {
  New-Item -Path $script:LogsDir -ItemType Directory -Force | Out-Null
}

[System.Windows.Forms.Application]::EnableVisualStyles()
$script:AppContext = New-Object System.Windows.Forms.ApplicationContext
$script:ContextMenu = New-Object System.Windows.Forms.ContextMenuStrip

$script:StatusItem = New-Object System.Windows.Forms.ToolStripMenuItem("Status: ...")
$script:StatusItem.Enabled = $false
$script:StatusDetailsItem = New-Object System.Windows.Forms.ToolStripMenuItem("Controller/UI status")
$script:StatusDetailsItem.Enabled = $false
$script:HeaderStackItem = New-Object System.Windows.Forms.ToolStripMenuItem("Service Control")
$script:HeaderStackItem.Enabled = $false
$script:HeaderOpenItem = New-Object System.Windows.Forms.ToolStripMenuItem("Open Surfaces")
$script:HeaderOpenItem.Enabled = $false
$script:HeaderPairItem = New-Object System.Windows.Forms.ToolStripMenuItem("Pair and Diagnostics")
$script:HeaderPairItem.Enabled = $false

$script:StartItem = New-Object System.Windows.Forms.ToolStripMenuItem("Start Mobile Stack")
$script:StopItem = New-Object System.Windows.Forms.ToolStripMenuItem("Stop Mobile Stack")
$script:OpenUiLocalItem = New-Object System.Windows.Forms.ToolStripMenuItem("Open Mobile UI (Local)")
$script:OpenUiNetworkItem = New-Object System.Windows.Forms.ToolStripMenuItem("Open Mobile UI (Network)")
$script:PairQrItem = New-Object System.Windows.Forms.ToolStripMenuItem("Show Pair QR (Mobile Login)")
$script:OpenControllerItem = New-Object System.Windows.Forms.ToolStripMenuItem("Open Controller UI")
$script:OpenLogsItem = New-Object System.Windows.Forms.ToolStripMenuItem("Open Logs Folder")
$script:ExitItem = New-Object System.Windows.Forms.ToolStripMenuItem("Exit Tray")

$script:StartItem.Add_Click({ Start-ActionProcess -Action "start" })
$script:StopItem.Add_Click({ Start-ActionProcess -Action "stop" })
$script:OpenUiLocalItem.Add_Click({
  if (-not $script:LastStatus) { Update-UiState }
  Open-Url ("http://127.0.0.1:{0}" -f $script:UiPort)
})
$script:OpenUiNetworkItem.Add_Click({
  if (-not $script:LastStatus) { Update-UiState }
  $ip = [string]$script:LastStatus.lan_ip
  if ($ip) {
    Open-Url ("http://{0}:{1}" -f $ip, $script:UiPort)
  }
})
$script:PairQrItem.Add_Click({
  Show-PairQrWindow
})
$script:OpenControllerItem.Add_Click({
  if (-not $script:LastStatus) { Update-UiState }
  $port = [int]$script:LastStatus.controller_port
  Open-Url ("http://127.0.0.1:{0}" -f $port)
})
$script:OpenLogsItem.Add_Click({
  try { Start-Process explorer.exe $script:LogsDir | Out-Null } catch {}
})
$script:ExitItem.Add_Click({ Cleanup-And-Exit })

$null = $script:ContextMenu.Items.Add($script:StatusItem)
$null = $script:ContextMenu.Items.Add($script:StatusDetailsItem)
$null = $script:ContextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
$null = $script:ContextMenu.Items.Add($script:HeaderStackItem)
$null = $script:ContextMenu.Items.Add($script:StartItem)
$null = $script:ContextMenu.Items.Add($script:StopItem)
$null = $script:ContextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
$null = $script:ContextMenu.Items.Add($script:HeaderOpenItem)
$null = $script:ContextMenu.Items.Add($script:OpenUiLocalItem)
$null = $script:ContextMenu.Items.Add($script:OpenUiNetworkItem)
$null = $script:ContextMenu.Items.Add($script:OpenControllerItem)
$null = $script:ContextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
$null = $script:ContextMenu.Items.Add($script:HeaderPairItem)
$null = $script:ContextMenu.Items.Add($script:PairQrItem)
$null = $script:ContextMenu.Items.Add($script:OpenLogsItem)
$null = $script:ContextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
$null = $script:ContextMenu.Items.Add($script:ExitItem)

$script:NotifyIcon = New-Object System.Windows.Forms.NotifyIcon
$script:NotifyIcon.Icon = [System.Drawing.SystemIcons]::Application
$script:NotifyIcon.Visible = $true
$script:NotifyIcon.ContextMenuStrip = $script:ContextMenu
$script:NotifyIcon.Text = "Codrex Mobile Tray"
$script:NotifyIcon.BalloonTipTitle = "Codrex"
$script:NotifyIcon.BalloonTipText = "Tray launcher started."
$script:NotifyIcon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
$script:NotifyIcon.ShowBalloonTip(1800)

$script:NotifyIcon.Add_DoubleClick({
  Open-Url ("http://127.0.0.1:{0}" -f $script:UiPort)
})

$script:Timer = New-Object System.Windows.Forms.Timer
$script:Timer.Interval = 3000
$script:Timer.Add_Tick({
  Handle-PendingAction
  Update-UiState
  Flush-BalloonQueue
})

Update-UiState
$script:Timer.Start()

try {
  [System.Windows.Forms.Application]::Run($script:AppContext)
} finally {
  try {
    if ($null -ne $mutex) {
      $mutex.ReleaseMutex() | Out-Null
      $mutex.Dispose()
    }
  } catch {}
}
