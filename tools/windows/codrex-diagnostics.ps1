function Get-CodrexDiagnosticsLayout {
  param(
    [string]$RuntimeDir
  )
  $logsDir = Join-Path $RuntimeDir "logs"
  $actionsDir = Join-Path $logsDir "actions"
  return [pscustomobject]@{
    runtime_dir = $RuntimeDir
    logs_dir = $logsDir
    actions_dir = $actionsDir
    events_log = Join-Path $logsDir "launcher-events.log"
    last_action_path = Join-Path $logsDir "last-action.json"
    last_error_path = Join-Path $logsDir "last-error.json"
  }
}

function Ensure-CodrexDiagnosticsLayout {
  param(
    [string]$RuntimeDir
  )
  $layout = Get-CodrexDiagnosticsLayout -RuntimeDir $RuntimeDir
  foreach ($dir in @($layout.logs_dir, $layout.actions_dir)) {
    if (-not (Test-Path $dir)) {
      New-Item -Path $dir -ItemType Directory -Force | Out-Null
    }
  }
  return $layout
}

function New-CodrexActionId {
  return ([guid]::NewGuid().ToString("N"))
}

function Get-CodrexTimestamp {
  return (Get-Date).ToString("o")
}

function Get-CodrexCurrentActionId {
  $value = [string]$env:CODEX_ACTION_ID
  if ($value -and $value.Trim()) {
    return $value.Trim()
  }
  return ""
}

function Get-CodrexCurrentActionName {
  $value = [string]$env:CODEX_ACTION_NAME
  if ($value -and $value.Trim()) {
    return $value.Trim()
  }
  return ""
}

function Get-CodrexCurrentActionSource {
  $value = [string]$env:CODEX_ACTION_SOURCE
  if ($value -and $value.Trim()) {
    return $value.Trim()
  }
  return ""
}

function Get-CodrexSelectedRouteFromState {
  param(
    [string]$RuntimeDir
  )
  try {
    $statePath = Join-Path (Join-Path $RuntimeDir "state") "launcher.state.json"
    if (-not (Test-Path $statePath)) {
      return ""
    }
    $payload = Get-Content -Path $statePath -Raw | ConvertFrom-Json
    $route = ([string]$payload.preferred_pair_route).Trim().ToLowerInvariant()
    if ($route -in @("lan", "tailscale")) {
      return $route
    }
  } catch {}
  return ""
}

function Get-CodrexStringTail {
  param(
    [AllowNull()]
    [string]$Value,
    [int]$MaxChars = 320
  )
  if (-not $Value) {
    return ""
  }
  if ($Value.Length -le $MaxChars) {
    return $Value
  }
  return ("..." + $Value.Substring($Value.Length - $MaxChars))
}

function Get-CodrexTextTail {
  param(
    [AllowNull()]
    [object]$Text,
    [int]$MaxLines = 60,
    [int]$MaxChars = 4000
  )
  if ($null -eq $Text) {
    return ""
  }
  $lines = @()
  if ($Text -is [System.Collections.IEnumerable] -and -not ($Text -is [string])) {
    foreach ($item in $Text) {
      if ($null -ne $item) {
        $lines += [string]$item
      }
    }
  } else {
    $raw = [string]$Text
    if ($raw) {
      $lines = @($raw -split "`r?`n")
    }
  }
  if (-not $lines -or $lines.Count -eq 0) {
    return ""
  }
  $tail = @($lines | Select-Object -Last $MaxLines)
  $joined = ($tail -join "`n").Trim()
  if (-not $joined) {
    return ""
  }
  if ($joined.Length -le $MaxChars) {
    return $joined
  }
  return ("..." + $joined.Substring($joined.Length - $MaxChars))
}

