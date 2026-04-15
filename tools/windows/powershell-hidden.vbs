Set shell = CreateObject("WScript.Shell")

If WScript.Arguments.Count = 0 Then
  WScript.Quit 1
End If

command = "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden "
For i = 0 To WScript.Arguments.Count - 1
  command = command & """" & Replace(WScript.Arguments(i), """", """""") & """ "
Next

shell.Run command, 0, False
