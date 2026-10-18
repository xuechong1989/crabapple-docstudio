# -*- coding: utf-8 -*-
# xuechong 2026-08-07 处理异常-072.tif索引越界修复 回归测试
"""背景白化网格采样边界回归测试。"""
import numpy as np


def test_enhance_background_no_out_of_bounds():
    """采样索引不得超过像素总数（修复 072.tif 越界崩溃）。"""
    from backend.cleaner.background import BackgroundMixin
    h, w = 270, 32071  # 270*32071=8659170，复现原崩溃尺寸
    img = np.zeros((h, w, 3), dtype=np.uint8)
    out = BackgroundMixin()._enhance_background(img, np.zeros((h, w), dtype=np.uint8))
    assert out.shape == img.shape
