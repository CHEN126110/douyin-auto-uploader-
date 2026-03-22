param(
  [Parameter(Mandatory = $true)]
  [string]$AgentId,

  [Parameter(Mandatory = $true)]
  [string]$Model,

  [switch]$RestartGateway
)

$ErrorActionPreference = "Stop"

$configPath = "C:\Users\12611\.openclaw\openclaw.json"
if (-not (Test-Path $configPath)) {
  throw "OpenClaw config not found: $configPath"
}

$aliasMap = @{
  "minimax" = "scnet/MiniMax-M2.5"
  "qwen" = "bailian/qwen-plus"
  "qwenmax" = "bailian/qwen-max"
  "coder" = "bailian/qwen-coder-plus"
  "qwenvl" = "bailian/qwen-vl-plus"
}

$agentKey = $AgentId.Trim().ToLower()
$modelKey = $Model.Trim()
$resolvedModel = if ($aliasMap.ContainsKey($modelKey.ToLower())) { $aliasMap[$modelKey.ToLower()] } else { $modelKey }

$mainFallbacks = @(
  "scnet/MiniMax-M2.5",
  "bailian/qwen-plus",
  "bailian/qwen-max",
  "bailian/qwen-coder-plus"
) | Where-Object { $_ -ne $resolvedModel }

$douyinFallbacks = @(
  "scnet/MiniMax-M2.5",
  "bailian/qwen-max",
  "bailian/qwen-plus",
  "bailian/qwen-vl-plus"
) | Where-Object { $_ -ne $resolvedModel }

$config = Get-Content -Raw -Path $configPath | ConvertFrom-Json

switch ($agentKey) {
  "main" {
    $config.agents.defaults.model.primary = $resolvedModel
    $config.agents.defaults.model.fallbacks = @($mainFallbacks)
    $targetFallbacks = @($config.agents.defaults.model.fallbacks)
  }
  "douyin" {
    $target = $config.agents.list | Where-Object { $_.id -eq "douyin" }
    if ($null -eq $target) {
      throw "Agent not found: douyin"
    }
    $target.model.primary = $resolvedModel
    $target.model.fallbacks = @($douyinFallbacks)
    $targetFallbacks = @($target.model.fallbacks)
  }
  default {
    throw "Unsupported AgentId: $AgentId"
  }
}

$config | ConvertTo-Json -Depth 100 | Set-Content -Path $configPath -Encoding UTF8

$gatewayResult = "unchanged"
if ($RestartGateway) {
  & openclaw gateway stop | Out-Null
  Start-Sleep -Seconds 2
  & openclaw gateway start | Out-Null
  $gatewayResult = "restarted"
}

[ordered]@{
  success = $true
  agent = $agentKey
  model = $resolvedModel
  fallbacks = $targetFallbacks
  gateway = $gatewayResult
} | ConvertTo-Json -Depth 10
