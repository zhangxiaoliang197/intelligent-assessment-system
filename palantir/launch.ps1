# =============================================================================
#  AEGIS Launch Script
#  Builds, starts and seeds the entire platform with a single command.
#
#  Usage:
#    .\launch.ps1              # Full Docker Compose build + start + seed
#    .\launch.ps1 -Mode dev    # Infrastructure in Docker, backend+frontend local
#    .\launch.ps1 -SkipSeed    # Skip database seeding
#    .\launch.ps1 -Down        # Tear down everything (including volumes)
# =============================================================================

param(
    [ValidateSet("docker", "dev")]
    [string]$Mode = "docker",
    [switch]$SkipSeed,
    [switch]$Down,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

# -- Colors and formatting ----------------------------------------------------

function Write-Header { param([string]$Text) Write-Host "`n$Text" -ForegroundColor Cyan }
function Write-Step { param([string]$Text) Write-Host "  >> $Text" -ForegroundColor White }
function Write-Ok { param([string]$Text) Write-Host "  [OK] $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "  [!!] $Text" -ForegroundColor Yellow }
function Write-Fail { param([string]$Text) Write-Host "  [FAIL] $Text" -ForegroundColor Red }

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    if (-not (Test-Path $Path)) { return $values }

    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*(?:#|$)') { continue }
        if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { continue }

        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        $values[$name] = $value
    }

    return $values
}

function Set-BackendEnvironment {
    $dotenv = Read-DotEnv -Path (Join-Path $Root ".env")

    $mapping = @{
        "DeepSeek__ApiKey" = "DEEPSEEK_API_KEY"
        "DeepSeek__BaseUrl" = "DEEPSEEK_BASE_URL"
        "DeepSeek__Model" = "DEEPSEEK_MODEL"
        "ConnectionStrings__Neo4j" = "NEO4J_URI"
        "ConnectionStrings__OpenSearch" = "OPENSEARCH_URL"
        "ConnectionStrings__Redis" = "REDIS_CONNECTION"
    }

    foreach ($target in $mapping.Keys) {
        $source = $mapping[$target]
        $value = [Environment]::GetEnvironmentVariable($source)
        if ([string]::IsNullOrWhiteSpace($value)) {
            $value = $dotenv[$source]
        }
        if ($target -eq "ConnectionStrings__Neo4j") {
            $value = $value -replace '://neo4j(?=[:/]|$)', '://localhost'
        }
        elseif ($target -eq "ConnectionStrings__OpenSearch") {
            $value = $value -replace '://opensearch(?=[:/]|$)', '://localhost'
        }
        elseif ($target -eq "ConnectionStrings__Redis") {
            $value = $value -replace '^redis(?=[:/]|$)', 'localhost'
        }
        if (-not [string]::IsNullOrWhiteSpace($value) -and
            [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($target))) {
            Set-Item -Path "Env:$target" -Value $value
        }
    }

    if ([string]::IsNullOrWhiteSpace($env:ASPNETCORE_URLS)) {
        $port = $env:API_PORT
        if ([string]::IsNullOrWhiteSpace($port)) { $port = $dotenv["API_PORT"] }
        if ([string]::IsNullOrWhiteSpace($port)) { $port = "5000" }
        $env:ASPNETCORE_URLS = "http://localhost:$port"
    }
}

function Show-Banner {
    Write-Host ""
    Write-Host "    ___   _____________ _____" -ForegroundColor Blue
    Write-Host "   /   | / ____/ ____/ / ___/" -ForegroundColor Blue
    Write-Host "  / /| |/ __/ / / __  / __ \" -ForegroundColor Blue
    Write-Host " / ___ / /___/ /_/ / / /_/ /" -ForegroundColor DarkCyan
    Write-Host "/_/  |_\____/\____/ /\____/" -ForegroundColor DarkCyan
    Write-Host ""
    Write-Host "  Analytical Engine for Graph Intelligence and Security" -ForegroundColor DarkGray
    Write-Host "  Water Supply Sabotage Detection Platform" -ForegroundColor DarkGray
    Write-Host ("  " + "-" * 52) -ForegroundColor DarkGray
    Write-Host ""
}

# -- Prerequisite checks ------------------------------------------------------

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Port {
    param([int]$Port)
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpClient]::new()
        $listener.Connect("127.0.0.1", $Port)
        $listener.Close()
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($listener) { $listener.Dispose() }
    }
}

