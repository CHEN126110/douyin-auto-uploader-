param(
    [Parameter(Mandatory = $true)]
    [string]$Tool,

    [string]$ArgsJson,

    [string[]]$Arg,

    [ValidateSet('json', 'text', 'markdown', 'raw')]
    [string]$Output = 'json'
)

$ErrorActionPreference = 'Stop'

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    try {
        $command = Get-Command $Name -ErrorAction Stop
        return $command.Source
    } catch {
        return $null
    }
}

function Resolve-McporterCliPath {
    $checkedPaths = New-Object System.Collections.Generic.List[string]

    if ($env:MCPORTER_CLI_PATH) {
        $checkedPaths.Add($env:MCPORTER_CLI_PATH)
        if (Test-Path $env:MCPORTER_CLI_PATH) {
            return @{
                CliPath = $env:MCPORTER_CLI_PATH
                CheckedPaths = $checkedPaths
            }
        }
    }

    $candidatePaths = New-Object System.Collections.Generic.List[string]

    if ($env:APPDATA) {
        $candidatePaths.Add((Join-Path $env:APPDATA 'npm\node_modules\mcporter\dist\cli.js'))
    }

    $npmPath = Resolve-CommandPath -Name 'npm'
    if ($npmPath) {
        try {
            $npmRoot = (& $npmPath root -g 2>$null | Select-Object -First 1).Trim()
            if ($npmRoot) {
                $candidatePaths.Add((Join-Path $npmRoot 'mcporter\dist\cli.js'))
            }
        } catch {
        }
    }

    foreach ($commandName in @('mcporter', 'mcporter.cmd', 'mcporter.ps1')) {
        $commandPath = Resolve-CommandPath -Name $commandName
        if (-not $commandPath) {
            continue
        }

        $commandDir = Split-Path -Parent $commandPath
        if ($commandDir) {
            $candidatePaths.Add((Join-Path $commandDir 'node_modules\mcporter\dist\cli.js'))
        }
    }

    foreach ($candidatePath in $candidatePaths | Select-Object -Unique) {
        $checkedPaths.Add($candidatePath)
        if (Test-Path $candidatePath) {
            return @{
                CliPath = $candidatePath
                CheckedPaths = $checkedPaths
            }
        }
    }

    throw @(
        'mcporter CLI not found.'
        'Checked paths:'
        ($checkedPaths | ForEach-Object { " - $_" })
        'Install mcporter or set MCPORTER_CLI_PATH to the full cli.js path.'
    ) -join [Environment]::NewLine
}

$nodePath = Resolve-CommandPath -Name 'node'
if (-not $nodePath) {
    throw 'Node.js command not found on PATH.'
}

$resolved = Resolve-McporterCliPath
$cliPath = $resolved.CliPath

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

& $nodePath @commandArgs
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    exit $exitCode
}
