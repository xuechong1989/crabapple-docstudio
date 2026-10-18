# -*- coding: utf-8 -*-
"""
双层PDF转换模块（PaddleOCR 引擎实现）
使用 PaddleOCR 对扫描版 PDF 进行 OCR 识别，生成可搜索的双层 PDF

功能特点：
1. 保留原PDF的DPI和图像质量
2. 自动检测并矫正90度旋转的页面
3. 支持 GPU 加速

注意：默认使用 RapidOCR 引擎（ocr_rapid.py），本模块作为备选引擎保留。
"""

import os
import sys

# PaddlePaddle 环境变量（必须在导入 paddle 之前设置）
os.environ.setdefault('FLAGS_use_mkldnn', '0')
os.environ.setdefault('FLAGS_pir_apply_shape_optimization_pass', '0')
os.environ.setdefault('FLAGS_enable_pir_api', '0')
os.environ.setdefault('FLAGS_enable_pir_in_executor', '0')
os.environ.setdefault('FLAGS_enable_pir_with_pt_in_dy2st', '0')
os.environ.setdefault('FLAGS_pir_apply_inplace_pass', '0')

from pathlib import Path
from typing import Optional, List, Tuple
import math

import cv2
import numpy as np

# PDF处理
import fitz  # PyMuPDF

# 导入配置（包内用相对导入，独立运行时回退到 url.conf 解析）
try:
    from . import config as cfg
except ImportError:
    from pathlib import Path as _FallbackPath
    _fb_root = _FallbackPath(__file__).parent.parent
    _fb_url_conf = {}
    _fb_conf_path = _fb_root / "url.conf"
    if _fb_conf_path.exists():
        for _fb_line in _fb_conf_path.read_text(encoding="utf-8").splitlines():
            _fb_line = _fb_line.strip()
            if not _fb_line or _fb_line.startswith("#") or "=" not in _fb_line:
                continue
            _fb_k, _fb_v = _fb_line.split("=", 1)
            _fb_k, _fb_v = _fb_k.strip(), _fb_v.strip()
            for _fb_ref in _fb_url_conf:
                _fb_v = _fb_v.replace(f"${{{_fb_ref}}}", _fb_url_conf[_fb_ref])
            _fb_url_conf[_fb_k] = _fb_v
    _fb_data_str = _fb_url_conf.get("DOCSTUDIO_BASE_DIR", "/data/crabapple-docstudio")
    _fb_data = _FallbackPath(_fb_data_str)
    class cfg:
        DATA_DIR = _fb_data
        TMP_DIR = _FallbackPath(_fb_url_conf.get("TMPDIR", str(_fb_data / "tmp")))
        OCR_FORCE_SKIP_ORIENTATION = True
        OCR_FIX_72DPI_PDF = True
        OCR_DEFAULT_DPI = 300
        OCR_DET_LIMIT_SIDE_LEN = 800
        OCR_REC_BATCH_NUM = 6
        OCR_ORIENTATION_MAX_DIM = 960
        OCR_MAX_IMAGE_DIM = 4096
        OCR_PRESCALE_ENABLED = False
        OCR_TILE_THRESHOLD = 9999
        OCR_TILE_SIZE = 1000
        OCR_TILE_OVERLAP = 50
        OCR_MAX_PARALLEL_PAGES = 0


# PaddleOCR 实例缓存（带线程锁保护）
_ocr_engines = {}
_ocr_engines_lock = __import__('threading').Lock()

def log(msg):
    """带时间戳的日志输出，同时写入调试文件（格式：年-月-日 时:分:秒.毫秒）"""
    import sys
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    try:
        if sys.stdout.isatty():
            from backend.services.logging_service import DEBUG_LOG_FILE as _dlf
            with open(_dlf, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        sys.stderr.write(f"[日志写入失败] {e}\n")

def release_ocr_engine(engine_key: str = None):
    """
    释放OCR引擎内存

    Args:
        engine_key: 要释放的引擎key，如 "ch_ori", "ch_no_ori"
                   如果为None，释放所有引擎
    """
    global _ocr_engines
    import gc

    with _ocr_engines_lock:
        if engine_key:
            if engine_key in _ocr_engines:
                del _ocr_engines[engine_key]
                log(f"  [OCR] Released engine: {engine_key}")
        else:
            _ocr_engines.clear()
            log(f"  [OCR] Released all engines")

    gc.collect()

from .config import _is_truthy_env as _is_truthy


def get_paddle_device():
    """
    获取 PaddleOCR 运行设备（自动检测GPU，优先使用CUDA）
    
    Returns:
        tuple: (device_str, use_gpu, reason)
    """
    device_override = os.environ.get("DOCSTUDIO_OCR_DEVICE", "")
    use_gpu_env = os.environ.get("DOCSTUDIO_USE_GPU", "1")
    use_gpu = _is_truthy(use_gpu_env)
    
    # 环境变量强制指定设备
    if device_override:
        if device_override.lower() == "cpu":
            return "cpu", False, "forced cpu by env"
        return device_override, True, "forced device by env"
    
    # 环境变量禁用GPU
    if not use_gpu:
        return "cpu", False, "gpu disabled by env"
    
    # 自动检测GPU
    gpu_available = False
    gpu_info = "unknown"
    
    # 方法1：检查PaddlePaddle的CUDA支持
    try:
        import paddle
        if paddle.is_compiled_with_cuda():
            gpu_count = paddle.device.cuda.device_count()
            if gpu_count > 0:
                gpu_available = True
                gpu_info = f"PaddlePaddle CUDA, {gpu_count} GPU(s)"
                log(f"  [GPU] 检测到 {gpu_count} 个NVIDIA GPU (PaddlePaddle CUDA)")
    except Exception as e:
        log(f"  [GPU] PaddlePaddle CUDA检测失败: {e}")
    
    # 方法2：如果方法1失败，尝试直接检查CUDA
    if not gpu_available:
        try:
            import subprocess
            result = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], 
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                gpu_names = result.stdout.strip().split('\n')
                log(f"  [GPU] nvidia-smi 检测到GPU: {gpu_names}")
                # 虽然检测到GPU，但PaddlePaddle可能不支持，返回警告
                gpu_info = f"nvidia-smi found {len(gpu_names)} GPU(s), but PaddlePaddle may not support CUDA"
                log(f"  [GPU] ⚠ 检测到GPU但 PaddlePaddle 未编译CUDA支持，请安装: pip install paddlepaddle-gpu")
        except Exception as e:
            log(f"[CUDA检测] nvidia-smi执行异常: {e}")
    
    if gpu_available:
        return "gpu:0", True, gpu_info
    else:
        return "cpu", False, f"cuda unavailable ({gpu_info})"