function Protect-CodrexUrlSecrets {
  param(
    [AllowNull()]
    [string]$Value
  )
  if (-not $Value) {
    return ""
  }
  $sanitized = $Value
  $patterns = @(
    '([?&](?:code|token|auth|x-auth-token|auth_token|pair_code)=)[^&]+',
    '([?&](?:cookie|session|sessionid)=)[^&]+'
  )
  foreach ($pattern in $patterns) {
    $sanitized = [regex]::Replace($sanitized, $pattern, '$1<redacted>', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
  }
  return $sanitized
}

function Test-CodrexSensitiveKey {
  param(
    [string]$KeyName
  )
  if (-not $KeyName) {
    return $false
  }
  return ($KeyName -match '(?i)(^|_|-)(token|code|cookie|authorization|secret|password|session)(_|-|$)' -or
    $KeyName -match '(?i)x-auth-token' -or
    $KeyName -match '(?i)pair[_-]?url')
}

function ConvertTo-CodrexSafeData {
  param(
    [AllowNull()]
    [object]$Value,
    [string]$KeyName = ""
  )
  if ($null -eq $Value) {
    return $null
  }
  if ($Value -is [string]) {
    if (Test-CodrexSensitiveKey -KeyName $KeyName) {
      return "<redacted>"
    }
    return (Protect-CodrexUrlSecrets -Value $Value)
  }
  if ($Value -is [bool] -or
      $Value -is [byte] -or
      $Value -is [int16] -or
      $Value -is [int32] -or
      $Value -is [int64] -or
      $Value -is [single] -or
      $Value -is [double] -or
      $Value -is [decimal]) {
    return $Value
  }
  if ($Value -is [DateTime] -or $Value -is [DateTimeOffset]) {
    return $Value.ToString("o")
  }
  if ($Value -is [System.Collections.IDictionary]) {
    $safe = [ordered]@{}
    foreach ($key in $Value.Keys) {
      $name = [string]$key
      $safe[$name] = ConvertTo-CodrexSafeData -Value $Value[$key] -KeyName $name
    }
    return [pscustomobject]$safe
  }
  if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
    $items = @()
    foreach ($item in $Value) {
      $items += ,(ConvertTo-CodrexSafeData -Value $item)
    }
    return @($items)
  }

  $properties = $Value.PSObject.Properties
  if ($properties -and $properties.Count -gt 0) {
    $safe = [ordered]@{}
    foreach ($property in $properties) {
      if (-not $property) { continue }
      $name = [string]$property.Name
      $safe[$name] = ConvertTo-CodrexSafeData -Value $property.Value -KeyName $name
    }
    return [pscustomobject]$safe
  }

  return (Protect-CodrexUrlSecrets -Value ([string]$Value))
}

function Rotate-CodrexTextLog {
  param(
    [string]$Path,
    [int]$MaxFiles = 5,
    [int]$MaxBytes = 1048576
  )
  if (-not $Path -or -not (Test-Path $Path)) {
    return
  }
  try {
    $file = Get-Item -Path $Path -ErrorAction Stop
    if ($file.Length -lt $MaxBytes) {
      return
    }
  } catch {
    return
  }
  for ($index = $MaxFiles - 1; $index -ge 1; $index--) {
    $source = if ($index -eq 1) { $Path } else { "$Path.$($index - 1)" }
    $target = "$Path.$index"
    if (Test-Path $target) {
      Remove-Item -Path $target -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $source) {
      Move-Item -Path $source -Destination $target -Force -ErrorAction SilentlyContinue
    }
  }
}

function Rotate-CodrexActionLogs {
  param(
    [string]$ActionsDir,
    [int]$MaxFiles = 50
  )
  if (-not $ActionsDir -or -not (Test-Path $ActionsDir)) {
    return
  }
  try {
    $files = @(Get-ChildItem -Path $ActionsDir -File -Filter "*.json" | Sort-Object LastWriteTime -Descending)
  } catch {
    return
  }
  if ($files.Count -le $MaxFiles) {
    return
  }
  foreach ($file in ($files | Select-Object -Skip $MaxFiles)) {
    Remove-Item -Path $file.FullName -Force -ErrorAction SilentlyContinue
  }
}

function Get-CodrexPortDiagnosticsSnapshot {
  param(
    [int[]]$Ports
  )
  $portList = @($Ports | Where-Object { $_ -gt 0 } | Select-Object -Unique)
  if (-not $portList -or $portList.Count -eq 0) {
    return @()
  }
  $snapshots = @()
  try {
    $connections = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $portList -contains [int]$_.LocalPort })
  } catch {
    $connections = @()
  }
  foreach ($connection in $connections) {
    $procId = [int]$connection.OwningProcess
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $procId) -ErrorAction SilentlyContinue
    $snapshots += ,([pscustomobject]@{
      local_address = [string]$connection.LocalAddress
      local_port = [int]$connection.LocalPort
      state = [string]$connection.State
      owning_process = $procId
      process_name = if ($process) { [string]$process.Name } else { "" }
      command_line_tail = if ($process -and $process.CommandLine) { Get-CodrexStringTail -Value ([string]$process.CommandLine) -MaxChars 280 } else { "" }
    })
  }
  return @($snapshots)
}

