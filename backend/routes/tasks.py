# -*- coding: utf-8 -*-
# xuechong 2026-07-18 研发BUG-0009-图档扫描-用户隔离机制问题 tasks API（重构版）
"""tasks API — 所有任务操作通过用户 scope 隔离"""
import asyncio, shutil, uuid, zipfile, re as _re
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Request, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from backend.services.app_state import state
from backend.services.image_utils import is_image_file
from backend.services.user_scope import get_user_scope
import backend.services.history_service as _hsvc

from backend import config as _cfg
import cv2
import numpy as np

router = APIRouter(tags=["tasks"])


# xuechong 2026-07-18 从请求获取当前用户的 scope
def _get_scope(request: Request):
# xuechong 2026-07-18 从请求获取当前用户的 scope
    """从请求获取当前用户的 scope，无 token 则 401"""
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return get_user_scope(username)


# xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# 取消上传批总量限制（用户决策）：接收层逐文件落盘临时目录、业务层逐文件分块处理，
# 内存峰值≈单文件（≤200MB），不随批次总量膨胀，故总量限制无内存依据；单文件 200MB 上限保留（_read_upload_file 内校验）
def _check_upload_size(content_length: str | None) -> int:
    """解析 Content-Length 头并返回字节数（不再限制批总量，仅作日志参考）"""
    if content_length:
        try:
            return int(content_length)
        except ValueError:
            pass
    return 0


# xuechong 2026-07-18 构建安全的输出路径（含路径穿越防护）
def _safe_task_path(scope, task_id: str, filename: str = None) -> Path:
# xuechong 2026-07-18 构建安全的输出路径（含路径穿越防护）
    """构建安全的输出路径（含路径穿越防护和 task_id 格式校验）"""
    if not _re.match(r'^[a-zA-Z0-9_-]+$', task_id):
        raise HTTPException(status_code=400, detail="无效的任务ID")
    # xuechong 2026-07-18 使用用户 scope 的输出目录
    base = scope.output_dir.resolve()
    if filename:
        p = (base / task_id / filename).resolve()
    else:
        p = (base / task_id).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问指定路径")
    return p


async def _read_upload_file(file, max_bytes: int) -> bytes:
    """分块读取上传文件，超出限制抛 HTTP 413"""
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)  # 1MB 分块读取
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"单个文件 ({file.filename}) 大小 ({total / 1024 / 1024:.1f} MB) 超过限制 ({_cfg.MAX_UPLOAD_SIZE_MB} MB)"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/upload")
# xuechong 2026-07-18 批量上传文件接口（用户隔离）
async def upload_files(
# xuechong 2026-07-18 批量上传文件接口（用户隔离）
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    批量上传文件接口（用户隔离）
    支持多个文件同时上传，会自动过滤非图片文件
    """
    # Content-Length 预检查
    _check_upload_size(request.headers.get("content-length"))

    # 手动解析表单数据，设置足够大的 max_files 和 max_fields 限制
    form = await request.form(max_files=100000000, max_fields=100000000)
    files = form.getlist("files")

    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的文件")

    scope = _get_scope(request)
    username = scope.username

    # 创建任务
    task_id = str(uuid.uuid4())[:8]
    # xuechong 2026-07-18 使用用户 scope 的上传目录
    task_upload_dir = scope.upload_dir / task_id
    task_upload_dir.mkdir(parents=True, exist_ok=True)

    # 保存上传的文件
    saved_files = []
    for file in files:
        if not file.filename:
            continue

        # 处理文件夹上传时的路径（只保留文件名）
        filename = Path(file.filename).name

        if not is_image_file(filename):
            continue

        file_path = task_upload_dir / filename
        content = await _read_upload_file(file, _cfg.MAX_UPLOAD_SIZE_BYTES)
        with open(file_path, "wb") as f:
            f.write(content)
        saved_files.append(file_path)

    if not saved_files:
        await asyncio.to_thread(shutil.rmtree, task_upload_dir, True)
        raise HTTPException(status_code=400, detail="没有找到支持的图片文件（支持: PNG, JPG, BMP, TIF, WEBP）")

    # 按文件名排序（确保文件夹上传时按顺序处理和合并）
    saved_files.sort(key=lambda x: x.name.lower())

    # xuechong 2026-07-18 写入用户 scope 的任务字典
    with scope._lock:
        scope.upload_tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "total_files": len(saved_files),
            "processed_files": 0,
            "message": "等待处理...",
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "output_files": [],
            "username": username,
            "upload_dir": str(task_upload_dir),
            "output_dir": str(scope.output_dir / task_id),
        }
    # xuechong 2026-07-18 持久化任务状态
    scope.save_tasks()

    # 启动后台处理（传递 username 以便后台任务使用用户 scope）
    background_tasks.add_task(_hsvc.process_task, task_id, saved_files, username)

    return {
        "task_id": task_id,
        "file_count": len(saved_files),
        "message": f"已上传 {len(saved_files)} 个文件，开始处理..."
    }


@router.get("/api/task/{task_id}")
# xuechong 2026-07-18 获取任务状态（用户隔离）
async def get_task_status(task_id: str, request: Request):
# xuechong 2026-07-18 获取任务状态（用户隔离）
    """获取任务状态（用户隔离）"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/api/tasks")
