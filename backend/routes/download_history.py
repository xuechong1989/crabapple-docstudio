# -*- coding: utf-8 -*-
# xuechong 2026-07-18 研发BUG-0009-图档扫描-用户隔离机制问题 下载历史与预览 API（重构版）
"""下载历史与预览 API — 用户隔离版"""
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Response, HTTPException, Request
from fastapi.responses import FileResponse
from backend.services.logging_service import log_info
from backend.services.user_scope import get_user_scope
from backend.services.path_service import APP_ROOT

router = APIRouter(tags=["download-history"])


# xuechong 2026-07-18 从请求获取当前用户的 scope
def _get_scope(request: Request):
# xuechong 2026-07-18 从请求获取当前用户的 scope
    """从请求获取当前用户的 scope，无 token 则 401"""
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return get_user_scope(username)


# xuechong 2026-06-30 获取当前用户的筛选后历史列表（与 /api/download-history 保持一致）
def _get_filtered_history(request: Request):
    """获取当前用户的筛选后历史列表（用户隔离，从 scope 读取）"""
    # xuechong 2026-07-16 用户隔离：从 scope 读取
    scope = _get_scope(request)
    return scope.download_history


# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题
# 跨所有 scope 查找 task（仅限无 token 场景的兼容回退，优先搜索当前用户）
def _find_task_any_scope(task_id: str, req: Request = None):
    """在所有用户 scope 中查找 task（优先当前用户，回退遍历所有 scope 仅限无token场景）"""
    from backend.services.user_scope import get_all_usernames
    # 优先从当前用户 scope 获取
    try:
        scope = _get_scope(req)
        task = scope.upload_tasks.get(task_id)
        if task:
            return task, scope
        # xuechong 2026-07-21 研发BUG-0009 有token但任务不属于当前用户，拒绝访问
        return None, None
    except HTTPException:
        pass
    # 回退：无token场景（如图片预览），遍历所有用户 scope
    for uname in get_all_usernames():
        s = get_user_scope(uname)
        if task_id in s.upload_tasks:
            return s.upload_tasks[task_id], s
    return None, None


