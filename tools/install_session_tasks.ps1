#Requires -Version 5.1
<#
.SYNOPSIS
    Recreate / repair the two session-related scheduled tasks (DMR_SessionWatch,
    DMR_Desktop). Idempotent: safe to run repeatedly.

.DESCRIPTION
    Why this file exists
    --------------------
    DMR's autostart has three layers:
      L1  Startup\DMR_AutoUp.cmd        logon, interactive, visible console window
      L2  DMR_SessionWatch task         logon + unlock, moves DMR into your session
      L3  DMR_Boot task (boot_task.xml) session 0 backstop when nobody logs in

    L1 is just a file, L3 has tools\boot_task.xml. But L2 was originally created
    by ad-hoc commands typed into a shell and never written down -- so nobody
    could rebuild it. This script closes that gap.

    Trigger of L2: LogonTrigger + SessionStateChangeTrigger(SessionUnlock).
    Why unlock as well: RDP reconnect or local unlock after the machine was left
    at the lock screen re-fires it, so the DMR window follows you to the session
    you are actually looking at.

.PARAMETER User
    Account the tasks run as. Default Administrator.

.PARAMETER Remove
    Unregister both tasks instead of creating them.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_session_tasks.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_session_tasks.ps1 -Remove

.NOTES
    Requires an elevated shell (tasks run with RunLevel=Highest).
    ASCII ONLY -- Windows PowerShell 5.1 reads .ps1 as ANSI when there is no BOM,
    so any non-ASCII character here would be mangled. Same rule as the *.bat files.
#>
[CmdletBinding()]
param(
    [string]$User = 'Administrator',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$root = 'F:\DanmakuRender_AutoUp'
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$script = Join-Path $root 'tools\autostart_launch.py'

if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found: $pythonw" }
if (-not (Test-Path $script))  { throw "autostart_launch.py not found: $script" }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument 'tools\autostart_launch.py' `
                                  -WorkingDirectory $root

if ($Remove) {
    foreach ($n in @('DMR_SessionWatch', 'DMR_Desktop')) {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if ($t) { Unregister-ScheduledTask -TaskName $n -Confirm:$false; Write-Host "  [removed] $n" }
        else    { Write-Host "  [skip]    $n (not present)" }
    }
    return
}

# --- L2-a: logon + unlock -> migrate DMR into the interactive session ---------
# SessionStateChangeTrigger has no dedicated cmdlet in PS 5.1; build it via CIM.
$unlock = New-CimInstance -CimClass (Get-CimClass -ClassName MSFT_TaskSessionStateChangeTrigger `
        -Namespace Root/Microsoft/Windows/TaskScheduler) -ClientOnly
$unlock.StateChange = 8            # 8 = SessionUnlock
$unlock.UserId = $User
$triggers = @( (New-ScheduledTaskTrigger -AtLogOn -User $User), $unlock )

$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest

$watch = New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal
Register-ScheduledTask -TaskName 'DMR_SessionWatch' -InputObject $watch -Force | Out-Null
Write-Host '  [ok] DMR_SessionWatch  (logon + unlock -> autostart_launch.py)'

# --- L2-b: manual "bring the window over here" entry -------------------------
# No trigger: it only runs when you start it by hand from Task Scheduler or
# from tools\dmr-status.ps1 hints.
$desk = New-ScheduledTask -Action $action -Settings $settings -Principal $principal
Register-ScheduledTask -TaskName 'DMR_Desktop' -InputObject $desk -Force | Out-Null
Write-Host '  [ok] DMR_Desktop       (manual, no trigger)'

Write-Host ''
Write-Host 'Verify:'
foreach ($n in @('DMR_SessionWatch', 'DMR_Desktop')) {
    $t = Get-ScheduledTask -TaskName $n
    $tt = ($t.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ','
    Write-Host ("  {0,-18} State={1,-8} LogonType={2,-11} Triggers={3}" -f `
        $n, $t.State, $t.Principal.LogonType, $(if ($tt) { $tt } else { '(none)' }))
}
