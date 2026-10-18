# -*- coding: utf-8 -*-
"""
海棠文档工坊 - Web 后端服务
FastAPI 实现，支持批量文件上传和处理
集成 RapidOCR 实现图片转可搜索 PDF 功能（需要 Python 3.11）
"""

import os
import sys

# PaddlePaddle 环境变量（必须在导入 paddle 之前设置）
os.environ.setdefault('FLAGS_use_mkldnn', '0')
os.environ.setdefault('FLAGS_pir_apply_shape_optimization_pass', '0')
os.environ.setdefault('FLAGS_enable_pir_api', '0')
os.environ.setdefault('FLAGS_enable_pir_in_executor', '0')
os.environ.setdefault('FLAGS_enable_pir_with_pt_in_dy2st', '0')
os.environ.setdefault('FLAGS_pir_apply_inplace_pass', '0')

from pathlib import Path

from backend.services.logging_service import log_info, setup_utf8_encoding
setup_utf8_encoding()
import shutil
import io
import asyncio
import json
from datetime import datetime
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel

# PDF 生成
import fitz  # PyMuPDF

# ============================================================
# FastAPI 应用配置
# ============================================================

app = FastAPI(
    title="海棠文档工坊 API",
    description="文档图片清洁处理服务 - 支持批量上传和处理",
    version="3.4.00"
)

# ============================================================
# 全局异常处理器：捕获所有未处理异常，记录完整堆栈到日志
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback as _tb
    error_trace = _tb.format_exc()
    log_info(f"[全局异常] {request.method} {request.url.path}: {exc}")
    log_info(f"[全局异常] 详细堆栈:\n{error_trace}")
    # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
    # 返回给前端的 detail 带异常类型与排查指引（原实现只回"服务器内部错误"，用户无从下手；
    # 不暴露内部路径与堆栈细节）
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误（{type(exc).__name__}），完整原因已记录在服务日志，请联系管理员或查看服务窗口日志"}
    )

# xuechong 2026-06-01 CORS 配置 — 从环境变量或 url.conf 读取，支持远程访问
_allowed_origins_env = os.environ.get('DOCSTUDIO_CORS_ORIGINS', '')

# xuechong 2026-06-26 如果环境变量为空，尝试从 url.conf 读取
if not _allowed_origins_env:
    try:
        _url_conf_path = Path(__file__).parent.parent / 'url.conf'
        if _url_conf_path.exists():
            with open(_url_conf_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('DOCSTUDIO_CORS_ORIGINS='):
                        _allowed_origins_env = line.split('=', 1)[1].strip()
                        break
    except Exception:
        pass

if _allowed_origins_env:
    _allowed_origins = [o.strip() for o in _allowed_origins_env.split(',') if o.strip()]
else:
    _allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,  # xuechong 2026-06-01 支持 Authorization 头
    allow_methods=["*"],
    allow_headers=["*"],
)

# xuechong 2026-05-31 防浏览器缓存中间件：index.html 禁止缓存，确保新版本立即生效
@app.middleware("http")
async def _no_cache_html_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    # index.html 及其它 .html 文件禁止缓存，确保每次发布新版浏览器获取最新文件
    if path == "/" or path.endswith(".html") or path == "/index.html":
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    # 带哈希的静态资源（js/css/png）允许长期缓存，因为版本更新后文件名哈希会变
    elif any(path.endswith(ext) for ext in (".js", ".css", ".png", ".jpg", ".svg", ".woff2", ".ico")):
        # zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
        # 修复非法缓存值：3153.0.1 系 3.0.1 发版批量替换版本号误伤（原值 31536000=1年），
        # 非法 max-age 会被浏览器忽略导致长期缓存契约失效，此处恢复标准一年期缓存
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

# xuechong 2026-06-27 JWT 认证中间件（无 token 返回 401）
from backend.middleware.auth import AuthMiddleware
app.add_middleware(AuthMiddleware)

# ============================================================
# 目录配置（跨平台兼容）
# ============================================================

BASE_DIR = Path(__file__).parent

# 获取应用根目录
def _get_app_root():
    """获取应用根目录"""
    app_root = Path(__file__).parent.parent.resolve()
    if (app_root / "start_server.py").exists():
        return app_root
    return Path.cwd()

APP_ROOT = _get_app_root()

