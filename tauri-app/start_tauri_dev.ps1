param([switch]$NoPause, [switch]$Dev)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
$exitCode = 0
$launcherMutex = $null
$mutexAcquired = $false
$logFile = $null

function Write-LaunchMessage([string]$Message) {
    Write-Host $Message
    if ($logFile) {
        Add-Content -LiteralPath $logFile -Value $Message -Encoding UTF8
    }
}

try {
    $launcherMutex = [System.Threading.Mutex]::new($false, 'Local\DouyinSockPublisherDevLauncher')
    try {
        $mutexAcquired = $launcherMutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $mutexAcquired = $true
    }
    if (-not $mutexAcquired) {
        Write-Host '[提示] 开发版正在启动或运行中，请稍候。'
        $exitCode = 20
        exit $exitCode
    }

    if ($NoPause) {
        $logDir = Join-Path $env:LOCALAPPDATA 'com.dyin.sock-publisher\logs'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        $logFile = Join-Path $logDir 'dev-launch.log'
        [IO.File]::WriteAllText($logFile, '', [System.Text.UTF8Encoding]::new($false))
    }
    Set-Location -LiteralPath $PSScriptRoot
    Write-LaunchMessage '========================================'
    Write-LaunchMessage '抖音袜子发布工具 - 开发版'
    Write-LaunchMessage '========================================'
    Write-LaunchMessage "前端目录：$PSScriptRoot"

    # 低完整性的工作区会让新编译的 EXE 以低权限运行，无法写入 AppData。
    # 仅将两处构建产物目录标记为普通用户的中完整性，不修改 DACL 或业务数据目录。
    $releaseDir = Join-Path $PSScriptRoot 'src-tauri\target\release'
    $sidecarDir = Join-Path $PSScriptRoot 'src-tauri\sidecar'
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
    $icacls = Join-Path $env:WINDIR 'System32\icacls.exe'
    foreach ($artifactDir in @($releaseDir, $sidecarDir)) {
        if (-not (Test-Path -LiteralPath $artifactDir -PathType Container)) {
            throw "找不到构建产物目录：$artifactDir"
        }
        $integrityResult = & $icacls $artifactDir /setintegritylevel '(OI)(CI)M' 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "无法设置构建产物的正常运行级别：$artifactDir`n$($integrityResult -join "`n")"
        }
    }

    # 日常入口只启动内置前端的已构建程序；编译仅由显式 -Dev 进入。
    $appExe = Join-Path $releaseDir 'douyin-sock-publisher.exe'
    $existingApps = @(Get-CimInstance Win32_Process -Filter "Name = 'douyin-sock-publisher.exe'")
    if ($existingApps.Count -gt 0) {
        if (@($existingApps | Where-Object { $_.ExecutablePath -ne $appExe }).Count -gt 0) {
            throw '另一版本正在运行，请先关闭后再启动当前工作区。'
        }
        Write-LaunchMessage '[提示] 当前工作区应用已在运行，不重复启动。'
        exit 0
    }
    if (-not $Dev) {
        if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
            throw '尚无可启动的桌面构建。请先执行 npm run tauri:build -- --no-bundle；普通启动不会自动编译。'
        }
        # 询问程序自己的构建类型。release 优化可能拆分字符串常量，不能扫描 EXE 文本判版本。
        $probeInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $probeInfo.FileName = $appExe
        $probeInfo.Arguments = '--desktop-startup-check'
        $probeInfo.UseShellExecute = $false
        $probeInfo.CreateNoWindow = $true
        $probeProcess = [System.Diagnostics.Process]::Start($probeInfo)
        try {
            if (-not $probeProcess.WaitForExit(5000)) {
                $probeProcess.Kill()
                throw '桌面构建类型检查超时，未启动编译。'
            }
            if ($probeProcess.ExitCode -ne 0) {
                throw '当前 EXE 是依赖前端服务的开发壳，请先执行 npm run tauri:build -- --no-bundle 生成内置前端版本。'
            }
        } finally {
            $probeProcess.Dispose()
        }
        Write-LaunchMessage "[启动] 直接启动内置前端的应用（不编译、不启动前端服务）：$appExe"
        Start-Process -FilePath $appExe -WorkingDirectory $releaseDir | Out-Null
    }

    if ($Dev) {
        $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
        Get-Command cargo.exe -ErrorAction Stop | Out-Null

        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'node_modules') -PathType Container)) {
            Write-LaunchMessage '[准备] 正在安装前端依赖...'
            if ($NoPause) {
                & $env:ComSpec /d /c ('call "' + $npm + '" install >> "' + $logFile + '" 2>&1')
            } else {
                & $npm install
            }
            if ($LASTEXITCODE -ne 0) {
                throw "前端依赖安装失败，退出码：$LASTEXITCODE"
            }
        }

        Write-LaunchMessage '[启动] 正在启动开发版；首次编译可能需要几分钟，请稍候。'
        if ($NoPause) {
            & $env:ComSpec /d /c ('call "' + $npm + '" run tauri:dev >> "' + $logFile + '" 2>&1')
        } else {
            & $npm run tauri:dev
        }
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            Write-LaunchMessage '[结束] 应用已退出。'
        } else {
            Write-LaunchMessage "[错误] 开发版启动或运行失败，退出码：$exitCode"
        }
    }
} catch {
    $exitCode = 1
    Write-LaunchMessage "[错误] 启动失败：$($_.Exception.Message)"
} finally {
    if ($mutexAcquired) { $launcherMutex.ReleaseMutex() }
    if ($launcherMutex) { $launcherMutex.Dispose() }
    if (-not $NoPause) {
        Read-Host '按回车键关闭此窗口' | Out-Null
    }
}
exit $exitCode
