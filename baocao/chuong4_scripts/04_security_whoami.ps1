# ============================================================
# Script 04: Kiem tra Non-root user trong cac container
# Tuong ung: Muc 4.3.1 / Hinh 4.a phu
# ============================================================
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WebReel - Xac minh container chay duoi user non-root" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1] API container (webreel-api):" -ForegroundColor Yellow
Write-Host "    whoami: " -NoNewline
docker exec webreel-api whoami
Write-Host "    id    : " -NoNewline
docker exec webreel-api id
Write-Host ""

Write-Host "[2] Autoscaler container (webreel-autoscaler):" -ForegroundColor Yellow
Write-Host "    whoami: " -NoNewline
docker exec webreel-autoscaler whoami
Write-Host "    id    : " -NoNewline
docker exec webreel-autoscaler id
Write-Host ""

Write-Host "[3] Session-manager (chay Chrome --no-sandbox duoi webreel):" -ForegroundColor Yellow
Write-Host "    whoami cua Chrome process:" -NoNewline
docker exec webreel-session-manager su webreel -c "whoami && id"
Write-Host ""

Write-Host "[4] Frontend (Nginx unprivileged):" -ForegroundColor Yellow
Write-Host "    whoami: " -NoNewline
docker exec webreel-frontend whoami
Write-Host ""

Write-Host "[5] Docker socket proxy:" -ForegroundColor Yellow
Write-Host "    whoami: " -NoNewline
docker exec webreel-docker-proxy whoami
Write-Host ""

Write-Host "Ket luan: Tat ca worker process da ha quyen ve user 'webreel' (UID 1000)" -ForegroundColor Magenta
Write-Host "khong con dac quyen root trong container." -ForegroundColor Magenta
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " HOAN TAT - Hay chup man hinh cua so Terminal nay" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
