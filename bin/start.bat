@echo off
chcp 936 >nul 2>&1
rem xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码
rem 本文件为GBK编码,禁止chcp 65001:UTF-8码页下cmd解析批处理会按字节错位切割行
title 海棠文档工坊

echo ============================================================
echo   海棠文档工坊 - 启动服务
echo ============================================================
echo.

:: 切换到项目根目录（脚本在 bin 目录下，需要返回上层）
cd /d "%~dp0.."
echo 当前目录: %CD%
echo.

:: 检查并停止已运行的服务
echo [1/6] 检查是否有已运行的服务...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   发现端口8000被占用，正在停止旧服务 PID: %%a
    taskkill /F /PID %%a >nul 2>&1
    timeout /t 2 /nobreak >nul
)
echo   端口8000已就绪
echo.

:: ============================================================
:: 检测 Python
:: ============================================================
echo [2/6] 检测Python环境...

rem xuechong 2026-08-07 启动失败修复：优先项目venv，避免误用PATH其他Python
rem xuechong 2026-08-17 crabapple-docstudio 环境隔离加固
rem 服务只认项目venv，缺失自动构建，种子Python固定探测验版3.11
rem PATH候选仅建venv不直接跑服务，防外部软件污染PATH误用
rem xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
rem venv全自动健康检测：健康直接用；损坏自动删除重建；不存在自动创建
set "VENV_PY=%CD%\.venv\Scripts\python.exe"
set "VENV_HEALTHY=1"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import uvicorn, fastapi, cv2, numpy, PIL, fitz, torch" >nul 2>&1
    if errorlevel 1 set "VENV_HEALTHY=0"
) else (
    set "VENV_HEALTHY=0"
)

if "%VENV_HEALTHY%"=="1" (
    echo   使用项目虚拟环境: %VENV_PY%
    set "PYTHON_CMD=%VENV_PY%"
    goto check_node
)

if exist "%CD%\.venv" (
    echo   检测到虚拟环境损坏，自动删除重建...
    rd /s /q "%CD%\.venv"
)

echo   开始自动构建虚拟环境（本地离线包优先，缺失才联网）...

:: ---- 固定探测顺序：显式安装路径 → py 启动器 → PATH 候选（逐一验版 3.11.x） ----
set "SEED_PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "SEED_PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined SEED_PY if exist "C:\Program Files\Python311\python.exe" set "SEED_PY=C:\Program Files\Python311\python.exe"
if not defined SEED_PY if exist "C:\Python311\python.exe" set "SEED_PY=C:\Python311\python.exe"

if not defined SEED_PY (
    py -3.11 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        for /f "usebackq delims=" %%p in (`py -3.11 -c "import sys; print(sys.executable)"`) do set "SEED_PY=%%p"
    )
)

if not defined SEED_PY (
    for /f "delims=" %%p in ('where python 2^>nul') do (
        if not defined SEED_PY (
            "%%p" -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,11) else 1)" >nul 2>&1
            if not errorlevel 1 set "SEED_PY=%%p"
        )
    )
)

if not defined SEED_PY goto no_python_found
echo   找到 Python 3.11: %SEED_PY%

:: ---- 创建项目虚拟环境并安装依赖 ----
echo   创建项目虚拟环境 .venv ...
"%SEED_PY%" -m venv "%~dp0..\.venv"
if not exist "%VENV_PY%" goto venv_create_failed

echo   安装依赖包 ...
rem xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
rem pip按UTF-8读取依赖清单：修复GBK区域Windows解码中文注释报错
set PYTHONUTF8=1
if exist "%~dp0..\assets\windows\wheels" (
    echo   使用本地离线依赖包 assets\windows\wheels ...
    "%VENV_PY%" -m pip install --no-index --find-links="%~dp0..\assets\windows\wheels" -r "%~dp0..\assets\windows\requirements-win-freeze.txt"
    if errorlevel 1 (
        echo   [警告] 本地离线包安装失败，转为联网安装 ...
        "%VENV_PY%" -m pip install -r requirements.txt
        if errorlevel 1 (
            echo   [警告] 联网安装也失败，服务启动自检将给出详细缺失清单
        ) else (
            echo   依赖安装完成（联网）
        )
    ) else (
        echo   依赖安装完成（本地离线包）
    )
) else (
    echo   未找到本地离线包，联网安装 requirements.txt ...
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo   [警告] 依赖安装失败，服务启动自检将给出详细缺失清单
    ) else (
        echo   依赖安装完成
    )
)
set "PYTHON_CMD=%VENV_PY%"
goto check_node

