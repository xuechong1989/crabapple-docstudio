# -*- coding: utf-8 -*-
"""dual_layer API"""
from typing import List
import os, shutil, uuid, zipfile, io, re as _re, asyncio
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Request, HTTPException, Response
from fastapi.responses import FileResponse
from backend.services.user_scope import get_user_scope
from backend.services.logging_service import log_info, debug_log, DEBUG_LOG_FILE
import backend.services.history_service as _hsvc

import fitz

router = APIRouter(tags=["dual_layer"])

# ============================================================


# xuechong 2026-07-18 获取用户的双层PDF上传目录
def _get_upload_dir(scope) -> Path:
    d = scope.dual_layer_dir / "upload"
    d.mkdir(parents=True, exist_ok=True)
    return d


# xuechong 2026-07-18 获取用户的双层PDF输出目录
def _get_output_dir(scope) -> Path:
    d = scope.dual_layer_dir / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d


# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题 双层PDF转换进度改为用户隔离
def _set_dual_layer_progress(scope, key: str, progress: dict):
    # xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题 使用 scope 的进度锁
    scope.set_dual_layer_progress(key, progress)


# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题 获取进度改为用户隔离
def _get_dual_layer_progress(scope, key: str):
    # xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题 使用 scope 的进度查询
    return scope.get_dual_layer_progress(key)

# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局 load_dual_layer_history / save_dual_layer_history 已废弃，统一使用 UserScope

