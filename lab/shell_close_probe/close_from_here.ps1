# close_from_here.ps1 -- send close request(s) to an instance started by launch_only.ps1.
# Works from Windows PowerShell 5.1 and PowerShell 7. ASCII only.
#   <powershell.exe|pwsh> -File close_from_here.ps1 -InfoFile <launch-info.txt> -Method post|sys|cmw|all
param(
    [Parameter(Mandatory = $true)][string]$InfoFile,
    [ValidateSet('post', 'sys', 'cmw', 'all')][string]$Method = 'post',
    [int]$WaitSec = 10
)
. "$PSScriptRoot\Probe-Lib.ps1"
$kv = @{}
Get-Content -LiteralPath $InfoFile | ForEach-Object { $p = $_ -split '=', 2; if ($p.Count -eq 2) { $kv[$p[0]] = $p[1] } }
$procId = [int]$kv['pid']
$hwnd = [IntPtr][int64]$kv['hwnd']
$tid = [uint32]$kv['tid']
$dataDir = $kv['datadir']
Write-Output ("host: PSVersion={0} edition={1} pid={2}" -f $PSVersionTable.PSVersion, $PSVersionTable.PSEdition, $PID)
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
if (-not $proc) { Write-Output 'target already gone'; exit 2 }
if ($proc.ProcessName -ne 'douyin-sock-publisher') { throw "pid $procId is '$($proc.ProcessName)', not an app instance; refusing" }
Show-ProbeThreads $procId 'before' $tid -GuiOnly
Write-Output ("responding(WM_NULL)={0} IsHungAppWindow={1}" -f (Test-Responding $hwnd), [W32]::IsHungAppWindow($hwnd))
$methods = @($Method)
if ($Method -eq 'all') { $methods = @('post', 'sys', 'cmw') }
foreach ($m in $methods) {
    Write-Output ("=== close via '{0}' ===" -f $m)
    switch ($m) {
        'post' { Send-PostClose $hwnd }
        'sys'  { Send-SysClose $hwnd }
        'cmw'  { $proc.Refresh(); Write-Output ("CloseMainWindow() -> {0}" -f $proc.CloseMainWindow()) }
    }
    if ($proc.WaitForExit($WaitSec * 1000)) { Write-Output ("exited code={0}" -f $proc.ExitCode); break }
    Write-Output ("still running after ${WaitSec}s via '{0}'" -f $m)
}
if ($dataDir) { Show-RuntimeLog $dataDir 'final' }
