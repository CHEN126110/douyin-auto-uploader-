param()

$ErrorActionPreference = "Stop"

$configPath = "C:\Users\12611\.openclaw\openclaw.json"
if (-not (Test-Path $configPath)) {
  throw "OpenClaw config not found: $configPath"
}

$config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
$agents = @{}

$agents["main"] = [ordered]@{
  primary = $config.agents.defaults.model.primary
  fallbacks = @($config.agents.defaults.model.fallbacks)
}

$douyin = $config.agents.list | Where-Object { $_.id -eq "douyin" }
if ($null -ne $douyin) {
  $agents["douyin"] = [ordered]@{
    primary = $douyin.model.primary
    fallbacks = @($douyin.model.fallbacks)
  }
}

$aliases = [ordered]@{
  minimax = "scnet/MiniMax-M2.5"
  qwen = "bailian/qwen-plus"
  qwenmax = "bailian/qwen-max"
  coder = "bailian/qwen-coder-plus"
  qwenvl = "bailian/qwen-vl-plus"
}

[ordered]@{
  success = $true
  configPath = $configPath
  agents = $agents
  aliases = $aliases
} | ConvertTo-Json -Depth 10
