@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title LumaNest - AI Photo Studio
if exist "LumaNest.exe" (
  start "" "%~dp0LumaNest.exe"
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  echo Chua cai dat. Chay: python scripts\bootstrap.py --with-local-chat --with-subject-tools
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -u scripts\launch.py
if errorlevel 1 pause
