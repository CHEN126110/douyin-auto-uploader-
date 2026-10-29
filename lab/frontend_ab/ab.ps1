# 前端「改动前 / 改动后」A/B 对照验证的环境脚本（用法见同目录 README.md）。
#
#   .\ab.ps1 setup                      建工作目录 + Python 虚拟环境 + 假商品 + 基线数据（只需做一次）
#   .\ab.ps1 orig -Src <目录>           生成「原版」前端副本（端口 1421）；<目录> 是改动前备份下来的 src
#   .\ab.ps1 prep [-WashLabel] [-Mock <json>]   恢复隔离数据、重启隔离 Sidecar(5002)、重启代理(5003)、设置假场景
#   .\ab.ps1 stop                       停掉后端与代理
#
# 端口约定（**不碰 5001**：那是真实桌面应用的 Sidecar，里面是用户的真实数据，验证时它可能正在运行）：
#   代理 5003（可用 AB_PROXY_PORT 改；转发到隔离 Sidecar 5002 并记录 / 假响应）、
#   新代码 Vite 1420、原版 Vite 1421。前端写死的 5001 由 vite.ab.config.mts 在开发服务器里改写成代理端口，
#   所以两个前端都必须用该配置启动（见 README）；harness.js 在每个场景开跑前还会再核对一次。
# 所有数据都在 $env:AB_WORK（默认 lab/frontend_ab/.work）下，不碰用户真实数据目录。
param(
    [Parameter(Position = 0, Mandatory = $true)][ValidateSet('setup', 'orig', 'prep', 'stop')][string]$Cmd,
    [string]$Src = '',
    [string]$Mock = '',
    [switch]$WashLabel
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = (Resolve-Path (Join-Path $here '..\..')).Path
$work = if ($env:AB_WORK) { $env:AB_WORK } else { Join-Path $here '.work' }
$py = if ($env:AB_PY) { $env:AB_PY } else { Join-Path $work 'venv\Scripts\python.exe' }
$data = Join-Path $work 'backend-data'
$pristine = Join-Path $work 'pristine-data'
$sidecarDir = Join-Path $repo 'tauri-app\python-sidecar'
$proxyPort = if ($env:AB_PROXY_PORT) { [int]$env:AB_PROXY_PORT } else { 5003 }
$backendPort = 5002
if ($proxyPort -eq 5001 -or $backendPort -eq 5001) { throw '5001 是真实桌面应用的端口，验证工具不能使用' }
$proxyUrl = "http://127.0.0.1:$proxyPort"

# 默认假场景：删除类接口只返回成功（不碰数据），其余转发隔离后端；发布类接口由各场景自己按需开启假响应
$defaultMock = '{"mock_platform":null,"upload_mode":"success","start_mode":"ok","freight_mode":null,"settings_fail":false,"external_tasks":[],"taobao_external":[],"taobao_mode":"fill_ok","xhs_ok":true,"capture_mode":null,"mock_deletes":true,"mock_publish_save":false,"reset_tasks":true}'

# 只停本工具自己起的进程：先核对命令行；对不上（端口被别的程序占着，比如真实应用）就中止，绝不乱杀。
function Stop-Port([int]$port, [string]$expected) {
    Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | ForEach-Object {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)"
        if ($proc -and $proc.CommandLine -match $expected) {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        } else {
            throw "端口 $port 被别的程序占用（pid=$($_.OwningProcess) $($proc.CommandLine)），不是本工具启动的，已中止，没有动它"
        }
    }
}

function Wait-Url([string]$url, [int]$seconds = 30) {
    for ($i = 0; $i -lt $seconds * 2; $i++) {
        Start-Sleep -Milliseconds 500
        try { if ((Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2).StatusCode -eq 200) { return $true } } catch { }
    }
    return $false
}

function Start-Backend {
    $env:PYTHONUTF8 = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:SIDECAR_MODE = '1'; $env:SIDECAR_PORT = "$backendPort"
    $env:DOUYIN_DATA_DIR = $data
    # 后端会往 %LOCALAPPDATA%\com.dyin.sock-publisher\logs 写引导日志：也指到工作目录，不写用户目录
    $env:LOCALAPPDATA = Join-Path $work 'localappdata'
    Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory $sidecarDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $work 'backend.out.log') -RedirectStandardError (Join-Path $work 'backend.err.log')
    if (-not (Wait-Url "http://127.0.0.1:$backendPort/health" 40)) { throw '后端没有在 40 秒内就绪，见 backend.err.log' }
}

function Start-Proxy {
    Stop-Port $proxyPort 'proxy_mock\.py'
    Start-Sleep -Seconds 1
    $env:PYTHONUTF8 = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'; $env:AB_WORK = $work; $env:AB_PROXY_PORT = "$proxyPort"
    Start-Process -FilePath $py -ArgumentList (Join-Path $here 'proxy_mock.py') -WorkingDirectory $here -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $work 'proxy.out.log') -RedirectStandardError (Join-Path $work 'proxy.err.log')
    if (-not (Wait-Url "$proxyUrl/__ctl/state" 15)) { throw '代理没有就绪，见 proxy.err.log' }
}

