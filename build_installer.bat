@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Novelflow installer build ===
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

echo [1/3] Installing build tools...
python -m pip install -q pyinstaller
if errorlevel 1 goto fail

echo [2/3] Building Novelflow.exe...
python -m PyInstaller novelflow-gui.spec --noconfirm --clean
if errorlevel 1 goto fail
if not exist "dist\Novelflow\Novelflow.exe" (
    echo Build failed: dist\Novelflow\Novelflow.exe not found.
    goto fail
)

set "ISCC="
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 7\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 7\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo.
    echo [3/3] Inno Setup not installed.
    echo.
    echo Download the free compiler once:
    echo   https://jrsoftware.org/isdl.php
    echo.
    echo Portable app is ready at: dist\Novelflow\Novelflow.exe
    echo Re-run this file after installing Inno Setup to create Novelflow-Setup.exe
    echo.
    pause
    exit /b 0
)

echo [3/3] Creating Windows installer...
"%ISCC%" installer\Novelflow.iss
if errorlevel 1 goto fail

echo.
echo Done!
echo   Installer: installer\output\Novelflow-Setup.exe
echo   Portable:  dist\Novelflow\Novelflow.exe
echo.
echo Upload Novelflow-Setup.exe to GitHub Releases for end users.
echo.
pause
exit /b 0

:fail
echo.
echo Build failed.
pause
exit /b 1
