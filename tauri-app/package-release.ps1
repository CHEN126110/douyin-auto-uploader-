param(
    [switch]$SkipSidecarBuild,
    [switch]$SkipSmokeTest,
    [switch]$EmitUpdaterManifest,
    [string]$ReleaseNotes = ""
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

    # 自动更新签名：createUpdaterArtifacts 需要私钥才能生成 .sig 签名文件。
    # 私钥默认放在仓库外 %USERPROFILE%\.tauri-keys\，绝不进 git。
    if ($EmitUpdaterManifest -and -not $env:TAURI_SIGNING_PRIVATE_KEY) {
        $defaultKey = Join-Path $env:USERPROFILE ".tauri-keys\douyin-sock-publisher.key"
        if (Test-Path $defaultKey) {
            $env:TAURI_SIGNING_PRIVATE_KEY = $defaultKey
            if (-not $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) {
                # 密码存在仓库外的 password.txt（绝不进 git）；空密码在 tauri signer 里有歧义，必须用明确密码
                $pwFile = Join-Path $env:USERPROFILE ".tauri-keys\password.txt"
                if (Test-Path $pwFile) {
                    $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = (Get-Content $pwFile -Raw).Trim()
                } else {
                    throw "未找到签名密码文件: $pwFile（应包含生成密钥时用的密码）"
                }
            }
            Write-Host "[updater] 已加载签名私钥: $defaultKey"
        } else {
            throw "需要生成更新签名，但未找到私钥。请设置环境变量 TAURI_SIGNING_PRIVATE_KEY，或把私钥放到 $defaultKey"
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

    if ($EmitUpdaterManifest) {
        Write-Host "[updater] 生成 latest.json ..."
        $sigPath = "$($installer.FullName).sig"
        if (-not (Test-Path $sigPath)) {
            throw "未找到更新签名文件: $sigPath（确认 tauri.conf.json 的 bundle.createUpdaterArtifacts=true，且打包时已设签名私钥 TAURI_SIGNING_PRIVATE_KEY）"
        }
        $pkgVersion = (Get-Content (Join-Path $projectRoot "package.json") -Raw | ConvertFrom-Json).version
        $sigContent = (Get-Content $sigPath -Raw).Trim()

        # GitHub 上传 Release asset 时会把文件名里的非 ASCII 字符逐个替换成 '.'，
        # 中文产品名（抖音袜子发布工具_x.y.z_x64-setup.exe）传上去会变成一串点，
        # 用 URL 编码的中文名拼下载地址必然 404。所以统一改名成 ASCII 再发布，
        # 与 .github/workflows/release.yml 的 ASSET_PREFIX 保持一致。
        $assetPrefix = "DouyinSockPublisher"
        $assetName = "{0}_{1}_x64-setup.exe" -f $assetPrefix, $pkgVersion
        $stageDir = Join-Path $bundleDir "release-assets"
        New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
        Copy-Item $installer.FullName (Join-Path $stageDir $assetName) -Force
        Copy-Item $sigPath (Join-Path $stageDir ($assetName + ".sig")) -Force

        $downloadUrl = "https://github.com/CHEN126110/douyin-auto-uploader-/releases/download/v$pkgVersion/$assetName"
        $pubDate = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        $manifest = [ordered]@{
            version   = $pkgVersion
            notes     = $ReleaseNotes
            pub_date  = $pubDate
            platforms = [ordered]@{
                "windows-x86_64" = [ordered]@{
                    signature = $sigContent
                    url       = $downloadUrl
                }
            }
        }
        $json = $manifest | ConvertTo-Json -Depth 6
        $manifestPath = Join-Path $stageDir "latest.json"
        # 明确写 UTF-8 无 BOM：updater 解析 latest.json 不接受 BOM，notes 含中文需正确编码
        [System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "[updater] 待发布产物已就绪: $stageDir"
        Get-ChildItem $stageDir | ForEach-Object {
            Write-Host ("  {0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
        }
    }

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
    if ($EmitUpdaterManifest -and $installer) {
        $relVer = (Get-Content (Join-Path $projectRoot 'package.json') -Raw | ConvertFrom-Json).version
        Write-Host ""
        Write-Host "[updater] 发布步骤（让旧客户端能检测到更新）："
        Write-Host "  常规做法是打 tag 交给 GitHub Actions 自动发布："
        Write-Host "    git tag v$relVer; git push origin v$relVer"
        Write-Host "  手动发布时（不走 CI）："
        Write-Host "  1. 在 GitHub 仓库建一个 tag = v$relVer 的 Release"
        Write-Host "  2. 把 $stageDir 里的三个文件全部上传（exe / exe.sig / latest.json）"
        Write-Host "  3. 发布为正式版(非草稿、非预发布)，否则 releases/latest 命不中"
        Write-Host "  注意：不要重命名 asset，latest.json 里的下载地址按 ASCII 名硬拼"
    }
} finally {
    Pop-Location
}
