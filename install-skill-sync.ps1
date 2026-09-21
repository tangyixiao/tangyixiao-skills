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
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Watch installed Codex user skills and sync them to tangyixiao-skills.' -Force -ErrorAction Stop | Out-Null
    try {
        Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } catch {
        Write-Warning "Task was registered but could not be started immediately. It will start at next logon: $($_.Exception.Message)"
    }
    if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
        throw "Scheduled task registration could not be verified: $TaskName"
    }
    Write-Output "Installed and started scheduled task: $TaskName"
} catch {
    $runCommand = '"{0}" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{1}"' -f $shell, $Watcher
    New-Item -Path $runKey -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name $TaskName -Value $runCommand
    $process = Start-Process -FilePath $shell -ArgumentList @('-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $Watcher) -WindowStyle Hidden -PassThru
    if (-not $process) {
        throw "Could not start the fallback watcher process. Scheduled-task error: $($_.Exception.Message)"
    }
    Write-Warning "Scheduled task registration was unavailable; installed a current-user login startup fallback instead."
    Write-Output "Login startup value: HKCU\Software\Microsoft\Windows\CurrentVersion\Run\$TaskName"
}
Write-Output "Repository: $RepoRoot"