def get_paddleocr_version():
    """获取 PaddleOCR 版本号"""
    try:
        import paddleocr
        return paddleocr.__version__
    except Exception as e:
        log(f"[版本检测] 获取PaddleOCR版本失败: {e}")
        return "unknown"


def get_ocr_engine(ocr_lang: str = "ch", with_orientation: bool = True):
    """
    获取或初始化 PaddleOCR 实例
    
    Args:
        ocr_lang: 语言
        with_orientation: 是否启用方向检测
            - True: 用于检测页面方向
            - False: 用于最终 OCR（页面已旋转正确后使用）
    """
    global _ocr_engines

    # 语言映射
    lang_map = {
        "ch": "ch",
        "en": "en",
        "chinese_cht": "chinese_cht",
        "japan": "japan",
        "korean": "korean",
    }
    lang = lang_map.get(ocr_lang, "ch")

    # 根据是否启用方向检测使用不同的 key
    engine_key = f"{lang}_ori" if with_orientation else f"{lang}_no_ori"

    # 快速路径：无需锁（已缓存则直接返回）
    if engine_key in _ocr_engines:
        return _ocr_engines[engine_key]

    with _ocr_engines_lock:
        # 双重检查：其他线程可能已初始化
        if engine_key in _ocr_engines:
            return _ocr_engines[engine_key]
        version = get_paddleocr_version()
        ori_status = "with" if with_orientation else "without"
        log(f"  [Dual-Layer PDF] Loading PaddleOCR {version} model (lang={lang}, {ori_status} orientation)...")
        try:
            from paddleocr import PaddleOCR
            device, use_gpu, reason = get_paddle_device()
            
            # 明显标记GPU状态
            if use_gpu:
                log(f"  [Dual-Layer PDF] ★★★ GPU加速已启用 ★★★")
                log(f"  [Dual-Layer PDF] OCR device: {device} ({reason})")
            else:
                log(f"  [Dual-Layer PDF] OCR device: {device} ({reason})")
                log(f"  [Dual-Layer PDF] 提示: 安装GPU版PaddlePaddle可获得10倍以上加速")
            
            # 检查版本，使用不同的初始化参数
            major_version = int(version.split('.')[0]) if version != "unknown" else 2
            
            # 从配置获取性能参数
            det_limit = getattr(cfg, 'OCR_DET_LIMIT_SIDE_LEN', 960)
            rec_batch = getattr(cfg, 'OCR_REC_BATCH_NUM', 6)
            cpu_threads = getattr(cfg, 'OCR_CPU_THREADS', 0)
            
            # 自动检测CPU核心数
            if cpu_threads <= 0:
                import multiprocessing
                cpu_threads = multiprocessing.cpu_count()
            
            log(f"  [Dual-Layer PDF] CPU threads: {cpu_threads}")
            
            if major_version >= 3:
                # PaddleOCR 3.x 新 API
                kwargs = {
                    "lang": lang,
                    "use_doc_orientation_classify": with_orientation,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": with_orientation,
                    "device": device,
                    "enable_mkldnn": False,  # 禁用 MKL-DNN 避免 CPU 兼容性问题
                    # 性能优化参数
                    "det_limit_side_len": det_limit,
                    "rec_batch_num": rec_batch,
                }
                try:
                    _ocr_engines[engine_key] = PaddleOCR(**kwargs)
                except TypeError:
                    # 某些参数可能不支持，逐步移除
                    kwargs.pop("device", None)
                    kwargs.pop("enable_mkldnn", None)
                    kwargs.pop("det_limit_side_len", None)
                    kwargs.pop("rec_batch_num", None)
                    kwargs["use_gpu"] = use_gpu
                    _ocr_engines[engine_key] = PaddleOCR(**kwargs)
            else:
                # PaddleOCR 2.x 旧 API
                common_kwargs = {
                    "lang": lang,
                    "use_gpu": use_gpu,
                    "enable_mkldnn": False,
                    "det_limit_side_len": det_limit,
                    "rec_batch_num": rec_batch,
                    "cpu_threads": cpu_threads,
                    "use_space_char": True,
                }
                if with_orientation:
                    common_kwargs["use_angle_cls"] = True
                    common_kwargs["cls"] = True
                else:
                    common_kwargs["use_angle_cls"] = False
                    common_kwargs["cls"] = False
                
                _ocr_engines[engine_key] = PaddleOCR(**common_kwargs)
            
            log(f"  [Dual-Layer PDF] PaddleOCR model loaded (det_limit={det_limit}, rec_batch={rec_batch}, threads={cpu_threads})")
        except Exception as e:
            log(f"  [Dual-Layer PDF] PaddleOCR load failed: {e}")
            return None
    return _ocr_engines[engine_key]



def get_system_font_path() -> Optional[str]:
    """获取系统中文字体路径"""
    if sys.platform == 'win32':
        font_paths = [
            r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
            r"C:\Windows\Fonts\simsun.ttc",    # 宋体
            r"C:\Windows\Fonts\simhei.ttf",    # 黑体
        ]
    else:
        font_paths = [
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/System/Library/Fonts/PingFang.ttc",
        ]
    
    for path in font_paths:
        if os.path.exists(path):
            return path
    return None


