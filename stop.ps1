# ========================================
# Intelligent Assessment System - Stop Script
# Usage: .\stop.ps1
# ========================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Stopping all services..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$ports = @(10086, 10252, 10253, 10254, 10255, 10256, 10258, 10259)
$names = @("Frontend","Knowledge","QA","Indicator","Evaluation","Ontology","Admin","SolutionEval")

$stopped = 0
for ($i = 0; $i -lt $ports.Count; $i++) {
    $port = $ports[$i]
    $name = $names[$i]
    $ids = (netstat -ano | Select-String ":$port " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] })
    if ($ids) {
        foreach ($id in $ids) {
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
        Write-Host "  [OK] Stopped $name (:$port)" -ForegroundColor Green
        $stopped++
    } else {
        Write-Host "  [--] $name (:$port) - Not running" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Stopped $stopped services" -ForegroundColor White