param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Chưa có môi trường Python. Chạy setup.ps1 trước.'
}
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
Write-Host 'Đang khởi động LumaNest...' -ForegroundColor Cyan
Write-Host 'Trình duyệt mặc định sẽ tự mở khi ứng dụng sẵn sàng.'
Write-Host 'Giữ cửa sổ này mở khi dùng ứng dụng. Nhấn Ctrl+C để dừng.'
& $taskPython -u scripts/launch.py --port $Port
if ($LASTEXITCODE -ne 0) {
    throw "Ứng dụng không khởi động được (mã lỗi $LASTEXITCODE). Xem thông báo phía trên."
}
