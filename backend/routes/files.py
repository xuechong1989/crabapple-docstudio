# -*- coding: utf-8 -*-
# xuechong 2026-07-18 研发BUG-0009-图档扫描-用户隔离机制问题 files API（重构版）
"""files API — 所有文件操作通过用户 scope 隔离"""
import shutil
import asyncio
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks, Response, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.services.logging_service import log_info
from backend.services.image_utils import SUPPORTED_EXTENSIONS
from backend.services.user_scope import get_user_scope
import backend.services.history_service as _hsvc

import cv2
import numpy as np

router = APIRouter(tags=["files"])


# xuechong 2026-07-18 从请求获取当前用户的 scope
def _get_scope(request: Request):
# xuechong 2026-07-18 从请求获取当前用户的 scope
    """从请求获取当前用户的 scope，无 token 则 401"""
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return get_user_scope(username)

# ============================================================

@router.post("/api/rotate-image/{task_id}")
# xuechong 2026-07-18 旋转图片并保存（用户隔离）
async def rotate_image(
# xuechong 2026-07-18 旋转图片并保存（用户隔离）
    task_id: str,
    path: str,
    direction: str = "right",
    request: Request = None
):
    """
    旋转图片并保存（用户隔离）

    Args:
        task_id: 任务ID
        path: 图片相对路径
        direction: 旋转方向，"left" 表示逆时针90度，"right" 表示顺时针90度
    """
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])
    file_path = upload_dir / path
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 安全检查：确保路径在上传目录内
    try:
        file_path.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问此文件")

    # 检查是否是图片文件
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    try:
        from PIL import Image

        # 备份原图（如果还没有备份）
        backup_dir = upload_dir / "_backup"
        rel_path = file_path.relative_to(upload_dir)
        backup_path = backup_dir / rel_path
        
        if not backup_path.exists():
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, backup_path)
            log_info(f"[旋转] 已备份原图: {backup_path}")
        
        # 获取原图DPI
        image_dpi = _hsvc.get_image_dpi(file_path)
        
        # 打开图片并旋转（transpose 会立即加载像素数据）
        with Image.open(str(file_path)) as img:
            # 根据方向旋转
            if direction == "left":
                # 逆时针旋转90度 = 顺时针旋转270度
                rotated = img.transpose(Image.Transpose.ROTATE_90)
                angle_str = "逆时针90度"
            else:
                # 顺时针旋转90度 = 逆时针旋转270度
                rotated = img.transpose(Image.Transpose.ROTATE_270)
                angle_str = "顺时针90度"
        
        # 保存旋转后的图片（保留原图格式和DPI）
        if suffix in {'.jpg', '.jpeg'}:
            rotated.save(str(file_path), "JPEG", quality=95, dpi=(image_dpi, image_dpi))
        elif suffix == '.png':
            rotated.save(str(file_path), "PNG", dpi=(image_dpi, image_dpi))
        elif suffix in {'.tif', '.tiff'}:
            rotated.save(str(file_path), "TIFF", dpi=(image_dpi, image_dpi))
        elif suffix == '.bmp':
            rotated.save(str(file_path), "BMP", dpi=(image_dpi, image_dpi))
        elif suffix == '.webp':
            rotated.save(str(file_path), "WEBP", quality=95)
        else:
            rotated.save(str(file_path))
        
        log_info(f"[旋转] 图片已旋转 {angle_str}: {file_path.name}")
        
        return {
            "success": True,
            "message": f"图片已{angle_str}旋转并保存",
            "path": path,
            "direction": direction
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"旋转失败: {str(e)}")