# 存储根目录配置（跨平台兼容）
def _get_storage_root():
    """获取存储根目录（从 url.conf 派生，config.py 已初始化）"""
    from . import config as _cfg
    path = Path(str(_cfg.DATA_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path

STORAGE_ROOT = _get_storage_root()

# 更新日志文件到持久化数据目录（与 start.sh 的 nohup 日志同目录）
_logs_dir = STORAGE_ROOT / "logs"
_logs_dir.mkdir(parents=True, exist_ok=True)
DEBUG_LOG_FILE = _logs_dir / "crabapple-docstudio.log"

# 全局可变状态
from backend.services.app_state import state

# 监控目录配置（跨平台兼容）
def _get_monitor_dirs():
    """获取监控目录"""
    base_dir = STORAGE_ROOT if STORAGE_ROOT.name == "data" else (STORAGE_ROOT / "data")
    source_dir = base_dir / "original"
    target_dir = base_dir / "target"
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    return source_dir, target_dir

state.MONITOR_SOURCE_DIR, state.MONITOR_TARGET_DIR = _get_monitor_dirs()

# 动态目录变量（在服务启动时根据 IP_端口 初始化）
state.UPLOAD_DIR: Path = None
state.OUTPUT_DIR: Path = None
state.TEMP_DIR: Path = None  # 临时目录根路径

# 服务地址配置（由 server.py / init_storage_dirs 设置）
state.SERVER_HOST = "127.0.0.1"
state.SERVER_PORT = "8000"

# ============================================================
# ============================================================
# WebSocket / 日志 / 目录监控 — 从 ws_service 导入
# ============================================================

from backend.services.ws_service import sync_log, dir_watcher

# 路由模块挂载

from backend.routes.auth import router as auth_router
app.include_router(auth_router)
from backend.routes.websocket import router as websocket_router
app.include_router(websocket_router)
from backend.routes.system import router as system_router
app.include_router(system_router)
from backend.routes.download_history import router as download_history_router
app.include_router(download_history_router)
from backend.routes.tasks import router as tasks_router
app.include_router(tasks_router)
from backend.routes.directory import router as directory_router
app.include_router(directory_router)
from backend.routes.upload import router as upload_router
app.include_router(upload_router)
from backend.routes.files import router as files_router
app.include_router(files_router)
from backend.routes.dual_layer import router as dual_layer_router
app.include_router(dual_layer_router)
from backend.routes.edit_pdf import router as edit_pdf_router
app.include_router(edit_pdf_router)


# ============================================================
# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局历史存储（init/load/save）已废弃，所有历史读写统一使用 user_scope.py 的 UserScope
# 仅保留 _update_upload_history（仍被 process_task 使用，通过 username 定位 scope）

# xuechong 2026-07-18 更新上传历史记录中的任务状态（用户隔离）
def _update_upload_history(task_id: str, status: str, message: str, completed_at: str, has_pdf: bool):
    """根据 task_id 查找并更新上传历史记录（从任务的 username 直接定位 scope）"""
    try:
        from backend.services.user_scope import get_user_scope, get_all_usernames
        # xuechong 2026-07-18 在所有用户 scope 中查找任务（任务可能在任意用户 scope 中）
        for username in get_all_usernames():
            scope = get_user_scope(username)
            task = scope.upload_tasks.get(task_id)
            if not task:
                continue
            # 找到任务，更新对应的历史记录
            for record in scope.upload_history:
                if record.get("task_id") == task_id:
                    record["status"] = status
                    record["last_message"] = message
                    record["completed_at"] = completed_at
                    record["has_pdf"] = has_pdf
                    scope.save_upload_history()
                    return
            # 任务存在但历史记录不存在（可能已被删除），直接返回
            return
        log_info(f"[上传历史] 未找到任务 {task_id}")
    except Exception as scope_err:
        log_info(f"[上传历史] 更新用户scope失败: {scope_err}")




# ============================================================
# 存储目录初始化
# ============================================================

# xuechong 2026-07-18 研发BUG-0009-图档扫描-用户隔离机制问题 数据迁移
def _migrate_to_user_dirs(user_mgr=None):
    """启动时自动迁移旧数据到 users/{username}/ 目录"""
    from backend.services.path_service import USERS_ROOT

    # 读取 user_id → username 映射
    user_map = {}  # {user_id: username}
    if user_mgr:
        for uname, udata in user_mgr._users.items():
            user_map[udata.get('user_id', '')] = uname

    migrated_count = 0

    # 1. 迁移 history/{user_id}/ → users/{username}/history/
    old_history_root = STORAGE_ROOT / "history"
    if old_history_root.exists():
        for user_dir in old_history_root.iterdir():
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name
            username = user_map.get(user_id, 'admin' if user_id == '_default_admin' else user_id)
            new_history_dir = USERS_ROOT / username / "history"
            new_history_dir.mkdir(parents=True, exist_ok=True)
            for json_file in user_dir.glob("*.json"):
                dst = new_history_dir / json_file.name
                if not dst.exists():
                    shutil.move(str(json_file), str(dst))
                    migrated_count += 1
            # 迁移后删除旧目录（如果为空）
            try:
                user_dir.rmdir()
            except OSError:
                pass

    # 2. 迁移 tmp/uploads/{user_id}/ → users/{username}/uploads/
    old_uploads_root = STORAGE_ROOT / "tmp" / "uploads"
    if old_uploads_root.exists():
        for user_dir in old_uploads_root.iterdir():
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name
            username = user_map.get(user_id, 'admin' if user_id == '_default_admin' else user_id)
            new_uploads_dir = USERS_ROOT / username / "uploads"
            new_uploads_dir.mkdir(parents=True, exist_ok=True)
            for task_dir in user_dir.iterdir():
                if task_dir.is_dir():
                    dst = new_uploads_dir / task_dir.name
                    if not dst.exists():
                        shutil.move(str(task_dir), str(dst))
                        migrated_count += 1

    # 3. 迁移 tmp/outputs/{user_id}/ → users/{username}/outputs/
    old_outputs_root = STORAGE_ROOT / "tmp" / "outputs"
    if old_outputs_root.exists():
        for user_dir in old_outputs_root.iterdir():
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name
            username = user_map.get(user_id, 'admin' if user_id == '_default_admin' else user_id)
            new_outputs_dir = USERS_ROOT / username / "outputs"
            new_outputs_dir.mkdir(parents=True, exist_ok=True)
            for task_dir in user_dir.iterdir():
                if task_dir.is_dir():
                    dst = new_outputs_dir / task_dir.name
                    if not dst.exists():
                        shutil.move(str(task_dir), str(dst))
                        migrated_count += 1

    # 4. 迁移全局历史文件到 admin 用户
    admin_history = USERS_ROOT / "admin" / "history"
    admin_history.mkdir(parents=True, exist_ok=True)
    for hist_name in ["download_history.json", "upload_history.json", "edit_pdf_history.json"]:
        old_file = STORAGE_ROOT / hist_name
        if old_file.exists():
            dst = admin_history / hist_name
            if not dst.exists():
                shutil.move(str(old_file), str(dst))
                migrated_count += 1

    # 5. 迁移双层PDF历史到 admin 用户
    old_dual_hist = STORAGE_ROOT / "dual_layer" / "dual_layer_history.json"
    if old_dual_hist.exists():
        dst = admin_history / "dual_layer_history.json"
        if not dst.exists():
            shutil.move(str(old_dual_hist), str(dst))
            migrated_count += 1

    if migrated_count > 0:
        log_info(f"[数据迁移] 已迁移 {migrated_count} 项数据到 users/ 目录")

    return migrated_count


def init_storage_dirs(host: str = None, port: str = None):
    """
    初始化存储目录
    统一使用 tmp 目录存储上传和输出文件
    """

    if host:
        state.SERVER_HOST = host
    if port:
        state.SERVER_PORT = str(port)

    # 统一使用 tmp 目录，不再按 IP_PORT 创建子目录
    tmp_dir = STORAGE_ROOT / "tmp"
    data_dir = STORAGE_ROOT / "data"
    logs_dir = STORAGE_ROOT / "logs"
    plugins_dir = STORAGE_ROOT / "plugins"

    state.UPLOAD_DIR = tmp_dir / "uploads"
    state.OUTPUT_DIR = tmp_dir / "outputs"
    state.TEMP_DIR = tmp_dir  # 临时目录根路径

    # 同步更新 path_service 模块变量（routes/*.py 可能从 path_service 导入）
    import backend.services.path_service as _ps
    _ps.UPLOAD_DIR = state.UPLOAD_DIR
    _ps.OUTPUT_DIR = state.OUTPUT_DIR
    _ps.TEMP_DIR = state.TEMP_DIR

    # 确保目录存在
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    state.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    state.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    log_info(f"  存储目录已初始化:")
    log_info(f"    根目录: {STORAGE_ROOT}")
    log_info(f"    临时目录: {tmp_dir}")
    log_info(f"    上传目录: {state.UPLOAD_DIR}")
    log_info(f"    输出目录: {state.OUTPUT_DIR}")

    # V3.1.01 xuechong 2026-07-25 JWT + 用户系统仅在正式启动时初始化一次
    # host 参数有值表示是 startup_event 调用，而非模块导入时的默认调用
    if host:
        # V3.1.01 xuechong 2026-07-25 初始化 JWT 认证服务（密钥持久化到文件，重启不失效）
        from backend.services.auth_service import init_jwt_service
        import secrets as _secrets_jwt
        jwt_secret = os.environ.get('DOCSTUDIO_JWT_SECRET')
        if not jwt_secret:
            _jwt_secret_file = STORAGE_ROOT / ".jwt_secret"
            try:
                if _jwt_secret_file.exists():
                    jwt_secret = _jwt_secret_file.read_text(encoding='utf-8').strip()
                    if jwt_secret:
                        log_info(f"[JWT] 从持久化文件加载密钥，重启后用户无需重新登录")
            except Exception as _e_jwt:
                log_info(f"[JWT] 读取密钥文件失败: {_e_jwt}")
            if not jwt_secret:
                jwt_secret = _secrets_jwt.token_hex(32)
                try:
                    _jwt_secret_file.write_text(jwt_secret, encoding='utf-8')
                    log_info(f"[JWT] 自动生成并持久化密钥，重启后用户无需重新登录")
                except Exception as _e_jwt:
                    log_info(f"[JWT] 自动生成随机密钥（未能持久化，重启后用户需重新登录）")
        # xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
        # token 有效期 24 小时改为 1 年（8760 小时）：内网系统内部人使用，登录一次一年内免登录，
        # 不再出现隔天回来登录态悄悄失效、上传时才集中爆发 401 的问题
        init_jwt_service(secret=jwt_secret, expire_hours=8760)

        # xuechong 2026-06-01 初始化用户系统并创建默认管理员
        from backend.models.user import UserManager
        user_mgr = UserManager(STORAGE_ROOT / "users.json")
        user_mgr.load()
        if user_mgr.is_first_run:
            from backend.routes.auth import _compute_password_hash
            # 优先使用部署方设置的口令；未设置时生成一次性随机口令
            default_pwd = os.environ.get("DOCSTUDIO_ADMIN_PASSWORD") or _secrets_jwt.token_urlsafe(12)
            user_mgr.create_user(
                username="admin",
                password=_compute_password_hash(default_pwd),
                display_name="管理员",
                role="admin"
            )
            log_info("=" * 60)
            log_info(f"  首次启动！已创建默认管理员账户：")
            log_info(f"    用户名: admin")
            log_info(f"    密码:   {default_pwd}")
            log_info(f"  请妥善保管此密码，登录后可在用户管理中修改")
            log_info("=" * 60)
            state._default_admin_password = default_pwd
        # 将 user_mgr 挂载到 state 供 auth 路由使用
        state._user_manager = user_mgr

        # xuechong 2026-07-18 迁移旧数据到 users/{username}/ 目录
        _migrate_to_user_dirs(user_mgr)

# 默认初始化（使用环境变量中的配置）
init_storage_dirs()

# ============================================================
# 全局变量
# ============================================================

# xuechong 2026-06-02 GPU 处理队列锁（防止多用户并发导致 GPU OOM）
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-015 Lock → BoundedSemaphore（可配置并发许可数）
# GPU_CONCURRENCY_PERMITS=1 等价于旧 Lock（完全互斥），生产实测后可调 2
import threading as _threading_gpu
from backend import config as _gpu_cfg
_gpu_permits = getattr(_gpu_cfg, 'GPU_CONCURRENCY_PERMITS', 1)
if _gpu_permits <= 1:
    _gpu_queue_lock = _threading_gpu.Lock()
else:
    _gpu_queue_lock = _threading_gpu.BoundedSemaphore(_gpu_permits)

# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# state.tasks_status / state.tasks_cancel_flags 已废弃，统一使用 scope.* 版本

# 专用线程池（限制并发，防止线程爆炸）
_dual_layer_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dual-layer")

# 清洁器实例（延迟初始化）
state._cleaner = None
state._cleaner_class = None

# 模型预热标志
state._models_warmed_up = False

def warmup_models():
    """
    模型预热 - 在服务启动时预加载所有耗时模型和引擎
    
    ★ 所有耗时步骤都必须在启动时完成 ★
    避免首次请求时用户等待，每个步骤都有详细日志。
    
    预热步骤：
    [1/4] YOLO 布局检测模型（PyTorch GPU/CPU）
    [2/4] OCR 方向检测引擎（RapidOCR, det_limit=640）
    [3/4] OCR 文字保护引擎（RapidOCR, det_limit=960）
    [4/4] 双层PDF OCR 引擎（RapidOCR, det_limit=默认）
    """
    if state._models_warmed_up:
        return
    
    import time
    total_start = time.time()
    
    log_info("=" * 60)
    log_info("[系统启动] 开始预热所有模型和引擎...")
    log_info("[系统启动] （首次启动可能需要数分钟，请耐心等待）")
    log_info("=" * 60)
    
    # ============================================================
    # [1/4] YOLO 布局检测模型
    # ============================================================
    step_start = time.time()
    log_info("")
    log_info("[启动 1/4] 加载 YOLO 布局检测模型...")
    try:
        if state._cleaner_class is None:
            state._cleaner_class = get_cleaner_class()
        if state._cleaner is None:
            state._cleaner = state._cleaner_class()
        device_info = getattr(state._cleaner, 'device', 'unknown')
        step_elapsed = time.time() - step_start
        if device_info and 'cuda' in str(device_info):
            log_info(f"[启动 1/4] ✓ YOLO 模型就绪，设备: {device_info} (GPU加速)，耗时 {step_elapsed:.1f}s")
        else:
            log_info(f"[启动 1/4] ✓ YOLO 模型就绪，设备: {device_info} (CPU模式)，耗时 {step_elapsed:.1f}s")
    except Exception as e:
        step_elapsed = time.time() - step_start
        log_info(f"[启动 1/4] ✗ YOLO 模型加载失败: {e}，耗时 {step_elapsed:.1f}s")
    
    # ============================================================
    # [2/4] OCR 方向检测引擎（cleaner.py 中使用，det_limit=640）
    # ============================================================
    step_start = time.time()
    log_info("")
    log_info("[启动 2/4] 预热 OCR 方向检测引擎 (det_limit=640)...")
    log_info("[启动 2/4] （首次 CUDA JIT 编译可能需要 1-3 分钟，编译结果会缓存到磁盘）")
    try:
        cleaner_module = sys.modules.get('backend.cleaner')
        if cleaner_module and hasattr(cleaner_module, '_get_cached_ocr_engine'):
            cleaner_module._get_cached_ocr_engine(640)
            step_elapsed = time.time() - step_start
            log_info(f"[启动 2/4] ✓ OCR 方向检测引擎就绪，耗时 {step_elapsed:.1f}s")
        else:
            log_info(f"[启动 2/4] ⚠ cleaner 模块未加载，跳过")
    except Exception as e:
        step_elapsed = time.time() - step_start
        log_info(f"[启动 2/4] ✗ OCR 方向检测引擎预热失败: {e}，耗时 {step_elapsed:.1f}s")
    
    # ============================================================
    # [3/4] OCR 文字保护引擎（cleaner.py 中使用，det_limit=960）
    # ============================================================
    step_start = time.time()
    log_info("")
    log_info("[启动 3/4] 预热 OCR 文字保护引擎 (det_limit=960)...")
    try:
        cleaner_module = sys.modules.get('backend.cleaner')
        if cleaner_module and hasattr(cleaner_module, '_get_cached_ocr_engine'):
            cleaner_module._get_cached_ocr_engine(960)
            step_elapsed = time.time() - step_start
            log_info(f"[启动 3/4] ✓ OCR 文字保护引擎就绪，耗时 {step_elapsed:.1f}s")
        else:
            log_info(f"[启动 3/4] ⚠ cleaner 模块未加载，跳过")
    except Exception as e:
        step_elapsed = time.time() - step_start
        log_info(f"[启动 3/4] ✗ OCR 文字保护引擎预热失败: {e}，耗时 {step_elapsed:.1f}s")
    
    # ============================================================
    # [4/4] 双层PDF OCR 引擎（ocr_rapid.py 中使用）
    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-005/011 统一 det_limit=960
    # ============================================================
    step_start = time.time()
    log_info("")
    log_info("[启动 4/4] 预热双层PDF OCR 引擎 (det_limit=960)...")
    try:
        from .ocr_rapid import get_rapid_ocr_engine
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-005/011 统一预热 det960，消除多引擎并存
        get_rapid_ocr_engine("ch", use_cls=False, det_limit=960)
        step_elapsed = time.time() - step_start
        log_info(f"[启动 4/4] ✓ 双层PDF OCR 引擎就绪 (det960)，耗时 {step_elapsed:.1f}s")
    except Exception as e:
        step_elapsed = time.time() - step_start
        log_info(f"[启动 4/4] ✗ 双层PDF OCR 引擎预热失败: {e}，耗时 {step_elapsed:.1f}s")
    
    # ============================================================
    # 预热完成
    # ============================================================
    state._models_warmed_up = True
    total_elapsed = time.time() - total_start
    log_info("")
    log_info("=" * 60)
    log_info(f"[系统启动] ✓ 所有模型预热完成，总耗时 {total_elapsed:.1f}s")
    log_info(f"[系统启动] ✓ 系统已就绪，可以接受请求")
    log_info("=" * 60)
    log_info("")


def log_startup_summary():
    """服务启动汇总：一次性输出 CPU/GPU 运行模式总览

    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化
    用途：warmup_models 各步骤日志分散（YOLO、OCR、方向检测等），运维无法一眼
    确认哪些功能走 GPU、哪些走 CPU。此函数在模型预热完成后调用，仅读取已初始化
    状态与轻量检测结果，不加载任何模型、不阻塞启动。
    """
    from datetime import datetime as _dt
    try:
        from backend import __version__ as _ver
    except Exception:
        _ver = "unknown"
    from backend import config as _cfg

    _divider = "=" * 66
    log_info(_divider)
    log_info(f" [启动汇总] 系统运行模式总览 v{_ver}  {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_info("-" * 66)

    # ---- 基础能力：PyTorch CUDA ----
    torch_ok = False
    torch_line = "未安装/不可用"
    try:
        import torch
        torch_ok = bool(torch.cuda.is_available())
        torch_line = f"torch {torch.__version__} (CUDA {torch.version.cuda or '无'})"
        if torch_ok:
            _gpu_name = torch.cuda.get_device_name(0)
            _total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            try:
                _free_gb, _ = torch.cuda.mem_get_info(0)
                torch_line += f" | {_gpu_name} ({_total_gb:.1f}GB, 空闲{_free_gb / 1024 ** 3:.1f}GB)"
            except Exception:
                torch_line += f" | {_gpu_name} ({_total_gb:.1f}GB)"
    except Exception as _e:
        torch_line += f" | 检测异常: {_e}"
    log_info(f" [GPU] PyTorch CUDA   : {'可用' if torch_ok else '不可用'} | {torch_line}")

    # ---- 基础能力：onnxruntime ----
    ort_gpu = False
    ort_line = "未安装/不可用"
    try:
        import onnxruntime as _ort
        _device = _ort.get_device()
        _providers = _ort.get_available_providers()
        ort_gpu = (_device == "GPU") and ("CUDAExecutionProvider" in _providers)
        ort_line = f"{_ort.__version__} | device={_device} | providers={_providers}"
    except Exception as _e:
        ort_line += f" | 检测异常: {_e}"
    log_info(f" [GPU] onnxruntime    : {'GPU 版' if ort_gpu else 'CPU 版'} | {ort_line}")

    # ---- 各功能设备归属 ----
    yolo_dev = getattr(state._cleaner, 'device', None) if state._cleaner is not None else None
    if yolo_dev:
        _tag = "GPU" if "cuda" in str(yolo_dev).lower() else "CPU"
        log_info(f" [{_tag}] YOLO 布局检测  : {yolo_dev}（保护区域/低置信区域检测）")
    else:
        log_info(" [FAIL] YOLO 布局检测  : 未加载（预热失败或未初始化）")

    ocr_gpu = False
    try:
        from .ocr_rapid import detect_ort_gpu
        ocr_gpu = detect_ort_gpu()
    except Exception:
        ocr_gpu = ort_gpu
    _ocr_tag = "GPU" if ocr_gpu else "CPU"
    log_info(f" [{_ocr_tag}] RapidOCR 推理  : {_ocr_tag}（方向检测/文字保护/双层PDF 共用引擎）")

    # ---- 已加载 OCR 引擎明细（det_limit 实际值） ----
    _eng_parts = []
    try:
        from backend.cleaner.ocr_engine import _orientation_ocr_cache as _ort_cache
        for _k in sorted(_ort_cache.keys()):
            _eng_parts.append(f"cleaner_{_k}")
    except Exception:
        pass
    try:
        from backend.ocr_rapid import _rapid_ocr_engines as _rapid_cache
        for _k in sorted(_rapid_cache.keys()):
            _eng_parts.append(f"ocr_{_k}")
    except Exception:
        pass
    if _eng_parts:
        log_info(f" [配置] 已加载OCR引擎  : {', '.join(_eng_parts)}")

    # ---- CPU 功能 ----
    log_info(" [CPU] 图像清洁算法  : 背景白化/去噪/钉孔/印章/灰色保护（OpenCV+numpy）")
    log_info(" [CPU] PDF 生成文字层: PyMuPDF（TextWriter 透明文字层）")
    log_info(" [CPU] 图像编解码/DPI: OpenCV + PIL")

    # ---- 并行模式 ----
    _cpu_count = os.cpu_count() or 4
    if ocr_gpu:
        log_info(" [并行] OCR 推理线程  : 1（GPU 串行，onnxruntime CUDA EP 不支持并发推理）")
    else:
        log_info(f" [并行] OCR 推理线程  : min(CPU核数={_cpu_count}, 8)={min(_cpu_count, 8)}（CPU 多线程）")
    _gpu_permits = getattr(_cfg, 'GPU_CONCURRENCY_PERMITS', 1)
    if _gpu_permits <= 1:
        log_info(" [并行] GPU 队列锁    : 全局互斥锁（多用户 GPU 操作串行）")
    else:
        log_info(f" [并行] GPU 并发许可  : {_gpu_permits}（Semaphore，允许多任务同时使用 GPU）")

    # ---- 预解码缓存 ----
    _predecode = getattr(_cfg, 'UPLOAD_PREDECODE_CACHE_ENABLED', False)
    if _predecode:
        _pd_max = getattr(_cfg, 'UPLOAD_PREDECODE_CACHE_MAX', 50)
        log_info(f" [缓存] 预解码缓存    : 开启（最大 {_pd_max} 张，LRU 淘汰）")
    else:
        log_info(" [缓存] 预解码缓存    : 关闭")

    # ---- 关键配置 ----
    _det = getattr(_cfg, 'OCR_DET_LIMIT_SIDE_LEN', 1280)
    log_info(f" [配置] det_limit     : 方向640 / 文字保护960 / 双层PDF默认{_det}（REQ-011 将统一 960）")
    log_info(f" [配置] 灰度内容保护  : {'开启' if getattr(_cfg, 'ENABLE_GRAY_CONTENT_PROTECTION', True) else '关闭'}（190-245 候选范围 + 规则判定）")
    log_info(f" [配置] CUDA JIT 缓存 : {_cfg.CUDA_CACHE_DIR}")

    log_info(_divider)


def get_cleaner_class():
    """获取 DocumentCleaner 类（延迟加载，避免启动时加载 YOLO）"""
    if state._cleaner_class is None:
        from backend.cleaner import DocumentCleaner
        state._cleaner_class = DocumentCleaner
        log_info("DocumentCleaner 类加载成功")
    return state._cleaner_class

def get_cleaner():
    """获取或初始化清洁器实例"""
    if state._cleaner is None:
        log_info("正在加载 YOLO 模型...")
        CleanerClass = get_cleaner_class()
        state._cleaner = CleanerClass()
        log_info("YOLO 模型加载完成")
    return state._cleaner



# ============================================================
# 性能优化配置
# ============================================================

# 统一的图片宽度（确保所有页面尺寸一致）

def get_system_font_path() -> str:
    """获取系统中可用的中文字体路径"""
    import platform
    
    # 优先字体列表（按优先级排序）
    if platform.system() == "Windows":
        font_candidates = [
            "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
            "C:/Windows/Fonts/msyhbd.ttc",    # 微软雅黑粗体
            "C:/Windows/Fonts/simsun.ttc",    # 宋体
            "C:/Windows/Fonts/simhei.ttf",    # 黑体
            "C:/Windows/Fonts/simkai.ttf",    # 楷体
        ]
    else:
        # Linux/Mac 字体路径
        font_candidates = [
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/PingFang.ttc",
        ]
    
    for font_path in font_candidates:
        if os.path.exists(font_path):
            return font_path
    
    return None


def image_to_searchable_pdf(image: np.ndarray, output_pdf_path: Path, jpeg_quality: int = None, target_size_kb: int = None, dpi: int = None) -> bool:
    """
    将图片转换为双层可搜索PDF（性能优化版）
    
    Args:
        image: 图像数据
        output_pdf_path: 输出PDF路径
        jpeg_quality: JPEG压缩质量
        target_size_kb: 目标文件大小
        dpi: 图像DPI，用于计算正确的PDF页面尺寸。如果为None，默认使用300 DPI
    """
    try:
        if image is None:
            return False
        
        # 图片尺寸
        img_height, img_width = image.shape[:2]
        
        # 使用传入的DPI或默认300 DPI
        if dpi is None or dpi <= 0:
            dpi = 300
        
        # 计算PDF页面尺寸（单位：点，72点=1英寸）
        # 物理尺寸 = 像素数 / DPI（英寸）
        # PDF点数 = 物理尺寸 * 72
        pdf_width = img_width * 72.0 / dpi
        pdf_height = img_height * 72.0 / dpi
        
        log_info(f"  [PDF] 图片: {img_width}x{img_height} 像素, DPI: {dpi}")
        log_info(f"  [PDF] 页面尺寸: {pdf_width:.1f}x{pdf_height:.1f} 点 ({pdf_width/72:.2f}x{pdf_height/72:.2f} 英寸)")
        
        # OCR — 使用 RapidOCR（GPU/CPU 自适应）
        from .ocr_rapid import get_rapid_ocr_engine, ocr_image_with_rapid
        ocr_engine_info = get_rapid_ocr_engine("ch", use_cls=False)
        ocr_data = ocr_image_with_rapid(image, ocr_engine_info)
        log_info(f"  [PDF] OCR: {len(ocr_data)} 个文字块 (RapidOCR)")
        
        # 转 JPEG（压缩）
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(image_rgb)
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        
        # 计算 JPEG 质量
        # 修复：从高质量开始测试，避免对已压缩图片进行过度压缩
        if jpeg_quality is None:
            if target_size_kb and target_size_kb > 0:
                # 先测试高质量，如果满足目标大小就使用高质量
                for q in [95, 90, 85, 80, 75, 70, 60, 50, 40, 30]:
                    buf = io.BytesIO()
                    pil_image.save(buf, format='JPEG', quality=q)
                    if len(buf.getvalue()) / 1024 <= target_size_kb * 1.1:
                        jpeg_quality = q
                        break
                else:
                    jpeg_quality = 30
            else:
                jpeg_quality = 85  # 默认使用较高质量
        
        # 保存 JPEG 到内存（保留DPI信息）
        jpeg_buf = io.BytesIO()
        pil_image.save(jpeg_buf, format='JPEG', quality=jpeg_quality, dpi=(dpi, dpi))
        jpeg_data = jpeg_buf.getvalue()
        log_info(f"  [PDF] JPEG: {len(jpeg_data)/1024:.0f}KB (质量{jpeg_quality}, DPI保留: {dpi})")
        log_info(f"  [PDF] 图像像素: {img_width}x{img_height} (原始尺寸保持不变)")
        
        # 创建 PDF
        doc = fitz.open()
        page = doc.new_page(width=pdf_width, height=pdf_height)

        # 插入图片
        page.insert_image(page.rect, stream=jpeg_data)
        
        # 添加透明文字层（不可见但可选中/搜索）
        # 使用 render_mode=3 创建真正透明的文字
        text_count = 0
        
        # 【重要】OCR坐标是像素坐标，需要转换为PDF点坐标
        # 转换公式：pdf坐标 = 像素坐标 * 72 / DPI
        scale_factor = 72.0 / dpi
        
        for item in ocr_data:
            bbox = item.get('box', [])
            text = item.get('text', '')
            # 修复：parse_rapid_ocr_result 返回的置信度键名为 'confidence'（兼容 'score'）
            conf = item.get('confidence', item.get('score', 0.0))

            if conf < 0.3 or not text or not text.strip():
                continue
            
            try:
                bbox_arr = np.array(bbox, dtype=np.float32)
                if bbox_arr.ndim != 2 or bbox_arr.shape[0] < 4:
                    continue
                xs = bbox_arr[:, 0]
                ys = bbox_arr[:, 1]
                
                # 将像素坐标转换为PDF点坐标
                x_min = float(min(xs)) * scale_factor
                x_max = float(max(xs)) * scale_factor
                y_min = float(min(ys)) * scale_factor
                y_max = float(max(ys)) * scale_factor
                box_h = y_max - y_min
                box_w = x_max - x_min
                
                if box_w <= 0 or box_h <= 0:
                    continue
                
                # ===== 智能计算字体大小 =====
                # 根据边界框宽度和文字内容反推合适的字体大小
                chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
                other_count = len(text) - chinese_count
                
                # 中文字符宽度≈字体大小，英文/数字宽度≈字体大小*0.55
                # 估算: box_w = chinese_count * font_size + other_count * font_size * 0.55
                char_width_factor = chinese_count + other_count * 0.55
                if char_width_factor > 0:
                    font_size_by_width = box_w / char_width_factor
                else:
                    font_size_by_width = box_h * 0.8
                
                # 同时考虑高度约束（字体不能超过边界框高度的80%）
                font_size_by_height = box_h * 0.8
                
                # 取两者中较小的值，确保文字不会溢出
                font_size = min(font_size_by_width, font_size_by_height)
                font_size = max(font_size, 4)  # 最小4pt
                font_size = min(font_size, 72)  # 最大72pt
                
                # ===== 使用 insert_textbox 添加文字层（已验证对齐最准确）=====
                # 创建矩形框，使用 OCR 返回的边界框坐标
                rect = fitz.Rect(x_min, y_min, x_max, y_max)
                
                # insert_textbox 会自动在矩形框内放置文字
                # 使用白色文字 (1,1,1) 隐藏但可选中
                try:
                    # 尝试多个字体大小，确保文字能放入框内
                    for scale in [0.85, 0.7, 0.6, 0.5, 0.4]:
                        try_font_size = min(font_size, box_h * scale)
                        try_font_size = max(try_font_size, 4)
                        
                        rc = page.insert_textbox(
                            rect,
                            text,
                            fontname="china-s",
                            fontsize=try_font_size,
                            color=(1, 1, 1),  # 白色文字，隐藏但可选中
                            align=0  # 左对齐
                        )
                        if rc >= 0:  # 成功
                            text_count += 1
                            break
                    else:
                        # 所有字体都失败，用最小字体强制插入
                        page.insert_textbox(rect, text, fontname="china-s", fontsize=6, 
                                           color=(1, 1, 1), align=0)
                        text_count += 1
                except Exception as e:
                    import traceback
                    log_info(f"[PDF文字层] 插入文字框失败: {e}")
                    log_info(f"[PDF文字层] 详细堆栈:\n{traceback.format_exc()}")

            except Exception as e:
                import traceback
                log_info(f"[PDF文字层] 处理OCR文字坐标失败: {e}")
                log_info(f"[PDF文字层] 详细堆栈:\n{traceback.format_exc()}")
        
        log_info(f"  [PDF] 透明文字层: {text_count} 个")

        # zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题
        # 保存前子集化OCR文字层字库并回收全量字库流，避免单页PDF内嵌整份CJK字库导致体积翻倍
        from backend.services.pdf_font_service import save_pdf_with_font_subset
        save_pdf_with_font_subset(doc, output_pdf_path)
        doc.close()

        final_kb = output_pdf_path.stat().st_size / 1024
        log_info(f"  [PDF] 完成: {final_kb:.0f}KB")

        return True
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"  [PDF] 失败: {e}")
        try:
            doc.close()
        except Exception:
            pass
        return False


def _parse_rational(value) -> float:
    """
    解析TIFF中的Rational值（可能是IFDRational对象、元组或数值）
    
    Returns:
        float: 解析后的数值，如果解析失败返回0
    """
    try:
        # IFDRational 对象（PIL/Pillow）
        if hasattr(value, 'numerator') and hasattr(value, 'denominator'):
            if value.denominator and value.denominator != 0:
                return float(value.numerator) / float(value.denominator)
            return float(value.numerator)
        
        # 元组形式 (numerator, denominator)
        if isinstance(value, tuple):
            if len(value) >= 2 and value[1] and value[1] != 0:
                return float(value[0]) / float(value[1])
            elif len(value) >= 1:
                return float(value[0])
        
        # 直接数值
        return float(value)
    except Exception as e:
        log_info(f"[DPI解析] Rational值解析失败: {e}")
        return 0


def get_image_dpi(image_path: Path, image_bytes: bytes = None) -> int:
    """
    获取图像的DPI信息（支持TIF/TIFF/JPEG/PNG等格式）

    Args:
        image_path: 图像文件路径
        image_bytes: 可选，已读取的图像字节（避免重复打开文件，REQ-002）
    
    Returns:
        int: 图像DPI，如果无法获取则返回300（默认值）
    """
    DEFAULT_DPI = 300
    MIN_DPI = 72
    MAX_DPI = 1200
    
    try:
        if image_bytes is not None:
            pil_image = Image.open(io.BytesIO(image_bytes))
        else:
            pil_image = Image.open(str(image_path))
        
        # 方法1: 检查 'dpi' 字段（常见于 JPEG/PNG）
        dpi_info = pil_image.info.get('dpi')
        if dpi_info:
            if isinstance(dpi_info, tuple) and len(dpi_info) >= 1:
                dpi = _parse_rational(dpi_info[0])
            else:
                dpi = _parse_rational(dpi_info)
            
            if MIN_DPI <= dpi <= MAX_DPI:
                log_info(f"  [DPI] 从'dpi'字段读取: {int(dpi)}")
                return int(dpi)
            elif dpi > 0:
                log_info(f"  [DPI] 'dpi'字段值 {dpi} 超出合理范围({MIN_DPI}-{MAX_DPI})，使用默认值")
        
        # 方法2: 检查 TIFF 特定标签（XResolution=282, YResolution=283）
        if hasattr(pil_image, 'tag_v2'):
            # ResolutionUnit: 1=无单位, 2=英寸(DPI), 3=厘米(DPCM)
            resolution_unit = pil_image.tag_v2.get(296, 2)  # 默认英寸
            x_resolution = pil_image.tag_v2.get(282)  # XResolution
            
            if x_resolution is not None:
                dpi = _parse_rational(x_resolution)
                
                # 调试输出原始值
                log_info(f"  [DPI] TIFF标签: XResolution={x_resolution}, 解析值={dpi}, ResolutionUnit={resolution_unit}")
                
                # 如果单位是厘米(DPCM)，转换为DPI
                if resolution_unit == 3 and dpi > 0:
                    dpi = dpi * 2.54
                    log_info(f"  [DPI] 从DPCM转换为DPI: {int(dpi)}")
                
                # 验证DPI范围
                if MIN_DPI <= dpi <= MAX_DPI:
                    log_info(f"  [DPI] 从TIFF tag_v2读取: {int(dpi)}")
                    return int(dpi)
                elif dpi > 0:
                    log_info(f"  [DPI] TIFF标签值 {dpi} 超出合理范围({MIN_DPI}-{MAX_DPI})，使用默认值")
        
        # 方法3: 检查旧版 TIFF 标签（tag字典）
        if hasattr(pil_image, 'tag'):
            x_res = pil_image.tag.get(282)
            resolution_unit = 2  # 默认英寸
            unit_tag = pil_image.tag.get(296)
            if unit_tag and isinstance(unit_tag, tuple) and len(unit_tag) > 0:
                resolution_unit = unit_tag[0]
            
            if x_res:
                if isinstance(x_res, tuple) and len(x_res) > 0:
                    dpi = _parse_rational(x_res[0])
                else:
                    dpi = _parse_rational(x_res)
                
                # 调试输出
                log_info(f"  [DPI] TIFF旧标签: XResolution={x_res}, 解析值={dpi}, ResolutionUnit={resolution_unit}")
                
                # 如果单位是厘米，转换为DPI
                if resolution_unit == 3 and dpi > 0:
                    dpi = dpi * 2.54
                
                if MIN_DPI <= dpi <= MAX_DPI:
                    log_info(f"  [DPI] 从TIFF tag读取: {int(dpi)}")
                    return int(dpi)
                elif dpi > 0:
                    log_info(f"  [DPI] TIFF旧标签值 {dpi} 超出合理范围({MIN_DPI}-{MAX_DPI})，使用默认值")
        
    except Exception as e:
        log_info(f"  [DPI] 读取失败: {e}")
        import traceback
        traceback.print_exc()
    
    log_info(f"  [DPI] 无法读取有效DPI，使用默认值: {DEFAULT_DPI}")
    return DEFAULT_DPI


def save_image_with_dpi(image: np.ndarray, output_path: Path, dpi: int = 300, 
                        quality: int = 95, target_size: int = None) -> bool:
    """
    保存图片并保留DPI信息
    
    Args:
        image: OpenCV格式的图像 (BGR)
        output_path: 输出文件路径
        dpi: DPI值
        quality: JPEG/WEBP质量 (1-100)
        target_size: 目标文件大小（字节），如果指定则动态调整质量
    
    Returns:
        bool: 是否成功
    """
    try:
        # 转换为RGB（PIL使用RGB）
        if len(image.shape) == 3 and image.shape[2] == 3:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = image
        
        pil_image = Image.fromarray(image_rgb)
        suffix = output_path.suffix.lower()
        
        if suffix in {'.tif', '.tiff'}:
            # TIF格式：保留DPI，使用LZW压缩
            pil_image.save(str(output_path), format='TIFF', compression='tiff_lzw', dpi=(dpi, dpi))
        
        elif suffix in {'.jpg', '.jpeg'}:
            # JPEG格式：保留DPI，动态调整质量
            if target_size and target_size > 0:
                # 动态调整质量以匹配目标大小
                for q in [quality, 85, 75, 65, 55, 45, 35]:
                    buf = io.BytesIO()
                    pil_image.save(buf, format='JPEG', quality=q, dpi=(dpi, dpi))
                    if len(buf.getvalue()) <= target_size * 1.1:  # 允许10%误差
                        quality = q
                        break
            
            pil_image.save(str(output_path), format='JPEG', quality=quality, dpi=(dpi, dpi))
        
        elif suffix == '.png':
            # PNG格式：保留DPI
            pil_image.save(str(output_path), format='PNG', dpi=(dpi, dpi))
        
        elif suffix == '.webp':
            # WEBP格式：保留DPI，动态调整质量
            if target_size and target_size > 0:
                for q in [quality, 85, 75, 65, 55, 45, 35]:
                    buf = io.BytesIO()
                    pil_image.save(buf, format='WEBP', quality=q)
                    if len(buf.getvalue()) <= target_size * 1.1:
                        quality = q
                        break
            
            pil_image.save(str(output_path), format='WEBP', quality=quality)
        
        elif suffix == '.bmp':
            # BMP格式
            pil_image.save(str(output_path), format='BMP', dpi=(dpi, dpi))
        
        else:
            # 其他格式：尝试保存
            pil_image.save(str(output_path), dpi=(dpi, dpi))
        
        return True
    
    except Exception as e:
        log_info(f"[save_image_with_dpi] 保存失败: {e}")
        return False


def create_searchable_pdf(image_path: Path, output_pdf_path: Path) -> bool:
    """
    从图片文件创建可搜索PDF（包装函数）
    """
    try:
        # 获取原文件大小（KB）
        original_size_kb = image_path.stat().st_size / 1024
        file_ext = image_path.suffix.lower()
        
        sync_log("INFO", f"[PDF转换] 开始处理图片: {image_path.name}")
        sync_log("INFO", f"[PDF转换] 原文件大小: {original_size_kb:.0f}KB, 格式: {file_ext}")
        
        # 获取图像DPI
        image_dpi = get_image_dpi(image_path)
        sync_log("INFO", f"[PDF转换] 图像DPI: {image_dpi}")
        
        # 读取图片（支持中文路径）
        image = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            sync_log("ERROR", f"[PDF转换] 无法读取图片: {image_path}")
            return False
        
        # 根据原文件格式和内部压缩方式决定目标大小
        # 关键修复：检测TIF文件内部是否已经使用有损压缩（如JPEG）
        tif_already_compressed = False
        if file_ext in ['.tif', '.tiff']:
            # 检测TIF内部的压缩方式
            try:
                from PIL import Image as PILImage
                with PILImage.open(str(image_path)) as pil_img:
                    if pil_img.format == "TIFF" and hasattr(pil_img, 'tag_v2'):
                        compression = pil_img.tag_v2.get(259, 1)  # 259 = Compression tag
                        # 压缩类型：6=JPEG旧版, 7=JPEG新版, 34712=JPEG2000
                        if compression in [6, 7, 34712]:
                            tif_already_compressed = True
                            sync_log("INFO", f"[PDF转换] TIF文件内部已使用JPEG压缩")
                        else:
                            compression_names = {1: "无压缩", 2: "CCITT", 3: "CCITT T.4", 
                                                4: "CCITT T.6", 5: "LZW", 8: "Deflate/ZIP", 
                                                32773: "PackBits"}
                            comp_name = compression_names.get(compression, f"未知({compression})")
                            sync_log("INFO", f"[PDF转换] TIF文件内部压缩方式: {comp_name}")
            except Exception as e:
                sync_log("WARNING", f"[PDF转换] 无法检测TIF压缩方式: {e}")
        
        # 根据文件类型和压缩状态决定目标大小
        if file_ext in ['.tif', '.tiff', '.bmp']:
            if tif_already_compressed:
                # TIF内部已经是JPEG压缩：保持相近大小，避免二次压缩导致质量损失
                target_size_kb = original_size_kb * 1.0
                sync_log("INFO", f"[PDF转换] TIF已JPEG压缩: {original_size_kb:.0f}KB -> 目标: 保持原大小")
            else:
                # 真正的无损格式：可以适度压缩，但不要太激进（从15%改为50%）
                img_height, img_width = image.shape[:2]
                target_size_kb = original_size_kb * 0.50
                # 设置合理的最小值，确保基本质量
                min_size_kb = (img_width * img_height) / 1024 / 10  # 每像素约 0.1KB
                target_size_kb = max(target_size_kb, min_size_kb, 200)
                sync_log("INFO", f"[PDF转换] 无损格式压缩: {original_size_kb:.0f}KB -> 目标: {target_size_kb:.0f}KB")
        elif file_ext in ['.png']:
            # PNG：目标大小设为原文件的 70%
            target_size_kb = original_size_kb * 0.7
            target_size_kb = max(target_size_kb, 100)
            sync_log("INFO", f"[PDF转换] PNG格式压缩: {original_size_kb:.0f}KB -> 目标: {target_size_kb:.0f}KB")
        else:
            # JPEG 等已压缩格式：保持相近大小
            target_size_kb = original_size_kb * 1.0
            sync_log("INFO", f"[PDF转换] 已压缩格式: {original_size_kb:.0f}KB -> 目标: {target_size_kb:.0f}KB")
        
        # 调用核心转换函数（传入DPI）
        sync_log("INFO", f"[PDF转换] 开始PDF生成流程...")
        result = image_to_searchable_pdf(image, output_pdf_path, target_size_kb=target_size_kb, dpi=image_dpi)
        
        if result:
            final_size_kb = output_pdf_path.stat().st_size / 1024
            sync_log("SUCCESS", f"[PDF转换] 完成! 输出PDF大小: {final_size_kb:.0f}KB")
        else:
            sync_log("ERROR", f"[PDF转换] PDF生成失败")
            
        return result
        
    except Exception as e:
        sync_log("ERROR", f"[PDF转换] 创建PDF失败: {e}")
        return False




def merge_pdfs_to_single(pdf_paths: List[Path], output_path: Path, add_page_number: bool = True) -> bool:
    """
    合并多个 PDF 为一个，保留双层PDF的文字层
    
    注意：传入的 pdf_paths 应该已经按正确顺序排列，本函数不会重新排序
    使用 insert_pdf 方法直接合并，确保保留文字层
    
    Args:
        pdf_paths: PDF 文件路径列表（已排序）
        output_path: 输出 PDF 路径
        add_page_number: 是否添加页码
        
    Returns:
        bool: 是否成功
    """
    try:
        log_info(f"  [PDF合并] 开始合并 {len(pdf_paths)} 个PDF文件（严格按传入顺序，保留文字层）")
        for i, p in enumerate(pdf_paths):
            log_info(f"    {i+1}. {p.name}")
        
        # 创建合并后的PDF
        merged_pdf = fitz.open()
        total_pages = 0
        
        # 直接使用 insert_pdf 合并，保留文字层
        for pdf_path in pdf_paths:
            if pdf_path.exists():
                src_doc = fitz.open(str(pdf_path))
                merged_pdf.insert_pdf(src_doc)
                total_pages += len(src_doc)
                src_doc.close()
        
        log_info(f"  [PDF合并] 合并完成，共 {total_pages} 页（已保留文字层）")
        
        # 根据参数决定是否添加页码
        if add_page_number:
            add_page_numbers(merged_pdf)
            log_info(f"  [PDF合并] 成功保存: {output_path.name}（{total_pages}页，已添加页码）")
        else:
            log_info(f"  [PDF合并] 成功保存: {output_path.name}（{total_pages}页，不含页码）")

        # zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题
        # 合并保存前先子集化字库并回收垃圾对象，消除insert_pdf合并导致的每页一份全量CJK字库
        from backend.services.pdf_font_service import save_pdf_with_font_subset
        save_pdf_with_font_subset(merged_pdf, output_path)
        merged_pdf.close()

        return True

    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"  [PDF合并] 失败: {e}")
        return False


# xuechong 2026-08-27 研发需求-0138-图档扫描-3.2.00-PDF添加页码 页码宋体子集字体（Noto Serif SC，
# SIL OFL 1.1 开源许可证可随包分发，见同目录 OFL-License.txt；仅含数字/短横线/空格/预留字符，10.8KB）
# 源字体与子集化命令备份：工作目录 研发需求-0138-图档扫描-3.2.00-PDF添加页码\研发需求-0138-字体源-NotoSerifSC-Regular.ttf
_PAGENUM_FONT_PATH = Path(__file__).parent / "fonts" / "noto-serif-sc-pagenum-subset.ttf"
# xuechong 2026-08-27 研发需求-0138-图档扫描-3.2.00-PDF添加页码 字体对象模块级缓存（仅加载一次；None=未加载）
_PAGENUM_FONT_CACHE = None

# zhaoqiaotong 2026-09-02 研发BUG-0041-图档扫描-3.2.04-修复PDF页码遮挡正文内容的问题 页码腾位常量：
# 底部预留页码带高度pt（白底衬上沿 h-34.84 + 检测外扩2pt + 安全余量约3pt，
# 避免腾位后内容紧贴白底衬）；页码区域非白像素占比阈值（≥1%判定有正文，
# 样张实测空白0.00%与有内容≥6.79%间隔两个数量级，余量充足）；非白判定亮度阈值（任一通道<245）
_PAGENUM_RESERVE_PT = 40.0
_PAGENUM_OCCUPY_RATIO = 0.01
_PAGENUM_NON_WHITE = 245


def _get_pagenum_font():
    """获取页码宋体字体对象（模块级缓存；加载失败返回 None 走无页码兜底）"""
    global _PAGENUM_FONT_CACHE
    if _PAGENUM_FONT_CACHE is None:
        if not _PAGENUM_FONT_PATH.exists():
            log_info(f"  [页码] 宋体字体文件缺失，本批 PDF 不添加页码: {_PAGENUM_FONT_PATH}")
            return None
        _PAGENUM_FONT_CACHE = fitz.Font(fontfile=str(_PAGENUM_FONT_PATH))
    return _PAGENUM_FONT_CACHE


# ============================================================
# zhaoqiaotong 2026-09-02 研发BUG-0041-图档扫描-3.2.04-修复PDF页码遮挡正文内容的问题
# 页码腾位辅助函数组：票据占满整页或延伸到页底时，页码（白底衬+黑字）会遮挡正文。
# 处理策略：绘制页码前检测页码区域是否已有正文；有则优先将内容整体上移（顶部空白
# 足够，尺寸不变），否则以页面顶部为不动点等比缩放（底部留出页码带），保证每页
# 页码保留且零遮挡。变换采用 PDF 标准 cm 图形矩阵（clean_contents 合并内容流后
# 包裹 q...Q），图像与OCR文字层整体跟随变换，双层PDF可搜索性不变（已实验实证）。
# ============================================================


def _pagenum_rect_occupied(page, rect) -> bool:
    """检测页码矩形（外扩2pt）内是否已有正文内容。

    局部渲染（约30x24pt@72DPI，<1000像素）取像素，非白像素占比≥阈值判定有正文。
    任何异常返回 False（按空白处理照常绘制页码，与修复前行为一致，零回归红线）。
    """
    try:
        clip = fitz.Rect(rect.x0 - 2, rect.y0 - 2, rect.x1 + 2, rect.y1 + 2) & page.rect
        pix = page.get_pixmap(clip=clip, dpi=72)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        non_white = int((arr[:, :, :3].min(axis=2) < _PAGENUM_NON_WHITE).sum())
        return non_white / (pix.width * pix.height) >= _PAGENUM_OCCUPY_RATIO
    except Exception as e:
        log_info(f"  [页码] 页码区域内容检测失败，按空白处理: {e}")
        return False


def _pagenum_blanks_pt(page):
    """整页低分辨率渲染计算内容包围盒，返回(顶部空白pt, 底部空白pt)。

    抗噪：行非白像素数≥max(3, 行宽2%)才计为内容行，排除扫描图边缘孤立杂色
    （样张019最底行仅7px杂色，不抗噪会使底部空白测量失真而误选缩放策略）。
    任何异常返回 (None, None)，调用方跳过该页腾位（该页不绘制页码，保底不遮挡正文）。
    """
    try:
        probe_dpi = 54
        pix = page.get_pixmap(dpi=probe_dpi)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        mask = arr[:, :, :3].min(axis=2) < _PAGENUM_NON_WHITE
        scale = 72.0 / probe_dpi
        row_cnt = mask.sum(axis=1)
        rows = np.where(row_cnt >= max(3, int(mask.shape[1] * 0.02)))[0]
        h_pt = page.rect.height
        if rows.size == 0:
            return h_pt, h_pt
        return float(rows[0]) * scale, float(h_pt - (rows[-1] + 1) * scale)
    except Exception as e:
        log_info(f"  [页码] 页面内容包围盒测量失败: {e}")
        return None, None


def _pagenum_apply_transform(page, matrix_text: str) -> None:
    """对页面内容施加全局 cm 图形矩阵变换（PDF用户空间，y向上）。

    clean_contents 将内容流合并为单条后包裹 q <矩阵> cm ... Q，页面全部内容
    （图像层+OCR文字层）整体跟随变换，内容零删除。matrix_text 形如
    "1 0 0 1 0 37.7"（上移37.7pt）或 "0.94 0 0 0.94 17.6 51"（等比缩放）。
    变换异常由调用方兜底（该页跳过页码，PDF照常生成）。
    """
    page.clean_contents()
    xref = page.get_contents()[0]
    data = page.parent.xref_stream(xref)
    page.parent.update_stream(
        xref,
        b"q\n" + matrix_text.encode("ascii") + b" cm\n" + data + b"\nQ\n"
    )


def add_page_numbers(pdf_doc):
    """
    为PDF添加页码（页面内容文字方式，内嵌宋体子集字体）

    页码要求（研发需求-0138-图档扫描-3.2.00-PDF添加页码）：
    1. 位置：页脚底部居中，距下边缘 7mm，从 1 开始每页连续
    2. 字体：宋体（Noto Serif SC 子集，SIL OFL 开源可随离线包分发）
    3. 字号：10pt（10号字）；颜色：黑色；白底衬保证可读性
    4. 样式：- X -（例如 - 1 -，- 2 -）

    xuechong 2026-08-27 研发需求-0138-图档扫描-3.2.00-PDF添加页码 零回归红线：
    本函数任何异常只记日志并放弃页码（PDF 照常生成，不带页码），
    绝不上抛导致生成任务失败、绝不产出损坏 PDF。
    2026-08-28 适应性整改：返回 bool（True=已加页码，False=未加，如字体缺失兜底），
    供调用方在任务消息中告知用户"页码未添加"，仍不影响 PDF 生成。

    xuechong 2026-08-27 研发需求-0138-图档扫描-3.2.00-PDF添加页码 绘制方式变更说明：
    旧实现采用 FreeText 注释（当时认为 insert_text 会破坏白色文字层）。
    实测 PyMuPDF 1.28.2 下 insert_text 与现行 TextWriter 透明文字层完全共存
    （实证材料见工作目录），且 FreeText 注释不支持自定义字体文件、无法内嵌宋体，
    故改为页面内容文字 + insert_font 内嵌宋体子集（多页字体仅嵌入一次，已实测）。

    zhaoqiaotong 2026-09-02 研发BUG-0041-图档扫描-3.2.04-修复PDF页码遮挡正文内容的问题 腾位说明：
    每页绘制前检测页码区域是否已有正文（票据占满整页或延伸到页底时，旧逻辑的
    白底衬+页码会直接盖在票据上）。有正文优先将内容整体上移（顶部空白足够时，
    尺寸不变），否则以页面顶部为不动点等比缩放，底部腾出页码带后再绘制页码，
    每页页码保留、连续编号不变；双层PDF文字层随变换整体移动，可搜索性不变。
    区域检测/包围盒测量失败按空白照常绘制，内容变换失败该页跳过页码，
    均不阻断PDF生成（零回归红线延续）。方案与实验数据见研发BUG-0041工作目录。
    """
    try:
        # 零回归红线兜底：字体缺失/损坏时放弃页码，PDF 正常产出（与旧版无页码行为一致）
        font = _get_pagenum_font()
        if font is None:
            return False

        # 10号字 = 10pt（中文字号序列无"10号"，按 Word 数字字号理解，用户已确认默认项）
        font_size = 10

        # 7mm 转换为点（1mm ≈ 2.834645pt），沿用旧版位置参数
        margin_bottom = 7 * 2.834645  # 约19.84pt

        total_pages = len(pdf_doc)

        for page_num in range(total_pages):
            page = pdf_doc[page_num]

            # 页码文本：- X -（左右各有一条一字线）
            page_text = f"- {page_num + 1} -"

            # 按字体实际度量精确计算文本宽度（替代旧版估算式）
            text_width = font.text_length(page_text, fontsize=font_size)

            # 页码位置：页面底部往上，水平居中；insert_text 的 y 为文字基线
            x_center = page.rect.width / 2
            x_start = x_center - text_width / 2
            y_baseline = page.rect.height - margin_bottom

            try:
                # 白底衬矩形（与旧版 FreeText 白底视觉一致，仅覆盖页码条区域）
                rect = fitz.Rect(
                    x_start - 5,           # 左侧留余量
                    y_baseline - font_size - 5,
                    x_start + text_width + 5,
                    y_baseline + 5
                )

                # zhaoqiaotong 2026-09-02 研发BUG-0041-图档扫描-3.2.04-修复PDF页码遮挡正文内容的问题
                # 页码腾位：区域空白（占比<1%）照常绘制（与修复前行为一致）；
                # 区域已有正文时优先上移（顶部空白足够，内容尺寸不变），
                # 否则等比缩放（以页面顶部为不动点，底部腾出页码带），保证零遮挡。
                # 测量失败按空白处理照常绘制（零回归红线）；变换失败走本层 except，
                # 该页跳过页码但 PDF 照常生成（保底不遮挡正文）。
                if _pagenum_rect_occupied(page, rect):
                    top_blank, bottom_blank = _pagenum_blanks_pt(page)
                    if top_blank is None:
                        log_info(f"  [页码] 第 {page_num + 1} 页腾位测量失败，该页跳过页码")
                        continue
                    delta = _PAGENUM_RESERVE_PT - bottom_blank
                    if delta > 0 and top_blank >= delta + 2.0:
                        # PyMuPDF 视角内容上移 delta = PDF 用户空间（y向上）平移 +delta
                        _pagenum_apply_transform(page, f"1 0 0 1 0 {delta:.4f}")
                        log_info(f"  [页码] 第 {page_num + 1} 页页码区域有正文，内容整体上移 {delta:.1f}pt 腾出页码带")
                    else:
                        # 缩放：以页面顶部为不动点等比缩小，左右对称留白，底部空出预留带
                        s = (page.rect.height - _PAGENUM_RESERVE_PT) / page.rect.height
                        _pagenum_apply_transform(
                            page,
                            f"{s:.4f} 0 0 {s:.4f} "
                            f"{(1 - s) * page.rect.width / 2:.4f} {(1 - s) * page.rect.height:.4f}"
                        )
                        log_info(f"  [页码] 第 {page_num + 1} 页页码区域有正文，内容等比缩放 s={s:.3f} 腾出页码带")

                page.draw_rect(rect, color=None, fill=(1, 1, 1))
                # 引用宋体子集字体（PyMuPDF 自动去重，多页仅嵌入一次）
                # zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题
                # 页码字体资源名由 F0 改为 F1：OCR 透明文字层（china-s）在页面资源中占用 F0，
                # 编辑PDF对已子集化的OCR页面追加页码时，F0 同名会被 OCR 子集字库占用，
                # 导致页码字形缺失（提取为空字符、视觉不显示）。F1 独立命名后互不冲突。
                page.insert_font(fontname="F1", fontfile=str(_PAGENUM_FONT_PATH))
                page.insert_text(
                    (x_start, y_baseline),
                    page_text,
                    fontname="F1",
                    fontsize=font_size,
                    color=(0, 0, 0)  # 黑色文字
                )
            except Exception as e:
                # 单页失败跳过该页页码，不中断整本（沿用旧版容错）
                log_info(f"  [页码] 第 {page_num + 1} 页添加失败: {e}")

    except Exception as e:
        # 零回归红线兜底：页码功能任何异常仅记日志，PDF 照常生成（不带页码）
        log_info(f"  [页码] 添加页码失败，本批 PDF 不带页码: {e}")
        return False
    return True

# ============================================================
# 数据模型
# ============================================================

class TaskStatus(BaseModel):
    task_id: str
    status: str  # pending, processing, completed, failed
    progress: int  # 0-100
    total_files: int
    processed_files: int
    message: str
    created_at: str
    completed_at: Optional[str] = None
    output_files: List[str] = []

class ProcessConfig(BaseModel):
    enable_deskew: bool = True
    enable_background_enhance: bool = True
    enable_seal_protection: bool = True
    enable_aggressive_clean: bool = True

# ============================================================
# 辅助函数
# ============================================================

SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'}

def is_image_file(filename: str) -> bool:
    """检查文件是否为支持的图片格式"""
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS

def process_single_image(image_path: Path, output_dir: Path, cleaner, idx: int = 0) -> dict:
    """处理单张图片并转换为 PDF"""
    try:
        # 读取图片（支持中文路径）
        image = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return {"success": False, "error": f"无法读取图片: {image_path.name}"}
        
        # xuechong 2026-08-07 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 修复DPI丢失
        # 缓存原图DPI，确保清洁器和PDF生成使用一致的DPI
        image_dpi = get_image_dpi(image_path)

        # 处理图片（清洁、矫正等）+ OCR识别（均为GPU操作）
        # xuechong GPU 队列锁保护，防止多用户并发导致显存竞争OOM
        with _gpu_queue_lock:
            result = cleaner.process(image, debug=False, dpi=image_dpi)
            cleaned_image = result['result']

            # 转换为 PDF（带 OCR 文字层，使用索引序号避免同名stem覆盖）
            # 性能优化：直接传递内存中的图像，避免临时PNG的磁盘写入+读取往返
            # xuechong 2026-08-07 修复：传入原始DPI确保PDF页面尺寸正确
            pdf_path = output_dir / f"_page_{idx:04d}.pdf"
            pdf_success = image_to_searchable_pdf(cleaned_image, pdf_path, jpeg_quality=95, dpi=image_dpi)

        # PDF生成失败时的回退：保存清洁后的PNG（保持原有容错行为）
        temp_png_path = output_dir / f"_page_{idx:04d}_cleaned.png"
        if not pdf_success:
            cv2.imencode('.png', cleaned_image)[1].tofile(str(temp_png_path))
        
        return {
            "success": pdf_success,
            "input": image_path.name,
            "output": pdf_path.name if pdf_success else temp_png_path.name,
            "output_type": "pdf" if pdf_success else "png",
            "size": f"{image.shape[1]}x{image.shape[0]}",
            "skew_angle": result.get('skew_angle', 0)
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e), "input": image_path.name}

