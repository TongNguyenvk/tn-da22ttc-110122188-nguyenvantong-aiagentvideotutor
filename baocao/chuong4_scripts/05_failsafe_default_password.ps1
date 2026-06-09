# ============================================================
# Script 05: Co che Fail-safe khi phat hien mat khau mac dinh
# Tuong ung: Hinh 4.a - Terminal log "CRITICAL SECURITY ALERT ... Exiting"
#
# Co che: trong backend/main.py, ham lifespan() check
#   - Neu ENVIRONMENT=production VA password = default
#   - Goi sys.exit(1) -> container thoat ngay
# ============================================================
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WebReel - Demo Fail-safe khi dung mat khau mac dinh" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1] Show source code (backend/main.py - ham lifespan):" -ForegroundColor Yellow
docker exec webreel-api sh -c "sed -n '138,158p' /app/webreel-ai-agent/backend/main.py"
Write-Host ""

Write-Host "[2] Bay gio chay 1 container API moi voi ENVIRONMENT=production" -ForegroundColor Yellow
Write-Host "    + REDIS_PASSWORD=webreel_secret_2026 (default)" -ForegroundColor Yellow
Write-Host "    -> Container PHAI tu thoat va log CRITICAL SECURITY ALERT" -ForegroundColor Yellow
Write-Host ""

$projectDir = "F:\==HK1-2526==\ThucTap\webreel\webreel-ai-agent"
Push-Location $projectDir

docker run --rm --name webreel-failsafe-test `
    --network webreel-ai-agent_db-net `
    -e ENVIRONMENT=production `
    -e REDIS_PASSWORD=webreel_secret_2026 `
    -e MONGO_PASSWORD=webreel_mongo_2026 `
    -e REDIS_URL=redis://:webreel_secret_2026@redis:6379/0 `
    -e MONGO_URL=mongodb://webreel:webreel_mongo_2026@mongodb:27017 `
    -e MONGO_DB=webreel `
    -e OUTPUT_DIR=/app/output `
    -e PYTHONIOENCODING=utf-8 `
    webreel-ai-agent-api 2>&1 | Select-String -Pattern "SECURITY|CRITICAL|Exit|default|password|Halting"

$exit = $LASTEXITCODE
Pop-Location

Write-Host ""
Write-Host "Container exit code: $exit (khac 0 = bi cuong che dung dung mong doi)" -ForegroundColor Magenta
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " HOAN TAT - Hay chup man hinh cua so Terminal nay" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
