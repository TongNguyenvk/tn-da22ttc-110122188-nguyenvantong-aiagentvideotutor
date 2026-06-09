# ============================================================
# Script 02: Submit 1 job va xem log Worker pickup tu Redis
# Tuong ung: Hinh 4.z - Nhat ky phan phoi tac vu qua Redis
# ============================================================
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WebReel - Submit job qua /api/jobs & xem log Worker" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Tao payload
$payload = @{
    task = "Open https://example.com and read the heading"
    video_name = "demo_chapter4"
    environment = "web"
    config = @{}
} | ConvertTo-Json -Compress

Write-Host "[1/2] Gui POST toi http://localhost:8000/api/jobs (qua container)..." -ForegroundColor Yellow
Write-Host "       Payload: $payload"
Write-Host ""
$resp = docker exec webreel-api curl -s -i -X POST http://localhost:8000/api/jobs `
    -H "Content-Type: application/json" `
    -d $payload
Write-Host "Response:" -ForegroundColor Green
$resp
Write-Host ""

Write-Host "[2/2] Doi 3 giay roi lay nhat ky API (xem log Worker pickup)..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
Write-Host ""
docker logs --tail 25 webreel-api 2>&1 | Select-String -Pattern "Job submitted|Routing|Phase 1|Status transition|pickup|Worker"
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " HOAN TAT - Hay chup man hinh cua so Terminal nay" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