def process_task(task_id: str, file_paths: List[Path], username: str = "admin"):
    """后台处理任务（用户隔离）"""
    # xuechong 2026-07-18 使用用户 scope
    from backend.services.user_scope import get_user_scope
    scope = get_user_scope(username)
    task = scope.upload_tasks.get(task_id)
    if not task:
        log_info(f"[任务{task_id}] 任务不存在")
        return
    task_output_dir = scope.output_dir / task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)

    # 初始化取消标志
    scope.tasks_cancel_flags[task_id] = False
    
    try:
        cleaner = get_cleaner()
        task["status"] = "processing"
        task["message"] = "正在处理图片..."
        
        results = []
        pdf_files = []
        
        for i, file_path in enumerate(file_paths):
            # 检查是否被取消
            if scope.tasks_cancel_flags.get(task_id, False):
                task["status"] = "cancelled"
                task["message"] = f"已取消处理。已完成 {len([r for r in results if r['success']])} 张"
                task["completed_at"] = datetime.now().isoformat()
                # 如果有已处理的 PDF，仍然合并
                if pdf_files:
                    _merge_task_pdfs(task_output_dir, pdf_files, task_id)
                return
            
            if not file_path.exists():
                continue
            
            task["message"] = f"{file_path.name} ({i+1}/{len(file_paths)})"
            result = process_single_image(file_path, task_output_dir, cleaner, idx=i)
            results.append(result)
            
            task["processed_files"] = i + 1
            task["progress"] = int((i + 1) / len(file_paths) * 90)  # 预留 10% 给 PDF 合并
            
            if result["success"]:
                task["output_files"].append(result["output"])
                if result.get("output_type") == "pdf":
                    pdf_files.append(task_output_dir / result["output"])

            # 每处理 20 张图片清理一次 GPU 缓存，防止显存持续增长
            # 性能优化：降低清理频率（原每5张），减少不必要的 CUDA 同步开销
            if (i + 1) % 20 == 0:
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        log_info(f"[任务{task_id}] 已清理GPU显存缓存 ({i+1}/{len(file_paths)})")
                except Exception as e:
                    log_info(f"[任务{task_id}] GPU缓存清理失败（非致命）: {e}")
        
        # 合并所有 PDF 为一个
        task["message"] = "正在合并 PDF..."
        merged_pdf_path = _merge_task_pdfs(task_output_dir, pdf_files, task_id)
        
        if merged_pdf_path:
            # ============================================================
            # 性能优化：跳过冗余的双层PDF转换
            # 原因：process_single_image → image_to_searchable_pdf 已为每页
            # 生成OCR文字层，insert_pdf 合并时完整保留文字层，
            # 无需对合并后的PDF重复执行全量OCR识别（消除约1/3总耗时）
            # ============================================================
            task["progress"] = 95
            log_info(f"[任务{task_id}] 合并PDF已包含OCR文字层，跳过重复双层转换: {merged_pdf_path.name}")
            
            task["merged_pdf"] = merged_pdf_path.name
            # 文件夹上传时，最终只输出一个合并的 PDF
            task["output_files"] = [merged_pdf_path.name]
        
        task["status"] = "completed"
        task["progress"] = 100
        success_count = len([r for r in results if r['success']])
        fail_count = len([r for r in results if not r['success']])
        # xuechong 2026-07-18 记录下载历史到用户 scope
        if merged_pdf_path and pdf_files:
            first_name = Path(file_paths[0]).stem if file_paths else task_id
            hist_item = {
                "task_id": task_id,
                "folder_name": first_name or task_id,
                "first_image_name": first_name,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "pdf_path": str(merged_pdf_path),
                "file_count": len(pdf_files),
                "download_count": 0,
                "edited": False,
                "edit_download_count": 0,
                "username": username
            }
            scope.download_history.insert(0, hist_item)
            scope.save_download_history()

        task["message"] = f"处理完成！成功 {success_count} 张，失败 {fail_count} 张，已生成 PDF"
        task["completed_at"] = datetime.now().isoformat()
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        log_info(f"[任务{task_id}] 处理失败: {e}")
        log_info(f"[任务{task_id}] 异常详情:\n{error_detail}")
        task["status"] = "failed"
        task["message"] = f"处理失败: {str(e)}"
        task["error_detail"] = error_detail
        task["completed_at"] = datetime.now().isoformat()
    finally:
        # 清理取消标志
        scope.tasks_cancel_flags.pop(task_id, None)
        # xuechong 2026-07-18 持久化任务状态（完成/失败后）
        scope.save_tasks()


