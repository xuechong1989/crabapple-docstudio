@echo off
chcp 65001 >nul 2>&1
title Document Scanner - openEuler Build (CUDA 12.8)

echo ============================================================
echo   Document Scanner - openEuler Build
echo ============================================================
echo.
echo   Target:  Linux (OpenEuler / CentOS / RHEL)
echo   PyTorch: CUDA 12.8 (RTX 5070 sm_120 / Blackwell)
echo   Python:  3.11
echo.

cd /d "%~dp0.."
call "%~dp0_paths.bat"

echo [Check] Python environment...
set "PYTHON_CMD="
if defined DOCSTUDIO_PYTHON (
    "%DOCSTUDIO_PYTHON%" --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=%DOCSTUDIO_PYTHON%"
        echo   Use DOCSTUDIO_PYTHON: %DOCSTUDIO_PYTHON%
    )
)
if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
        echo   Use system PATH python
    )
)
if not defined PYTHON_CMD (
    echo   [ERROR] Python not found!
    echo   Install Python 3.11+ or set DOCSTUDIO_PYTHON env var.
    pause
    exit /b 1
)
echo   Python: %PYTHON_CMD%
echo.

echo [Pre-build] Run tests...
"%PYTHON_CMD%" scripts/run_tests.py
if errorlevel 1 (
    echo   [FAIL] Tests failed! Fix before building.
    pause
    exit /b 1
)
echo.

echo Select build type:
echo   [1] Pack dependencies (use existing offline packages)
echo   [2] Pack program (lightweight, no deps)
echo   [3] Pack both
echo   [4] Validate + download missing whl, then pack both
echo.
choice /c 1234 /m "Enter choice"
set "SEL=%errorlevel%"
echo.

if "%SEL%"=="1" goto :do_deps
if "%SEL%"=="2" goto :do_program
if "%SEL%"=="3" goto :do_all
if "%SEL%"=="4" goto :do_download_and_all
goto :do_program

:do_deps
echo.
echo ============================================================
echo   Pack Dependencies
echo ============================================================
echo.

:: Check offline packages exist
echo [Check] Offline packages...
set "WHL_COUNT=0"
for /f %%A in ('dir /b assets\linux\wheels\*.whl 2^>nul ^| find /c /v ""') do set "WHL_COUNT=%%A"
echo   Found %WHL_COUNT% whl files in assets\linux\wheels\
if "%WHL_COUNT%"=="0" (
    echo.
    echo [ERROR] No whl files found!
    echo   Path: %CD%\assets\linux\wheels\
    echo   Please run option [4] to download offline packages first.
    pause
    exit /b 1
)
echo.

echo [Pack] Building dependency package...
call :run_py pack_deps.py
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency pack failed!
    pause
    exit /b 1
)
echo.

echo ============================================================
echo   Dependencies pack done!
echo.
echo   Deploy steps:
echo     1. Upload crabapple-docstudio-deps-v*.tar.gz to server
echo     2. tar -xzf crabapple-docstudio-deps-v*.tar.gz
echo     3. cd dependence
echo     4. chmod +x install_deps.sh
echo     5. ./install_deps.sh
echo     6. cd .. ^&^& mv dependence /data/crabapple-docstudio/dependence
echo     (Only deploy once, reuse for future versions)
echo ============================================================
pause
exit /b 0

:do_program
echo.
echo ============================================================
echo   Pack Program (lightweight, no offline deps)
echo ============================================================
echo.

echo [Pack] Building program package...
call :run_py pack_release.py --platform linux
if errorlevel 1 (
    echo.
    echo [ERROR] Pack failed!
    pause
    exit /b 1
)
echo.

echo ============================================================
echo   Program pack done!
echo.
echo   Deploy steps:
echo     1. Upload crabapple-docstudio-v*.tar.gz to server
echo     2. tar -xzf crabapple-docstudio-v*.tar.gz
echo     3. cd crabapple-docstudio-v*
echo     4. chmod +x start.sh stop.sh
echo     5. ./start.sh
echo.
echo   Note: Ensure deps pack is already deployed
echo   at /data/crabapple-docstudio/dependence/
echo   (Only deploy once, reuse for future versions)
echo ============================================================
pause
exit /b 0

:do_all
call :do_deps
if errorlevel 1 goto :eof
call :do_program
goto :eof

:do_download_and_all
echo.
echo ============================================================
echo   Validate + Download Missing + Pack All
echo ============================================================
echo.

echo [1/4] Validate offline packages, download missing only...
echo.
echo   Checking each critical whl file in assets/linux/wheels/
echo   Existing complete files will be SKIPPED.
echo   Only missing or incomplete files will be downloaded.
echo.
call :run_py download_offline_deps.py --platform linux --cuda 12.8 --python-version 3.11 --validate
if errorlevel 1 (
    echo.
    echo [ERROR] Download failed! Check network.
    pause
    exit /b 1
)
echo.

set "WHL_COUNT=0"
for /f %%A in ('dir /b assets\linux\wheels\*.whl 2^>nul ^| find /c /v ""') do set "WHL_COUNT=%%A"
echo   Verified: %WHL_COUNT% whl files
if "%WHL_COUNT%"=="0" (
    echo [ERROR] No whl files after download!
    pause
    exit /b 1
)
echo.

echo [2/4] Pack dependencies...
call :run_py pack_deps.py
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency pack failed!
    pause
    exit /b 1
)
echo.

echo [3/4] Pack program...
call :run_py pack_release.py --platform linux
if errorlevel 1 (
    echo.
    echo [ERROR] Program pack failed!
    pause
    exit /b 1
)
echo.

echo ============================================================
echo   Full build done!
echo.
echo   Output files:
echo     - crabapple-docstudio-deps-v*.tar.gz (deps, deploy once)
echo     - crabapple-docstudio-v*.tar.gz      (program, per version)
echo.
echo   Deploy:
echo     1. Upload both tar.gz to server
echo     2. First: cd dependence ^&^& ./install_deps.sh
echo     3. Then:  cd .. ^&^& mv dependence /data/crabapple-docstudio/dependence
echo     4. Then:  cd crabapple-docstudio-v* ^&^& ./start.sh
echo ============================================================
pause
exit /b 0

:: ============================================================
:: Helper: run a Python script from the project's scripts/ directory
:: Usage: call :run_py script_name.py [args...]
:: ============================================================
:run_py
"%PYTHON_CMD%" scripts\%~1 %~2 %~3 %~4 %~5 %~6 %~7 %~8 %~9
goto :eof