# xuechong 2026-07-18 列出当前用户的任务（用户隔离）
async def list_tasks(request: Request):
# xuechong 2026-07-18 列出当前用户的任务（用户隔离）
    """列出当前用户的任务（用户隔离）"""
    scope = _get_scope(request)
    return list(scope.upload_tasks.values())


@router.get("/api/download/{task_id}")
# xuechong 2026-07-18 下载处理结果（PDF格式，用户隔离）
async def download_results(task_id: str, request: Request):
# xuechong 2026-07-18 下载处理结果（PDF格式，用户隔离）
    """下载处理结果（PDF 格式，用户隔离）"""
    from urllib.parse import quote

    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] not in ["completed", "cancelled"]:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    task_output_dir = _safe_task_path(scope, task_id)
    if not task_output_dir.exists():
        raise HTTPException(status_code=404, detail="输出目录不存在")

    # 优先返回合并后的 PDF
    merged_pdf_name = task.get("merged_pdf")
    if merged_pdf_name:
        merged_pdf_path = task_output_dir / merged_pdf_name
        if merged_pdf_path.exists():
            filename = f"文档处理结果_{task_id}.pdf"
            ascii_filename = f"result_{task_id}.pdf"
            return FileResponse(
                path=str(merged_pdf_path),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}"
                }
            )

    # 查找 merged_*.pdf 文件
    merged_pdfs = list(task_output_dir.glob(f"merged_{task_id}.pdf"))
    if merged_pdfs:
        filename = f"文档处理结果_{task_id}.pdf"
        ascii_filename = f"result_{task_id}.pdf"
        return FileResponse(
            path=str(merged_pdfs[0]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}"
            }
        )

    # 如果没有合并的 PDF，查找单个 PDF 文件
    pdf_files = list(task_output_dir.glob("*.pdf"))
    if pdf_files:
        if len(pdf_files) == 1:
            filename = f"文档处理结果_{task_id}.pdf"
            ascii_filename = f"result_{task_id}.pdf"
            return FileResponse(
                path=str(pdf_files[0]),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}"
                }
            )
        else:
            # 合并多个 PDF
            merged_path = task_output_dir / f"merged_{task_id}.pdf"
            _hsvc.merge_pdfs_to_single(pdf_files, merged_path)
            filename = f"文档处理结果_{task_id}.pdf"
            ascii_filename = f"result_{task_id}.pdf"
            return FileResponse(
                path=str(merged_path),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}"
                }
            )

    # 兜底：打包为 ZIP
    zip_path = scope.output_dir / f"{task_id}_results.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in task_output_dir.iterdir():
            if file_path.is_file():
                zipf.write(file_path, file_path.name)

    filename = f"文档处理结果_{task_id}.zip"
    ascii_filename = f"result_{task_id}.zip"
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}"
        }
    )


@router.get("/api/download/{task_id}/{filename}")
# xuechong 2026-07-18 下载单个处理结果文件（用户隔离）
async def download_single_file(task_id: str, filename: str, request: Request):
# xuechong 2026-07-18 下载单个处理结果文件（用户隔离）
    """下载单个处理结果文件（用户隔离）"""
    from urllib.parse import quote

    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    file_path = _safe_task_path(scope, task_id, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    # 根据文件类型设置 MIME 类型
    if filename.lower().endswith('.pdf'):
        media_type = "application/pdf"
    elif filename.lower().endswith('.png'):
        media_type = "image/png"
    else:
        media_type = "application/octet-stream"

    # 生成 ASCII 安全的备用文件名
    import re
    ascii_filename = re.sub(r'[^\x00-\x7F]', '_', filename) if any(ord(c) > 127 for c in filename) else filename

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}"
        }
    )


