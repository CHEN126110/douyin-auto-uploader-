param(
    [switch]$SkipSidecarBuild,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseExe = Join-Path $projectRoot "src-tauri\\target\\release\\douyin-sock-publisher.exe"
$bundleDir = Join-Path $projectRoot "src-tauri\\target\\release\\bundle\\nsis"
$appDataDir = Join-Path $env:LOCALAPPDATA "com.dyin.sock-publisher"
$logDir = Join-Path $appDataDir "logs"
$runtimeLog = Join-Path $logDir "tauri-runtime.log"
$sidecarStdoutLog = Join-Path $logDir "python-backend.stdout.log"
$sidecarStderrLog = Join-Path $logDir "python-backend.stderr.log"

function Stop-ReleaseProcesses {
    Get-Process -Name "python-backend", "douyin-sock-publisher" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    try {
        Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object {
                if ($_ -and $_ -gt 0) {
                    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
                }
            }
    } catch {
    }
}

function Reset-SmokeLogs {
    @($runtimeLog, $sidecarStdoutLog, $sidecarStderrLog) | ForEach-Object {
        if (Test-Path $_) {
            Remove-Item $_ -Force -ErrorAction SilentlyContinue
        }
    }
}

function Show-SmokeDiagnostics {
    Write-Host ""
    Write-Host "[diagnostics] app data dir: $appDataDir"
    foreach ($logPath in @($runtimeLog, $sidecarStdoutLog, $sidecarStderrLog)) {
        Write-Host "[diagnostics] $logPath"
        if (Test-Path $logPath) {
            Get-Content -Path $logPath -Tail 120
        } else {
            Write-Host "  (missing)"
        }
    }
}

Push-Location $projectRoot
try {
    Stop-ReleaseProcesses
    Start-Sleep -Milliseconds 500

    if (-not $SkipSidecarBuild) {
        Write-Host "[1/3] Building Python sidecar..."
        & python ".\\python-sidecar\\build_sidecar.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Python sidecar build failed with exit code $LASTEXITCODE"
        }
    }

    Write-Host "[2/3] Building Tauri release..."
    & npm.cmd run tauri:build
    if ($LASTEXITCODE -ne 0) {
        throw "Tauri release build failed with exit code $LASTEXITCODE"
    }

    if (-not (Test-Path $releaseExe)) {
        throw "Release executable not found: $releaseExe"
    }

    $installer = Get-ChildItem $bundleDir -Filter "*-setup.exe" -ErrorAction Stop |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $SkipSmokeTest) {
        Write-Host "[3/3] Running packaged smoke test..."
        Stop-ReleaseProcesses
        Reset-SmokeLogs
        Start-Sleep -Seconds 1

        $process = $null
        try {
            $process = Start-Process -FilePath $releaseExe -PassThru
            $deadline = (Get-Date).AddSeconds(60)
            $healthy = $false

            while ((Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 800

                if ($process.HasExited) {
                    throw "Release executable exited early with code $($process.ExitCode)"
                }

                try {
                    $response = Invoke-WebRequest -Uri "http://127.0.0.1:5001/health" -TimeoutSec 5
                    if ($response.StatusCode -eq 200) {
                        $health = $response.Content | ConvertFrom-Json
                        $healthy = $true
                        break
                    }
                } catch {
                }
            }

            if (-not $healthy) {
                Show-SmokeDiagnostics
                throw "Packaged smoke test failed: backend health endpoint did not become ready."
            }
        } finally {
            if ($process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
            Stop-ReleaseProcesses
        }
    }

    Write-Host ""
    Write-Host "Build complete."
    Write-Host "Release EXE: $releaseExe"
    if ($installer) {
        Write-Host "Installer: $($installer.FullName)"
    }
} finally {
    Pop-Location
}
