# ============================================================
# Script 07: Thuoc tinh video thanh pham (FullHD 30fps)
# Tuong ung: Hinh 4.u - Properties video MP4
#
# Truyen vao 1 file MP4 (mac dinh: tim file moi nhat trong volume output_data)
# ============================================================
param(
    [string]$VideoPath
)
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WebReel - Thuoc tinh file video thanh pham" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not $VideoPath) {
    Write-Host "[1] Khong truyen VideoPath -> tim file MP4 moi nhat trong /app/output cua web-worker volume..." -ForegroundColor Yellow
    $latest = docker run --rm -v webreel-ai-agent_output_data:/app/output alpine sh -c "find /app/output -name '*.mp4' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-"
    if ([string]::IsNullOrWhiteSpace($latest)) {
        Write-Host "Khong tim thay file MP4 nao trong volume output_data." -ForegroundColor Red
        Write-Host "Hay chay 03_ffmpeg_stream_copy.ps1 truoc, sau do truyen tham so -VideoPath" -ForegroundColor Red
        Write-Host "Vi du: .\07_video_properties.ps1 -VideoPath `"$env:TEMP\webreel_ffmpeg_demo\final.mp4`"" -ForegroundColor Red
        exit 1
    }
    $latest = $latest.Trim()
    Write-Host "File moi nhat trong container: $latest" -ForegroundColor Green
    Write-Host ""

    Write-Host "[2] Phan tich bang ffprobe..." -ForegroundColor Yellow
    docker run --rm -v webreel-ai-agent_output_data:/app/output linuxserver/ffmpeg `
        -i $latest -hide_banner 2>&1 | Select-String -Pattern "Duration|Stream|Video|Audio|Metadata"
} else {
    if (-not (Test-Path $VideoPath)) {
        Write-Host "Khong tim thay file: $VideoPath" -ForegroundColor Red
        exit 1
    }
    Write-Host "File: $VideoPath" -ForegroundColor Green
    Write-Host ""

    $dir = Split-Path $VideoPath -Parent
    $file = Split-Path $VideoPath -Leaf

    Write-Host "[1] Phan tich bang ffprobe (qua Docker)..." -ForegroundColor Yellow
    docker run --rm -v "${dir}:/work" linuxserver/ffmpeg `
        -i "/work/$file" -hide_banner 2>&1 | Select-String -Pattern "Duration|Stream|Video|Audio|Metadata"
    Write-Host ""

    Write-Host "[2] Thuoc tinh Windows (Get-Item):" -ForegroundColor Yellow
    Get-Item $VideoPath | Format-List Name, Length, CreationTime, LastWriteTime
}
Write-Host ""

Write-Host "Ket qua mong doi: Video: 1920x1080, 30 fps; Audio: aac/stereo" -ForegroundColor Magenta
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " HOAN TAT - Hay chup man hinh cua so Terminal nay" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
