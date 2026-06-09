# ============================================================
# Script 00 (SETUP - chay 1 lan): Tao user demo de test rate limit
# Sau khi tao xong, lay token luu vao bien moi truong $env:WEBREEL_TOKEN
# ============================================================
$ErrorActionPreference = "Stop"

$apiBase = "http://localhost:3000/api"
$email = "chuong4_demo@webreel.com"
$password = "DemoPassword123!"

Write-Host "[1/4] Dang ky user demo ($email)..." -ForegroundColor Yellow
$body = @{ email = $email; password = $password; name = "Chuong4 Demo" } | ConvertTo-Json
try {
    $r = Invoke-RestMethod -Method POST -Uri "$apiBase/auth/register" -ContentType "application/json" -Body $body
    Write-Host "  -> Da dang ky: $($r.email)" -ForegroundColor Green
} catch {
    Write-Host "  -> User co the da ton tai (bo qua loi 400/409)" -ForegroundColor DarkYellow
}

Write-Host "[2/4] Mo khoa verify email (qua mongosh)..." -ForegroundColor Yellow
$mongoCmd = 'db = db.getSiblingDB("webreel"); db.users.updateOne({email:"' + $email + '"}, {$set:{email_verified:true, status:"active"}})'
docker exec webreel-mongodb mongosh -u webreel -p webreel_mongo_2026 --authenticationDatabase admin --quiet --eval $mongoCmd | Out-Null
Write-Host "  -> Da verify email" -ForegroundColor Green

Write-Host "[3/4] Dang nhap de lay JWT token..." -ForegroundColor Yellow
$loginBody = @{ email = $email; password = $password } | ConvertTo-Json
$resp = Invoke-RestMethod -Method POST -Uri "$apiBase/auth/login" -ContentType "application/json" -Body $loginBody
$token = $resp.access_token
Write-Host "  -> Token: $($token.Substring(0,40))..." -ForegroundColor Green

Write-Host "[4/4] Luu token vao bien moi truong WEBREEL_TOKEN..." -ForegroundColor Yellow
$env:WEBREEL_TOKEN = $token
[Environment]::SetEnvironmentVariable("WEBREEL_TOKEN", $token, "User")
Write-Host "  -> Da luu vao User Environment Variable" -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " SETUP HOAN TAT" -ForegroundColor Green
Write-Host " Bay gio co the chay 06_rate_limit_429.ps1 trong cua so moi" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