def build_pdf_file_tree(base_path: Path, relative_base: str = "", task_id: str = "") -> dict:
    """构建PDF文件树结构（只包含PDF文件和包含PDF的目录）
    
    Args:
        base_path: 目录的绝对路径
        relative_base: 相对路径前缀（用于递归）
        task_id: 任务ID，作为路径的顶层前缀
    """
    # 根目录使用task_id作为路径，子目录使用relative_base
    if not relative_base:
        current_path = task_id
    else:
        current_path = relative_base
    
    result = {
        "name": base_path.name,
        "path": current_path,
        "type": "directory",
        "children": []
    }
    
    try:
        items = sorted(base_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        for item in items:
            # 构建子项的路径：task_id/subdir/file.pdf
            if current_path:
                rel_path = f"{current_path}/{item.name}"
            else:
                rel_path = item.name
            
            if item.is_dir():
                # 递归处理子目录
                sub_tree = build_pdf_file_tree(item, rel_path, task_id)
                # 只添加包含PDF文件的目录
                if sub_tree["children"]:
                    result["children"].append(sub_tree)
            elif item.is_file() and item.suffix.lower() == '.pdf':
                # 添加PDF文件
                result["children"].append({
                    "name": item.name,
                    "path": rel_path,
                    "type": "file",
                    "extension": item.suffix.lower(),
                    "size": item.stat().st_size
                })
    except Exception as e:
        log_info(f"  [Warning] Failed to read directory {base_path}: {e}")
    
    return result


@router.post("/api/dual-layer/upload")
# xuechong 2026-07-18 上传PDF文件用于双层PDF转换（用户隔离）
async def upload_dual_layer_files(request: Request, files: List[UploadFile] = File(...)):
    """上传PDF文件用于双层PDF转换（用户隔离）"""
    import traceback

    # xuechong 2026-07-18 获取用户 scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)

    # Content-Length 预检查
    from backend.routes.tasks import _check_upload_size
    _check_upload_size(request.headers.get("content-length"))

    if not files:
        raise HTTPException(status_code=400, detail="没有上传文件")

    # xuechong 2026-07-18 使用用户 scope 的上传目录
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    upload_dir = _get_upload_dir(scope)
    task_dir = upload_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_count = 0
    folder_name = ""
    
    try:
        for file in files:
            if not file.filename.lower().endswith('.pdf'):
                continue
            
            # 获取相对路径
            rel_path = file.filename
            if '/' in rel_path:
                parts = rel_path.split('/')
                if not folder_name:
                    folder_name = parts[0]
            
            # 创建目标路径（路径穿越防护）
            target_path = (task_dir / rel_path).resolve()
            try:
                target_path.relative_to(task_dir.resolve())
            except ValueError:
                log_info(f"[双层PDF上传] 路径穿越拒绝: {rel_path}")
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 保存文件（分块读取，限制大小）
            content_chunks = []
            total_read = 0
            max_pdf_bytes = 200 * 1024 * 1024  # 200MB 单文件限制
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > max_pdf_bytes:
                    raise HTTPException(status_code=413, detail=f"PDF文件 ({file.filename}) 超过大小限制 (200MB)")
                content_chunks.append(chunk)
            content = b"".join(content_chunks)
            with open(target_path, 'wb') as f:
                f.write(content)
            pdf_count += 1
        
        if pdf_count == 0:
            # xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：rmtree 包装到线程池
            await asyncio.to_thread(shutil.rmtree, task_dir, True)
            raise HTTPException(status_code=400, detail="没有有效的PDF文件")
        
        if not folder_name:
            folder_name = task_id
        
        # 构建文件树（路径包含task_id前缀）
        file_tree = build_pdf_file_tree(task_dir, task_id=task_id)
        
        return {
            "task_id": task_id,
            "folder_name": folder_name,
            "total_files": pdf_count,
            "file_tree": file_tree
        }
        
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        await asyncio.to_thread(shutil.rmtree, task_dir, True)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.post("/api/dual-layer/convert")
# xuechong 2026-07-18 转换选中的PDF为双层PDF（用户隔离）
async def convert_dual_layer_pdf(request: Request):
    """转换选中的PDF为双层PDF（用户隔离）"""
    import asyncio
    from datetime import datetime

    # xuechong 2026-07-18 获取用户 scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)

    # 记录 API 调用
    log_info(f"\n{'*'*60}")
    log_info(f"  [API调用] /api/dual-layer/convert 被调用！")
    log_info(f"  [API调用] 时间: {datetime.now().strftime('%H:%M:%S.%f')}")
    log_info(f"  [API调用] 用户: {username}")
    log_info(f"{'*'*60}\n")
    
    data = await request.json()
    path = data.get("path", "")
    ocr_lang = data.get("ocr_lang", "ch")
    keep_structure = data.get("keep_structure", True)
    auto_rotate = data.get("auto_rotate", True)

    if not path:
        raise HTTPException(status_code=400, detail="未指定转换路径")
    
    # 防止重复转换
    with scope._dual_layer_lock:
        if path in scope._dual_layer_processing:
            log_info(f"  [双层PDF] 文件正在处理中，跳过重复请求: {path}")
            raise HTTPException(status_code=409, detail="该文件正在处理中，请勿重复提交")
        scope._dual_layer_processing.add(path)
    
    # 查找对应的上传目录
    # path格式: task_id/relative_path 或直接是文件名
    parts = path.split("/")
    task_id = parts[0] if parts else ""

    if not _re.match(r'^[a-zA-Z0-9_-]+$', task_id):
        with scope._dual_layer_lock:
            scope._dual_layer_processing.discard(path)
        raise HTTPException(status_code=400, detail="无效的任务ID")

    task_dir = _get_upload_dir(scope) / task_id
    if not task_dir.exists():
        # 尝试在所有任务目录中查找
        for d in _get_upload_dir(scope).iterdir():
            if d.is_dir():
                check_path = d / path
                if check_path.exists():
                    task_dir = d
                    task_id = d.name
                    break

    source_path = (_get_upload_dir(scope) / path)
    # 路径穿越防护
    try:
        source_path.resolve().relative_to(_get_upload_dir(scope).resolve())
    except ValueError:
        with scope._dual_layer_lock:
            scope._dual_layer_processing.discard(path)
        raise HTTPException(status_code=403, detail="无权访问指定路径")
    if not source_path.exists():
        with scope._dual_layer_lock:
            scope._dual_layer_processing.discard(path)
        raise HTTPException(status_code=404, detail="文件或目录不存在")
    
    # 创建输出目录
    output_task_dir = _get_output_dir(scope) / task_id
    output_task_dir.mkdir(parents=True, exist_ok=True)
    
    # 收集要转换的PDF文件
    pdf_files = []
    if source_path.is_file():
        pdf_files = [source_path]
    else:
        pdf_files = list(source_path.rglob("*.pdf"))
    
    # 调试：打印收集到的文件数量
    log_info(f"  [双层PDF] 收集到 {len(pdf_files)} 个PDF文件: {[f.name for f in pdf_files]}")
    
    if not pdf_files:
        with scope._dual_layer_lock:
            scope._dual_layer_processing.discard(path)
        raise HTTPException(status_code=400, detail="没有找到PDF文件")
    
    # 根据配置选择OCR引擎
    try:
        from backend.config import OCR_ENGINE
    except ImportError:
        OCR_ENGINE = os.environ.get("DOCSTUDIO_OCR_ENGINE", "rapidocr")
    
    if OCR_ENGINE.lower() == "rapidocr":
        debug_log(f"使用 RapidOCR 引擎进行双层PDF转换")
        from backend.ocr_rapid import convert_to_dual_layer_pdf
    else:
        debug_log(f"使用 PaddleOCR 引擎进行双层PDF转换")
        from backend.ocr_pdf import convert_to_dual_layer_pdf
    
    # 初始化进度
    progress_key = f"path:{path}"
    total_files = len(pdf_files)
    _set_dual_layer_progress(scope, progress_key, {
        "currentFile": "",
        "filePercent": None,
        "current": 0,
        "total": total_files,
        "totalPercent": 0 if total_files > 0 else 100,
        "completed": 0,
        "processing": 1 if total_files > 0 else 0,
        "pending": max(0, total_files - 1)
    })
    
    # xuechong 2026-07-18 捕获 username 供 do_convert 内部记录历史时使用
    _dl_username = getattr(request.state, 'username', 'admin')
    _dl_scope = get_user_scope(_dl_username)
    # 定义同步转换函数（将在线程池中执行）
    def do_convert():
        _success_count = 0
        _failed_count = 0
        _output_files = []
        _total_pages = 0  # 统计总页数
        total_count = len(pdf_files)
        
        for file_idx, pdf_file in enumerate(pdf_files):
            completed = _success_count + _failed_count
            _set_dual_layer_progress(scope, progress_key, {
                "currentFile": pdf_file.name,
                "filePercent": 0,
                "currentPage": 0,
                "totalPages": 0,
                "step": "preparing",
                "current": completed,
                "total": total_count,
                "totalPercent": int((completed / total_count) * 100) if total_count else 100,
                "completed": completed,
                "processing": 1 if total_count else 0,
                "pending": max(0, total_count - completed - 1)
            })
            
            # 创建进度回调函数
            def make_progress_callback(file_name, file_index, files_total):
                def progress_callback(step, current_page, page_total, percent):
                    # 计算总进度：已完成文件 + 当前文件进度
                    files_done = _success_count + _failed_count
                    total_percent = int((files_done + percent / 100) / files_total * 100) if files_total else 100
                    
                    step_name = "方向检测" if step == "orientation" else "OCR识别"
                    _set_dual_layer_progress(scope, progress_key, {
                        "currentFile": file_name,
                        "filePercent": percent,
                        "currentPage": current_page,
                        "totalPages": page_total,
                        "step": step_name,
                        "current": files_done,
                        "total": files_total,
                        "totalPercent": total_percent,
                        "completed": files_done,
                        "processing": 1,
                        "pending": max(0, files_total - files_done - 1)
                    })
                return progress_callback
            
            file_progress = make_progress_callback(pdf_file.name, file_idx, total_count)
            
            try:
                # 计算相对路径
                rel_path = pdf_file.relative_to(_get_upload_dir(scope) / task_id)
                
                if keep_structure:
                    output_path = output_task_dir / rel_path
                else:
                    output_path = output_task_dir / pdf_file.name
                
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 执行转换（保留原PDF质量，自动旋转90度页面）
                result = convert_to_dual_layer_pdf(
                    str(pdf_file),
                    str(output_path),
                    ocr_lang=ocr_lang,
                    auto_rotate=auto_rotate,
                    progress_callback=file_progress
                )
                
                if result:
                    _success_count += 1
                    _output_files.append(str(output_path))
                    # 统计页数
                    try:
                        doc = fitz.open(str(output_path))
                        _total_pages += len(doc)
                        doc.close()
                    except Exception as e:
                        log_info(f"[双层PDF] 统计页数失败 {output_path.name}: {e}")
                else:
                    _failed_count += 1
                    
            except Exception as e:
                log_info(f"  [双层PDF] 转换失败 {pdf_file.name}: {e}")
                _failed_count += 1
            
            completed = _success_count + _failed_count
            _set_dual_layer_progress(scope, progress_key, {
                "currentFile": pdf_file.name,
                "filePercent": 100,
                "currentPage": 0,
                "totalPages": 0,
                "step": "completed",
                "current": completed,
                "total": total_count,
                "totalPercent": int((completed / total_count) * 100) if total_count else 100,
                "completed": completed,
                "processing": 1 if completed < total_count else 0,
                "pending": max(0, total_count - completed - 1) if completed < total_count else 0
            })
        
        return _success_count, _failed_count, _output_files, _total_pages
    
    # 在线程池中执行 CPU 密集型任务，避免阻塞事件循环
    loop = asyncio.get_event_loop()
    success_count, failed_count, output_files, total_pages = await loop.run_in_executor(_hsvc.get_dual_layer_executor(), do_convert)
    
    # 最终进度
    completed = success_count + failed_count
    _set_dual_layer_progress(scope, progress_key, {
        "currentFile": "",
        "filePercent": 100 if total_files > 0 else None,
        "current": completed,
        "total": total_files,
        "totalPercent": 100 if total_files > 0 else 0,
        "completed": completed,
        "processing": 0,
        "pending": 0
    })
    
    # xuechong 2026-06-02 创建记录（同时写入全局和用户 scope 以确保视图可见）
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []
    for output_file in output_files:
        record_id = str(uuid.uuid4())[:8]
        record = {
            "id": record_id,
            "name": Path(output_file).name,
            "type": "file",
            "fileCount": 1,
            "createdAt": created_at,
            "task_id": task_id,
            "output_dir": str(output_task_dir),
            "output_files": [output_file],
            "username": _dl_username
        }
        # xuechong 2026-07-16 只写入用户 scope，不再写全局 state
        _dl_scope.dual_layer_history.insert(0, record)
        records.insert(0, record)

    _dl_scope.save_dual_layer_history()

    # 清理处理中状态
    with scope._dual_layer_lock:
        scope._dual_layer_processing.discard(path)

    result = {
        "success": failed_count == 0 and success_count > 0,
        "success_count": success_count,
        "failed_count": failed_count,
        "total_pages": total_pages,
        "records": records
    }
    if len(records) == 1:
        result["record"] = records[0]
    return result


@router.post("/api/dual-layer/convert-all")
# xuechong 2026-07-18 批量转换当前任务中的所有PDF文件（用户隔离）
async def convert_all_dual_layer_pdf(request: Request):
    """批量转换当前任务中的所有PDF文件（用户隔离）"""
    import asyncio

    # xuechong 2026-07-18 获取用户 scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)

    # 清空并初始化调试日志文件
    with open(DEBUG_LOG_FILE, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("  双层PDF转换调试日志\n")
        f.write("=" * 60 + "\n\n")

    debug_log("API /api/dual-layer/convert-all 被调用")

    data = await request.json()
    task_id = data.get("task_id", "")  # 必须指定任务ID
    ocr_lang = data.get("ocr_lang", "ch")
    keep_structure = data.get("keep_structure", True)
    auto_rotate = data.get("auto_rotate", True)

    debug_log(f"参数: task_id={task_id}, ocr_lang={ocr_lang}, auto_rotate={auto_rotate}")

    # 验证 task_id
    if not task_id:
        debug_log("错误: 未指定 task_id")
        raise HTTPException(status_code=400, detail="未指定任务ID，请先上传文件")
    if not _re.match(r'^[a-zA-Z0-9_-]+$', task_id):
        raise HTTPException(status_code=400, detail="无效的任务ID")

    # xuechong 2026-07-18 使用用户 scope 的上传目录
    upload_dir = _get_upload_dir(scope)
    task_dir = upload_dir / task_id
    if not task_dir.exists():
        debug_log(f"错误: 任务目录不存在: {task_dir}")
        raise HTTPException(status_code=400, detail=f"任务目录不存在: {task_id}")
    
    debug_log(f"任务目录: {task_dir}")
    all_pdf_files = list(task_dir.rglob("*.pdf"))
    debug_log(f"共找到 {len(all_pdf_files)} 个PDF文件:")
    for i, f in enumerate(all_pdf_files):
        debug_log(f"  [{i+1}/{len(all_pdf_files)}] {f}")
    
    if not all_pdf_files:
        debug_log("没有找到PDF文件，返回400错误")
        raise HTTPException(status_code=400, detail="没有找到PDF文件")
    
    # 根据配置选择OCR引擎
    try:
        from backend.config import OCR_ENGINE
    except ImportError:
        OCR_ENGINE = os.environ.get("DOCSTUDIO_OCR_ENGINE", "rapidocr")
    
    if OCR_ENGINE.lower() == "rapidocr":
        debug_log(f"使用 RapidOCR 引擎进行批量双层PDF转换")
        from backend.ocr_rapid import convert_to_dual_layer_pdf
    else:
        debug_log(f"使用 PaddleOCR 引擎进行批量双层PDF转换")
        from backend.ocr_pdf import convert_to_dual_layer_pdf
    
    debug_log("开始定义 do_convert 函数")
    
    # 初始化进度
    progress_key = f"task:{task_id}"
    total_files = len(all_pdf_files)
    _set_dual_layer_progress(scope, progress_key, {
        "currentFile": "",
        "filePercent": None,
        "current": 0,
        "total": total_files,
        "totalPercent": 0 if total_files > 0 else 100,
        "completed": 0,
        "processing": 1 if total_files > 0 else 0,
        "pending": max(0, total_files - 1)
    })
    
    # xuechong 2026-07-18 捕获 username 供 do_convert 内部记录历史时使用
    _dl_username = getattr(request.state, 'username', 'admin')
    _dl_scope = get_user_scope(_dl_username)
    # 定义同步转换函数（将在线程池中执行）
    _task_id = task_id

    def do_convert():
        nonlocal all_pdf_files
        debug_log(">>> do_convert 函数开始执行")
        _success_count = 0
        _failed_count = 0
        _total_pages = 0  # 统计总页数
        _task_outputs = {_task_id: []}
        total_files = len(all_pdf_files)
        debug_log(f">>> 任务ID: {_task_id}, 需要处理 {total_files} 个文件")
        
        for file_idx, pdf_file in enumerate(all_pdf_files):
            completed = _success_count + _failed_count
            _set_dual_layer_progress(scope, progress_key, {
                "currentFile": pdf_file.name,
                "filePercent": 0,
                "currentPage": 0,
                "totalPages": 0,
                "step": "preparing",
                "current": completed,
                "total": total_files,
                "totalPercent": int((completed / total_files) * 100) if total_files else 100,
                "completed": completed,
                "processing": 1 if total_files else 0,
                "pending": max(0, total_files - completed - 1)
            })
            debug_log(f">>> 开始处理文件 [{file_idx+1}/{total_files}]: {pdf_file}")
            
            # 创建进度回调函数
            def make_progress_callback(file_name, files_total):
                def progress_callback(step, current_page, page_total, percent):
                    # 计算总进度：已完成文件 + 当前文件进度
                    files_done = _success_count + _failed_count
                    total_percent = int((files_done + percent / 100) / files_total * 100) if files_total else 100
                    
                    step_name = "方向检测" if step == "orientation" else "OCR识别"
                    _set_dual_layer_progress(scope, progress_key, {
                        "currentFile": file_name,
                        "filePercent": percent,
                        "currentPage": current_page,
                        "totalPages": page_total,
                        "step": step_name,
                        "current": files_done,
                        "total": files_total,
                        "totalPercent": total_percent,
                        "completed": files_done,
                        "processing": 1,
                        "pending": max(0, files_total - files_done - 1)
                    })
                return progress_callback
            
            file_progress = make_progress_callback(pdf_file.name, total_files)
            
            try:
                # 创建输出目录（使用外部传入的 task_id）
                output_task_dir = _get_output_dir(scope) / _task_id
                output_task_dir.mkdir(parents=True, exist_ok=True)
                
                # 计算输出路径（相对于任务目录）
                rel_path = pdf_file.relative_to(_get_upload_dir(scope) / _task_id)
                if keep_structure:
                    output_path = output_task_dir / rel_path
                else:
                    output_path = output_task_dir / pdf_file.name
                
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 执行转换（保留原PDF质量，自动旋转90度页面）
                result = convert_to_dual_layer_pdf(
                    str(pdf_file),
                    str(output_path),
                    ocr_lang=ocr_lang,
                    auto_rotate=auto_rotate,
                    progress_callback=file_progress
                )
                
                if result:
                    _success_count += 1
                    _task_outputs[_task_id].append(str(output_path))
                    # 统计页数
                    try:
                        doc = fitz.open(str(output_path))
                        _total_pages += len(doc)
                        doc.close()
                    except Exception as e:
                        log_info(f"[双层PDF] 统计页数失败 {output_path.name}: {e}")
                    debug_log(f">>> 文件转换成功: {pdf_file.name}")
                else:
                    _failed_count += 1
                    debug_log(f">>> 文件转换失败(返回False): {pdf_file.name}")
                    
            except Exception as e:
                debug_log(f">>> 文件转换异常: {pdf_file.name}, 错误: {e}")
                _failed_count += 1
            
            completed = _success_count + _failed_count
            _set_dual_layer_progress(scope, progress_key, {
                "currentFile": pdf_file.name,
                "filePercent": 100,
                "currentPage": 0,
                "totalPages": 0,
                "step": "completed",
                "current": completed,
                "total": total_files,
                "totalPercent": int((completed / total_files) * 100) if total_files else 100,
                "completed": completed,
                "processing": 1 if completed < total_files else 0,
                "pending": max(0, total_files - completed - 1) if completed < total_files else 0
            })
        
        debug_log(f">>> do_convert 函数执行完毕, 成功={_success_count}, 失败={_failed_count}, 总页数={_total_pages}")
        return _success_count, _failed_count, _task_outputs, _total_pages
    
    # 在线程池中执行 CPU 密集型任务，避免阻塞事件循环
    loop = asyncio.get_event_loop()
    success_count, failed_count, task_outputs, total_pages = await loop.run_in_executor(_hsvc.get_dual_layer_executor(), do_convert)
    
    # 最终进度
    completed = success_count + failed_count
    _set_dual_layer_progress(scope, progress_key, {
        "currentFile": "",
        "filePercent": 100 if total_files > 0 else None,
        "current": completed,
        "total": total_files,
        "totalPercent": 100 if total_files > 0 else 0,
        "completed": completed,
        "processing": 0,
        "pending": 0
    })
    
    # 为每个输出文件创建记录
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []
    for task_id, output_files in task_outputs.items():
        output_dir = _get_output_dir(scope) / task_id
        for output_file in output_files:
            record_id = str(uuid.uuid4())[:8]
            record = {
                "id": record_id,
                "name": Path(output_file).name,
                "type": "file",
                "fileCount": 1,
                "createdAt": created_at,
                "task_id": task_id,
                "output_dir": str(output_dir),
                "output_files": [output_file],
                "username": _dl_username
            }
            # xuechong 2026-07-16 只写入用户 scope，不再写全局 state
            _dl_scope.dual_layer_history.insert(0, record)
            records.insert(0, record)

    _dl_scope.save_dual_layer_history()

    return {
        "success": failed_count == 0 and success_count > 0,
        "success_count": success_count,
        "failed_count": failed_count,
        "total_pages": total_pages,
        "records": records
    }


@router.get("/api/dual-layer/progress")
# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题 进度查询添加用户隔离
async def get_dual_layer_progress(path: str = "", task_id: str = "", request: Request = None):
    """获取双层PDF转换进度（用户隔离）"""
    if not path and not task_id:
        raise HTTPException(status_code=400, detail="必须指定 path 或 task_id")
    # xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题 从请求获取用户 scope
    username = getattr(request.state, 'username', None) if request else None
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    key = f"path:{path}" if path else f"task:{task_id}"
    progress = _get_dual_layer_progress(scope, key) or {}
    return {"progress": progress}


# xuechong 2026-07-18 双层PDF历史辅助
def _dl_scope(req: Request = None):
    username = getattr(req.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return get_user_scope(username)


@router.get("/api/dual-layer/history")
# xuechong 2026-07-18 获取当前用户的双层PDF转换记录（用户隔离）
async def get_dual_layer_history(request: Request):
    """获取当前用户的双层PDF转换记录（用户隔离，从 scope 读取）"""
    # xuechong 2026-07-16 用户隔离：从 scope 读取而非全局 state
    scope = _dl_scope(request)
    return {"history": scope.dual_layer_history}


@router.delete("/api/dual-layer/history")
# xuechong 2026-07-18 清空当前用户的双层PDF转换记录
async def clear_dual_layer_history(request: Request):
    """清空当前用户的双层PDF转换记录"""
    scope = _dl_scope(request)
    scope.dual_layer_history.clear()
    scope.save_dual_layer_history()
    return {"message": "记录已清空"}


@router.get("/api/dual-layer/preview/{record_id}")
# xuechong 2026-07-18 预览双层PDF文件
async def preview_dual_layer_record(record_id: str, request: Request):
    """预览双层PDF文件"""
    scope = _dl_scope(request)
    record = None
    for r in scope.dual_layer_history:
        if r.get("id") == record_id:
            record = r
            break

    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    output_files = record.get("output_files", [])
    if not output_files:
        raise HTTPException(status_code=404, detail="没有输出文件")

    # 返回第一个PDF文件用于预览
    first_file = Path(output_files[0])
    if not first_file.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        path=str(first_file),
        media_type="application/pdf"
    )

@router.get("/api/dual-layer/download/{record_id}")
# xuechong 2026-07-18 下载双层PDF文件或打包下载（用户隔离）
async def download_dual_layer_record(record_id: str, request: Request):
    """下载双层PDF文件或打包下载（用户隔离）"""
    from urllib.parse import quote

    # xuechong 2026-07-16 用户隔离：从 scope 读取
    scope = _dl_scope(request)
    record = None
    for r in scope.dual_layer_history:
        if r.get("id") == record_id:
            record = r
            break

    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    output_files = record.get("output_files", [])
    if not output_files:
        raise HTTPException(status_code=404, detail="没有输出文件")

    # 单个文件直接下载
    if len(output_files) == 1:
        file_path = Path(output_files[0])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        
        filename = file_path.name
        encoded_filename = quote(filename, safe='')
        
        return FileResponse(
            path=str(file_path),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="output.pdf"; filename*=UTF-8\'\'{encoded_filename}'
            }
        )
    
    # 多个文件打包下载
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path_str in output_files:
            file_path = Path(file_path_str)
            if file_path.exists():
                # 使用相对路径作为ZIP内的文件名
                arc_name = file_path.name
                zf.write(file_path, arc_name)
    
    zip_buffer.seek(0)
    zip_content = zip_buffer.read()
    
    zip_name = f"{record.get('name', 'output')}_双层PDF.zip"
    encoded_zip_name = quote(zip_name, safe='')
    
    return Response(
        content=zip_content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="output.zip"; filename*=UTF-8\'\'{encoded_zip_name}'
        }
    )