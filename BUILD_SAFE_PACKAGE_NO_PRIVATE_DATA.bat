@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo Building SAFE ZERO BOT package
echo No accounts.json / credentials.json / logs / backups will be copied.
echo Images stay external next to the exe.
echo ========================================

call BUILD_EXE_EXTERNAL_ASSETS.bat
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

if exist dist\accounts.json del /q dist\accounts.json
if exist dist\credentials.json del /q dist\credentials.json
if exist dist\settings.json del /q dist\settings.json
if exist dist\item_selections.json del /q dist\item_selections.json
if exist dist\logs rmdir /s /q dist\logs
if exist dist\backups rmdir /s /q dist\backups

echo.
echo SAFE PACKAGE READY:
echo dist\ZERO_LOGIN_BOT.exe
echo dist\assets\
echo.
echo Private runtime files were removed from dist.
pause