:no_python_found
echo.
echo ============================================================
echo   [错误] 找不到 Python 3.11！
echo ============================================================
echo.
echo   已按固定顺序探测以下位置均未找到 Python 3.11：
echo     1. %%LOCALAPPDATA%%\Programs\Python\Python311\python.exe
echo     2. C:\Program Files\Python311\python.exe
echo     3. C:\Python311\python.exe
echo     4. py -3.11 启动器
echo     5. PATH 中的 python（版本校验 3.11.x，仅用于创建虚拟环境）
echo.
echo   请安装 Python 3.11 后重试:
echo     https://www.python.org/downloads/release/python-3119/
echo.
pause
exit /b 1

:venv_create_failed
echo.
echo ============================================================
echo   [错误] 项目虚拟环境创建失败！
echo ============================================================
echo.
echo   种子 Python: %SEED_PY%
echo   请检查磁盘空间与目录权限后重试
echo.
pause
exit /b 1

:: ============================================================
:: 检查前端产物（缺失才构建，无 Node.js 醒目报错）
:: ============================================================
:check_node
echo.
echo [3/6] 检查前端产物...

rem xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码
rem 前端缺失白屏修复:dist就绪直接用,缺失时无Node醒目报错退出
if exist "frontend\dist\index.html" (
    echo   前端产物已就绪: frontend\dist
    goto clean_cache
)

echo   [警告] 前端产物缺失: frontend\dist
where node >nul 2>&1
if %errorlevel% neq 0 goto no_frontend
if not exist "frontend\package.json" goto no_frontend

if not exist "frontend\node_modules" (
    echo   安装前端依赖...
    cd frontend
    call npm install
    cd ..
)
if not exist "frontend\node_modules\*" goto no_frontend

echo   构建前端项目...
cd frontend
call npm run build
cd ..
if exist "frontend\dist\index.html" (
    echo   前端构建成功
    goto clean_cache
)

rem xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码
rem 错误提示用type输出文本文件,避免bat内长中文行解析问题
rem xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码
rem 中文提示经cmd65001解析会错位切割,改用type输出文本文件
:no_frontend
type "%~dp0frontend_missing_msg.txt"
echo.
pause
exit /b 1

:: ============================================================
:: 清理Python缓存
:: ============================================================
:clean_cache
echo.
echo [4/6] 清理Python缓存...
if exist "backend\__pycache__" (
    rd /s /q "backend\__pycache__" >nul 2>&1
    echo   已清理 backend\__pycache__
)
if exist "__pycache__" (
    rd /s /q "__pycache__" >nul 2>&1
    echo   已清理 __pycache__
)
echo   缓存清理完成
echo.

:: ============================================================
:: 检查目录结构
:: ============================================================
:check_dirs
echo [5/6] 检查目录结构...
call "%~dp0_paths.bat"
echo   目录结构已就绪
echo.

:: ============================================================
:: 启动服务
:: ============================================================
:start_server
echo [6/6] 启动服务...
echo.

if not exist "start_server.py" (
    echo   [错误] 找不到 start_server.py!
    echo   当前目录: %CD%
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo   服务将在后台启动，浏览器即将打开
echo ============================================================
echo.

:: 后台启动服务（最小化窗口，方便排查启动错误）
set NO_BROWSER=1
start "文档扫描服务" /d "%CD%" /min cmd /k "title 文档扫描服务 && set NO_BROWSER=1 && %PYTHON_CMD% start_server.py || (echo. && echo ============================================================ && echo   服务启动失败！请截图此窗口内容反馈 && echo ============================================================ && echo. && pause)"

:: 等待服务启动并自检
echo   等待服务启动并自检...
set "SERVER_OK=0"
for /l %%i in (1,1,30) do (
    timeout /t 2 /nobreak >nul
    curl -s -o nul -w "%%{http_code}" http://localhost:8000/api/health 2>nul | findstr "200" >nul && set "SERVER_OK=1" && goto server_ready
    echo   等待中... (%%i/30)
)
echo   [警告] 服务启动超时，请检查"文档扫描服务"窗口中的日志
goto open_browser

:server_ready
echo   服务自检通过

:open_browser
:: 打开浏览器
start "" "http://localhost:8000"

if "%SERVER_OK%"=="1" (
    echo [成功] 服务已在后台启动！
    echo.
    echo   （任务栏中最小化的"文档扫描服务"窗口是服务进程，请勿关闭）
) else (
    echo [警告] 服务可能未正常启动！
    echo   请点击任务栏中"文档扫描服务"窗口查看错误日志
)
echo.
echo   此窗口将自动关闭...
echo.

timeout /t 3 /nobreak >nul
exit