function Write-CodrexEventLog {
  param(
    [string]$RuntimeDir,
    [string]$Source,
    [string]$Message,
    [string]$Action = "",
    [string]$Level = "info",
    [AllowNull()]
    [object]$Context = $null,
    [string]$ActionId = ""
  )
  if (-not $RuntimeDir) {
    return ""
  }
  $layout = Ensure-CodrexDiagnosticsLayout -RuntimeDir $RuntimeDir
  Rotate-CodrexTextLog -Path $layout.events_log
  $timestamp = Get-CodrexTimestamp
  $effectiveActionId = if ($ActionId) { $ActionId } else { Get-CodrexCurrentActionId }
  $effectiveAction = if ($Action) { $Action } else { Get-CodrexCurrentActionName }
  $safeContext = if ($null -ne $Context) { ConvertTo-CodrexSafeData -Value $Context } else { $null }
  $contextJson = ""
  if ($safeContext) {
    try {
      $contextJson = ($safeContext | ConvertTo-Json -Depth 8 -Compress)
    } catch {}
  }
  $parts = @("[{0}]" -f $timestamp)
  if ($Level) { $parts += "level=$Level" }
  if ($Source) { $parts += "source=$Source" }
  if ($effectiveAction) { $parts += "action=$effectiveAction" }
  if ($effectiveActionId) { $parts += "action_id=$effectiveActionId" }
  if ($Message) {
    $parts += ('message="{0}"' -f ($Message -replace '"', "'"))
  }
  if ($contextJson) {
    $parts += "context=$contextJson"
  }
  Add-Content -Path $layout.events_log -Value ($parts -join " ") -Encoding UTF8
  return $layout.events_log
}

function Write-CodrexActionLog {
  param(
    [string]$RuntimeDir,
    [string]$Action,
    [string]$Source,
    [AllowNull()]
    [object]$Payload,
    [string]$ActionId = "",
    [switch]$IsError
  )
  if (-not $RuntimeDir) {
    return $null
  }
  $layout = Ensure-CodrexDiagnosticsLayout -RuntimeDir $RuntimeDir
  Rotate-CodrexActionLogs -ActionsDir $layout.actions_dir
  $effectiveActionId = if ($ActionId) { $ActionId } else { Get-CodrexCurrentActionId }
  if (-not $effectiveActionId) {
    $effectiveActionId = New-CodrexActionId
  }
  $timestamp = Get-CodrexTimestamp
  $safePayload = ConvertTo-CodrexSafeData -Value $Payload
  $record = [ordered]@{
    action_id = $effectiveActionId
    timestamp = $timestamp
    action = $Action
    source = $Source
  }
  if ($safePayload -is [psobject] -or $safePayload -is [System.Collections.IDictionary]) {
    foreach ($property in $safePayload.PSObject.Properties) {
      $record[$property.Name] = $property.Value
    }
  } else {
    $record["payload"] = $safePayload
  }
  $stamp = (Get-Date).ToString("yyyyMMdd-HHmmss-fff")
  $safeActionName = if ($Action) { ($Action -replace '[^A-Za-z0-9._-]', '-') } else { "action" }
  $actionPath = Join-Path $layout.actions_dir ("{0}-{1}-{2}.json" -f $stamp, $safeActionName, $effectiveActionId.Substring(0, 8))
  $record | ConvertTo-Json -Depth 10 | Set-Content -Path $actionPath -Encoding UTF8
  Copy-Item -Path $actionPath -Destination $layout.last_action_path -Force
  $shouldStoreAsError = $IsError
  try {
    if ($record.Contains("ok") -and $record.ok -eq $false) {
      $shouldStoreAsError = $true
    }
  } catch {}
  if ($shouldStoreAsError) {
    Copy-Item -Path $actionPath -Destination $layout.last_error_path -Force
  }
  Rotate-CodrexActionLogs -ActionsDir $layout.actions_dir
  return [pscustomobject]@{
    action_id = $effectiveActionId
    action_path = $actionPath
    last_action_path = $layout.last_action_path
    last_error_path = $layout.last_error_path
    events_log = $layout.events_log
  }
}
