# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
# xuechong 2026-07-20 研发BUG-0009 大文件拆分：GPU/OCR 函数提取到 gpu.py / ocr_engine.py
"""
海棠文档工坊 - 核心清洁处理模块（拆分版）

本文件包含：
1. 模块级函数（_log、get_model_path）
2. 从 gpu.py / ocr_engine.py 重新导出的函数（保持对外接口不变）
3. 导出 DocumentCleaner（从 core.py 导入）

拆分结构：
- __init__.py: 模块级函数 + 导出
- gpu.py: CUDA 可用性检测、YOLO 设备选择（_check_cuda_available、_setup_cuda_jit_cache、get_yolo_device）
- ocr_engine.py: OCR 引擎创建与缓存（_get_cached_ocr_engine）
- cache.py: KernelCache、ConfigCache、ImageCache
- core.py: DocumentCleaner 主类
- skew.py: 倾斜矫正 Mixin
- orientation.py: 页面方向检测 Mixin
- receipt.py: 票据处理 Mixin
- protect.py: 保护区域检测 Mixin
- noise.py: 噪点检测 Mixin
- background.py: 背景增强 Mixin
"""

import warnings
# 抑制 omegaconf 的无害警告（doclayout_yolo/ultralytics 内部触发）
warnings.filterwarnings("ignore", message="update.*merge flag", module="omegaconf")

import sys
from datetime import datetime

# ========== 统一日志函数（带时间戳） ==========
def _log(msg: str):
    """统一日志函数：带完整时间戳 年-月-日 时:分:秒.毫秒"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    sys.stdout.write(f"[{timestamp}] {msg}\n")
    sys.stdout.flush()

from backend import config as cfg

# 导入缓存类（供其他模块使用）
from .cache import kernel_cache, config_cache, ImageCache, KernelCache, ConfigCache

# xuechong 2026-07-20 从 gpu.py / ocr_engine.py 重新导出（保持对外接口不变）
from .gpu import _check_cuda_available, _setup_cuda_jit_cache, get_yolo_device
from .ocr_engine import _get_cached_ocr_engine


def get_model_path():
    """获取模型路径（优先使用本地模型，避免网络请求）"""
    if cfg.YOLO_MODEL_PATH:
        _log(f"  [模型] 使用本地模型: {cfg.YOLO_MODEL_PATH}")
        return cfg.YOLO_MODEL_PATH

    # 本地模型不存在时，抛出明确错误（避免在内网环境下尝试下载）
    error_msg = (
        f"[错误] 未找到本地 YOLO 模型文件！\n"
        f"  期望文件: {cfg.YOLO_MODEL_FILENAME}\n"
        f"  请将模型文件放入 models/ 目录下，或确保 Hugging Face 缓存存在。\n"
        f"  模型下载地址: https://huggingface.co/{cfg.YOLO_MODEL_REPO}"
    )
    _log(error_msg)
    raise FileNotFoundError(error_msg)


# ============================================================
# 导出 DocumentCleaner（从 core.py 导入）
# ============================================================
from .core import DocumentCleaner

__all__ = ['DocumentCleaner', '_log', '_check_cuda_available', '_setup_cuda_jit_cache',
           '_get_cached_ocr_engine', 'get_model_path', 'get_yolo_device']
