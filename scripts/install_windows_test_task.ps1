param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = "Stop"
$TaskName = "DJUA SMS Gateway Test"
$Root = (Resolve-Path $Root).Path
$Launcher = Join-Path $Root "start_djua_gateway_hidden.vbs"

if (-not (Test-Path $Launcher)) {
    throw "Launcher introuvable: $Launcher"
}

$Wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
$Arguments = '"' + $Launcher + '"'
$Action = New-ScheduledTaskAction -Execute $Wscript -Argument $Arguments -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "DJUA_SMS temporary automatic Windows test gateway" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "TASK_OK: $TaskName"