function Assert-Prerequisites {
    Write-Header "Checking prerequisites"

    # Docker
    if (-not (Test-Command "docker")) {
        Write-Fail "Docker is not installed or not in PATH."
        exit 1
    }
    $dockerRunning = docker info 2>&1 | Select-String "Server Version"
    if (-not $dockerRunning) {
        Write-Fail "Docker daemon is not running. Start Docker Desktop first."
        exit 1
    }
    Write-Ok "Docker $(docker --version | Select-String -Pattern '\d+\.\d+\.\d+' | ForEach-Object { $_.Matches[0].Value })"

    # Docker Compose
    $composeVersion = docker compose version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Docker Compose V2 is not available."
        exit 1
    }
    Write-Ok "Docker Compose $($composeVersion -replace '.*v','v' -replace '\s.*','')"

    # Dev mode extras
    if ($Mode -eq "dev") {
        if (-not (Test-Command "dotnet")) {
            Write-Fail ".NET SDK is required for dev mode."
            exit 1
        }
        $sdkVersion = dotnet --version 2>&1
        Write-Ok ".NET SDK $sdkVersion"

        if (-not (Test-Command "node")) {
            Write-Fail "Node.js is required for dev mode."
            exit 1
        }
        $nodeVersion = node --version 2>&1
        Write-Ok "Node.js $nodeVersion"

        if (-not (Test-Command "npm")) {
            Write-Fail "npm is required for dev mode."
            exit 1
        }
    }

    # Port availability
    $ports = @(
        @{ Port = 3000; Name = "Frontend" },
        @{ Port = 5000; Name = "API" },
        @{ Port = 7474; Name = "Neo4j Browser" },
        @{ Port = 7687; Name = "Neo4j Bolt" },
        @{ Port = 9200; Name = "OpenSearch" },
        @{ Port = 6379; Name = "Redis" }
    )

    if ($Mode -eq "dev") {
        $ports += @{ Port = 5173; Name = "Vite Dev Server" }
    }

    $blocked = @()
    foreach ($p in $ports) {
        if (Test-Port -Port $p.Port) {
            $blocked += "$($p.Name) (:$($p.Port))"
        }
    }

    if ($blocked.Count -gt 0) {
        Write-Warn "Ports already in use: $($blocked -join ', ')"
        Write-Warn "Attempting to continue -- existing AEGIS containers may be reused."
    }
    else {
        Write-Ok "All required ports are available"
    }
}

# -- Tear down -----------------------------------------------------------------

function Invoke-Down {
    Write-Header "Tearing down AEGIS"
    Set-Location $Root
    docker compose down -v --remove-orphans 2>&1 | ForEach-Object { Write-Step $_ }
    Write-Ok "All containers and volumes removed"
    exit 0
}

# -- Wait for healthy service --------------------------------------------------

function Wait-ForEndpoint {
    param(
        [string]$Url,
        [string]$Name,
        [int]$TimeoutSeconds = 120,
        [int]$IntervalSeconds = 3
    )

    Write-Step "Waiting for $Name ($Url)..."
    $elapsed = 0
    while ($elapsed -lt $TimeoutSeconds) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-Ok "$Name is ready ($elapsed`s)"
                return $true
            }
        }
        catch { }
        Start-Sleep -Seconds $IntervalSeconds
        $elapsed += $IntervalSeconds
    }

    Write-Fail "$Name did not become healthy within $TimeoutSeconds seconds."
    return $false
}

# -- Docker Compose mode -------------------------------------------------------

