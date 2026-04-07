$procs = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq 'msedgewebview2.exe' -and $_.CommandLine -match 'Codrex\.Launcher\.exe\.WebView2'
}
$procs | Select-Object ProcessId, ParentProcessId, CommandLine | ConvertTo-Json -Compress
