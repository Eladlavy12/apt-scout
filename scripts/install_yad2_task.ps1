<#
.SYNOPSIS
Registers (or removes) the "APT-Scout yad2 feed" Task Scheduler task, which
runs scripts/local_yad2_feed.ps1 hourly at :45 while this Windows user is
logged on.

The :45 offset is deliberate: the cloud pipeline's hourly run starts at :05
(see the workflow schedule), so this leaves a comfortable window for the
local job to fetch, commit, and push before the cloud reads the feed - and
the feed's own freshness check (feed_max_age_hours, default 6h) tolerates
this job being late or skipped entirely.

-LogonType Interactive is required (not S4U/password-based): the browser
fallback in adapters/yad2.py needs a real, visible Chrome, which only works
in an interactive desktop session.

.PARAMETER Unregister
Remove the scheduled task instead of creating it.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\install_yad2_task.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\install_yad2_task.ps1 -Unregister
#>

param(
    [switch]$Unregister
)

$TaskName = "APT-Scout yad2 feed"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Unregistered scheduled task '$TaskName' (if it existed)."
    exit 0
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $RepoRoot "scripts\local_yad2_feed.ps1"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Could not find $ScriptPath - run this script from inside the repo."
    exit 1
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $ScriptPath + '"'
)

# One trigger, anchored at today's :45, repeating every hour indefinitely.
$StartBoundary = (Get-Date).Date.AddMinutes(45)
$Trigger = New-ScheduledTaskTrigger -Once -At $StartBoundary `
    -RepetitionInterval (New-TimeSpan -Hours 1)

$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$registration = @{

    TaskName    = $TaskName

    Action      = $Action

    Trigger     = $Trigger

    Settings    = $Settings

    Principal   = $Principal

    Force       = $true

    ErrorAction = 'Stop'

}

try {

    Register-ScheduledTask @registration | Out-Null

} catch {

    Write-Error "Task registration failed: $($_.Exception.Message)"

    exit 1

}

Write-Host "Registered scheduled task '$TaskName': hourly at :45, while logged on."
Write-Host "Log file: $env:LOCALAPPDATA\apt-scout\feed.log"
Write-Host "Check status with: Get-ScheduledTask -TaskName '$TaskName'"
