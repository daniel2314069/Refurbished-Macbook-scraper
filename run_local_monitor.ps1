[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$monitorPath = Join-Path $projectRoot "monitor.py"
$secretPath = Join-Path $projectRoot ".local\discord-webhook.xml"
$logDirectory = Join-Path $projectRoot "logs"
$logPath = Join-Path $logDirectory "monitor.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-MonitorLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[$timestamp] $Message"
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "Local Python environment not found: $pythonPath"
    }
    if (-not (Test-Path -LiteralPath $secretPath)) {
        throw "Discord Webhook is not configured. Run setup_windows_task.ps1."
    }

    $credential = Import-Clixml -LiteralPath $secretPath
    $webhookUrl = $credential.GetNetworkCredential().Password
    if (-not $webhookUrl.StartsWith("https://discord.com/api/webhooks/") -and
        -not $webhookUrl.StartsWith("https://discordapp.com/api/webhooks/")) {
        throw "The saved Discord Webhook URL is invalid."
    }

    $env:DISCORD_WEBHOOK_URL = $webhookUrl
    Write-MonitorLog "Starting Apple refurbished product check"
    & $pythonPath $monitorPath 2>&1 | ForEach-Object {
        Write-MonitorLog $_.ToString()
    }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Monitor exited with code $exitCode"
    }
    Write-MonitorLog "Check completed"
}
catch {
    Write-MonitorLog "Error: $($_.Exception.Message)"
    exit 1
}
finally {
    Remove-Item Env:DISCORD_WEBHOOK_URL -ErrorAction SilentlyContinue
}

exit 0
