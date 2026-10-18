# -*- coding: utf-8 -*-
# xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# REQ-003 二次倾斜矫正门控机制单元测试（纯几何构造，不依赖 OCR/方向检测，确定性断言）
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
import numpy as np

from backend.cleaner import DocumentCleaner


def _make_text_image(tilt_deg: float = 0.0) -> np.ndarray:
    """构造横排文字行合成图（白底黑条模拟），tilt_deg 为整体逆时针倾斜角"""
    canvas = np.full((1400, 2000), 255, dtype=np.uint8)
    for row in range(10):
        y = 150 + row * 120
        # 条宽 1200px = 0.6 倍图宽，避开文字行通道的全幅伪影过滤（rect_w < w*0.8 严格边界）
        cv2.rectangle(canvas, (400, y), (1600, y + 40), 0, -1)
    if tilt_deg:
        h, w = canvas.shape
        m = cv2.getRotationMatrix2D((w // 2, h // 2), tilt_deg, 1.0)
        canvas = cv2.warpAffine(canvas, m, (w, h), borderValue=255)
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def test_telemetry_recorded_on_horizontal_text():
    """横排文字图：遥测记录 n_text>=2、final 接近 0（正图无矫正）"""
    c = DocumentCleaner()
    angle = c._detect_skew_angle(_make_text_image(0.0))
    t = c._last_skew_telemetry
    assert t["n_text"] >= 2
    assert abs(angle) < 0.5


def test_vertical_text_first_pass_blind():
    """竖排文字图（横放票据在竖版扫描中的形态）：文字行近垂直 → 首轮 n_text<2（已知盲区特征）"""
    c = DocumentCleaner()
    img = _make_text_image(2.0)
    vertical = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)  # 文字行变为近垂直
    angle = c._detect_skew_angle(vertical)
    assert c._last_skew_telemetry["n_text"] < 2, \
        f"竖排形态下文字行样本应为<2，实测 {c._last_skew_telemetry['n_text']}"


def test_second_detect_recovers_tilt_after_rotation():
    """90°旋转回正后的形态（横排文字+3°倾斜）：二次检测应恢复倾斜幅值且文字通道有效"""
    c = DocumentCleaner()
    upright = _make_text_image(3.0)  # 模拟管线 90° 旋转后的形态：文字行已近水平
    angle = c._detect_skew_angle(upright)
    # 检测返回的是"待矫正角"（与 _deskew_image 同号约定），此处断言幅值恢复 ≈3°
    assert abs(abs(angle) - 3.0) < 1.0, f"二次检测幅值应约 3°，实测 {angle:.2f}°"
    assert c._last_skew_telemetry["n_text"] >= 2
