# release-mcp — Build, push, and roll out a new etc-platform MCP image.
# Usage:
#   .\release-mcp.ps1 v3.1.0                  # build + push (no team-config bump)
#   .\release-mcp.ps1 v3.1.0 -BumpTeam        # also update team-ai-config .env.example + git push
#   .\release-mcp.ps1 v3.1.0 -BumpTeam -Yes   # non-interactive (skip confirmations)
#
# What it does:
#   1. Validate version format (vMAJOR.MINOR.PATCH)
#   2. docker build -t {NS}/etc-platform:{ver} + :latest
#   3. docker push both tags
#   4. (with -BumpTeam) cd to team-ai-config repo, update .env.example, commit + push

#Requires -Version 5.1
[CmdletBinding()]
param(
  [Parameter(Position=0, Mandatory=$true)] [string] $Version,
  [switch] $BumpTeam,
  [switch] $Yes,
  [string] $Namespace = 'o0mrblack0o',
  [string] $TeamRepo  = 'D:\Projects\team-ai-config'
)

$ErrorActionPreference = 'Stop'

# ─── colors ────────────────────────────────────────────────────────────
function Write-Info($m) { Write-Host "▶ $m" -ForegroundColor White }
function Write-Ok($m)   { Write-Host "  ✓ $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "  ⚠ $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "  ✗ $m" -ForegroundColor Red }

# ─── validate ──────────────────────────────────────────────────────────
if ($Version -notmatch '^v\d+\.\d+\.\d+(-[\w\.]+)?$') {
  Write-Err "Version must be 'vMAJOR.MINOR.PATCH' (e.g. v3.1.0). Got: $Version"
  exit 1
}

$Image       = "$Namespace/etc-platform"
$ImageVer    = "${Image}:${Version}"
$ImageLatest = "${Image}:latest"
$BuildCtx    = $PSScriptRoot

if (-not (Test-Path (Join-Path $BuildCtx 'Dockerfile'))) {
  Write-Err "Dockerfile not found at $BuildCtx — run from etc-platform source root"
  exit 1
}

# Check docker login (best-effort heuristic: try inspect public image, else hint)
docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Err 'Docker daemon not running'; exit 1 }

# ─── confirm ───────────────────────────────────────────────────────────
Write-Host ''
Write-Host "Release Plan" -ForegroundColor White
Write-Host "  Image      : $ImageVer + :latest"
Write-Host "  Build ctx  : $BuildCtx"
Write-Host "  Bump team  : $(if ($BumpTeam) { "Yes (->$TeamRepo\mcp\etc-platform\.env.example)" } else { 'No' })"
Write-Host ''

if (-not $Yes) {
  $yn = Read-Host 'Proceed? (y/N)'
  if ($yn -notmatch '^[Yy]') { Write-Host 'Aborted.'; exit 0 }
}

# ─── build ─────────────────────────────────────────────────────────────
Write-Info "Building $ImageVer"
docker build -t $ImageVer -t $ImageLatest $BuildCtx
if ($LASTEXITCODE -ne 0) { Write-Err 'Build failed'; exit 1 }
Write-Ok 'Built'

# ─── push ──────────────────────────────────────────────────────────────
Write-Info "Pushing $ImageVer"
docker push $ImageVer
if ($LASTEXITCODE -ne 0) {
  Write-Err 'Push failed — Did you `docker login`? (token: app.docker.com/settings/personal-access-tokens)'
  exit 1
}
Write-Ok "Pushed $Version"

Write-Info "Pushing $ImageLatest"
docker push $ImageLatest
if ($LASTEXITCODE -ne 0) { Write-Err 'Push :latest failed'; exit 1 }
Write-Ok 'Pushed :latest'

# ─── bump team-ai-config (optional) ────────────────────────────────────
if ($BumpTeam) {
  if (-not (Test-Path $TeamRepo)) {
    Write-Warn "team-ai-config repo not found at $TeamRepo — skip bump (use -TeamRepo to override)"
  } else {
    Write-Info "Bumping team-ai-config to $Version"
    $envFile = Join-Path $TeamRepo 'mcp\etc-platform\.env.example'
    if (-not (Test-Path $envFile)) {
      Write-Err "Not found: $envFile"
      exit 1
    }
    $content = Get-Content -Raw $envFile
    $newContent = $content -replace 'ETC_PLATFORM_IMAGE=.*', "ETC_PLATFORM_IMAGE=$ImageVer"
    if ($content -eq $newContent) {
      Write-Ok ".env.example already at $Version"
    } else {
      Set-Content -Path $envFile -Value $newContent -NoNewline
      Write-Ok "Updated $envFile"
    }

    Push-Location $TeamRepo
    try {
      git diff --quiet 2>$null; $clean = ($LASTEXITCODE -eq 0)
      if ($clean) {
        Write-Ok 'No changes to commit (env already pinned)'
      } else {
        git add mcp/etc-platform/.env.example
        git commit -m "Bump MCP image to $Version"
        git push
        Write-Ok "team-ai-config pushed"
      }
    } finally { Pop-Location }
  }
}

# ─── done ──────────────────────────────────────────────────────────────
Write-Host ''
Write-Host "✅ Released $ImageVer" -ForegroundColor Green
Write-Host ''
Write-Host 'Team rollout:'
if ($BumpTeam) {
  Write-Host '  Team: ai-kit update    (will pull new image + restart)'
} else {
  Write-Host '  1. Bump team-ai-config\mcp\etc-platform\.env.example -> ETC_PLATFORM_IMAGE='"$ImageVer"
  Write-Host '  2. cd team-ai-config && git add . && git commit -m "Bump MCP $Version" && git push'
  Write-Host '  3. Team: ai-kit update'
  Write-Host ''
  Write-Host '  (or re-run with -BumpTeam to do steps 1-2 automatically)'
}
