$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding

$launcher = Join-Path $PSScriptRoot 'start-hidden.vbs'
$iconSource = Join-Path $PSScriptRoot 'tauri-app\src-tauri\icons\icon.ico'
foreach ($requiredFile in @($launcher, $iconSource, (Join-Path $PSScriptRoot 'start_frontend.bat'))) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "找不到启动所需文件：$requiredFile"
    }
}
$iconBytes = [IO.File]::ReadAllBytes($iconSource)
if ($iconBytes.Length -lt 6 -or [BitConverter]::ToString($iconBytes[0..3]) -ne '00-00-01-00') {
    throw "图标不是有效的 Windows ICO 文件：$iconSource"
}

$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$shortcutPath = Join-Path $desktop '抖音袜子发布工具.lnk'
if (Test-Path -LiteralPath $shortcutPath) {
    $backupDir = Join-Path $PSScriptRoot ('.tmp\shortcut-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Copy-Item -LiteralPath $shortcutPath -Destination (Join-Path $backupDir 'shortcut.lnk')
}

# 按图标内容使用新文件名，让 Explorer 读取正确图标，避免依赖旧缓存。
$iconDir = Join-Path $env:LOCALAPPDATA 'com.dyin.sock-publisher\icons'
New-Item -ItemType Directory -Path $iconDir -Force | Out-Null
$iconHash = (Get-FileHash -LiteralPath $iconSource -Algorithm SHA256).Hash.Substring(0, 12)
$iconPath = Join-Path $iconDir "dev-$iconHash.ico"
Copy-Item -LiteralPath $iconSource -Destination $iconPath -Force

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$shortcut.Arguments = '"' + $launcher + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.IconLocation = $iconPath + ',0'
$shortcut.Description = '抖音袜子发布工具（开发版）'
$shortcut.WindowStyle = 1
$shortcut.Save()
Write-Output "已修复桌面快捷方式：$shortcutPath"