switch ($Cmd) {
    'setup' {
        New-Item -ItemType Directory -Force $work, (Join-Path $work 'captures') | Out-Null
        if (-not (Test-Path $py)) {
            Write-Output '创建 Python 3.11 虚拟环境并安装后端依赖子集（需要几分钟）…'
            & py -3.11 -m venv (Join-Path $work 'venv')
            $env:PYTHONUTF8 = '1'
            & $py -m pip install --disable-pip-version-check -q flask flask-cors peewee requests websocket-client aiohttp psutil DrissionPage pillow pyyaml ruamel.yaml Flask-JWT-Extended natsort py7zr numpy scipy
        }
        $fixtures = Join-Path $work 'fixtures'
        & $py (Join-Path $here 'make_fixtures.py') $fixtures
        # 用空数据目录起一次后端，导入假商品，再把数据目录存成「基线」
        Stop-Port $backendPort 'app\.py'
        if (Test-Path $data) { Remove-Item -Recurse -Force $data }
        Start-Backend
        $paths = Get-ChildItem $fixtures -Directory | ForEach-Object { $_.FullName }
        $body = @{ paths = @($paths) } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$backendPort/api/import/folders" -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
        Stop-Port $backendPort 'app\.py'
        Start-Sleep -Seconds 2
        if (Test-Path $pristine) { Remove-Item -Recurse -Force $pristine }
        Copy-Item -Recurse $data $pristine
        Write-Output "基线数据已建立：$pristine"
    }
    'orig' {
        if (-not $Src) { throw '用法：.\ab.ps1 orig -Src <改动前备份的 src 目录>' }
        $app = Join-Path $work 'orig-app'
        if (Test-Path $app) {
            # 副本里的 node_modules 是指向 tauri-app\node_modules 的联接点。递归删除前先单独摘掉它：
            # Directory.Delete（非递归）对联接点只删链接本身，绝不会动到真实的 node_modules；
            # 如果它碰巧是个真目录（非空），这里会直接报错中止，而不是递归删下去。
            $nm = Join-Path $app 'node_modules'
            if (Test-Path $nm) { [System.IO.Directory]::Delete($nm) }
            Remove-Item -Recurse -Force $app
        }
        New-Item -ItemType Directory $app | Out-Null
        foreach ($f in 'index.html', 'package.json', 'tsconfig.json', 'tsconfig.node.json', 'vite.config.ts') {
            Copy-Item (Join-Path $repo "tauri-app\$f") $app
        }
        Copy-Item -Recurse $Src (Join-Path $app 'src')
        $cfg = Join-Path $app 'vite.config.ts'
        $text = (Get-Content $cfg -Raw -Encoding UTF8).Replace('port: 1420,', 'port: 1421,').Replace('base: "./",', "base: `"./`",`n  cacheDir: `"../orig-vite-cache`",")
        [IO.File]::WriteAllText($cfg, $text, (New-Object Text.UTF8Encoding($false)))
        # 验证用配置包装（把前端写死的 5001 改写成代理端口）；模板里的路径换成副本里的 ./vite.config
        $wrap = (Get-Content (Join-Path $here 'vite.ab.config.mts') -Raw -Encoding UTF8).Replace('../../tauri-app/vite.config', './vite.config')
        [IO.File]::WriteAllText((Join-Path $app 'vite.ab.config.mts'), $wrap, (New-Object Text.UTF8Encoding($false)))
        New-Item -ItemType Junction -Path (Join-Path $app 'node_modules') -Target (Join-Path $repo 'tauri-app\node_modules') | Out-Null
        Write-Output "原版副本已生成：$app（在该目录里 npm run dev -- --config vite.ab.config.mts 即在 1421 端口起原版）"
    }
    'prep' {
        if (-not (Test-Path $pristine)) { throw '还没有基线数据，请先 .\ab.ps1 setup' }
        Stop-Port $backendPort 'app\.py'
        Start-Sleep -Seconds 2
        if (Test-Path $data) { Remove-Item -Recurse -Force $data }
        Copy-Item -Recurse $pristine $data
        Start-Backend
        if (-not (Wait-Url "$proxyUrl/__ctl/state" 2)) { Start-Proxy }
        Invoke-RestMethod -Method Post -Uri "$proxyUrl/__ctl/reset" | Out-Null
        if ($WashLabel) {
            $env:AB_WORK = $work
            & $py (Join-Path $here 'setup_washlabel.py')
            Invoke-RestMethod -Method Post -Uri "$proxyUrl/__ctl/reset" | Out-Null
        }
        $json = if ($Mock) { $Mock } else { $defaultMock }
        Invoke-RestMethod -Method Post -Uri "$proxyUrl/__ctl/mock" -Body $json | Out-Null
        Write-Output 'prep 完成'
    }
    'stop' {
        Stop-Port $backendPort 'app\.py'
        Stop-Port $proxyPort 'proxy_mock\.py'
        Write-Output '已停止后端与代理'
    }
}
