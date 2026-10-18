# -*- coding: utf-8 -*-
# xuechong 2026-07-18 研发BUG-0009-图档扫描-用户隔离机制问题 edit_pdf API（重构版）
"""edit_pdf API — 所有编辑PDF操作通过用户 scope 隔离"""
from typing import List
import asyncio, re, shutil, uuid, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.services.path_service import STORAGE_ROOT
import backend.services.path_service as _psvc
from backend.services.logging_service import log_info
from backend.services.user_scope import get_user_scope
import backend.services.history_service as _hsvc

router = APIRouter(tags=["edit_pdf"])


# xuechong 2026-07-18 从请求获取当前用户的 scope
def _get_scope(request: Request):
    """从请求获取当前用户的 scope，无 token 则 401"""
    username = getattr(request.state, 'username', None)
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    return get_user_scope(username)


# xuechong 2026-07-18 根据 task_id 在所有用户 scope 中查找任务（仅限后台线程内部使用）
def _find_task_scope(task_id: str):
    """在所有用户 scope 中查找 edit_pdf 任务，返回 (task, scope) 或 (None, None)
    注意：此函数不做用户校验，仅供后台线程（无 request 上下文）使用"""
    from backend.services.user_scope import get_all_usernames
    for username in get_all_usernames():
        scope = get_user_scope(username)
        if task_id in scope.edit_pdf_tasks:
            return scope.edit_pdf_tasks[task_id], scope
    return None, None


# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题
# 带用户校验的任务查找（API 端点专用，防止跨用户访问）
def _find_task_scope_verified(task_id: str, request: Request):
    """在当前请求用户的 scope 中查找 edit_pdf 任务，防止跨用户访问"""
    scope = _get_scope(request)
    if task_id in scope.edit_pdf_tasks:
        return scope.edit_pdf_tasks[task_id], scope
    raise HTTPException(status_code=404, detail="任务不存在")


# xuechong 2026-07-18 根据 task_id 获取任务所属用户的 scope（用于后台线程写入历史）
def _scope_from_task(task_id: str):
    """根据 task_id 查找所属用户的 scope，未找到则返回 None"""
    _, scope = _find_task_scope(task_id)
    return scope

# ============================================================

# xuechong 2026-07-18 编辑PDF任务最大数量
_EDIT_PDF_MAX_TASKS = 20


# xuechong 2026-07-18 清理用户 scope 中最旧的编辑PDF任务
def _cleanup_old_edit_pdf_tasks(scope) -> None:
    if len(scope.edit_pdf_tasks) <= _EDIT_PDF_MAX_TASKS:
        return
    sorted_tasks = sorted(
        scope.edit_pdf_tasks.items(),
        key=lambda x: x[1].get("created_at", "")
    )
    to_remove = len(scope.edit_pdf_tasks) - _EDIT_PDF_MAX_TASKS
    for i in range(to_remove):
        old_task_id, old_task_info = sorted_tasks[i]
        old_task_dir = Path(old_task_info.get("task_dir", ""))
        if old_task_dir.exists():
            shutil.rmtree(old_task_dir, ignore_errors=True)
        del scope.edit_pdf_tasks[old_task_id]
        log_info(f"[编辑PDF] 已清理旧任务: {old_task_id}")


# xuechong 2026-07-18 构建安全的编辑PDF工作路径
# 文件实际存储在 TEMP_DIR/edit_pdf/（全局临时目录），任务所有权由 _find_task_scope 保证
def _safe_edit_pdf_path(scope, task_id: str, file_id: str, subpath: str) -> Path:
    base = (_psvc.TEMP_DIR / "edit_pdf").resolve()
    p = (base / task_id / file_id / subpath).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问指定路径")
    return p


# zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
# 任务/文件标识合法性校验：task_id/file_id 来自URL或请求体并参与磁盘路径拼接，
# 仅允许字母数字下划线连字符（服务端生成的形如 20260909_224854_fa967db0 / file_0），
# 从源头禁止相对父目录片段、盘符、分隔符等进入路径拼接
_EDIT_PDF_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')


def _validate_edit_pdf_ids(task_id: str, file_id: str) -> None:
    """校验 task_id/file_id 字符集合法，非法直接 400（防止路径拼接越界）"""
    if not task_id or not _EDIT_PDF_ID_PATTERN.match(task_id):
        raise HTTPException(status_code=400, detail="非法任务标识")
    if not file_id or not _EDIT_PDF_ID_PATTERN.match(file_id):
        raise HTTPException(status_code=400, detail="非法文件标识")


# zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
# per-file 页面渲染锁：防止"用户点开文件触发懒渲染"与"批量修图线程补渲染"并发
# 重复渲染同一文件（互相覆盖半成品）。锁字典按 task_id+file_id 寻址，惰性创建永不清理
# （锁对象极小，任务量级20个/用户，无泄漏风险）
_edit_pdf_render_locks = {}
_edit_pdf_render_locks_guard = threading.Lock()


def _get_edit_pdf_render_lock(task_id: str, file_id: str) -> threading.Lock:
    """获取指定文件的页面渲染锁（不存在则创建）"""
    key = f"{task_id}_{file_id}"
    with _edit_pdf_render_locks_guard:
        lock = _edit_pdf_render_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _edit_pdf_render_locks[key] = lock
        return lock


# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 操作内容类型常量：内容类操作（修图/OCR/页面编辑）成果沉淀在页面工作区，重建延续、
# 累计保留；成品类操作即处理配方激活项（去除空白页/添加页码/PDF瘦身），跟随当前配方
_OP_CONTENT = {"修图", "OCR", "页面编辑"}
_OP_TRANSFORM = {"去除空白页", "添加页码", "PDF瘦身"}

# 空白页判定按页缓存：key=f"{task_id}_{file_id}"，value={原始页索引: 是否空白}。
# 页面被编辑/修图时作废对应条目（保存页面=单页、修图=整文件），统一构建时只重判变动页
_edit_pdf_blank_cache = {}

# per-file 输出构建锁：防止并发下载/预览同时重建同一文件的 output_final.pdf
# （与渲染锁同模式：锁字典按 task_id+file_id 寻址，惰性创建永不清理）
_edit_pdf_build_locks = {}
_edit_pdf_build_locks_guard = threading.Lock()


def _get_edit_pdf_build_lock(task_id: str, file_id: str) -> threading.Lock:
    """获取指定文件的输出构建锁（不存在则创建）"""
    key = f"{task_id}_{file_id}"
    with _edit_pdf_build_locks_guard:
        lock = _edit_pdf_build_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _edit_pdf_build_locks[key] = lock
        return lock


# 处理配方文件名（存于 file_dir，随任务目录持久化/清理）
_EDIT_PDF_RECIPE_FILE = "process_recipe.json"


def _read_edit_pdf_recipe(file_dir: Path) -> dict:
    """读取处理配方（UTF-8无BOM）；缺失/损坏按无配方（全False）处理并记日志。

    返回结构：{remove_blank_pages, add_page_number, shrink, version, built_version, built_recipe}；
    version=内容版本号（保存页面/修图/OCR/一键处理时+1），built_version/built_recipe=上次
    构建时的版本与配方（复用判定依据：均未变且 output_final.pdf 存在则直接复用零重建）。
    """
    import json

    no_recipe = {
        "remove_blank_pages": False,
        "add_page_number": False,
        "shrink": False,
        "version": 0,
        "built_version": -1,
        "built_recipe": {"remove_blank_pages": False, "add_page_number": False, "shrink": False},
    }
    recipe_path = file_dir / _EDIT_PDF_RECIPE_FILE
    if not recipe_path.exists():
        return no_recipe
    try:
        data = json.loads(recipe_path.read_text(encoding="utf-8"))
        merged = dict(no_recipe)
        for key in merged:
            if key in data:
                merged[key] = data[key]
        return merged
    except Exception as e:
        log_info(f"[编辑PDF] 处理配方读取失败，按无配方处理: {recipe_path}, 错误: {e}")
        return no_recipe


def _write_edit_pdf_recipe(file_dir: Path, recipe: dict) -> None:
    """写处理配方到 process_recipe.json（UTF-8无BOM）"""
    import json

    (file_dir / _EDIT_PDF_RECIPE_FILE).write_text(
        json.dumps(recipe, ensure_ascii=False), encoding="utf-8"
    )


def _bump_edit_pdf_version(task_id: str, file_id: str) -> None:
    """内容版本号+1：任何影响输出内容的变化（保存页面/修图/OCR）调用，
    使下次统一构建自动重建（复用失效）。异步上下文调用方负责包装 asyncio.to_thread。
    并发安全：与统一构建的配方终写互斥（同持 per-file 构建锁），防止"读-改-写"丢失
    对方更新（丢失版本号会导致编辑后误复用旧成品）"""
    file_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / file_id
    with _get_edit_pdf_build_lock(task_id, file_id):
        recipe = _read_edit_pdf_recipe(file_dir)
        recipe["version"] = int(recipe.get("version", 0)) + 1
        _write_edit_pdf_recipe(file_dir, recipe)


def _invalidate_blank_cache(task_id: str, file_id: str, page_num: int = None) -> None:
    """作废空白页判定缓存：page_num 指定时只作废该页（保存页面场景），
    否则清空整个文件的缓存（修图场景：全部页面像素已变）"""
    key = f"{task_id}_{file_id}"
    if page_num is not None:
        cache = _edit_pdf_blank_cache.get(key)
        if cache is not None:
            cache.pop(page_num, None)
    else:
        _edit_pdf_blank_cache.pop(key, None)


def _active_transform_labels(recipe: dict) -> list:
    """按配方生成成品类操作标签列表（操作内容展示与记录合成用）"""
    labels = []
    if recipe.get("remove_blank_pages"):
        labels.append("去除空白页")
    if recipe.get("add_page_number"):
        labels.append("添加页码")
    if recipe.get("shrink"):
        labels.append("PDF瘦身")
    return labels


def _merge_edit_pdf_operations(old_operations, add_content_ops: list, transform_labels: list) -> list:
    """合成操作内容列表：旧内容类累计（去重保序）+ 本次新增内容类 + 当前配方激活项
    （成品类整体以当前配方为准，历史成品类项不保留——与文件真实状态一致）"""
    merged = []
    for op in list(old_operations or []):
        if op in _OP_CONTENT and op not in merged:
            merged.append(op)
    for op in add_content_ops:
        if op in _OP_CONTENT and op not in merged:
            merged.append(op)
    for op in transform_labels:
        if op in _OP_TRANSFORM and op not in merged:
            merged.append(op)
    return merged


def _get_edit_pdf_snapshot_path(scope, task_id: str, file_id: str) -> Path:
    """存档快照路径（users/{username}/edit_pdf/{task_id}_{file_id}.pdf，覆盖式一文件一份）；
    启用 user_scope 预留的 edit_pdf_dir——独立于任务目录，任务超上限清理不波及"""
    return scope.edit_pdf_dir / f"{task_id}_{file_id}.pdf"


def _count_edit_pdf_pages(task_id: str, file_id: str) -> int:
    """统计已渲染的页面数（page_N.png，排除 _backup 备份图）；路径由校验后的ID从可信根推导"""
    _validate_edit_pdf_ids(task_id, file_id)
    pages_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / file_id / "pages"
    if not pages_dir.exists():
        return 0
    return len([f for f in pages_dir.glob("page_*.png") if "_backup" not in f.name])


# zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
# 后台补渲机制整体移除（四轮回归结论）：懒渲染落地后其价值只剩"预付修图提取阶段"，
# 而大文件几乎总在被让位/中止，从未真正跑完；反而是首看竞争、线程池护航、机械盘
# 读写打崩三轮回归的共同源头。看图由按需渲染兜底，修图/OCR开工自渲（有进度提示）

# zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
# 主图优先通道：整页原图（page）渲染登记优先数，缩略图（thumb）渲染自旋让路——
# 文件首开时浏览器并发请求视口内全部缩略图+主图原图，若按到达顺序在渲染层排队，
# 主图要等约20张缩略图渲完才轮到（实测秒级）。优先通道保证主图先渲（用户视线焦点）
_edit_pdf_render_gate_lock = threading.Lock()
_edit_pdf_urgent_pending = 0


# zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _enter_edit_pdf_render_gate(kind: str) -> None:
    """进入按需渲染：page（主图）登记优先数立即放行；thumb 让路——先付250ms起步宽限
    （浏览器同拍并发主图+缩略图请求且缩略图DOM在前通常先到，宽限窗等主图到达登记
    优先数，否则在途缩略图渲染无法让路），再自旋等待优先数清零（50ms间隔，3秒防
    饿死兜底——极端情况下让路失效也不永久阻塞）"""
    global _edit_pdf_urgent_pending
    if kind == "page":
        with _edit_pdf_render_gate_lock:
            _edit_pdf_urgent_pending += 1
        return
    time.sleep(0.25)
    deadline = time.time() + 3.0
    while True:
        with _edit_pdf_render_gate_lock:
            if _edit_pdf_urgent_pending == 0:
                return
        if time.time() > deadline:
            return
        time.sleep(0.05)


# zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _exit_edit_pdf_render_gate(kind: str) -> None:
    """退出按需渲染：page 清除优先数（缩略图恢复通行）"""
    global _edit_pdf_urgent_pending
    if kind == "page":
        with _edit_pdf_render_gate_lock:
            _edit_pdf_urgent_pending -= 1


# zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
# 按需渲染专用线程池（page/thumb 分池）：此前渲染走 asyncio.to_thread 的共享默认
# 线程池（本机16工作线程），快速切换时约20张缩略图渲染（含闸门宽限的睡眠，占着
# 工作线程）把池占满，下一次切换的 recipe 接口（内部 to_thread）排队其后——对运行
# 中服务实测 recipe 从2ms劣化到722ms，遮罩停留。分池隔离：page池保主图渲染不在池
# 层面排队等缩略图；thumb池与共享池彻底分离，API元数据调用不再被渲染护航
_EDIT_PDF_PAGE_RENDER_WORKERS = 2
_EDIT_PDF_THUMB_RENDER_WORKERS = 4
_edit_pdf_page_render_executor = ThreadPoolExecutor(
    max_workers=_EDIT_PDF_PAGE_RENDER_WORKERS, thread_name_prefix="editpdf-page-render")
_edit_pdf_thumb_render_executor = ThreadPoolExecutor(
    max_workers=_EDIT_PDF_THUMB_RENDER_WORKERS, thread_name_prefix="editpdf-thumb-render")


# zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
async def _run_edit_pdf_render(task_id: str, file_id: str, page_num: int, kind: str) -> None:
    """图片端点按需渲染提交入口：page（主图原图）走 page 池，thumb（缩略图）走 thumb 池"""
    loop = asyncio.get_running_loop()
    pool = _edit_pdf_page_render_executor if kind == "page" else _edit_pdf_thumb_render_executor
    await loop.run_in_executor(pool, _ensure_edit_pdf_page_image, task_id, file_id, page_num, kind)


# zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _is_edit_pdf_pages_rendered(task_id: str, file_id: str) -> bool:
    """全量渲染完成哨兵判定：以 pages/dpi_info.json 存在为准——渲染函数全部页面写完后
    才写该文件，是现成的完成标志。禁止用 page_*.png 数量>0 判定：渲染逐页落盘，
    "渲染中途"（按需渲染/后台补渲进行中）数到部分页会误判完成，页面列表接口返回部分
    页数、一键处理跳过补渲染导致中途缺页"""
    pages_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / file_id / "pages"
    return (pages_dir / "dpi_info.json").exists()


# zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _atomic_save_pixmap(pix, final_path: Path) -> None:
    """像素图原子落盘：先写临时文件再 replace——按需渲染（无锁）与后台补渲（持文件锁）
    可能并发写同一页，内容确定性一致，原子替换保证读者永远看到完整文件不破图。
    临时文件名加唯一后缀（并发渲染同一页时确定性同名会互相抢replace，实测WinError 2）
    并保留原图片扩展名（pixmap 按扩展名推断编码格式，纯.tmp不被识别）。
    Windows下并发 replace 同一目标会间歇性 WinError 5（目标被并发改名锁定）：
    短重试串行化竞争；最终仍失败时若目标已被在途的另一方产出则视为成功，否则清理
    本临时文件抛出（端点按404处理，下次请求重渲）"""
    tmp_path = final_path.with_name(f"{final_path.stem}.tmp{uuid.uuid4().hex[:8]}{final_path.suffix}")
    pix.save(str(tmp_path))
    last_err = None
    for attempt in range(5):
        try:
            tmp_path.replace(final_path)
            return
        except OSError as e:
            last_err = e
            time.sleep(0.02 * (attempt + 1))
    if final_path.exists():
        # 并发的另一方已产出同内容目标文件，本份临时文件作废
        tmp_path.unlink(missing_ok=True)
        return
    tmp_path.unlink(missing_ok=True)
    raise last_err


# zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _get_page_render_dpi(pages_dir, page_num: int, orig_path) -> int:
    """获取修图用页面真实渲染DPI：优先读渲染时记录的 dpi_info.json。

    zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
    旧版本页面 PNG 的 pHYs 由 PyMuPDF 默认写 96（渲染侧已改为写入真实 DPI），
    存量页面文件按 get_image_dpi 仍读回 96，cleaner 字高判据被 _scale_r 等比缩小，
    页码词组保护失效导致页码被清（实测 pic3_p1/p3、pic4_p1）；
    dpi_info.json 是渲染时逐页探测登记的权威 DPI，优先取用，缺失再回退图片元数据。
    """
    import json
    try:
        info = json.loads((Path(pages_dir) / "dpi_info.json").read_text(encoding="utf-8"))
        dpi = int(info.get(str(page_num), 0))
        if dpi > 0:
            return dpi
    except Exception:
        pass
    return _hsvc.get_image_dpi(orig_path)


