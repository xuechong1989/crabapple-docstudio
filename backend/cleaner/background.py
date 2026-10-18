# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
"""背景增强 Mixin 模块"""

import cv2
import numpy as np

from backend import config as cfg
from . import _log


class BackgroundMixin:
    """背景增强功能"""

    def _enhance_background(self, image: np.ndarray, protect_mask: np.ndarray = None) -> np.ndarray:
        """背景白化：基于 noteshrink 算法"""
        h, w = image.shape[:2]

        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-010 背景白化确定性
        # 旧实现使用 np.random.choice 随机采样，同一张图每次处理结果不同
        # 改为均匀网格采样（等间距），保证输出完全可复现
        sample_count = max(1000, int(h * w * 0.05))
        total_pixels = h * w
        if sample_count >= total_pixels:
            indices = np.arange(total_pixels)
        else:
            step = total_pixels / sample_count
            indices = np.arange(0, total_pixels, step).astype(np.int64)
            # xuechong 2026-08-07 处理异常-072.tif索引越界修复 浮点步长累积误差可能产生等于 total_pixels 的越界索引，裁剪到合法范围
            indices = indices[indices < total_pixels]
        pixels = image.reshape(-1, 3)[indices]

        quantized = (pixels // 32) * 32 + 16
        packed = quantized[:, 0].astype(np.int32) * 65536 + quantized[:, 1].astype(np.int32) * 256 + quantized[:, 2].astype(np.int32)
        unique, counts = np.unique(packed, return_counts=True)
        bg_packed = unique[counts.argmax()]
        bg_color = np.array([bg_packed // 65536, (bg_packed // 256) % 256, bg_packed % 256], dtype=np.uint8)

        bg_hsv = cv2.cvtColor(bg_color.reshape(1, 1, 3), cv2.COLOR_BGR2HSV).astype(np.float32)
        bg_s, bg_v = bg_hsv[0, 0, 1], bg_hsv[0, 0, 2]

        s_diff = np.abs(hsv[:, :, 1] - bg_s)
        v_diff = np.abs(hsv[:, :, 2] - bg_v)

        v_threshold = cfg.BACKGROUND_VALUE_THRESHOLD
        s_threshold = cfg.BACKGROUND_SAT_THRESHOLD

        fg_mask = (v_diff >= v_threshold) | (s_diff >= s_threshold)
        
        # 保护区域内的像素不允许白化
        if protect_mask is not None:
            fg_mask = fg_mask | (protect_mask > 0)

        # xuechong 2026-08-07 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 修复灰色区间保护回归
        # 恢复 3.1.02 行为：灰度 190-245 的像素可能是图纸有效内容（剖面线/阴影/表格边框/材料标识），
        # 不应被当作"背景"刷白。性能优化只改采样方式（确定性网格），不改保护逻辑
        if getattr(cfg, 'ENABLE_GRAY_CONTENT_PROTECTION', True):
            _gray_ch = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _light_gray_fg = (_gray_ch >= 190) & (_gray_ch < 245)
            fg_mask = fg_mask | _light_gray_fg

        result = image.copy()
        bg_pixel_count = np.sum(~fg_mask)
        result[~fg_mask] = (255, 255, 255)

        _log(f"    背景色 BGR: {bg_color}, 背景V={bg_v:.0f}, 背景S={bg_s:.0f}")
        _log(f"    阈值: V差≥{v_threshold}, S差≥{s_threshold}")
        _log(f"    白化像素: {bg_pixel_count} ({100*bg_pixel_count/(h*w):.1f}%)")

        return result
