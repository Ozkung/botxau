<#
.SYNOPSIS
    Register a Scheduled Task that restarts the bot after a VPS reboot.

.DESCRIPTION
    Trigger is "at log on", not "at startup", on purpose: the MetaTrader 5
    terminal is a desktop application and the Python package talks to it over
    IPC inside an interactive session. A task running as SYSTEM before anyone
    logs in would find no terminal to connect to.

    So the VPS still has to reach a logged-in desktop session by itself -
    configure auto-logon on the VPS and have MT5 start with Windows.

    Register:    powershell -ExecutionPolicy Bypass -File installer\install-task.ps1
    Remove:      powershell -ExecutionPolicy Bypass -File installer\uninstall-task.ps1

.PARAMETER TaskName
    Name of the scheduled task. Default: XAUUSD-bot

.PARAMETER DelaySeconds
    Seconds to wait after log on before starting, so MT5 can come up first.
#>
[CmdletBinding()]
param(
    [string]$TaskName = "XAUUSD-bot",
    [int]$DelaySeconds = 120
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\run_live.py"

if (-not (Test-Path $VenvPython)) { throw "Not installed yet - run install.bat first." }
if (-not (Test-Path (Join-Path $Root "config.yaml"))) { throw "config.yaml is missing - run install.bat first." }

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Task '$TaskName' already exists - replacing it."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $VenvPython `
    -Argument "`"$Script`" --config `"$(Join-Path $Root 'config.yaml')`"" `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT${DelaySeconds}S"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 2) -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "XAUUSD Asian-range breakout bot (MT5)" | Out-Null

Write-Host ""
Write-Host "Registered scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  Runs:      $VenvPython $Script"
Write-Host "  Trigger:   at log on of $env:USERNAME, ${DelaySeconds}s delay"
Write-Host "  Restart:   every 2 minutes if it exits, up to 999 times"
Write-Host ""
Write-Host "Start it now without rebooting:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Check it:                        Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host ""
Write-Host "The STOP file still works while the task runs: it blocks new entries" -ForegroundColor Yellow
Write-Host "but does not stop the task. To stop the task itself, run" -ForegroundColor Yellow
Write-Host "  Stop-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "and remember the restart rule above will not bring it back until the" -ForegroundColor Yellow
Write-Host "next log on, since Stop-ScheduledTask is a deliberate stop." -ForegroundColor Yellow
