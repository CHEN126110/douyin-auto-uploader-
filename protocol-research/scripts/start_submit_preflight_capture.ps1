$ErrorActionPreference = "Stop"

param(
  [string]$Profile = "submit-preflight",
  [string]$Sample = "current_page",
  [string]$Timestamp = "",
  [int]$DurationMs = 120000
)

if (-not $Timestamp) {
  $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
}

$projectRoot = "e:\Script Project\Dyin\beiufen\2.0"
$mcpServerDir = Join-Path $projectRoot "mcp-server"
$outputDir = Join-Path $projectRoot "protocol-research\captures\submit-preflight"
$outputPath = Join-Path $outputDir ("fxg_protocol_capture_{0}_{1}_{2}.json" -f $Profile.Replace("-", "_"), $Sample, $Timestamp)

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

Set-Location $mcpServerDir

$env:DOUYIN_CDP_LIST_URL = "http://127.0.0.1:9333/json/list"
$env:DURATION_MS = [string]$DurationMs
$env:CAPTURE_PROFILE = $Profile
$env:OUTPUT_PATH = $outputPath

Write-Host "Starting preflight capture..."
Write-Host ("Profile: {0}" -f $Profile)
Write-Host ("Sample:  {0}" -f $Sample)
Write-Host ("Output:  {0}" -f $outputPath)
Write-Host ""
Write-Host "During the capture window, manually drive the page close to the target action."
Write-Host "This script only starts local blocked capture. It does not claim success for any endpoint."

npm run capture:fxg-protocol