@router.get("/api/download-result/{task_id}")
async def download_upload_result(task_id: str, request: Request = None):
    """下载上传任务的处理结果（跨scope搜索，支持无token的图片请求）"""
    task, scope = _find_task_any_scope(task_id, request)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")
    merged_pdf = task.get("merged_pdf")
    if merged_pdf:
        merged_pdf_path = Path(merged_pdf)
        if merged_pdf_path.exists():
            ascii_filename = f"{task_id}.pdf"
            encoded_filename = quote(merged_pdf_path.name, safe='')
            return FileResponse(path=str(merged_pdf_path), media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"})
    raise HTTPException(status_code=404, detail="输出文件不存在")


@router.get("/api/download-user-manual")
async def download_user_manual():
    """下载用户操作手册"""
    manual_filename = "海棠文档工坊_用户操作手册_V2.3.00.docx"
    manual_path = APP_ROOT / ".claude" / "docs" / manual_filename
    if not manual_path.exists():
        raise HTTPException(status_code=404, detail="用户操作手册文件不存在")
    ascii_filename = "user_manual_v2.3.00.docx"
    encoded_filename = quote(manual_filename, safe='')
    return FileResponse(path=str(manual_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'})


# ---- 下载历史 CRUD（用户隔离） ----

@router.get("/api/download-history")
# xuechong 2026-07-18 获取当前用户的下载历史（用户隔离）
async def get_download_history(request: Request, response: Response):
# xuechong 2026-07-18 获取当前用户的下载历史（用户隔离）
    """获取当前用户的下载历史（用户隔离，从 scope 读取）"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    # xuechong 2026-07-16 用户隔离：从 scope 读取而非全局 state
    scope = _get_scope(request)
    # xuechong 2026-10-06 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 旧记录补齐 source 字段（form-in 演示链标记，嵌入页会话过滤据它放行演示链转换记录）
    scope.heal_history_sources()
    return {"history": scope.download_history, "total": len(scope.download_history)}


@router.get("/api/download-history-item/{index}")
# xuechong 2026-07-18 按索引下载历史PDF
async def download_history_item(index: int, request: Request):
# xuechong 2026-07-18 按索引下载历史PDF
    """按索引下载历史 PDF"""
    # xuechong 2026-06-30 修复：使用与列表相同的数据源和筛选逻辑
    filtered = _get_filtered_history(request)
    if index < 0 or index >= len(filtered):
        raise HTTPException(status_code=404, detail="下载记录不存在")
    item = filtered[index]
    item["download_count"] = item.get("download_count", 0) + 1
    # xuechong 2026-07-16 保存到用户 scope 而非全局
    scope = _get_scope(request)
    scope.save_download_history()

    pdf_path = item.get("pdf_path", "")
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF路径不存在")
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="PDF文件不存在或已被删除")

    first_image_name = item.get("first_image_name", "")
    download_filename = f"{first_image_name}.pdf" if first_image_name else f"{item.get('folder_name', 'download')}.pdf"
    encoded = quote(download_filename, safe='')
    return FileResponse(path=str(pdf_file), media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=\"download_{index}.pdf\"; filename*=UTF-8''{encoded}"})


@router.delete("/api/download-history-item/{index}")
# xuechong 2026-07-18 删除下载历史记录
async def delete_history_item(index: int, request: Request):
# xuechong 2026-07-18 删除下载历史记录
    """删除下载历史记录"""
    # xuechong 2026-06-30 修复：使用与列表相同的数据源和筛选逻辑
    filtered = _get_filtered_history(request)
    if index < 0 or index >= len(filtered):
        raise HTTPException(status_code=404, detail="下载记录不存在")
    item = filtered[index]
    # xuechong 2026-07-16 从 scope 中删除而非全局 state
    scope = _get_scope(request)
    scope.download_history.remove(item)
    scope.save_download_history()
    log_info(f"[下载历史] user={_get_scope(request).username} 已删除: {item.get('folder_name', '未知')}")
    return {"success": True, "message": f"已删除记录: {item.get('folder_name', '未知')}"}


@router.put("/api/download-history-item/{index}/mark-edited")
# xuechong 2026-07-18 标记为已编辑
async def mark_history_item_edited(index: int, request: Request):
# xuechong 2026-07-18 标记为已编辑
    """标记为已编辑"""
    # xuechong 2026-06-30 修复：使用与列表相同的数据源和筛选逻辑
    filtered = _get_filtered_history(request)
    if index < 0 or index >= len(filtered):
        raise HTTPException(status_code=404, detail="下载记录不存在")
    item = filtered[index]
    item["edited"] = True
    # xuechong 2026-07-16 保存到用户 scope 而非全局
    scope = _get_scope(request)
    scope.save_download_history()
    return {"success": True, "message": "已标记为编辑状态"}


@router.put("/api/download-history-item/{index}/edit-downloaded")
# xuechong 2026-07-18 标记编辑后下载（用户隔离）
async def mark_history_item_edit_downloaded(index: int, request: Request):
# xuechong 2026-07-18 标记编辑后下载（用户隔离）
    """标记编辑后下载（用户隔离）"""
    # xuechong 2026-06-30 修复：使用与列表相同的数据源和筛选逻辑
    filtered = _get_filtered_history(request)
    if index < 0 or index >= len(filtered):
        raise HTTPException(status_code=404, detail="下载记录不存在")
    item = filtered[index]
    item["edited"] = True
    item["edit_download_count"] = item.get("edit_download_count", 0) + 1
    # xuechong 2026-07-16 保存到用户 scope 而非全局
    scope = _get_scope(request)
    scope.save_download_history()
    return {"success": True, "message": "已记录编辑后下载"}


@router.put("/api/download-history-item/{index}/rename")
# xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# form-in智能收集整理步骤4转换记录重命名：只改记录显示名（folder_name/first_image_name），
# 下载文件名由 first_image_name 派生随之变化，物理文件与 pdf_path 不动
async def rename_history_item(index: int, request: Request, new_name: str = ""):
# xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    """重命名下载历史记录（只改显示名与下载文件名，物理文件不动）"""
    filtered = _get_filtered_history(request)
    if index < 0 or index >= len(filtered):
        raise HTTPException(status_code=404, detail="下载记录不存在")
    safe_name = (new_name or "").strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="新文件名不能为空")
    for ch in '/\\<>:"|?*':
        if ch in safe_name:
            raise HTTPException(status_code=400, detail="新文件名含有非法字符")
    old_name = filtered[index].get("folder_name", "未知")
    filtered[index]["folder_name"] = safe_name
    filtered[index]["first_image_name"] = safe_name
    scope = _get_scope(request)
    scope.save_download_history()
    log_info(f"[下载历史] user={scope.username} 已重命名: {old_name} -> {safe_name}")
    return {"success": True, "message": f"已重命名: {old_name} -> {safe_name}"}


# xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
# 转换记录弹框批量下载：按索引列表把多条记录的PDF打成一个ZIP一次下载。
# ZIP条目名取记录显示名（重命名后即新名字），同条目重名依次加(2)(3)序号；
# 某条PDF文件缺失只跳过该条不中断整批；每条有效记录下载次数加1（与单条下载计次一致）；
# ZIP落盘到用户输出目录流式打包（不整块占内存），响应发送完由后台任务删除临时文件
@router.get("/api/download-history-item-batch")
# xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
async def download_history_item_batch(indices: str = "", request: Request = None):
    """批量下载下载历史中的多条PDF（ZIP打包，用户隔离）"""
    import asyncio
    import zipfile
    from datetime import datetime
    from starlette.background import BackgroundTask

    scope = _get_scope(request)
    filtered = scope.download_history

    # xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
    # 解析 indices：逗号分隔、去空白、去重、保持传入顺序
    seen_indices = set()
    ordered_indices = []
    for raw in (indices or "").split(','):
        part = raw.strip()
        if part and part not in seen_indices:
            seen_indices.add(part)
            ordered_indices.append(part)
    if not ordered_indices:
        raise HTTPException(status_code=400, detail="未指定要下载的记录")

    # xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
    def _pack_batch_zip():
        """同步打包线程：过滤有效记录、计次、写ZIP，返回(请求条数, 成功条数, ZIP路径, 无效索引列表)"""
        success_entries = []
        used_arc_names = set()
        invalid_parts = []
        # 列表浅拷贝做快照：同一用户并发删除记录时原列表会缩短，按快照取值不会越界
        snapshot = list(filtered)
        for part in ordered_indices:
            # int直接转换并接住异常：isdigit预检挡不住"--5"“²”这类也能通过预检、int却抛错的输入
            try:
                index = int(part)
            except ValueError:
                invalid_parts.append(part)
                continue
            if index < 0 or index >= len(snapshot):
                invalid_parts.append(part)
                continue
            item = snapshot[index]
            pdf_path = item.get("pdf_path", "")
            if not pdf_path or not Path(pdf_path).exists():
                invalid_parts.append(part)
                continue
            # ZIP条目名 = 记录显示名.pdf（与单条下载的文件名同源，重命名后即新名字）
            display_name = item.get("first_image_name") or item.get("folder_name") or "PDF文件"
            arc_name = f"{display_name}.pdf"
            if arc_name in used_arc_names:
                # 同名条目从(2)起加序号，保证ZIP内不互相覆盖
                seq = 2
                while f"{display_name}({seq}).pdf" in used_arc_names:
                    seq += 1
                arc_name = f"{display_name}({seq}).pdf"
            used_arc_names.add(arc_name)
            success_entries.append((arc_name, Path(pdf_path)))
            # 与单条下载一致：每下载一条计数加1（循环内只改内存，ZIP写盘成功后才统一写盘）
            item["download_count"] = item.get("download_count", 0) + 1
        if not success_entries:
            return len(ordered_indices), 0, None, invalid_parts
        zip_path = scope.output_dir / f"batch_download_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.zip"
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for arc_name, pdf_file in success_entries:
                    zf.write(str(pdf_file), arcname=arc_name)
        except Exception as e:
            # 打包失败（磁盘满/PDF被别的程序占用等）：删掉半成品ZIP、计次不落盘，异常抛给调用方转提示
            try:
                zip_path.unlink(missing_ok=True)
            except Exception:
                pass
            log_info(f"[下载历史] 批量打包ZIP失败: 错误={e}")
            raise
        # ZIP写盘成功后计次统一落盘一次：用户拿到文件与计次保持一致
        scope.save_download_history()
        return len(ordered_indices), len(success_entries), zip_path, invalid_parts

    # xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
    # 打包线程里的异常（半成品ZIP已在线程内清理并记日志）转成用户可读提示
    try:
        requested, succeeded, zip_path, invalid_parts = await asyncio.to_thread(_pack_batch_zip)
    except Exception:
        raise HTTPException(status_code=500, detail="批量打包失败，请重试")

    if succeeded == 0:
        # 传入索引全部无效时，提示语区分"文件没了"和"索引本身不对"两种原因
        if len(invalid_parts) == len(ordered_indices):
            raise HTTPException(status_code=400, detail="未找到有效的下载记录索引")
        raise HTTPException(status_code=400, detail="所选记录的PDF文件不存在或已被删除")
    if invalid_parts:
        invalid_str = ','.join(invalid_parts)
        log_info(f"[下载历史] 批量下载跳过无效记录索引: {invalid_str}")
    log_info(f"[下载历史] user={scope.username} 批量下载完成: 请求{requested}条, 成功{succeeded}条")

    # xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
    # 响应发送完成后由后台任务删除临时ZIP，不占数据盘
    def _cleanup_batch_zip(path: Path):
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            log_info(f"[下载历史] 清理批量下载临时ZIP失败: {path}, 错误: {e}")

    # xuechong 2026-10-12 研发需求-0178-图档扫描-3.3.05-新增PDF文件重命名与批量下载
    # 下载包名用纯ASCII（pdf-日期---时分秒.zip，如 pdf-2026-10-12---17-49-20.zip）：
    # 部分浏览器与老解压工具对中文包名处理不一，纯英文数字横杠彻底避开乱码；
    # ZIP内的PDF条目名仍用记录显示名（重命名后的新名字），zipfile自带UTF-8标志
    zip_filename = f"pdf-{datetime.now().strftime('%Y-%m-%d---%H-%M-%S')}.zip"
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        background=BackgroundTask(_cleanup_batch_zip, zip_path),
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"'
        }
    )


@router.get("/api/preview-pdf/{task_id}")
async def preview_pdf_result(task_id: str, request: Request = None):
    """预览处理结果 PDF（跨scope搜索，支持无token请求）"""
    task, scope = _find_task_any_scope(task_id, request)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="任务尚未完成")
    merged_pdf = task.get("merged_pdf")
    if merged_pdf:
        pdf_path = Path(merged_pdf)
        if pdf_path.exists():
            return FileResponse(path=str(pdf_path), media_type="application/pdf")
    raise HTTPException(status_code=404, detail="输出文件不存在")


@router.get("/api/preview-history-item/{index}")
async def preview_history_item(index: int, request: Request):
    """预览下载历史中的 PDF"""
    # xuechong 2026-06-30 修复：使用与列表相同的数据源和筛选逻辑
    filtered = _get_filtered_history(request)
    if index < 0 or index >= len(filtered):
        raise HTTPException(status_code=404, detail="下载记录不存在")
    pdf_path = filtered[index].get("pdf_path", "")
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF文件不存在")
    # xuechong 2026-06-30 添加缓存控制头，防止浏览器缓存旧的预览结果
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )
