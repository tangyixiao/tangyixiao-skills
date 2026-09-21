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
$pending = $false
$lastEvent = Get-Date

try {
    while ($true) {
        $change = $watcher.WaitForChanged([IO.WatcherChangeTypes]::All, 2000)
        if (-not $change.TimedOut) {
            $relative = [string]$change.Name
            if ($relative -ne '.system' -and -not $relative.StartsWith('.system\', [StringComparison]::OrdinalIgnoreCase)) {
                $pending = $true
                $lastEvent = Get-Date
            }
        }
        if ($pending -and ((Get-Date) - $lastEvent).TotalSeconds -ge $DebounceSeconds) {
            $pending = $false
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
    $watcher.Dispose()
}