def _merge_task_pdfs(output_dir: Path, pdf_files: List[Path], task_id: str) -> Optional[Path]:
    """合并任务的所有 PDF 文件"""
    if not pdf_files:
        return None
    
    merged_pdf_path = output_dir / f"merged_{task_id}.pdf"
    
    if len(pdf_files) == 1:
        # 只有一个 PDF，直接复制
        shutil.copy(pdf_files[0], merged_pdf_path)
    else:
        # 多个 PDF，合并
        merge_pdfs_to_single(pdf_files, merged_pdf_path)
    
    # 删除单独的 PDF 文件（保留合并后的）
    for pdf_file in pdf_files:
        if pdf_file.exists() and pdf_file != merged_pdf_path:
            try:
                pdf_file.unlink()
            except OSError as e:
                log_info(f"[文件清理] 删除临时PDF失败 {pdf_file.name}: {e}")
    
    return merged_pdf_path

# ============================================================
# API 端点
# ============================================================

# System routes → routes/system.py + routes/websocket.py
# 登录验证 API → routes/auth.py
# tasks API → routes/tasks.py
# 系统管理 API → routes/system.py


def process_uploaded_folder_task(task_id: str, username: str = "admin"):
    """后台处理上传的文件夹（用户隔离）"""
    import time as _time
    import fitz

    # xuechong 2026-07-18 使用用户 scope
    from backend.services.user_scope import get_user_scope
    scope = get_user_scope(username)
    task = scope.upload_tasks.get(task_id)
    if not task:
        log_info(f"[处理任务{task_id}] 任务不存在")
        return

    upload_dir = Path(task["upload_dir"])
    output_dir = Path(task["output_dir"])
    add_page_number = task.get("add_page_number", True)
    selected_path = task.get("selected_path", "")
    
    # 检查是否已执行过一键修图（针对同一目录）
    images_already_cleaned = (
        task.get("images_cleaned", False) and 
        task.get("cleaned_path", "") == selected_path
    )
    
    try:
        cleaner = None
        if not images_already_cleaned:
            # xuechong 2026-06-02 GPU 队列锁保护，防止多用户并发 OOM
            with _gpu_queue_lock:
                cleaner = get_cleaner()

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 单页快速文字层：预初始化 OCR 引擎（det960）
        # 主流程不再调用整本 convert_to_dual_layer_pdf_rapid，改用每页 TextWriter 快速路径
        from .ocr_rapid import get_rapid_ocr_engine, ocr_image_with_rapid, write_ocr_text_layer
        try:
            with _gpu_queue_lock:
                _ocr_engine_info = get_rapid_ocr_engine("ch", use_cls=False, det_limit=960)
            log_info(f"[处理任务{task_id}] OCR 引擎已就绪（det960, TextWriter 快速文字层模式）")
        except Exception as ocr_init_err:
            log_info(f"[处理任务{task_id}] OCR 引擎初始化失败，将回退纯图 PDF: {ocr_init_err}")
            _ocr_engine_info = None
        
        target_dir = upload_dir / selected_path if selected_path else upload_dir

        # 路径穿越防护
        try:
            target_dir.resolve().relative_to(upload_dir.resolve())
        except ValueError:
            task["status"] = "failed"
            task["message"] = "无效的目录路径"
            task["completed_at"] = datetime.now().isoformat()
            log_info(f"[处理任务{task_id}] 路径穿越拒绝: {selected_path}")
            return
        
        image_files = []
        for item in target_dir.iterdir():
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                image_files.append(item)
        
        # 按文件名排序（确保第一个文件用作PDF命名）
        image_files = sorted(image_files, key=lambda x: x.name.lower())
        total_files = len(image_files)
        
        if total_files == 0:
            task["status"] = "failed"
            task["message"] = "没有找到图片文件"
            return
        
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 内存 PDF 合并
        # 每页 fitz.Document 保留在内存（不落盘），合并时 insert_pdf 直接引用，
        # 省去逐页写盘+读回+删除；大目录（数百页）内存估算约 3-8MB/页
        pdf_docs = []
        skipped_images = []  # 记录处理失败被跳过的图片
        # zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
        # 记录被判定为空白页而忽略的图片（收尾消息明确告知用户忽略数量）
        blank_skipped = []  # 记录空白页被忽略的图片文件名
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 跟踪单页 OCR 失败（合并后触发整本回退）
        _ocr_any_page_failed = False
        start_time = _time.time()

        # 日志提示处理模式
        if images_already_cleaned:
            log_info(f"[处理任务{task_id}] 图片已净化，跳过净化步骤，直接合成PDF")
        else:
            log_info(f"[处理任务{task_id}] 需要净化图片后合成PDF")

        # 检查是否使用 GPU（用于 GPU 内存管理）
        _use_gpu = False
        if cleaner is not None and hasattr(cleaner, 'device'):
            _use_gpu = str(cleaner.device) != 'cpu'
            if _use_gpu:
                try:
                    import torch
                    torch.cuda.empty_cache()
                    log_info(f"[处理任务{task_id}] GPU模式: {cleaner.device}，已清理显存缓存")
                except Exception as e:
                    log_info(f"[处理任务{task_id}] GPU缓存清理失败（非致命）: {e}")

        # 检查备份目录，确定哪些图片已被手动修改
        backup_dir = upload_dir / "_backup"

        for idx, image_path in enumerate(image_files):
            # xuechong 2026-07-18 检查取消标志（用户 scope）
            if scope.tasks_cancel_flags.get(task_id, False):
                task["status"] = "cancelled"
                task["message"] = f"处理已取消，已完成 {idx}/{total_files} 张"
                task["completed_at"] = datetime.now().isoformat()
                # 关闭已生成的内存页 Document（不再有临时文件）
                if pdf_docs:
                    for tmp_doc in pdf_docs:
                        try:
                            tmp_doc.close()
                        except Exception as close_e:
                            log_info(f"[处理任务{task_id}] 取消时关闭内存页 Document 失败（非致命）: {close_e}")
                    pdf_docs.clear()
                # 清理合并后的PDF（如果已生成）
                if idx > 0:
                    first_name = image_files[0].stem
                    merged_tmp = output_dir / f"{first_name}.pdf"
                    if merged_tmp.exists():
                        try:
                            merged_tmp.unlink()
                        except OSError:
                            pass
                scope.tasks_cancel_flags.pop(task_id, None)
                # xuechong 2026-06-01 更新用户上传历史
                _update_upload_history( task_id, "cancelled", task["message"], task["completed_at"], False)
                log_info(f"[处理任务{task_id}] 已取消: {idx}/{total_files} 张已处理")
                return

            processed_count = idx + 1
            task["current_file"] = image_path.name
            task["processed_files"] = processed_count
            task["progress"] = int(processed_count / total_files * 90)

            # 计算相对路径，检查是否有备份（有备份说明已手动修改过）
            rel_path = image_path.relative_to(upload_dir)
            backup_path = backup_dir / rel_path
            image_has_backup = backup_path.exists()

            # 判断是否需要跳过净化（已批量净化 或 已手动修改）
            skip_cleaning = images_already_cleaned or image_has_backup

            # xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
            # 用户复验：页面标题已是"正在生成PDF..."，副标题再写"正在合成PDF:"/"正在处理:"
            # 属于重复废话——统一只显示"文件名 (n/N)"，标题管动作、副标题管对象和进度
            task["message"] = f"{image_path.name} ({processed_count}/{total_files})"

            try:
                # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-009 预解码缓存（启用时从缓存读取，避免重复 imdecode）
                from backend.services.image_cache import load_image_with_cache
                try:
                    image, image_dpi = load_image_with_cache(image_path)
                except ValueError:
                    log_info(f"[处理任务{task_id}] 图片读取失败，跳过: {image_path.name}")
                    skipped_images.append((image_path.name, "图片读取失败"))
                    continue

                # 如果图片已净化或已手动修改，直接使用当前图片；否则执行净化
                # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 清洁 + OCR 合并到一个 GPU 锁内
                ocr_results = []
                if skip_cleaning:
                    cleaned_image = image
                    if image_has_backup and not images_already_cleaned:
                        log_info(f"[处理任务{task_id}] 图片已手动修改，跳过净化: {image_path.name}")
                else:
                    with _gpu_queue_lock:
                        result = cleaner.process(image, debug=False, dpi=image_dpi)
                    cleaned_image = result['result']

                # zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
                # 空白页检测（净化后、OCR前）：净化后空白页已成纯白（装订孔等无效杂质已被
                # 清除），带签章页因彩色印章保护仍会检出有效内容而保留。空白页直接忽略
                # 不成页、不做OCR——先忽略空白页、后加页码：合并后 add_page_numbers 仅对
                # 保留页从1连续编号。检测异常按非空白处理（零误删红线：宁可不删、绝不误删）。
                from backend.services.blank_page_service import is_blank_bgr_image
                _is_blank, _blank_reason = is_blank_bgr_image(cleaned_image, image_dpi)
                if _is_blank:
                    blank_skipped.append(image_path.name)
                    log_info(f"[处理任务{task_id}] 空白页已忽略: {image_path.name}（{_blank_reason}）")
                    continue

                # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 单页 OCR（GPU 锁内推理）
                if _ocr_engine_info is not None:
                    try:
                        with _gpu_queue_lock:
                            ocr_results = ocr_image_with_rapid(cleaned_image, _ocr_engine_info, det_limit_side_len=960)
                    except Exception as ocr_err:
                        log_info(f"[处理任务{task_id}] 单页OCR失败，该页无文字层: {image_path.name} - {ocr_err}")
                        _ocr_any_page_failed = True

                # 使用 PIL 和 fitz 创建 PDF
                rgb_image = cv2.cvtColor(cleaned_image, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(rgb_image)

                # 计算PDF页面尺寸（使用原图DPI）
                # 公式：PDF点数 = 像素数 * 72 / DPI
                pdf_width = pil_image.width * 72.0 / image_dpi
                pdf_height = pil_image.height * 72.0 / image_dpi

                # 安全检查：PDF页面尺寸应在合理范围内
                # A4纸大约 595x842 pt，最大允许 A0纸的4倍（约 9500x13500 pt）
                MAX_PDF_DIMENSION = 14400  # 约200英寸，200*72=14400pt
                if pdf_width > MAX_PDF_DIMENSION or pdf_height > MAX_PDF_DIMENSION:
                    log_info(f"  [PDF] 警告: 计算的页面尺寸过大 ({pdf_width:.1f}x{pdf_height:.1f}pt)，可能DPI读取错误")
                    # 使用默认300 DPI重新计算
                    image_dpi = 300
                    pdf_width = pil_image.width * 72.0 / image_dpi
                    pdf_height = pil_image.height * 72.0 / image_dpi
                    log_info(f"  [PDF] 使用默认DPI={image_dpi}重新计算: {pdf_width:.1f}x{pdf_height:.1f}pt")

                log_info(f"  [PDF] {image_path.name}: {pil_image.width}x{pil_image.height}px, DPI={image_dpi}, 页面={pdf_width:.1f}x{pdf_height:.1f}pt")

                # 创建 PDF（使用正确的页面尺寸）
                # 性能优化：内存流传递JPEG，避免临时文件的磁盘写入+读取+删除
                jpeg_buf = io.BytesIO()
                pil_image.save(jpeg_buf, format="JPEG", quality=90, dpi=(image_dpi, image_dpi))
                doc = fitz.open()
                page = doc.new_page(width=pdf_width, height=pdf_height)
                # 图片填满整个页面（图片会自动缩放到页面尺寸）
                page.insert_image(page.rect, stream=jpeg_buf.getvalue())

                # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 TextWriter 快速透明文字层
                # spike 已验证：文字层跨 insert_pdf 合并后完整保留且可搜索
                if ocr_results:
                    text_count = write_ocr_text_layer(page, ocr_results, image_dpi)
                    log_info(f"  [PDF] {image_path.name}: OCR文字层 {text_count} 个文本框")
                else:
                    log_info(f"  [PDF] {image_path.name}: 无OCR文字层（OCR失败或无文字）")

                # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 不落盘，内存合并
                pdf_docs.append(doc)

            except Exception as e:
                import traceback
                error_detail = traceback.format_exc()
                log_info(f"[处理任务{task_id}] 处理异常: {image_path.name} - {str(e)}")
                log_info(f"[处理任务{task_id}] 异常详情:\n{error_detail}")

                # GPU 模式下清理 CUDA 缓存
                if _use_gpu:
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception as e:
                        log_info(f"[任务{task_id}] GPU缓存清理失败（非致命）: {e}")

                # 异常即停：设置任务失败并返回
                task["status"] = "failed"
                task["message"] = f"处理异常已停止: {image_path.name} - {str(e)}"
                task["error_detail"] = error_detail
                task["completed_at"] = datetime.now().isoformat()
                log_info(f"[处理任务{task_id}] 因异常停止，已处理 {processed_count}/{total_files} 张")
                # 关闭已生成的内存页 Document，避免泄漏
                for tmp_doc in pdf_docs:
                    try:
                        tmp_doc.close()
                    except Exception as close_e:
                        log_info(f"[处理任务{task_id}] 异常退出时关闭内存页 Document 失败（非致命）: {close_e}")
                pdf_docs.clear()
                return

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 修复 REQ-002 内存合并后 pdf_files 未更新
        _pdf_success_count = len(pdf_docs)

        log_info(f"[处理任务{task_id}] 处理统计: 总计 {total_files} 张, 成功 {_pdf_success_count} 张")

        # 合并PDF
        first_image_name = image_files[0].stem if image_files else "output"
        if pdf_docs:
            task["message"] = "正在合并PDF..."
            task["progress"] = 92

            merged_pdf_path = output_dir / f"{first_image_name}.pdf"
            
            merged_doc = fitz.open()
            # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 内存 Document 直接合并
            for pdf_doc in pdf_docs:
                merged_doc.insert_pdf(pdf_doc)
            
            # 添加页码（统一使用 add_page_numbers 函数）
            # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
            # 记录页码是否成功，失败（字体缺失等兜底）时在任务消息中明确告知用户
            _pagenum_added = True
            if add_page_number:
                _pagenum_added = add_page_numbers(merged_doc)

            # zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题
            # 合并保存前子集化OCR文字层字库并回收旧全量字库流（每页一份约3.5MB的根因消除点）
            from backend.services.pdf_font_service import save_pdf_with_font_subset
            save_pdf_with_font_subset(merged_doc, merged_pdf_path)
            merged_doc.close()
            # 释放内存页 Document
            for pdf_doc in pdf_docs:
                try:
                    pdf_doc.close()
                except Exception as close_e:
                    log_info(f"[处理任务{task_id}] 合并后释放内存页 Document 失败（非致命）: {close_e}")
            pdf_docs.clear()
            
            # ============================================================
            # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 跳过冗余整本 OCR
            # 每页已用 TextWriter 写入透明文字层，insert_pdf 合并后文字层完整保留
            # （spike 验证通过：get_text() 可搜索、blocks 可提取）
            # 不再调用 convert_to_dual_layer_pdf_rapid 做全量 OCR，节省 100% OCR 耗时
            # ============================================================
            task["message"] = "PDF 已包含 OCR 文字层，无需重复转换"
            task["progress"] = 95
            log_info(f"[处理任务{task_id}] 合并PDF已包含OCR文字层，跳过重复双层转换: {merged_pdf_path.name}")

            # 若所有页均无 OCR 文字层（引擎初始化失败），回退整本 OCR
            # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 回退条件：
            # ① 引擎未初始化 ② 任意页单页 OCR 失败
            _need_fallback_ocr = (_ocr_engine_info is None) or _ocr_any_page_failed
            if _need_fallback_ocr:
                if _ocr_engine_info is None:
                    log_info(f"[处理任务{task_id}] OCR 引擎未初始化，回退整本双层转换")
                else:
                    log_info(f"[处理任务{task_id}] 部分页 OCR 失败，回退整本双层转换补全文字层")
                # xuechong 2026-07-18 OCR 阶段前检查取消标志（用户 scope）
                if scope.tasks_cancel_flags.get(task_id, False):
                    task["status"] = "cancelled"
                    task["message"] = f"处理已取消（OCR前）"
                    task["completed_at"] = datetime.now().isoformat()
                    scope.tasks_cancel_flags.pop(task_id, None)
                    _update_upload_history(task_id, "cancelled", task["message"], task["completed_at"], True)
                    log_info(f"[处理任务{task_id}] 在OCR前取消")
                    return

                try:
                    from .ocr_rapid import convert_to_dual_layer_pdf_rapid
                    dual_layer_temp_path = output_dir / f"{first_image_name}_dual.pdf"
                    with _gpu_queue_lock:
                        dual_success = convert_to_dual_layer_pdf_rapid(
                            str(merged_pdf_path),
                            str(dual_layer_temp_path),
                            ocr_lang="ch"
                        )
                    if dual_success and dual_layer_temp_path.exists():
                        try:
                            merged_pdf_path.unlink(missing_ok=True)
                            dual_layer_temp_path.rename(merged_pdf_path)
                            log_info(f"[处理任务{task_id}] 回退双层PDF转换成功")
                        except OSError as e:
                            log_info(f"[处理任务{task_id}] 替换PDF失败: {e}")
                    else:
                        log_info(f"[处理任务{task_id}] 回退双层PDF转换失败，保留原PDF")
                except Exception as dual_err:
                    import traceback
                    error_detail = traceback.format_exc()
                    log_info(f"[处理任务{task_id}] 回退双层PDF转换异常: {dual_err}")
                    log_info(f"[处理任务{task_id}] 异常详情:\n{error_detail}")
            
            task["merged_pdf"] = str(merged_pdf_path)

        elapsed_time = _time.time() - start_time
        completed_time = datetime.now()

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 修复
        # REQ-002 内存合并改造后 pdf_docs 取代了 pdf_files，最终检查改用 _pdf_success_count
        if _pdf_success_count > 0:
            # 记录到下载历史（必须在 status="completed" 之前，避免竞态：
            # 前端看到completed后会立即发起下一个目录的processUpload，
            # 后者会重置task["merged_pdf"]等字段，导致历史记录pdf_path为空）
            history_item = {
                "task_id": task_id,
                "folder_name": selected_path or task.get("folder_name", task_id),
                "first_image_name": first_image_name,
                "created_at": completed_time.strftime("%Y-%m-%d %H:%M:%S"),
                "pdf_path": str(merged_pdf_path),
                "file_count": _pdf_success_count
            }
            history_item["download_count"] = 0
            history_item["edited"] = False
            history_item["edit_download_count"] = 0
            history_item["username"] = username
            # xuechong 2026-07-18 写入用户 scope
            scope.download_history.insert(0, history_item)
            scope.save_download_history()
            log_info(f"[处理任务{task_id}] 已添加到下载历史: {history_item['folder_name']}")

            task["status"] = "completed"
            task["progress"] = 100
            # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
            # 开了页码但兜底未加上时，消息明确告知（PDF 本身照常生成，不受影响）
            _pagenum_note = "" if (not add_page_number or _pagenum_added) else "；注意：页码未添加（页码字体文件缺失或异常，详见服务日志）"
            # zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
            # 完成消息追加空白页忽略数量（页码仅对保留页连续编号，与忽略动作天然有序）
            _blank_note = f"；已忽略 {len(blank_skipped)} 张空白页" if blank_skipped else ""
            if skipped_images:
                task["message"] = f"处理完成！成功 {_pdf_success_count}/{total_files} 个文件（跳过 {len(skipped_images)} 个），耗时 {elapsed_time:.1f}秒{_pagenum_note}{_blank_note}"
            else:
                task["message"] = f"处理完成！共处理 {_pdf_success_count} 个文件，耗时 {elapsed_time:.1f}秒{_pagenum_note}{_blank_note}"
        else:
            task["status"] = "failed"
            # zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
            # 全部图片均为空白页时给出明确失败原因（不能产出0页PDF）
            if blank_skipped and len(blank_skipped) == total_files:
                task["message"] = f"处理失败：全部 {total_files} 张图片均为空白页，未生成PDF"
            elif blank_skipped:
                task["message"] = f"处理失败：没有成功生成任何PDF文件（另有 {len(blank_skipped)} 张空白页已忽略）"
            else:
                task["message"] = "处理失败：没有成功生成任何PDF文件"

        task["completed_at"] = completed_time.isoformat()
        task["can_download"] = True
        # xuechong 2026-06-01 更新用户上传历史
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 修复：pdf_files 在内存合并后不再填充，改用 _pdf_success_count
        _update_upload_history( task_id, task["status"], task["message"], completed_time.isoformat(), _pdf_success_count > 0)

        # xuechong 2026-09-22 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
        # PDF生成成功后推送到form-in文件库：直写云盘存储+读回校验MD5+调元数据注册接口，
        # 全部在后台单线程池执行；FORM_IN_ENABLED不为true时submit_push直接返回，
        # 任何异常只记日志，不影响本地PDF与任务状态
        if task["status"] == "completed":
            try:
                from backend.form_in import submit_push
                submit_push(str(merged_pdf_path), selected_path or task_id, task)
            except Exception as push_err:
                log_info(f"[处理任务{task_id}] 推送form-in入口调用失败（不影响本地PDF）: {push_err}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        task["status"] = "failed"
        task["message"] = f"处理失败: {str(e)}"
        task["completed_at"] = datetime.now().isoformat()
        # xuechong 2026-06-01 更新用户上传历史
        _update_upload_history( task_id, "failed", task["message"], task["completed_at"], False)
    finally:
        # xuechong 2026-07-18 持久化任务状态（用户 scope）
        scope.save_tasks()


@app.get("/api/preview-upload/{task_id}")
async def preview_upload_file(task_id: str, path: str, request: Request = None):
    """预览上传的文件（用户隔离）"""
    # xuechong 2026-07-18 从用户 scope 获取任务
    from backend.services.user_scope import get_user_scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])
    file_path = upload_dir / path
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    try:
        file_path.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问此文件")

    suffix = file_path.suffix.lower()

    if suffix in {'.tif', '.tiff'}:
        try:
            with Image.open(str(file_path)) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='PNG')
                img_byte_arr.seek(0)
                return Response(content=img_byte_arr.getvalue(), media_type="image/png")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TIF文件转换失败: {str(e)}")

    if suffix in {'.png', '.jpg', '.jpeg'}:
        media_type = f"image/{suffix[1:]}"
    elif suffix == '.bmp':
        media_type = "image/bmp"
    elif suffix == '.webp':
        media_type = "image/webp"
    else:
        media_type = "application/octet-stream"
    
    return FileResponse(path=str(file_path), media_type=media_type)



