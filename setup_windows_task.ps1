[CmdletBinding()]
param(
    [switch]$SkipNotificationTest
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$monitorPath = Join-Path $projectRoot "monitor.py"
$runnerPath = Join-Path $projectRoot "run_local_monitor.ps1"
$hiddenRunnerPath = Join-Path $projectRoot "run_local_monitor_hidden.vbs"
$localDirectory = Join-Path $projectRoot ".local"
$secretPath = Join-Path $localDirectory "discord-webhook.xml"
$taskName = "Apple Refurbished Monitor"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw ".venv was not found. Create it and install requirements.txt first."
}

Write-Host "Paste the Discord Webhook URL (input will be hidden):"
$secureWebhook = Read-Host -AsSecureString
$credential = [System.Management.Automation.PSCredential]::new(
    "discord-webhook",
    $secureWebhook
)
$webhookUrl = $credential.GetNetworkCredential().Password
if (-not $webhookUrl.StartsWith("https://discord.com/api/webhooks/") -and
    -not $webhookUrl.StartsWith("https://discordapp.com/api/webhooks/")) {
    throw "Invalid Discord Webhook URL. The scheduled task was not created."
}

New-Item -ItemType Directory -Path $localDirectory -Force | Out-Null
$credential | Export-Clixml -LiteralPath $secretPath

if (-not $SkipNotificationTest) {
    Write-Host "Sending a Discord test notification..."
    $env:DISCORD_WEBHOOK_URL = $webhookUrl
    try {
        & $pythonPath $monitorPath --test-notification
        if ($LASTEXITCODE -ne 0) {
            throw "Discord test notification failed. The scheduled task was not created."
        }
    }
    finally {
        Remove-Item Env:DISCORD_WEBHOOK_URL -ErrorAction SilentlyContinue
    }
}

$wscriptPath = Join-Path $env:SystemRoot "System32\wscript.exe"
$arguments = "`"$hiddenRunnerPath`""
$action = New-ScheduledTaskAction -Execute $wscriptPath -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Checks Apple Taiwan for refurbished MacBook Air M5 products every minute and sends Discord notifications"

Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

Write-Host ""
Write-Host "Setup complete: $taskName"
Write-Host "Interval: every 1 minute"
Write-Host "Resume: monitoring continues on the next interval; missed runs start as soon as possible"
Write-Host "Log: $(Join-Path $projectRoot 'logs\monitor.log')"
