# -*- coding: utf-8 -*-
"""应用全局可变状态 — 通过命名空间对象访问，避免 from-import + global 赋值裂痕

使用方式:
    from backend.services.app_state import state
    state.UPLOAD_DIR = Path("/some/path")   # 赋值
    print(state.UPLOAD_DIR)                 # 读取

state 对象本身从不会被重赋值，所有模块 import 同一个 state 实例。
"""
import time as _time
from pathlib import Path


class _AppState:
    """应用全局状态容器"""
    pass


state = _AppState()

# ---- 启动时间 ----
state._start_time = _time.time()

# ---- 路径（初始 None，由 init_storage_dirs 设置） ----
state.UPLOAD_DIR: Path = None
state.OUTPUT_DIR: Path = None
state.TEMP_DIR: Path = None
# xuechong 2026-07-16 任务状态持久化文件路径
state.TASKS_FILE: Path = None

# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局历史记录和 dual_layer 状态已废弃，统一使用 user_scope.py 的 UserScope

# ---- 模型 ----
state._cleaner = None
state._cleaner_class = None
state._models_warmed_up = False
