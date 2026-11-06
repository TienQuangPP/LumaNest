@echo off
setlocal
chcp 65001 >nul
title Dong goi ban phat hanh F Smart Memories

:: Tim thu muc goc chua ma nguon
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%scripts\package_release.py" (
    cd /d "%SCRIPT_DIR%"
) else if exist "%SCRIPT_DIR%LumaNest\scripts\package_release.py" (
    cd /d "%SCRIPT_DIR%LumaNest"
) else (
    echo [LOI] Khong tim thay scripts\package_release.py
    pause
    exit /b 1
)

:: Tim trinh thong dich Python
set "PY_CMD="
if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
) else (
    py -3.12 --version >nul 2>&1
    if errorlevel 0 (
        set "PY_CMD=py -3.12"
    ) else (
        python --version >nul 2>&1
        if errorlevel 0 (
            set "PY_CMD=python"
        )
    )
)

if "%PY_CMD%"=="" (
    echo [LOI] Khong tim thay Python. Vui long cai dat Python hoac tao .venv.
    pause
    exit /b 1
)

echo ======================================================================
echo    KHOI CHAY DONG GOI F SMART MEMORIES
echo ======================================================================
echo Thu muc: %cd%
echo Python : %PY_CMD%
echo.

%PY_CMD% scripts\package_release.py %*
set "EXIT_CODE=%errorlevel%"

echo.
if %EXIT_CODE% equ 0 (
    echo [THANH CONG] Qua trinh dong goi hoan tat.
) else (
    echo [LOI] Qua trinh dong goi that bai. Ma loi: %EXIT_CODE%
)
echo ======================================================================

if %EXIT_CODE% neq 0 (
    echo.
    echo [THONG BAO] Co loi xay ra trong qua trinh dong goi.
    pause
)
exit /b %EXIT_CODE%
