param([string]$Python = 'python', [switch]$SkipModels, [switch]$SkipCPUOptimization, [switch]$SkipSemanticSearch, [switch]$WithLocalChat, [switch]$WithSubjectTools, [switch]$WithDev)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$setupArgs = @('-u', 'scripts/bootstrap.py')
if ($SkipModels) { $setupArgs += '--skip-models' }
if ($SkipCPUOptimization) { $setupArgs += '--skip-cpu-optimization' }
if ($SkipSemanticSearch) { $setupArgs += '--skip-semantic-search' }
if ($WithLocalChat) { $setupArgs += '--with-local-chat' }
if ($WithSubjectTools) { $setupArgs += '--with-subject-tools' }
if ($WithDev) { $setupArgs += '--with-dev' }
$appPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $appPython) { & $appPython @setupArgs } else { & $Python @setupArgs }
if ($LASTEXITCODE -ne 0) { throw 'Cài đặt chưa hoàn tất. Xem lỗi ở trên rồi chạy lại.' }
