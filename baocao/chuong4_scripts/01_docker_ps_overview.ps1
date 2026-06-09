# ============================================================
# Script 01: Tong quan cum Docker dang chay
# Tuong ung: minh chung muc 4.1.1 / 4.2 - kien truc Docker
# ============================================================
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WebReel - Tong quan cum vung chua Docker (docker-compose.prod.yml)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Phien ban Docker Engine:" -ForegroundColor Yellow
docker version --format 'Docker Engine v{0}' -f (docker version --format '{{.Server.Version}}')
Write-Host ""

Write-Host "[2/3] Danh sach container dang chay:" -ForegroundColor Yellow
docker ps --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"
Write-Host ""

Write-Host "[3/3] Tieu thu tai nguyen thoi gian thuc:" -ForegroundColor Yellow
docker stats --no-stream --format "table {{.Name}}`t{{.CPUPerc}}`t{{.MemUsage}}`t{{.MemPerc}}"
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " HOAN TAT - Hay chup man hinh cua so Terminal nay" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