@router.post("/api/redraw-image/{task_id}")
# xuechong 2026-07-18 图片重绘：调整像素深浅（用户隔离）
async def redraw_image(
# xuechong 2026-07-18 图片重绘：调整像素深浅（用户隔离）
    task_id: str,
    path: str,
    direction: str = "enhance",
    step: int = 10,
    request: Request = None
):
    """
    图片重绘：调整像素深浅

    Args:
        task_id: 任务ID
        path: 图片相对路径
        direction: "enhance"=加深(像素值减小), "weaken"=变浅(像素值增大)
        step: 调整幅度（1-255），默认10
    """
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])
    file_path = upload_dir / path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        file_path.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问此文件")

    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    step = max(1, min(255, step))

    try:
        # 备份原图（如果还没有备份）
        backup_dir = upload_dir / "_backup"
        rel_path = file_path.relative_to(upload_dir)
        backup_path = backup_dir / rel_path

        if not backup_path.exists():
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, backup_path)
            log_info(f"[重绘] 已备份原图: {backup_path}")

        # 获取原图DPI
        image_dpi = _hsvc.get_image_dpi(file_path)

        # 读取图片
        image = cv2.imdecode(np.fromfile(str(file_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(status_code=400, detail="无法读取图片文件")

        # 像素调整（纯白像素不动）
        # 创建掩码：非纯白像素（任一通道<255）才参与调整
        white_mask = np.any(image < 255, axis=2)  # True = 非纯白
        if direction == "enhance":
            # 加深：像素值减小
            adjusted = cv2.subtract(image, np.full_like(image, step))
            msg = f"图片已加深（步长{step}）并保存"
        else:
            # 变浅：像素值增大
            adjusted = cv2.add(image, np.full_like(image, step))
            msg = f"图片已变浅（步长{step}）并保存"
        # 纯白像素还原
        white_pixels = ~white_mask
        adjusted[white_pixels] = [255, 255, 255]

        # 保存（保留DPI）
        _hsvc.save_image_with_dpi(adjusted, file_path, dpi=image_dpi, quality=95)

        log_info(f"[重绘] {msg}: {file_path.name}")

        return {
            "success": True,
            "message": msg,
            "path": path,
            "direction": direction,
            "step": step
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"重绘失败: {str(e)}")


# xuechong 2026-07-18 一键修图：批量净化所选目录下所有图片
@router.post("/api/batch-clean/{task_id}")
async def batch_clean_images(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    selected_path: str = ""
):
    """一键修图：批量净化所选目录下所有图片"""
    scope = _get_scope(request)
    # xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 开始修图的拒绝分支补日志：拒绝只返回400/404时前端弹"修图失败"框而两系统日志均无记录
    task = scope.upload_tasks.get(task_id)
    if not task:
        log_info(f"[一键修图{task_id}] 拒绝开始修图：任务不存在")
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.get("clean_status") == "processing":
        log_info(f"[一键修图{task_id}] 拒绝开始修图：修图任务正在处理中（上一修图尚未结束）")
        raise HTTPException(status_code=400, detail="修图任务正在处理中")

    if not selected_path:
        log_info(f"[一键修图{task_id}] 拒绝开始修图：请选择要处理的目录")
        raise HTTPException(status_code=400, detail="请选择要处理的目录")

    upload_dir = Path(task["upload_dir"])
    selected_dir = (upload_dir / selected_path)

    # 路径穿越防护
    try:
        selected_dir.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无效的目录路径")

    if not selected_dir.exists():
        raise HTTPException(status_code=400, detail=f"选中的目录不存在: {selected_path}")

    if not selected_dir.is_dir():
        raise HTTPException(status_code=400, detail="请选择目录，而不是文件")

    has_subdirs = any(item.is_dir() and item.name != "_backup" for item in selected_dir.iterdir())
    if has_subdirs:
        raise HTTPException(status_code=400, detail="选中的目录包含子目录，请选择只包含图片文件的目录")

    # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
    # 断点续跑判定：上次同一目录修图被中断（clean_status=interrupted）→ 保留已完成清单续跑；
    # 其余情况（新目录/已完成后重跑/失败重跑）→ 清空清单从头处理，行为与历史版本一致
    resumable = (
        task.get("clean_status") == "interrupted"
        and task.get("clean_selected_path") == selected_path
        and isinstance(task.get("clean_done_files"), list)
    )
    done_count = len(task["clean_done_files"]) if resumable else 0
    if not resumable:
        task["clean_done_files"] = []

    # 初始化修图状态
    task["clean_status"] = "processing"
    task["clean_progress"] = 0
    task["clean_current_file"] = ""
    task["clean_message"] = f"断点续跑（已有 {done_count} 张完成）..." if resumable else "正在初始化..."
    task["clean_selected_path"] = selected_path
    task["clean_processed_files"] = 0
    task["images_cleaned"] = False
    scope.tasks_cancel_flags.pop(task_id, None)

    # xuechong 2026-07-18 后台执行（传入 username 以便任务函数使用用户 scope）
    username = scope.username
    background_tasks.add_task(batch_clean_images_task, task_id, username)

    return {"success": True, "message": "开始一键修图", "task_id": task_id, "selected_path": selected_path}


# xuechong 2026-07-18 后台执行批量图片净化任务（用户隔离）
async def batch_clean_images_task(task_id: str, username: str = "admin"):
# xuechong 2026-07-18 后台执行批量图片净化任务（用户隔离）
    """后台执行批量图片净化任务（用户隔离）"""
    scope = get_user_scope(username)
    task = scope.upload_tasks.get(task_id)
    if not task:
        log_info(f"[一键修图{task_id}] 任务不存在")
        return
    upload_dir = Path(task["upload_dir"])
    selected_path = task.get("clean_selected_path", "")
    
    try:
        cleaner = _hsvc.get_cleaner()
        
        target_dir = upload_dir / selected_path if selected_path else upload_dir
        backup_dir = upload_dir / "_backup"
        
        # 获取所有图片文件
        image_files = []
        for item in target_dir.iterdir():
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                image_files.append(item)
        
        image_files = sorted(image_files, key=lambda x: str(x).lower())
        total_files = len(image_files)

        if total_files == 0:
            task["clean_status"] = "failed"
            task["clean_message"] = "没有找到图片文件"
            return

        # xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
        # 清洁开始日志（范围+总数）：form-in智能收集整理页步骤2过程信息区按此展示本次清洁整体范围
        log_info(f"[一键修图{task_id}] 开始：共 {total_files} 张图片，目录：{selected_path if selected_path else '任务根目录'}")

        # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
        # 断点续跑：已处理清单（相对路径集合，仅保留当前批次仍存在的文件），重跑时直接跳过；
        # unreadable_count 统计无法读取被跳过的图片，完成消息中向用户说明口径
        valid_set = {str(p.relative_to(upload_dir)) for p in image_files}
        done_files = set(task.get("clean_done_files") or []) & valid_set
        task["clean_done_files"] = sorted(done_files)
        success_count = len(done_files)
        unreadable_count = 0
        # xuechong 2026-07-03 获取事件循环（在线程池中执行 CPU 密集操作，释放 GIL 避免阻塞 HTTP 请求处理）
        loop = asyncio.get_running_loop()

        for idx, image_path in enumerate(image_files):
            # 检查取消标志（用户 scope 内）
            if scope.tasks_cancel_flags.get(task_id, False):
                task["clean_status"] = "cancelled"
                task["clean_message"] = f"修图已停止 ({success_count}/{total_files} 张已完成)"
                task["clean_completed_at"] = datetime.now().isoformat()
                scope.tasks_cancel_flags.pop(task_id, None)
                log_info(f"[一键修图{task_id}] user={username} 已取消: {success_count}/{total_files}")
                # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
                # 终态落盘：取消状态持久化，重启后可断点续跑
                scope.save_tasks()
                return

            processed_count = idx + 1

            # 计算相对路径（用于备份）
            rel_path = image_path.relative_to(upload_dir)

            # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
            # 断点续跑：上次中断前已完成的文件跳过（不重复处理）
            if str(rel_path) in done_files:
                log_info(f"[一键修图{task_id}] 断点跳过已完成: {rel_path} ({processed_count}/{total_files})")
                task["clean_processed_files"] = processed_count
                task["clean_progress"] = int(processed_count / total_files * 100)
                task["clean_message"] = f"断点跳过已完成: {image_path.name} ({processed_count}/{total_files})"
                continue

            # 先更新进度消息（表示开始处理）
            task["clean_message"] = f"正在修图: {image_path.name} ({processed_count}/{total_files})"

            try:
                # xuechong 2026-07-03 读取原图（在线程池中执行，释放GIL避免阻塞事件循环）
                image = await loop.run_in_executor(
                    None,
                    lambda: cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
                )
                if image is None:
                    log_info(f"[一键修图{task_id}] 无法读取图片: {image_path.name}")
                    unreadable_count += 1
                    continue

                # 备份原图（如果还没有备份）
                backup_path = backup_dir / rel_path
                if not backup_path.exists():
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(image_path, backup_path)

                # xuechong 2026-07-03 执行净化处理（在线程池中执行，释放GIL避免阻塞事件循环）
                image_dpi = _hsvc.get_image_dpi(backup_path)  # 从备份文件读取原图DPI
                result = await loop.run_in_executor(
                    None,
                    lambda: cleaner.process(image, debug=False, dpi=image_dpi)
                )
                cleaned_image = result['result']

                # xuechong 2026-07-03 保存净化后的图片（在线程池中执行，释放GIL避免阻塞事件循环）
                await loop.run_in_executor(
                    None,
                    lambda: _hsvc.save_image_with_dpi(cleaned_image, image_path, dpi=image_dpi, quality=95)
                )
                
                success_count += 1

                # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
                # 断点清单：记录已完成文件
                done_files.add(str(rel_path))
                task["clean_done_files"] = sorted(done_files)

                # 处理完成后，更新状态（前端可以显示处理完成的图片）
                task["clean_current_file"] = image_path.name
                task["clean_current_path"] = str(rel_path)  # 已处理完成的图片路径
                task["clean_processed_files"] = processed_count
                task["clean_progress"] = int(processed_count / total_files * 100)
                # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
                # 每张落盘：进度+断点清单持久化，服务重启可断点续跑
                scope.save_tasks()
                # xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
                # 逐张完成日志（带 N/M 计数）：form-in智能收集整理页步骤2过程信息区按此实时展示
                # 清洁逐张进度，普通直接使用模式只是日志文件多几行，功能行为不变
                log_info(f"[一键修图{task_id}] 已完成 {processed_count}/{total_files}：{image_path.name}")

            except Exception as e:
                import traceback
                error_detail = traceback.format_exc()
                # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
                # 用户确认：单张异常必须整批立即停止（PDF已注定不可用）；
                # 日志与任务消息补强：失败文件完整相对路径 + 完整堆栈
                log_info(f"[一键修图{task_id}] 处理异常(整批停止): 相对路径={rel_path} 文件={image_path.name} - {str(e)}")
                log_info(f"[一键修图{task_id}] 异常详情:\n{error_detail}")
                task["clean_status"] = "failed"
                task["clean_message"] = f"修图异常已停止: {rel_path} - {str(e)}（已完成 {success_count}/{total_files} 张）"
                task["clean_completed_at"] = datetime.now().isoformat()
                scope.save_tasks()
                return

        # 所有图片处理完成
        task["clean_status"] = "completed"
        task["clean_progress"] = 100
        task["clean_message"] = f"修图完成: {success_count}/{total_files} 张图片" + (
            f"（{unreadable_count} 张无法读取被跳过）" if unreadable_count else "")
        task["clean_completed_at"] = datetime.now().isoformat()
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-001 修图完成后置位，生成PDF时复用净化结果跳过重复清洁
        task["images_cleaned"] = True
        task["cleaned_path"] = selected_path
        log_info(f"[一键修图{task_id}] 完成: {success_count}/{total_files} 张图片, images_cleaned=True, cleaned_path={selected_path}")
        # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
        # 终态落盘：完成状态与断点清单持久化（重启后 REQ-001 复用优化不失效）
        scope.save_tasks()

    except Exception as e:
        import traceback
        traceback.print_exc()
        task["clean_status"] = "failed"
        task["clean_message"] = f"修图失败: {str(e)}"
        task["clean_completed_at"] = datetime.now().isoformat()
        # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
        # 终态落盘：失败状态持久化
        try:
            scope.save_tasks()
        except Exception as save_err:
            log_info(f"[一键修图{task_id}] 失败状态落盘异常: {save_err}")


@router.get("/api/batch-clean-status/{task_id}")
# xuechong 2026-07-18 获取一键修图任务状态
async def get_batch_clean_status(task_id: str, request: Request = None):
# xuechong 2026-07-18 获取一键修图任务状态
    """获取一键修图任务状态"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return {
        "task_id": task_id,
        "status": task.get("clean_status", "idle"),
        "progress": task.get("clean_progress", 0),
        "current_file": task.get("clean_current_file", ""),
        "current_path": task.get("clean_current_path", ""),
        "message": task.get("clean_message", ""),
        "processed_files": task.get("clean_processed_files", 0),
        "images_cleaned": task.get("images_cleaned", False),
        "cleaned_path": task.get("cleaned_path", "")
    }


# xuechong 2026-07-18 批量图片重绘（用户隔离）
@router.post("/api/batch-redraw/{task_id}")
async def batch_redraw_images(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    selected_path: str = "",
    direction: str = "enhance",
    step: int = 10
):
    """批量图片重绘"""
    scope = _get_scope(request)
    # xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 开始重绘的拒绝分支补日志（同一键修图口径：拒绝必须留痕，两系统日志可追溯）
    task = scope.upload_tasks.get(task_id)
    if not task:
        log_info(f"[批量重绘{task_id}] 拒绝开始重绘：任务不存在")
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.get("redraw_status") == "processing":
        log_info(f"[批量重绘{task_id}] 拒绝开始重绘：重绘任务正在处理中（上一重绘尚未结束）")
        raise HTTPException(status_code=400, detail="重绘任务正在处理中")

    if not selected_path:
        log_info(f"[批量重绘{task_id}] 拒绝开始重绘：请选择要处理的目录")
        raise HTTPException(status_code=400, detail="请选择要处理的目录")

    upload_dir = Path(task["upload_dir"])
    selected_dir = (upload_dir / selected_path)

    try:
        selected_dir.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的目录路径")

    if not selected_dir.exists():
        raise HTTPException(status_code=400, detail=f"选中的目录不存在: {selected_path}")
    if not selected_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"选中的路径不是目录: {selected_path}")

    image_files = [item for item in selected_dir.iterdir() if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS]
    if not image_files:
        raise HTTPException(status_code=400, detail="选中的目录中没有图片文件")

    step = max(1, min(255, step))

    task["redraw_status"] = "processing"
    task["redraw_progress"] = 0
    task["redraw_current_file"] = ""
    task["redraw_current_path"] = ""
    task["redraw_message"] = "正在启动批量重绘..."
    task["redraw_processed_files"] = 0
    task["redraw_selected_path"] = selected_path
    task["redraw_direction"] = direction
    task["redraw_step"] = step
    task["redraw_completed_at"] = None

    background_tasks.add_task(batch_redraw_images_task, task_id, scope.username)

    return {
        "success": True,
        "message": f"批量重绘已启动，共 {len(image_files)} 张图片",
        "total_files": len(image_files)
    }


# xuechong 2026-07-18 后台执行批量图片重绘任务（用户隔离）
def batch_redraw_images_task(task_id: str, username: str = "admin"):
# xuechong 2026-07-18 后台执行批量图片重绘任务（用户隔离）
    """后台执行批量图片重绘任务（用户隔离）"""
    import time as _time

    scope = get_user_scope(username)
    task = scope.upload_tasks.get(task_id)
    if not task:
        log_info(f"[批量重绘{task_id}] 任务不存在")
        return
    upload_dir = Path(task["upload_dir"])
    selected_path = task.get("redraw_selected_path", "")
    direction = task.get("redraw_direction", "enhance")
    step = task.get("redraw_step", 10)

    try:
        target_dir = upload_dir / selected_path if selected_path else upload_dir
        backup_dir = upload_dir / "_backup"

        # 获取所有图片文件
        image_files = []
        for item in target_dir.iterdir():
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                image_files.append(item)

        image_files = sorted(image_files, key=lambda x: str(x).lower())
        total_files = len(image_files)

        if total_files == 0:
            task["redraw_status"] = "failed"
            task["redraw_message"] = "没有找到图片文件"
            return

        start_time = _time.time()
        success_count = 0

        for idx, image_path in enumerate(image_files):
            # xuechong 2026-06-01 检查取消标志，支持用户在批量重绘过程中取消任务
            if scope.tasks_cancel_flags.get(task_id, False):
                task["redraw_status"] = "cancelled"
                task["redraw_message"] = f"批量重绘已取消 ({success_count}/{total_files} 张已完成)"
                task["redraw_completed_at"] = datetime.now().isoformat()
                scope.tasks_cancel_flags.pop(task_id, None)
                log_info(f"[批量重绘{task_id}] user={username} 已取消: {success_count}/{total_files}")
                return

            processed_count = idx + 1

            rel_path = image_path.relative_to(upload_dir)

            task["redraw_message"] = f"正在重绘: {image_path.name} ({processed_count}/{total_files})"

            try:
                image = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    log_info(f"[批量重绘{task_id}] 无法读取图片: {image_path.name}")
                    continue

                # 备份原图（如果还没有备份）
                backup_path = backup_dir / rel_path
                if not backup_path.exists():
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(image_path, backup_path)

                image_dpi = _hsvc.get_image_dpi(backup_path)

                # 像素调整（纯白像素不动）
                white_mask = np.any(image < 255, axis=2)
                if direction == "enhance":
                    adjusted = cv2.subtract(image, np.full_like(image, step))
                else:
                    adjusted = cv2.add(image, np.full_like(image, step))
                white_pixels = ~white_mask
                adjusted[white_pixels] = [255, 255, 255]

                _hsvc.save_image_with_dpi(adjusted, image_path, dpi=image_dpi, quality=95)

                success_count += 1

                task["redraw_current_file"] = image_path.name
                task["redraw_current_path"] = str(rel_path)
                task["redraw_processed_files"] = processed_count
                task["redraw_progress"] = int(processed_count / total_files * 100)

            except Exception as e:
                import traceback
                error_detail = traceback.format_exc()
                log_info(f"[批量重绘{task_id}] 处理异常: {image_path.name} - {str(e)}")
                log_info(f"[批量重绘{task_id}] 异常详情:\n{error_detail}")
                task["redraw_status"] = "failed"
                task["redraw_message"] = f"批量重绘异常已停止: {image_path.name} - {str(e)}"
                task["redraw_completed_at"] = datetime.now().isoformat()
                return

        elapsed_time = _time.time() - start_time
        dir_text = "加深" if direction == "enhance" else "变浅"
        task["redraw_status"] = "completed"
        task["redraw_progress"] = 100
        task["redraw_message"] = f"批量{dir_text}完成！成功处理 {success_count}/{total_files} 张图片，耗时 {elapsed_time:.1f}秒"
        task["redraw_completed_at"] = datetime.now().isoformat()

    except Exception as e:
        import traceback
        traceback.print_exc()
        task["redraw_status"] = "failed"
        task["redraw_message"] = f"批量重绘失败: {str(e)}"
        task["redraw_completed_at"] = datetime.now().isoformat()


@router.get("/api/batch-redraw-status/{task_id}")
# xuechong 2026-07-18 获取批量重绘任务状态（用户隔离）
async def get_batch_redraw_status(task_id: str, request: Request = None):
# xuechong 2026-07-18 获取批量重绘任务状态（用户隔离）
    """获取批量重绘任务状态（用户隔离）"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "task_id": task_id,
        "status": task.get("redraw_status", "idle"),
        "progress": task.get("redraw_progress", 0),
        "current_file": task.get("redraw_current_file", ""),
        "current_path": task.get("redraw_current_path", ""),
        "message": task.get("redraw_message", ""),
        "processed_files": task.get("redraw_processed_files", 0),
        "direction": task.get("redraw_direction", "enhance"),
        "step": task.get("redraw_step", 10)
    }


@router.get("/api/preview-cleaned/{task_id}")
# xuechong 2026-07-18 预览净化后的图片（实时净化处理）
async def preview_cleaned_file(task_id: str, path: str, request: Request = None):
# xuechong 2026-07-18 预览净化后的图片（实时净化处理）
    """预览净化后的图片（实时净化处理）"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])
    file_path = upload_dir / path
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    try:
        file_path.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问此文件")

    try:
        image = cv2.imdecode(np.fromfile(str(file_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(status_code=400, detail="无法读取图片文件")
        
        cleaner = _hsvc.get_cleaner()
        result = cleaner.process(image, debug=False, dpi=_hsvc.get_image_dpi(file_path))
        cleaned_image = result['result']

        _, buffer = cv2.imencode('.png', cleaned_image)
        
        return Response(content=buffer.tobytes(), media_type="image/png")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片净化失败: {str(e)}")


from pydantic import Field

class ManualEditRequest(BaseModel):
    image_data: str = Field(..., description="Base64编码的图片数据")

@router.post("/api/save-manual-edit/{task_id}")
# xuechong 2026-07-18 保存手动修图结果（用户隔离）
async def save_manual_edit(task_id: str, path: str, body: ManualEditRequest, request: Request = None):
# xuechong 2026-07-18 保存手动修图结果（用户隔离）
    """保存手动修图结果（先备份原图，再替换）"""
    import base64
    from PIL import Image
    import io
    
    image_data = body.image_data
    
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])
    original_path = upload_dir / path
    
    if not original_path.exists():
        raise HTTPException(status_code=404, detail="原文件不存在")
    
    try:
        original_path.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问此文件")

    try:
        backup_dir = upload_dir / "_backup"
        backup_path = backup_dir / path
        
        if not backup_path.exists():
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original_path, backup_path)
        
        if ',' in image_data:
            _, data = image_data.split(',', 1)
        else:
            data = image_data
        
        image_bytes = base64.b64decode(data)

        # 防范 decompression bomb：限制解压后图片最大像素数
        from PIL import Image as PILImage
        max_pixels = 20000 * 20000  # 4亿像素上限
        old_max = PILImage.MAX_IMAGE_PIXELS
        PILImage.MAX_IMAGE_PIXELS = max_pixels

        img_buffer = io.BytesIO(image_bytes)
        try:
            pil_image = Image.open(img_buffer)
        finally:
            PILImage.MAX_IMAGE_PIXELS = old_max

        if pil_image.mode in ('RGBA', 'LA', 'P'):
            pil_image = pil_image.convert('RGB')
        
        suffix = original_path.suffix.lower()
        
        if suffix in {'.jpg', '.jpeg'}:
            pil_image.save(str(original_path), format='JPEG', quality=95, optimize=True)
        elif suffix == '.png':
            pil_image.save(str(original_path), format='PNG', optimize=True)
        elif suffix in {'.tif', '.tiff'}:
            pil_image.save(str(original_path), format='TIFF', compression='tiff_lzw')
        elif suffix == '.webp':
            pil_image.save(str(original_path), format='WEBP', quality=95)
        elif suffix == '.bmp':
            pil_image.save(str(original_path), format='BMP')
        else:
            pil_image.save(str(original_path), format='PNG')
        
        return {
            "success": True,
            "message": "修图已保存",
            "path": path,
            "has_backup": True
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


@router.post("/api/restore-image/{task_id}")
# xuechong 2026-07-18 还原为原始上传的图片（用户隔离）
async def restore_image(task_id: str, path: str, request: Request = None):
# xuechong 2026-07-18 还原为原始上传的图片（用户隔离）
    """还原为原始上传的图片"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])
    original_path = upload_dir / path
    backup_dir = upload_dir / "_backup"
    backup_path = backup_dir / path
    
    try:
        original_path.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问此文件")

    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="没有可还原的备份")
    
    try:
        shutil.copy2(backup_path, original_path)
        try:
            # xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：unlink 包装到线程池
            await asyncio.to_thread(backup_path.unlink)
        except OSError as e:
            log_info(f"[备份还原] 删除备份文件失败 {backup_path.name}: {e}")
        
        try:
            if backup_dir.exists() and not any(backup_dir.iterdir()):
                backup_dir.rmdir()
        except Exception as e:
            log_info(f"[备份还原] 清理空备份目录失败: {e}")
        
        return {
            "success": True,
            "message": "图片已还原为原图",
            "path": path
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"还原失败: {str(e)}")


@router.get("/api/check-backup/{task_id}")
# xuechong 2026-07-18 检查图片是否有备份可还原
async def check_backup(task_id: str, path: str, request: Request = None):
# xuechong 2026-07-18 检查图片是否有备份可还原
    """检查图片是否有备份可还原"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])
    backup_dir = upload_dir / "_backup"
    backup_path = (backup_dir / path)

    # 路径穿越防护
    try:
        backup_path.resolve().relative_to(backup_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问此文件")

    return {
        "has_backup": backup_path.exists(),
        "path": path
    }


@router.get("/api/preview-backup/{task_id}")
# xuechong 2026-07-18 预览备份的原图文件
async def preview_backup_file(task_id: str, path: str, request: Request = None):
# xuechong 2026-07-18 预览备份的原图文件
    """预览备份的原图文件"""
    scope = _get_scope(request)
    task = scope.upload_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    upload_dir = Path(task["upload_dir"])
    backup_dir = upload_dir / "_backup"
    backup_path = backup_dir / path
    
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="备份文件不存在")
    
    try:
        backup_path.resolve().relative_to(backup_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问此文件")

    suffix = backup_path.suffix.lower()
    
    # TIF 文件需要转换
    if suffix in {'.tif', '.tiff'}:
        try:
            from PIL import Image
            import io
            with Image.open(str(backup_path)) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='PNG')
                img_byte_arr.seek(0)
                return Response(content=img_byte_arr.getvalue(), media_type="image/png")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TIF文件转换失败: {str(e)}")
    
    # 其他格式直接返回
    if suffix in {'.png', '.jpg', '.jpeg'}:
        media_type = f"image/{suffix[1:]}"
    elif suffix == '.bmp':
        media_type = "image/bmp"
    elif suffix == '.webp':
        media_type = "image/webp"
    else:
        media_type = "application/octet-stream"
    
    return FileResponse(path=str(backup_path), media_type=media_type)

