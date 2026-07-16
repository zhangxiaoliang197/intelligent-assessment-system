# ========================================
# Intelligent Assessment System - Local environment setup
# Usage: powershell -ExecutionPolicy Bypass -File .\setup.ps1
# ========================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = $PSScriptRoot
$runtimeDir = Join-Path $root ".runtime"
$downloadDir = Join-Path $runtimeDir "downloads"
$venvDir = Join-Path $root ".venv"

$nodeVersion = "22.17.1"
$nodeArchiveName = "node-v$nodeVersion-win-x64.zip"
$nodeDir = Join-Path $runtimeDir "node-v$nodeVersion-win-x64"
$nodeExe = Join-Path $nodeDir "node.exe"
$npmCmd = Join-Path $nodeDir "npm.cmd"

$pythonVersion = "3.11.9"
$pythonDir = Join-Path $runtimeDir "python311"
$pythonExe = Join-Path $pythonDir "python.exe"
$pythonInstaller = Join-Path $downloadDir "python-$pythonVersion-amd64.exe"

New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null

function Download-File {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (Test-Path -LiteralPath $Destination) {
        return
    }

    Write-Host "  Downloading $Url" -ForegroundColor DarkGray
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

function Assert-NativeSuccess {
    param([Parameter(Mandatory = $true)][string]$Action)
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

Write-Host "[1/5] Preparing Node.js $nodeVersion..." -ForegroundColor Yellow
if (-not (Test-Path -LiteralPath $nodeExe)) {
    $nodeArchive = Join-Path $downloadDir $nodeArchiveName
    Download-File `
        -Url "https://nodejs.org/dist/v$nodeVersion/$nodeArchiveName" `
        -Destination $nodeArchive
    Expand-Archive -LiteralPath $nodeArchive -DestinationPath $runtimeDir -Force
}
if (-not (Test-Path -LiteralPath $nodeExe)) {
    throw "Node.js setup failed: $nodeExe was not created."
}
Write-Host "  $(& $nodeExe --version)" -ForegroundColor Green
$env:Path = "$nodeDir;$env:Path"

Write-Host "[2/5] Preparing Python $pythonVersion..." -ForegroundColor Yellow
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Download-File `
        -Url "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe" `
        -Destination $pythonInstaller

    $arguments = @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=$pythonDir",
        "Include_doc=0",
        "Include_launcher=0",
        "Include_test=0",
        "Include_tools=1",
        "Include_pip=1",
        "Shortcuts=0",
        "AssociateFiles=0",
        "PrependPath=0"
    )
    $process = Start-Process -FilePath $pythonInstaller -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Python installer failed with exit code $($process.ExitCode)."
    }
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python setup failed: $pythonExe was not created."
}
Write-Host "  $(& $pythonExe --version)" -ForegroundColor Green

Write-Host "[3/5] Installing Python dependencies..." -ForegroundColor Yellow
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $pythonExe -m venv $venvDir
    Assert-NativeSuccess "Creating Python virtual environment"
}
& $venvPython -m pip install --upgrade pip
Assert-NativeSuccess "Upgrading pip"

$pythonServices = @(
    "evaluation-service",
    "indicator-service",
    "knowledge-service",
    "ontology-service",
    "qa-service"
)
foreach ($service in $pythonServices) {
    Write-Host "  Installing $service requirements..." -ForegroundColor DarkGray
    $requirements = Join-Path $root "python\$service\requirements.txt"
    & $venvPython -m pip install -r $requirements
    Assert-NativeSuccess "Installing $service requirements"
}

Write-Host "[4/5] Installing frontend dependencies..." -ForegroundColor Yellow
Push-Location (Join-Path $root "frontend")
try {
    & $npmCmd install
    Assert-NativeSuccess "Installing frontend dependencies"
} finally {
    Pop-Location
}

Write-Host "[5/5] Building Java admin service..." -ForegroundColor Yellow
$maven = Get-Command mvn -ErrorAction SilentlyContinue
if (-not $maven) {
    throw "Maven was not found in PATH. Install Maven 3.6+ and rerun this script."
}
Push-Location (Join-Path $root "java\admin-service")
try {
    & $maven.Source package -DskipTests
    Assert-NativeSuccess "Building Java admin service"
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Environment setup complete." -ForegroundColor Green
Write-Host "Run: powershell -ExecutionPolicy Bypass -File .\start.ps1" -ForegroundColor Cyan
