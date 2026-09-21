[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RepoRoot = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$Watcher = Join-Path $RepoRoot 'watch-skills.ps1'
$TaskName = 'Tangyixiao Skills Sync'
$shell = (Get-Command pwsh, powershell -ErrorAction Stop | Select-Object -First 1).Source
$argument = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $Watcher
$action = New-ScheduledTaskAction -Execute $shell -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances Ignore -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description 'Watch installed Codex user skills and sync them to tangyixiao-skills.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Installed and started scheduled task: $TaskName"
Write-Output "Repository: $RepoRoot"
