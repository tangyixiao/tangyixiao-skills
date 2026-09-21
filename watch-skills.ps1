[CmdletBinding()]
param([int]$DebounceSeconds = 20)

$ErrorActionPreference = 'Continue'
$RepoRoot = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$SourceRoot = Join-Path $env:USERPROFILE '.codex\skills'
$SyncScript = Join-Path $RepoRoot 'sync-skills.ps1'
$LogRoot = Join-Path $env:LOCALAPPDATA 'tangyixiao-skills'
$LogPath = Join-Path $LogRoot 'sync.log'
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    Add-Content -LiteralPath $LogPath -Value "$(Get-Date -Format o) source directory missing: $SourceRoot"
    exit 1
}

$watcher = New-Object IO.FileSystemWatcher
$watcher.Path = $SourceRoot
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [IO.NotifyFilters]'FileName, DirectoryName, LastWrite, Size'
$watcher.EnableRaisingEvents = $true
$script:pending = $false
$script:lastEvent = Get-Date

$handler = {
    $path = $Event.SourceEventArgs.FullPath
    $relative = $path.Substring($SourceRoot.Length).TrimStart('\', '/')
    if ($relative -eq '.system' -or $relative.StartsWith('.system\', [StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    $script:pending = $true
    $script:lastEvent = Get-Date
}

$subscriptions = @(
    Register-ObjectEvent -InputObject $watcher -EventName Created -Action $handler
    Register-ObjectEvent -InputObject $watcher -EventName Changed -Action $handler
    Register-ObjectEvent -InputObject $watcher -EventName Deleted -Action $handler
    Register-ObjectEvent -InputObject $watcher -EventName Renamed -Action $handler
)

try {
    while ($true) {
        if ($script:pending -and ((Get-Date) - $script:lastEvent).TotalSeconds -ge $DebounceSeconds) {
            $script:pending = $false
            try {
                $output = & $SyncScript -Push 2>&1 | Out-String
                Add-Content -LiteralPath $LogPath -Value "$(Get-Date -Format o)`n$output"
            } catch {
                Add-Content -LiteralPath $LogPath -Value "$(Get-Date -Format o) sync failed: $($_.Exception.Message)"
            }
        }
        Start-Sleep -Seconds 2
    }
} finally {
    $subscriptions | ForEach-Object { Unregister-Event -SubscriptionId $_.Id -ErrorAction SilentlyContinue; Remove-Job -Id $_.Id -Force -ErrorAction SilentlyContinue }
    $watcher.Dispose()
}