def parse_ocr_result_with_rotation(ocr_result):
    """
    解析OCR结果（兼容PaddleOCR新旧版本），同时提取旋转角度
    
    Returns:
        tuple: (parsed_results, detected_angle)
            - parsed_results: [(bbox, text, confidence), ...]
            - detected_angle: PaddleOCR 检测到的文档旋转角度 (0, 90, 180, 270)
    """
    parsed_results = []
    detected_angle = 0
    
    if not ocr_result:
        return parsed_results, detected_angle
    
    if isinstance(ocr_result, list) and len(ocr_result) > 0:
        first_item = ocr_result[0]
        
        # 新版 PaddleOCR (>=3.x) 返回 OCRResult 对象
        if hasattr(first_item, 'get') and hasattr(first_item, 'keys'):
            rec_texts = first_item.get('rec_texts', [])
            rec_scores = first_item.get('rec_scores', [])
            dt_polys = first_item.get('dt_polys', [])
            
            # 提取文档预处理结果中的旋转角度
            doc_preprocessor_res = first_item.get('doc_preprocessor_res', {})
            if isinstance(doc_preprocessor_res, dict):
                detected_angle = doc_preprocessor_res.get('angle', 0)
            
            for i, text in enumerate(rec_texts):
                if i < len(dt_polys) and i < len(rec_scores):
                    bbox = dt_polys[i]
                    conf = rec_scores[i]
                    parsed_results.append((bbox, text, conf))
                    
        elif isinstance(first_item, list):
            # 旧版PaddleOCR格式
            items = ocr_result[0] if ocr_result[0] and isinstance(ocr_result[0][0], list) else ocr_result
            for item in items:
                if isinstance(item, list) and len(item) >= 2:
                    bbox = item[0]
                    text = item[1][0] if isinstance(item[1], tuple) else item[1]
                    conf = item[1][1] if isinstance(item[1], tuple) and len(item[1]) > 1 else 1.0
                    parsed_results.append((bbox, text, conf))
    
    return parsed_results, detected_angle


def parse_ocr_result(ocr_result):
    """
    解析OCR结果（兼容PaddleOCR新旧版本）
    
    Returns:
        list: [(bbox, text, confidence), ...]
    """
    results, _ = parse_ocr_result_with_rotation(ocr_result)
    return results


def detect_page_rotation(ocr_results: List[Tuple]) -> int:
    """
    检测页面文字的主要方向，判断是否需要旋转
    
    通过分析每个文本框的方向来判断页面整体方向
    
    Args:
        ocr_results: OCR识别结果 [(bbox, text, confidence), ...]
    
    Returns:
        int: 需要旋转的角度（0, 90, 180, 270）
    """
    if not ocr_results:
        return 0
    
    # 统计各方向的文本框数量
    direction_counts = {0: 0, 90: 0, 180: 0, 270: 0}
    
    for bbox, text, confidence in ocr_results:
        if confidence < 0.5 or len(text.strip()) < 2:
            continue
        
        try:
            bbox_arr = np.array(bbox)
            if bbox_arr.ndim != 2 or bbox_arr.shape[0] < 4:
                continue
            
            # 计算文本框的宽度和高度
            # bbox格式: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            # 通常是顺时针或逆时针的四个角点
            
            # 计算边长
            width1 = np.linalg.norm(bbox_arr[1] - bbox_arr[0])  # 上边
            width2 = np.linalg.norm(bbox_arr[2] - bbox_arr[3])  # 下边
            height1 = np.linalg.norm(bbox_arr[3] - bbox_arr[0])  # 左边
            height2 = np.linalg.norm(bbox_arr[2] - bbox_arr[1])  # 右边
            
            avg_width = (width1 + width2) / 2
            avg_height = (height1 + height2) / 2
            
            # 计算文本框的倾斜角度
            dx = bbox_arr[1][0] - bbox_arr[0][0]
            dy = bbox_arr[1][1] - bbox_arr[0][1]
            angle = math.degrees(math.atan2(dy, dx))
            
            # 将角度归一化到0-360
            angle = (angle + 360) % 360
            
            # 判断主要方向
            # 正常水平文字: 角度接近0或360
            # 90度旋转: 角度接近90
            # 180度旋转: 角度接近180
            # 270度旋转: 角度接近270
            
            if avg_width > avg_height * 1.5:
                # 横向文本框
                if -30 < angle < 30 or 330 < angle < 390:
                    direction_counts[0] += 1
                elif 60 < angle < 120:
                    direction_counts[90] += 1
                elif 150 < angle < 210:
                    direction_counts[180] += 1
                elif 240 < angle < 300:
                    direction_counts[270] += 1
            else:
                # 纵向文本框（单字或竖排文字）
                if 60 < angle < 120:
                    direction_counts[90] += 1
                elif 240 < angle < 300:
                    direction_counts[270] += 1
                    
        except Exception as e:
            log(f"[方向检测] 处理文本框方向异常: {e}")
            continue
    
    # 找出最多的方向
    total = sum(direction_counts.values())
    if total == 0:
        return 0
    
    max_direction = max(direction_counts, key=direction_counts.get)
    max_count = direction_counts[max_direction]
    
    # 如果主方向占比超过60%，则认为需要旋转
    if max_count / total > 0.6 and max_direction != 0:
        log(f"    Page rotation detected: {max_direction} degrees ({max_count}/{total} = {max_count/total*100:.1f}%)")
        return max_direction
    
    return 0


def rotate_page(page: fitz.Page, angle: int) -> fitz.Page:
    """
    旋转PDF页面
    
    Args:
        page: PDF页面对象
        angle: 旋转角度（90, 180, 270）
    
    Returns:
        旋转后的页面
    """
    if angle == 0:
        return page
    
    # 设置页面旋转
    page.set_rotation(angle)
    return page


def get_image_rect_in_page(page, doc=None):
    """
    获取图像在页面上的实际位置（矩形区域）
    
    返回: (rect, xref, pixel_width, pixel_height) 或 (None, None, 0, 0)
    """
    # 使用 get_image_info() 获取图像的精确位置
    image_infos = page.get_image_info()
    
    if image_infos:
        img_info = image_infos[0]  # 取第一个图像
        bbox = img_info.get('bbox')
        pixel_w = img_info.get('width', 0)
        pixel_h = img_info.get('height', 0)
        
        if bbox:
            rect = fitz.Rect(bbox)
            # 尝试获取 xref
            xref = img_info.get('xref')
            if not xref:
                # 如果 get_image_info 没有 xref，从 get_images 获取
                image_list = page.get_images(full=True)
                if image_list:
                    xref = image_list[0][0]
            return rect, xref, pixel_w, pixel_h
    
    # 备选方案：使用 get_images
    image_list = page.get_images(full=True)
    if image_list:
        xref = image_list[0][0]
        if doc:
            base_image = doc.extract_image(xref)
            pixel_w = base_image.get('width', 0)
            pixel_h = base_image.get('height', 0)
        else:
            pixel_w, pixel_h = 0, 0
        return page.rect, xref, pixel_w, pixel_h
    
    return None, None, 0, 0


