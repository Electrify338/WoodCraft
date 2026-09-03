# WoodCraft — commit the add-in folder and push it to GitHub.
#
#   .\wc-push.ps1 "what changed"
#
# Run it from anywhere; it works on the add-in folder itself. The first push
# opens a browser to sign in to GitHub — Git Credential Manager remembers it
# after that, so every later push is silent.
#
# What it does, and why in this order:
#   fetch          bring origin/main up to date without touching your files
#   reset --mixed  point HEAD at origin/main, keeping every file exactly as is,
#                  so the commit is a clean delta against what is on GitHub
#                  rather than against a months-old clone point
#   add -A         stage everything .gitignore does not exclude
#   commit / push  one commit, straight to main

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Message
)

$ErrorActionPreference = 'Stop'
$repo = Join-Path $env:APPDATA 'Autodesk\Autodesk Fusion 360\API\AddIns\WoodCraft'
$remote = 'https://github.com/Bassem-Tarek/WoodCraft.git'

if (-not (Test-Path (Join-Path $repo '.git'))) {
    Write-Error "No git repository at $repo"
}
Push-Location $repo
try {
    git remote set-url origin $remote
    git fetch origin

    # Keep the working tree; only move where git thinks we are.
    git reset --mixed origin/main | Out-Null

    git add -A
    if (-not (git diff --cached --name-only)) {
        Write-Host 'Nothing to push — the folder already matches origin/main.'
        return
    }

    Write-Host ''
    Write-Host 'About to commit:' -ForegroundColor Cyan
    git diff --cached --stat
    Write-Host ''

    git commit -m $Message
    git push origin HEAD:main
    Write-Host ''
    Write-Host 'Pushed to https://github.com/Bassem-Tarek/WoodCraft' -ForegroundColor Green
}
finally {
    Pop-Location
}
