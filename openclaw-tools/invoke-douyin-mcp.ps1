param(
    [Parameter(Mandatory = $true)]
    [string]$Tool,

    [string]$ArgsJson,

    [string[]]$Arg,

    [ValidateSet('json', 'text', 'markdown', 'raw')]
    [string]$Output = 'json'
)

$ErrorActionPreference = 'Stop'

$cliPath = 'C:\Users\12611\AppData\Roaming\npm\node_modules\mcporter\dist\cli.js'

if (-not (Test-Path $cliPath)) {
    throw "mcporter CLI not found: $cliPath"
}

$commandArgs = @(
    $cliPath
    'call'
    "douyin-publisher.$Tool"
)

if ($ArgsJson) {
    $commandArgs += @('--args', $ArgsJson)
}

$commandArgs += $Arg

$commandArgs += @('--output', $Output)

& node @commandArgs
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    exit $exitCode
}
