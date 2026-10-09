<#
.SYNOPSIS
  统一升级应用版本号（自动更新功能的版本一致性保障）。
.DESCRIPTION
  Tauri updater 用 tauri.conf.json 的 version 与 GitHub 上 latest.json 的 version 做 SemVer
  比较来决定要不要更新。版本号分散在 4 处，漏改任意一处都会导致"界面显示一个版本、
  更新器按另一个判断"的诡异问题。本脚本一次性把 4 处改成同一个值，UTF-8 无 BOM 写回
  （避免中文 cfg.yaml 乱码）。
.EXAMPLE
  ./scripts/bump-version.ps1 4.0.29
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$NewVersion
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# 校验 SemVer（updater 用 SemVer 比较，格式不对会判断失败）
if ($NewVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "版本号格式不合法: '$NewVersion'（需形如 4.0.29）"
}

# 本脚本位于 tauri-app/scripts/ 下
$tauriApp = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$repoRoot = Split-Path -Parent $tauriApp

function Set-Utf8NoBom([string]$Path, [string]$Content) {
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

# 1. tauri-app/package.json（顶层 version）
$pkgPath = Join-Path $tauriApp "package.json"
$pkg = Get-Content $pkgPath -Raw -Encoding UTF8
$pkg = $pkg -replace '("version"\s*:\s*")[^"]+(")', "`${1}$NewVersion`${2}"
Set-Utf8NoBom $pkgPath $pkg

# 2. tauri-app/src-tauri/Cargo.toml（[package] 段行首 version，不动依赖里的 version = "2"）
$cargoPath = Join-Path $tauriApp "src-tauri\Cargo.toml"
$cargo = Get-Content $cargoPath -Raw -Encoding UTF8
$cargo = $cargo -replace '(?m)^(version\s*=\s*")[^"]+(")', "`${1}$NewVersion`${2}"
Set-Utf8NoBom $cargoPath $cargo

# 3. tauri-app/src-tauri/tauri.conf.json（updater 比对的权威版本）
$confPath = Join-Path $tauriApp "src-tauri\tauri.conf.json"
$conf = Get-Content $confPath -Raw -Encoding UTF8
$conf = $conf -replace '("version"\s*:\s*")[^"]+(")', "`${1}$NewVersion`${2}"
Set-Utf8NoBom $confPath $conf

# 4. 根 cfg.yaml（base.version，后端业务版本，影响 /health 与关于页显示）
$cfgPath = Join-Path $repoRoot "cfg.yaml"
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8
$cfg = $cfg -replace '(?m)^(\s*version:\s*).+$', "`${1}$NewVersion"
Set-Utf8NoBom $cfgPath $cfg

# 锁文件中的应用版本也必须同步；不改任何依赖的版本。
$npmLockPath = Join-Path $tauriApp "package-lock.json"
$npmLock = Get-Content $npmLockPath -Raw -Encoding UTF8
$npmLock = $npmLock -replace '(?m)^(  "version"\s*:\s*")[^"]+(")', "`${1}$NewVersion`${2}"
$npmLock = $npmLock -replace '(?s)(""\s*:\s*\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"version"\s*:\s*")[^"]+(")', "`${1}$NewVersion`${2}"
Set-Utf8NoBom $npmLockPath $npmLock
$cargoLockPath = Join-Path $tauriApp "src-tauri\Cargo.lock"
$cargoLock = Get-Content $cargoLockPath -Raw -Encoding UTF8
$cargoLock = $cargoLock -replace '(?m)(^name = "douyin-sock-publisher"\r?\nversion = ")[^"]+(")', "`${1}$NewVersion`${2}"
Set-Utf8NoBom $cargoLockPath $cargoLock

foreach ($copyPath in @((Join-Path $tauriApp 'cfg.yaml'), (Join-Path $tauriApp 'python-sidecar\cfg.yaml'))) {
    $copy = Get-Content $copyPath -Raw -Encoding UTF8
    $copy = $copy -replace '(?m)^(\s*version:\s*).+$', "`${1}$NewVersion"
    Set-Utf8NoBom $copyPath $copy
}

Write-Host "版本号已统一更新为 $NewVersion："
Write-Host "  - $pkgPath"
Write-Host "  - $cargoPath"
Write-Host "  - $confPath"
Write-Host "  - $cfgPath"
Write-Host ""
Write-Host "下一步：npm run package:release -- -EmitUpdaterManifest -ReleaseNotes ""本次更新说明"""
