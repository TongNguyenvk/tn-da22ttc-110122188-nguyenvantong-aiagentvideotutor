# ============================================================
# Script 06: Rate Limit - 10/minute tra ve HTTP 429
# Tuong ung: Hinh 4.c - HTTP 429 Too Many Requests
#
# Chay 00_setup_demo_user.ps1 truoc do de co $env:WEBREEL_TOKEN
# ============================================================
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WebReel - Kiem thu Rate Limiter (15 yeu cau / 1 phut)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not $env:WEBREEL_TOKEN) {
    Write-Host "LOI: Chua co \$env:WEBREEL_TOKEN. Hay chay 00_setup_demo_user.ps1 truoc." -ForegroundColor Red
    exit 1
}

$token = $env:WEBREEL_TOKEN
$payload = '{"task":"demo rate limit","video_name":"rl_test","job_type":"web","config":{}}'

Write-Host "Gui 15 yeu cau POST /api/queue/submit (gioi han 10/phut)..." -ForegroundColor Yellow
Write-Host ""

for ($i = 1; $i -le 15; $i++) {
    try {
        $resp = Invoke-WebRequest -Method POST `
            -Uri "http://localhost:3000/api/queue/submit" `
            -ContentType "application/json" `
            -Headers @{ Authorization = "Bearer $token" } `
            -Body $payload -UseBasicParsing -ErrorAction Stop
        $code = $resp.StatusCode
        Write-Host ("Request #{0,2} -> HTTP {1} OK" -f $i, $code) -ForegroundColor Green
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        $body = ""
        try {
            $stream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $body = $reader.ReadToEnd()
        } catch {}
        if ($code -eq 429) {
            Write-Host ("Request #{0,2} -> HTTP {1} Too Many Requests | {2}" -f $i, $code, $body) -ForegroundColor Red
        } else {
            Write-Host ("Request #{0,2} -> HTTP {1} | {2}" -f $i, $code, $body) -ForegroundColor DarkRed
        }
    }
}
Write-Host ""

Write-Host "Ket qua mong doi: 10 yeu cau dau tra 200/201, 5 yeu cau cuoi tra 429" -ForegroundColor Magenta
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " HOAN TAT - Hay chup man hinh cua so Terminal nay" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