# ============================================================
# 双层PDF转换相关
# ============================================================

# 双层PDF存储目录（使用 STORAGE_ROOT，支持环境变量配置，便于多版本共享数据）
DUAL_LAYER_DATA_ROOT = STORAGE_ROOT / "dual_layer"
DUAL_LAYER_UPLOAD_DIR = DUAL_LAYER_DATA_ROOT / "upload"
DUAL_LAYER_OUTPUT_DIR = DUAL_LAYER_DATA_ROOT / "output"
DUAL_LAYER_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DUAL_LAYER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局 dual_layer 历史/进度/锁已废弃，统一使用 user_scope.py 的 UserScope

# ============================================================
# 启动时初始化
# ============================================================

def mount_frontend():
    """挂载前端静态文件"""
    # 检查是否存在构建后的前端文件
    frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"

    # xuechong 2026-07-21 研发BUG-0009 SPA 回退：未匹配的前端路由（/login、/img-to-pdf 等）返回 index.html
    # 注意：StaticFiles 抛出的是 starlette.exceptions.HTTPException（父类），
    # 不能用 fastapi.HTTPException（子类）捕获，否则回退不生效
    from starlette.exceptions import HTTPException as _StarletteHTTPException

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except _StarletteHTTPException as e:
                if e.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise

    if frontend_dist.exists():
        app.mount("/", SPAStaticFiles(directory=str(frontend_dist), html=True), name="frontend")
        log_info(f"  前端静态文件已挂载: {frontend_dist}")
    else:
        # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 前端产物缺失白屏修复
        # 前端产物缺失时不再静默挂载 frontend 源码目录（源码版 index.html 引用 /src/main.js，
        # 浏览器无法解析裸模块 "vue"，必然白屏）。改为醒目错误日志 + 根路由返回人话提示页，
        # 让"页面打不开"在第一眼就指向真实原因与恢复方式，而不是伪装成正常启动。
        log_info("  [错误] 前端产物缺失: frontend\\dist 不存在，浏览器页面将无法显示！")
        log_info("  [错误] 恢复方式1: 从开发机整目录拷贝 frontend\\dist 到部署目录（离线机适用）")
        log_info("  [错误] 恢复方式2: 安装 Node.js 18+ 后重新运行 bin\\start.bat 自动构建")

        @app.get("/", include_in_schema=False)
        async def frontend_missing_hint():
            # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 缺失提示页
            return HTMLResponse(
                "<html><head><meta charset='utf-8'><title>前端未部署</title></head>"
                "<body style='font-family:微软雅黑,sans-serif;max-width:640px;margin:80px auto;line-height:1.8'>"
                "<h2 style='color:#c0392b'>前端页面未部署</h2>"
                "<p>服务已启动，但缺少前端产物 <b>frontend\\dist</b>，页面无法显示。</p>"
                "<p>恢复方式（二选一）：</p>"
                "<p>1. 从开发机<b>整目录拷贝</b> frontend\\dist 到本机项目 frontend 目录下（离线环境适用）；</p>"
                "<p>2. 安装 Node.js 18+ 后重新运行 bin\\start.bat 自动构建。</p>"
                "</body></html>"
            )

