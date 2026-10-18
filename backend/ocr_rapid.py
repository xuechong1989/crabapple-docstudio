# -*- coding: utf-8 -*-
"""
双层PDF转换模块 - RapidOCR版本
使用RapidOCR对扫描版PDF进行OCR识别，生成可搜索的双层PDF

功能特点：
1. 保留原PDF的DPI和图像质量
2. 使用RapidOCR 3.x（基于ONNX Runtime）
3. GPU 优先：安装 onnxruntime-gpu 后自动使用 CUDA 加速 OCR
4. 无 GPU 时自动回退到 CPU（onnxruntime）
5. 兼容PaddleOCR版本的API接口

依赖安装：
pip install rapidocr>=3.5.0
# GPU加速（可选，推荐）：
pip install onnxruntime-gpu   # 替换 onnxruntime，自动启用 CUDA

RapidOCR 3.x API变化说明：
- 包名从 rapidocr-onnxruntime 改为 rapidocr
- 导入方式: from rapidocr import RapidOCR
- 返回结果: RapidOCROutput 数据类，通过 result.boxes/txts/scores 访问
"""

import os
import sys
import threading
from pathlib import Path
from typing import List, Tuple

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
        CUDA_CACHE_DIR = _FallbackPath(_fb_url_conf.get("CUDA_CACHE_PATH", str(_fb_data / "cache" / "cuda")))
        OCR_FORCE_SKIP_ORIENTATION = True
        OCR_FIX_72DPI_PDF = True
        OCR_DEFAULT_DPI = 300
        OCR_DET_LIMIT_SIDE_LEN = 1920
        OCR_REC_BATCH_NUM = 8
        OCR_ORIENTATION_MAX_DIM = 960
        OCR_MAX_IMAGE_DIM = 4096  # 不预缩放时使用原图
        OCR_PRESCALE_ENABLED = False  # 禁用预缩放以获得更好识别率


# RapidOCR 实例缓存
_rapid_ocr_engines = {}
_engine_lock = __import__('threading').Lock()

# 字体缓存（避免重复创建）
_font_cache = {}
_font_lock = __import__('threading').Lock()

# 是否启用详细日志（性能模式下关闭）
_verbose_logging = False

# ONNX Runtime GPU 状态缓存
_ort_gpu_checked = False
_ort_gpu_available = False
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 运行级验证失败标志
# 当引擎创建/预热失败时置 True，detect_ort_gpu() 返回 False
_ort_gpu_runtime_failed = False


def log(msg: str, force: bool = False):
    """输出日志（性能模式下只输出重要信息），格式：年-月-日 时:分:秒.毫秒"""
    if _verbose_logging or force:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{timestamp}]   [RapidOCR] {msg}"
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def detect_ort_gpu() -> bool:
    """
    检测 ONNX Runtime 是否支持 GPU（三层验证）。
    GPU 优先原则：如果安装了 onnxruntime-gpu，自动使用 CUDA 加速。

    xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 三层验证：
    ① 包级：onnxruntime.get_device()=="GPU"
    ② 列表级：CUDAExecutionProvider in get_available_providers()
    ③ 运行级：在 _init_rapid_ocr_engine 中创建引擎+推理成功
    三层全部满足才认定 GPU。任一失败记录明确日志并回退 CPU 多线程。

    安全机制：如果 PyTorch CUDA 不可用，即使 onnxruntime 报告支持
    CUDAExecutionProvider 也不信任，因为实际初始化可能卡死。

    Returns:
        bool: True 表示 GPU 可用且安全（①+② 通过，③ 在引擎初始化时验证）
    """
    global _ort_gpu_checked, _ort_gpu_available
    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 运行级失败后强制返回 False
    if _ort_gpu_runtime_failed:
        _ort_gpu_available = False
        _ort_gpu_checked = True
        return False
    if _ort_gpu_checked:
        return _ort_gpu_available
    
    _ort_gpu_checked = True
    _ort_gpu_available = False
    
    # ★ 先用 PyTorch 验证 CUDA 是否真正可用 ★
    torch_cuda_ok = False
    try:
        import torch
        torch_cuda_ok = torch.cuda.is_available()
        if not torch_cuda_ok:
            log("PyTorch CUDA 不可用 (torch.cuda.is_available()=False)", force=True)
            log("→ onnxruntime GPU 也将被禁用（防止 CUDA 初始化卡死）", force=True)
    except ImportError:
        log("PyTorch 未安装，无法验证 CUDA", force=True)
    except Exception as e:
        log(f"PyTorch CUDA 检测异常: {e}", force=True)
    
    try:
        import onnxruntime as ort
        ort_ver = ort.__version__
        providers = ort.get_available_providers()

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 三层验证 ①包级
        ort_device = ort.get_device()
        log(f"ONNX Runtime {ort_ver}, device={ort_device}, providers: {providers}", force=True)

        if ort_device != "GPU":
            log("✗ onnxruntime.get_device() != GPU（包级验证失败）", force=True)
            log("  → 可能安装了 onnxruntime（CPU 包）而非 onnxruntime-gpu", force=True)
            return _ort_gpu_available

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 三层验证 ②列表级
        if 'CUDAExecutionProvider' in providers:
            if torch_cuda_ok:
                # ★ 关键检查：onnxruntime-gpu 版本是否匹配 CUDA 12.x ★
                cuda_ver_ok = True
                try:
                    ver_parts = [int(x) for x in ort_ver.split('.')[:2]]
                    if ver_parts[0] < 1 or (ver_parts[0] == 1 and ver_parts[1] < 19):
                        log(f"⚠⚠⚠ onnxruntime-gpu {ort_ver} 是 CUDA 11 编译版本！", force=True)
                        log(f"⚠ 当前 PyTorch 使用 CUDA 12.x，但 onnxruntime-gpu < 1.19 需要 CUDA 11", force=True)
                        log(f"⚠ 会导致 'libcublasLt.so.11 not found' 错误，CUDA 加速无效", force=True)
                        log(f"⚠ 解决：安装 onnxruntime-gpu >= 1.19.0（pip install onnxruntime-gpu>=1.19.0）", force=True)
                        log(f"⚠ 当前使用 CPU 模式，避免 CUDA 库版本不匹配导致失败", force=True)
                        cuda_ver_ok = False
                except (ValueError, IndexError) as e:
                    log(f"⚠ onnxruntime 版本解析失败: {e}，跳过 CUDA 兼容性检查", force=True)
                
                if cuda_ver_ok:
                    _ort_gpu_available = True
                    log("★★★ ONNX Runtime GPU (CUDA) 加速已启用 ★★★", force=True)
                    try:
                        import torch
                        gpu_name = torch.cuda.get_device_name(0)
                        log(f"OCR GPU 设备: {gpu_name}", force=True)
                    except Exception as e:
                        log(f"[GPU设备名称获取失败] {e}")
                else:
                    _ort_gpu_available = False
            else:
                # PyTorch CUDA 不可用 → 不信任 onnxruntime CUDA（可能卡死）
                _ort_gpu_available = False
                log("⚠️ onnxruntime 报告支持 CUDA，但 PyTorch CUDA 不可用", force=True)
                log("⚠️ 需排查 CUDA 环境（GPU强制策略下不允许忽略GPU）", force=True)
        else:
            log("ONNX Runtime 仅支持 CPU（安装 onnxruntime-gpu >= 1.19.0 可启用 GPU 加速）", force=True)
    except ImportError:
        log("ONNX Runtime 未安装", force=True)
    except Exception as e:
        log(f"ONNX Runtime 检测异常: {e}", force=True)
    
    return _ort_gpu_available


