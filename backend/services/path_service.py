# -*- coding: utf-8 -*-
"""路径配置服务 — 所有磁盘路径从 url.conf 统一派生"""
import os
from pathlib import Path


BASE_DIR = Path(__file__).parent.parent


def _get_app_root() -> Path:
    app_root = Path(__file__).parent.parent.parent.resolve()
    if (app_root / "start_server.py").exists():
        return app_root
    return Path.cwd()


APP_ROOT = _get_app_root()


def _get_storage_root() -> Path:
    from backend import config as _cfg
    path = Path(str(_cfg.DATA_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


STORAGE_ROOT = _get_storage_root()


def _get_monitor_dirs() -> tuple:
    base_dir = STORAGE_ROOT if STORAGE_ROOT.name == "data" else (STORAGE_ROOT / "data")
    source_dir = base_dir / "original"
    target_dir = base_dir / "target"
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    return source_dir, target_dir


MONITOR_SOURCE_DIR, MONITOR_TARGET_DIR = _get_monitor_dirs()

# xuechong 2026-07-18 用户隔离：用户数据根目录
USERS_ROOT = STORAGE_ROOT / "users"
USERS_ROOT.mkdir(parents=True, exist_ok=True)

# ---- 可变状态（通过模块引用赋值，避免 from-import + global 赋值裂痕） ----
UPLOAD_DIR: Path = None
OUTPUT_DIR: Path = None
TEMP_DIR: Path = None
SERVER_HOST = "127.0.0.1"
SERVER_PORT = "8000"
