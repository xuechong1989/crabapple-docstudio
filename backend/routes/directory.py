# -*- coding: utf-8 -*-
"""directory API"""
from typing import Dict, List
import os, shutil, uuid, time as _time, io
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.services.app_state import state
from backend.services.path_service import STORAGE_ROOT, MONITOR_SOURCE_DIR, MONITOR_TARGET_DIR
from backend.services.logging_service import log_info
from backend.services.ws_service import sync_log, log_manager
from backend.services.image_utils import is_image_file, SUPPORTED_EXTENSIONS
import backend.services.history_service as _hsvc

import cv2
import numpy as np
from PIL import Image
import fitz

router = APIRouter(tags=["directory"])

# ============================================================

def build_directory_tree(root_path: Path, base_path: Path = None) -> dict:
    """
    构建目录树结构
    
    Args:
        root_path: 要扫描的根目录
        base_path: 用于计算相对路径的基准目录
    
    Returns:
        目录树字典
    """
    if base_path is None:
        base_path = root_path
    
    if not root_path.exists():
        return {"name": root_path.name, "type": "directory", "children": [], "path": str(root_path)}
    
    result = {
        "name": root_path.name,
        "type": "directory",
        "path": str(root_path),
        "relative_path": str(root_path.relative_to(base_path)) if root_path != base_path else "",
        "children": []
    }
    
    try:
        items = sorted(root_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        for item in items:
            if item.is_dir():
                result["children"].append(build_directory_tree(item, base_path))
            else:
                # 只显示支持的文件类型
                suffix = item.suffix.lower()
                if suffix in SUPPORTED_EXTENSIONS or suffix == '.pdf':
                    result["children"].append({
                        "name": item.name,
                        "type": "file",
                        "path": str(item),
                        "relative_path": str(item.relative_to(base_path)),
                        "extension": suffix,
                        "size": item.stat().st_size
                    })
    except PermissionError as e:
        log_info(f"[目录遍历] 权限不足, 无法访问目录: {e}")
    
    return result

@router.get("/api/directory-tree")
# xuechong 2026-07-18 获取源目录的目录树结构（用户隔离）
async def get_directory_tree(request: Request):
# xuechong 2026-07-18 获取源目录的目录树结构（用户隔离）
    """获取源目录的目录树结构（用户隔离）"""
    # xuechong 2026-07-18 使用用户 scope 的源目录
    from backend.services.user_scope import get_user_scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    source_dir = scope.source_dir

    await log_manager.add_log("INFO", "获取目录树", {"path": str(source_dir)})

    # 确保目录存在
    source_dir.mkdir(parents=True, exist_ok=True)

    tree = build_directory_tree(source_dir)

    return {
        "source_dir": str(source_dir),
        "target_dir": str(scope.target_dir),
        "tree": tree
    }

@router.get("/api/directory-info")
# xuechong 2026-07-18 获取监控目录信息（用户隔离）
async def get_directory_info(request: Request):
# xuechong 2026-07-18 获取监控目录信息（用户隔离）
    """获取监控目录信息（用户隔离）"""
    # xuechong 2026-07-18 使用用户 scope 的目录
    from backend.services.user_scope import get_user_scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    return {
        "source_dir": str(scope.source_dir),
        "target_dir": str(scope.target_dir),
        "source_exists": scope.source_dir.exists(),
        "target_exists": scope.target_dir.exists()
    }

# ============================================================
# 文件预览 API（新页面功能）
# ============================================================

@router.get("/api/file/preview")
# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 文件预览添加用户隔离
async def preview_local_file(path: str, request: Request = None):
    """
    预览本地文件（图片或 PDF）
    TIF/TIFF 文件会自动转换为 PNG 格式进行预览
    
    Args:
        path: 文件的绝对路径
    """
    from fastapi.responses import Response
    
    file_path = Path(path)
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题
    # 安全检查：优先使用用户 scope 目录验证，回退到全局监控目录（兼容无token场景）
    from backend.services.user_scope import get_user_scope, get_all_usernames
    username = getattr(request.state, 'username', None) if request else None
    path_allowed = False
    if username:
        scope = get_user_scope(username)
        # 允许访问用户自己的目录
        for user_dir in [scope.source_dir, scope.target_dir, scope.upload_dir, scope.output_dir]:
            try:
                file_path.resolve().relative_to(user_dir.resolve())
                path_allowed = True
                break
            except ValueError:
                continue
    # 回退：全局监控目录（兼容无token的图片请求）
    if not path_allowed:
        try:
            file_path.resolve().relative_to(MONITOR_SOURCE_DIR.resolve())
            path_allowed = True
        except ValueError:
            try:
                file_path.resolve().relative_to(MONITOR_TARGET_DIR.resolve())
                path_allowed = True
            except ValueError:
                pass
    if not path_allowed:
        raise HTTPException(status_code=403, detail="无权访问此文件")
    
    # 根据文件类型返回
    suffix = file_path.suffix.lower()
    
    # TIF/TIFF 文件特殊处理：转换为 PNG 预览
    if suffix in {'.tif', '.tiff'}:
        try:
            # 使用 PIL 读取 TIFF 文件
            with Image.open(str(file_path)) as img:
                # 转换为 RGB 模式（如果是 RGBA 或其他模式）
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                # 转换为 PNG 格式的字节流
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='PNG')
                img_byte_arr.seek(0)

                return Response(
                    content=img_byte_arr.getvalue(),
                    media_type="image/png"
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TIF文件转换失败: {str(e)}")
    
    # 其他格式直接返回
    if suffix in {'.png', '.jpg', '.jpeg'}:
        media_type = f"image/{suffix[1:]}"
    elif suffix in {'.bmp'}:
        media_type = "image/bmp"
    elif suffix in {'.webp'}:
        media_type = "image/webp"
    elif suffix == '.pdf':
        media_type = "application/pdf"
    else:
        media_type = "application/octet-stream"
    
    return FileResponse(path=str(file_path), media_type=media_type)

# ============================================================
# 单文件清洁处理 API（新页面功能）
# ============================================================

class CleanFileRequest(BaseModel):
    source_path: str
    task_id: str = ""  # 任务ID，用于解析相对路径
    save_to_source: bool = True  # 是否保存到源目录（覆盖原文件）

@router.post("/api/file/clean")
# xuechong 2026-07-18 清洁单个文件并保存（用户隔离）
async def clean_single_file(request: CleanFileRequest, req: Request = None):
# xuechong 2026-07-18 清洁单个文件并保存（用户隔离）
    """
    清洁单个文件并保存（用户隔离）
    直接替换原文件，保持原格式不变，输出文件大小与原图相似

    Args:
        source_path: 源文件路径（相对或绝对路径）
        task_id: 任务ID，用于将相对路径解析为绝对路径
        save_to_source: 是否覆盖原文件保存（始终为True，直接替换原图）
    """
    # xuechong 2026-07-21 研发BUG-0009 路径校验：优先检查用户 scope 目录，回退到 STORAGE_ROOT
    from backend.services.user_scope import get_user_scope
    username = getattr(req.state, 'username', None) if req else None
    scope = get_user_scope(username) if username else None

    # 如果提供了 task_id，使用任务的 upload_dir 解析相对路径
    if request.task_id and scope and request.task_id in scope.upload_tasks:
        upload_dir = Path(scope.upload_tasks[request.task_id]["upload_dir"])
        source_path = (upload_dir / request.source_path).resolve()
    else:
        source_path = Path(request.source_path).resolve()
    # 路径校验：有用户时仅允许用户 scope 目录，无用户时回退 STORAGE_ROOT
    path_allowed = False
    if scope:
        for user_dir in [scope.source_dir, scope.target_dir, scope.upload_dir, scope.output_dir]:
            try:
                source_path.relative_to(user_dir.resolve())
                path_allowed = True
                break
            except ValueError:
                continue
    else:
        # 无token场景（兼容旧版客户端），回退到 STORAGE_ROOT
        try:
            source_path.relative_to(STORAGE_ROOT.resolve())
            path_allowed = True
        except ValueError:
            pass
    if not path_allowed:
        raise HTTPException(status_code=403, detail="无权访问指定路径")

    if not source_path.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")
    
    if not is_image_file(source_path.name):
        raise HTTPException(status_code=400, detail="不支持的文件格式")
    
    # 获取原图文件大小
    original_size = source_path.stat().st_size
    
    await log_manager.add_log("INFO", f"开始清洁文件: {source_path.name} (原大小: {original_size / 1024:.1f}KB)")

    try:
        # 备份原图（与批量修图保持一致，支持还原）
        if request.task_id and scope and request.task_id in scope.upload_tasks:
            upload_dir = Path(scope.upload_tasks[request.task_id]["upload_dir"])
            backup_dir = upload_dir / "_backup"
            rel_path = source_path.relative_to(upload_dir)
            backup_path = backup_dir / rel_path
            if not backup_path.exists():
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, backup_path)

        # 读取图片
        image = cv2.imdecode(np.fromfile(str(source_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(status_code=400, detail="无法读取图片文件")
        
        # 处理图片
        cleaner = _hsvc.get_cleaner()
        result = cleaner.process(image, debug=False, dpi=_hsvc.get_image_dpi(source_path))

        # 直接替换原文件，保持原格式不变
        output_path = source_path  # 始终覆盖原文件
        processed_image = result['result']
        
        # 获取原图DPI
        source_dpi = _hsvc.get_image_dpi(source_path)
        
        # 使用保留DPI的函数保存图片
        _hsvc.save_image_with_dpi(processed_image, output_path, dpi=source_dpi, 
                          quality=85, target_size=original_size)
        
        # 获取输出文件大小
        output_size = output_path.stat().st_size
        
        await log_manager.add_log("SUCCESS", f"文件清洁完成: {output_path.name}", {
            "skew_angle": result.get('skew_angle', 0),
            "output_path": str(output_path),
            "original_size": f"{original_size / 1024:.1f}KB",
            "output_size": f"{output_size / 1024:.1f}KB"
        })
        
        return {
            "success": True,
            "message": f"文件清洁完成 (原大小: {original_size / 1024:.1f}KB → {output_size / 1024:.1f}KB)",
            "output_path": str(output_path),
            "skew_angle": result.get('skew_angle', 0),
            "original_size": original_size,
            "output_size": output_size
        }
        
    except Exception as e:
        await log_manager.add_log("ERROR", f"文件清洁失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

# ============================================================
# 保存编辑后的图片 API
# ============================================================

class SaveEditedImageRequest(BaseModel):
    source_path: str
    image_data: str  # Base64 编码的图片数据（data:image/png;base64,...）

@router.post("/api/file/save-edited")
# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 添加用户隔离
async def save_edited_image(request: SaveEditedImageRequest, req: Request = None):
    """
    保存橡皮擦编辑后的图片，直接覆盖原文件（用户隔离）
    """
    import base64
    
    source_path = Path(request.source_path).resolve()
    # xuechong 2026-07-21 研发BUG-0009 用户隔离校验：有用户时仅允许用户 scope 目录
    from backend.services.user_scope import get_user_scope
    username = getattr(req.state, 'username', None) if req else None
    path_allowed = False
    if username:
        scope = get_user_scope(username)
        for user_dir in [scope.source_dir, scope.target_dir, scope.upload_dir, scope.output_dir]:
            try:
                source_path.relative_to(user_dir.resolve())
                path_allowed = True
                break
            except ValueError:
                continue
    else:
        # 无token场景（兼容旧版客户端），回退到 STORAGE_ROOT
        try:
            source_path.relative_to(STORAGE_ROOT.resolve())
            path_allowed = True
        except ValueError:
            pass
    if not path_allowed:
        raise HTTPException(status_code=403, detail="无权访问指定路径")

    if not source_path.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")

    # 获取原图文件大小用于压缩控制
    original_size = source_path.stat().st_size

    await log_manager.add_log("INFO", f"保存编辑图片: {source_path.name}")

    try:
        # 解析 base64 图片数据
        # 格式: data:image/png;base64,xxxx
        if ',' in request.image_data:
            header, data = request.image_data.split(',', 1)
        else:
            data = request.image_data
        
        # 解码 base64
        image_bytes = base64.b64decode(data)
        
        # 用 PIL 读取图片（防解压炸弹）
        from PIL import Image as PILImage
        max_pixels = 20000 * 20000
        old_max = PILImage.MAX_IMAGE_PIXELS
        PILImage.MAX_IMAGE_PIXELS = max_pixels
        img_buffer = io.BytesIO(image_bytes)
        try:
            pil_image = Image.open(img_buffer)
        finally:
            PILImage.MAX_IMAGE_PIXELS = old_max
        
        # 转换为 RGB（去除 alpha 通道）
        if pil_image.mode in ('RGBA', 'LA', 'P'):
            pil_image = pil_image.convert('RGB')
        
        # 根据原文件格式保存，控制输出大小
        suffix = source_path.suffix.lower()
        
        if suffix in {'.jpg', '.jpeg'}:
            # JPEG 格式：动态调整质量
            target_size = original_size
            quality = 85
            
            for attempt in range(5):
                output_buffer = io.BytesIO()
                pil_image.save(output_buffer, format='JPEG', quality=quality, optimize=True)
                current_size = output_buffer.tell()
                
                if current_size <= target_size * 1.1:
                    break
                    
                ratio = target_size / current_size
                quality = max(30, min(95, int(quality * ratio)))
            
            output_buffer.seek(0)
            with open(source_path, 'wb') as f:
                f.write(output_buffer.read())
                
        elif suffix == '.png':
            # PNG 格式
            pil_image.save(str(source_path), format='PNG', optimize=True)
            
        elif suffix in {'.tif', '.tiff'}:
            # TIF 格式
            pil_image.save(str(source_path), format='TIFF', compression='tiff_lzw')
            
        elif suffix == '.webp':
            # WEBP 格式
            target_size = original_size
            quality = 85
            
            for attempt in range(5):
                output_buffer = io.BytesIO()
                pil_image.save(output_buffer, format='WEBP', quality=quality)
                current_size = output_buffer.tell()
                
                if current_size <= target_size * 1.1:
                    break
                    
                ratio = target_size / current_size
                quality = max(30, min(100, int(quality * ratio)))
            
            output_buffer.seek(0)
            with open(source_path, 'wb') as f:
                f.write(output_buffer.read())
        else:
            # 其他格式保存为 PNG
            pil_image.save(str(source_path), format='PNG')
        
        output_size = source_path.stat().st_size
        
        await log_manager.add_log("SUCCESS", f"编辑图片已保存: {source_path.name}", {
            "original_size": f"{original_size / 1024:.1f}KB",
            "output_size": f"{output_size / 1024:.1f}KB"
        })
        
        return {
            "success": True,
            "message": f"保存成功 (原大小: {original_size / 1024:.1f}KB → {output_size / 1024:.1f}KB)",
            "output_path": str(source_path)
        }
        
    except Exception as e:
        await log_manager.add_log("ERROR", f"保存编辑图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")

# ============================================================
# 批量转换 API（新页面功能）
# ============================================================

class BatchConvertRequest(BaseModel):
    folder_path: str  # 要处理的文件夹路径
    output_format: str = "pdf"  # 输出格式：pdf 或 image
    add_page_number: bool = True  # 是否添加页码，默认添加

# xuechong 2026-07-20 研发BUG-0009 BUG3: batch_tasks 已迁移到 UserScope（scope.batch_tasks），用户隔离

@router.post("/api/batch/convert")
async def batch_convert(request: BatchConvertRequest, background_tasks: BackgroundTasks, req: Request = None):
    """
    批量转换文件夹下的所有图片
    
    Args:
        folder_path: 文件夹路径
        output_format: 输出格式（pdf/image）
    """
    # xuechong 2026-07-20 研发BUG-0009 BUG3: 获取当前用户 scope（用户隔离）
    from backend.services.user_scope import get_user_scope
    username = getattr(req.state, 'username', None) if req else None
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)

    folder_path = Path(request.folder_path).resolve()
    # xuechong 2026-07-21 研发BUG-0009 路径穿越防护：必须在用户目录范围内
    path_in_user_dir = False
    for user_dir in [scope.source_dir, scope.target_dir, scope.upload_dir, scope.output_dir]:
        try:
            folder_path.relative_to(user_dir.resolve())
            path_in_user_dir = True
            break
        except ValueError:
            continue
    if not path_in_user_dir:
        raise HTTPException(status_code=403, detail="无权访问指定路径")

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail="文件夹不存在")
    
    if not folder_path.is_dir():
        raise HTTPException(status_code=400, detail="路径不是文件夹")
    
    # 收集所有图片文件（使用 set 去重，避免 Windows 大小写不敏感导致重复）
    image_files_set = set()
    for ext in SUPPORTED_EXTENSIONS:
        image_files_set.update(folder_path.glob(f"*{ext}"))
        image_files_set.update(folder_path.glob(f"*{ext.upper()}"))
    
    if not image_files_set:
        raise HTTPException(status_code=400, detail="文件夹中没有图片文件")
    
    # 排序
    image_files = sorted(image_files_set, key=lambda x: x.name.lower())
    
    # 创建批量任务
    task_id = str(uuid.uuid4())[:8]
    
    # 计算输出目录（保持相对路径结构）
    # xuechong 2026-07-20 研发BUG-0009 BUG3: 使用当前用户 scope 的目录
    try:
        relative_path = folder_path.relative_to(scope.source_dir)
        output_folder = scope.target_dir / relative_path
    except ValueError:
        output_folder = scope.target_dir / folder_path.name
    
    output_folder.mkdir(parents=True, exist_ok=True)
    
    scope.batch_tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0,
        "total_files": len(image_files),
        "processed_files": 0,
        "current_file": "",
        "message": "等待处理...",
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "output_folder": str(output_folder),
        "output_files": [],
        "username": username  # xuechong 2026-07-18 用于下载历史用户隔离
    }
    
    await log_manager.add_log("INFO", f"创建批量任务 {task_id}", {
        "folder": str(folder_path),
        "file_count": len(image_files)
    })
    
    # 启动后台处理（xuechong 2026-07-20 BUG3: 传递 username 供后台函数定位 scope）
    background_tasks.add_task(
        process_batch_convert,
        task_id,
        username,
        image_files,
        output_folder,
        request.output_format,
        request.add_page_number
    )
    
    return {
        "task_id": task_id,
        "file_count": len(image_files),
        "output_folder": str(output_folder),
        "message": f"已创建批量任务，共 {len(image_files)} 个文件"
    }

def process_single_file(args):
    """处理单个文件（图片清洁 + OCR + 转双层PDF）"""
    file_path, output_folder, output_format, cleaner, task_id, jpeg_quality, max_dimension, idx = args
    
    try:
        if not file_path.exists():
            return None, None
        
        # 获取原文件大小（用于智能压缩）
        original_size_kb = file_path.stat().st_size / 1024
        file_ext = file_path.suffix.lower()
        
        # 获取图像DPI（在清洁处理前获取）
        image_dpi = _hsvc.get_image_dpi(file_path)
        
        # 读取图片
        image = cv2.imdecode(np.fromfile(str(file_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None, f"无法读取: {file_path.name}"
        
        # 图片清洁、净化处理
        result = cleaner.process(image, debug=False, dpi=image_dpi)
        cleaned_image = result['result']
        
        if output_format == "pdf":
            # 根据原文件格式和内部压缩方式计算目标大小
            # 关键修复：检测TIF文件内部是否已经使用有损压缩（如JPEG）
            tif_already_compressed = False
            if file_ext in ['.tif', '.tiff']:
                try:
                    from PIL import Image as PILImage
                    with PILImage.open(str(file_path)) as pil_img:
                        if pil_img.format == "TIFF" and hasattr(pil_img, 'tag_v2'):
                            compression = pil_img.tag_v2.get(259, 1)  # 259 = Compression tag
                            # 压缩类型：6=JPEG旧版, 7=JPEG新版, 34712=JPEG2000
                            if compression in [6, 7, 34712]:
                                tif_already_compressed = True
                except Exception as e:
                    log_info(f"[TIF压缩检测] 检测TIF压缩类型失败: {e}")
            
            # 根据文件类型和压缩状态决定目标大小
            if file_ext in ['.tif', '.tiff', '.bmp']:
                if tif_already_compressed:
                    # TIF内部已经是JPEG压缩：保持原大小，避免二次压缩损失
                    target_size_kb = original_size_kb * 1.0
                    log_info(f"  [批处理] {file_path.name}: TIF内部已JPEG压缩，保持原大小 {original_size_kb:.0f}KB")
                else:
                    # 真正的无损格式：适度压缩到50%
                    img_h, img_w = cleaned_image.shape[:2]
                    target_size_kb = original_size_kb * 0.50
                    min_size_kb = max(200, (img_w * img_h) / 1024 / 10)
                    target_size_kb = max(target_size_kb, min_size_kb)
                    log_info(f"  [批处理] {file_path.name}: 无损TIF压缩 {original_size_kb:.0f}KB -> {target_size_kb:.0f}KB")
            elif file_ext == '.png':
                target_size_kb = original_size_kb * 0.7
                target_size_kb = max(target_size_kb, 100)
                log_info(f"  [批处理] {file_path.name}: PNG压缩 {original_size_kb:.0f}KB -> {target_size_kb:.0f}KB")
            else:
                target_size_kb = original_size_kb * 1.0
                log_info(f"  [批处理] {file_path.name}: 保持原大小 {original_size_kb:.0f}KB")
            
            log_info(f"  [批处理] {file_path.name}: DPI={image_dpi}")
            
            # 清洁后的图片转双层PDF（包含OCR文字层，保留原始DPI）
            # 使用索引序号命名，避免同名stem不同扩展名导致PDF覆盖
            pdf_path = output_folder / f"_page_{idx:04d}.pdf"
            pdf_success = _hsvc.image_to_searchable_pdf(cleaned_image, pdf_path, target_size_kb=target_size_kb, dpi=image_dpi)
            
            if pdf_success:
                return pdf_path, None
        else:
            # 保存为图片（保留原图DPI，使用索引序号避免stem冲突）
            output_path = output_folder / f"{file_path.stem}_{idx:04d}_cleaned.jpg"
            _hsvc.save_image_with_dpi(cleaned_image, output_path, dpi=image_dpi, quality=jpeg_quality)
            return output_path, None
            
    except Exception as e:
        return None, f"处理失败 {file_path.name}: {str(e)}"
    
    return None, None

def process_batch_convert(task_id: str, username: str, image_files: List[Path], output_folder: Path, output_format: str, add_page_number: bool = True):
    """后台批量转换处理（串行处理，避免PaddleOCR多线程冲突）"""
    # xuechong 2026-07-20 研发BUG-0009 BUG3: 从用户 scope 获取任务
    from backend.services.user_scope import get_user_scope
    scope = get_user_scope(username)
    task = scope.batch_tasks[task_id]
    task["add_page_number"] = add_page_number  # 保存到任务状态
    
    # 压缩配置（优化速度）
    JPEG_QUALITY = 65  # JPEG 质量（降低以加速）
    MAX_DIMENSION = 1200  # 最大图片边长（降低以加速OCR）
    
    try:
        cleaner = _hsvc.get_cleaner()
        task["status"] = "processing"
        
        pdf_files = []
        output_files = []
        start_time = _time.time()
        total_files = len(image_files)
        
        # 按文件名排序，确保顺序正确
        sorted_files = sorted(image_files, key=lambda x: x.name.lower())
        
        sync_log("INFO", f"[{task_id}] 开始处理 {total_files} 个文件（串行处理，避免OCR冲突）")
        
        # 串行处理每个文件（PaddleOCR 不支持多线程并行）
        for idx, file_path in enumerate(sorted_files):
            # 检查任务是否被停止
            if task.get("status") == "stopped":
                sync_log("WARNING", f"[{task_id}] 任务已被用户停止")
                return
            
            processed_count = idx + 1
            task["current_file"] = file_path.name
            task["message"] = f"正在处理: {file_path.name} ({processed_count}/{total_files})"
            task["processed_files"] = processed_count
            task["progress"] = int(processed_count / total_files * 90)
            
            # 每5个文件发送一次进度日志（减少日志输出以提升速度）
            if processed_count % 5 == 1 or processed_count == total_files:
                sync_log("INFO", f"[{task_id}] 处理进度: {processed_count}/{total_files}")
            
            # 处理单个文件
            args = (file_path, output_folder, output_format, cleaner, task_id, JPEG_QUALITY, MAX_DIMENSION, idx)
            try:
                result_path, error = process_single_file(args)
                if error:
                    sync_log("ERROR", f"[{task_id}] {error}")
                elif result_path:
                    if output_format == "pdf":
                        pdf_files.append(result_path)
                    output_files.append(result_path.name)
            except Exception as e:
                import traceback
                error_detail = traceback.format_exc()
                sync_log("ERROR", f"[{task_id}] 处理异常 {file_path.name}: {str(e)}")
                sync_log("ERROR", f"[{task_id}] 异常详情:\n{error_detail}")
                task["status"] = "failed"
                task["message"] = f"处理异常已停止: {file_path.name} - {str(e)}"
                task["completed_at"] = datetime.now().isoformat()
                return
        
        task["output_files"] = output_files
        
        # 检查任务是否被停止
        if task.get("status") == "stopped":
            sync_log("WARNING", f"[{task_id}] 任务已被用户停止")
            return
        
        # 检查是否所有文件都处理成功
        if len(pdf_files) != total_files:
            sync_log("WARNING", f"[{task_id}] 警告：{total_files} 个图片中有 {total_files - len(pdf_files)} 个处理失败")
        
        sync_log("INFO", f"[{task_id}] 成功生成 {len(pdf_files)} 个PDF文件，准备合并...")
        
        # 如果是 PDF 格式，合并所有 PDF
        merged_pdf_path = None
        first_image_name = sorted_files[0].stem if sorted_files else task_id
        
        if output_format == "pdf" and len(pdf_files) > 1:
            task["message"] = "正在合并 PDF..."
            task["progress"] = 92
            sync_log("INFO", f"[{task_id}] 合并 {len(pdf_files)} 个 PDF（按文件名顺序）")
            
            merged_pdf_path = output_folder / f"{first_image_name}.pdf"
            temp_merged_path = output_folder / f"_merged_{task_id}.pdf"
            
            # 合并PDF到临时文件（根据参数决定是否添加页码）
            _hsvc.merge_pdfs_to_single(pdf_files, temp_merged_path, add_page_number)
            
            # 删除单独的 PDF
            for pdf_file in pdf_files:
                if pdf_file.exists():
                    try:
                        pdf_file.unlink()
                    except Exception as e:
                        log_info(f"[文件清理] 删除临时PDF失败 {pdf_file.name}: {e}")
            
            # 重命名临时文件为最终文件名
            if temp_merged_path.exists():
                if merged_pdf_path.exists():
                    try:
                        merged_pdf_path.unlink()
                    except Exception as e:
                        log_info(f"[文件清理] 删除旧合并PDF失败 {merged_pdf_path.name}: {e}")
                temp_merged_path.rename(merged_pdf_path)
            
            sync_log("INFO", f"[{task_id}] 合并完成: {merged_pdf_path.name}")
            
        elif output_format == "pdf" and len(pdf_files) == 1:
            # 单个PDF重命名，根据参数决定是否添加页码
            merged_pdf_path = output_folder / f"{first_image_name}.pdf"
            
            try:
                doc = fitz.open(str(pdf_files[0]))
                if add_page_number:
                    _hsvc.add_page_numbers(doc)
                # zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题
                # 单文件PDF保存前子集化字库并回收旧全量字库流，避免单页PDF携带整份CJK字库
                from backend.services.pdf_font_service import save_pdf_with_font_subset
                save_pdf_with_font_subset(doc, merged_pdf_path)
                doc.close()
                if pdf_files[0] != merged_pdf_path and pdf_files[0].exists():
                    pdf_files[0].unlink()
            except Exception as e:
                log_info(f"[PDF保存] 保存合并PDF失败，回退为原文件: {e}")
                if pdf_files[0] != merged_pdf_path:
                    pdf_files[0].rename(merged_pdf_path)
        
        # 每个单独的PDF已经包含OCR文字层，合并后保持双层结构
        
        if merged_pdf_path:
            task["output_files"] = [merged_pdf_path.name]

        # 完成
        elapsed = _time.time() - start_time
        task["status"] = "completed"
        task["progress"] = 100
        task["completed_at"] = datetime.now().isoformat()

        if merged_pdf_path:
            task["merged_pdf"] = str(merged_pdf_path)

        # xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题 记录到用户 scope 的下载历史
        if merged_pdf_path and pdf_files:
            history_item = {
                "task_id": task_id,
                "folder_name": first_image_name or task_id,
                "first_image_name": first_image_name,
                "created_at": task["completed_at"],
                # xuechong 2026-10-06 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
                # 转换记录同任务打来源标记（嵌入页会话过滤据此放行演示链转换记录，与任务同款豁免）
                "source": task.get("source", ""),
                "pdf_path": str(merged_pdf_path),
                "file_count": len(pdf_files),
                "download_count": 0,
                "edited": False,
                "edit_download_count": 0
            }
            # xuechong 2026-07-20 研发BUG-0009 BUG3: 直接使用当前用户的 scope
            history_item["username"] = username
            scope.download_history.insert(0, history_item)
            scope.save_download_history()

        task["message"] = f"处理完成！共 {task['processed_files']} 个文件，耗时 {elapsed:.1f} 秒"

        sync_log("SUCCESS", f"[{task_id}] 批量任务完成", {
            "processed": task['processed_files'],
            "elapsed": f"{elapsed:.1f}s",
            "output_folder": str(output_folder)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        task["status"] = "failed"
        task["message"] = f"处理失败: {str(e)}"
        task["completed_at"] = datetime.now().isoformat()
        sync_log("ERROR", f"[{task_id}] 批量任务失败: {str(e)}")

@router.get("/api/batch/status/{task_id}")
async def get_batch_status(task_id: str, request: Request):
    """获取批量任务状态（用户隔离）"""
    # xuechong 2026-07-20 研发BUG-0009 BUG3: 从当前用户 scope 查询
    from backend.services.user_scope import get_user_scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    if task_id not in scope.batch_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    return scope.batch_tasks[task_id]

@router.get("/api/batch/tasks")
async def list_batch_tasks(request: Request):
    """列出当前用户的批量任务（用户隔离）"""
    # xuechong 2026-07-20 研发BUG-0009 BUG3: 从当前用户 scope 查询
    from backend.services.user_scope import get_user_scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    return list(scope.batch_tasks.values())

@router.post("/api/batch/stop/{task_id}")
async def stop_batch_task(task_id: str, request: Request):
    """
    停止批量任务
    
    Args:
        task_id: 任务ID
    """
    # xuechong 2026-07-20 研发BUG-0009 BUG3: 从当前用户 scope 查询
    from backend.services.user_scope import get_user_scope
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    if task_id not in scope.batch_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task = scope.batch_tasks[task_id]
    
    if task["status"] in ["completed", "failed", "stopped"]:
        return {"success": True, "message": "任务已结束"}
    
    # 标记任务为停止状态
    task["status"] = "stopped"
    task["message"] = "用户手动停止"
    task["completed_at"] = datetime.now().isoformat()
    
    await log_manager.add_log("WARNING", f"任务 {task_id} 已被用户停止")
    
    return {"success": True, "message": "任务已停止"}

# ============================================================
# 目录配置 API
# ============================================================

class DirConfigRequest(BaseModel):
    path: str

@router.get("/api/browse-dirs")
# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 添加用户隔离
async def browse_directories(path: str = "", request: Request = None):
    """
    浏览目录结构，用于目录选择器（用户隔离）
    
    Args:
        path: 要浏览的目录路径，为空则返回用户根目录下的子目录
    """
    import string
    from backend.services.user_scope import get_user_scope
    
    # xuechong 2026-07-21 研发BUG-0009 获取当前用户 scope
    username = getattr(request.state, 'username', None) if request else None
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)
    
    result = {
        "current_path": path,
        "parent_path": "",
        "directories": []
    }
    
    if not path:
        # xuechong 2026-07-21 研发BUG-0009 默认返回用户根目录下的子目录
        user_root = scope.user_root.resolve()
        result["current_path"] = str(user_root)
        try:
            dirs = []
            for item in sorted(user_root.iterdir(), key=lambda x: x.name.lower()):
                if item.is_dir() and not item.name.startswith('.'):
                    dirs.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "folder"
                    })
            result["directories"] = dirs
        except PermissionError:
            result["directories"] = []
            result["error"] = "权限不足，无法访问此目录"
        return result
    
    target_path = Path(path).resolve()
    # xuechong 2026-07-21 研发BUG-0009 路径必须在用户目录范围内
    try:
        target_path.relative_to(scope.user_root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问指定路径")
    
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="目录不存在")
    
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail="路径不是目录")
    
    result["current_path"] = str(target_path)
    
    # 获取父目录
    parent = target_path.parent
    if parent != target_path:
        result["parent_path"] = str(parent)
    
    # 列出子目录
    try:
        dirs = []
        for item in sorted(target_path.iterdir(), key=lambda x: x.name.lower()):
            if item.is_dir() and not item.name.startswith('.'):
                dirs.append({
                    "name": item.name,
                    "path": str(item),
                    "type": "folder"
                })
        result["directories"] = dirs
    except PermissionError:
        result["directories"] = []
        result["error"] = "权限不足，无法访问此目录"
    
    return result

@router.post("/api/config/source-dir")
# xuechong 2026-07-18 设置源目录（用户隔离）
async def set_source_dir(request: DirConfigRequest, req: Request = None):
# xuechong 2026-07-18 设置源目录（用户隔离）
    """
    设置源目录（用户隔离）

    Args:
        path: 新的源目录路径
    """
    # xuechong 2026-07-18 使用用户 scope
    from backend.services.user_scope import get_user_scope
    username = getattr(req.state, 'username', None) if req else None
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)

    new_path = Path(request.path).resolve()

    # 路径安全校验：必须在用户目录范围内
    try:
        new_path.relative_to(scope.user_root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="目录必须在用户数据目录范围内")

    if not new_path.exists():
        try:
            new_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"无法创建目录: {str(e)}")

    if not new_path.is_dir():
        raise HTTPException(status_code=400, detail="路径不是有效目录")

    scope.source_dir = new_path

    await log_manager.add_log("INFO", f"源目录已更新", {"path": str(new_path)})

    return {"success": True, "path": str(new_path)}

@router.post("/api/config/target-dir")
# xuechong 2026-07-18 设置输出目录（用户隔离）
async def set_target_dir(request: DirConfigRequest, req: Request = None):
# xuechong 2026-07-18 设置输出目录（用户隔离）
    """
    设置输出目录（用户隔离）

    Args:
        path: 新的输出目录路径
    """
    # xuechong 2026-07-18 使用用户 scope
    from backend.services.user_scope import get_user_scope
    username = getattr(req.state, 'username', None) if req else None
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    scope = get_user_scope(username)

    new_path = Path(request.path).resolve()

    # 路径安全校验：必须在用户目录范围内
    try:
        new_path.relative_to(scope.user_root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="目录必须在用户数据目录范围内")

    if not new_path.exists():
        # 尝试创建目录
        try:
            new_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"无法创建目录: {str(e)}")

    if not new_path.is_dir():
        raise HTTPException(status_code=400, detail="路径不是有效目录")

    scope.target_dir = new_path

    await log_manager.add_log("INFO", f"输出目录已更新", {"path": str(new_path)})

    return {"success": True, "path": str(new_path)}