function Start-DockerMode {
    Write-Header "Building and starting all services (Docker Compose)"
    Set-Location $Root

    $buildArgs = @("compose", "up", "-d")
    if ($Rebuild) { $buildArgs += "--build" }
    else { $buildArgs += "--build" }  # always build on launch

    Write-Step "docker compose up -d --build"
    Write-Host ""

    $composeOutput = & docker @buildArgs 2>&1
    $composeExit = $LASTEXITCODE
    foreach ($line in $composeOutput) {
        $text = "$line"
        if ($text -match "error|Error|ERROR") { Write-Fail $text }
        else { Write-Host "  $text" -ForegroundColor DarkGray }
    }

    if ($composeExit -ne 0) {
        Write-Fail "Docker Compose failed. Check the output above."
        Write-Host ""
        Write-Step "Showing container logs for debugging:"
        docker compose logs --tail=40 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
        exit 1
    }

    Write-Ok "All containers started"

    # Wait for services
    Write-Header "Waiting for services to become healthy"

    $healthy = $true
    if (-not (Wait-ForEndpoint -Url "http://localhost:9200/_cluster/health" -Name "OpenSearch")) { $healthy = $false }
    if (-not (Wait-ForEndpoint -Url "http://localhost:7474" -Name "Neo4j Browser")) { $healthy = $false }

    # Redis -- no HTTP, check via docker
    Write-Step "Checking Redis..."
    $retries = 0
    while ($retries -lt 20) {
        $ping = docker exec aegis-redis redis-cli ping 2>&1
        if ($ping -match "PONG") {
            Write-Ok "Redis is ready"
            break
        }
        Start-Sleep -Seconds 3
        $retries++
    }
    if ($retries -ge 20) { Write-Fail "Redis did not respond"; $healthy = $false }

    # API
    if (-not (Wait-ForEndpoint -Url "http://localhost:5000/swagger/v1/swagger.json" -Name "AEGIS API" -TimeoutSeconds 180)) { $healthy = $false }

    if (-not $healthy) {
        Write-Warn "Some services failed to start. Check logs with: docker compose logs"
    }

    return $healthy
}

# -- Dev mode (infra in Docker, app local) -------------------------------------

function Start-DevMode {
    Write-Header "Starting infrastructure (Docker)"
    Set-Location $Root
    Set-BackendEnvironment

    docker compose up -d neo4j opensearch redis 2>&1 | ForEach-Object {
        Write-Host "  $_" -ForegroundColor DarkGray
    }

    Write-Header "Waiting for infrastructure"
    $healthy = $true
    if (-not (Wait-ForEndpoint -Url "http://localhost:9200/_cluster/health" -Name "OpenSearch")) { $healthy = $false }
    if (-not (Wait-ForEndpoint -Url "http://localhost:7474" -Name "Neo4j Browser")) { $healthy = $false }

    Write-Step "Checking Redis..."
    $retries = 0
    while ($retries -lt 20) {
        $ping = docker exec aegis-redis redis-cli ping 2>&1
        if ($ping -match "PONG") { Write-Ok "Redis is ready"; break }
        Start-Sleep -Seconds 3
        $retries++
    }
    if ($retries -ge 20) { Write-Fail "Redis did not respond"; $healthy = $false }

    if (-not $healthy) {
        Write-Fail "Infrastructure is not healthy. Aborting."
        exit 1
    }

    # Restore and build backend
    Write-Header "Building .NET backend"
    Set-Location "$Root\src\backend"
    Write-Step "dotnet restore"
    dotnet restore Aegis.sln 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Write-Step "dotnet build"
    dotnet build Aegis.sln -c Release --no-restore 2>&1 | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }

    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Backend build failed."
        exit 1
    }
    Write-Ok "Backend compiled"

    # Install frontend dependencies
    Write-Header "Installing frontend dependencies"
    Set-Location "$Root\src\frontend"
    if (-not (Test-Path "node_modules")) {
        Write-Step "npm install"
        npm install 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    }
    else {
        Write-Ok "node_modules already present"
    }

    # Start backend in background
    Write-Header "Starting backend (.NET)"
    Set-Location "$Root\src\backend"
    $backendJob = Start-Job -ScriptBlock {
        Set-Location $using:Root\src\backend
        dotnet run --project Aegis.API -c Release --no-build
    }
    Write-Ok "Backend starting in background (Job $($backendJob.Id))"

    # Wait for API
    if (-not (Wait-ForEndpoint -Url "http://localhost:5000/swagger/v1/swagger.json" -Name "AEGIS API" -TimeoutSeconds 60)) {
        Write-Fail "API did not start. Check: Receive-Job -Id $($backendJob.Id)"
        exit 1
    }

    # Seed
    if (-not $SkipSeed) { Invoke-Seed }

    # Start frontend
    Write-Header "Starting frontend (Vite dev server)"
    Set-Location "$Root\src\frontend"
    Write-Step "npm run dev"
    Write-Host ""
    Write-Host "  The Vite dev server will start below." -ForegroundColor DarkGray
    Write-Host "  Press Ctrl+C to stop frontend and backend." -ForegroundColor DarkGray
    Write-Host ""

    try {
        npm run dev
    }
    finally {
        Write-Header "Shutting down"
        Stop-Job -Id $backendJob.Id -ErrorAction SilentlyContinue
        Remove-Job -Id $backendJob.Id -Force -ErrorAction SilentlyContinue
        Write-Ok "Backend job stopped"
    }
}

