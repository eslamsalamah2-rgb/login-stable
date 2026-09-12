@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "EXE_NAME=Login"

echo ========================================
echo Building %EXE_NAME%.exe
echo Application name: Login
echo User image assets stay OUTSIDE the exe
echo ========================================

if not exist main.py (
    echo ERROR: main.py not found. Run this file from the project folder.
    pause
    exit /b 1
)

python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo ERROR: PyInstaller install/update failed.
    pause
    exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name %EXE_NAME% ^
    --collect-data customtkinter ^
    main.py

if errorlevel 1 (
    echo ERROR: Build failed.
    pause
    exit /b 1
)

echo.
echo Copying external files next to the exe...

if exist assets (
    xcopy assets dist\assets\ /E /I /Y >nul
)

if exist accounts.json copy /Y accounts.json dist\accounts.json >nul
if exist settings.json copy /Y settings.json dist\settings.json >nul
if exist item_selections.json copy /Y item_selections.json dist\item_selections.json >nul
if exist accounts.json.example copy /Y accounts.json.example dist\accounts.json.example >nul

if not exist dist\assets (
    echo WARNING: dist\assets was not created. External image assets are missing.
)

echo.
echo DONE.
echo Exe path:
echo dist\%EXE_NAME%.exe
echo.
echo Keep this structure:
echo dist\Login.exe
echo dist\assets\...
echo dist\accounts.json
echo dist\settings.json
echo dist\item_selections.json
echo.
echo IMPORTANT: Drop/Use/Sash images are external in dist\assets, not inside the exe.
pause