def correct_pdf_orientation(
    input_path: str,
    output_path: str,
    ocr_lang: str = "ch",
    progress_callback: callable = None
) -> bool:
    """
    第一步：检测并矫正 PDF 页面方向，保存为新的扫描版 PDF
    
    关键：保持原始页面尺寸和图像位置不变！
    
    Args:
        progress_callback: 进度回调函数，签名为 callback(current_page, total_pages)
    """
    import time
    from PIL import Image
    import io

    src_doc = None
    output_doc = None
    try:
        log("=== 开始矫正页面方向 ===")
        input_path = Path(input_path)
        output_path = Path(output_path)

        if not input_path.exists():
            log(f"错误: 文件不存在 {input_path}")
            return False

        log("检查 PaddleOCR 版本...")
        version = get_paddleocr_version()
        log(f"PaddleOCR 版本: {version}")
        is_paddleocr_v3 = version != "unknown" and int(version.split('.')[0]) >= 3
        
        if not is_paddleocr_v3:
            import shutil
            shutil.copy(str(input_path), str(output_path))
            log("PaddleOCR < 3.x，跳过方向矫正")
            return True
        
        log("加载 OCR 引擎（带方向检测）...")
        ocr = get_ocr_engine(ocr_lang, with_orientation=True)
        if ocr is None:
            log("错误: OCR 引擎加载失败")
            return False
        log("OCR 引擎加载完成")
        
        log(f"打开 PDF: {input_path.name}")
        src_doc = fitz.open(str(input_path))
        total_pages = len(src_doc)
        log(f"总页数: {total_pages}")
        
        # 创建新的空白 PDF
        log("创建输出文档...")
        output_doc = fitz.open()
        
        def detect_angle(ocr_engine, image):
            """用缩略图检测方向（方向检测不需要高精度，缩放后速度更快）"""
            h, w = image.shape[:2]
            log(f"    - 原始图像尺寸: {w}x{h}")
            
            # 方向检测使用缩略图即可，大幅提升速度（从配置读取）
            max_dim = getattr(cfg, 'OCR_ORIENTATION_MAX_DIM', 1500)
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                new_w = int(w * scale)
                new_h = int(h * scale)
                small_image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
                log(f"    - 缩放后尺寸: {new_w}x{new_h} (用于方向检测)")
            else:
                small_image = image
                log(f"    - 图像尺寸较小，无需缩放")
            
            log("    - 调用 OCR 检测方向...")
            result = ocr_engine.ocr(small_image)
            log("    - OCR 调用完成")
            if result and len(result) > 0:
                first_item = result[0]
                if hasattr(first_item, 'get'):
                    doc_res = first_item.get('doc_preprocessor_res', {})
                    if isinstance(doc_res, dict):
                        angle = doc_res.get('angle', 0) or 0
                        log(f"    - 检测到角度: {angle}°")
                        return angle
            log("    - 未检测到角度，返回 0")
            return 0
        
        rotated_pages = 0
        start_time = time.time()
        
        for page_num in range(total_pages):
            # 报告进度
            if progress_callback:
                try:
                    progress_callback(page_num + 1, total_pages)
                except Exception as e:
                    log(f"[进度回调] 旋转处理进度回调异常: {e}")

            
            log(f"处理第 {page_num + 1}/{total_pages} 页...")
            src_page = src_doc[page_num]
            
            # 获取原始页面尺寸
            orig_page_width = src_page.rect.width
            orig_page_height = src_page.rect.height
            log(f"  原始页面尺寸: {orig_page_width:.1f} x {orig_page_height:.1f} pt")
            
            # 获取图像在页面上的精确位置
            img_rect, xref, pixel_w, pixel_h = get_image_rect_in_page(src_page, src_doc)
            
            if xref:
                # 提取原始图像
                base_image = src_doc.extract_image(xref)
                image_bytes = base_image["image"]
                img_width = base_image["width"]
                img_height = base_image["height"]
                
                log(f"  图像像素尺寸: {img_width} x {img_height}")
                log(f"  图像显示区域: ({img_rect.x0:.1f}, {img_rect.y0:.1f}) - ({img_rect.x1:.1f}, {img_rect.y1:.1f})")
                log(f"  图像显示尺寸: {img_rect.width:.1f} x {img_rect.height:.1f} pt")
                
                # 将原始图像转为 PIL Image
                pil_image = Image.open(io.BytesIO(image_bytes))
                
                # 转为 OpenCV 格式用于方向检测
                image_cv = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            else:
                # 没有嵌入图像，用页面渲染
                log("  没有嵌入图像，渲染页面")
                pix = src_page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x 缩放
                img_data = pix.tobytes("png")
                pil_image = Image.open(io.BytesIO(img_data))
                image_cv = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
                img_rect = src_page.rect
            
            # 检测方向
            log("  检测方向...")
            detected_angle = detect_angle(ocr, image_cv)
            
            # 计算新页面尺寸（如果旋转 90/270 度，宽高互换）
            if detected_angle in [90, 270]:
                new_page_width = orig_page_height
                new_page_height = orig_page_width
            else:
                new_page_width = orig_page_width
                new_page_height = orig_page_height
            
            # 创建新页面
            new_page = output_doc.new_page(width=new_page_width, height=new_page_height)
            
            # 如果需要旋转，物理旋转图像
            if detected_angle != 0:
                log(f"  物理旋转图像 {detected_angle}°...")
                
                if detected_angle == 90:
                    pil_image = pil_image.transpose(Image.Transpose.ROTATE_90)
                elif detected_angle == 180:
                    pil_image = pil_image.transpose(Image.Transpose.ROTATE_180)
                elif detected_angle == 270:
                    pil_image = pil_image.transpose(Image.Transpose.ROTATE_270)
                
                rotated_pages += 1
                log(f"  旋转后尺寸: {pil_image.width}x{pil_image.height}")
            else:
                log("  方向正确，无需旋转")
            
            # 保存图像
            img_bytes = io.BytesIO()
            if pil_image.mode == 'RGBA':
                pil_image.save(img_bytes, format='PNG')
            else:
                pil_image.save(img_bytes, format='JPEG', quality=95)
            img_bytes.seek(0)
            
            # 计算图像在新页面上的位置
            if img_rect and detected_angle in [90, 270]:
                # 旋转后，图像位置也要相应变换
                # 原位置 (x0, y0, x1, y1) 在页面 (W, H) 上
                # 旋转 90° 后，页面变成 (H, W)
                # 新位置需要重新计算以保持相对位置
                if detected_angle == 90:
                    new_x0 = img_rect.y0
                    new_y0 = orig_page_width - img_rect.x1
                    new_x1 = img_rect.y1
                    new_y1 = orig_page_width - img_rect.x0
                else:  # 270
                    new_x0 = orig_page_height - img_rect.y1
                    new_y0 = img_rect.x0
                    new_x1 = orig_page_height - img_rect.y0
                    new_y1 = img_rect.x1
                new_img_rect = fitz.Rect(new_x0, new_y0, new_x1, new_y1)
            elif img_rect and detected_angle == 180:
                new_x0 = orig_page_width - img_rect.x1
                new_y0 = orig_page_height - img_rect.y1
                new_x1 = orig_page_width - img_rect.x0
                new_y1 = orig_page_height - img_rect.y0
                new_img_rect = fitz.Rect(new_x0, new_y0, new_x1, new_y1)
            else:
                new_img_rect = img_rect if img_rect else new_page.rect
            
            log(f"  新页面尺寸: {new_page_width:.1f} x {new_page_height:.1f} pt")
            log(f"  图像插入位置: ({new_img_rect.x0:.1f}, {new_img_rect.y0:.1f}) - ({new_img_rect.x1:.1f}, {new_img_rect.y1:.1f})")
            
            # 插入图像到指定位置
            new_page.insert_image(new_img_rect, stream=img_bytes.getvalue())
            
            # 释放内存
            del image_cv, pil_image, img_bytes
            import gc
            gc.collect()
            
            elapsed = time.time() - start_time
            avg_time = elapsed / (page_num + 1)
            remaining = avg_time * (total_pages - page_num - 1)
            log(f"  进度: {elapsed:.1f}秒已用, 预计还需: {remaining:.0f}秒")
        
        log("保存矫正后的 PDF...")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_doc.save(str(output_path), garbage=0, deflate=False)

        log(f"=== 矫正完成: {output_path.name}, 物理旋转了 {rotated_pages} 页 ===")
        return True

    except Exception as e:
        import traceback
        log(traceback.format_exc())
        log(f"错误: {e}")
        return False
    finally:
        # 确保 fitz 文档句柄释放，防止 fd 泄漏
        if output_doc is not None:
            output_doc.close()
        if src_doc is not None:
            src_doc.close()


