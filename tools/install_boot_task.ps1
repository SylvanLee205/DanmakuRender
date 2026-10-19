# Re-register the DMR boot task with correct settings (ASCII only).
#
# Why this script exists
# ---------------------
# `schtasks /create /sc onstart` leaves ExecutionTimeLimit = PT72H. Task Scheduler
# then STOPS the task after 3 days, which kills DMR with it (the task runs
# Start_Render.bat in foreground on purpose, so task state == DMR state).
#
# `Set-ScheduledTask -Settings ...` cannot modify a task whose principal uses
# LogonType=Password without re-supplying the password; it fails with
# 0x8007052e "The user name or password is incorrect". So we re-register the
# whole task here and ask for the password exactly once.
#
# IMPORTANT: -Principal and -Password belong to DIFFERENT parameter sets.
# Using both raises "Parameter set cannot be resolved". Use -User / -Password /
# -RunLevel together instead.

$ErrorActionPreference = 'Stop'

$taskName = 'DanmakuRender_Boot'
$bat      = 'F:\DanmakuRender_AutoUp\Run_DMR.bat'
$workdir  = 'F:\DanmakuRender_AutoUp'

if (-not (Test-Path $bat)) { throw "missing action file: $bat" }

$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $workdir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$runAs = "$env:COMPUTERNAME\Administrator"

Write-Host 'Re-registering task with: unlimited runtime, start if missed, ignore new instance.'
$pwd = Read-Host -AsSecureString 'Password for Administrator'

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -User $runAs -Password $pwd -RunLevel Highest -Force | Out-Null

$t = Get-ScheduledTask -TaskName $taskName
$i = Get-ScheduledTaskInfo -TaskName $taskName

Write-Host ''
Write-Host "TaskName           : $($t.TaskName)"
Write-Host "State              : $($t.State)"
Write-Host "RunAs              : $($t.Principal.UserId) / $($t.Principal.LogonType) / $($t.Principal.RunLevel)"
Write-Host "ExecutionTimeLimit : $($t.Settings.ExecutionTimeLimit)    (PT0S means unlimited)"
Write-Host "StartWhenAvailable : $($t.Settings.StartWhenAvailable)"
Write-Host "LastRun / Result   : $($i.LastRunTime) / $($i.LastTaskResult)"
Write-Host ''

if ($t.Settings.ExecutionTimeLimit -eq 'PT0S') {
    Write-Host 'OK - 72 hour limit removed.'
} else {
    Write-Host 'WARNING - time limit was not applied. Tell the assistant what you see above.'
}
