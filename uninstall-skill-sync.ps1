[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$TaskName = 'Tangyixiao Skills Sync'
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    Write-Output "Scheduled task not found: $TaskName"
    exit 0
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Removed scheduled task: $TaskName"
