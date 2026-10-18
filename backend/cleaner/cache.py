# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
"""缓存类模块：KernelCache、ConfigCache、ImageCache"""

import cv2
import numpy as np
from typing import Tuple

from backend import config as cfg


class KernelCache:
    """
    形态学 Kernel 缓存 - 单例模式
    避免每次处理时重复创建相同的 kernel
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._kernels = {}
        return cls._instance
    
    def get_ellipse(self, size: int) -> np.ndarray:
        """获取椭圆 kernel（缓存）"""
        key = ('ellipse', size, size)
        if key not in self._kernels:
            self._kernels[key] = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (size, size)
            )
        return self._kernels[key]
    
    def get_ellipse_wh(self, w: int, h: int) -> np.ndarray:
        """获取椭圆 kernel（缓存，指定宽高）"""
        key = ('ellipse', w, h)
        if key not in self._kernels:
            self._kernels[key] = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (w, h)
            )
        return self._kernels[key]
    
    def get_rect(self, w: int, h: int) -> np.ndarray:
        """获取矩形 kernel（缓存）"""
        key = ('rect', w, h)
        if key not in self._kernels:
            self._kernels[key] = cv2.getStructuringElement(
                cv2.MORPH_RECT, (w, h)
            )
        return self._kernels[key]
    
    def get_ones(self, size: int) -> np.ndarray:
        """获取全1矩阵 kernel（缓存）"""
        key = ('ones', size, size)
        if key not in self._kernels:
            self._kernels[key] = np.ones((size, size), np.uint8)
        return self._kernels[key]


class ConfigCache:
    """
    配置值缓存 - 单例模式
    避免重复的 getattr 调用，提升性能
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
            cls._instance._loaded = False
        return cls._instance
    
    def _ensure_loaded(self):
        """确保配置已加载"""
        if self._loaded:
            return
        
        # 预加载常用配置值
        config_keys = [
            # 杂质线条检测
            ('ENABLE_STRAY_LINE_DETECTION', True),
            ('STRAY_LINE_MAX_WIDTH', 4),
            ('STRAY_LINE_MIN_LENGTH', 30),
            ('STRAY_LINE_MIN_ASPECT', 10.0),
            ('STRAY_LINE_PROTECT_DISTANCE', 20),
            # 折痕检测
            ('ENABLE_CREASE_DETECTION', True),
            ('CREASE_BINARY_THRESHOLD', 220),
            ('CREASE_MIN_LENGTH', 200),
            ('CREASE_MAX_WIDTH', 15),
            ('CREASE_MIN_ASPECT_RATIO', 15.0),
            # 钉痕检测
            ('PUNCH_HOLE_FULL_IMAGE', True),
            ('PUNCH_HOLE_MAX_ASPECT', 8.0),
            # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-003/004/002 新增
            ('PUNCH_HOLE_STRICT_MODE', True),
            ('PUNCH_HOLE_MIN_EXTENT', 0.5),
            ('PUNCH_HOLE_STRICT_MIN_AREA', 50),
            ('NOISE_PROTECT_COVER_MODE', True),
            ('NOISE_PROTECT_COVER_RATIO', 0.3),
            ('STRAY_LINE_PROTECT_COVER_RATIO', 0.05),
            ('NOISE_TEXT_GAP_EXCEPTION', True),
            ('NOISE_TEXT_GAP_NOISE_MAX_AREA', 60),
            ('NOISE_TEXT_GAP_MIN_DIST', 8),
            # 彩色保护（默认开启，保护彩色单据）
            ('ENABLE_COLOR_PROTECTION', True),
            ('ENABLE_FULL_COLOR_PROTECTION', True),
            ('FULL_COLOR_SATURATION_THRESHOLD', 20),
            ('COLOR_VALUE_MIN', 30),
            ('COLOR_VALUE_MAX', 250),
            ('COLOR_SATURATION_THRESHOLD', 30),
            ('YELLOW_H_LOW', 15),
            ('YELLOW_H_HIGH', 50),
            ('PINK_S_THRESHOLD', 20),
            ('PINK_H_LOW1', 140),
            ('PINK_H_HIGH1', 180),
            ('PINK_H_LOW2', 0),
            ('PINK_H_HIGH2', 10),
            ('BLUE_CYAN_H_LOW', 80),
            ('BLUE_CYAN_H_HIGH', 130),
            ('BLUE_CYAN_S_THRESHOLD', 25),
            ('BLUE_CYAN_V_MIN', 50),
            ('BLUE_CYAN_V_MAX', 250),
            # 英文数字保护
            ('ENABLE_ALPHANUMERIC_PROTECTION', True),
            ('ALPHANUMERIC_MIN_ASPECT', 0.2),
            ('ALPHANUMERIC_MAX_ASPECT', 4.0),
            # 单据检测
            ('ENABLE_RECEIPT_DETECTION', True),
            ('RECEIPT_BG_SAMPLE_MARGIN', 0.05),
            ('RECEIPT_EDGE_WHITE_THRESHOLD', 230),
            ('RECEIPT_EDGE_WHITE_RATIO', 0.70),
            ('RECEIPT_MIN_WHITE_EDGES', 3),
            ('RECEIPT_COLOR_DIFF_THRESHOLD', 15),
            ('RECEIPT_MIN_AREA_RATIO', 0.03),
            ('RECEIPT_MAX_AREA_RATIO', 0.60),
            ('RECEIPT_MIN_CONTOUR_AREA', 10000),
            ('RECEIPT_DILATE_KERNEL_SIZE', 5),
            ('RECEIPT_DILATE_ITERATIONS', 3),
            ('RECEIPT_SURROUNDING_CHECK_MARGIN', 30),
            ('RECEIPT_SURROUNDING_WHITE_RATIO', 0.50),
            # 纸张边界检测
            ('ENABLE_RECEIPT_BOUNDARY_BY_TEXTURE', True),
            ('RECEIPT_BOUNDARY_MIN_AREA_RATIO', 0.05),
            ('RECEIPT_BOUNDARY_MAX_AREA_RATIO', 0.98),
            # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
            # REQ-004 微小深色孤立斑强制清除（新增参数必须登记本清单，否则 config_cache 永远返回默认值）
            ('ENABLE_TINY_SPOT_CLEAN', True),
            ('TINY_SPOT_MAX_AREA', 450),
            ('TINY_SPOT_MAX_DIM', 28),
            ('AGGRESSIVE_CLEAN_THRESHOLD', 245),
        ]
        
        for key, default in config_keys:
            self._cache[key] = getattr(cfg, key, default)
        
        self._loaded = True
    
    def get(self, key: str, default=None):
        """获取缓存的配置值"""
        self._ensure_loaded()
        return self._cache.get(key, default)
    
    def reload(self):
        """重新加载配置（配置更新后调用）"""
        self._loaded = False
        self._cache.clear()
        self._ensure_loaded()