def set_verbose_logging(enabled: bool):
    """设置是否启用详细日志"""
    global _verbose_logging
    _verbose_logging = enabled


def get_cached_font(font_name: str = "china-s"):
    """获取缓存的字体对象（避免重复创建）"""
    with _font_lock:
        if font_name not in _font_cache:
            _font_cache[font_name] = fitz.Font(font_name)
        return _font_cache[font_name]


def get_image_dpi_from_bytes(image_bytes) -> int:
    """
    从图像字节数据中读取DPI信息
    
    Args:
        image_bytes: 图像的字节数据
    
    Returns:
        int: DPI值，如果无法读取返回None
    """
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
        log(f"[图像DPI读取失败] {e}")
    return None  # 无法读取DPI


def get_rapidocr_version():
    """获取 RapidOCR 版本号"""
    try:
        # RapidOCR 3.x 使用 importlib.metadata 获取版本
        from importlib.metadata import version
        return version('rapidocr')
    except Exception as e:
        log(f"[RapidOCR版本检测-importlib] {e}")
    
    try:
        # 备用方案：使用 pkg_resources
        import pkg_resources
        return pkg_resources.get_distribution('rapidocr').version
    except Exception as e:
        log(f"[RapidOCR版本检测-pkg_resources] {e}")
    
    try:
        # 尝试旧版包名（兼容性）
        import rapidocr_onnxruntime
        return getattr(rapidocr_onnxruntime, '__version__', 'unknown (legacy)')
    except Exception as e:
        log(f"[RapidOCR版本检测-旧版包名] {e}")
    
    return "not installed"


