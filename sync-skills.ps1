[CmdletBinding()]
param(
    [switch]$Push,
    [switch]$DryRun,
    [string]$SourceRoot = (Join-Path $env:USERPROFILE '.codex\skills')
)

$ErrorActionPreference = 'Stop'
$RepoRoot = [IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$ManifestPath = Join-Path $RepoRoot '.skill-sync-manifest.json'
$ExcludedTopLevel = @('.system')
$ExcludedDirectories = @('.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv')
$ExcludedFiles = @('.env', '*.pem', '*.key', '*.p12', '*.pfx')

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & git -C $RepoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Skill source directory not found: $SourceRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.git') -PathType Container)) {
    throw "Not a Git repository: $RepoRoot"
}

$sourceSkills = @(
    Get-ChildItem -LiteralPath $SourceRoot -Directory -Force |
        Where-Object {
            $_.Name -notin $ExcludedTopLevel -and
            (Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') -PathType Leaf)
        } |
        Sort-Object Name
)
if ($sourceSkills.Count -eq 0) {
    throw "No user skills containing SKILL.md were found under $SourceRoot"
}

$reparsePoints = @(
    foreach ($skill in $sourceSkills) {
        Get-ChildItem -LiteralPath $skill.FullName -Recurse -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
    }
)
if ($reparsePoints.Count -gt 0) {
    $paths = $reparsePoints | Select-Object -ExpandProperty FullName
    throw "Refusing to sync reparse points:`n$($paths -join [Environment]::NewLine)"
}

$previousNames = @()
if (Test-Path -LiteralPath $ManifestPath -PathType Leaf) {
    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        $previousNames = @($manifest.skills | ForEach-Object { [string]$_ })
    } catch {
        throw "Could not read $ManifestPath`: $($_.Exception.Message)"
    }
}

$currentNames = @($sourceSkills | ForEach-Object Name)
$staleNames = @($previousNames | Where-Object { $_ -notin $currentNames })
$robocopyExe = Join-Path $env:SystemRoot 'System32\robocopy.exe'
if (-not (Test-Path -LiteralPath $robocopyExe -PathType Leaf)) {
    throw "robocopy.exe not found: $robocopyExe"
}

Write-Output "Source: $SourceRoot"
Write-Output "Repository: $RepoRoot"
Write-Output "Skills: $($currentNames.Count)"

foreach ($name in $staleNames) {
    if ($name -notmatch '^[^\\/]+$') { throw "Unsafe stale skill name in manifest: $name" }
    $target = [IO.Path]::GetFullPath((Join-Path $RepoRoot $name))
    if (-not $target.StartsWith($RepoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe stale target: $target"
    }
    if ($DryRun) {
        Write-Output "Would remove stale skill: $name"
    } elseif (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
        Write-Output "Removed stale skill: $name"
    }
}

foreach ($skill in $sourceSkills) {
    $target = Join-Path $RepoRoot $skill.Name
    if ($DryRun) {
        Write-Output "Would mirror: $($skill.Name)"
        continue
    }

    New-Item -ItemType Directory -Path $target -Force | Out-Null
    $copyArgs = @(
        $skill.FullName,
        $target,
        '/MIR', '/R:2', '/W:1', '/NFL', '/NDL', '/NP', '/NJH', '/NJS'
    )
    foreach ($directory in $ExcludedDirectories) { $copyArgs += '/XD'; $copyArgs += $directory }
    foreach ($file in $ExcludedFiles) { $copyArgs += '/XF'; $copyArgs += $file }
    & $robocopyExe @copyArgs | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "Failed to mirror $($skill.Name); robocopy exit code $LASTEXITCODE"
    }
}

if ($DryRun) {
    Write-Output 'Dry run complete.'
    exit 0
}

$manifestObject = [ordered]@{
    source = '~/.codex/skills'
    skills = $currentNames
    excludedTopLevel = $ExcludedTopLevel
    excludedDirectories = $ExcludedDirectories
    excludedFiles = $ExcludedFiles
}
$manifestObject | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

$status = @(Invoke-Git @('status', '--short'))
if ($status.Count -eq 0) {
    Write-Output 'Repository already up to date.'
    exit 0
}

Write-Output 'Changed files:'
$status | ForEach-Object { Write-Output $_ }

if (-not $Push) {
    Write-Output 'Changes are local only. Use -Push to commit and push.'
    exit 0
}

Invoke-Git @('add', '--all') | Out-Null
Invoke-Git @('commit', '-m', 'chore: sync installed Codex skills') | ForEach-Object { Write-Output $_ }
Invoke-Git @('pull', '--rebase', '--autostash', 'origin', 'main') | ForEach-Object { Write-Output $_ }
Invoke-Git @('push', 'origin', 'HEAD:main') | ForEach-Object { Write-Output $_ }
Write-Output 'Skill sync pushed successfully.'
