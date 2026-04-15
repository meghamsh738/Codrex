[CmdletBinding()]
param(
    [string]$ControllerOrigin = "http://127.0.0.1:48787",
    [string]$ImagePath = "D:\1000001997.jpg",
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"

function Get-ControllerToken {
    if ($Token) {
        return $Token
    }
    $configPath = "D:\Codrex\remote-ui\state\controller.config.local.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        throw "controller token config not found: $configPath"
    }
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $resolved = [string]($config.token)
    if (-not $resolved) {
        throw "controller token missing in $configPath"
    }
    return $resolved
}

function Stop-OfficeApps {
    Get-Process POWERPNT, WINWORD, ONENOTE -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}

function Invoke-PasteImage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedToken
    )
    $response = & curl.exe -s -X POST -H "x-auth-token: $ResolvedToken" -F "file=@$ImagePath" "$ControllerOrigin/desktop/paste/image"
    if (-not $response) {
        throw "empty response from /desktop/paste/image"
    }
    return ($response | ConvertFrom-Json)
}

function Wait-ForComObject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProgId,
        [int]$MaxAttempts = 60
    )
    for ($attempt = 0; $attempt -lt $MaxAttempts; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $app = [System.Runtime.InteropServices.Marshal]::GetActiveObject($ProgId)
        } catch {
            $app = $null
        }
        if ($app) {
            return $app
        }
    }
    throw "COM app not ready: $ProgId"
}

function Test-PowerPointPaste {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedToken,
        [Parameter(Mandatory = $true)]
        $Shell
    )
    Stop-OfficeApps
    $proc = Start-Process -FilePath "C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE" -PassThru
    $ppt = $null
    $pres = $null
    try {
        $ppt = Wait-ForComObject -ProgId "PowerPoint.Application"
        $ppt.Visible = -1
        $pres = $ppt.Presentations.Add()
        $slide = $pres.Slides.Add(1, 12)
        $ppt.ActiveWindow.View.GotoSlide(1)
        Start-Sleep -Milliseconds 700
        [void]$Shell.AppActivate($proc.Id)
        Start-Sleep -Milliseconds 900
        $before = [int]$slide.Shapes.Count
        $response = Invoke-PasteImage -ResolvedToken $ResolvedToken
        Start-Sleep -Milliseconds 1500
        $after = [int]$slide.Shapes.Count
        return [pscustomobject]@{
            app            = "powerpoint"
            before         = $before
            after          = $after
            delta          = $after - $before
            ok             = ($after -gt $before) -and ($response.target_family -eq "powerpoint")
            target_process = [string]$response.target_process
            target_family  = [string]$response.target_family
            paste_strategy = [string]$response.paste_strategy
            detail         = [string]$response.detail
        }
    } finally {
        try { if ($pres) { $pres.Close() } } catch {}
        try { if ($ppt) { $ppt.Quit() } } catch {}
        try { if ($ppt) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) } } catch {}
    }
}

function Test-WordPaste {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedToken,
        [Parameter(Mandatory = $true)]
        $Shell
    )
    Stop-OfficeApps
    $proc = Start-Process -FilePath "C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE" -PassThru
    $word = $null
    $doc = $null
    try {
        $word = Wait-ForComObject -ProgId "Word.Application"
        $word.Visible = $true
        $doc = $word.Documents.Add()
        $doc.Activate()
        $word.Activate()
        Start-Sleep -Milliseconds 700
        [void]$Shell.AppActivate($proc.Id)
        Start-Sleep -Milliseconds 900
        $before = [int]($doc.Shapes.Count + $doc.InlineShapes.Count)
        $response = Invoke-PasteImage -ResolvedToken $ResolvedToken
        Start-Sleep -Milliseconds 1500
        $after = [int]($doc.Shapes.Count + $doc.InlineShapes.Count)
        return [pscustomobject]@{
            app            = "word"
            before         = $before
            after          = $after
            delta          = $after - $before
            ok             = ($after -gt $before) -and ($response.target_family -eq "word")
            target_process = [string]$response.target_process
            target_family  = [string]$response.target_family
            paste_strategy = [string]$response.paste_strategy
            detail         = [string]$response.detail
        }
    } finally {
        try { if ($doc) { $doc.Close(0) } } catch {}
        try { if ($word) { $word.Quit(0) } } catch {}
        try { if ($word) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) } } catch {}
    }
}

function Test-OneNotePaste {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedToken,
        [Parameter(Mandatory = $true)]
        $Shell
    )
    Stop-OfficeApps
    $proc = Start-Process -FilePath "C:\Program Files\Microsoft Office\root\Office16\ONENOTE.EXE" -PassThru
    try {
        Start-Sleep -Seconds 8
        [void]$Shell.AppActivate($proc.Id)
        Start-Sleep -Milliseconds 900
        $response = Invoke-PasteImage -ResolvedToken $ResolvedToken
        return [pscustomobject]@{
            app            = "onenote"
            before         = $null
            after          = $null
            delta          = $null
            ok             = ($response.target_family -eq "onenote")
            target_process = [string]$response.target_process
            target_family  = [string]$response.target_family
            paste_strategy = [string]$response.paste_strategy
            detail         = [string]$response.detail
        }
    } finally {
        try { Get-Process ONENOTE -ErrorAction SilentlyContinue | Stop-Process -Force } catch {}
    }
}

if (-not (Test-Path -LiteralPath $ImagePath)) {
    throw "image not found: $ImagePath"
}

$resolvedToken = Get-ControllerToken
$null = Invoke-RestMethod -Method Post -Uri "$ControllerOrigin/desktop/mode" -Headers @{ "x-auth-token" = $resolvedToken } -ContentType "application/json" -Body '{"enabled":true}'
$shell = New-Object -ComObject WScript.Shell

$results = @(
    Test-PowerPointPaste -ResolvedToken $resolvedToken -Shell $shell
    Test-WordPaste -ResolvedToken $resolvedToken -Shell $shell
    Test-OneNotePaste -ResolvedToken $resolvedToken -Shell $shell
)

$results | ConvertTo-Json -Depth 5
