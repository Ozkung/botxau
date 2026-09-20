<#
.SYNOPSIS
    Sets up the XAUUSD bot on Windows: virtualenv, dependencies, config, preflight check.

.DESCRIPTION
    Run it by double-clicking install.bat in the repo root, or directly:

        powershell -ExecutionPolicy Bypass -File installer\install.ps1

    It is safe to re-run: an existing config.yaml is kept unless you ask for a
    new one, and it never starts the bot or sends an order. Trading still has
    to be started by hand with installer\start-bot.bat.

.PARAMETER Unattended
    Skip every prompt and take the defaults (symbol XAUUSD, dry-run ON).

.PARAMETER SkipDoctor
    Do not run the preflight check at the end.
#>
[CmdletBinding()]
param(
    [switch]$Unattended,
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

function Write-Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "   [ OK ] $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "   [WARN] $text" -ForegroundColor Yellow }
function Write-Err($text) { Write-Host "   [FAIL] $text" -ForegroundColor Red }

function Read-Default($prompt, $default) {
    if ($Unattended) { return $default }
    $answer = Read-Host "$prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer.Trim()
}

function Read-YesNo($prompt, [bool]$default) {
    if ($Unattended) { return $default }
    $hint = if ($default) { "Y/n" } else { "y/N" }
    while ($true) {
        $answer = Read-Host "$prompt [$hint]"
        if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
        switch -Regex ($answer.Trim().ToLower()) {
            '^(y|yes)$' { return $true }
            '^(n|no)$'  { return $false }
            default     { Write-Host "   Please answer y or n." }
        }
    }
}

# --- 1. Python ---------------------------------------------------------------
function Find-Python {
    # The py launcher is the reliable way to pick a version on Windows.
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += ,@("py", @("-3", "-c", "import sys;print(sys.executable)"))
    }
    foreach ($exe in @("python", "python3")) {
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            $candidates += ,@($exe, @("-c", "import sys;print(sys.executable)"))
        }
    }
    foreach ($candidate in $candidates) {
        try {
            $path = & $candidate[0] @($candidate[1]) 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $path) { continue }
            $version = & $path -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
            $parts = $version.Split(".")
            if ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)) {
                return [pscustomobject]@{ Path = $path.Trim(); Version = $version.Trim() }
            }
            Write-Warn "ignoring Python $version at $path (need 3.10+)"
        } catch { continue }
    }
    return $null
}

Write-Host "XAUUSD bot installer" -ForegroundColor White
Write-Host "Repository: $Root"

Write-Step "Checking Python"
$python = Find-Python
if (-not $python) {
    Write-Err "no Python 3.10+ found on PATH"
    Write-Host "   Install it from https://www.python.org/downloads/windows/ and tick"
    Write-Host "   'Add python.exe to PATH' in the installer, then run this again."
    exit 1
}
Write-Ok "Python $($python.Version) at $($python.Path)"

# --- 2. Virtual environment --------------------------------------------------
Write-Step "Setting up the virtual environment"
if (Test-Path $VenvPython) {
    Write-Ok ".venv already exists - reusing it"
} else {
    & $python.Path -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Err "python -m venv failed"; exit 1 }
    Write-Ok "created .venv"
}

Write-Step "Installing dependencies (this can take a few minutes)"
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Err "pip install failed - see the output above"; exit 1 }
Write-Ok "dependencies installed"

& $VenvPython -c "import MetaTrader5" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "MetaTrader5 package available"
} else {
    Write-Err "the MetaTrader5 package did not install - the bot cannot trade without it"
    Write-Host "   It is Windows-only and needs a 64-bit Python. Check the pip output above."
    exit 1
}

# --- 3. Config ---------------------------------------------------------------
Write-Step "Configuration"
$configPath = Join-Path $Root "config.yaml"
$writeConfig = $true
if (Test-Path $configPath) {
    Write-Ok "config.yaml already exists"
    $writeConfig = Read-YesNo "   Replace it with a fresh one? (your current settings are lost)" $false
}

if ($writeConfig) {
    $symbol = Read-Default "   Symbol as your broker names it (XAUUSD, XAUUSDm, GOLD, ...)" "XAUUSD"
    $risk = Read-Default "   Risk per trade, % of equity" "0.5"
    $liveOrders = $false
    if (-not $Unattended) {
        Write-Host ""
        Write-Host "   dry-run ON means the bot logs signals but sends NO orders." -ForegroundColor Yellow
        Write-Host "   Keep it ON until you have watched it on a demo account for weeks." -ForegroundColor Yellow
        $liveOrders = Read-YesNo "   Send real orders (turn dry-run OFF)?" $false
    }
    $arguments = @(
        (Join-Path $Root "installer\configure.py"),
        "--out", $configPath, "--force",
        "--symbol", $symbol,
        "--risk", $risk,
        "--dry-run", $(if ($liveOrders) { "false" } else { "true" })
    )

    if (Read-YesNo "   Set up Telegram notifications now?" $false) {
        $token = Read-Default "   Telegram bot token" ""
        $chat = Read-Default "   Telegram chat id" ""
        if ($token) { $arguments += @("--telegram-token", $token) }
        if ($chat) { $arguments += @("--telegram-chat-id", $chat) }
    }

    $defaultTerminal = "C:\Program Files\MetaTrader 5\terminal64.exe"
    if (-not (Test-Path $defaultTerminal)) {
        Write-Warn "MT5 not found at the default location"
        $custom = Read-Default "   Full path to terminal64.exe (blank = let MT5 find itself)" ""
        if ($custom) { $arguments += @("--mt5-path", $custom) }
    } else {
        Write-Ok "MT5 terminal found at the default location"
    }

    & $VenvPython @arguments
    if ($LASTEXITCODE -ne 0) { Write-Err "could not write config.yaml"; exit 1 }
    Write-Ok "config.yaml written (it is gitignored - keep credentials out of git)"
}

# --- 4. Shortcuts ------------------------------------------------------------
Write-Step "Shortcuts"
if (-not $Unattended -and (Read-YesNo "   Put Start/Stop shortcuts on the Desktop?" $true)) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    foreach ($pair in @(@("Start XAUUSD bot", "start-bot.bat"), @("STOP XAUUSD bot", "stop-bot.bat"))) {
        $link = $shell.CreateShortcut((Join-Path $desktop "$($pair[0]).lnk"))
        $link.TargetPath = Join-Path $Root "installer\$($pair[1])"
        $link.WorkingDirectory = $Root
        $link.Save()
    }
    Write-Ok "shortcuts created on the Desktop"
}

# --- 5. Preflight ------------------------------------------------------------
if (-not $SkipDoctor) {
    Write-Step "Preflight check"
    Write-Host "   Open MT5 and log in first, or the live checks will fail." -ForegroundColor Yellow
    if ($Unattended -or (Read-YesNo "   Run it now?" $true)) {
        & $VenvPython (Join-Path $Root "scripts\doctor.py") --config $configPath
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "the preflight check found problems - fix them before trading"
            Write-Host "   Re-run it any time with: installer\doctor.bat"
        }
    }
}

Write-Step "Done"
Write-Host @"
   Next steps:
     1. installer\doctor.bat        preflight check against your MT5 terminal
     2. installer\start-bot.bat     start the bot (dry-run logs signals only)
     3. installer\stop-bot.bat      block new entries via the STOP file
     4. installer\install-task.ps1  optional: auto-start after a VPS reboot

   Logs go to logs\bot.log, trades to data\journal.sqlite.
   The strategy is NOT proven profitable - see docs\ARCHITECTURE.md section 7
   for the validation steps before risking real money.
"@
exit 0
