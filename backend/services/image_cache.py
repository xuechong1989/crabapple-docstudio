# -*- coding: utf-8 -*-
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-009 上传预解码缓存
"""上传预解码图片缓存服务

上传完成后预解码图片到内存缓存，一键修图与生成PDF复用内存图像，
减少重复 imdecode 与 DPI 读取。

特性：
- LRU 淘汰策略（默认 50 张）
- 按文件路径缓存（绝对路径 string key）
- 用户隔离清理（按 upload_dir 前缀批量失效）
- 配置化开关（UPLOAD_PREDECODE_CACHE_ENABLED，默认关闭）
"""
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from backend import config as cfg
from backend.services.logging_service import log_info


class _PredecodeCache:
    """线程安全的 LRU 预解码缓存"""

    def __init__(self, max_entries: int = 50):
        self._max = max_entries
        self._cache: OrderedDict[str, Tuple[np.ndarray, int]] = OrderedDict()
        self._lock = threading.Lock()
        self._enabled = getattr(cfg, 'UPLOAD_PREDECODE_CACHE_ENABLED', False)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get(self, path_str: str) -> Optional[Tuple[np.ndarray, int]]:
        """从缓存获取（命中时返回 (image, dpi)，未命中返回 None）"""
        if not self._enabled:
            return None
        with self._lock:
            if path_str in self._cache:
                self._cache.move_to_end(path_str)
                return self._cache[path_str]
            return None

    def put(self, path_str: str, image: np.ndarray, dpi: int) -> None:
        """写入缓存"""
        if not self._enabled:
            return
        with self._lock:
            if path_str in self._cache:
                self._cache.move_to_end(path_str)
            self._cache[path_str] = (image, dpi)
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def invalidate_prefix(self, dir_prefix: str) -> None:
        """按目录前缀批量失效（用户隔离清理时使用）"""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(dir_prefix)]
            for k in keys_to_remove:
                del self._cache[k]
            if keys_to_remove:
                log_info(f"[预解码缓存] 清理 {len(keys_to_remove)} 条（目录: {dir_prefix}）")

    def clear(self) -> None:
        """清空全部缓存"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            if count:
                log_info(f"[预解码缓存] 清空全部缓存（{count} 条）")

    def stats(self) -> dict:
        """返回缓存统计"""
        with self._lock:
            return {
                'enabled': self._enabled,
                'entries': len(self._cache),
                'max': self._max,
            }


# 全局单例
_cache_instance = _PredecodeCache(
    max_entries=getattr(cfg, 'UPLOAD_PREDECODE_CACHE_MAX', 50)
)


def load_image_with_cache(image_path: Path) -> Tuple[np.ndarray, int]:
    """加载图片（优先从缓存读取，未命中则解码并缓存）

    Args:
        image_path: 图片路径（Path 或 str）

    Returns:
        (image_bgr, dpi)
    """
    path = Path(image_path) if not isinstance(image_path, Path) else image_path
    path_str = str(path.resolve())

    # 尝试缓存命中
    cached = _cache_instance.get(path_str)
    if cached is not None:
        log_info(f"  [预解码缓存] 命中: {path.name}")
        return cached

    # 缓存未命中 → 解码（一次读盘，bytes 同时用于 DPI 读取，避免二次打开文件）
    raw_bytes = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(raw_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片: {path.name}")

    # DPI 读取（复用 app.py 的 get_image_dpi 逻辑，传 bytes 避免二次读盘）
    from backend.app import get_image_dpi
    dpi = get_image_dpi(path, image_bytes=raw_bytes.tobytes())

    # 写入缓存
    _cache_instance.put(path_str, image, dpi)

    return image, dpi


def predecode_images(file_paths: list, task_id: str = "") -> None:
    """批量预解码图片（上传完成后调用）

    Args:
        file_paths: 图片路径列表
        task_id: 任务 ID（日志用）
    """
    if not _cache_instance.enabled:
        return

    decoded = 0
    for fp in file_paths:
        path = Path(fp) if not isinstance(fp, Path) else fp
        path_str = str(path.resolve())
        if _cache_instance.get(path_str) is not None:
            continue  # 已缓存
        try:
            raw_bytes = np.fromfile(str(path), dtype=np.uint8)
            image = cv2.imdecode(raw_bytes, cv2.IMREAD_COLOR)
            if image is not None:
                from backend.app import get_image_dpi
                dpi = get_image_dpi(path, image_bytes=raw_bytes.tobytes())
                _cache_instance.put(path_str, image, dpi)
                decoded += 1
        except Exception as e:
            log_info(f"  [预解码缓存] 预解码失败: {path.name} - {e}")

    if decoded:
        log_info(f"[预解码缓存{' 任务'+task_id if task_id else ''}] 预解码 {decoded} 张图片")


def invalidate_user_cache(upload_dir: str) -> None:
    """清理用户上传目录对应的缓存（用户隔离清理时调用）

    Args:
        upload_dir: 用户上传目录绝对路径
    """
    dir_prefix = str(Path(upload_dir).resolve())
    _cache_instance.invalidate_prefix(dir_prefix)


def get_cache_stats() -> dict:
    """返回缓存统计信息"""
    return _cache_instance.stats()
