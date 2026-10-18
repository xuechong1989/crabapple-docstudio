# -*- coding: utf-8 -*-
"""WebSocket 连接管理、日志推送、目录监控"""
import asyncio
import threading
from datetime import datetime
from typing import Dict, Set, List

from fastapi import WebSocket

from backend.services.logging_service import log_info
from backend.services.path_service import MONITOR_SOURCE_DIR, MONITOR_TARGET_DIR
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {
            "directory": set(),
            "logs": set(),
        }

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        self.active_connections[channel].add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str):
        self.active_connections[channel].discard(websocket)

    async def broadcast(self, message: dict, channel: str):
        dead_connections = set()
        for connection in self.active_connections[channel]:
            try:
                await connection.send_json(message)
            except Exception as e:
                log_info(f"[WebSocket] 广播消息失败: {e}")
                dead_connections.add(connection)
        for conn in dead_connections:
            self.active_connections[channel].discard(conn)


ws_manager = ConnectionManager()


class LogManager:
    def __init__(self, max_logs: int = 500):
        self.logs: List[dict] = []
        self.max_logs = max_logs
        # xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
        # 日志自增序号：时间戳只有毫秒精度，同一毫秒内的连续日志（如逐张保存N/M）时间戳完全相同，
        # form-in八步页按时间戳做增量水位线会把同戳的第二行当重复丢弃——序号保证同毫秒行也可区分
        self._seq = 0

    def next_seq(self) -> int:
        with _log_lock:
            self._seq += 1
            return self._seq

    async def add_log(self, level: str, message: str, details: dict = None):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "details": details or {},
            "seq": log_manager.next_seq()
        }
        self.logs.append(log_entry)
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]
        await ws_manager.broadcast(log_entry, "logs")
        log_info(f"[{level}] {message}")

    def get_recent_logs(self, count: int = 100) -> List[dict]:
        return self.logs[-count:]

    # xuechong 2026-09-26 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 同步上下文追加日志：只入环形缓冲并截断，不广播也不回写日志文件。
    # add_log 是异步入口且内部会调 log_info，log_info 的同步追加必须走本方法，两边互相调用会一直递归
    def append_sync(self, entry: dict):
        with _log_lock:
            self._seq += 1
            entry["seq"] = self._seq
            self.logs.append(entry)
            if len(self.logs) > self.max_logs:
                self.logs = self.logs[-self.max_logs:]


log_manager = LogManager()
_log_lock = threading.Lock()


def sync_log(level: str, message: str, details: dict = None):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
        "details": details or {}
    }
    with _log_lock:
        log_manager._seq += 1
        log_entry["seq"] = log_manager._seq
        log_manager.logs.append(log_entry)
        if len(log_manager.logs) > log_manager.max_logs:
            log_manager.logs = log_manager.logs[-log_manager.max_logs:]
    log_info(f"[{level}] {message}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast(log_entry, "logs"), loop)
    except RuntimeError:
        pass


class DirectoryWatcher(FileSystemEventHandler):
    def __init__(self):
        self.observer = None
        self._loop = None

    def start(self, loop):
        self._loop = loop
        if self.observer:
            self.observer.stop()
        MONITOR_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        MONITOR_TARGET_DIR.mkdir(parents=True, exist_ok=True)
        self.observer = Observer()
        self.observer.schedule(self, str(MONITOR_SOURCE_DIR), recursive=True)
        self.observer.start()
        log_info(f"  目录监控已启动: {MONITOR_SOURCE_DIR}")

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()

    def _notify_change(self, event_type: str, path: str):
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast({
                    "type": event_type,
                    "path": path,
                    "timestamp": datetime.now().isoformat()
                }, "directory"),
                self._loop
            )

    def on_created(self, event):
        self._notify_change("created", event.src_path)

    def on_deleted(self, event):
        self._notify_change("deleted", event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._notify_change("modified", event.src_path)

    def on_moved(self, event):
        self._notify_change("moved", event.dest_path)


dir_watcher = DirectoryWatcher()