def _setup_cuda_jit_cache():
    """确保 CUDA JIT 编译缓存目录存在（环境变量已由 config.py 设置）"""
    cache_dir = str(cfg.CUDA_CACHE_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    log(f"  [CUDA缓存] JIT 编译缓存目录: {cache_dir}", force=True)


def get_rapid_ocr_engine(ocr_lang: str = "ch", use_cls: bool = False, det_limit: int = None):
    """
    获取或初始化 RapidOCR 实例
    
    ★ GPU 强制使用策略 ★
    规则：只要检测到 GPU + CUDA 可用，就必须使用 GPU，不存在降级 CPU。
    首次启动可能因 CUDA JIT 编译需要等待数分钟，耐心等待即可，
    编译结果会缓存到工程外部目录，下次启动秒加载。
    
    仅在以下情况使用 CPU：
    - 机器没有 GPU
    - CUDA 驱动未安装
    - onnxruntime-gpu 未安装（缺少 CUDAExecutionProvider）
    
    Args:
        ocr_lang: 语言（RapidOCR默认支持中英文）
        use_cls: 是否启用方向分类器（禁用可提速20-30%，扫描文档通常不需要）
        det_limit: 检测时的最大边长（RapidOCR 3.x 需要在初始化时传入）
    """
    global _rapid_ocr_engines
    
    # 获取配置中的检测边长
    if det_limit is None:
        det_limit = getattr(cfg, 'OCR_DET_LIMIT_SIDE_LEN', 1280)
    
    # 使用配置作为 key 的一部分，确保不同配置使用不同引擎
    engine_key = f"{ocr_lang}_cls{use_cls}_det{det_limit}"

    with _engine_lock:
        if engine_key not in _rapid_ocr_engines:
            _rapid_ocr_engines[engine_key] = _init_rapid_ocr_engine(engine_key, ocr_lang, use_cls, det_limit)

    return _rapid_ocr_engines[engine_key]


def _init_rapid_ocr_engine(engine_key, ocr_lang, use_cls, det_limit):
    """初始化 RapidOCR 引擎（在 _engine_lock 保护下调用）"""
    version = get_rapidocr_version()

    # 检测 GPU 支持
    gpu_available = detect_ort_gpu()

    if gpu_available:
        # ============================================================
        # ★ GPU 模式（强制）：检测到 CUDA 就必须用 GPU ★
        # ============================================================
        log(f"Loading RapidOCR {version} (lang={ocr_lang}, cls={use_cls}, det_limit={det_limit}, device=GPU)...", force=True)
        log(f"  [OCR] ★ 检测到 GPU + CUDA，强制使用 GPU 模式 ★", force=True)

        # 设置 CUDA JIT 缓存到工程外部（跨版本持久化）
        _setup_cuda_jit_cache()

        try:
            from rapidocr import RapidOCR

            init_params = {
                "Global.log_level": "error",
                "Det.limit_side_len": det_limit,
                "Det.limit_type": "max",
                # ★ 启用 CUDA + HEURISTIC（比默认 EXHAUSTIVE 首次快得多）★
                "EngineConfig.onnxruntime.use_cuda": True,
                "EngineConfig.onnxruntime.cuda_ep_cfg.device_id": 0,
                "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC",
                "EngineConfig.onnxruntime.cuda_ep_cfg.do_copy_in_default_stream": True,
                # 限制 OCR 占用的 GPU 显存，避免与 YOLO 争抢
                "EngineConfig.onnxruntime.cuda_ep_cfg.gpu_mem_limit": 4 * 1024 * 1024 * 1024,
            }

            engine = RapidOCR(params=init_params)

            # ★ 预热推理（不设超时，等待完成）★
            # 首次 CUDA JIT 编译可能需要几分钟，这是正常现象
            log(f"  [OCR] GPU 预热推理开始...", force=True)
            log(f"  [OCR] （首次 CUDA JIT 编译可能需要 1-3 分钟，请耐心等待，编译结果会缓存到磁盘）", force=True)

            import time as _time
            t_start = _time.time()

            import numpy as _np
            _dummy = _np.zeros((64, 64, 3), dtype=_np.uint8)
            try:
                engine(_dummy)
            except Exception as warmup_e:
                log(f"  [OCR] 预热时小异常（不影响后续使用）: {warmup_e}", force=True)

            elapsed = _time.time() - t_start
            log(f"  [OCR] ✓ GPU 引擎预热完成，耗时 {elapsed:.1f}s", force=True)
            log(f"RapidOCR engine loaded successfully (device: GPU, det_limit={det_limit})", force=True)
            log(f"  [OCR] ★ 后续 OCR 推理将使用 GPU 加速 ★", force=True)
            return {'engine': engine, 'use_cls': use_cls}

        except Exception as e:
            # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 运行级验证失败回退 CPU（不再 raise）
            log(f"  [OCR] ✗ GPU 引擎创建/预热失败（运行级验证失败）: {e}", force=True)
            import traceback
            log(f"  [OCR] {traceback.format_exc()}", force=True)
            log(f"  [OCR] → 回退 CPU 多线程模式（保证 OCR 功能可用）", force=True)
            # 同步全局标志：运行级失败后 detect_ort_gpu() 必须返回 False
            global _ort_gpu_runtime_failed
            _ort_gpu_runtime_failed = True
            gpu_available = False  # 降级标志，下面进入 CPU 分支

    # ============================================================
    # CPU 模式（原生 CPU 环境，或 GPU 引擎创建失败后的回退）
    # ============================================================
    if not gpu_available:
        if not _ort_gpu_checked or not _ort_gpu_available:
            log(f"Loading RapidOCR {version} (lang={ocr_lang}, cls={use_cls}, det_limit={det_limit}, device=CPU)...", force=True)
            log(f"  [OCR] 当前环境无 GPU/CUDA，使用 CPU 模式", force=True)
        else:
            log(f"  [OCR] GPU 回退: 使用 CPU 多线程模式 (det_limit={det_limit})", force=True)

        # 屏蔽 GPU，防止 onnxruntime-gpu 意外尝试 CUDA
        saved_cuda_env = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

        try:
            from rapidocr import RapidOCR

            init_params = {
                "Global.log_level": "error",
                "Det.limit_side_len": det_limit,
                "Det.limit_type": "max"
            }

            engine = RapidOCR(params=init_params)

            # CPU 预热
            import numpy as _np
            _dummy = _np.zeros((64, 64, 3), dtype=_np.uint8)
            try:
                engine(_dummy)
            except Exception as warmup_e:
                log(f"  [OCR] CPU 预热时小异常（不影响后续使用）: {warmup_e}", force=True)

            log(f"RapidOCR engine loaded successfully (device: CPU, det_limit={det_limit})", force=True)
            return {'engine': engine, 'use_cls': use_cls}

        except ImportError as e:
            # 尝试旧版包名（向后兼容）
            try:
                from rapidocr_onnxruntime import RapidOCR
                engine = RapidOCR()
                log(f"RapidOCR (legacy) engine loaded successfully (device: CPU)", force=True)
                return {'engine': engine, 'use_cls': use_cls}
            except ImportError:
                log(f"RapidOCR未安装: {e}", force=True)
                log("请运行: pip install rapidocr>=3.5.0", force=True)
                raise
        except Exception as e:
            log(f"RapidOCR初始化失败: {e}", force=True)
            raise
        finally:
            if saved_cuda_env is not None:
                os.environ["CUDA_VISIBLE_DEVICES"] = saved_cuda_env
            elif "CUDA_VISIBLE_DEVICES" in os.environ:
                del os.environ["CUDA_VISIBLE_DEVICES"]


def release_rapid_ocr_engine(engine_key: str = None):
    """
    释放RapidOCR引擎内存
    
    Args:
        engine_key: 要释放的引擎key
                   如果为None，释放所有引擎
    """
    global _rapid_ocr_engines
    import gc

    with _engine_lock:
        if engine_key:
            if engine_key in _rapid_ocr_engines:
                del _rapid_ocr_engines[engine_key]
                log(f"Released engine: {engine_key}")
        else:
            _rapid_ocr_engines.clear()
        log(f"Released all engines")
    
    gc.collect()


def _prescale_image(image: np.ndarray, max_dim: int) -> Tuple[np.ndarray, float]:
    """
    预缩放图像（提升OCR速度）
    
    Args:
        image: 输入图像
        max_dim: 最大边长
    
    Returns:
        Tuple[np.ndarray, float]: (缩放后的图像, 缩放比例)
    """
    h, w = image.shape[:2]
    max_side = max(h, w)
    
    if max_side <= max_dim:
        return image, 1.0
    
    scale = max_dim / max_side
    new_w = int(w * scale)
    new_h = int(h * scale)
    
    scaled = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    return scaled, scale


def parse_rapid_ocr_result(result) -> List[dict]:
    """
    解析RapidOCR识别结果
    
    RapidOCR 3.x 返回格式 (RapidOCROutput 数据类):
        result.boxes: numpy array [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] for each text
        result.txts: tuple of text strings
        result.scores: tuple of confidence scores
    
    RapidOCR 1.x 返回格式 (旧版，向后兼容):
        result = (
            [([[x1,y1],[x2,y2],[x3,y3],[x4,y4]], text, confidence), ...],
            elapsed_time
        )
    
    Args:
        result: RapidOCR返回的结果
    
    Returns:
        List[dict]: 解析后的文本框列表
    """
    parsed = []
    
    if result is None:
        return parsed
    
    # 检测 RapidOCR 3.x 新格式 (RapidOCROutput 数据类)
    if hasattr(result, 'boxes') and hasattr(result, 'txts') and hasattr(result, 'scores'):
        # RapidOCR 3.x 格式
        boxes = result.boxes
        txts = result.txts
        scores = result.scores
        
        if boxes is None or txts is None:
            return parsed
        
        for i in range(len(txts)):
            box = boxes[i].tolist() if hasattr(boxes[i], 'tolist') else boxes[i]
            text = txts[i]
            confidence = scores[i] if scores and i < len(scores) else 0.0
            
            if len(box) >= 4:
                parsed.append({
                    'box': box,
                    'text': text,
                    'confidence': confidence
                })
    else:
        # RapidOCR 1.x 旧格式（向后兼容）
        # 返回的是元组 (boxes_list, elapsed_time)
        boxes_list = result[0] if result else None
        
        if not boxes_list:
            return parsed
        
        for item in boxes_list:
            if len(item) >= 3:
                box = item[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                text = item[1]
                confidence = item[2]
                
                # 转换box格式
                if len(box) >= 4:
                    parsed.append({
                        'box': box,
                        'text': text,
                        'confidence': confidence
                    })
    
    return parsed


def ocr_image_with_rapid(image: np.ndarray, ocr_engine_info: dict, det_limit_side_len: int = None) -> List[dict]:
    """
    使用RapidOCR对图像进行OCR（性能优化版）
    
    Args:
        image: 输入图像（BGR格式）
        ocr_engine_info: RapidOCR引擎信息字典 {'engine': engine, 'use_cls': bool}
        det_limit_side_len: 检测时图像最大边长（None则使用引擎默认值）
    
    Returns:
        List[dict]: OCR结果列表
    """
    try:
        # 兼容旧版调用方式
        if isinstance(ocr_engine_info, dict):
            ocr_engine = ocr_engine_info['engine']
            use_cls = ocr_engine_info.get('use_cls', False)
        else:
            ocr_engine = ocr_engine_info
            use_cls = False
        
        h, w = image.shape[:2]
        log(f"  OCR输入: {w}x{h}, det_limit={det_limit_side_len}, cls={use_cls}")
        
        # RapidOCR接受BGR格式的numpy数组
        # 关键优化：
        # 1. use_cls=False 可提速20-30%（扫描文档通常不需要方向分类）
        # 2. det_limit_side_len 控制检测精度与速度的平衡
        
        # RapidOCR 3.x 参数通过初始化传入，调用时只传基本参数
        result = ocr_engine(
            image, 
            use_det=True,
            use_cls=use_cls,  # 禁用方向分类可显著提速
            use_rec=True
        )
        
        parsed = parse_rapid_ocr_result(result)
        log(f"  OCR识别到 {len(parsed)} 个文本框")
        return parsed
    except Exception as e:
        log(f"OCR识别失败: {e}", force=True)
        import traceback
        log(traceback.format_exc(), force=True)
        return []



# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 TextWriter 快速文字层公共函数
# 抽取自 add_text_layer_to_pdf_rapid 第二阶段（lines 766-801），供主流程单页 PDF 使用
def write_ocr_text_layer(page: "fitz.Page", ocr_results: List[dict],
                         page_dpi: int, scale: float = 1.0) -> int:
    """
    将 OCR 结果以 TextWriter 快速路径写入 PDF 页面的透明文字层

    TextWriter 路径已验证（spike）：文字层跨 insert_pdf 合并后完整保留且可搜索。
    采用批量 append + 一次 write_text 的快速路径（insert_textbox 慢路径禁止用于主流程）。

    Args:
        page: PyMuPDF 页面对象（fitz.Page）
        ocr_results: OCR 识别结果列表（来自 ocr_image_with_rapid）
        page_dpi: 页面 DPI（用于像素→PDF 点坐标转换）
        scale: 预缩放比例（默认 1.0，OCR 预缩放时需反算）

    Returns:
        int: 成功写入的文本框数量
    """
    cached_font = get_cached_font("china-s")
    tw = fitz.TextWriter(page.rect)
    text_count = 0

    for item in ocr_results:
        box = item['box']
        text = item['text']

        if not text or not text.strip():
            continue

        try:
            pts = np.array(box, dtype=np.float32)
            if scale < 1.0:
                pts = pts / scale
            pts_pdf = pts * 72.0 / page_dpi

            x_min = float(min(pts_pdf[:, 0]))
            y_min = float(min(pts_pdf[:, 1]))
            x_max = float(max(pts_pdf[:, 0]))
            y_max = float(max(pts_pdf[:, 1]))

            box_h = y_max - y_min
            if box_h <= 0 or x_max <= x_min:
                continue

            font_size = max(4, min(72, box_h * 0.8))
            baseline_y = y_max - box_h * 0.1

            tw.append(pos=(x_min, baseline_y), text=text, font=cached_font, fontsize=font_size)
            text_count += 1
        except Exception as e:
            log(f"[文本框坐标写入失败] text='{text[:20]}...', {e}")

    if text_count > 0:
        tw.write_text(page, color=(0, 0, 0), render_mode=3)

    return text_count


def add_text_layer_to_pdf_rapid(
    input_path: str,
    output_path: str,
    ocr_lang: str = "ch",
    progress_callback: callable = None,
    fast_mode: bool = True
) -> bool:
    """
    为PDF添加OCR文字层（RapidOCR版本 - 性能优化版）
    
    性能优化：
    1. 复用 Font 对象（减少约15%时间）
    2. 禁用方向分类器（减少约20-30%时间）
    3. 批量写入文本层
    4. 多页并行OCR识别（多页PDF速度提升50-100%）
    5. 减少日志输出
    
    Args:
        input_path: 输入PDF文件路径
        output_path: 输出PDF文件路径
        ocr_lang: OCR语言
        progress_callback: 进度回调函数 callback(current_page, total_pages)
        fast_mode: 是否启用快速模式（禁用方向分类器）
    
    Returns:
        bool: 是否成功
    """
    import time as time_module
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    log(f"开始添加文字层: {input_path.name}", force=True)
    start_time = time_module.time()

    output_doc = None
    try:
        # 配置参数
        default_dpi = getattr(cfg, 'OCR_DEFAULT_DPI', 300)
        max_image_dim = getattr(cfg, 'OCR_MAX_IMAGE_DIM', 4096)
        prescale_enabled = getattr(cfg, 'OCR_PRESCALE_ENABLED', False)
        det_limit = getattr(cfg, 'OCR_DET_LIMIT_SIDE_LEN', 960)
        
        # 快速模式下使用更小的检测边长
        if fast_mode and det_limit > 960:
            det_limit = 960
        
        # 获取OCR引擎
        ocr_engine_info = get_rapid_ocr_engine(ocr_lang, use_cls=not fast_mode, det_limit=det_limit)
        
        # 打开输入PDF（仅用于获取页数，fitz.Document 非线程安全，不可跨线程共享）
        doc = fitz.open(str(input_path))
        total_pages = len(doc)
        doc.close()

        log(f"PDF共 {total_pages} 页, 快速模式: {fast_mode}, det_limit: {det_limit}", force=True)

        # 预先获取缓存的字体
        cached_font = get_cached_font("china-s")

        # ========== 第一阶段：并行提取图像和执行OCR ==========
        def process_page_ocr(page_idx):
            """单页OCR处理（可并行）"""
            # 每个线程独立打开文档（fitz.Document 非线程安全，不可共享）
            local_doc = fitz.open(str(input_path))
            try:
                page = local_doc[page_idx]

                # 获取页面信息
                images = page.get_images()
                page_dpi = default_dpi
                original_image_bytes = None
                dpi_metadata_found = False  # 标记是否从图像中读取到有效DPI元数据

                if images:
                    try:
                        xref = images[0][0]
                        img_info = local_doc.extract_image(xref)
                        if img_info:
                            original_image_bytes = img_info.get("image")
                            image_dpi = get_image_dpi_from_bytes(original_image_bytes)
                            if image_dpi and 72 <= image_dpi <= 1200:
                                page_dpi = image_dpi
                                dpi_metadata_found = True
                    except Exception as e:
                        log(f"[页面图像DPI提取失败] page={page_idx+1}, {e}")

                # 性能优化：满足安全条件时直接解码嵌入图像，跳过页面重渲染
                # 安全条件：无旋转 + 单图占满页面 + DPI元数据有效 + 尺寸与渲染结果严格一致
                # 不满足时自动回退渲染路径，确保任何场景下行为不变
                img_bgr = None
                pix = None

                if (original_image_bytes is not None and len(images) == 1
                        and page.rotation == 0 and dpi_metadata_found):
                    try:
                        decoded = cv2.imdecode(
                            np.frombuffer(original_image_bytes, dtype=np.uint8),
                            cv2.IMREAD_COLOR)
                        if decoded is not None:
                            # 严格验证：解码尺寸必须与渲染尺寸完全一致（保证坐标映射等价）
                            exp_w = int(round(page.rect.width * page_dpi / 72.0))
                            exp_h = int(round(page.rect.height * page_dpi / 72.0))
                            dh, dw = decoded.shape[:2]
                            if dw == exp_w and dh == exp_h:
                                img_bgr = decoded
                    except Exception as e:
                        log(f"[直解嵌入图像失败，回退渲染] page={page_idx+1}, {e}")

                if img_bgr is None:
                    # 渲染路径（默认/回退）
                    zoom = page_dpi / 72.0
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, alpha=False)

                    # 转换为numpy数组
                    img_rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
                    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

                # 预缩放（大图自动启用，提升速度）
                h, w = img_bgr.shape[:2]
                auto_prescale_threshold = 2048  # 大于2048px自动启用预缩放
                if prescale_enabled or max(h, w) > auto_prescale_threshold:
                    img_for_ocr, scale = _prescale_image(img_bgr, min(max_image_dim, auto_prescale_threshold))
                else:
                    img_for_ocr, scale = img_bgr, 1.0

                # 执行OCR
                ocr_results = ocr_image_with_rapid(img_for_ocr, ocr_engine_info, det_limit_side_len=det_limit)

                return {
                    'page_idx': page_idx,
                    'page_rect': page.rect,
                    'page_dpi': page_dpi,
                    'original_image_bytes': original_image_bytes,
                    'pix_samples': pix.samples if pix is not None else None,
                    'pix_width': pix.width if pix is not None else 0,
                    'pix_height': pix.height if pix is not None else 0,
                    'ocr_results': ocr_results,
                    'scale': scale
                }
            except Exception as e:
                log(f"[页面OCR处理异常] page={page_idx+1}, {e}")
                return None
            finally:
                local_doc.close()
        
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-004 OCR 流水线化（内存换时间）
        # 拆分为两阶段：Stage A（渲染/解码，CPU 可并行）→ Stage B（OCR 推理，GPU 串行）
        # GPU 模式下两阶段重叠执行（预取），CPU 模式保持原并行逻辑
        import queue as queue_module

        def render_page(page_idx: int) -> dict:
            """Stage A：页面渲染/解码（CPU 密集，可多线程并行）"""
            local_doc = fitz.open(str(input_path))
            try:
                page = local_doc[page_idx]
                images = page.get_images()
                page_dpi = default_dpi
                original_image_bytes = None
                dpi_metadata_found = False

                if images:
                    try:
                        xref = images[0][0]
                        img_info = local_doc.extract_image(xref)
                        if img_info:
                            original_image_bytes = img_info.get("image")
                            image_dpi = get_image_dpi_from_bytes(original_image_bytes)
                            if image_dpi and 72 <= image_dpi <= 1200:
                                page_dpi = image_dpi
                                dpi_metadata_found = True
                    except Exception as e:
                        log(f"[页面图像DPI提取失败] page={page_idx+1}, {e}")

                img_bgr = None
                pix = None
                if (original_image_bytes is not None and len(images) == 1
                        and page.rotation == 0 and dpi_metadata_found):
                    try:
                        decoded = cv2.imdecode(
                            np.frombuffer(original_image_bytes, dtype=np.uint8),
                            cv2.IMREAD_COLOR)
                        if decoded is not None:
                            exp_w = int(round(page.rect.width * page_dpi / 72.0))
                            exp_h = int(round(page.rect.height * page_dpi / 72.0))
                            dh, dw = decoded.shape[:2]
                            if dw == exp_w and dh == exp_h:
                                img_bgr = decoded
                    except Exception as e:
                        log(f"[直解嵌入图像失败，回退渲染] page={page_idx+1}, {e}")

                if img_bgr is None:
                    zoom = page_dpi / 72.0
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img_rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
                    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

                h, w = img_bgr.shape[:2]
                auto_prescale_threshold = 2048
                if prescale_enabled or max(h, w) > auto_prescale_threshold:
                    img_for_ocr, scale = _prescale_image(img_bgr, min(max_image_dim, auto_prescale_threshold))
                else:
                    img_for_ocr, scale = img_bgr, 1.0

                return {
                    'page_idx': page_idx,
                    'page_rect': page.rect,
                    'page_dpi': page_dpi,
                    'original_image_bytes': original_image_bytes,
                    'pix_samples': pix.samples if pix is not None else None,
                    'pix_width': pix.width if pix is not None else 0,
                    'pix_height': pix.height if pix is not None else 0,
                    'img_for_ocr': img_for_ocr,
                    'scale': scale
                }
            except Exception as e:
                log(f"[页面渲染异常] page={page_idx+1}, {e}")
                return None
            finally:
                local_doc.close()

        def ocr_page(rendered: dict) -> dict:
            """Stage B：OCR 推理（GPU 串行 / CPU 可并行）"""
            if rendered is None:
                return None
            try:
                ocr_results = ocr_image_with_rapid(
                    rendered['img_for_ocr'], ocr_engine_info, det_limit_side_len=det_limit)
                rendered['ocr_results'] = ocr_results
                del rendered['img_for_ocr']  # 释放图像内存
                return rendered
            except Exception as e:
                log(f"[OCR推理异常] page={rendered['page_idx']+1}, {e}")
                return None

        # 并行执行OCR（GPU模式下串行以避免onnxruntime CUDA EP显存竞争，CPU模式多线程）
        cpu_count = os.cpu_count() or 4
        use_gpu = detect_ort_gpu()
        page_results = [None] * total_pages

        if use_gpu and total_pages > 1:
            # REQ-004 GPU 流水线模式：Stage A（渲染）多线程预取 → Stage B（OCR）单线程串行
            prefetch_limit = getattr(cfg, 'OCR_PAGE_PREFETCH_LIMIT', 32)
            prefetch_workers_cfg = getattr(cfg, 'OCR_PREFETCH_WORKERS', 0)
            if prefetch_workers_cfg > 0:
                prefetch_workers = min(prefetch_workers_cfg, total_pages)
            else:
                prefetch_workers = min(max(cpu_count - 1, 1), total_pages, 4)

            log(f"使用 GPU 流水线模式：{prefetch_workers} 线程预取渲染，OCR 串行推理，预取上限 {prefetch_limit} 页")

            prefetch_queue = queue_module.Queue(maxsize=prefetch_limit)

            def producer_simple() -> None:
                with ThreadPoolExecutor(max_workers=prefetch_workers) as pool:
                    # 分批提交，按序收集结果
                    batch_size = prefetch_workers
                    for batch_start in range(0, total_pages, batch_size):
                        batch_end = min(batch_start + batch_size, total_pages)
                        futures = {pool.submit(render_page, i): i for i in range(batch_start, batch_end)}
                        # 按页码顺序收集（保证 PDF 页序）
                        batch_results = {}
                        for future in as_completed(futures):
                            page_idx = futures[future]
                            batch_results[page_idx] = future.result()
                        for i in range(batch_start, batch_end):
                            prefetch_queue.put(batch_results.get(i))
                prefetch_queue.put(None)  # 哨兵标记结束

            producer_thread = threading.Thread(target=producer_simple, daemon=True)
            producer_thread.start()

            # Stage B 消费者：串行 OCR 推理
            completed = 0
            for i in range(total_pages):
                rendered = prefetch_queue.get()  # 阻塞等待预取结果
                result = ocr_page(rendered)
                page_results[i] = result
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_pages)
                if completed % 10 == 0:
                    log(f"  [流水线] OCR 进度: {completed}/{total_pages}")

            producer_thread.join(timeout=5)

        elif total_pages > 1 and not use_gpu:
            max_workers = min(cpu_count, total_pages, 8)
            log(f"使用 {max_workers} 线程并行处理OCR (CPU模式)")
            # CPU 模式保持原逻辑：渲染+OCR 合并在 process_page_ocr 中并行
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_page_ocr, i): i for i in range(total_pages)}
                completed = 0
                for future in as_completed(futures):
                    page_idx = futures[future]
                    try:
                        page_results[page_idx] = future.result()
                        completed += 1
                        if progress_callback:
                            progress_callback(completed, total_pages)
                    except Exception as e:
                        log(f"  页 {page_idx + 1} OCR失败: {e}")
                        page_results[page_idx] = None
        else:
            # 单页直接处理
            for i in range(total_pages):
                page_results[i] = process_page_ocr(i)
                if progress_callback:
                    progress_callback(i + 1, total_pages)
        
        # ========== 第二阶段：串行构建PDF ==========
        output_doc = fitz.open()
        
        for page_idx, result in enumerate(page_results):
            if result is None:
                continue
            
            page_rect = result['page_rect']
            page_dpi = result['page_dpi']
            original_image_bytes = result['original_image_bytes']
            ocr_results = result['ocr_results']
            scale = result['scale']
            
            # 创建新页面
            new_page = output_doc.new_page(width=page_rect.width, height=page_rect.height)
            
            # 插入图像
            if original_image_bytes:
                new_page.insert_image(new_page.rect, stream=original_image_bytes)
            else:
                # 从保存的数据重建pixmap
                pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, result['pix_width'], result['pix_height']), result['pix_samples'], False)
                new_page.insert_image(new_page.rect, pixmap=pix)
            
            # 批量添加透明文字层
            tw = fitz.TextWriter(new_page.rect)
            text_count = 0
            
            for item in ocr_results:
                box = item['box']
                text = item['text']
                
                if not text or not text.strip():
                    continue
                
                try:
                    pts = np.array(box, dtype=np.float32)
                    if scale < 1.0:
                        pts = pts / scale
                    pts_pdf = pts * 72.0 / page_dpi
                    
                    x_min = float(min(pts_pdf[:, 0]))
                    y_min = float(min(pts_pdf[:, 1]))
                    x_max = float(max(pts_pdf[:, 0]))
                    y_max = float(max(pts_pdf[:, 1]))
                    
                    box_h = y_max - y_min
                    if box_h <= 0 or x_max <= x_min:
                        continue
                    
                    font_size = max(4, min(72, box_h * 0.8))
                    baseline_y = y_max - box_h * 0.1
                    
                    tw.append(pos=(x_min, baseline_y), text=text, font=cached_font, fontsize=font_size)
                    text_count += 1
                except Exception as e:
                    log(f"[文本框坐标写入失败] text='{text[:20]}...', {e}")
            
            # 写入文本
            if text_count > 0:
                tw.write_text(new_page, color=(0, 0, 0), render_mode=3)
            
            log(f"  页 {page_idx + 1}/{total_pages}: {text_count} 文本框")
        
        # 保存输出PDF
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题
        # 整本转换/OCR回退保存前子集化文字层字库，避免输出PDF内嵌整份CJK字库导致体积翻倍
        from backend.services.pdf_font_service import save_pdf_with_font_subset
        save_pdf_with_font_subset(output_doc, output_path)

        total_time = time_module.time() - start_time
        log(f"完成: {output_path.name}, 总耗时: {total_time:.1f}秒, 平均: {total_time/total_pages:.2f}秒/页", force=True)
        return True

    except Exception as e:
        import traceback
        log(traceback.format_exc(), force=True)
        log(f"添加文字层失败: {e}", force=True)
        return False
    finally:
        if output_doc is not None:
            output_doc.close()


