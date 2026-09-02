<#
.SYNOPSIS
Fetches yad2 fresh through a real, headed Chrome on this PC and commits the
raw listings to state/feeds/yad2.json, so the cloud's hourly run can use
them as yad2's input (see src/apt_scout/adapters/yad2.py's feed-first
fetch, and src/apt_scout/local_feed.py, which does the actual fetch/write).

yad2 blocks GitHub's servers at every fetch tier but works fine from a real
browser on a residential connection, which is why this half of the pipeline
has to run here instead of in CI.

Meant to run unattended from Task Scheduler (see install_yad2_task.ps1);
never prompts. Every step is logged to
%LOCALAPPDATA%\apt-scout\feed.log.
#>

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $env:LOCALAPPDATA "apt-scout"
$LogFile = Join-Path $LogDir "feed.log"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

function Write-Log {
    param([string]$Message)
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content -Path $LogFile -Encoding utf8 -Value "$stamp  $Message"
}

# A failed "git pull --rebase" (or "git pull --rebase -X theirs") can leave
# the repo sitting mid-rebase, which would block every future run's pull and
# push until someone notices and cleans it up by hand. If either rebase
# state directory is present, abort it so the next attempt starts clean.
function Resolve-StuckRebase {
    $rebaseMerge = Join-Path $RepoRoot ".git\rebase-merge"
    $rebaseApply = Join-Path $RepoRoot ".git\rebase-apply"
    if ((Test-Path $rebaseMerge) -or (Test-Path $rebaseApply)) {
        $abortOutput = (git rebase --abort 2>&1 | Out-String).Trim()
        Write-Log "detected a stuck rebase; ran git rebase --abort: $abortOutput"
    }
}

Write-Log "=== run start ==="
Set-Location $RepoRoot

# Best-effort: pick up any newer feed/state committed elsewhere since the
# last run. A failure here (offline, conflicting local changes, etc.) must
# not stop the fetch - it just means this run works from a slightly stale
# base, which the retrying push below still handles safely.
$pullOutput = (git pull --rebase --autostash 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -eq 0) {
    Write-Log "git pull ok: $pullOutput"
} else {
    Write-Log "git pull failed (continuing anyway): $pullOutput"
    Resolve-StuckRebase
}

# Enables the tier-2 browser fallback in adapters/yad2.py to use a real,
# visible Chrome instead of headless - required for yad2's bot detection.
$env:APT_SCOUT_BROWSER_HEADED = "1"

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Write-Log "fetching yad2 via $PythonExe -m apt_scout.local_feed"
$fetchOutput = ""
$fetchExit = 1
try {
    $fetchOutput = (& $PythonExe -m apt_scout.local_feed --repo $RepoRoot 2>&1 | Out-String).Trim()
    $fetchExit = $LASTEXITCODE
    Write-Log "local_feed exit=$fetchExit output: $fetchOutput"
} catch {
    Write-Log "failed to run $PythonExe (missing venv/python?): $($_.Exception.Message)"
    $fetchExit = 1
}

if ($fetchExit -ne 0) {
    Write-Log "fetch failed; leaving the existing feed file untouched. === run end (failure) ==="
    exit $fetchExit
}

$statusOutput = (git status --porcelain state/feeds/yad2.json | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($statusOutput)) {
    Write-Log "no change to state/feeds/yad2.json; nothing to commit. === run end ==="
    exit 0
}

git add state/feeds/yad2.json
$commitOutput = (git commit -m "chore: yad2 local feed" 2>&1 | Out-String).Trim()
Write-Log "git commit: $commitOutput"

$pushed = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    $pushOutput = (git push 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -eq 0) {
        Write-Log "git push ok on attempt $attempt"
        $pushed = $true
        break
    }
    Write-Log "git push failed on attempt $attempt : $pushOutput"
    $rebaseOutput = (git pull --rebase -X theirs 2>&1 | Out-String).Trim()
    Write-Log "git pull --rebase -X theirs (attempt $attempt): $rebaseOutput"
    Resolve-StuckRebase
}

if ($pushed) {
    # GitHub throttles cron schedules on free repos to a few runs a day, so
    # trigger the cloud scan explicitly whenever a fresh feed has been pushed.
    try {
        $kick = (& gh workflow run scan --repo Eladlavy12/apt-scout 2>&1 | Out-String).Trim()
        Write-Log "cloud scan triggered: $kick"
    } catch {
        Write-Log "cloud scan trigger skipped: $($_.Exception.Message)"
    }
    Write-Log "=== run end: success ==="
    exit 0
} else {
    Write-Log "=== run end: push failed after 3 attempts ==="
    exit 1
}
