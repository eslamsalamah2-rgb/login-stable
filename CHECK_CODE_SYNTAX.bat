@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo ZERO BOT - Python syntax check
echo This does not run the bot or click anything.
echo ========================================

python -m compileall -q .
if errorlevel 1 (
    echo.
    echo SYNTAX CHECK FAILED.
    echo Read the Python error above.
    pause
    exit /b 1
)

echo.
echo SYNTAX CHECK OK.
pause