@router.get("/api/preview/{task_id}/{filename}")
# xuechong 2026-07-18 预览处理结果文件（用户隔离）
async def preview_file(task_id: str, filename: str, request: Request):
# xuechong 2026-07-18 预览处理结果文件（用户隔离）
    """预览处理结果文件（用户隔离）"""
    scope = _get_scope(request)
    file_path = _safe_task_path(scope, task_id, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    # 根据文件类型设置 MIME 类型
    if filename.lower().endswith('.pdf'):
        media_type = "application/pdf"
    elif filename.lower().endswith('.png'):
        media_type = "image/png"
    else:
        media_type = "application/octet-stream"

    return FileResponse(path=str(file_path), media_type=media_type)


@router.get("/api/preview/{task_id}")
# xuechong 2026-07-18 预览任务的合并PDF（用户隔离）
async def preview_merged_pdf(task_id: str, request: Request):
# xuechong 2026-07-18 预览任务的合并PDF（用户隔离）
    """预览任务的合并 PDF（用户隔离）"""
    scope = _get_scope(request)
    task_output_dir = _safe_task_path(scope, task_id)
    if not task_output_dir.exists():
        raise HTTPException(status_code=404, detail="输出目录不存在")

    # 查找合并的 PDF
    merged_pdf = task_output_dir / f"merged_{task_id}.pdf"
    if merged_pdf.exists():
        return FileResponse(path=str(merged_pdf), media_type="application/pdf")

    # 查找任何 PDF 文件
    pdf_files = list(task_output_dir.glob("*.pdf"))
    if pdf_files:
        return FileResponse(path=str(pdf_files[0]), media_type="application/pdf")

    raise HTTPException(status_code=404, detail="未找到 PDF 文件")


@router.post("/api/task/{task_id}/cancel")
# xuechong 2026-07-18 取消正在处理的任务（用户隔离）
async def cancel_task(task_id: str, request: Request = None):
# xuechong 2026-07-18 取消正在处理的任务（用户隔离）
    """取消正在处理的任务（用户隔离）"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.get("clean_status") == "processing":
        scope.tasks_cancel_flags[task_id] = True
        task["clean_message"] = "正在取消..."
        return {"message": "取消请求已发送", "task_id": task_id}
    if task.get("status") == "processing":
        scope.tasks_cancel_flags[task_id] = True
        task["message"] = "正在取消..."
        return {"message": "取消请求已发送", "task_id": task_id}
    if task.get("redraw_status") == "processing":
        scope.tasks_cancel_flags[task_id] = True
        task["redraw_message"] = "正在取消..."
        return {"message": "取消请求已发送", "task_id": task_id}
    raise HTTPException(status_code=400, detail="该任务没有正在进行的操作")


@router.post("/api/cancel-all")
# xuechong 2026-07-18 取消当前用户所有正在处理的任务（用户隔离）
async def cancel_all_tasks(request: Request):
# xuechong 2026-07-18 取消当前用户所有正在处理的任务（用户隔离）
    """取消当前用户所有正在处理的任务（用户隔离）"""
    scope = _get_scope(request)
    cancelled = []
    for task_id, task in scope.upload_tasks.items():
        if task["status"] in ["pending", "processing"]:
            scope.tasks_cancel_flags[task_id] = True
            task["message"] = "正在取消..."
            cancelled.append(task_id)

    return {"message": f"已发送取消请求", "cancelled_tasks": cancelled}


@router.delete("/api/task/{task_id}")
# xuechong 2026-07-18 删除任务及其文件（用户隔离）
async def delete_task(task_id: str, request: Request):
# xuechong 2026-07-18 删除任务及其文件（用户隔离）
    """删除任务及其文件（用户隔离）"""
    if not _re.match(r'^[a-zA-Z0-9_-]+$', task_id):
        raise HTTPException(status_code=400, detail="无效的任务ID")

    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 如果任务正在处理，先取消
    if task["status"] in ["pending", "processing"]:
        scope.tasks_cancel_flags[task_id] = True

    # xuechong 2026-07-18 删除用户 scope 目录中的文件
    # xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：rmtree/unlink 包装到线程池
    await asyncio.to_thread(shutil.rmtree, scope.upload_dir / task_id, True)
    await asyncio.to_thread(shutil.rmtree, scope.output_dir / task_id, True)

    # 删除 ZIP 文件
    zip_path = scope.output_dir / f"{task_id}_results.zip"
    if zip_path.exists():
        await asyncio.to_thread(zip_path.unlink)

    # 删除任务状态
    scope.upload_tasks.pop(task_id, None)
    scope.tasks_cancel_flags.pop(task_id, None)
    scope.save_tasks()

    return {"message": "任务已删除"}


@router.post("/api/process-single")
# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 单文件处理添加用户隔离
async def process_single(request: Request, file: UploadFile = File(...)):
    """
    单文件即时处理（同步）
    适合单张图片快速处理，输出 PDF 格式
    """
    if not file.filename or not is_image_file(file.filename):
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    # xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 使用用户 scope 的临时目录
    scope = _get_scope(request)

    try:
        # 读取上传的文件（限制大小）
        content = await _read_upload_file(file, _cfg.MAX_UPLOAD_SIZE_BYTES)
        nparr = np.frombuffer(content, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            raise HTTPException(status_code=400, detail="无法解析图片文件")

        # 从上传字节中读取DPI（此时无文件路径，不能用 get_image_dpi）
        image_dpi = 300
        try:
            from PIL import Image as PILImage
            import io as _io
            _pil_tmp = PILImage.open(_io.BytesIO(content))
            _dpi_info = _pil_tmp.info.get('dpi')
            if _dpi_info and isinstance(_dpi_info, tuple) and _dpi_info[0] > 0:
                image_dpi = int(_dpi_info[0])
        except Exception:
            pass

        # 处理图片
        cleaner = _hsvc.get_cleaner()
        result = cleaner.process(image, debug=False, dpi=image_dpi)

        # xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 保存到用户 scope 的临时目录
        temp_id = str(uuid.uuid4())[:8]
        temp_output_dir = scope.output_dir / "temp"
        temp_output_dir.mkdir(parents=True, exist_ok=True)

        # 先保存清洁后的图片
        temp_png_filename = f"{Path(file.filename).stem}_cleaned_{temp_id}.png"
        temp_png_path = temp_output_dir / temp_png_filename
        cv2.imencode('.png', result['result'])[1].tofile(str(temp_png_path))

        # 转换为 PDF
        output_filename = f"{Path(file.filename).stem}_{temp_id}.pdf"
        output_path = temp_output_dir / output_filename
        pdf_success = _hsvc.create_searchable_pdf(temp_png_path, output_path)

        # 删除临时 PNG
        if pdf_success and temp_png_path.exists():
            await asyncio.to_thread(temp_png_path.unlink)

        if pdf_success:
            return {
                "success": True,
                "filename": output_filename,
                "download_url": f"/api/download-temp/{output_filename}",
                "file_type": "pdf",
                "size": f"{image.shape[1]}x{image.shape[0]}",
                "skew_angle": result.get('skew_angle', 0)
            }
        else:
            # PDF 转换失败，返回 PNG
            return {
                "success": True,
                "filename": temp_png_filename,
                "download_url": f"/api/download-temp/{temp_png_filename}",
                "file_type": "png",
                "size": f"{image.shape[1]}x{image.shape[0]}",
                "skew_angle": result.get('skew_angle', 0)
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/api/download-temp/{filename}")
# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 临时文件下载添加用户隔离
async def download_temp_file(filename: str, request: Request = None):
    """下载临时处理结果（用户隔离）"""
    from urllib.parse import quote

    # xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 从用户 scope 的临时目录查找
    scope = _get_scope(request)
    file_path = (scope.output_dir / "temp" / filename).resolve()
    try:
        file_path.relative_to((scope.output_dir / "temp").resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问指定路径")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    # 根据文件类型设置 MIME 类型
    if filename.lower().endswith('.pdf'):
        media_type = "application/pdf"
    elif filename.lower().endswith('.png'):
        media_type = "image/png"
    else:
        media_type = "application/octet-stream"

    # 生成 ASCII 安全的备用文件名
    import re
    ascii_filename = re.sub(r'[^\x00-\x7F]', '_', filename) if any(ord(c) > 127 for c in filename) else filename

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quote(filename)}"
        }
    )
