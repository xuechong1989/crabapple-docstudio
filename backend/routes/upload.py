# -*- coding: utf-8 -*-
# xuechong 2026-07-18 研发BUG-0009-图档扫描-用户隔离机制问题 upload API（重构版）
"""upload API — 所有任务和文件操作通过用户 scope 隔离"""
import asyncio, shutil, uuid
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from backend.services.logging_service import log_info
from backend.services.image_utils import is_image_file, SUPPORTED_EXTENSIONS
from backend.services.user_scope import get_user_scope

from backend import config as _cfg
from backend.routes.tasks import _check_upload_size, _read_upload_file

router = APIRouter(tags=["upload"])


# xuechong 2026-07-18 从请求获取当前用户的 scope
def _get_scope(request: Request):
    """从请求获取当前用户的 scope，无 token 则 401"""
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return get_user_scope(username)


@router.post("/api/upload-folder")
# xuechong 2026-07-18 上传文件夹（用户隔离）
# xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# task_id 参数支持追加模式（前端分批上传复用同一任务）
async def upload_folder(request: Request, background_tasks: BackgroundTasks, task_id: str = ""):
# xuechong 2026-07-18 上传文件夹（用户隔离）
    """上传文件夹（用户隔离）"""
    _check_upload_size(request.headers.get("content-length"))
    form = await request.form(max_files=100000000, max_fields=100000000)
    files = form.getlist("files")
    paths = form.getlist("paths")
    if not files or not paths:
        raise HTTPException(status_code=400, detail="请选择要上传的文件夹")
    if len(files) != len(paths):
        raise HTTPException(status_code=400, detail="文件和路径数量不匹配")

    # xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
    # 接收前端预检上报的不可读文件清单：浏览器读不到的文件（被移动/删除/占用/路径超长）
    # 无法到达后端，此处把前端点名的文件路径写入服务端日志，保证"前后端双侧都有具体文件路径"可查
    skipped_report = form.get("skipped_unreadable")
    if skipped_report:
        try:
            import json as _json
            skipped_list = _json.loads(str(skipped_report))
            detail = "; ".join(str(item.get("path", item if isinstance(item, str) else "")) for item in skipped_list)
            log_info(f"[上传预检上报] 浏览器端跳过 {len(skipped_list)} 个无法读取的文件（本次实传 {len(files)} 个）: {detail}")
        except Exception as _e:
            log_info(f"[上传预检上报] 解析跳过清单失败: {_e}; 原始内容前500字符: {str(skipped_report)[:500]}")

    scope = _get_scope(request)
    username = scope.username
    # xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
    # 支持追加模式（前端分批上传复用同一任务）：task_id 传入且任务存在 → 文件并入该任务；否则新建任务
    appending = bool(task_id) and task_id in scope.upload_tasks
    if not appending:
        task_id = str(uuid.uuid4())[:8]
    # xuechong 2026-07-18 使用用户 scope 的上传目录
    upload_dir = scope.upload_dir / task_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    log_info(f"[上传任务{task_id}] {'追加' if appending else '开始'}上传，共 {len(files)} 个文件")

    saved_files = []
    # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
    # 记录失败文件清单，返回给前端明确告知哪些文件未上传成功（原实现仅日志，用户不知道丢了哪张）
    failed_files = []
    folder_name = ""
    for file, rel_path in zip(files, paths):
        if not file.filename:
            continue
        rel_path_str = rel_path if isinstance(rel_path, str) else str(rel_path)
        rel_path_str = rel_path_str.replace('\\', '/')
        if not folder_name:
            parts = Path(rel_path_str).parts
            if parts:
                folder_name = parts[0]
        file_dest = (upload_dir / rel_path_str).resolve()
        try:
            file_dest.relative_to(upload_dir.resolve())
        except ValueError:
            log_info(f"[上传任务{task_id}] 路径穿越拒绝: {rel_path_str}")
            failed_files.append(f"{rel_path_str}（路径非法被拒绝）")
            continue
        file_dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = await _read_upload_file(file, _cfg.MAX_UPLOAD_SIZE_BYTES)
            with open(file_dest, "wb") as f:
                f.write(content)
            if is_image_file(file.filename):
                saved_files.append(file_dest)
                # xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
                # 逐文件保存日志（带 N/M 计数）：form-in智能收集整理页的过程信息区按这些日志实时展示
                # 逐文件进度与总进度，普通直接使用模式只是日志文件多几行，功能行为不变
                log_info(f"[上传任务{task_id}] 已保存 {len(saved_files)}/{len(files)}：{rel_path_str}")
            else:
                failed_files.append(f"{file.filename}（不支持的文件类型）")
        except Exception as e:
            log_info(f"[上传任务{task_id}] 保存文件失败: {rel_path_str} - {str(e)}")
            failed_files.append(f"{rel_path_str}（{str(e)}）")

    # xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 上传收尾日志：成功/失败计数一眼可查（失败清单已逐条记录在上面的保存失败日志里）
    if failed_files:
        log_info(f"[上传任务{task_id}] 接收完成：成功 {len(saved_files)} 个，失败 {len(failed_files)} 个")
    else:
        log_info(f"[上传任务{task_id}] 接收完成：{len(saved_files)} 个文件全部成功")

    if not saved_files:
        # xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：rmtree 包装到线程池
        if not appending:
            await asyncio.to_thread(shutil.rmtree, upload_dir, True)
        raise HTTPException(status_code=400, detail="没有找到支持的图片文件")

    saved_files.sort(key=lambda x: str(x).lower())

    # xuechong 2026-07-18 写入用户 scope 的任务字典
    with scope._lock:
        if appending:
            # xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
            # 追加模式：累加文件数并持久化，不重建任务、不重复写历史
            prev = scope.upload_tasks[task_id]
            prev["total_files"] = prev.get("total_files", 0) + len(saved_files)
            prev["message"] = f"已上传 {prev['total_files']} 个文件，等待处理"
            prev["status"] = "uploaded"
        else:
            scope.upload_tasks[task_id] = {
                "task_id": task_id,
                "folder_name": folder_name or task_id,
                "status": "uploaded",
                "username": username,
                # xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
                # 任务来源标记（form-in演示链代理上传带X-Task-Source头）：嵌入页会话过滤据此
                # 放行演示链任务——八步页先上传、嵌入页后打开时刚传的任务不被会话起点误滤
                "source": request.headers.get('x-task-source', ''),
                "progress": 0,
                "total_files": len(saved_files),
                "processed_files": 0,
                "current_file": "",
                "message": f"已上传 {len(saved_files)} 个文件，等待处理",
                "created_at": datetime.now().isoformat(),
                "completed_at": None,
                "upload_dir": str(upload_dir),
                "output_dir": None,
                "can_download": False
            }
    # xuechong 2026-07-18 持久化任务状态
    scope.save_tasks()

    if appending:
        return {"task_id": task_id, "folder_name": scope.upload_tasks[task_id].get("folder_name", task_id),
                "file_count": scope.upload_tasks[task_id]["total_files"], "appended": len(saved_files),
                "message": f"已追加 {len(saved_files)} 个文件"}

    # xuechong 2026-07-18 写入用户 scope 的上传历史
    scope.upload_history.insert(0, {
        "task_id": task_id, "folder_name": folder_name or task_id,
        "file_count": len(saved_files), "status": "uploaded",
        "total_files": len(saved_files), "processed_files": 0,
        # xuechong 2026-10-06 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
        # 上传历史同任务打来源标记（嵌入页会话过滤据此放行演示链上传记录，与任务同款豁免）
        "source": request.headers.get('x-task-source', ''),
        "created_at": datetime.now().isoformat(), "completed_at": None,
        "last_message": f"已上传 {len(saved_files)} 个文件，等待处理",
        "has_pdf": False, "username": username
    })
    try:
        scope.save_upload_history()
    except Exception as e:
        log_info(f"[上传历史] 保存失败: {e}")

    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-009 上传完成后预解码缓存（后台执行）
    from backend.services.image_cache import predecode_images
    background_tasks.add_task(predecode_images, saved_files, task_id)

    # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
    # 部分文件失败时在响应中明确告知失败清单（前端 toast 已透传 detail/message）
    _fail_note = ""
    if failed_files:
        _fail_note = f"；另有 {len(failed_files)} 个文件未上传成功：{'; '.join(failed_files[:10])}" + ("等" if len(failed_files) > 10 else "")
    return {"task_id": task_id, "folder_name": folder_name or task_id,
            "file_count": len(saved_files), "message": f"已上传 {len(saved_files)} 个文件{_fail_note}",
            "failed_files": failed_files}


# zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
@router.post("/api/upload-diagnostic")
# 免鉴权接收前端上传失败诊断包（精确路径已加入 auth 中间件 _PUBLIC_PATHS）：
# 要抓的 401 死循环场景下带无效凭证的请求到不了业务层，上报通道必须免鉴权才能送达；
# 只写运行日志不落库，请求体限长 + 控制字符清洗防日志注入
async def upload_diagnostic(request: Request):
    """接收前端上传失败诊断包并写入运行日志"""
    import json as _json
    import re as _re_clean
    try:
        raw = await request.body()
        # 诊断包只含失败清单与环境信息，16KB 足够；超限截断防止恶意/异常请求刷日志
        if len(raw) > 16 * 1024:
            raw = raw[:16 * 1024]
        text = raw.decode('utf-8', errors='replace')
        try:
            data = _json.loads(text)
            build = data.get('build') or {}
            failed = data.get('failed') or []
            # 单行摘要：每个失败文件压缩为 路径|HTTP状态码|原因，最多取前 10 条防刷屏
            failed_items = []
            for f in failed[:10]:
                if isinstance(f, dict):
                    failed_items.append(f"{f.get('path', '?')}|HTTP {f.get('status', 0)}|{f.get('detail') or f.get('error', '')}")
                else:
                    failed_items.append(str(f))
            summary = (
                f"事件={data.get('event', '?')} 用户={data.get('user', '?')}"
                f" 前端版本={build.get('version', '?')}/构建时间戳={build.get('buildTime', '?')}"
                f" 页面运行={data.get('page_uptime_sec', '?')}s 文件总数={data.get('total', '?')}"
                f" 已传={data.get('uploaded', '?')} 任务={data.get('task_id', '')}"
                f" UA={data.get('user_agent', '')}"
                f" 失败清单={'；'.join(failed_items)}"
            )
        except Exception:
            # JSON 解析失败按原文记录（前500字符），保证现场证据不丢
            summary = f"非JSON负载: {text[:500]}"
        # 清洗控制字符/换行保证单行，防止伪造多行日志
        summary = _re_clean.sub(r'[\x00-\x1f\x7f]', ' ', summary)
        log_info(f"[前端诊断上报] {summary}")
        return {"success": True}
    except Exception as e:
        log_info(f"[前端诊断上报] 接收失败: {e}")
        return {"success": False}


@router.get("/api/upload-task/{task_id}")
# xuechong 2026-07-18 获取上传任务状态（用户隔离）
async def get_upload_task(task_id: str, request: Request):
# xuechong 2026-07-18 获取上传任务状态（用户隔离）
    """获取上传任务状态（用户隔离）"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/api/upload-file-tree/{task_id}")
# xuechong 2026-07-18 获取上传文件树（用户隔离）
async def get_upload_file_tree(task_id: str, request: Request):
# xuechong 2026-07-18 获取上传文件树（用户隔离）
    """获取上传文件树（用户隔离）"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])

    def build_tree(current_dir: Path, root_dir: Path):
        node = {"name": current_dir.name or "root", "type": "directory", "children": [],
                "path": str(current_dir.relative_to(root_dir))}
        if str(current_dir.relative_to(root_dir)) == ".":
            node["path"] = ""
        try:
            items = sorted(current_dir.iterdir(), key=lambda x: (not x.is_dir(), str(x).lower()))
        # xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
        # 目录缺失（数据目录改名/文件被移除）时返回空子节点而非500，前端展示空树不报错
        except (PermissionError, FileNotFoundError, OSError):
            return node
        for item in items:
            if item.is_dir():
                if not item.name.startswith('_'):
                    node["children"].append(build_tree(item, root_dir))
            elif item.suffix.lower() in SUPPORTED_EXTENSIONS:
                node["children"].append(
                    {"name": item.name, "type": "file", "path": str(item.relative_to(root_dir))})
        return node

    tree = build_tree(upload_dir, upload_dir)
    return {"task_id": task_id, "folder_name": task.get("folder_name", task_id), "tree": tree}


