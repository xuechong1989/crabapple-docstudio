# -*- coding: utf-8 -*-
# xuechong 2026-09-26 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# 日志同步进入内存环形缓冲：form-in 的收集整理进度页轮询 /api/logs 即可拿到带时间戳的完整日志流
import sys as _sys_for_log
from pathlib import Path

DEBUG_LOG_FILE = Path(__file__).parent.parent / "crabapple-docstudio.log"


def debug_log(msg: str):
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}\n"
    _sys_for_log.stdout.write(line)
    _sys_for_log.stdout.flush()
    try:
        if _sys_for_log.stdout.isatty() or _sys_for_log.platform == 'win32':
            with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        _sys_for_log.stderr.write(f"[日志写入失败] {e}\n")


def log_info(msg: str):
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}\n"
    _sys_for_log.stdout.write(line)
    _sys_for_log.stdout.flush()
    try:
        if _sys_for_log.stdout.isatty() or _sys_for_log.platform == 'win32':
            with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        _sys_for_log.stderr.write(f"[日志写入失败] {e}\n")
    _append_ring_buffer("INFO", msg)


# xuechong 2026-09-26 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# 把日志同步追加进内存环形缓冲（/api/logs 的数据源）。不复用异步的 add_log：它内部会回头调
# log_info，两边互相调用会一直递归；也不做 WebSocket 广播，进度页走轮询
def _append_ring_buffer(level: str, msg: str):
    # 延迟导入：ws_service 顶层 import 了本模块的 log_info，函数内导入避免循环依赖
    try:
        from backend.services.ws_service import log_manager
        from datetime import datetime
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": msg,
            "details": {},
        }
        log_manager.append_sync(entry)
    except Exception:
        # 环形缓冲只是展示通道，失败不影响日志文件写入主流程
        pass


def setup_utf8_encoding():
    import sys
    if sys.platform == 'win32':
        import os
        os.system('chcp 65001 >nul 2>&1')
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except Exception as e:
            sys.stderr.write(f"[编码设置] stdout/stderr UTF-8 设置失败: {e}\n")