def _probe_edit_pdf_page_dpi(doc, page, page_idx: int) -> int:
    """探测页面内嵌图像的原始DPI（优先读内嵌图像DPI信息，无则按图像宽/页宽推算，夹72~600）
    ——从 _render_edit_pdf_pages 循环体原样抽出，全量渲染与按需渲染共用同一探测逻辑"""
    page_dpi = 300  # 默认DPI
    images = page.get_images()
    if images:
        try:
            xref = images[0][0]
            img_info = doc.extract_image(xref)
            if img_info:
                # 尝试从图像数据获取DPI
                from PIL import Image
                from io import BytesIO
                img_bytes = img_info.get("image")
                if img_bytes:
                    pil_img = Image.open(BytesIO(img_bytes))
                    dpi_info = pil_img.info.get('dpi')
                    if dpi_info and isinstance(dpi_info, tuple) and dpi_info[0] > 0:
                        page_dpi = int(dpi_info[0])
                    else:
                        # 根据图像尺寸和页面尺寸推算DPI
                        img_width = img_info.get("width", 0)
                        if img_width > 0:
                            # 页面宽度(点) / 72 * DPI = 图像宽度(像素)
                            # DPI = 图像宽度 * 72 / 页面宽度
                            page_dpi = int(img_width * 72 / page.rect.width)
                            page_dpi = max(72, min(600, page_dpi))  # 限制在合理范围
        except Exception as e:
            log_info(f"[编辑PDF] 获取页面 {page_idx} DPI失败: {e}")
    return page_dpi


# zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
# 同页按需渲染单飞登记：key=(task_id,file_id,page_num,kinds)，value=完成事件——
# 浏览器对同一图片URL的并发重复请求（如主图img+预取同时到达）不再重复渲染同一页，
# 后到者等待在途渲染完成后直接复用产物
_edit_pdf_render_inflight = {}
_edit_pdf_render_inflight_lock = threading.Lock()


# zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _render_edit_pdf_page_now(task_id: str, file_id: str, page_num: int, kinds: set) -> bool:
    """按需渲染单页指定产物（kinds ⊆ {thumb, page}，thumb=100px缩略图 / page=原DPI整页图），
    原子落盘。刻意不拿 per-file 渲染锁：按需渲染必须插队——后台补渲持锁渲整个文件期间
    （大文件可达分钟级），用户请求的页若排队等锁就退化为"等全量"，失去懒渲染意义；
    与补渲并发写同页时内容确定性一致+原子替换，无害。页码越界/无原PDF返回 False 不产出
    （调用方按文件不存在→404，与基线行为一致）。缩略图请求不做DPI探测（用不到且省时）。
    zhaoqiaotong 2026-09-17 同页单飞：在途渲染去重，后到者等事件后直接返回（产物
    存在性由调用方复核）"""
    import fitz

    if page_num < 0 or not kinds:
        return False
    _validate_edit_pdf_ids(task_id, file_id)

    # 同页单飞：已在渲则等待复用（在途失败时产物缺失由端点404兜底，下次请求重渲）
    inflight_key = (task_id, file_id, page_num, tuple(sorted(kinds)))
    with _edit_pdf_render_inflight_lock:
        inflight_ev = _edit_pdf_render_inflight.get(inflight_key)
        if inflight_ev is None:
            inflight_ev = threading.Event()
            _edit_pdf_render_inflight[inflight_key] = inflight_ev
            is_leader = True
        else:
            is_leader = False
    if not is_leader:
        inflight_ev.wait(timeout=10)
        return True

    try:
        file_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / file_id
        pdf_path = file_dir / "original.pdf"
        pages_dir = file_dir / "pages"
        if not pdf_path.exists():
            return False
        # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 主图优先通道：kind 含 page 视为主图渲染登记优先；纯 thumb 让路等待（首开时主图
        # 不再排在约20张视口缩略图后面，实测显著提前出图）
        primary_kind = "page" if "page" in kinds else "thumb"
        _enter_edit_pdf_render_gate(primary_kind)
        try:
            pages_dir.mkdir(exist_ok=True)
            doc = fitz.open(pdf_path)
            try:
                if page_num >= len(doc):
                    return False
                page = doc[page_num]
                page_dpi = 300
                if "page" in kinds:
                    page_dpi = _probe_edit_pdf_page_dpi(doc, page, page_num)
                if "thumb" in kinds:
                    # 生成缩略图 (100px宽)
                    scale = 100 / page.rect.width
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                    _atomic_save_pixmap(pix, pages_dir / f"thumb_{page_num}.png")
                if "page" in kinds:
                    # 生成原图（使用原DPI）
                    zoom = page_dpi / 72.0
                    pix_hd = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                    # zhaoqiaotong 2026-09-17 研发BUG-0060 页面PNG写入真实渲染DPI（防pHYs默认96）
                    pix_hd.set_dpi(page_dpi, page_dpi)
                    _atomic_save_pixmap(pix_hd, pages_dir / f"page_{page_num}.png")
                return True
            finally:
                doc.close()
        finally:
            _exit_edit_pdf_render_gate(primary_kind)
    finally:
        with _edit_pdf_render_inflight_lock:
            _edit_pdf_render_inflight.pop(inflight_key, None)
        inflight_ev.set()


# zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _ensure_edit_pdf_page_image(task_id: str, file_id: str, page_num: int, kind: str) -> None:
    """图片端点按需渲染入口（同步函数，供 asyncio.to_thread 调用避免阻塞事件循环）：
    目标产物缺失时当场渲染该页；越界/无PDF/渲染异常不产出，端点按"文件仍不存在"→404"""
    try:
        _render_edit_pdf_page_now(task_id, file_id, page_num, {kind})
    except Exception as e:
        log_info(f"[编辑PDF] 按需渲染页面产物失败（按404处理）: task_id={task_id}, file_id={file_id}, 页={page_num}, 类型={kind}, 错误: {e}")


def _render_edit_pdf_pages(task_id: str, file_id: str) -> int:
    """渲染PDF每页为页面图片（thumb_N.png 缩略图 + page_N.png 原DPI整页图 + dpi_info.json）

    逻辑取自 get_edit_pdf_file_pages 的懒渲染分支（研发需求-0166 缺陷修复抽出复用）：
    DPI 探测优先读页面内嵌图像的 DPI 信息，无则按图像宽/页宽推算，夹在 72~600。
    安全设计：不接收任何裸路径入参——入口校验ID字符集后，original.pdf 与 pages 目录
    全部由可信根（TEMP_DIR/edit_pdf/<task_id>/<file_id>）推导，构造上保证不出任务目录。
    返回渲染的页数。

    zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    两处增强：①单页产物已存在则跳过（按需渲染已渲过的页不重复劳动；服务中断后重渲
    只补缺失页，自愈加速）；②全部产物与哨兵 dpi_info.json 原子落盘（与按需渲染并发
    写同页时保证读者看到完整文件）。DPI 探测抽出为 _probe_edit_pdf_page_dpi 共用。
    """
    import fitz

    _validate_edit_pdf_ids(task_id, file_id)
    file_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / file_id
    pdf_path = file_dir / "original.pdf"
    pages_dir = file_dir / "pages"

    pages_dir.mkdir(exist_ok=True)

    doc = fitz.open(pdf_path)

    # 存储每页的DPI信息
    page_dpi_info = {}

    for i in range(len(doc)):
        page = doc[i]

        # 获取页面中图像的原始DPI（公共探测函数）
        page_dpi = _probe_edit_pdf_page_dpi(doc, page, i)

        # 保存DPI信息
        page_dpi_info[i] = page_dpi

        thumb_path = pages_dir / f"thumb_{i}.png"
        page_path = pages_dir / f"page_{i}.png"

        # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 单页产物已存在则跳过（按需渲染/中断重渲场景），DPI信息仍照常登记保证哨兵完整
        if thumb_path.exists() and page_path.exists():
            continue

        # 生成缩略图 (100px宽)
        if not thumb_path.exists():
            scale = 100 / page.rect.width
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            _atomic_save_pixmap(pix, thumb_path)

        # 生成原图（使用原DPI）
        if not page_path.exists():
            zoom = page_dpi / 72.0
            mat_hd = fitz.Matrix(zoom, zoom)
            pix_hd = page.get_pixmap(matrix=mat_hd)
            # zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
            # PyMuPDF get_pixmap 默认 xres/yres=96，pix.save 会把它写进 PNG pHYs；
            # 修图按 get_image_dpi 读回 96 导致 cleaner 字高判据被 _scale_r 等比缩小
            # （300DPI渲染 10px 判据在 dpi=96 下缩为 ~3px），页码词组保护失效。
            # 保存前写入真实渲染 DPI
            pix_hd.set_dpi(page_dpi, page_dpi)
            _atomic_save_pixmap(pix_hd, page_path)

        log_info(f"[编辑PDF] 页面 {i} 提取完成，DPI: {page_dpi}")

    # 保存DPI信息到文件（完成哨兵，原子写：全部页面产物落盘后才写，_is_edit_pdf_pages_rendered 依据）
    import json
    sentinel_tmp = pages_dir / "dpi_info.json.tmp"
    sentinel_tmp.write_text(json.dumps(page_dpi_info))
    sentinel_tmp.replace(pages_dir / "dpi_info.json")

    total = len(page_dpi_info)
    doc.close()
    return total


def _ensure_edit_pdf_pages_rendered(task_id: str, file_id: str) -> int:
    """确保页面已渲染：已渲染直接返回页数；未渲染则加锁渲染（锁内二次检查防并发重复）

    GET 上下文：渲染异常由 FastAPI 转 500；
    批量修图线程上下文：由 do_clean_all_pages 外层 try/except 捕获后进度标 failed。

    zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    完成判定由"page_*.png 数量>0"改为哨兵文件（_is_edit_pdf_pages_rendered）：
    渲染中途到达的并发请求不再被快路径误判为"已渲染"而返回部分页数，
    而是正确等锁到渲染完成后返回完整页数。
    """
    # 快路径：已渲染无需加锁（哨兵判定，渲染中途不误判）
    if _is_edit_pdf_pages_rendered(task_id, file_id):
        return _count_edit_pdf_pages(task_id, file_id)

    with _get_edit_pdf_render_lock(task_id, file_id):
        # 锁内二次检查：等待锁期间另一路（按需渲染触发的补渲/批量修图）可能已完成渲染
        if _is_edit_pdf_pages_rendered(task_id, file_id):
            return _count_edit_pdf_pages(task_id, file_id)
        return _render_edit_pdf_pages(task_id, file_id)