@app.post("/api/process-upload/{task_id}")
async def process_upload_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    add_page_number: bool = True,
    selected_path: str = ""
):
    """处理上传的文件夹（用户隔离）"""
    from backend.services.user_scope import get_user_scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    # xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 生成请求来源诊断日志：区分form-in代理（Java UA无Referer）与浏览器页面直连
    # （带Origin/Referer），排查同一任务被双端重复触发生成的问题
    req_ua = request.headers.get('user-agent', '')
    req_referer = request.headers.get('referer', '') or request.headers.get('origin', '')
    log_info(f"[处理任务{task_id}] 生成请求来源 UA={req_ua[:60]} Referer={req_referer[:80]}")

    # xuechong 2026-07-18 从用户 scope 获取任务
    # xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 开始处理的各拒绝分支补日志：此前拒绝只返回400/404，前端弹"处理失败"框而
    # 扫描系统日志与 form-in 过程日志均无任何记录，问题无从追溯
    task = scope.upload_tasks.get(task_id)
    if not task:
        log_info(f"[处理任务{task_id}] 拒绝开始处理：任务不存在")
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] == "processing":
        log_info(f"[处理任务{task_id}] 拒绝开始处理：任务正在处理中（上一处理尚未结束，稍候自动继续或重试）")
        raise HTTPException(status_code=400, detail="任务正在处理中")

    if not selected_path:
        log_info(f"[处理任务{task_id}] 拒绝开始处理：请选择要处理的目录")
        raise HTTPException(status_code=400, detail="请选择要处理的目录")

    upload_dir = Path(task["upload_dir"])
    selected_dir = (upload_dir / selected_path)

    # 路径穿越防护
    try:
        selected_dir.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的目录路径")

    if not selected_dir.exists():
        raise HTTPException(status_code=400, detail=f"选中的目录不存在: {selected_path}")

    if not selected_dir.is_dir():
        raise HTTPException(status_code=400, detail="请选择目录，而不是文件")

    has_subdirs = any(item.is_dir() and item.name != "_backup" for item in selected_dir.iterdir())
    if has_subdirs:
        raise HTTPException(status_code=400, detail="选中的目录包含子目录，请选择只包含图片文件的目录")

    # 为每个 selected_path 创建独立的输出子目录（用户隔离）
    safe_subdir = selected_path.replace("/", "_").replace("\\", "_") if selected_path else "_root"
    output_dir = scope.output_dir / task_id / safe_subdir

    # 只清空当前子目录的文件
    if output_dir.exists():
        for old_file in output_dir.iterdir():
            try:
                if old_file.is_file():
                    # xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：unlink 包装到线程池
                    await asyncio.to_thread(old_file.unlink)
            except Exception as e:
                log_info(f"[文件清理] 清理输出目录旧文件失败 {old_file.name}: {e}")
    output_dir.mkdir(parents=True, exist_ok=True)

    task["output_dir"] = str(output_dir)
    task["add_page_number"] = add_page_number
    task["selected_path"] = selected_path
    task["progress"] = 0
    task["processed_files"] = 0
    task["current_file"] = ""
    task["merged_pdf"] = None
    task["can_download"] = False
    task["status"] = "processing"
    task["message"] = "正在处理..."

    background_tasks.add_task(process_uploaded_folder_task, task_id, username)

    return {"success": True, "message": "开始处理", "task_id": task_id, "selected_path": selected_path}


# 下载历史与预览 API → routes/download_history.py

# xuechong 2026-06-02 用 lifespan 替代已弃用的 @app.on_event
from contextlib import asynccontextmanager

@asynccontextmanager
async def _app_lifespan(app_instance):
    """应用生命周期管理（替代 on_event startup/shutdown）"""
    # ---- startup ----
    log_info("=" * 60)
    log_info("  海棠文档工坊 Web 服务启动中...")
    log_info("=" * 60)

    init_storage_dirs(state.SERVER_HOST, state.SERVER_PORT)

    state.MONITOR_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    state.MONITOR_TARGET_DIR.mkdir(parents=True, exist_ok=True)
    log_info(f"  源文件目录: {state.MONITOR_SOURCE_DIR}")
    log_info(f"  输出目录: {state.MONITOR_TARGET_DIR}")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_dual_layer_executor, warmup_models)
    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 启动汇总
    log_startup_summary()
    dir_watcher.start(loop)
    mount_frontend()

    yield  # ---- 服务运行中 ----

    # ---- shutdown ----
    dir_watcher.stop()
    log_info("  目录监控已停止")
    _dual_layer_executor.shutdown(wait=True)
    log_info("  线程池已关闭")

app.router.lifespan_context = _app_lifespan

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