def convert_to_dual_layer_pdf_rapid(
    input_path: str,
    output_path: str,
    ocr_lang: str = "ch",
    auto_rotate: bool = True,
    progress_callback: callable = None,
    fast_mode: bool = True
) -> bool:
    """
    将扫描版PDF转换为双层PDF（RapidOCR版本 - 性能优化版）
    
    性能优化（fast_mode=True）：
    1. 禁用方向分类器（提速20-30%）
    2. 优化检测边长（提速10-20%）
    3. 复用Font对象（提速10-15%）
    4. 批量写入文本层
    
    Args:
        input_path: 输入PDF文件路径
        output_path: 输出PDF文件路径
        ocr_lang: OCR语言 (ch, en等)
        auto_rotate: 是否自动检测并旋转页面（保留参数兼容性）
        progress_callback: 进度回调函数，签名为 callback(step, current_page, total_pages, percent)
        fast_mode: 是否启用快速模式（默认True，可提速40-50%）
    
    Returns:
        bool: 转换是否成功
    """
    import time as time_module

    input_path = Path(input_path)
    output_path = Path(output_path)
    
    conversion_start_time = time_module.time()
    log(f"=== 开始转换双层PDF (RapidOCR): {input_path.name} ===", force=True)
    
    try:
        # 获取PDF总页数用于进度计算
        temp_doc = None
        try:
            temp_doc = fitz.open(str(input_path))
            total_pages = len(temp_doc)
        except Exception as e:
            log(f"[PDF页数读取失败] {input_path.name}, {e}")
            total_pages = 1
        finally:
            if temp_doc is not None:
                temp_doc.close()
        
        # 进度回调包装
        def ocr_progress(current_page, page_total):
            if progress_callback:
                percent = int((current_page / page_total) * 100)
                progress_callback("ocr", current_page, page_total, percent)
        
        # 添加OCR文字层（使用快速模式）
        success = add_text_layer_to_pdf_rapid(
            str(input_path), 
            str(output_path), 
            ocr_lang, 
            ocr_progress,
            fast_mode=fast_mode
        )
        
        elapsed_time = time_module.time() - conversion_start_time
        if success:
            avg_time = elapsed_time / total_pages if total_pages > 0 else 0
            log(f"=== 转换完成: {output_path.name}，总耗时: {elapsed_time:.1f}秒，平均: {avg_time:.2f}秒/页 ===", force=True)
        else:
            log(f"错误: 添加文字层失败，耗时: {elapsed_time:.1f}秒", force=True)
        
        return success
        
    except Exception as e:
        import traceback
        log(traceback.format_exc(), force=True)
        elapsed_time = time_module.time() - conversion_start_time
        log(f"错误: {e}，耗时: {elapsed_time:.1f}秒", force=True)
        return False