@router.post("/api/edit-pdf/upload-multiple")
# xuechong 2026-07-18 上传多个PDF文件用于编辑（用户隔离）
async def upload_edit_pdf_multiple(request: Request, files: List[UploadFile] = File(...)):
    """上传多个PDF文件用于编辑"""
    import fitz  # PyMuPDF
    
    if not files:
        raise HTTPException(status_code=400, detail="没有上传文件")
    
    # 只筛选PDF文件
    pdf_files = [f for f in files if f.filename.lower().endswith('.pdf')]
    
    if not pdf_files:
        raise HTTPException(status_code=400, detail="没有有效的PDF文件")
    
    # 创建任务目录
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    task_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    
    # 获取文件夹名称
    folder_name = ""
    if pdf_files[0].filename and '/' in pdf_files[0].filename:
        folder_name = pdf_files[0].filename.split('/')[0]
    if not folder_name:
        folder_name = f"PDF文件({len(pdf_files)}个)"
    
    file_list = []
    
    try:
        for idx, file in enumerate(pdf_files):
            file_id = f"file_{idx}"
            file_dir = task_dir / file_id
            file_dir.mkdir(exist_ok=True)
            
            # 获取文件名（去除路径）
            filename = file.filename.split('/')[-1] if '/' in file.filename else file.filename
            
            # 保存原始PDF（分块读取，限制大小）
            pdf_path = file_dir / "original.pdf"
            content_chunks = []
            total_read = 0
            # zhaoqiaotong 2026-09-02 研发BUG-0040-图档扫描-3.2.03-编辑PDF模块若干问题修复
            # 单文件限制由200MB放宽到1GB（用户持有大体积合法PDF），文案同步避免误导
            max_pdf_bytes = 1024 * 1024 * 1024  # 1GB 单文件限制
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > max_pdf_bytes:
                    raise HTTPException(status_code=413, detail=f"PDF文件 ({filename}) 超过大小限制 (1GB)")
                content_chunks.append(chunk)
            content = b"".join(content_chunks)
            with open(pdf_path, 'wb') as f:
                f.write(content)
            
            # 打开PDF获取页面数
            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)
            doc.close()
            
            file_list.append({
                "file_id": file_id,
                "filename": filename,
                "path": file.filename,
                "total_pages": total_pages
            })
        
        # xuechong 2026-07-18 保存任务到用户 scope
        scope = _get_scope(request)
        scope.edit_pdf_tasks[task_id] = {
            "folder_name": folder_name,
            "files": file_list,
            "task_dir": str(task_dir),
            "created_at": datetime.now().isoformat(),
            "username": scope.username
        }
        # xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：清理含 rmtree，包装到线程池
        await asyncio.to_thread(_cleanup_old_edit_pdf_tasks, scope)

        return {
            "success": True,
            "task_id": task_id,
            "folder_name": folder_name,
            "files": file_list
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 上传多个PDF失败: 文件数={len(files) if files else 0}, 错误: {e}")
        await asyncio.to_thread(shutil.rmtree, task_dir, True)
        raise HTTPException(status_code=500, detail=f"处理PDF失败: {str(e)}")


@router.post("/api/edit-pdf/import")
# xuechong 2026-07-18 从服务器已有路径导入PDF到编辑工作区
async def import_edit_pdf(request: Request):
    """从服务器已有路径导入PDF到编辑工作区（无需重新上传）"""
    import fitz  # PyMuPDF

    data = await request.json()
    pdf_path = (data.get("pdf_path") or "").strip()
    source_task_id = (data.get("task_id") or "").strip()
    source = (data.get("source") or "manual")

    # xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题
    # 通过 task_id 从当前用户 scope 的 download_history 查找 PDF 路径（禁止跨用户）
    if not pdf_path and source_task_id:
        username = getattr(request.state, 'username', None)
        if username:
            scope = get_user_scope(username)
            for item in scope.download_history:
                if item.get("task_id") == source_task_id:
                    pdf_path = item.get("pdf_path", "")
                    break

    if not pdf_path:
        # xuechong 2026-06-30 添加详细的错误日志
        log_info(f"[编辑PDF] 导入失败: 缺少 pdf_path 或 task_id 参数, source_task_id={source_task_id}, pdf_path={pdf_path}")
        raise HTTPException(status_code=400, detail="缺少 pdf_path 或 task_id 参数")

    # zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
    # 路径穿越防护前置加固：显式拒绝路径中的 .. 相对父目录片段（与下方 resolve+relative_to
    # 双层校验配合，杜绝规范化后仍指向 STORAGE_ROOT 之外的输入进入任何文件操作）
    if ".." in Path(pdf_path).parts:
        log_info(f"[编辑PDF] 导入拒绝含..片段的路径: pdf_path={pdf_path}")
        raise HTTPException(status_code=403, detail="无权访问指定路径")

    src = Path(pdf_path).resolve()
    # 路径穿越防护：仅允许访问 STORAGE_ROOT 内的文件
    try:
        src.relative_to(STORAGE_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="无权访问指定路径")

    if not src.exists():
        raise HTTPException(status_code=404, detail=f"PDF文件不存在: {pdf_path}")

    # 创建编辑工作区
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    file_id = "file_0"
    task_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id
    file_dir = task_dir / file_id
    file_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 复制文件到编辑工作区
        shutil.copy2(str(src), str(file_dir / "original.pdf"))

        # 获取页面数
        doc = fitz.open(str(file_dir / "original.pdf"))
        total_pages = len(doc)
        doc.close()

        filename = src.name

        file_list = [{
            "file_id": file_id,
            "filename": filename,
            "path": filename,
            "total_pages": total_pages
        }]

        scope = _get_scope(request)
        scope.edit_pdf_tasks[task_id] = {
            "folder_name": filename,
            "files": file_list,
            "task_dir": str(task_dir),
            "source": source,
            "source_task_id": source_task_id,
            "created_at": datetime.now().isoformat(),
            "username": scope.username
        }
        # xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：清理含 rmtree，包装到线程池
        await asyncio.to_thread(_cleanup_old_edit_pdf_tasks, scope)

        return {
            "success": True,
            "task_id": task_id,
            "folder_name": filename,
            "files": file_list
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 导入PDF失败: pdf_path={pdf_path}, 错误: {e}")
        await asyncio.to_thread(shutil.rmtree, task_dir, True)
        raise HTTPException(status_code=500, detail=f"导入PDF失败: {str(e)}")


@router.get("/api/edit-pdf/file/{task_id}/{file_id}/pages")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def get_edit_pdf_file_pages(task_id: str, file_id: str, request: Request):
    """获取指定PDF文件的页面列表（懒加载，用户隔离）"""
    task, scope = _find_task_scope_verified(task_id, request)

    task_info = scope.edit_pdf_tasks[task_id]
    task_dir = Path(task_info["task_dir"])
    file_dir = task_dir / file_id
    pdf_path = file_dir / "original.pdf"

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF文件不存在")

    # zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
    # 标识合法性校验（file_id 参与上方路径拼接，白名单校验防越界）
    _validate_edit_pdf_ids(task_id, file_id)

    # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # 列表零等待（彻底懒渲染）：不再调用 _ensure 等全量渲染（页数多时分钟级遮罩的根因），
    # 页数改取任务元数据（上传/导入时登记的 total_pages，异常缺失时打开 original.pdf
    # 现数兜底）；未渲染页的缩略图/原图由图片端点按需渲染兜底，全量渲染由上传后的
    # 后台补渲线程完成
    pages_dir = file_dir / "pages"
    total_pages = 0
    for f in task_info.get("files", []):
        if f.get("file_id") == file_id:
            total_pages = int(f.get("total_pages") or 0)
            break

    def _count_pdf_pages_now() -> int:
        import fitz
        doc = fitz.open(pdf_path)
        n = len(doc)
        doc.close()
        return n

    if total_pages <= 0:
        total_pages = await asyncio.to_thread(_count_pdf_pages_now)

    # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # edited 标志改单次目录枚举判定：原逐页 exists 在任何渲染写盘期间会被文件系统
    # 元数据竞争拖慢（实测59次exists从1.8ms卡到1104ms——"切换仍显示加载中"的直接原因）
    edited_names = set()
    if pages_dir.exists():
        try:
            edited_names = {p.name for p in pages_dir.iterdir()}
        except OSError as e:
            log_info(f"[编辑PDF] 页面目录枚举失败（edited标志按无处理）: task_id={task_id}, file_id={file_id}, 错误: {e}")

    # 返回页面列表
    # zhaoqiaotong 2026-09-11 研发需求-0167 GUI复测二轮整改 每页返回 edited 标志
    # （该页是否存在已保存的手工编辑 edited_N.png）——前端切换文件后重新加载页面
    # 列表时据此正确显示已编辑内容，修复"切回后涂抹内容显示回退为原图"的存量缺陷
    # zhaoqiaotong 2026-09-16 研发BUG-0057 页数来源由磁盘扫描改为元数据（未渲染页也返回，
    # 由此前端可立即构建全部页位的缩略图URL，由 lazy+按需渲染渐进填充）
    pages = []
    for i in range(total_pages):
        pages.append({
            "thumbnail": f"/api/edit-pdf/page/{task_id}/{file_id}/{i}/thumbnail",
            "original": f"/api/edit-pdf/page/{task_id}/{file_id}/{i}/original",
            "edited": f"edited_{i}.png" in edited_names
        })

    # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # 返回内容版本号（process_recipe.json 的 version，保存/还原/修图/OCR/构建时+1）：
    # 前端据此构建图片URL的 ?v= 参数——内容不变URL不变命中浏览器缓存（替代 ?t=时间戳
    # 的每次全量重下），内容变化URL自动换新
    version = int(_read_edit_pdf_recipe(file_dir).get("version", 0))

    return {
        "success": True,
        "pages": pages,
        "version": version
    }


@router.get("/api/edit-pdf/page/{task_id}/{file_id}/{page_num}/thumbnail")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def get_edit_pdf_page_thumbnail(task_id: str, file_id: str, page_num: int, request: Request):
    """获取PDF页面缩略图（用户隔离）"""
    _, scope = _find_task_scope_verified(task_id, request)
    thumb_path = _safe_edit_pdf_path(scope, task_id, file_id, f"pages/thumb_{page_num}.png")
    # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # 缺失页按需渲染（只渲100px缩略图，约0.1秒/张；不拿文件锁即时插队，原子落盘）：
    # 页码越界/无PDF不产出走404，与基线行为一致
    # zhaoqiaotong 2026-09-17 研发BUG-0057 渲染走专用thumb线程池（与API共享池隔离）；
    # 长缓存头：URL 已按内容版本号（?v=）寻址，同一URL内容不变可放心复用，private 防共享代理缓存
    if not thumb_path.exists():
        await _run_edit_pdf_render(task_id, file_id, page_num, "thumb")
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="缩略图不存在")
    return FileResponse(str(thumb_path), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/edit-pdf/page/{task_id}/{file_id}/{page_num}/original")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def get_edit_pdf_page_original(task_id: str, file_id: str, page_num: int, request: Request):
    """获取PDF页面原图（用户隔离）"""
    _, scope = _find_task_scope_verified(task_id, request)
    orig_path = _safe_edit_pdf_path(scope, task_id, file_id, f"pages/page_{page_num}.png")
    # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # 缺失页按需渲染整页原图（约0.6秒/张；不拿文件锁即时插队，原子落盘）：
    # 页码越界/无PDF不产出走404，与基线行为一致
    # zhaoqiaotong 2026-09-17 研发BUG-0057 渲染走专用page线程池（主图不排队等缩略图）；
    # 长缓存头：URL 已按内容版本号（?v=）寻址
    if not orig_path.exists():
        await _run_edit_pdf_render(task_id, file_id, page_num, "page")
    if not orig_path.exists():
        raise HTTPException(status_code=404, detail="页面图片不存在")
    return FileResponse(str(orig_path), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/edit-pdf/page/{task_id}/{file_id}/{page_num}/backup")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def get_edit_pdf_page_backup(task_id: str, file_id: str, page_num: int, request: Request):
    """获取PDF页面的备份原图（用户隔离）"""
    _, scope = _find_task_scope_verified(task_id, request)
    # 优先返回备份文件（一键修图前的原图）
    backup_path = _safe_edit_pdf_path(scope, task_id, file_id, f"pages/page_{page_num}_backup.png")
    if backup_path.exists():
        # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 长缓存头：URL 已按内容版本号（?v=）寻址
        return FileResponse(str(backup_path), media_type="image/png",
                            headers={"Cache-Control": "private, max-age=86400"})
    # 如果没有备份，返回当前原图
    orig_path = _safe_edit_pdf_path(scope, task_id, file_id, f"pages/page_{page_num}.png")
    # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # 回退原图缺失时按需渲染兜底（备份是修图产物无法按需生成，原图可以）
    if not orig_path.exists():
        await _run_edit_pdf_render(task_id, file_id, page_num, "page")
    if orig_path.exists():
        return FileResponse(str(orig_path), media_type="image/png",
                            headers={"Cache-Control": "private, max-age=86400"})
    raise HTTPException(status_code=404, detail="页面图片不存在")


class CleanPageRequest(BaseModel):
    task_id: str
    file_id: str
    page_num: int
    ocr_lang: str = "ch"


class CleanAllPagesRequest(BaseModel):
    task_id: str
    file_id: str
    ocr_lang: str = "ch"
    # zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
    # apply_clean=False 跳过AI清洁+OCR（"一键处理"仅设置配方并构建，流程2快速路径）；
    # 默认 True 与原一键修图行为完全一致（不传新参数的旧调用零回归）
    apply_clean: bool = True
    # 以下三项为写入该文件的处理配方（长期生效，统一构建时自动应用：去空白页→加页码→瘦身）
    remove_blank_pages: bool = False
    add_page_number: bool = False
    shrink: bool = False


# xuechong 2026-07-18 批量一键修图进度存储（模块级共享，key 含 task_id 碰撞概率极低）
edit_pdf_clean_all_progress = {}


@router.post("/api/edit-pdf/clean-all-pages")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def clean_all_edit_pdf_pages(request: CleanAllPagesRequest, req: Request):
    """对PDF所有页面进行AI智能修图 + OCR添加文字层（用户隔离）"""
    task_id = request.task_id
    file_id = request.file_id
    ocr_lang = request.ocr_lang or "ch"
    
    task, scope = _find_task_scope_verified(task_id, req)

    # zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
    # 标识白名单校验（task_id/file_id 参与下方路径拼接，防越界）
    _validate_edit_pdf_ids(task_id, file_id)

    task_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / file_id
    pages_dir = task_dir / "pages"

    # 原PDF存储在 task_dir / "original.pdf"
    original_pdf_path = task_dir / "original.pdf"
    if not original_pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF文件不存在")

    # zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
    # 页面未渲染（批量修图对从未查看过的文件）不再404"页面目录不存在"：
    # 页数改取上传时登记值（兜底打开original.pdf现数），实际渲染由后台线程
    # 开工时补做（见 do_clean_all_pages 开头），懒加载语义保持"用到才渲染"
    # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # 页数优先级改为"元数据→fitz现数"（去掉"磁盘数PNG优先"分支）：懒渲染下 pages 目录
    # 只有被查看过的页（部分渲染），磁盘计数会少计总页数导致只处理部分页
    total_pages = 0
    for f in task.get("files", []):
        if f.get("file_id") == file_id:
            total_pages = int(f.get("total_pages") or 0)
            break
    if total_pages <= 0:
        import fitz
        try:
            doc = fitz.open(original_pdf_path)
            total_pages = len(doc)
            doc.close()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"无法读取PDF: {str(e)}")
    if total_pages == 0:
        raise HTTPException(status_code=404, detail="PDF没有页面")
    
    # 初始化进度
    progress_key = f"{task_id}_{file_id}"
    edit_pdf_clean_all_progress[progress_key] = {
        "status": "processing",
        "current_page": 0,
        "total_pages": total_pages,
        "phase": "cleaning",  # cleaning / ocr / done
        "message": "正在初始化...",
        "current_page_completed": 0  # 已完成修图的页码（供前端切换显示）
    }
    
    # 启动后台线程处理
    # zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
    # 透传"一键处理"参数：apply_clean（是否执行AI修图+OCR）与三项处理配方
    import threading
    thread = threading.Thread(
        target=do_clean_all_pages,
        args=(task_id, file_id, task_dir, pages_dir, total_pages, progress_key, original_pdf_path, ocr_lang,
              request.apply_clean, request.remove_blank_pages, request.add_page_number, request.shrink)
    )
    thread.daemon = True
    thread.start()
    
    return {
        "success": True,
        "total_pages": total_pages,
        "message": f"开始处理 {total_pages} 页（修图 + OCR）"
    }


# xuechong 2026-07-18 后台执行批量一键修图 + OCR（同步函数，在线程中执行）
# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 升级为「一键处理」后台线程：apply_clean 控制是否执行AI修图+OCR（成果沉淀工作区）；
# 随后写入处理配方（去除空白页/添加页码/PDF瘦身，长期生效）并统一构建成品（配方链
# 顺序与既有下载链一致：去空白页→加页码→瘦身），操作记录写入操作内容（内容类累计+
# 当前配方项），完成进度携带实际效果摘要（未生效项如实透出）
def do_clean_all_pages(task_id: str, file_id: str, task_dir: Path, pages_dir: Path,
                        total_pages: int, progress_key: str, original_pdf_path: Path, ocr_lang: str = "ch",
                        apply_clean: bool = True, remove_blank_pages: bool = False,
                        add_page_number: bool = False, shrink: bool = False):
    """后台执行一键处理（可选AI修图+OCR + 处理配方统一构建）（同步函数，在线程中执行）"""
    import cv2
    import numpy as np
    import fitz
    from PIL import Image
    from io import BytesIO

    scope_ep = _scope_from_task(task_id)  # xuechong 2026-06-02
    if not scope_ep:
        log_info(f"[编辑PDF] 一键处理失败: task_id={task_id} 找不到对应用户scope")
        edit_pdf_clean_all_progress[progress_key].update({"status": "failed", "message": "任务scope丢失"})
        return

    try:
        # zhaoqiaotong 2026-09-10 研发需求-0167 apply_clean=False：跳过渲染与逐页修图+OCR
        # （"一键处理"未勾修图的流程2快速路径：页面成果已在工作区，无需重跑分钟级AI处理）
        if not apply_clean:
            log_info(f"[编辑PDF] 一键处理跳过修图（未勾选修图）: task_id={task_id}, file_id={file_id}")
        else:
            # zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
            # 开工前补渲染：批量修图可能对从未查看过的文件执行，其页面尚未懒渲染
            # （upload-multiple 只存 original.pdf，页面是查看时才渲染的）。缺失时先渲染
            # 再修图，进度文案显示"正在提取页面"；已渲染文件不走此分支（零回归）。
            # 渲染在 per-file 锁内进行，与"用户点开查看触发懒渲染"互斥，不会重复渲染
            # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
            # 判定改哨兵（原"数量>0"）：懒渲染下用户按需渲染过的文件有部分页但未全渲，
            # "数量>0"会骗过检查跳过补渲染导致修图中途缺页；哨兵保证全量完成才放行
            if not _is_edit_pdf_pages_rendered(task_id, file_id):
                edit_pdf_clean_all_progress[progress_key].update({
                    "phase": "cleaning",
                    "message": f"正在提取页面（共 {total_pages} 页）..."
                })
                log_info(f"[编辑PDF] 页面未渲染，先提取页面: task_id={task_id}, file_id={file_id}")
                rendered = _ensure_edit_pdf_pages_rendered(task_id, file_id)
                if rendered <= 0:
                    edit_pdf_clean_all_progress[progress_key].update({
                        "status": "failed",
                        "message": "页面提取失败：PDF没有可提取的页面"
                    })
                    return
                if rendered != total_pages:
                    # 登记页数与实际不符时以实际渲染页数为准（同步修正进度总页数）
                    total_pages = rendered
                    edit_pdf_clean_all_progress[progress_key]["total_pages"] = total_pages

            cleaner = _hsvc.get_cleaner()

            # 获取OCR引擎和字体
            from backend.ocr_rapid import get_rapid_ocr_engine, get_cached_font, ocr_image_with_rapid
            ocr_engine_info = get_rapid_ocr_engine(ocr_lang, use_cls=False, det_limit=960)
            cached_font = get_cached_font("china-s")  # 返回的是 fitz.Font 对象

            # 打开原PDF获取页面尺寸
            doc = fitz.open(str(original_pdf_path))

            try:
                # 第一阶段：修图 + OCR（每处理完一页立即生成双层PDF）
                for page_num in range(total_pages):
                    # 更新进度：开始处理第N页
                    edit_pdf_clean_all_progress[progress_key].update({
                        "current_page": page_num + 1,
                        "phase": "cleaning",
                        "message": f"正在修图 {page_num + 1}/{total_pages} 页..."
                    })

                    orig_path = pages_dir / f"page_{page_num}.png"
                    if not orig_path.exists():
                        continue

                    # 读取图片
                    image = cv2.imdecode(np.fromfile(str(orig_path), dtype=np.uint8), cv2.IMREAD_COLOR)
                    if image is None:
                        continue

                    # AI修图（包含自动矫正、去噪等）
                    # zhaoqiaotong 2026-09-17 研发BUG-0060 修图DPI优先取渲染登记值（防存量PNG pHYs=96）
                    result = cleaner.process(image, debug=False,
                                             dpi=_get_page_render_dpi(pages_dir, page_num, orig_path))
                    cleaned_image = result['result']

                    # 备份原图
                    backup_path = pages_dir / f"page_{page_num}_backup.png"
                    if not backup_path.exists():
                        import shutil
                        shutil.copy2(orig_path, backup_path)

                    # 保存清洁后的图片
                    cv2.imencode('.png', cleaned_image)[1].tofile(str(orig_path))

                    # 重新生成缩略图
                    thumb_path = pages_dir / f"thumb_{page_num}.png"
                    h, w = cleaned_image.shape[:2]
                    scale = 100 / w
                    thumb = cv2.resize(cleaned_image, (int(w * scale), int(h * scale)))
                    cv2.imencode('.png', thumb)[1].tofile(str(thumb_path))

                    # 删除已有的编辑后图片
                    for ext in ['jpg', 'png']:
                        edited_path = pages_dir / f"edited_{page_num}.{ext}"
                        if edited_path.exists():
                            edited_path.unlink()

                    # 标记该页修图完成（供前端切换显示）
                    edit_pdf_clean_all_progress[progress_key]["current_page_completed"] = page_num + 1

                    # 更新进度：开始OCR
                    edit_pdf_clean_all_progress[progress_key].update({
                        "phase": "ocr",
                        "message": f"正在OCR识别 {page_num + 1}/{total_pages} 页..."
                    })

                    # OCR识别
                    img_h, img_w = cleaned_image.shape[:2]

                    # 获取页面尺寸
                    if page_num < len(doc):
                        page = doc[page_num]
                        page_rect = page.rect
                    else:
                        page_rect = fitz.Rect(0, 0, img_w * 72 / 150, img_h * 72 / 150)

                    scale_x = page_rect.width / img_w
                    scale_y = page_rect.height / img_h

                    # 执行OCR
                    ocr_results = ocr_image_with_rapid(cleaned_image, ocr_engine_info, det_limit_side_len=960)

                    # 创建单页双层PDF
                    page_pdf_path = pages_dir / f"page_{page_num}_dual.pdf"
                    page_doc = fitz.open()
                    new_page = page_doc.new_page(width=page_rect.width, height=page_rect.height)

                    # 插入图片
                    with Image.open(str(orig_path)) as pil_img:
                        if pil_img.mode == 'RGBA':
                            pil_img = pil_img.convert('RGB')
                        img_buffer = BytesIO()
                        pil_img.save(img_buffer, format='JPEG', quality=85)
                    img_buffer.seek(0)
                    new_page.insert_image(page_rect, stream=img_buffer.read())

                    # 添加文字层
                    if ocr_results:
                        tw = fitz.TextWriter(page_rect)

                        for item in ocr_results:
                            box = item['box']
                            text = item['text']

                            if not text or not text.strip():
                                continue

                            try:
                                pts = np.array(box, dtype=np.float32)
                                pts[:, 0] = pts[:, 0] * scale_x
                                pts[:, 1] = pts[:, 1] * scale_y

                                x_min = float(min(pts[:, 0]))
                                y_min = float(min(pts[:, 1]))
                                x_max = float(max(pts[:, 0]))
                                y_max = float(max(pts[:, 1]))

                                box_h = y_max - y_min
                                if box_h <= 0 or x_max <= x_min:
                                    continue

                                font_size = box_h * 0.85
                                font_size = max(6, min(font_size, 72))

                                tw.append((x_min, y_max - box_h * 0.15), text, font=cached_font, fontsize=font_size)
                            except Exception as e:
                                log_info(f"[编辑PDF文字层] 写入OCR文字失败: 页={page_num+1}, 文字='{text}', 错误: {e}")
                                import traceback
                                traceback.print_exc()

                        tw.write_text(new_page, color=(0, 0, 0), render_mode=3)

                    page_doc.save(str(page_pdf_path), garbage=4, deflate=True)
                    page_doc.close()

                    log_info(f"[编辑PDF] 页面 {page_num + 1}/{total_pages} 修图+OCR完成")
            finally:
                doc.close()

            # xuechong 2026-07-18 记录OCR已处理 + 标记所有页面已修改（使用用户 scope）
            if task_id in scope_ep.edit_pdf_tasks:
                if "ocr_processed_pages" not in scope_ep.edit_pdf_tasks[task_id]:
                    scope_ep.edit_pdf_tasks[task_id]["ocr_processed_pages"] = {}
                scope_ep.edit_pdf_tasks[task_id]["ocr_processed_pages"][file_id] = set(range(total_pages))

                if "modified_pages" not in scope_ep.edit_pdf_tasks[task_id]:
                    scope_ep.edit_pdf_tasks[task_id]["modified_pages"] = {}
                scope_ep.edit_pdf_tasks[task_id]["modified_pages"][file_id] = set(range(total_pages))

            # zhaoqiaotong 2026-09-10 研发需求-0167 修图改变每页像素：作废整文件空白页缓存
            # （统一构建时重判一次并重新缓存；未勾修图不改变像素，缓存保留）
            _invalidate_blank_cache(task_id, file_id)

        # zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
        # 写入处理配方（长期生效，统一构建自动应用）：版本+1 使旧构建结果失效。
        # 写入持 per-file 构建锁（与 _bump_edit_pdf_version/统一构建终写互斥，防丢失更新）
        file_dir = pages_dir.parent
        recipe = _read_edit_pdf_recipe(file_dir)
        recipe["remove_blank_pages"] = remove_blank_pages
        recipe["add_page_number"] = add_page_number
        recipe["shrink"] = shrink
        recipe["version"] = int(recipe.get("version", 0)) + 1
        with _get_edit_pdf_build_lock(task_id, file_id):
            _write_edit_pdf_recipe(file_dir, recipe)
        transform_labels = _active_transform_labels(recipe)

        # 附加阶段进度文案（任一配方项激活时展示，与修图阶段衔接）
        # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 带页数展示：仅配方路径构建链为分钟级重活（406页实测约2分钟独占CPU），
        # 静态文案无页数信息会让用户误判卡死
        if transform_labels:
            edit_pdf_clean_all_progress[progress_key].update({
                "phase": "processing",
                "message": f"正在执行{'、'.join(transform_labels)}（共 {total_pages} 页，页数多时需数分钟）..."
            })

        # 统一构建：合并（修图成果/手工编辑）→ 配方链（去空白页→加页码→瘦身）→ 成品+存档快照
        final_pdf_path, effects = _build_edit_pdf_output(scope_ep, task_id, file_id)

        # zhaoqiaotong 2026-09-10 研发需求-0167 写入或更新操作记录（操作内容=内容类累计+当前配方项）
        if task_id in scope_ep.edit_pdf_tasks:
            task_info = scope_ep.edit_pdf_tasks[task_id]
            try:
                # zhaoqiaotong 2026-09-10 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
                # 按 task_id+file_id 查找已有记录决定插入/更新（多文件任务每文件独立一行）
                existing_rec = None
                for rec in scope_ep.edit_pdf_history:
                    if rec.get("task_id") == task_id and rec.get("file_id") == file_id:
                        existing_rec = rec
                        break

                record_pdf_path = effects.get("snapshot") or str(final_pdf_path)
                record_page_count = effects.get("page_count", 0)
                modified_count = len(task_info.get("modified_pages", {}).get(file_id, set()) or [])
                new_operations = _merge_edit_pdf_operations(
                    (existing_rec or {}).get("operations"),
                    ["修图"] if apply_clean else [],
                    transform_labels,
                )

                if existing_rec is None:
                    filename = "output.pdf"
                    for f in task_info.get("files", []):
                        if f.get("file_id") == file_id:
                            filename = f.get("filename", "output.pdf")
                            break
                    source = task_info.get("source", "manual")
                    record = {
                        "task_id": task_id,
                        "file_id": file_id,
                        "filename": filename,
                        "source": source,
                        "source_task_id": task_info.get("source_task_id", ""),
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "pdf_path": record_pdf_path,
                        "page_count": record_page_count,
                        "edited_pages": modified_count,
                        "download_count": 0,
                        "operations": new_operations
                    }
                    record["username"] = task_info.get("username", "admin")  # xuechong 2026-06-27
                    # xuechong 2026-07-16 只写入用户 scope，不再写全局 state
                    scope_ep.edit_pdf_history.insert(0, record)
                    log_info(f"[编辑PDF] 一键处理操作记录已写入: {filename} (操作: {'、'.join(new_operations) or '无'})")
                else:
                    # 已有记录，更新时间和PDF路径与操作内容
                    existing_rec["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    existing_rec["pdf_path"] = record_pdf_path
                    existing_rec["edited_pages"] = modified_count
                    existing_rec["page_count"] = record_page_count
                    existing_rec["operations"] = new_operations
                    log_info(f"[编辑PDF] 一键处理操作记录已更新（操作: {'、'.join(new_operations) or '无'}）")
                scope_ep.save_edit_pdf_history()
            except Exception as e:
                import traceback
                traceback.print_exc()
                log_info(f"[编辑PDF] 一键处理写入操作记录失败: task_id={task_id}, file_id={file_id}, 错误: {e}")

        # 完成（携带实际效果摘要，前端完成 toast 按此拼装；未生效项如实透出）
        edit_pdf_clean_all_progress[progress_key].update({
            "status": "completed",
            "current_page": total_pages,
            "current_page_completed": total_pages,
            "phase": "done",
            "message": "处理完成！",
            "effects": {
                "cleaned_pages": total_pages if apply_clean else 0,
                "remove_blank_applied": bool(effects.get("remove_blank_applied")),
                "removed_blank_pages": effects.get("removed_blank_pages", 0),
                # FIX-J3 本次构建判定的空白页列表（0基原始页索引），前端据此显示页面列表角标
                "blank_pages": effects.get("blank_pages", []),
                "pagenum_applied": bool(effects.get("pagenum_applied")),
                "renumbered": bool(effects.get("renumbered")),
                "shrink_applied": bool(effects.get("shrink_applied")),
                "not_applied": effects.get("not_applied", []),
                "page_count": effects.get("page_count", 0)
            }
        })

        log_info(f"[编辑PDF] 一键处理完成: task_id={task_id}, file_id={file_id}, 修图={apply_clean}, 配方={transform_labels}, 效果={effects}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 一键处理失败: task_id={task_id}, file_id={file_id}, 总页数={total_pages}, 错误: {e}")
        edit_pdf_clean_all_progress[progress_key].update({
            "status": "failed",
            "message": f"处理失败: {str(e)}"
        })


@router.get("/api/edit-pdf/clean-all-progress/{task_id}/{file_id}")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def get_clean_all_progress(task_id: str, file_id: str, request: Request):
    """获取批量一键修图进度（用户隔离）"""
    _find_task_scope_verified(task_id, request)
    progress_key = f"{task_id}_{file_id}"
    progress = edit_pdf_clean_all_progress.get(progress_key)
    
    if not progress:
        return {"status": "idle"}
    
    return progress


# xuechong 2026-07-18 一键OCR全部页面进度存储（模块级共享，key 含 task_id 碰撞概率极低）
edit_pdf_ocr_all_progress = {}


@router.post("/api/edit-pdf/ocr-all-pages")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def ocr_all_edit_pdf_pages(request: CleanAllPagesRequest, req: Request):
    """对PDF所有页面执行OCR（用户隔离）"""
    task_id = request.task_id
    file_id = request.file_id
    ocr_lang = request.ocr_lang or "ch"

    task, scope = _find_task_scope_verified(task_id, req)

    task_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / file_id
    pages_dir = task_dir / "pages"

    original_pdf_path = task_dir / "original.pdf"
    if not original_pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF文件不存在")

    # 统计需要处理的页面（跳过已OCR的）
    task_info = scope.edit_pdf_tasks[task_id]
    ocr_processed = task_info.get("ocr_processed_pages", {}).get(file_id, set())

    # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # 待OCR页清单由"磁盘扫描 page_*.png"改为按元数据页数构建：懒渲染下 pages 目录只有
    # 被查看过的页（部分渲染），磁盘扫描会静默漏掉未渲页少OCR；页面渲染由后台线程开工
    # 时补齐（见 _do_ocr_all_pages 开头，与一键处理补渲染同模式）。原"页面目录不存在"
    # 404 一并移除（从未查看过的文件可直接OCR，不再要求先点开过）
    total_pages = 0
    for f in task_info.get("files", []):
        if f.get("file_id") == file_id:
            total_pages = int(f.get("total_pages") or 0)
            break

    def _count_pdf_pages_now() -> int:
        import fitz
        doc = fitz.open(original_pdf_path)
        n = len(doc)
        doc.close()
        return n

    if total_pages <= 0:
        total_pages = await asyncio.to_thread(_count_pdf_pages_now)
    if total_pages <= 0:
        raise HTTPException(status_code=404, detail="PDF没有页面")

    pending_pages = [i for i in range(total_pages) if i not in ocr_processed]

    if not pending_pages:
        return {"success": True, "total_pages": 0, "message": "所有页面已完成OCR"}

    # 初始化进度
    progress_key = f"{task_id}_{file_id}"
    edit_pdf_ocr_all_progress[progress_key] = {
        "status": "processing",
        "current_page": 0,
        "total_pages": len(pending_pages),
        "message": "正在初始化..."
    }

    # 启动后台线程
    import threading
    thread = threading.Thread(
        target=_do_ocr_all_pages,
        args=(task_id, file_id, task_dir, pages_dir, pending_pages, progress_key, original_pdf_path, ocr_lang)
    )
    thread.daemon = True
    thread.start()

    return {
        "success": True,
        "total_pages": len(pending_pages),
        "message": f"开始OCR识别 {len(pending_pages)} 页"
    }


# xuechong 2026-07-18 后台执行OCR全部页面（不做图像修改）
def _do_ocr_all_pages(task_id: str, file_id: str, task_dir: Path, pages_dir: Path,
                       pending_pages: list, progress_key: str, original_pdf_path: Path, ocr_lang: str):
    """后台执行OCR全部页面（不做图像修改）"""
    import fitz
    import cv2
    import numpy as np

    scope_ep = _scope_from_task(task_id)  # xuechong 2026-06-02
    if not scope_ep:
        log_info(f"[编辑PDF-OCR全部] 失败: task_id={task_id} 找不到对应用户scope")
        edit_pdf_ocr_all_progress[progress_key].update({"status": "failed", "message": "任务scope丢失"})
        return

    try:
        # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 开工前补渲染（哨兵判定）：懒渲染下页面可能只有部分存在（用户查看过的页），
        # OCR 逐页读 page_N.png 前必须全量渲完（与 do_clean_all_pages 同模式）
        if not _is_edit_pdf_pages_rendered(task_id, file_id):
            edit_pdf_ocr_all_progress[progress_key].update({
                "message": "正在提取页面..."
            })
            log_info(f"[编辑PDF-OCR全部] 页面未全渲，先提取页面: task_id={task_id}, file_id={file_id}")
            _ensure_edit_pdf_pages_rendered(task_id, file_id)

        from backend.ocr_rapid import get_rapid_ocr_engine, get_cached_font, ocr_image_with_rapid
        ocr_engine_info = get_rapid_ocr_engine(ocr_lang, use_cls=False, det_limit=960)
        cached_font = get_cached_font("china-s")

        doc = fitz.open(str(original_pdf_path))
        total = len(pending_pages)
        success_count = 0

        try:
            for idx, page_num in enumerate(pending_pages):
                edit_pdf_ocr_all_progress[progress_key].update({
                    "current_page": idx + 1,
                    "total_pages": total,
                    "message": f"正在OCR识别第 {page_num + 1} 页 ({idx + 1}/{total})..."
                })

                page = doc[page_num]
                page_rect = page.rect
                page_img_path = pages_dir / f"page_{page_num}.png"

                if not page_img_path.exists():
                    log_info(f"[编辑PDF-OCR全部] 页面 {page_num} 图片不存在，跳过")
                    continue

                # 读取页面图片
                img_bgr = cv2.imdecode(np.fromfile(str(page_img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
                if img_bgr is None:
                    log_info(f"[编辑PDF-OCR全部] 页面 {page_num} 图片读取失败，跳过")
                    continue
                img_h, img_w = img_bgr.shape[:2]

                # 执行OCR
                ocr_results = ocr_image_with_rapid(img_bgr, ocr_engine_info, det_limit_side_len=960)

                # 创建单页双层PDF
                page_pdf_path = pages_dir / f"page_{page_num}_dual.pdf"
                page_doc = fitz.open()
                new_page = page_doc.new_page(width=page_rect.width, height=page_rect.height)

                # 插入原图
                with open(page_img_path, 'rb') as f:
                    img_bytes = f.read()
                new_page.insert_image(new_page.rect, stream=img_bytes)

                # 添加透明文字层
                text_count = 0
                if ocr_results:
                    scale_x = page_rect.width / img_w
                    scale_y = page_rect.height / img_h
                    tw = fitz.TextWriter(new_page.rect)

                    for item in ocr_results:
                        box = item['box']
                        text = item['text']
                        if not text or not text.strip():
                            continue
                        try:
                            pts = np.array(box, dtype=np.float32)
                            pts[:, 0] *= scale_x
                            pts[:, 1] *= scale_y
                            x_min = float(min(pts[:, 0]))
                            y_max = float(max(pts[:, 1]))
                            box_h = float(max(pts[:, 1])) - float(min(pts[:, 1]))
                            if box_h <= 0:
                                continue
                            font_size = max(4, min(72, box_h * 0.8))
                            baseline_y = y_max - box_h * 0.1
                            tw.append(pos=(x_min, baseline_y), text=text, font=cached_font, fontsize=font_size)
                            text_count += 1
                        except Exception as e:
                            log_info(f"[编辑PDF-OCR全部] 写入文字失败: 页={page_num}, 文字='{text}', 错误: {e}")
                            import traceback
                            traceback.print_exc()

                    if text_count > 0:
                        tw.write_text(new_page, color=(0, 0, 0), render_mode=3)

                page_doc.save(str(page_pdf_path), garbage=4, deflate=True)
                page_doc.close()

                # 标记已处理
                task_info = scope_ep.edit_pdf_tasks[task_id]
                if "modified_pages" not in task_info:
                    task_info["modified_pages"] = {}
                if file_id not in task_info["modified_pages"]:
                    task_info["modified_pages"][file_id] = set()
                task_info["modified_pages"][file_id].add(page_num)

                if "ocr_processed_pages" not in task_info:
                    task_info["ocr_processed_pages"] = {}
                if file_id not in task_info["ocr_processed_pages"]:
                    task_info["ocr_processed_pages"][file_id] = set()
                task_info["ocr_processed_pages"][file_id].add(page_num)

                success_count += 1
                log_info(f"[编辑PDF-OCR全部] 页面 {page_num} 完成（{text_count} 个文字块）")
        finally:
            doc.close()

        # xuechong 2026-07-18 立即合并生成最终双层PDF
        task_info = scope_ep.edit_pdf_tasks.get(task_id, {})
        output_pdf_path = original_pdf_path
        if task_info:
            output_pdf_path = merge_edit_pdf_output(
                pages_dir.parent, original_pdf_path, pages_dir, task_info, file_id
            )

        # xuechong 2026-07-18 写入或更新操作记录（使用用户 scope）
        if task_id in scope_ep.edit_pdf_tasks:
            task_info = scope_ep.edit_pdf_tasks[task_id]
            try:
                # zhaoqiaotong 2026-09-10 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
                # 按 task_id+file_id 查找已有记录决定插入/更新（与一键修图同因修复：
                # 任务级 history_recorded 标志在多文件任务中丢失第2个及以后文件的记录）
                existing_rec = None
                for rec in scope_ep.edit_pdf_history:
                    if rec.get("task_id") == task_id and rec.get("file_id") == file_id:
                        existing_rec = rec
                        break

                if existing_rec is None:
                    filename = "output.pdf"
                    for f in task_info.get("files", []):
                        if f.get("file_id") == file_id:
                            filename = f.get("filename", "output.pdf")
                            break
                    source = task_info.get("source", "manual")
                    record = {
                        "task_id": task_id,
                        "file_id": file_id,
                        "filename": filename,
                        "source": source,
                        "source_task_id": task_info.get("source_task_id", ""),
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "pdf_path": str(output_pdf_path),
                        "page_count": len(list(pages_dir.glob("page_*.png"))),
                        "edited_pages": success_count,
                        "download_count": 0,
                        # zhaoqiaotong 2026-09-10 研发需求-0167 操作内容：内容类累计+当前配方项
                        "operations": _merge_edit_pdf_operations([], ["OCR"], _active_transform_labels(_read_edit_pdf_recipe(pages_dir.parent)))
                    }
                    record["username"] = task_info.get("username", "admin")  # xuechong 2026-06-27
                    # xuechong 2026-07-16 只写入用户 scope，不再写全局 state
                    scope_ep.edit_pdf_history.insert(0, record)
                    log_info(f"[编辑PDF-OCR全部] 已写入操作记录: {filename}")
                else:
                    existing_rec["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    existing_rec["pdf_path"] = str(output_pdf_path)
                    existing_rec["edited_pages"] = success_count
                    existing_rec["page_count"] = len(list(pages_dir.glob("page_*.png")))
                    # zhaoqiaotong 2026-09-10 研发需求-0167 操作内容：内容类累计+当前配方项
                    existing_rec["operations"] = _merge_edit_pdf_operations(
                        existing_rec.get("operations"), ["OCR"],
                        _active_transform_labels(_read_edit_pdf_recipe(pages_dir.parent)))
                    log_info(f"[编辑PDF-OCR全部] 操作记录已更新时间")
                scope_ep.save_edit_pdf_history()
            except Exception as e:
                import traceback
                traceback.print_exc()
                log_info(f"[编辑PDF-OCR全部] 写入操作记录失败: task_id={task_id}, file_id={file_id}, 错误: {e}")

        # zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
        # OCR为内容类操作：版本号+1 使下次统一构建自动重建含最新文字层
        # （OCR只改文字层不改页面像素，空白页判定缓存无需失效）
        _bump_edit_pdf_version(task_id, file_id)

        edit_pdf_ocr_all_progress[progress_key].update({
            "status": "completed",
            "current_page": total,
            "current_page_completed": success_count,
            "message": f"OCR识别完成，共处理 {success_count}/{total} 页"
        })
        log_info(f"[编辑PDF-OCR全部] 全部 {success_count}/{total} 页OCR完成")

    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF-OCR全部] 处理失败: task_id={task_id}, file_id={file_id}, 待处理页={pending_pages}, 错误: {e}")
        edit_pdf_ocr_all_progress[progress_key].update({
            "status": "failed",
            "message": f"处理失败: {str(e)}"
        })


@router.get("/api/edit-pdf/ocr-all-progress/{task_id}/{file_id}")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def get_ocr_all_progress(task_id: str, file_id: str, request: Request):
    """获取一键OCR全部页面进度（用户隔离）"""
    _find_task_scope_verified(task_id, request)
    progress_key = f"{task_id}_{file_id}"
    progress = edit_pdf_ocr_all_progress.get(progress_key)
    if not progress:
        return {"status": "idle"}
    return progress


@router.post("/api/edit-pdf/clean-page")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def clean_edit_pdf_page(request: CleanPageRequest, req: Request):
    """对单个PDF页面进行AI智能修图（用户隔离）"""
    import cv2
    import numpy as np
    
    task_id = request.task_id
    file_id = request.file_id
    page_num = request.page_num
    
    task, scope = _find_task_scope_verified(task_id, req)
    
    task_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / file_id
    pages_dir = task_dir / "pages"
    
    if not pages_dir.exists():
        raise HTTPException(status_code=404, detail="页面目录不存在")
    
    # 读取原始页面图片
    orig_path = pages_dir / f"page_{page_num}.png"
    if not orig_path.exists():
        raise HTTPException(status_code=404, detail="页面图片不存在")
    
    try:
        log_info(f"[编辑PDF] 开始对页面 {page_num} 进行一键修图...")
        
        # 读取图片
        image = cv2.imdecode(np.fromfile(str(orig_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(status_code=400, detail="无法读取页面图片")
        
        # 获取cleaner并处理
        cleaner = _hsvc.get_cleaner()
        # zhaoqiaotong 2026-09-17 研发BUG-0060 修图DPI优先取渲染登记值（防存量PNG pHYs=96）
        result = cleaner.process(image, debug=False,
                                 dpi=_get_page_render_dpi(pages_dir, page_num, orig_path))
        cleaned_image = result['result']

        # 备份原图（如果尚未备份）
        backup_path = pages_dir / f"page_{page_num}_backup.png"
        if not backup_path.exists():
            import shutil
            shutil.copy2(orig_path, backup_path)
            log_info(f"[编辑PDF] 页面 {page_num} 原图已备份")
        
        # 保存清洁后的图片（覆盖原文件）
        cv2.imencode('.png', cleaned_image)[1].tofile(str(orig_path))
        
        # 重新生成缩略图
        thumb_path = pages_dir / f"thumb_{page_num}.png"
        h, w = cleaned_image.shape[:2]
        scale = 100 / w
        thumb = cv2.resize(cleaned_image, (int(w * scale), int(h * scale)))
        cv2.imencode('.png', thumb)[1].tofile(str(thumb_path))
        
        # 删除已有的编辑后图片（因为原图已经修改了）
        edited_jpg_path = pages_dir / f"edited_{page_num}.jpg"
        edited_png_path = pages_dir / f"edited_{page_num}.png"
        # xuechong 2026-07-20 研发BUG-0009 异步阻塞IO修复：unlink 包装到线程池
        if edited_jpg_path.exists():
            await asyncio.to_thread(edited_jpg_path.unlink)
        if edited_png_path.exists():
            await asyncio.to_thread(edited_png_path.unlink)

        # 删除旧的 output.pdf，使后续下载重新生成（包含本次修图结果）
        output_pdf_path = task_dir / "output.pdf"
        if output_pdf_path.exists():
            await asyncio.to_thread(output_pdf_path.unlink)

        log_info(f"[编辑PDF] 页面 {page_num} 一键修图完成")

        # zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
        # 单页修图改变该页像素：版本号+1 触发下次统一构建重建；作废该页空白判定缓存
        await asyncio.to_thread(_bump_edit_pdf_version, task_id, file_id)
        _invalidate_blank_cache(task_id, file_id, page_num)

        return {
            "success": True,
            "message": "一键修图完成"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 单页修图失败: task_id={task_id}, file_id={file_id}, 页={page_num}, 错误: {e}")
        raise HTTPException(status_code=500, detail=f"一键修图失败: {str(e)}")


class SavePageRequest(BaseModel):
    task_id: str
    file_id: str
    page_num: int
    image_data: str  # base64 编码的图片数据
    ocr_lang: str = "ch"  # OCR 语言: ch/en/cht/ja/ko


@router.post("/api/edit-pdf/save-page")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def save_edit_pdf_page(request: SavePageRequest, req: Request):
    """保存编辑后的PDF页面（用户隔离，同时进行OCR重建该页的双层PDF）

    zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    重活移出事件循环：图像解码/存图/OCR推理/双层PDF构建（与后台任务竞争时实测33秒）
    此前全部内联在 async 处理器里同步执行——期间整个服务事件循环被冻住，下载流/
    预览/其他请求全部停摆。现仅鉴权与目录校验留在事件循环，主体经线程执行"""
    task_id = request.task_id
    task, scope = _find_task_scope_verified(task_id, req)

    task_info = scope.edit_pdf_tasks[task_id]
    task_dir = _psvc.TEMP_DIR / "edit_pdf" / task_id / request.file_id
    pages_dir = task_dir / "pages"
    if not pages_dir.exists():
        raise HTTPException(status_code=404, detail="页面目录不存在")

    return await asyncio.to_thread(
        _do_save_edit_pdf_page, request, scope, task_info, task_dir, pages_dir
    )


# zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _do_save_edit_pdf_page(request: SavePageRequest, scope, task_info: dict, task_dir: Path, pages_dir: Path) -> dict:
    """保存页面同步主体（线程中执行）：base64解码→存图→OCR→重建双层PDF→版本bump与
    操作记录（原 save_edit_pdf_page 主体原样迁移，原 await to_thread 改同步直调）"""
    import base64
    import fitz
    import cv2
    import numpy as np
    from io import BytesIO
    from PIL import Image

    task_id = request.task_id
    file_id = request.file_id
    page_num = request.page_num
    image_data = request.image_data
    ocr_lang = request.ocr_lang or "ch"

    try:
        # 解析base64图片数据
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        image_bytes = base64.b64decode(image_data)
        
        # 处理图像（前端已发送JPEG格式，防解压炸弹）
        # 重要：不改变图像分辨率，保持原DPI
        max_pixels = 20000 * 20000
        old_max = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = max_pixels
        try:
            pil_image = Image.open(BytesIO(image_bytes))
        finally:
            Image.MAX_IMAGE_PIXELS = old_max
        if pil_image.mode == 'RGBA':
            # 将透明背景转为白色
            background = Image.new('RGB', pil_image.size, (255, 255, 255))
            background.paste(pil_image, mask=pil_image.split()[3])
            pil_image = background
        elif pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        
        # 保存为JPEG（不缩放，保持原始分辨率和DPI）
        edited_jpg_path = pages_dir / f"edited_{page_num}.jpg"
        pil_image.save(str(edited_jpg_path), 'JPEG', quality=85, optimize=True)
        
        # 保存用于前端显示
        edited_png_path = pages_dir / f"edited_{page_num}.png"
        pil_image.save(str(edited_png_path), 'PNG')
        
        log_info(f"[编辑PDF] 页面 {page_num} 图像已保存，开始OCR重建双层PDF...")
        
        # === 立即进行OCR，生成该页的双层PDF ===
        from backend.ocr_rapid import get_rapid_ocr_engine, get_cached_font, ocr_image_with_rapid
        
        # 获取原PDF的页面尺寸
        original_pdf_path = task_dir / "original.pdf"
        original_doc = fitz.open(str(original_pdf_path))
        try:
            original_page = original_doc[page_num]
            page_rect = original_page.rect
        finally:
            original_doc.close()

        # 读取编辑后的图像进行OCR（使用 np.fromfile 兼容中文路径）
        img_bgr = cv2.imdecode(np.fromfile(str(edited_jpg_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=500, detail=f"无法读取编辑后的图片: {edited_jpg_path}")
        img_h, img_w = img_bgr.shape[:2]

        # 获取OCR引擎和字体
        ocr_engine_info = get_rapid_ocr_engine(ocr_lang, use_cls=False, det_limit=960)
        cached_font = get_cached_font("china-s")

        # 执行OCR
        ocr_results = ocr_image_with_rapid(img_bgr, ocr_engine_info, det_limit_side_len=960)

        # 创建单页双层PDF
        page_pdf_path = pages_dir / f"page_{page_num}_dual.pdf"
        page_doc = fitz.open()
        try:
            new_page = page_doc.new_page(width=page_rect.width, height=page_rect.height)

            # 读取JPEG图像并插入
            with open(edited_jpg_path, 'rb') as f:
                jpg_bytes = f.read()
            new_page.insert_image(new_page.rect, stream=jpg_bytes)

            text_count = 0
            if ocr_results:
                # 计算图像坐标到PDF坐标的缩放比例
                scale_x = page_rect.width / img_w
                scale_y = page_rect.height / img_h

                # 添加透明文字层
                tw = fitz.TextWriter(new_page.rect)
            
            for item in ocr_results:
                box = item['box']
                text = item['text']
                
                if not text or not text.strip():
                    continue
                
                try:
                    pts = np.array(box, dtype=np.float32)
                    pts[:, 0] = pts[:, 0] * scale_x
                    pts[:, 1] = pts[:, 1] * scale_y
                    
                    x_min = float(min(pts[:, 0]))
                    y_min = float(min(pts[:, 1]))
                    x_max = float(max(pts[:, 0]))
                    y_max = float(max(pts[:, 1]))
                    
                    box_h = y_max - y_min
                    if box_h <= 0 or x_max <= x_min:
                        continue
                    
                    font_size = max(4, min(72, box_h * 0.8))
                    baseline_y = y_max - box_h * 0.1
                    
                    tw.append(pos=(x_min, baseline_y), text=text, font=cached_font, fontsize=font_size)
                    text_count += 1
                except Exception as e:
                    log_info(f"[双层PDF文字层] 写入OCR文字失败: 页={page_num}, 文字='{text}', 错误: {e}")
                    import traceback
                    traceback.print_exc()
            
            # 写入透明文字层 (render_mode=3)
            if text_count > 0:
                tw.write_text(new_page, color=(0, 0, 0), render_mode=3)

            # 保存该页的双层PDF
            page_doc.save(str(page_pdf_path), garbage=4, deflate=True)
        finally:
            page_doc.close()
        
        log_info(f"[编辑PDF] 页面 {page_num} 双层PDF已生成（{text_count} 个文字块）")
        
        # xuechong 2026-07-18 记录修改信息（标记为已保存，使用用户 scope）
        if task_id in scope.edit_pdf_tasks:
            if "modified_pages" not in scope.edit_pdf_tasks[task_id]:
                scope.edit_pdf_tasks[task_id]["modified_pages"] = {}
            if file_id not in scope.edit_pdf_tasks[task_id]["modified_pages"]:
                scope.edit_pdf_tasks[task_id]["modified_pages"][file_id] = set()
            scope.edit_pdf_tasks[task_id]["modified_pages"][file_id].add(page_num)

            # 标记该页已完成OCR处理
            if "ocr_processed_pages" not in scope.edit_pdf_tasks[task_id]:
                scope.edit_pdf_tasks[task_id]["ocr_processed_pages"] = {}
            if file_id not in scope.edit_pdf_tasks[task_id]["ocr_processed_pages"]:
                scope.edit_pdf_tasks[task_id]["ocr_processed_pages"][file_id] = set()
            scope.edit_pdf_tasks[task_id]["ocr_processed_pages"][file_id].add(page_num)

            # zhaoqiaotong 2026-09-11 研发需求-0167 GUI复测二轮整改 手工编辑页标记
            # （与修图标记区分：还原接口据此判定"页面编辑"操作内容是否应从记录移除）
            if "manual_edited_pages" not in scope.edit_pdf_tasks[task_id]:
                scope.edit_pdf_tasks[task_id]["manual_edited_pages"] = {}
            if file_id not in scope.edit_pdf_tasks[task_id]["manual_edited_pages"]:
                scope.edit_pdf_tasks[task_id]["manual_edited_pages"][file_id] = set()
            scope.edit_pdf_tasks[task_id]["manual_edited_pages"][file_id].add(page_num)

            # 立即合并生成最终双层PDF
            output_pdf_path = merge_edit_pdf_output(
                task_dir, task_dir / "original.pdf",
                pages_dir, task_info, file_id
            )

            # 写入或更新操作记录
            try:
                # zhaoqiaotong 2026-09-10 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
                # 按 task_id+file_id 查找已有记录决定插入/更新（与一键修图同因修复：
                # 任务级 history_recorded 标志在多文件任务中丢失第2个及以后文件的记录）
                existing_rec = None
                for rec in scope.edit_pdf_history:
                    if rec.get("task_id") == task_id and rec.get("file_id") == file_id:
                        existing_rec = rec
                        break

                if existing_rec is None:
                    filename = "output.pdf"
                    for f in task_info.get("files", []):
                        if f.get("file_id") == file_id:
                            filename = f.get("filename", "output.pdf")
                            break
                    source = task_info.get("source", "manual")
                    record = {
                        "task_id": task_id,
                        "file_id": file_id,
                        "filename": filename,
                        "source": source,
                        "source_task_id": task_info.get("source_task_id", ""),
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "pdf_path": str(output_pdf_path),
                        "page_count": len(list((task_dir / "pages").glob("page_*.png"))),
                        "edited_pages": 1,
                        "download_count": 0,
                        # zhaoqiaotong 2026-09-10 研发需求-0167 操作内容：内容类累计+当前配方项
                        "operations": _merge_edit_pdf_operations([], ["页面编辑"], _active_transform_labels(_read_edit_pdf_recipe(task_dir)))
                    }
                    record["username"] = task_info.get("username", "admin")  # xuechong 2026-06-27
                    # xuechong 2026-07-16 只写入用户 scope，不再写全局 state
                    scope.edit_pdf_history.insert(0, record)
                    log_info(f"[编辑PDF] 已写入操作记录: {filename} (来源: {source})")
                else:
                    # 已有记录，更新时间、PDF路径和编辑页数
                    existing_rec["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    existing_rec["pdf_path"] = str(output_pdf_path)
                    edited_count = len(task_info.get("modified_pages", {}).get(file_id, set()))
                    existing_rec["edited_pages"] = edited_count
                    existing_rec["page_count"] = len(list((task_dir / "pages").glob("page_*.png")))
                    # zhaoqiaotong 2026-09-10 研发需求-0167 操作内容：内容类累计+当前配方项
                    existing_rec["operations"] = _merge_edit_pdf_operations(
                        existing_rec.get("operations"), ["页面编辑"],
                        _active_transform_labels(_read_edit_pdf_recipe(task_dir)))
                    log_info(f"[编辑PDF] 操作记录已更新时间")
                scope.save_edit_pdf_history()
            except Exception as e:
                import traceback
                traceback.print_exc()
                log_info(f"[编辑PDF] 写入操作记录失败: task_id={task_id}, file_id={file_id}, 页={page_num}, 错误: {e}")

        # zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
        # 页面编辑为内容类操作：版本号+1 使下次统一构建自动重建（含本页编辑）；
        # 仅作废该页的空白判定缓存（重建时只重判此页，其余页直接用缓存）
        # zhaoqiaotong 2026-09-17 研发BUG-0057 已在线程中执行，改同步直调
        _bump_edit_pdf_version(task_id, file_id)
        _invalidate_blank_cache(task_id, file_id, page_num)

        # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 返回 bump 后的内容版本号：前端据此构建该页 edited 图片URL的 ?v= 参数
        new_version = int(_read_edit_pdf_recipe(task_dir).get("version", 0))

        return {
            "success": True,
            "message": f"保存成功，已识别 {text_count} 个文字块",
            "text_count": text_count,
            "edited_url": f"/api/edit-pdf/page/{task_id}/{file_id}/{page_num}/edited",
            "version": new_version
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 保存页面失败: task_id={task_id}, file_id={file_id}, 页={page_num}, ocr_lang={ocr_lang}, 错误: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


@router.post("/api/edit-pdf/restore-page")
# zhaoqiaotong 2026-09-11 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# GUI复测二轮整改新增：页面还原端点。原「一键还原」是纯前端画布回退，不触达服务端
# ——已保存的手工编辑（edited_N.png/page_N_dual.pdf/modified标记/版本号/成品）全部
# 原样保留，导致下载与操作记录中的PDF不复原且界面显示与实际不一致。本端点落地真实
# 还原：
#   - 修图过的页：撤销手工编辑，回到修图后状态（用修图产物 page_N.png 重建单页双层
#     PDF：插入修图图 + 重新OCR文字层），页仍保留在 modified/ocr_processed；
#   - 未修图过的页：完全还原（删除 edited/双层产物并移出 modified），合并时回退为
#     original.pdf 对应原始页；
#   - 版本号+1 使下次统一构建自动回退；操作记录同步（edited_pages 与"页面编辑"标识）。
async def restore_edit_pdf_page(request: CleanPageRequest, req: Request):
    """还原页面：撤销该页已保存的手工编辑（服务端状态真实回退）

    zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    重活移出事件循环（与save同修）：删编辑产物/重建双层PDF含OCR推理，此前内联在
    async 处理器里同步执行会冻住整个服务；鉴权、目录校验与幂等分支留在事件循环"""
    task_id = request.task_id
    file_id = request.file_id
    page_num = request.page_num
    task, scope = _find_task_scope_verified(task_id, req)
    task_info = scope.edit_pdf_tasks[task_id]

    file_dir = Path(task_info["task_dir"]) / file_id
    pages_dir = file_dir / "pages"
    if not pages_dir.exists():
        raise HTTPException(status_code=404, detail="页面目录不存在")

    page_png = pages_dir / f"page_{page_num}.png"
    if not page_png.exists():
        raise HTTPException(status_code=404, detail="页面图片不存在")

    # 手工编辑是否存在（无编辑则幂等成功返回）
    has_edit = (pages_dir / f"edited_{page_num}.png").exists() or (pages_dir / f"edited_{page_num}.jpg").exists()
    manual_set = task_info.get("manual_edited_pages", {}).get(file_id, set())
    if not has_edit and page_num not in manual_set:
        # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 幂等分支同样返回当前内容版本号（本次未变化，前端沿用即可）
        return {
            "success": True,
            "message": "该页无已保存的手工编辑",
            "restored": False,
            "version": int(_read_edit_pdf_recipe(file_dir).get("version", 0))
        }

    return await asyncio.to_thread(
        _do_restore_edit_pdf_page, request, scope, task_info, file_dir, pages_dir, manual_set
    )


# zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
def _do_restore_edit_pdf_page(request: CleanPageRequest, scope, task_info: dict,
                              file_dir: Path, pages_dir: Path, manual_set: set) -> dict:
    """还原页面同步主体（线程中执行）：删编辑产物→（修图页）用修图产物重建双层PDF→
    版本bump与操作记录（原 restore_edit_pdf_page 主体原样迁移，await 改同步直调）"""
    import fitz

    task_id = request.task_id
    file_id = request.file_id
    page_num = request.page_num
    ocr_lang = request.ocr_lang or "ch"

    # 该页是否修图过（备份图存在=修图产物 page_N.png 为修图后状态）
    cleaned_page = (pages_dir / f"page_{page_num}_backup.png").exists()

    try:
        # 删除手工编辑产物
        for name in (f"edited_{page_num}.jpg", f"edited_{page_num}.png"):
            p = pages_dir / name
            if p.exists():
                p.unlink()
        # 移出手工编辑标记
        if page_num in manual_set:
            manual_set.discard(page_num)

        if cleaned_page:
            # 修图过的页：重建单页双层PDF（修图图 + 重新OCR文字层），页保留在 modified/ocr
            from backend.ocr_rapid import get_rapid_ocr_engine, ocr_image_with_rapid
            import cv2
            import numpy as np

            original_pdf_path = file_dir / "original.pdf"
            doc = fitz.open(str(original_pdf_path))
            try:
                page_rect = doc[page_num].rect if page_num < len(doc) else None
            finally:
                doc.close()
            if page_rect is None:
                raise HTTPException(status_code=500, detail="无法读取原PDF页面尺寸")

            page_png = pages_dir / f"page_{page_num}.png"
            img_bgr = cv2.imdecode(np.fromfile(str(page_png), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img_bgr is None:
                raise HTTPException(status_code=500, detail=f"无法读取修图后的页面图片: {page_png}")
            img_h, img_w = img_bgr.shape[:2]
            ocr_engine_info = get_rapid_ocr_engine(ocr_lang, use_cls=False, det_limit=960)
            ocr_results = ocr_image_with_rapid(img_bgr, ocr_engine_info, det_limit_side_len=960)

            page_pdf_path = pages_dir / f"page_{page_num}_dual.pdf"
            page_doc = fitz.open()
            try:
                new_page = page_doc.new_page(width=page_rect.width, height=page_rect.height)
                with open(page_png, 'rb') as f:
                    img_bytes = f.read()
                new_page.insert_image(new_page.rect, stream=img_bytes)
                text_count = 0
                if ocr_results:
                    from backend.ocr_rapid import get_cached_font
                    cached_font = get_cached_font("china-s")
                    scale_x = page_rect.width / img_w
                    scale_y = page_rect.height / img_h
                    tw = fitz.TextWriter(new_page.rect)
                    for item in ocr_results:
                        box = item['box']
                        text = item['text']
                        if not text or not text.strip():
                            continue
                        try:
                            pts = np.array(box, dtype=np.float32)
                            pts[:, 0] *= scale_x
                            pts[:, 1] *= scale_y
                            x_min = float(min(pts[:, 0]))
                            y_max = float(max(pts[:, 1]))
                            box_h = float(max(pts[:, 1])) - float(min(pts[:, 1]))
                            if box_h <= 0:
                                continue
                            font_size = max(4, min(72, box_h * 0.8))
                            baseline_y = y_max - box_h * 0.1
                            tw.append(pos=(x_min, baseline_y), text=text, font=cached_font, fontsize=font_size)
                            text_count += 1
                        except Exception as e:
                            log_info(f"[编辑PDF-还原] 写入文字失败: 页={page_num}, 文字='{text}', 错误: {e}")
                    if text_count > 0:
                        tw.write_text(new_page, color=(0, 0, 0), render_mode=3)
                page_doc.save(str(page_pdf_path), garbage=4, deflate=True)
            finally:
                page_doc.close()
            log_info(f"[编辑PDF] 页面 {page_num} 已还原为修图后状态（重建双层PDF，{text_count} 个文字块）")
        else:
            # 未修图过的页：完全还原（删除双层产物并移出 modified，合并回退原始页）
            dual = pages_dir / f"page_{page_num}_dual.pdf"
            if dual.exists():
                # zhaoqiaotong 2026-09-17 研发BUG-0057 已在线程中执行，改同步直调
                dual.unlink()
            for key in ("modified_pages", "ocr_processed_pages"):
                pages_set = task_info.get(key, {}).get(file_id)
                if pages_set and page_num in pages_set:
                    pages_set.discard(page_num)
            log_info(f"[编辑PDF] 页面 {page_num} 已完全还原为原始页")

        # 版本+1：下次统一构建自动回退（下载/操作记录随建随新）
        # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 已在线程中执行，改同步直调
        _bump_edit_pdf_version(task_id, file_id)
        _invalidate_blank_cache(task_id, file_id, page_num)

        # 操作记录同步：edited_pages 更新；无手工编辑页残留时移除"页面编辑"标识
        try:
            existing_rec = None
            for rec in scope.edit_pdf_history:
                if rec.get("task_id") == task_id and rec.get("file_id") == file_id:
                    existing_rec = rec
                    break
            if existing_rec is not None:
                existing_rec["edited_pages"] = len(task_info.get("modified_pages", {}).get(file_id, set()) or [])
                if not manual_set:
                    ops = [op for op in (existing_rec.get("operations") or []) if op != "页面编辑"]
                    existing_rec["operations"] = ops
                scope.save_edit_pdf_history()
                log_info(f"[编辑PDF] 还原后操作记录已同步: {existing_rec.get('filename', '')}")
        except Exception as e:
            log_info(f"[编辑PDF] 还原后操作记录同步失败: task_id={task_id}, file_id={file_id}, 页={page_num}, 错误: {e}")

        # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 返回 bump 后的内容版本号：前端据此重建该页 original 图片URL的 ?v= 参数
        restored_version = int(_read_edit_pdf_recipe(file_dir).get("version", 0))
        return {"success": True, "message": "已还原", "restored": True, "version": restored_version}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 还原页面失败: task_id={task_id}, file_id={file_id}, 页={page_num}, 错误: {e}")
        raise HTTPException(status_code=500, detail=f"还原失败: {str(e)}")


@router.get("/api/edit-pdf/page/{task_id}/{file_id}/{page_num}/edited")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def get_edit_pdf_page_edited(task_id: str, file_id: str, page_num: int, request: Request):
    """获取PDF页面编辑后的图片（用户隔离）"""
    _, scope = _find_task_scope_verified(task_id, request)
    edited_path = _safe_edit_pdf_path(scope, task_id, file_id, f"pages/edited_{page_num}.png")
    if edited_path.exists():
        # zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
        # 长缓存头：URL 已按内容版本号（?v=）寻址，同一URL内容不变可放心复用
        return FileResponse(str(edited_path), media_type="image/png",
                            headers={"Cache-Control": "private, max-age=86400"})

    # 如果没有编辑过，返回原图
    orig_path = _safe_edit_pdf_path(scope, task_id, file_id, f"pages/page_{page_num}.png")
    # zhaoqiaotong 2026-09-16 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题
    # 回退原图缺失时按需渲染兜底（edited 是保存产物无法按需生成，原图可以）
    # zhaoqiaotong 2026-09-17 研发BUG-0057 渲染走专用page线程池；长缓存头（URL按?v=寻址）
    if not orig_path.exists():
        await _run_edit_pdf_render(task_id, file_id, page_num, "page")
    if not orig_path.exists():
        raise HTTPException(status_code=404, detail="页面图片不存在")
    return FileResponse(str(orig_path), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/edit-pdf/check-unsaved/{task_id}/{file_id}")
# xuechong 2026-07-21 研发BUG-0009 添加用户校验防止跨用户访问
async def check_edit_pdf_unsaved(task_id: str, file_id: str, request: Request):
    """检查是否有未保存的修改（用户隔离）"""
    task, scope = _find_task_scope_verified(task_id, request)
    
    task_info = scope.edit_pdf_tasks[task_id]
    modified_pages = task_info.get("modified_pages", {}).get(file_id, set())
    ocr_processed_pages = task_info.get("ocr_processed_pages", {}).get(file_id, set())
    
    # 如果有修改但没有处理OCR，说明有未保存的修改
    # 注意：这里检查的是服务端记录，前端还需要检查当前画布是否有未保存的修改
    unsaved_pages = modified_pages - ocr_processed_pages
    
    return {
        "has_unsaved": len(unsaved_pages) > 0,
        "unsaved_pages": list(unsaved_pages),
        "modified_pages": list(modified_pages),
        "processed_pages": list(ocr_processed_pages)
    }


def merge_edit_pdf_output(file_dir: Path, original_pdf_path: Path,
                           pages_dir: Path, task_info: dict, file_id: str) -> Path:
    """合并已处理页面为最终双层PDF，返回 output.pdf 路径。

    每次调用都删除旧 output.pdf 后重新生成，确保包含最新修改。
    如果无修改页面，返回 original.pdf。
    """
    import fitz

    output_pdf_path = file_dir / "output.pdf"

    modified_pages = task_info.get("modified_pages", {}).get(file_id, set())
    ocr_processed_pages = task_info.get("ocr_processed_pages", {}).get(file_id, set())

    if not modified_pages:
        return original_pdf_path

    # 删除旧的 output.pdf，强制重新生成（避免返回过期缓存）
    if output_pdf_path.exists():
        try:
            output_pdf_path.unlink()
        except Exception as e:
            log_info(f"[编辑PDF] 删除旧 output.pdf 失败: {output_pdf_path}, 错误: {e}")

    doc = None
    new_doc = None
    try:
        doc = fitz.open(str(original_pdf_path))
        new_doc = fitz.open()

        for page_num in range(len(doc)):
            if page_num in ocr_processed_pages:
                page_pdf_path = pages_dir / f"page_{page_num}_dual.pdf"
                if page_pdf_path.exists():
                    page_doc = fitz.open(str(page_pdf_path))
                    new_doc.insert_pdf(page_doc)
                    page_doc.close()
                    log_info(f"[编辑PDF] 页面 {page_num} 使用已处理的双层PDF")
                else:
                    new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                    log_info(f"[编辑PDF] 页面 {page_num} 双层PDF不存在，使用原页面")
            else:
                new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

        # zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题
        # 合并输出前子集化字库，消除每页 page_dual.pdf 逐页内嵌全量CJK字库造成的体积放大
        from backend.services.pdf_font_service import save_pdf_with_font_subset
        save_pdf_with_font_subset(new_doc, output_pdf_path)
        return output_pdf_path
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 合并最终PDF失败: file_dir={file_dir}, file_id={file_id}, 错误: {e}")
        return original_pdf_path
    finally:
        if new_doc:
            new_doc.close()
        if doc:
            doc.close()


# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 检测并移除各页底部旧页码文本（"- N -"格式），返回处理的页数。
# 逻辑原样抽取自 _remove_blank_pages_edit_pdf（3.2.08 已在453样张验证），供"去除空白页"
# 与"添加页码"两处复用；find_old_pagenum_rects 保守判定（页码带内有其他文字返回None不移除）。
# redact 不改变页数；fill=False 不补白块（白底上的旧页码移除后即露出白底）。
# zhaoqiaotong 2026-09-14 研发BUG-0052-图档扫描-3.2.11-修复编辑PDF模块对已有页码PDF添加页码时，部分旧页码残留
# 检测升级：整带全匹配在页码带内混有正文时整体放弃（pic2.pdf 第1/2页表格表头/厂商页脚
# 与旧页码共存即漏检、残留双重页码），改用 find_old_pagenum_rects_in_doc 跨页一致性
# 校验（词组候选+序号连续+位置一致+字体一致取最长链），带内有正文仍可检出；
# 判据不满足仍按无旧页码处理（不劣于修复前，宁漏检不误删）。
def _redact_old_pagenums(doc) -> int:
    """移除各页旧页码文本（redact），返回实际处理的页数（0=未检出旧页码）"""
    import fitz

    from backend.services.blank_page_service import find_old_pagenum_rects_in_doc

    redact_count = 0
    for page_num, num_rects in enumerate(find_old_pagenum_rects_in_doc(doc)):
        if not num_rects:
            continue
        for r in num_rects:
            # 外扩1pt确保字形边缘完全覆盖
            doc[page_num].add_redact_annot(r + (-1, -1, 1, 1), fill=False)
        doc[page_num].apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            text=fitz.PDF_REDACT_TEXT_REMOVE,
        )
        redact_count += 1
    return redact_count


# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
# 在合并结果副本上叠加页码：复用 backend\app.py 的 add_page_numbers 唯一权威实现
# （经 _hsvc 懒加载代理调用，与图片转PDF页码规格完全一致：宋体/黑色/10pt/底部居中7mm/- X -/从1连续）。
# 零回归红线（沿用研发需求-0138）：字体缺失或任何异常时仅记日志并返回原路径，
# 下载到的仍是不带页码的正常合并结果，本函数绝不抛异常、绝不影响输出。
# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 页码安全：添加前先检测旧页码，检出则 redact 移除后连续重编号（杜绝只勾"添加页码"
# 对已带页码PDF产生双重页码）；返回值改为 (路径, 是否重编页码) 供效果摘要透出。
# zhaoqiaotong 2026-09-14 研发BUG-0052-图档扫描-3.2.11-修复编辑PDF模块对已有页码PDF添加页码时，部分旧页码残留
# 检测升级为 find_old_pagenum_rects_in_doc 跨页一致性校验：页码带内混有正文（页脚地址/
# 表格表头）时旧页码仍可检出移除，修复"部分旧页码残留"。
def _stamp_page_numbers_edit_pdf(file_dir: Path, src_pdf_path: Path):
    """为合并结果副本添加页码，返回(最终路径, 是否移除旧页码并重编号)。

    - 未检出旧页码：严格分离路径（3.2.05）——复制副本后增量追加页码，体积≈原文件+页码；
    - 检出旧页码：打开源文件 redact 移除旧页码后连续重编号，结构性修改全量保存到副本
      （体积影响由瘦身/子集化收口）；
    - 任何异常仅记日志并返回(原路径, False)，输出永不失败。
    """
    import fitz

    from backend.services.blank_page_service import find_old_pagenum_rects_in_doc

    output_path = file_dir / "output_pagenum.pdf"
    try:
        # 先对源文件只读检测旧页码（决定走增量追加还是移除重编路径）
        detect_doc = fitz.open(str(src_pdf_path))
        try:
            renumbered = any(find_old_pagenum_rects_in_doc(detect_doc))
        finally:
            detect_doc.close()

        # 删除旧页码文件后重新生成，避免返回过期缓存（与 output.pdf 同策略）
        if output_path.exists():
            try:
                output_path.unlink()
            except Exception as e:
                log_info(f"[编辑PDF] 删除旧页码文件失败: {output_path}, 错误: {e}")

        if not renumbered:
            # 无旧页码：复制原文件后增量追加页码（严格分离：不整体重写/回收任何对象）
            shutil.copy2(str(src_pdf_path), str(output_path))
            doc = fitz.open(str(output_path))
            try:
                # 复用页码函数：True=已加页码；False=字体缺失等兜底（函数内部已记日志）
                added = _hsvc.add_page_numbers(doc)
                if not added:
                    # 页码未添加（兜底）：删除副本，返回原路径，PDF 照常输出
                    output_path.unlink(missing_ok=True)
                    return src_pdf_path, False
                # 增量保存：只在原文件字节上追加页码对象，体积≈原文件+页码，不做任何瘦身
                doc.save(str(output_path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
                return output_path, False
            finally:
                doc.close()

        # 检出旧页码：redact 移除后连续重编号（防双重页码）；结构性修改全量保存到副本
        doc = fitz.open(str(src_pdf_path))
        try:
            redacted = _redact_old_pagenums(doc)
            log_info(f"[编辑PDF] 添加页码前已移除 {redacted} 页旧页码文本（连续重编号）")
            added = _hsvc.add_page_numbers(doc)
            if not added:
                # 页码未添加（兜底）：放弃副本返回原路径（旧页码保留，PDF 照常输出）
                return src_pdf_path, False
            doc.save(str(output_path), garbage=3, deflate=True)
            return output_path, True
        finally:
            doc.close()
    except Exception as e:
        import traceback
        traceback.print_exc()
        # 兜底：失败时清理可能不完整的页码副本，返回原路径
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass
        log_info(f"[编辑PDF] 添加页码失败，输出不带页码的合并结果: {src_pdf_path}, 错误: {e}")
        return src_pdf_path, False


# zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
# 编辑PDF去除空白页：删除合并结果中的空白页并移除剩余页旧页码，由调用方决定重编页码。
# 空白页判定复用 backend\services\blank_page_service.py（渲染120dpi+连通域，排除底部
# 旧页码文字像素，只有页码的"空白页"可正确识别；检测异常按非空白保留，零误删红线）。
# 旧页码必须移除而不能靠白底衬遮挡：add_page_numbers 的腾位检测会把旧页码误判为
# "区域已有正文"，每页误触发内容上移/缩放（研发BUG-0041腾位逻辑被错误激活），
# 且文本层会残留双份页码（复制/搜索出两个页码号）。
# 移除方式：add_redact_annot + apply_redactions(images=PDF_REDACT_IMAGE_NONE,
# graphics=PDF_REDACT_LINE_ART_NONE)——仅删除页码文字，页面图像铺满整页绝不能
# 用默认 images 参数（默认值会涂黑 redact 区域内的图像像素）。
def _remove_blank_pages_edit_pdf(file_dir: Path, src_pdf_path: Path, blank_cache: dict = None):
    """删除空白页并移除剩余页旧页码，返回(最终路径, 删除页数, 是否检出旧页码)。

    处理顺序（需求"删除空白页之后注意更新页码"的落地）：
    1. 逐页空白判定（先于任何修改，页序稳定）。blank_cache 提供时按页缓存判定结果：
       命中页跳过渲染检测直接复用（页面内容未变时判定结果不变；编辑/修图页由调用方
       作废对应缓存条目，实现"只重判变动页"）
    2. 移除保留页旧页码文本（按删页前的页序 redact，redact 不改变页数；逻辑抽取为
       _redact_old_pagenums 公共函数，与"添加页码"防双重页码复用）
    3. delete_pages 删除空白页
    4. 保存到副本 output_noblank.pdf（结构性改动不可增量保存）
    无空白页且无旧页码 → 返回原路径不产生副本；全部页均为空白 → 放弃删除（0页PDF非法）。
    零回归红线：任何异常仅记日志并返回(原路径, 0, False)，输出永不失败。
    """
    import fitz

    from backend.services.blank_page_service import is_blank_pdf_page

    output_path = file_dir / "output_noblank.pdf"
    try:
        doc = fitz.open(str(src_pdf_path))
        try:
            page_count = len(doc)

            # 第一步：逐页空白判定（渲染+连通域，排除底部旧页码文字像素）
            blank_indices = []
            for page_num in range(page_count):
                # zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
                # 缓存命中：页面内容未变（原始页索引稳定），直接复用历史判定结果
                if blank_cache is not None and page_num in blank_cache:
                    if blank_cache[page_num]:
                        blank_indices.append(page_num)
                        log_info(f"[编辑PDF] 第 {page_num + 1} 页为空白页（缓存判定）")
                    continue
                _blank, _reason = is_blank_pdf_page(doc[page_num])
                # zhaoqiaotong 2026-09-10 研发需求-0167 新判定写回缓存（供后续构建复用）
                if blank_cache is not None:
                    blank_cache[page_num] = _blank
                if _blank:
                    blank_indices.append(page_num)
                    log_info(f"[编辑PDF] 第 {page_num + 1} 页为空白页: {_reason}")

            # 全部页均为空白：放弃删除（0页PDF非法），带页码的页不会被判空白，此处仅防御
            if blank_indices and len(blank_indices) == page_count:
                log_info(f"[编辑PDF] 全部 {page_count} 页均为空白页，放弃删除，按原文件返回")
                return src_pdf_path, 0, False

            # 第二步：保留页旧页码检测与移除（无论是否删页，检出旧页码即移除供调用方重编号）
            # zhaoqiaotong 2026-09-10 研发需求-0167 redact 逻辑抽取为公共函数（与页码安全复用）
            redact_count = _redact_old_pagenums(doc)
            had_old_pagenum = redact_count > 0
            if had_old_pagenum:
                log_info(f"[编辑PDF] 已移除 {redact_count} 页的旧页码文本（待重编连续页码）")

            # 无空白页且无旧页码：返回原路径，不产生副本（对现网零影响）
            if not blank_indices and not had_old_pagenum:
                return src_pdf_path, 0, False

            # 第三步：删除空白页（redact 不改变页数，blank_indices 仍有效）
            if blank_indices:
                doc.delete_pages(blank_indices)
                log_info(f"[编辑PDF] 已删除 {len(blank_indices)} 张空白页（原页序）: {[i + 1 for i in blank_indices]}")

            # 第四步：保存副本（先删旧副本避免过期缓存，与其他输出副本同策略）
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception as e:
                    log_info(f"[编辑PDF] 删除旧去空白页文件失败: {output_path}, 错误: {e}")
            # 结构性改动不可增量保存；garbage=3 回收被删页面孤立对象
            doc.save(str(output_path), garbage=3, deflate=True)
            return output_path, len(blank_indices), had_old_pagenum
        finally:
            doc.close()
    except Exception as e:
        import traceback
        traceback.print_exc()
        # 兜底：清理可能不完整的副本，返回原路径（下载永不失败）
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass
        log_info(f"[编辑PDF] 去除空白页失败，下载未去空白的合并结果: {src_pdf_path}, 错误: {e}")
        return src_pdf_path, 0, False


# zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题 编辑PDF下载瘦身副本
def _shrink_edit_pdf_output(file_dir: Path, src_pdf_path: Path) -> Path:
    """为编辑PDF下载结果生成字体子集化瘦身副本，返回最终下载路径。

    与生成侧修复同源（backend/services/pdf_font_service.py）：先 doc.subset_fonts()
    再以 garbage=4 + deflate=True 保存，去除每页重复内嵌的全量中文字库；
    图片流、页面尺寸、OCR文字层、页码均不变。任何异常仅记日志并返回原路径，
    下载永不失败（零回归红线，与页码函数一致）。
    """
    try:
        if src_pdf_path.name == "output_pagenum.pdf":
            output_path = file_dir / "output_pagenum_shrink.pdf"
        else:
            output_path = file_dir / "output_shrink.pdf"
        # 删除旧瘦身副本后重新生成，避免返回过期缓存（与其他输出副本同策略）
        if output_path.exists():
            output_path.unlink()

        import fitz  # PyMuPDF

        from backend.services.pdf_font_service import save_pdf_with_font_subset

        doc = fitz.open(str(src_pdf_path))
        try:
            save_pdf_with_font_subset(doc, output_path)
        finally:
            doc.close()
        return output_path
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 瘦身失败，下载未瘦身的合并结果: {src_pdf_path}, 错误: {e}")
        return src_pdf_path


# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 统一输出构建入口（处理配方模型的唯一成品生成路径）：
#   合并最新页面（原件+修图/编辑成果）→（配方：去除空白页→添加页码→PDF瘦身，顺序与
#   3.2.08 既有链一致）→ 固化稳定产物 output_final.pdf → 刷新存档快照（操作记录用）。
# 复用机制：内容版本号与配方均未变且 output_final.pdf 存在 → 直接复用零重建
# （批量下载未编辑文件≈仅打包IO；编辑过的文件只重判变动页，秒级）。
# 并发安全：per-file 构建锁串行化（锁内二次复用检查）。
# 零回归红线：任何异常兜底返回合并结果/原件，输出永不失败；效果摘要如实记录未生效项。
def _build_edit_pdf_output(scope, task_id: str, file_id: str):
    """统一构建：按处理配方与最新编辑生成成品，返回(最终PDF路径, 效果摘要dict)。

    effects 结构：{remove_blank_applied, removed_blank_pages, pagenum_applied, renumbered,
    shrink_applied, not_applied: [未生效说明...], page_count, snapshot: 存档快照路径或None}
    """
    import fitz

    _validate_edit_pdf_ids(task_id, file_id)
    task_info = scope.edit_pdf_tasks.get(task_id)
    if task_info is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    file_dir = Path(task_info["task_dir"]) / file_id
    original_pdf_path = file_dir / "original.pdf"
    pages_dir = file_dir / "pages"
    if not original_pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF文件不存在")

    recipe = _read_edit_pdf_recipe(file_dir)
    final_path = file_dir / "output_final.pdf"

    def _recipe_unchanged() -> bool:
        """配方激活项与上次构建时是否一致（复用判定的配方维度）"""
        built = recipe.get("built_recipe") or {}
        return (built.get("remove_blank_pages") == recipe["remove_blank_pages"]
                and built.get("add_page_number") == recipe["add_page_number"]
                and built.get("shrink") == recipe["shrink"])

    def _reusable() -> bool:
        """复用判定：产物存在 且 版本未变 且 配方未变（双校验缺一不可）"""
        return (final_path.exists()
                and recipe.get("version") == recipe.get("built_version")
                and _recipe_unchanged())

    def _recipe_effect_flags(effects: dict):
        """按配方激活项填充 effects 布尔位（复用/兜底路径无实际执行信息时按配方报告）"""
        effects["remove_blank_applied"] = bool(recipe["remove_blank_pages"])
        effects["pagenum_applied"] = bool(recipe["add_page_number"])
        effects["shrink_applied"] = bool(recipe["shrink"])
        # FIX-J3 空白页判定列表（去空白配方激活时从缓存读出，供前端页面列表角标）
        if recipe["remove_blank_pages"]:
            cache = _edit_pdf_blank_cache.get(f"{task_id}_{file_id}", {})
            effects["blank_pages"] = sorted(k for k, v in cache.items() if v)
        else:
            effects["blank_pages"] = []
        return effects

    # 现网快速路径（零回归）：无配方激活且无修改页 → 直接返回原件，不产生任何构建产物
    modified_pages = task_info.get("modified_pages", {}).get(file_id, set())
    recipe_active = bool(recipe["remove_blank_pages"] or recipe["add_page_number"] or recipe["shrink"])
    if not recipe_active and not modified_pages:
        return original_pdf_path, _recipe_effect_flags({
            "removed_blank_pages": 0, "renumbered": False, "not_applied": [], "page_count": 0, "snapshot": None
        })

    # 锁外快查：可复用直接返回（最常见路径，批量下载未编辑文件零重建）
    if _reusable():
        return final_path, _recipe_effect_flags({
            "removed_blank_pages": 0, "renumbered": False, "not_applied": [], "page_count": 0, "snapshot": None
        })

    with _get_edit_pdf_build_lock(task_id, file_id):
        # 锁内二次复用检查：等待锁期间另一请求可能已完成重建
        if _reusable():
            return final_path, _recipe_effect_flags({
                "removed_blank_pages": 0, "renumbered": False, "not_applied": [], "page_count": 0, "snapshot": None
            })

        effects = {"remove_blank_applied": False, "removed_blank_pages": 0, "pagenum_applied": False,
                   "renumbered": False, "shrink_applied": False, "not_applied": [],
                   "page_count": 0, "snapshot": None}

        # 第一步：合并（原件 或 替换修改页后的页级拼接结果）；merge 异常兜底返回原件
        try:
            base = merge_edit_pdf_output(file_dir, original_pdf_path, pages_dir, task_info, file_id)
        except Exception as e:
            import traceback
            traceback.print_exc()
            log_info(f"[编辑PDF] 统一构建合并失败，兜底返回原件: task_id={task_id}, file_id={file_id}, 错误: {e}")
            effects["not_applied"] = [f"{label}(构建异常未生效)" for label in _active_transform_labels(recipe)]
            return original_pdf_path, _recipe_effect_flags(effects)

        # 第二步：配方链（顺序固化：去空白页→加页码→瘦身）；单项异常由各函数内部兜底
        try:
            had_old_pagenum = False
            if recipe["remove_blank_pages"]:
                blank_cache = _edit_pdf_blank_cache.setdefault(f"{task_id}_{file_id}", {})
                base, removed, had_old_pagenum = _remove_blank_pages_edit_pdf(file_dir, base, blank_cache)
                effects["removed_blank_pages"] = removed
                effects["remove_blank_applied"] = removed > 0
                # FIX-J3 本次构建判定的空白页原始页索引（0基），供前端页面列表角标
                effects["blank_pages"] = sorted(k for k, v in blank_cache.items() if v)
                if removed > 0:
                    log_info(f"[编辑PDF] 统一构建-去除空白页生效: 删除{removed}页")
                else:
                    effects["not_applied"].append("去除空白页(未检出空白页)")

            if recipe["add_page_number"] or had_old_pagenum:
                stamped_path, renumbered = _stamp_page_numbers_edit_pdf(file_dir, base)
                applied = stamped_path != base
                effects["renumbered"] = renumbered
                if recipe["add_page_number"]:
                    effects["pagenum_applied"] = applied
                    if applied:
                        log_info(f"[编辑PDF] 统一构建-添加页码生效{'（旧页码已移除并重编号）' if renumbered else ''}")
                    else:
                        effects["not_applied"].append("添加页码(未生效，详见日志)")
                elif applied:
                    # 未勾页码但因去空白检出旧页码自动重编，如实记录
                    effects["pagenum_applied"] = True
                    log_info("[编辑PDF] 统一构建-检出旧页码已自动移除并重编号")
                base = stamped_path

            if recipe["shrink"]:
                shrunk_path = _shrink_edit_pdf_output(file_dir, base)
                effects["shrink_applied"] = shrunk_path != base
                if effects["shrink_applied"]:
                    log_info("[编辑PDF] 统一构建-PDF瘦身生效")
                else:
                    effects["not_applied"].append("PDF瘦身(未生效，详见日志)")
                base = shrunk_path
        except Exception as e:
            import traceback
            traceback.print_exc()
            log_info(f"[编辑PDF] 统一构建配方链异常，兜底返回合并结果: task_id={task_id}, file_id={file_id}, 错误: {e}")
            effects["not_applied"] = list(dict.fromkeys(
                effects["not_applied"] + [f"{label}(构建异常未生效)" for label in _active_transform_labels(recipe)]))
            return base, effects

        # 第三步：固化为稳定产物 output_final.pdf（先删旧避免半成品；大文件复制可接受秒级）
        try:
            if final_path.exists():
                final_path.unlink()
            shutil.copy2(str(base), str(final_path))
        except Exception as e:
            import traceback
            traceback.print_exc()
            log_info(f"[编辑PDF] 统一构建固化产物失败，兜底返回链结果: task_id={task_id}, file_id={file_id}, 错误: {e}")
            return base, effects

        # 第四步：更新构建基准（复用判定依据）并刷新存档快照（操作记录预览/下载与任务清理后的终版）
        recipe["built_version"] = recipe["version"]
        recipe["built_recipe"] = {
            "remove_blank_pages": recipe["remove_blank_pages"],
            "add_page_number": recipe["add_page_number"],
            "shrink": recipe["shrink"],
        }
        try:
            _write_edit_pdf_recipe(file_dir, recipe)
        except Exception as e:
            log_info(f"[编辑PDF] 统一构建写配方失败（复用判定退化为重建，无害）: {task_id}/{file_id}, 错误: {e}")

        try:
            snapshot_path = _get_edit_pdf_snapshot_path(scope, task_id, file_id)
            if snapshot_path.exists():
                snapshot_path.unlink()
            shutil.copy2(str(final_path), str(snapshot_path))
            effects["snapshot"] = str(snapshot_path)
        except Exception as e:
            log_info(f"[编辑PDF] 存档快照刷新失败（不影响构建）: {task_id}/{file_id}, 错误: {e}")

        try:
            d = fitz.open(str(final_path))
            try:
                effects["page_count"] = len(d)
            finally:
                d.close()
        except Exception:
            effects["page_count"] = 0

        return final_path, effects


@router.get("/api/edit-pdf/recipe/{task_id}/{file_id}")
# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 查询文件当前处理配方（「一键处理」配置弹窗回显用）
# zhaoqiaotong 2026-09-11 研发需求-0167 GUI复测二轮整改 返回值增加 cleaned 标志：
# 修图会为每页生成 page_N_backup.png 备份，以备份存在性判定"是否已修图过"，
# 跨会话准确（前端会话内标志刷新即丢），供一键处理防重复执行判定
# zhaoqiaotong 2026-09-12 研发需求-0167 五轮整改（FIX-J3）返回值增加 blank_pages：
# 去空白配方激活时回传缓存判定的空白页原始页索引列表（0基），供前端页面列表
# 显示"空白页·导出时已去除"角标（用户实测反馈：列表仍显示空白页会误导"未去除"）
async def get_edit_pdf_recipe(task_id: str, file_id: str, request: Request):
    """获取指定PDF文件当前的处理配方、已修图标志与空白页判定（用户隔离）"""
    task, scope = _find_task_scope_verified(task_id, request)
    _validate_edit_pdf_ids(task_id, file_id)
    file_dir = Path(task["task_dir"]) / file_id
    recipe = await asyncio.to_thread(_read_edit_pdf_recipe, file_dir)

    def _has_clean_backup() -> bool:
        pages_dir = file_dir / "pages"
        return any(pages_dir.glob("page_*_backup.png")) if pages_dir.exists() else False

    cleaned = await asyncio.to_thread(_has_clean_backup)

    # 空白页判定列表：仅去空白配方激活时有效（未激活导出本就包含空白页，不标记）
    def _blank_pages() -> list:
        if not recipe["remove_blank_pages"]:
            return []
        cache = _edit_pdf_blank_cache.get(f"{task_id}_{file_id}", {})
        return sorted(k for k, v in cache.items() if v)

    return {
        "recipe": {
            "remove_blank_pages": recipe["remove_blank_pages"],
            "add_page_number": recipe["add_page_number"],
            "shrink": recipe["shrink"],
        },
        "cleaned": cleaned,
        "blank_pages": _blank_pages()
    }


@router.get("/api/edit-pdf/download/{task_id}/{file_id}")
# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 添加用户校验防止跨用户访问
# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 下载简化为"统一构建结果的取货"：原 remove_blank_pages/add_page_number/shrink 三个
# 下载时开关参数移除（配方由「一键处理」设置，长期生效）；下载零处理决策、零记录写入
# （操作内容已由一键处理/保存页面/OCR完整记录）。未设置配方且无修改页时返回原件
# （与现网行为完全一致，零回归）；版本与配方未变时复用 output_final.pdf（零重建）。
async def download_edit_pdf_file(task_id: str, file_id: str, request: Request):
    """下载处理完成后的PDF（统一构建：处理配方+最新编辑；用户隔离）"""
    from urllib.parse import quote

    task, scope = _find_task_scope_verified(task_id, request)

    pdf_to_download, _effects = await asyncio.to_thread(
        _build_edit_pdf_output, scope, task_id, file_id
    )

    # zhaoqiaotong 2026-09-12 研发需求-0167 七轮整改（FIX-L1）主界面单文件下载
    # 统一计入下载次数（与批量/弹窗内下载一致；download_count 为统计字段，
    # 不属于"下载零操作内容写入"原则约束的范围）
    try:
        rec = _find_edit_pdf_record_by_key(scope, task_id, file_id)
        if rec is not None:
            rec["download_count"] = rec.get("download_count", 0) + 1
            scope.save_edit_pdf_history()
    except Exception as e:
        log_info(f"[编辑PDF] 下载计次失败（不影响下载）: task_id={task_id}, file_id={file_id}, 错误: {e}")

    # 查找文件名
    filename = "output.pdf"
    for f in task.get("files", []):
        if f.get("file_id") == file_id:
            filename = f.get("filename", "output.pdf")
            break

    encoded_filename = quote(filename, safe='')

    return FileResponse(
        path=str(pdf_to_download),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="output.pdf"; filename*=UTF-8\'\'{encoded_filename}'
        }
    )


# zhaoqiaotong 2026-09-09 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能
# 批量下载勾选的多个PDF处理结果（ZIP打包）。
# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 简化为逐文件统一构建（_build_edit_pdf_output）：三个下载时开关参数移除（配方由
# 「一键处理」按文件设置），版本与配方未变的文件零重建直接复用 output_final.pdf；
# 下载全程零记录写入。单个文件构建异常仅记日志并跳过（ZIP内不含该文件），绝不中断
# 整批；全部失败才报错。ZIP落盘 task_dir 流式打包（单文件上限1GB，禁止内存组包），
# 响应发送完成后由 BackgroundTask 删除临时ZIP。
@router.get("/api/edit-pdf/download-multiple/{task_id}")
async def download_edit_pdf_files_batch(task_id: str, request: Request, file_ids: str = ""):
    """批量下载多个处理完成的PDF文件（ZIP打包，用户隔离）"""
    import zipfile
    from urllib.parse import quote
    from starlette.background import BackgroundTask

    task, scope = _find_task_scope_verified(task_id, request)

    # 解析 file_ids：逗号分隔、去空白、去重、保持传入顺序
    seen_ids = set()
    ordered_ids = []
    for fid in file_ids.split(','):
        fid = fid.strip()
        if fid and fid not in seen_ids:
            seen_ids.add(fid)
            ordered_ids.append(fid)
    if not ordered_ids:
        raise HTTPException(status_code=400, detail="未指定要下载的PDF文件")

    # 防御性校验：file_id 必须属于当前任务（正常前端不会传非法id）
    task_files = {f.get("file_id"): f for f in task.get("files", [])}
    invalid_ids = [fid for fid in ordered_ids if fid not in task_files]
    if invalid_ids:
        raise HTTPException(status_code=400, detail=f"文件不属于当前任务: {','.join(invalid_ids)}")

    task_dir = Path(task["task_dir"])

    # 逐文件统一构建（与单文件下载完全同链：各文件独立按自身配方与版本判定复用/重建）
    success_entries = []  # (ZIP内条目名, 最终PDF路径)
    for file_id in ordered_ids:
        file_info = task_files[file_id]
        filename = file_info.get("filename", "output.pdf")
        try:
            pdf_to_download, _effects = await asyncio.to_thread(
                _build_edit_pdf_output, scope, task_id, file_id
            )
            # zhaoqiaotong 2026-09-12 研发需求-0167 七轮整改（FIX-L1）批量下载
            # 逐文件计入下载次数（与单文件主按钮/弹窗内下载一致）
            try:
                rec = _find_edit_pdf_record_by_key(scope, task_id, file_id)
                if rec is not None:
                    rec["download_count"] = rec.get("download_count", 0) + 1
            except Exception as e:
                log_info(f"[编辑PDF] 批量下载计次失败（不影响下载）: 文件名={filename}, 错误: {e}")
            # ZIP条目名优先用上传相对路径（保留子文件夹结构，避免不同子文件夹同名冲突）
            arc_name = file_info.get("path") or filename
            success_entries.append((arc_name, pdf_to_download))
        except Exception as e:
            import traceback
            traceback.print_exc()
            log_info(f"[编辑PDF] 批量下载单文件构建失败（已跳过）: 文件名={filename}, 错误: {e}")

    # 计次统一落盘一次（循环内仅改内存，减少json写放大）
    try:
        scope.save_edit_pdf_history()
    except Exception as e:
        log_info(f"[编辑PDF] 批量下载计次落盘失败（不影响下载）: 错误: {e}")

    if not success_entries:
        raise HTTPException(status_code=500, detail="批量下载失败：所有文件处理均失败")

    # 打包ZIP（落盘 task_dir，逐文件流式写入）
    zip_path = task_dir / f"batch_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for arc_name, pdf_path in success_entries:
                zf.write(pdf_path, arcname=arc_name)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"打包ZIP失败: {str(e)}")

    folder_name = task.get("folder_name", "批量编辑")
    encoded_zipname = quote(f"{folder_name}-批量编辑.zip", safe='')
    log_info(
        f"[编辑PDF] 批量下载完成: 任务={task_id}, 成功={len(success_entries)}/{len(ordered_ids)}（统一构建，按文件配方）"
    )

    # 响应发送完成后由后台任务删除临时ZIP，不占数据盘
    def _cleanup_batch_zip(path: Path):
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            log_info(f"[编辑PDF] 清理批量下载临时ZIP失败: {path}, 错误: {e}")

    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        background=BackgroundTask(_cleanup_batch_zip, zip_path),
        headers={
            "Content-Disposition": f'attachment; filename="batch_download.zip"; filename*=UTF-8\'\'{encoded_zipname}'
        }
    )


# 编辑PDF操作记录接口（用户隔离版）
@router.get("/api/edit-pdf/history")
# xuechong 2026-07-18 获取当前用户的编辑PDF操作记录（用户隔离）
async def get_edit_pdf_history(request: Request):
    """获取当前用户的编辑PDF操作记录（用户隔离，从 scope 读取）"""
    # xuechong 2026-07-16 用户隔离：从 scope 读取而非全局 state
    scope = _get_scope(request)
    return {"history": scope.edit_pdf_history}


@router.delete("/api/edit-pdf/history/{index}")
# xuechong 2026-07-18 删除编辑PDF操作记录
# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 删除记录时连带清理存档快照（edit_pdf_dir 下），不留孤儿文件
async def delete_edit_pdf_history(index: int, request: Request):
    """删除编辑PDF操作记录（连带清理存档快照）"""
    scope = _get_scope(request)
    try:
        if 0 <= index < len(scope.edit_pdf_history):
            rec = scope.edit_pdf_history.pop(index)
            # zhaoqiaotong 2026-09-10 研发需求-0167 清理该记录的存档快照（仅限本用户快照目录内）
            try:
                pdf_path = rec.get("pdf_path", "")
                if pdf_path and scope.edit_pdf_dir in Path(pdf_path).parents:
                    snapshot = Path(pdf_path)
                    if snapshot.exists():
                        await asyncio.to_thread(snapshot.unlink)
                        log_info(f"[编辑PDF] 已清理存档快照: {snapshot}")
            except Exception as e:
                log_info(f"[编辑PDF] 清理存档快照失败（记录已删除）: {rec.get('filename', '未知')}, 错误: {e}")
            scope.save_edit_pdf_history()
            log_info(f"[编辑PDF] user={scope.username} 已删除: {rec.get('filename', '未知')}")
            return {"success": True}
        raise HTTPException(status_code=404, detail="记录不存在")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"删除记录失败: {str(e)}")


# zhaoqiaotong 2026-09-11 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# GUI复测缺陷修复：操作记录按下标寻址在"前端取列表之后、点击之前"发生记录插入
# （insert(0) 使全部下标错位一位）时会预览/下载/删除到别的文件——3.2.10 一键处理
# 高频写记录后该竞态实测复现。修复：预览/下载/删除改为按记录天然键 task_id+file_id
# 寻址（键在记录生命周期内稳定，不受列表插入影响），旧下标端点保留兼容过渡。
def _find_edit_pdf_record_by_key(scope, task_id: str, file_id: str):
    """按 task_id+file_id 查找操作记录（返回记录dict或None；同键多条时取首条，与更新逻辑一致）"""
    for rec in scope.edit_pdf_history:
        if rec.get("task_id") == task_id and rec.get("file_id") == file_id:
            return rec
    return None


async def _resolve_edit_pdf_record_pdf(scope, rec) -> str:
    """解析操作记录当前应服务的PDF路径：任务存活→统一构建最新版（含配方与最新编辑，
    复用机制同样生效）；任务已被清理→返回存档快照（此时文件不可能再被编辑，快照即终版）。
    构建成功后把记录 pdf_path 指向快照（任务清理后仍可访问；指针无变化不重复落盘）。"""
    pdf_path = rec.get("pdf_path", "")
    task_id = rec.get("task_id", "")
    file_id = rec.get("file_id", "")
    task = scope.edit_pdf_tasks.get(task_id)
    if task and any(f.get("file_id") == file_id for f in task.get("files", [])):
        try:
            built_path, built_effects = await asyncio.to_thread(
                _build_edit_pdf_output, scope, task_id, file_id
            )
            snapshot = built_effects.get("snapshot")
            if snapshot:
                built_path = snapshot
                if rec.get("pdf_path") != snapshot:
                    rec["pdf_path"] = snapshot
                    scope.save_edit_pdf_history()
            pdf_path = str(built_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            log_info(f"[编辑PDF] 操作记录解析构建失败，回退记录路径: 文件名={rec.get('filename', '')}, 错误: {e}")
    return pdf_path


@router.get("/api/edit-pdf/record/{task_id}/{file_id}/preview")
# zhaoqiaotong 2026-09-11 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 操作记录预览（按记录键寻址，防下标错位；前端URL携带 _t 缓存戳防浏览器回放旧响应）
async def preview_edit_pdf_record_by_key(task_id: str, file_id: str, request: Request):
    """按 task_id+file_id 预览操作记录中的文件（任务存活构建最新版，否则存档快照）"""
    scope = _get_scope(request)
    _validate_edit_pdf_ids(task_id, file_id)
    rec = _find_edit_pdf_record_by_key(scope, task_id, file_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    pdf_path = await _resolve_edit_pdf_record_pdf(scope, rec)
    if pdf_path and Path(pdf_path).exists():
        return FileResponse(path=pdf_path, media_type="application/pdf", headers={"Content-Disposition": "inline"})
    raise HTTPException(status_code=404, detail="文件不存在")


@router.get("/api/edit-pdf/record/{task_id}/{file_id}/download")
# zhaoqiaotong 2026-09-11 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 操作记录下载（按记录键寻址；download_count 累加沿用既有行为）
async def download_edit_pdf_record_by_key(task_id: str, file_id: str, request: Request):
    """按 task_id+file_id 下载操作记录中的文件"""
    from urllib.parse import quote
    scope = _get_scope(request)
    _validate_edit_pdf_ids(task_id, file_id)
    rec = _find_edit_pdf_record_by_key(scope, task_id, file_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    pdf_path = await _resolve_edit_pdf_record_pdf(scope, rec)
    filename = rec.get("filename", "output.pdf")
    if pdf_path and Path(pdf_path).exists():
        rec["download_count"] = rec.get("download_count", 0) + 1
        scope.save_edit_pdf_history()
        encoded_filename = quote(filename, safe='')
        log_info(f"[编辑PDF] 下载历史文件(按键): {filename}, pdf_path={pdf_path}")
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="output.pdf"; filename*=UTF-8\'\'{encoded_filename}'}
        )
    log_info(f"[编辑PDF] 下载文件不存在(按键): {filename}, pdf_path={pdf_path}")
    raise HTTPException(status_code=404, detail="文件不存在")


@router.delete("/api/edit-pdf/record/{task_id}/{file_id}")
# zhaoqiaotong 2026-09-11 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 操作记录删除（按记录键寻址；连带清理存档快照，与下标版删除同策略）
async def delete_edit_pdf_record_by_key(task_id: str, file_id: str, request: Request):
    """按 task_id+file_id 删除操作记录（连带清理存档快照）"""
    scope = _get_scope(request)
    _validate_edit_pdf_ids(task_id, file_id)
    rec = _find_edit_pdf_record_by_key(scope, task_id, file_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        scope.edit_pdf_history.remove(rec)
    except ValueError:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        pdf_path = rec.get("pdf_path", "")
        if pdf_path and scope.edit_pdf_dir in Path(pdf_path).parents:
            snapshot = Path(pdf_path)
            if snapshot.exists():
                await asyncio.to_thread(snapshot.unlink)
                log_info(f"[编辑PDF] 已清理存档快照: {snapshot}")
    except Exception as e:
        log_info(f"[编辑PDF] 清理存档快照失败（记录已删除）: {rec.get('filename', '未知')}, 错误: {e}")
    scope.save_edit_pdf_history()
    log_info(f"[编辑PDF] user={scope.username} 已删除(按键): {rec.get('filename', '未知')}")
    return {"success": True}


@router.get("/api/edit-pdf/history-preview/{index}")
# xuechong 2026-07-18 预览编辑PDF操作记录中的文件
# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 任务存活→统一构建最新版（含配方与最新编辑，复用机制同样生效）；任务已被清理→
# 返回存档快照（此时文件不可能再被编辑，快照即终版）；均不可得→404
# zhaoqiaotong 2026-09-11 研发需求-0167 GUI复测缺陷修复：下标寻址存在列表插入错位
# 竞态，前端已改用按键寻址端点；本下标端点保留兼容过渡（解析逻辑已抽公共函数）
async def preview_edit_pdf_history(index: int, request: Request):
    """预览编辑PDF操作记录中的文件（任务存活时构建最新版，否则返回存档快照）"""
    scope = _get_scope(request)
    try:
        if 0 <= index < len(scope.edit_pdf_history):
            rec = scope.edit_pdf_history[index]
            pdf_path = await _resolve_edit_pdf_record_pdf(scope, rec)
            if pdf_path and Path(pdf_path).exists():
                return FileResponse(path=pdf_path, media_type="application/pdf", headers={"Content-Disposition": "inline"})
        raise HTTPException(status_code=404, detail="文件不存在")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"预览失败: {str(e)}")


@router.get("/api/edit-pdf/history-download/{index}")
# xuechong 2026-07-18 下载编辑PDF操作记录中的文件
# zhaoqiaotong 2026-09-10 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化
# 与预览同策略：任务存活→统一构建最新版；任务已清理→存档快照终版
async def download_edit_pdf_history(index: int, request: Request):
    """下载编辑PDF操作记录中的文件"""
    from urllib.parse import quote
    scope = _get_scope(request)
    try:
        if 0 <= index < len(scope.edit_pdf_history):
            record = scope.edit_pdf_history[index]
            pdf_path = await _resolve_edit_pdf_record_pdf(scope, record)
            filename = record.get("filename", "output.pdf")
            if pdf_path and Path(pdf_path).exists():
                # 更新下载次数
                record["download_count"] = record.get("download_count", 0) + 1
                scope.save_edit_pdf_history()
                encoded_filename = quote(filename, safe='')
                log_info(f"[编辑PDF] 下载历史文件: index={index}, 文件名={filename}, pdf_path={pdf_path}")
                return FileResponse(
                    path=pdf_path,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="output.pdf"; filename*=UTF-8\'\'{encoded_filename}'}
                )
            log_info(f"[编辑PDF] 下载文件不存在: index={index}, pdf_path={pdf_path}")
        raise HTTPException(status_code=404, detail="文件不存在")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_info(f"[编辑PDF] 下载历史文件失败: index={index}, 错误: {e}")
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


# 保留旧的单文件上传API（兼容）
@router.post("/api/edit-pdf/upload")
# xuechong 2026-07-21 研发BUG-0009-图档扫描-用户隔离机制问题 修复缺少 request 参数导致无法获取用户 scope
async def upload_edit_pdf(request: Request, file: UploadFile = File(...)):
    """上传单个PDF文件用于编辑（兼容旧接口）"""
    # 重用多文件上传接口（传递 request 以支持用户隔离）
    return await upload_edit_pdf_multiple(request, [file])