@router.get("/api/active-tasks")
# xuechong 2026-07-18 当前用户的活跃任务（用户隔离）
async def get_active_tasks(request: Request):
# xuechong 2026-07-18 当前用户的活跃任务（用户隔离）
    """当前用户的活跃任务（用户隔离）"""
    scope = _get_scope(request)
    tasks = []
    for task_id, task in scope.upload_tasks.items():
        tasks.append({
            "task_id": task_id,
            "folder_name": task.get("folder_name", task_id),
            "status": task.get("status", "unknown"),
            "progress": task.get("progress", 0),
            "message": task.get("message", ""),
            "total_files": task.get("total_files", 0),
            "processed_files": task.get("processed_files", 0),
            "can_download": task.get("can_download", False),
            "clean_status": task.get("clean_status", "idle"),
            # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
            # 未完成任务弹框需要展示修图断点进度
            "clean_progress": task.get("clean_progress", 0),
            "clean_processed_files": task.get("clean_processed_files", 0),
            "clean_message": task.get("clean_message", ""),
            "created_at": task.get("created_at", ""),
            "selected_path": task.get("selected_path", ""),
            # xuechong 2026-09-30 研发需求-0164 任务来源标记（form-in演示链），嵌入页会话过滤用
            "source": task.get("source", ""),
        })
    return {"active_tasks": tasks}


@router.delete("/api/upload-task/{task_id}/file")
# xuechong 2026-07-18 删除上传任务中的文件（用户隔离）
async def delete_upload_file(task_id: str, request: Request, file_path: str = ""):
# xuechong 2026-07-18 删除上传任务中的文件（用户隔离）
    """删除上传任务中的文件（用户隔离）"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not file_path:
        raise HTTPException(status_code=400, detail="未指定要删除的文件路径")
    upload_dir = Path(task["upload_dir"]).resolve()
    target = (upload_dir / file_path).resolve()
    try:
        target.relative_to(upload_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问指定路径")
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    if target.is_dir():
        await asyncio.to_thread(shutil.rmtree, target, True)
    else:
        await asyncio.to_thread(target.unlink)
    file_count = sum(1 for f in upload_dir.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS)
    task["total_files"] = file_count
    return {"message": "删除成功", "task_id": task_id, "total_files": file_count}


# ---- 上传历史（用户 scope） ----

@router.get("/api/upload-history")
# xuechong 2026-07-18 获取当前用户的上传历史（用户隔离）
async def get_upload_history(request: Request):
# xuechong 2026-07-18 获取当前用户的上传历史（用户隔离）
    """获取当前用户的上传历史（用户隔离）"""
    scope = _get_scope(request)
    # xuechong 2026-10-06 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 旧记录补齐 source 字段（form-in 演示链标记，嵌入页会话过滤据此放行演示链上传记录）
    scope.heal_history_sources()
    return {"history": scope.upload_history, "total": len(scope.upload_history)}


# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 task_id 格式校验
import re as _re

def _validate_task_id(task_id: str):
    """校验 task_id 格式，防止路径穿越"""
    if not _re.match(r'^[a-zA-Z0-9_-]+$', task_id):
        raise HTTPException(status_code=400, detail="无效的任务ID")


@router.delete("/api/upload-history/{task_id}")
# xuechong 2026-07-18 删除上传历史记录
async def delete_upload_history_item(task_id: str, request: Request):
# xuechong 2026-07-18 删除上传历史记录
    _validate_task_id(task_id)
    scope = _get_scope(request)
    idx = next((i for i, r in enumerate(scope.upload_history) if r.get("task_id") == task_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    # xuechong 2026-07-18 删除用户 scope 目录中的文件
    tu = scope.upload_dir / task_id
    to = scope.output_dir / task_id
    if tu.exists():
        await asyncio.to_thread(shutil.rmtree, tu, True)
    if to.exists():
        await asyncio.to_thread(shutil.rmtree, to, True)
    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-009 预解码缓存失效
    from backend.services.image_cache import invalidate_user_cache
    invalidate_user_cache(str(tu))
    scope.upload_tasks.pop(task_id, None)
    del scope.upload_history[idx]
    scope.save_upload_history()
    scope.save_tasks()
    return {"message": "记录已删除", "task_id": task_id}


@router.delete("/api/upload-history")
# xuechong 2026-07-18 清空上传历史
async def clear_upload_history(request: Request):
# xuechong 2026-07-18 清空上传历史
    scope = _get_scope(request)
    scope.upload_history.clear()
    scope.save_upload_history()
    return {"message": "上传历史已清空"}
