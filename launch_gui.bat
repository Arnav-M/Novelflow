@echo off
cd /d "%~dp0"

if exist "dist\Novelflow\Novelflow.exe" (
    start "" "dist\Novelflow\Novelflow.exe"
    exit /b
)

if exist "Novelflow.exe" (
    start "" "Novelflow.exe"
    exit /b
)

where novelflow-gui >nul 2>&1
if %errorlevel%==0 (
    start "" novelflow-gui
    exit /b
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
    set PYTHONPATH=%~dp0src
    start "" pythonw -m novelflow.gui
    exit /b
)

echo.
echo Novelflow GUI could not start.
echo.
echo Build installer:  build_installer.bat
echo Or dev install:   pip install -e .
echo.
pause