# -- Seed database -------------------------------------------------------------

function Invoke-Seed {
    Write-Header "Seeding database"
    Write-Step "POST http://localhost:5000/api/seed"

    try {
        $response = Invoke-WebRequest `
            -Uri "http://localhost:5000/api/seed" `
            -Method POST `
            -UseBasicParsing `
            -TimeoutSec 30

        if ($response.StatusCode -eq 200) {
            $body = $response.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
            $message = if ($body -and $body.message) { $body.message } else { "Database seeded successfully" }
            Write-Ok $message
        }
        else {
            Write-Warn "Seed returned status $($response.StatusCode)"
        }
    }
    catch {
        Write-Warn "Seed request failed: $($_.Exception.Message)"
        Write-Warn "You can seed manually later: Invoke-WebRequest -Method POST http://localhost:5000/api/seed"
    }
}

# -- Summary -------------------------------------------------------------------

function Show-Summary {
    Write-Header "AEGIS is ready"
    Write-Host ""
    Write-Host "  Service              URL" -ForegroundColor White
    Write-Host "  -------------------  -------------------------------------------" -ForegroundColor DarkGray

    if ($Mode -eq "docker") {
        Write-Host "  Frontend             " -NoNewline -ForegroundColor DarkGray
        Write-Host "http://localhost:3000" -ForegroundColor Cyan
    }
    else {
        Write-Host "  Frontend (Vite)      " -NoNewline -ForegroundColor DarkGray
        Write-Host "http://localhost:5173" -ForegroundColor Cyan
    }

    Write-Host "  API (Swagger)        " -NoNewline -ForegroundColor DarkGray
    Write-Host "http://localhost:5000/swagger" -ForegroundColor Cyan
    Write-Host "  Neo4j Browser        " -NoNewline -ForegroundColor DarkGray
    Write-Host "http://localhost:7474" -ForegroundColor Cyan
    Write-Host "  OpenSearch            " -NoNewline -ForegroundColor DarkGray
    Write-Host "http://localhost:9200" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Neo4j credentials    neo4j / aegis2026!" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Commands:" -ForegroundColor White
    Write-Host "    .\launch.ps1 -Down       Stop and remove everything" -ForegroundColor DarkGray
    Write-Host "    docker compose logs -f    Stream all container logs" -ForegroundColor DarkGray
    Write-Host ""
}

# ==============================================================================
#  Main
# ==============================================================================

Show-Banner

if ($Down) { Invoke-Down }

Assert-Prerequisites

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

if ($Mode -eq "docker") {
    $ok = Start-DockerMode
    if ($ok -and -not $SkipSeed) { Invoke-Seed }
    Show-Summary

    $stopwatch.Stop()
    Write-Host "  Total time: $([math]::Round($stopwatch.Elapsed.TotalSeconds))s" -ForegroundColor DarkGray
    Write-Host ""

    # Open browser
    Write-Step "Opening browser..."
    Start-Process "http://localhost:3000"
}
elseif ($Mode -eq "dev") {
    Start-DevMode
    # Show-Summary is not reached in dev mode because npm run dev blocks
}

$stopwatch.Stop()
