<#
.SYNOPSIS
    Remove the scheduled task created by install-task.ps1.

.DESCRIPTION
    Only unregisters the task. The virtualenv, config.yaml, journal and logs
    are left alone, and a bot process already running is not killed - stop that
    from its own window, or with Stop-ScheduledTask before running this.
#>
[CmdletBinding()]
param([string]$TaskName = "XAUUSD-bot")

$ErrorActionPreference = "Stop"

if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Write-Host "No scheduled task named '$TaskName' - nothing to do."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "A bot process that is already running was not touched." -ForegroundColor Yellow