def batch_convert_to_dual_layer_pdf_rapid(
    input_dir: str,
    output_dir: str,
    ocr_lang: str = "ch",
    keep_structure: bool = True,
    auto_rotate: bool = True
) -> Tuple[int, int]:
    """
    批量转换目录中的PDF文件（RapidOCR版本）
    
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
        log(f"Input dir not exist: {input_dir}")
        return (0, 0)
    
    pdf_files = list(input_path.rglob("*.pdf"))
    
    if not pdf_files:
        log(f"No PDF files found: {input_dir}")
        return (0, 0)
    
    success_count = 0
    failed_count = 0
    
    for pdf_file in pdf_files:
        if keep_structure:
            rel_path = pdf_file.relative_to(input_path)
            out_file = output_path / rel_path
        else:
            out_file = output_path / pdf_file.name
        
        if convert_to_dual_layer_pdf_rapid(str(pdf_file), str(out_file), ocr_lang, auto_rotate):
            success_count += 1
        else:
            failed_count += 1
    
    return (success_count, failed_count)


# 为了兼容性，提供与PaddleOCR版本相同的函数名
convert_to_dual_layer_pdf = convert_to_dual_layer_pdf_rapid
batch_convert_to_dual_layer_pdf = batch_convert_to_dual_layer_pdf_rapid


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python ocr_rapid.py <input_pdf> <output_pdf> [lang]")
        print("  lang: ch(Chinese), en(English)")
        print("")
        print("RapidOCR version:", get_rapidocr_version())
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    lang = sys.argv[3] if len(sys.argv) > 3 else "ch"
    
    success = convert_to_dual_layer_pdf_rapid(input_file, output_file, lang)
    sys.exit(0 if success else 1)
