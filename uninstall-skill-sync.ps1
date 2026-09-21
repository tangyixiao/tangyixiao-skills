[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$TaskName = 'Tangyixiao Skills Sync'
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task: $TaskName"
}
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runValue = Get-ItemProperty -Path $runKey -Name $TaskName -ErrorAction SilentlyContinue
if ($null -ne $runValue) {
    Remove-ItemProperty -Path $runKey -Name $TaskName -ErrorAction Stop
    Write-Output "Removed login startup value: $TaskName"
}
if ($null -eq $existing -and $null -eq $runValue) {
    Write-Output "No active skill sync registration found."
}