# 全局缓存实例
kernel_cache = KernelCache()
config_cache = ConfigCache()


class ImageCache:
    """
    图像预处理缓存 - 增强版
    
    避免重复计算，支持：
    - 灰度图、二值图、HSV、LAB 缓存
    - 连通域分析结果缓存
    - 掩码数组池（可复用）
    - HSV 通道分离缓存
    """
    
    def __init__(self, image: np.ndarray):
        """初始化缓存，执行一次性预处理"""
        self.h, self.w = image.shape[:2]
        
        # 灰度图 - 只计算一次
        self._gray = None
        
        # 二值图 - 只计算一次
        self._binary = None
        self._binary_threshold = None
        
        # 连通域分析结果 - 只计算一次
        self._cc_labels = None
        self._cc_stats = None
        self._cc_centroids = None
        self._cc_num_labels = None
        
        # HSV 图像 - 只计算一次
        self._hsv = None
        self._hsv_channels = None  # (H, S, V) 分离的通道
        
        # LAB 图像 - 只计算一次
        self._lab = None
        
        # 掩码数组池 - 可复用的掩码数组
        self._mask_pool = {}
        
        # 原图引用
        self._image = image
    
    @property
    def gray(self) -> np.ndarray:
        """获取灰度图（延迟计算）"""
        if self._gray is None:
            self._gray = cv2.cvtColor(self._image, cv2.COLOR_BGR2GRAY)
        return self._gray
    
    @property
    def hsv(self) -> np.ndarray:
        """获取HSV图像（延迟计算）"""
        if self._hsv is None:
            self._hsv = cv2.cvtColor(self._image, cv2.COLOR_BGR2HSV)
        return self._hsv
    
    @property
    def lab(self) -> np.ndarray:
        """获取LAB图像（延迟计算）"""
        if self._lab is None:
            self._lab = cv2.cvtColor(self._image, cv2.COLOR_BGR2LAB)
        return self._lab
    
    def get_hsv_channels(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """获取分离的 H/S/V 通道（缓存，避免重复切片）"""
        if self._hsv_channels is None:
            hsv = self.hsv
            self._hsv_channels = (hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2])
        return self._hsv_channels
    
    def get_binary(self, threshold: int = None) -> np.ndarray:
        """获取二值图（延迟计算，可指定阈值）"""
        if threshold is None:
            threshold = cfg.BINARY_THRESHOLD
        
        if self._binary is None or self._binary_threshold != threshold:
            _, self._binary = cv2.threshold(self.gray, threshold, 255, cv2.THRESH_BINARY_INV)
            self._binary_threshold = threshold
            # 二值图变了，连通域需要重新计算
            self._cc_labels = None
        return self._binary
    
    def get_connected_components(self, threshold: int = None) -> Tuple[int, np.ndarray, np.ndarray, np.ndarray]:
        """获取连通域分析结果（延迟计算）"""
        binary = self.get_binary(threshold)
        
        if self._cc_labels is None:
            self._cc_num_labels, self._cc_labels, self._cc_stats, self._cc_centroids = \
                cv2.connectedComponentsWithStats(binary, connectivity=8)
        
        return self._cc_num_labels, self._cc_labels, self._cc_stats, self._cc_centroids
    
    def get_zero_mask(self, name: str = None) -> np.ndarray:
        """
        获取一个全零掩码数组
        
        如果提供 name，则从池中获取并重置为零（可复用）
        如果不提供 name，则创建新数组
        """
        if name is None:
            return np.zeros((self.h, self.w), dtype=np.uint8)
        
        if name not in self._mask_pool:
            self._mask_pool[name] = np.zeros((self.h, self.w), dtype=np.uint8)
        else:
            self._mask_pool[name].fill(0)
        return self._mask_pool[name]
    
    def clear_cache(self):
        """清除缓存（释放内存）"""
        self._gray = None
        self._binary = None
        self._hsv = None
        self._hsv_channels = None
        self._lab = None
        self._cc_labels = None
        self._cc_stats = None
        self._cc_centroids = None
        self._mask_pool.clear()

