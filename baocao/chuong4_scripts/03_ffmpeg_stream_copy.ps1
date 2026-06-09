# ============================================================
# Script 03: FFmpeg Stream Copy minh chung
# Tuong ung: Hinh 4.v - FFmpeg thuc thi Stream Copy
# Chay ffmpeg -c copy bi nhao video (tinh) + nhao am thanh
# ============================================================
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WebReel - Minh chung FFmpeg Stream Copy" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$tmpDir = "$env:TEMP\webreel_ffmpeg_demo"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

Write-Host "[1/4] Tao video silent 10 giay 1920x1080 30fps..." -ForegroundColor Yellow
docker run --rm -v "${tmpDir}:/work" linuxserver/ffmpeg `
    -y -f lavfi -i "color=c=navy:s=1920x1080:r=30:d=10" `
    -c:v libx264 -preset ultrafast /work/silent.mp4 2>&1 | Select-Object -Last 3
Write-Host ""

Write-Host "[2/4] Tao audio 440Hz dai 10 giay..." -ForegroundColor Yellow
docker run --rm -v "${tmpDir}:/work" linuxserver/ffmpeg `
    -y -f lavfi -i "sine=frequency=440:duration=10" -c:a aac /work/voice.m4a 2>&1 | Select-Object -Last 3
Write-Host ""

Write-Host "[3/4] Phoi tron bang Stream Copy (-c:v copy -c:a copy)..." -ForegroundColor Yellow
$start = Get-Date
docker run --rm -v "${tmpDir}:/work" linuxserver/ffmpeg `
    -y -i /work/silent.mp4 -i /work/voice.m4a `
    -map 0:v -map 1:a -c:v copy -c:a copy `
    /work/final.mp4 2>&1 | Select-String -Pattern "Stream|copy|time=|video:"
$elapsed = (Get-Date) - $start
Write-Host ""
Write-Host "  >>> Render completed in $($elapsed.TotalSeconds.ToString('F2'))s <<<" -ForegroundColor Magenta
Write-Host ""

Write-Host "[4/4] Thuoc tinh file final.mp4:" -ForegroundColor Yellow
docker run --rm -v "${tmpDir}:/work" linuxserver/ffmpeg `
    -i /work/final.mp4 -hide_banner 2>&1 | Select-String -Pattern "Duration|Stream|Video|Audio"
Write-Host ""
Write-Host "File tai: $tmpDir\final.mp4" -ForegroundColor Cyan
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " HOAN TAT - Hay chup man hinh cua so Terminal nay" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
