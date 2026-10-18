# -*- coding: utf-8 -*-
"""
海棠文档工坊 - 核心模块

主要功能：
1. YOLO 文档布局检测（保护表格、图片区域）
2. 黑斑噪点检测与清除
3. 纵向推土机黑边检测与清除
"""

# 延迟导入 — config 总是可用，cleaner 依赖 doclayout_yolo/torch（仅 GPU 环境可用）
from . import config


def __getattr__(name):
    if name == "DocumentCleaner":
        from .cleaner import DocumentCleaner
        return DocumentCleaner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ['DocumentCleaner', 'config']
__version__ = '3.4.00'
