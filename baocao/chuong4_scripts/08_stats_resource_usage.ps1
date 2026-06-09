# ============================================================
# Script 08: Tieu thu tai nguyen thuc te
# Tuong ung: Muc 4.4.3 - Mu+c trien khai RAM
# ============================================================
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WebReel - Tieu thu tai nguyen tung container" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1] Bang thong ke chi tiet RAM/CPU (3 mau cach nhau 2 giay):" -ForegroundColor Yellow
for ($i = 1; $i -le 3; $i++) {
    Write-Host ""
    Write-Host "--- Snapshot #$i ---" -ForegroundColor DarkCyan
    docker stats --no-stream --format "table {{.Name}}`t{{.CPUPerc}}`t{{.MemUsage}}`t{{.MemPerc}}"
    if ($i -lt 3) { Start-Sleep -Seconds 2 }
}
Write-Host ""

Write-Host "[2] Tong RAM ho:" -ForegroundColor Yellow
$totalRamGB = "{0:N2}" -f ((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$freeRamGB = "{0:N2}" -f ((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB)
Write-Host "    Tong RAM: $totalRamGB GB"
Write-Host "    RAM trong: $freeRamGB GB"
Write-Host ""

Write-Host "[3] CPU ho:" -ForegroundColor Yellow
$cpu = Get-CimInstance Win32_Processor
Write-Host "    $($cpu.Name)"
Write-Host "    Cores: $($cpu.NumberOfCores) / Logical processors: $($cpu.NumberOfLogicalProcessors)"
Write-Host ""

Write-Host "Quan sat: Idle (chua co Chrome worker) -> tong khoang 800 MB" -ForegroundColor Magenta
Write-Host "          Khi worker pickup job va chay Chrome -> peak 2.5-3 GB / worker" -ForegroundColor Magenta
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " HOAN TAT - Hay chup man hinh cua so Terminal nay" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
