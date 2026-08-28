param(
  [string]$TargetDir = "."
)

$ErrorActionPreference = "Stop"
$OverlayDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetDir = (Resolve-Path $TargetDir).Path

if (-not (Test-Path (Join-Path $TargetDir "docker-compose.yml")) -or -not (Test-Path (Join-Path $TargetDir "src\frontend"))) {
  throw "Target does not look like palantir-ghotam-like: $TargetDir"
}

$compose = Join-Path $TargetDir "docker-compose.yml"
$backup = Join-Path $TargetDir "docker-compose.pre-v7.yml"
if (-not (Test-Path $backup)) {
  Copy-Item -Force $compose $backup
}

Copy-Item -Recurse -Force (Join-Path $OverlayDir "src\*") (Join-Path $TargetDir "src")
Copy-Item -Recurse -Force (Join-Path $OverlayDir "data\*") (Join-Path $TargetDir "data")

if (Test-Path (Join-Path $OverlayDir "docs")) {
  New-Item -ItemType Directory -Force (Join-Path $TargetDir "docs") | Out-Null
  Copy-Item -Recurse -Force (Join-Path $OverlayDir "docs\*") (Join-Path $TargetDir "docs")
}

Copy-Item -Force (Join-Path $OverlayDir "docker-compose.yml") $compose
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $TargetDir "docker-compose.dynamic.yml")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $TargetDir "src\frontend\package-lock.json")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $TargetDir "src\backend\Aegis.Infrastructure\AI\OllamaService.cs")

Write-Host "AEGIS Dynamic Ontology v7 applied to: $TargetDir"
Write-Host "Original compose backup: docker-compose.pre-v7.yml"
Write-Host "Add a NEW DeepSeek key to repository-root .env as DEEPSEEK_API_KEY=..."
Write-Host "Then run: docker compose up -d --build"
