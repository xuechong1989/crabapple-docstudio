@echo off
rem xuechong 2026-08-28 removed chcp 65001: pure ASCII file needs no codepage; it corrupts GBK callers
rem ============================================================
rem _paths.bat - Shared disk path config module
rem Called by other .bat files via call "%~dp0_paths.bat"
rem
rem Strategy:
rem   - Use _WIN suffix variables first (e.g. DOCSTUDIO_BASE_DIR_WIN)
rem   - ${} refs in url.conf cannot expand in batch, derived vars calculated here
rem   - Linux absolute paths (starting with /) fallback to project defaults
rem ============================================================

rem 1. Parse url.conf
if exist "url.conf" (
    for /f "usebackq eol=# tokens=1,2 delims==" %%a in ("url.conf") do (
        if not "%%a"=="" if not "%%b"=="" set "%%a=%%b"
    )
)
rem 1.1 Clear variables with unexpanded ${} (config.py derives from DATA_DIR)
rem Prevent literal ${DOCSTUDIO_BASE_DIR} directory creation
set "HF_HOME="
set "CUDA_CACHE_PATH="
set "CUDA_CACHE_MAXSIZE="
set "TMPDIR="
set "TORCH_HOME="
set "MPLCONFIGDIR="
set "ULTRALYTICS_CONFIG_DIR="

rem 2. Windows prefers _WIN suffix variables
if defined DOCSTUDIO_BASE_DIR_WIN set "DOCSTUDIO_BASE_DIR=%DOCSTUDIO_BASE_DIR_WIN%"

rem 3. Detect Linux absolute paths (starting with /), invalid on Windows -> clear to trigger fallback
if defined DOCSTUDIO_BASE_DIR (
    echo %DOCSTUDIO_BASE_DIR%| findstr /b "/" >nul 2>&1
    if not errorlevel 1 set "DOCSTUDIO_BASE_DIR="
)

rem 4. Unified fallback defaults
if not defined DOCSTUDIO_BASE_DIR set "DOCSTUDIO_BASE_DIR=%CD%\data"

rem 5. Derived paths (calculated here, override invalid ${} values from url.conf)
set "DOCSTUDIO_DATA_DIR=%DOCSTUDIO_BASE_DIR%"
set "DOCSTUDIO_TMP_DIR=%DOCSTUDIO_BASE_DIR%\tmp"
set "DOCSTUDIO_DIST_DIR=%DOCSTUDIO_BASE_DIR%\dist"

rem 6. Create required subdirectories
if not exist "%DOCSTUDIO_BASE_DIR%" mkdir "%DOCSTUDIO_BASE_DIR%"
if not exist "%DOCSTUDIO_BASE_DIR%\data" mkdir "%DOCSTUDIO_BASE_DIR%\data"
if not exist "%DOCSTUDIO_BASE_DIR%\data\original" mkdir "%DOCSTUDIO_BASE_DIR%\data\original"
if not exist "%DOCSTUDIO_BASE_DIR%\data\target" mkdir "%DOCSTUDIO_BASE_DIR%\data\target"
if not exist "%DOCSTUDIO_BASE_DIR%\logs" mkdir "%DOCSTUDIO_BASE_DIR%\logs"
if not exist "%DOCSTUDIO_BASE_DIR%\tmp" mkdir "%DOCSTUDIO_BASE_DIR%\tmp"
if not exist "%DOCSTUDIO_BASE_DIR%\plugins" mkdir "%DOCSTUDIO_BASE_DIR%\plugins"
