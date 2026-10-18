# -*- coding: utf-8 -*-
# xuechong 2026-07-18 研发BUG-0009-图档扫描-用户隔离机制问题 系统/健康检查/管理员/日志 API（重构版）
"""系统/健康检查/管理员/日志 API — 任务统计从所有用户 scope 聚合"""
import os, signal, time as _time, asyncio, shutil
from fastapi import APIRouter, Request, HTTPException
from backend.services.app_state import state
from backend.services.ws_service import log_manager
from backend.services.user_scope import get_all_usernames, get_user_scope

router = APIRouter(tags=["system"])


# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 管理员角色校验
def _require_admin(request: Request):
    """校验当前用户是否为管理员角色，非管理员拒绝访问"""
    role = getattr(request.state, 'role', None)
    if role != 'admin':
        raise HTTPException(status_code=403, detail="需要管理员权限")


# xuechong 2026-07-18 从所有用户 scope 聚合任务列表
def _aggregate_tasks():
    """从所有用户 scope 聚合任务列表"""
    all_tasks = {}
    for username in get_all_usernames():
        scope = get_user_scope(username)
        all_tasks.update(scope.upload_tasks)
    return all_tasks


@router.get("/api")
async def api_root():
    return {"message": "海棠文档工坊 API 服务正在运行", "version": "3.4.00"}


@router.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": _time.time()}


@router.get("/api/admin/status")
async def get_system_status(request: Request):
    _require_admin(request)
    uptime_seconds = int(_time.time() - state._start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    # xuechong 2026-07-18 从所有用户 scope 聚合任务统计
    all_tasks = _aggregate_tasks()
    total_tasks = len(all_tasks)
    processing_tasks = len([t for t in all_tasks.values() if t.get("status") == "processing"])
    completed_tasks = len([t for t in all_tasks.values() if t.get("status") == "completed"])
    failed_tasks = len([t for t in all_tasks.values() if t.get("status") in ["failed", "cancelled"]])

    total_files = sum(t.get("total_files", 0) for t in all_tasks.values())
    processed_files = sum(t.get("processed_files", 0) for t in all_tasks.values())

    def get_dir_size(path):
        total = 0
        if path and path.exists():
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        return total

    upload_size = get_dir_size(state.UPLOAD_DIR)
    output_size = get_dir_size(state.OUTPUT_DIR)

    return {
        "status": "running",
        "uptime": f"{hours}小时 {minutes}分钟 {seconds}秒",
        "uptime_seconds": uptime_seconds,
        "tasks": {
            "total": total_tasks,
            "processing": processing_tasks,
            "completed": completed_tasks,
            "failed": failed_tasks
        },
        "files": {
            "total": total_files,
            "processed": processed_files
        },
        "storage": {
            "uploads_mb": round(upload_size / 1024 / 1024, 2),
            "outputs_mb": round(output_size / 1024 / 1024, 2),
            "total_mb": round((upload_size + output_size) / 1024 / 1024, 2)
        },
        "model_loaded": state._cleaner is not None
    }


@router.post("/api/admin/clear-all")
# xuechong 2026-07-18 清理所有用户的任务
async def clear_all_tasks(request: Request):
    _require_admin(request)
    # xuechong 2026-07-18 从所有用户 scope 清理任务
    cleared_count = 0
    for username in get_all_usernames():
        scope = get_user_scope(username)
        for task_id in list(scope.upload_tasks.keys()):
            task = scope.upload_tasks[task_id]
            if task.get("status") in ["pending", "processing"]:
                scope.tasks_cancel_flags[task_id] = True
                task["status"] = "cancelled"
            # 删除文件（xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：rmtree 包装到线程池）
            if scope.upload_dir:
                await asyncio.to_thread(shutil.rmtree, scope.upload_dir / task_id, True)
            if scope.output_dir:
                await asyncio.to_thread(shutil.rmtree, scope.output_dir / task_id, True)
            cleared_count += 1
        scope.upload_tasks.clear()
        scope.tasks_cancel_flags.clear()
        scope.save_tasks()

    return {"message": f"已清理 {cleared_count} 个任务", "cleared": cleared_count}


@router.post("/api/admin/clear-completed")
# xuechong 2026-07-18 清理所有用户的已完成任务
async def clear_completed_tasks(request: Request):
    _require_admin(request)
    # xuechong 2026-07-18 从所有用户 scope 清理已完成任务
    cleared = 0
    for username in get_all_usernames():
        scope = get_user_scope(username)
        to_remove = []
        for task_id, task in scope.upload_tasks.items():
            if task.get("status") in ["completed", "failed", "cancelled"]:
                to_remove.append(task_id)
        for task_id in to_remove:
            del scope.upload_tasks[task_id]
            scope.tasks_cancel_flags.pop(task_id, None)
            cleared += 1
        scope.save_tasks()

    return {"message": f"已清理 {cleared} 个任务", "cleared": cleared}


@router.post("/api/admin/shutdown")
# xuechong 2026-07-18 关闭服务器前取消所有用户的任务
async def shutdown_server(request: Request):
    _require_admin(request)
    # xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题
    # 修复逻辑错误：应遍历 upload_tasks 设置取消标志，而非遍历 tasks_cancel_flags 自身
    for username in get_all_usernames():
        scope = get_user_scope(username)
        for task_id, task in scope.upload_tasks.items():
            if task.get("status") in ("pending", "processing", "uploaded"):
                scope.tasks_cancel_flags[task_id] = True

    def shutdown():
        _time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    import threading
    threading.Thread(target=shutdown, daemon=True).start()
    return {"message": "服务器正在关闭..."}


@router.get("/api/logs")
async def get_logs(count: int = 100):
    return log_manager.get_recent_logs(count)
