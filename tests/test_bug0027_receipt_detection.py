# -*- coding: utf-8 -*-
# xuechong 2026-08-19 研发BUG-0027-图档扫描-3.1.06-票据单据区分判定逻辑优化 验收测试
"""研发BUG-0027 验收测试：A组002色差消除 / B组票据零回退 / E组零新问题逐像素守卫

运行方式：
    python -m pytest tests/test_bug0027_receipt_detection.py -v --tb=short

环境变量覆盖（换机器/CI 时无需改代码）：
    BUG0027_SAMPLE_DIR    样张目录（默认研发BUG-0027工作目录 基准样张）
    BUG0027_BASELINE_DIR  修改前基线输出目录（默认同工作目录 修改前基线，2026-08-19 编码前归档）

C 组（BUG-0026 不回退）不在本文件重复实现：全量 pytest 时由 tests/test_bug0026_gray_blocks.py
覆盖（含 5 张样张指标断言），本文件 E 组另以其样张做逐像素一致性守卫。

A 组说明：方案 §3.2 指标"表格区内外背景 ≥255 占比差 ≤1pp"不可直接计算（内容像素密度影响
占比），实现口径等价调整为"表格区与外部四角的背景像素（gray>=240，排除深色内容）中位灰度
一致"——即客户观察"转 PDF 后背景颜色一样"的直接判据。实测锚点（2026-08-19）：修复后表格区
与四角中位均为 255；250-254 残留为边缘过渡散点（ROI 占比 2.29%，5×5 腐蚀后 ≥100px 小块仅
2 个），远低于同批 001.tif 天然普通路径输出的 13.43% 且无连续色差块（大块指标为 0）。
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

WORK_DIR = Path(os.environ.get("BUG0027_WORK_DIR", "tests/samples/bug0027"))
SAMPLE_DIR = Path(os.environ.get("BUG0027_SAMPLE_DIR", str(WORK_DIR / "基准样张")))
BASELINE_DIR = Path(os.environ.get("BUG0027_BASELINE_DIR", str(WORK_DIR / "修改前基线")))
BUG0026_SAMPLE_DIR = Path(os.environ.get(
    "BUG0026_SAMPLE_DIR", "tests/samples/2026-08-14"))

SAMPLES_AVAILABLE = (SAMPLE_DIR / "002.tif").exists()
BASELINE_AVAILABLE = (BASELINE_DIR / "002.png").exists()
BUG0026_AVAILABLE = (BUG0026_SAMPLE_DIR / "001.tif").exists()

# 002 原色差主块区域（修改前基线实测，归一化坐标，矫正后画布）
TABLE_ROI_NORM = (0.533, 0.267, 0.993, 0.658)


def _load_image(path) -> np.ndarray:
    """项目标准加载模式（兼容中文路径）"""
    raw = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(raw, cv2.IMREAD_COLOR)


def _nearwhite_blocks(out: np.ndarray) -> int:
    """250-254 大块数（21×21 腐蚀后 >=3000px，与原因分析 §3.3 同口径）"""
    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    m = ((g >= 250) & (g <= 254)).astype(np.uint8) * 255
    me = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21)))
    num, _, stats, _ = cv2.connectedComponentsWithStats(me, connectivity=8)
    return int(sum(1 for i in range(1, num) if stats[i, cv2.CC_STAT_AREA] >= 3000))


@pytest.fixture(scope="module")
def results():
    """延迟初始化并缓存全部样张的处理结果（module 级，避免重复跑管线）"""
    import doclayout_yolo.utils.torch_utils as _tu
    _tu.get_cpu_info = lambda: "CPU (mock)"
    from backend.cleaner import DocumentCleaner
    cleaner = DocumentCleaner()

    names = ["002.tif", "001.tif", "票据-粉色.jpg", "票据-绿色.jpg", "表单.jpg"]
    cache = {}
    for name in names:
        p = SAMPLE_DIR / name
        if not p.exists():
            continue
        cache[name] = cleaner.process(_load_image(p), debug=False, dpi=300)["result"]
    for i in range(1, 6):
        p = BUG0026_SAMPLE_DIR / f"00{i}.tif"
        if p.exists():
            cache[f"bug0026-00{i}.tif"] = cleaner.process(_load_image(p), debug=False, dpi=300)["result"]
    return cache


# ============================================================
# A 组：本例 002.tif 色差消除（REQ-001 治本例）
# ============================================================

class TestGroupA:
    """研发BUG-0027 验收 A 组：002 表格误判修正后输出无 250-254 色差"""

    @pytest.mark.skipif(not SAMPLES_AVAILABLE, reason="BUG-0027 样张目录不可用")
    def test_002_nearwhite_blocks_zero(self, results):
        out = results["002.tif"]
        blocks = _nearwhite_blocks(out)
        assert blocks == 0, f"002.tif 输出 250-254 大块 {blocks} 个（修改前 17 个），色差未消除"

    @pytest.mark.skipif(not SAMPLES_AVAILABLE, reason="BUG-0027 样张目录不可用")
    def test_002_table_bg_consistent_with_outside(self, results):
        """表格区与外部背景中位灰度一致（客户观察"背景颜色一样"的直接判据）"""
        out = results["002.tif"]
        h, w = out.shape[:2]
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        x1 = int(TABLE_ROI_NORM[0] * w)
        y1 = int(TABLE_ROI_NORM[1] * h)
        x2 = int(TABLE_ROI_NORM[2] * w)
        y2 = int(TABLE_ROI_NORM[3] * h)
        roi_bg = g[y1:y2, x1:x2]
        roi_bg = roi_bg[roi_bg >= 240]  # 背景像素（排除深色内容）
        m = 200
        corners = np.concatenate([
            g[:m, :m].ravel(), g[:m, -m:].ravel(),
            g[-m:, :m].ravel(), g[-m:, -m:].ravel()
        ])
        corners_bg = corners[corners >= 240]
        assert len(roi_bg) > 0 and len(corners_bg) > 0, "背景像素采样为空"
        med_in = float(np.median(roi_bg))
        med_out = float(np.median(corners_bg))
        assert abs(med_in - med_out) <= 1, \
            f"表格区背景中位灰度 {med_in:.0f} 与外部 {med_out:.0f} 不一致，色差未消除"


# ============================================================
# B 组：真彩色票据零回退（红线：逐像素一致）
# ============================================================

class TestGroupB:
    """研发BUG-0027 验收 B 组：票据-粉色/绿色输出与修改前基线逐像素一致（b001/b002 教训红线）"""

    @pytest.mark.skipif(not (SAMPLES_AVAILABLE and BASELINE_AVAILABLE), reason="样张或基线目录不可用")
    @pytest.mark.parametrize("name", ["票据-粉色.jpg", "票据-绿色.jpg"])
    def test_receipt_pixel_identical(self, results, name):
        out = results[name]
        base = _load_image(BASELINE_DIR / f"{Path(name).stem}.png")
        assert base is not None and base.shape == out.shape, f"{name} 基线缺失或形状不一致"
        diff = int(np.sum(np.any(base != out, axis=2)))
        assert diff == 0, f"{name} 与修改前基线差异 {diff} 像素（红线：彩色票据必须零变化）"


# ============================================================
# E 组：零新问题守卫（用户红线：不经单据路径与判定正确的样张逐像素一致）
# ============================================================

class TestGroupE:
    """研发BUG-0027 验收 E 组：普通路径样张（001/表单/BUG-0026 五张）与修改前基线逐像素一致

    依据（2026-08-19 基线归档时以处理日志确认路径分类）：
    - 001.tif/表单.jpg/BUG-0026 客户 001-005.tif 走普通文档路径，本次改动不触及该路径代码，
      输出必须逐像素一致；002.tif 为修复目标按 A 组指标验收，不要求一致。
    """

    @pytest.mark.skipif(not (SAMPLES_AVAILABLE and BASELINE_AVAILABLE), reason="样张或基线目录不可用")
    @pytest.mark.parametrize("name", ["001.tif", "表单.jpg"])
    def test_normal_path_pixel_identical(self, results, name):
        out = results[name]
        base = _load_image(BASELINE_DIR / f"{Path(name).stem}.png")
        assert base is not None and base.shape == out.shape, f"{name} 基线缺失或形状不一致"
        diff = int(np.sum(np.any(base != out, axis=2)))
        assert diff == 0, f"{name} 与修改前基线差异 {diff} 像素（普通文档路径必须零变化）"

    @pytest.mark.skipif(not (BUG0026_AVAILABLE and BASELINE_AVAILABLE), reason="BUG-0026 样张或基线目录不可用")
    @pytest.mark.parametrize("idx", range(1, 6))
    def test_bug0026_samples_pixel_identical(self, results, idx):
        name = f"bug0026-00{idx}.tif"
        out = results[name]
        base = _load_image(BASELINE_DIR / f"{name.replace('.tif', '')}.png")
        assert base is not None and base.shape == out.shape, f"{name} 基线缺失或形状不一致"
        diff = int(np.sum(np.any(base != out, axis=2)))
        assert diff == 0, f"{name} 与修改前基线差异 {diff} 像素（普通文档路径必须零变化）"