def add_text_layer_to_pdf(
    input_path: str,
    output_path: str,
    ocr_lang: str = "ch",
    progress_callback: callable = None
) -> bool:
    """
    第二步：对已经矫正方向的 PDF 添加 OCR 文字层
    
    注意：输入的 PDF 应该是已经物理旋转过的，没有 rotation 属性
    
    性能优化措施：
    1. OCR引擎参数优化：det_limit_side_len 限制检测尺寸，rec_batch_num 批量识别
    2. 智能分块OCR：超大图像自动分块处理，降低内存占用
    3. 图像预缩放：超大图像在OCR前先缩放，大幅降低内存和处理时间
    4. 可配置参数：所有性能参数可通过 config.py 调整
    
    Args:
        progress_callback: 进度回调函数，签名为 callback(current_page, total_pages)
    
    TODO: 多页并行处理（OCR_MAX_PARALLEL_PAGES > 0 时启用）
    目前串行处理以确保稳定性，未来可实现并行处理提升多页PDF速度
    """
    import time
    import gc
    
    def get_memory_usage_mb():
        """获取当前进程内存使用量（MB）"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except Exception as e:
            log(f"[内存监控] 获取进程内存使用量失败: {e}")
            return 0
    
    src_doc = None
    output_doc = None
    try:
        log("=== 开始添加文字层 ===")
        input_path = Path(input_path)
        output_path = Path(output_path)

        if not input_path.exists():
            log(f"错误: 文件不存在 {input_path}")
            return False

        log("加载 OCR 引擎（不带方向检测）...")
        ocr = get_ocr_engine(ocr_lang, with_orientation=False)
        if ocr is None:
            log("错误: OCR 引擎加载失败")
            return False
        log("OCR 引擎加载完成")
        
        log(f"打开 PDF: {input_path.name}")
        src_doc = fitz.open(str(input_path))
        total_pages = len(src_doc)
        log(f"总页数: {total_pages}")
        
        def get_image_dpi_from_bytes(image_bytes):
            """从图像字节数据中读取DPI信息"""
            try:
                from PIL import Image
                import io
                pil_img = Image.open(io.BytesIO(image_bytes))
                dpi_info = pil_img.info.get('dpi')
                if dpi_info:
                    if isinstance(dpi_info, tuple):
                        return int(dpi_info[0])
                    return int(dpi_info)
            except Exception as e:
                log(f"[DPI读取] 从图像字节读取DPI失败: {e}")

            return None  # 无法读取DPI
        
        # 检查是否需要修正72DPI的PDF
        fix_72dpi = getattr(cfg, 'OCR_FIX_72DPI_PDF', False)
        
        log("创建输出文档...")
        output_doc = fitz.open()
        
        # 检测PDF是否为72DPI（页面点数≈像素数）
        need_resize = False
        image_dpi = None  # 原图的DPI
        
        if fix_72dpi and total_pages > 0:
            first_page = src_doc[0]
            first_rect, first_xref, first_pw, first_ph = get_image_rect_in_page(first_page, src_doc)
            if first_xref and first_pw and first_ph:
                # 计算当前PDF的DPI
                detected_dpi = first_pw / (first_rect.width / 72) if first_rect.width > 0 else 300
                
                # 尝试从嵌入图像中读取原始DPI
                try:
                    base_image = src_doc.extract_image(first_xref)
                    image_dpi = get_image_dpi_from_bytes(base_image["image"])
                    if image_dpi:
                        log(f"从原图读取到DPI: {image_dpi}")
                except Exception as e:
                    log(f"[DPI提取] 从嵌入图像提取DPI异常: {e}")

                
                if 70 <= detected_dpi <= 74:  # 接近72DPI，说明PDF尺寸不对
                    if image_dpi and image_dpi > 74:  # 原图DPI大于72
                        need_resize = True
                        log(f"检测到PDF为72DPI，将使用原图DPI({image_dpi})修正")
                    else:
                        # 无法读取原图DPI，使用配置中的默认DPI
                        default_dpi = getattr(cfg, 'OCR_DEFAULT_DPI', 300)
                        image_dpi = default_dpi
                        need_resize = True
                        log(f"PDF为72DPI，无法读取原图DPI，使用默认DPI({default_dpi})修正")
        
        if need_resize and image_dpi:
            # 需要重新创建页面（使用原图DPI修正）
            for page_num in range(total_pages):
                src_page = src_doc[page_num]
                img_rect, xref, pixel_w, pixel_h = get_image_rect_in_page(src_page, src_doc)
                
                if xref and pixel_w and pixel_h:
                    # 尝试读取当前页图像的DPI
                    page_image_dpi = image_dpi  # 默认使用第一页的DPI
                    try:
                        base_image = src_doc.extract_image(xref)
                        page_dpi = get_image_dpi_from_bytes(base_image["image"])
                        if page_dpi:
                            page_image_dpi = page_dpi
                    except Exception as e:
                        log(f"[DPI读取] 读取第{page_num+1}页图像DPI异常: {e}")
    
                    
                    # 计算正确的页面尺寸（使用原图DPI）
                    new_width = pixel_w * 72.0 / page_image_dpi
                    new_height = pixel_h * 72.0 / page_image_dpi
                    
                    log(f"  第{page_num+1}页: {pixel_w}x{pixel_h}px, DPI={page_image_dpi}, 页面={new_width:.1f}x{new_height:.1f}pt")
                    
                    # 创建新页面
                    new_page = output_doc.new_page(width=new_width, height=new_height)
                    
                    # 提取并插入原始图像（保持原始像素不变）
                    base_image = src_doc.extract_image(xref)
                    new_page.insert_image(new_page.rect, stream=base_image["image"])
                else:
                    # 无法获取图像信息，直接复制页面
                    output_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
            
            log(f"已使用原图DPI({image_dpi})修正PDF尺寸")
        else:
            # 不需要修正，直接复制
            output_doc.insert_pdf(src_doc)
        
        font_path = get_system_font_path()
        font = fitz.Font(fontfile=font_path) if font_path else fitz.Font("china-s")
        log(f"使用字体: {font_path or 'default'}")
        
        total_text_blocks = 0
        start_time = time.time()

        ocr_result = None
        ocr_results = None
        for page_num in range(total_pages):
            # 报告进度
            if progress_callback:
                try:
                    progress_callback(page_num + 1, total_pages)
                except Exception as e:
                    log(f"[进度回调] 文字层处理进度回调异常: {e}")

            
            log(f"处理第 {page_num + 1}/{total_pages} 页...")
            page = output_doc[page_num]
            
            # 获取页面尺寸
            page_width = page.rect.width
            page_height = page.rect.height
            log(f"  页面尺寸: {page_width:.1f} x {page_height:.1f} pt")
            
            # 获取图像在页面上的精确位置（page 属于 output_doc，必须传 output_doc）
            img_rect, xref, pixel_w, pixel_h = get_image_rect_in_page(page, output_doc)
            
            if xref:
                # 提取原始图像
                base_image = src_doc.extract_image(xref)
                image_bytes = base_image["image"]
                
                # 转为 OpenCV 格式
                nparr = np.frombuffer(image_bytes, np.uint8)
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                orig_h, orig_w = image.shape[:2]
                img_h, img_w = orig_h, orig_w
                log(f"  原始图像像素尺寸: {orig_w} x {orig_h} px")
                
                # 预缩放大图像（关键性能优化）
                prescale_enabled = getattr(cfg, 'OCR_PRESCALE_ENABLED', False)
                max_image_dim = getattr(cfg, 'OCR_MAX_IMAGE_DIM', 2500)
                prescale_factor = 1.0

                if prescale_enabled and max(orig_h, orig_w) > max_image_dim:
                    prescale_factor = max_image_dim / max(orig_h, orig_w)
                    new_w = int(orig_w * prescale_factor)
                    new_h = int(orig_h * prescale_factor)
                    log(f"  图像过大，预缩放: {orig_w}x{orig_h} -> {new_w}x{new_h} (factor={prescale_factor:.3f})")
                    image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    img_h, img_w = new_h, new_w
                
                # 使用 get_image_info 返回的精确显示区域
                img_display_width = img_rect.width
                img_display_height = img_rect.height
                img_offset_x = img_rect.x0
                img_offset_y = img_rect.y0
                
                log(f"  图像显示区域: ({img_rect.x0:.1f}, {img_rect.y0:.1f}) - ({img_rect.x1:.1f}, {img_rect.y1:.1f})")
                log(f"  图像显示尺寸: {img_display_width:.1f} x {img_display_height:.1f} pt")
                
                # 计算真实 DPI（使用原始尺寸）
                dpi_x = orig_w / (img_display_width / 72)
                dpi_y = orig_h / (img_display_height / 72)
                log(f"  真实 DPI: x={dpi_x:.1f}, y={dpi_y:.1f}")
            else:
                # 没有嵌入图像，用 1:1 比例渲染
                log("  没有嵌入图像，按页面尺寸渲染")
                pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
                img_data = pix.tobytes("png")
                nparr = np.frombuffer(img_data, np.uint8)
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                orig_h, orig_w = image.shape[:2]
                img_h, img_w = orig_h, orig_w
                log(f"  渲染图像尺寸: {orig_w} x {orig_h} px")
                
                # 预缩放大图像
                prescale_enabled = getattr(cfg, 'OCR_PRESCALE_ENABLED', False)
                max_image_dim = getattr(cfg, 'OCR_MAX_IMAGE_DIM', 2500)
                
                if prescale_enabled and max(orig_h, orig_w) > max_image_dim:
                    prescale_factor = max_image_dim / max(orig_h, orig_w)
                    new_w = int(orig_w * prescale_factor)
                    new_h = int(orig_h * prescale_factor)
                    log(f"  图像过大，预缩放: {orig_w}x{orig_h} -> {new_w}x{new_h}")
                    image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    img_h, img_w = new_h, new_w
                
                img_display_width = page_width
                img_display_height = page_height
                img_offset_x = 0
                img_offset_y = 0
            
            # 直接执行OCR（预缩放后图像已经足够小）
            log(f"  执行 OCR（图像尺寸: {img_w}x{img_h}）...")
            ocr_start = time.time()
            ocr_result = ocr.ocr(image)
            ocr_time = time.time() - ocr_start
            ocr_results, _ = parse_ocr_result_with_rotation(ocr_result)
            log(f"  OCR 完成，识别到 {len(ocr_results)} 个文本块，耗时: {ocr_time:.1f}秒")
            
            # 坐标转换：原图像素坐标 -> PDF 点坐标
            # 关键：使用图像在页面上的显示尺寸，而不是页面尺寸！
            scale_x = img_display_width / img_w
            scale_y = img_display_height / img_h
            log(f"  坐标缩放比例: x={scale_x:.6f}, y={scale_y:.6f}")
            log(f"  图像偏移: x={img_offset_x:.1f}, y={img_offset_y:.1f}")
            
            page_text_count = 0
            
            if ocr_results:
                tw = fitz.TextWriter(page.rect)
                for bbox, text, confidence in ocr_results:
                    if confidence < 0.3 or not text.strip():
                        continue
                    
                    try:
                        bbox_arr = np.array(bbox)
                        if bbox_arr.ndim == 2:
                            x_coords = bbox_arr[:, 0].tolist()
                            y_coords = bbox_arr[:, 1].tolist()
                        else:
                            x_coords = bbox_arr[0::2].tolist()
                            y_coords = bbox_arr[1::2].tolist()
                        
                        x_min, x_max = min(x_coords), max(x_coords)
                        y_min, y_max = min(y_coords), max(y_coords)
                    except Exception as e:
                        log(f"[坐标处理] 解析OCR文本框坐标异常: {e}")
                        continue
                    
                    # 缩放坐标并加上图像偏移
                    pdf_x1 = x_min * scale_x + img_offset_x
                    pdf_y1 = y_min * scale_y + img_offset_y
                    pdf_x2 = x_max * scale_x + img_offset_x
                    pdf_y2 = y_max * scale_y + img_offset_y
                    
                    box_width = pdf_x2 - pdf_x1
                    box_height = pdf_y2 - pdf_y1
                    
                    if box_width <= 0 or box_height <= 0:
                        continue
                    
                    # 计算字体大小
                    chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
                    other_count = len(text) - chinese_count
                    char_width_factor = chinese_count + other_count * 0.55
                    
                    if char_width_factor > 0:
                        font_size = min(box_width / char_width_factor, box_height * 0.8)
                    else:
                        font_size = box_height * 0.8
                    font_size = max(4, min(72, font_size))
                    
                    try:
                        baseline_y = pdf_y2 - box_height * 0.1
                        tw.append(pos=(pdf_x1, baseline_y), text=text, font=font, fontsize=font_size)
                        page_text_count += 1
                        total_text_blocks += 1
                    except Exception as e:
                        log(f"[文字写入] 写入文字层到PDF失败(文本='{text[:20]}...'): {e}")
                        continue

            if page_text_count > 0:
                tw.write_text(page, color=(0, 0, 0), render_mode=3)

            # 释放当前页图像内存
            del image
            if ocr_result is not None:
                del ocr_result
            if ocr_results is not None:
                del ocr_results
            gc.collect()
            
            elapsed = time.time() - start_time
            avg_time = elapsed / (page_num + 1)
            remaining = avg_time * (total_pages - page_num - 1)
            mem_mb = get_memory_usage_mb()
            log(f"  添加了 {page_text_count} 个文本块, 用时: {elapsed:.1f}秒, 预计还需: {remaining:.0f}秒, 内存: {mem_mb:.0f}MB")
        
        log("保存双层 PDF...")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_doc.save(str(output_path), garbage=0, deflate=False, clean=False)
        output_doc.close()
        src_doc.close()
        
        log(f"=== 文字层添加完成: {output_path.name}, 共 {total_text_blocks} 个文本块 ===")
        return True

    except Exception as e:
        import traceback
        log(traceback.format_exc())
        log(f"错误: {e}")
        return False
    finally:
        if output_doc is not None:
            output_doc.close()
        if src_doc is not None:
            src_doc.close()


def convert_to_dual_layer_pdf(
    input_path: str,
    output_path: str,
    ocr_lang: str = "ch",
    auto_rotate: bool = True,
    progress_callback: callable = None
) -> bool:
    """
    将扫描版PDF转换为双层PDF（两步走流程）
    
    步骤1：检测方向并物理旋转图像，生成矫正后的扫描版PDF
    步骤2：对矫正后的PDF进行OCR，添加文字层，生成最终双层PDF
    
    特点：
    1. 物理旋转图像，不使用PDF旋转属性
    2. 保留原PDF的DPI和图像质量（不缩放图像）
    3. 文字层大小根据背景文字大小智能设置
    
    Args:
        input_path: 输入PDF文件路径
        output_path: 输出PDF文件路径
        ocr_lang: OCR语言 (ch, en, chinese_cht, japan, korean)
        auto_rotate: 是否自动检测并旋转页面
        progress_callback: 进度回调函数，签名为 callback(step, current_page, total_pages, percent)
            - step: "orientation" 或 "ocr"
            - current_page: 当前处理的页码（从1开始）
            - total_pages: 总页数
            - percent: 当前文件的整体进度百分比 (0-100)
    
    Returns:
        bool: 转换是否成功
    """
    import uuid as _uuid
    import time as time_module
    
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    conversion_start_time = time_module.time()
    log(f"=== 开始转换双层PDF: {input_path.name} ===")
    
    try:
        # 检查 PaddleOCR 版本
        version = get_paddleocr_version()
        is_paddleocr_v3 = version != "unknown" and int(version.split('.')[0]) >= 3
        
        # 检查是否强制跳过方向检测（配置优先）
        force_skip_orientation = getattr(cfg, 'OCR_FORCE_SKIP_ORIENTATION', False)
        if force_skip_orientation:
            log("配置已强制禁用方向检测，跳过步骤1")
        
        # 判断是否需要两步处理（方向检测+OCR）
        need_two_steps = auto_rotate and is_paddleocr_v3 and not force_skip_orientation
        
        if need_two_steps:
            # ============================================================
            # 步骤1：检测方向并物理旋转图像（占50%进度）
            # ============================================================
            log("【步骤1】检测方向并物理旋转图像...")

            # 创建临时文件存储矫正后的PDF（使用 url.conf 配置的临时目录）
            _tmp_base = str(cfg.TMP_DIR)
            os.makedirs(_tmp_base, exist_ok=True)
            temp_dir = os.path.join(_tmp_base, f"orient_{_uuid.uuid4().hex}")
            os.makedirs(temp_dir, exist_ok=True)
            corrected_pdf_path = Path(temp_dir) / "corrected.pdf"
            orientation_success = False

            try:
                # 步骤1进度回调（0-50%）
                def orientation_progress(current_page, page_total):
                    if progress_callback:
                        percent = int((current_page / page_total) * 50)
                        progress_callback("orientation", current_page, page_total, percent)

                orientation_success = correct_pdf_orientation(str(input_path), str(corrected_pdf_path), ocr_lang, orientation_progress)
                if not orientation_success:
                    log("错误: 方向矫正失败")
                    return False
            finally:
                if not orientation_success:
                    import shutil
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception as e:
                        log(f"临时目录清理失败（非致命）: {e}")
            
            # 释放方向检测引擎内存，为步骤2腾出空间
            lang_map = {"ch": "ch", "en": "en", "chinese_cht": "chinese_cht", "japan": "japan", "korean": "korean"}
            lang = lang_map.get(ocr_lang, "ch")
            release_ocr_engine(f"{lang}_ori")
            log("已释放方向检测引擎内存")
            
            # 使用矫正后的PDF作为下一步输入
            step2_input = str(corrected_pdf_path)
        else:
            # 不需要方向矫正，直接使用原PDF
            step2_input = str(input_path)
        
        # ============================================================
        # 步骤2：对矫正后的PDF添加OCR文字层
        # ============================================================
        log("【步骤2】添加OCR文字层...")
        
        # 步骤2进度回调
        if need_two_steps:
            # 两步处理时，步骤2占50-100%
            def ocr_progress(current_page, page_total):
                if progress_callback:
                    percent = 50 + int((current_page / page_total) * 50)
                    progress_callback("ocr", current_page, page_total, percent)
        else:
            # 单步处理时，步骤2占0-100%
            def ocr_progress(current_page, page_total):
                if progress_callback:
                    percent = int((current_page / page_total) * 100)
                    progress_callback("ocr", current_page, page_total, percent)
        
        success = add_text_layer_to_pdf(step2_input, str(output_path), ocr_lang, ocr_progress)
        
        # 清理临时文件
        if auto_rotate and is_paddleocr_v3:
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                log(f"[临时清理] 清理临时目录失败({temp_dir}): {e}")
        
        elapsed_time = time_module.time() - conversion_start_time
        if success:
            log(f"=== 转换完成: {output_path.name}，耗时: {elapsed_time:.1f}秒 ===")
        else:
            log(f"错误: 添加文字层失败，耗时: {elapsed_time:.1f}秒")
        
        return success
        
    except Exception as e:
        import traceback
        log(traceback.format_exc())
        elapsed_time = time_module.time() - conversion_start_time
        log(f"错误: {e}，耗时: {elapsed_time:.1f}秒")
        return False


def batch_convert_to_dual_layer_pdf(
    input_dir: str,
    output_dir: str,
    ocr_lang: str = "ch",
    keep_structure: bool = True,
    auto_rotate: bool = True
) -> Tuple[int, int]:
    """
    批量转换目录中的PDF文件
    
    Args:
        input_dir: 输入目录
        output_dir: 输出目录
        ocr_lang: OCR语言
        keep_structure: 是否保持目录结构
        auto_rotate: 是否自动检测并旋转页面
    
    Returns:
        Tuple[int, int]: (成功数, 失败数)
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    
    if not input_path.exists():
        log(f"  [Dual-Layer PDF] Input dir not exist: {input_dir}")
        return (0, 0)
    
    pdf_files = list(input_path.rglob("*.pdf"))
    
    if not pdf_files:
        log(f"  [Dual-Layer PDF] No PDF files found: {input_dir}")
        return (0, 0)
    
    success_count = 0
    failed_count = 0
    
    for pdf_file in pdf_files:
        if keep_structure:
            rel_path = pdf_file.relative_to(input_path)
            out_file = output_path / rel_path
        else:
            out_file = output_path / pdf_file.name
        
        try:
            if convert_to_dual_layer_pdf(str(pdf_file), str(out_file), ocr_lang, auto_rotate):
                success_count += 1
            else:
                failed_count += 1
        except Exception as e:
            log(f"[批量转换] 文件 {pdf_file.name} 转换异常: {e}")
            failed_count += 1
    
    return (success_count, failed_count)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python ocr_pdf.py <input_pdf> <output_pdf> [lang] [auto_rotate]")
        print("  lang: ch(Chinese), en(English), chinese_cht(Traditional), japan, korean")
        print("  auto_rotate: true/false (default: true)")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    lang = sys.argv[3] if len(sys.argv) > 3 else "ch"
    auto_rotate = sys.argv[4].lower() != 'false' if len(sys.argv) > 4 else True
    
    success = convert_to_dual_layer_pdf(input_file, output_file, lang, auto_rotate)
    sys.exit(0 if success else 1)
