param(
  [string]$RepoRoot = "",
  [switch]$AttemptGenerate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

if (-not $RepoRoot) {
  $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$iconDir = Join-Path $RepoRoot "ui\\public"
$required = @(
  @{ name = "icon-192.png"; size = 192; maskable = $false },
  @{ name = "icon-512.png"; size = 512; maskable = $false },
  @{ name = "icon-maskable-192.png"; size = 192; maskable = $true },
  @{ name = "icon-maskable-512.png"; size = 512; maskable = $true },
  @{ name = "apple-touch-icon.png"; size = 180; maskable = $false }
)

function Get-CornerMeanColor([System.Drawing.Bitmap]$bmp) {
  $w = $bmp.Width
  $h = $bmp.Height
  $samples = @(
    $bmp.GetPixel(0, 0),
    $bmp.GetPixel([Math]::Max(0, $w - 1), 0),
    $bmp.GetPixel(0, [Math]::Max(0, $h - 1)),
    $bmp.GetPixel([Math]::Max(0, $w - 1), [Math]::Max(0, $h - 1))
  )
  $r = 0.0
  $g = 0.0
  $b = 0.0
  foreach ($c in $samples) {
    $r += [double]$c.R
    $g += [double]$c.G
    $b += [double]$c.B
  }
  return @{
    r = $r / $samples.Count
    g = $g / $samples.Count
    b = $b / $samples.Count
  }
}

function Get-Luma([System.Drawing.Color]$c) {
  return (0.2126 * [double]$c.R) + (0.7152 * [double]$c.G) + (0.0722 * [double]$c.B)
}

function Analyze-Icon([string]$path, [int]$expectedSize, [bool]$isMaskable) {
  if (-not (Test-Path $path)) {
    return @{
      ok = $false
      detail = "missing file"
      contrast = 0.0
      stddev = 0.0
      margin = 0
      expected_margin = 0
      mean_r = 0.0
      mean_g = 0.0
      mean_b = 0.0
    }
  }

  $bmp = New-Object System.Drawing.Bitmap $path
  try {
    if ($bmp.Width -ne $expectedSize -or $bmp.Height -ne $expectedSize) {
      return @{
        ok = $false
        detail = "wrong size ${($bmp.Width)}x${($bmp.Height)} (expected ${expectedSize}x${expectedSize})"
        contrast = 0.0
        stddev = 0.0
        margin = 0
        expected_margin = 0
        mean_r = 0.0
        mean_g = 0.0
        mean_b = 0.0
      }
    }

    $bg = Get-CornerMeanColor -bmp $bmp
    $threshold = 24.0

    $minL = 255.0
    $maxL = 0.0
    $sumL = 0.0
    $sumL2 = 0.0
    $sumR = 0.0
    $sumG = 0.0
    $sumB = 0.0
    $count = 0.0
    $left = $bmp.Width
    $top = $bmp.Height
    $right = -1
    $bottom = -1

    for ($y = 0; $y -lt $bmp.Height; $y++) {
      for ($x = 0; $x -lt $bmp.Width; $x++) {
        $px = $bmp.GetPixel($x, $y)
        $l = Get-Luma $px
        if ($l -lt $minL) { $minL = $l }
        if ($l -gt $maxL) { $maxL = $l }
        $sumL += $l
        $sumL2 += ($l * $l)
        $sumR += [double]$px.R
        $sumG += [double]$px.G
        $sumB += [double]$px.B
        $count += 1.0

        $diff = [Math]::Sqrt(
          ([Math]::Pow(([double]$px.R - $bg.r), 2.0)) +
          ([Math]::Pow(([double]$px.G - $bg.g), 2.0)) +
          ([Math]::Pow(([double]$px.B - $bg.b), 2.0))
        )
        if ($diff -gt $threshold) {
          if ($x -lt $left) { $left = $x }
          if ($y -lt $top) { $top = $y }
          if ($x -gt $right) { $right = $x }
          if ($y -gt $bottom) { $bottom = $y }
        }
      }
    }

    if ($count -le 0) {
      return @{
        ok = $false
        detail = "no pixels"
        contrast = 0.0
        stddev = 0.0
        margin = 0
        expected_margin = 0
        mean_r = 0.0
        mean_g = 0.0
        mean_b = 0.0
      }
    }

    $contrast = $maxL - $minL
    $meanL = $sumL / $count
    $variance = [Math]::Max(0.0, ($sumL2 / $count) - ($meanL * $meanL))
    $stddev = [Math]::Sqrt($variance)
    $meanR = $sumR / $count
    $meanG = $sumG / $count
    $meanB = $sumB / $count

    if ($right -lt $left -or $bottom -lt $top) {
      $left = 0
      $top = 0
      $right = $bmp.Width - 1
      $bottom = $bmp.Height - 1
    }

    $margin = [Math]::Min(
      [Math]::Min($left, $top),
      [Math]::Min(($bmp.Width - 1 - $right), ($bmp.Height - 1 - $bottom))
    )
    $expectedMargin = if ($isMaskable) {
      [Math]::Floor($expectedSize * 0.10)
    } else {
      [Math]::Floor($expectedSize * 0.04)
    }

    $contrastPass = $contrast -ge 55.0
    $clarityPass = $stddev -ge 18.0
    $safeZonePass = if ($isMaskable) { $margin -ge $expectedMargin } else { $true }
    $ok = $contrastPass -and $clarityPass -and $safeZonePass

    $detail = "ok"
    if (-not $ok) {
      $detail = "contrast=$([Math]::Round($contrast,2)), stddev=$([Math]::Round($stddev,2)), margin=$margin (need >= $expectedMargin for maskable)"
    }

    return @{
      ok = $ok
      detail = $detail
      contrast = [Math]::Round($contrast, 2)
      stddev = [Math]::Round($stddev, 2)
      margin = $margin
      expected_margin = $expectedMargin
      mean_r = [Math]::Round($meanR, 2)
      mean_g = [Math]::Round($meanG, 2)
      mean_b = [Math]::Round($meanB, 2)
    }
  } finally {
    $bmp.Dispose()
  }
}

function Save-ResizedIcon([string]$source, [string]$dest, [int]$size, [double]$paddingRatio) {
  $src = [System.Drawing.Image]::FromFile($source)
  $bmp = New-Object System.Drawing.Bitmap $size, $size
  $gfx = [System.Drawing.Graphics]::FromImage($bmp)
  try {
    $gfx.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $gfx.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $gfx.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $gfx.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $gfx.Clear([System.Drawing.Color]::Transparent)

    $padding = [int][Math]::Round($size * [Math]::Max(0.0, [Math]::Min(0.45, $paddingRatio)))
    $inner = [Math]::Max(1, $size - (2 * $padding))
    $gfx.DrawImage($src, $padding, $padding, $inner, $inner)
    $bmp.Save($dest, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $gfx.Dispose()
    $bmp.Dispose()
    $src.Dispose()
  }
}

function Evaluate-Icons([string]$baseDir) {
  $result = [ordered]@{}
  foreach ($item in $required) {
    $path = Join-Path $baseDir $item.name
    $result[$item.name] = Analyze-Icon -path $path -expectedSize ([int]$item.size) -isMaskable ([bool]$item.maskable)
  }
  $std = $result["icon-512.png"]
  $mask = $result["icon-maskable-512.png"]
  $signatureDiff = [Math]::Sqrt(
    [Math]::Pow(([double]$std.mean_r - [double]$mask.mean_r), 2.0) +
    [Math]::Pow(([double]$std.mean_g - [double]$mask.mean_g), 2.0) +
    [Math]::Pow(([double]$std.mean_b - [double]$mask.mean_b), 2.0)
  )
  $result["consistency"] = @{
    ok = ($signatureDiff -le 48.0)
    detail = "mean color delta = $([Math]::Round($signatureDiff, 2))"
    delta = [Math]::Round($signatureDiff, 2)
  }
  return $result
}

function Show-Report([hashtable]$report) {
  Write-Host "`nIcon quality report:"
  foreach ($item in $required) {
    $name = [string]$item.name
    $row = $report[$name]
    $status = if ($row.ok) { "PASS" } else { "FAIL" }
    Write-Host (" - {0,-22} {1}  contrast={2}  stddev={3}  margin={4}" -f $name, $status, $row.contrast, $row.stddev, $row.margin)
    if (-not $row.ok) {
      Write-Host ("   detail: {0}" -f $row.detail)
    }
  }
  $consistency = $report["consistency"]
  $cStatus = if ($consistency.ok) { "PASS" } else { "FAIL" }
  Write-Host (" - {0,-22} {1}  {2}" -f "standard-maskable", $cStatus, $consistency.detail)
}

function Is-ReportOk([hashtable]$report) {
  foreach ($item in $required) {
    if (-not $report[[string]$item.name].ok) {
      return $false
    }
  }
  return [bool]$report["consistency"].ok
}

if (-not (Test-Path $iconDir)) {
  throw "Icon directory not found: $iconDir"
}

$initialReport = Evaluate-Icons -baseDir $iconDir
Show-Report -report $initialReport

if (Is-ReportOk -report $initialReport) {
  Write-Host "`nIcon checks passed. Existing icons kept."
  exit 0
}

if (-not $AttemptGenerate) {
  Write-Warning "Icon checks failed. Re-run with -AttemptGenerate to try automatic regeneration."
  exit 1
}

if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
  Write-Warning "OPENAI_API_KEY is missing. Skipping generation and keeping existing icons."
  exit 0
}

$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
$imageGenCli = Join-Path $codexHome "skills\\imagegen\\scripts\\image_gen.py"
if (-not (Test-Path $imageGenCli)) {
  Write-Warning "Image generation CLI not found at $imageGenCli. Skipping generation."
  exit 0
}

$tmpDir = Join-Path $RepoRoot "tmp\\icon-workflow"
if (-not (Test-Path $tmpDir)) {
  New-Item -Path $tmpDir -ItemType Directory -Force | Out-Null
}
$master = Join-Path $tmpDir "icon-master.png"

$prompt = "Use case: logo-brand. Asset type: PWA app icon. Primary request: Create a clean, modern icon for Codrex Remote with abstract screen-and-control symbolism. Style: flat vector-like, high contrast, teal/blue palette on dark-friendly background. Constraints: no text, no letters, no watermark, centered composition, readable at 48px."
Write-Host "`nGenerating replacement icon master..."
$generate = Start-Process -FilePath "python" -ArgumentList @(
  $imageGenCli,
  "generate",
  "--prompt", $prompt,
  "--size", "1024x1024",
  "--quality", "high",
  "--output-format", "png",
  "--out", $master
) -NoNewWindow -Wait -PassThru

if ($generate.ExitCode -ne 0 -or -not (Test-Path $master)) {
  Write-Warning "Image generation failed (exit $($generate.ExitCode)). Existing icons unchanged."
  exit 0
}

Write-Host "Writing icon variants..."
Save-ResizedIcon -source $master -dest (Join-Path $iconDir "icon-512.png") -size 512 -paddingRatio 0.0
Save-ResizedIcon -source $master -dest (Join-Path $iconDir "icon-192.png") -size 192 -paddingRatio 0.0
Save-ResizedIcon -source $master -dest (Join-Path $iconDir "icon-maskable-512.png") -size 512 -paddingRatio 0.12
Save-ResizedIcon -source $master -dest (Join-Path $iconDir "icon-maskable-192.png") -size 192 -paddingRatio 0.12
Save-ResizedIcon -source $master -dest (Join-Path $iconDir "apple-touch-icon.png") -size 180 -paddingRatio 0.0

$finalReport = Evaluate-Icons -baseDir $iconDir
Show-Report -report $finalReport
if (Is-ReportOk -report $finalReport) {
  Write-Host "`nRegenerated icons pass quality checks."
  exit 0
}

Write-Warning "Regenerated icons still fail checks. Review assets manually."
exit 1
