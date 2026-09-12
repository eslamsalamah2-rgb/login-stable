@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ZERO_LOGIN_BOT.exe (
    echo ERROR: ZERO_LOGIN_BOT.exe was not found beside this launcher.
    echo Build it first with BUILD_EXE_EXTERNAL_ASSETS.bat
    pause
    exit /b 1
)

start "" "%~dp0ZERO_LOGIN_BOT.exe"
exit /b 0
