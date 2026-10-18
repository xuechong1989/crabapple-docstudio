# -*- coding: utf-8 -*-
# xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景 验收测试
"""研发BUG-0026 验收测试：A组客户样张净化恢复 / B组图纸不回退 / C组回归

运行方式：
    python -m pytest tests/test_bug0026_gray_blocks.py -v --tb=short

环境变量覆盖（换机器/CI 时无需改代码）：
    BUG0026_SAMPLE_DIR  样张目录（默认 tests/samples/2026-08-14，001-005.tif）
    BUG0026_OLD002      老 002 图纸样张路径（默认 tests/samples/002-扫描件-1663x2395.tif）

3.0.3 基线常量来源：研发BUG-0026 工作目录 诊断输出\\3.0.03\\指标汇总.json（官方 3.0.3 包实测）。
"""
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SAMPLE_DIR = Path(os.environ.get(
    "BUG0026_SAMPLE_DIR",
    "tests/samples/2026-08-14",
))
OLD002_PATH = Path(os.environ.get(
    "BUG0026_OLD002",
    "tests/samples/002-扫描件-1663x2395.tif",
))

SAMPLES_AVAILABLE = (SAMPLE_DIR / "001.tif").exists()
OLD002_AVAILABLE = OLD002_PATH.exists()

# 3.0.3 实测基线（研发BUG-0026 诊断输出\3.0.03\指标汇总.json，2026-08-18）
# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能 002.tif 基线重标定
# 研发需求-0139 整页灰雾门控（REQ-010）后 002.tif 灰底清除更净，实测 gray 2.41→2.05、dark 8.31→8.00
# （dark 项此前因测试在 gray 断言处先失败而未暴露）；A/B 目检新旧产物（研发需求-0141 工作目录
# 002tif对比产物\）：正文/红章/手写签名/表格线零丢失，灰色审查章略淡可辨，属预期改进非退化
BASELINE_303 = {
    "001.tif": {"white": 95.36, "near": 0.45, "blocks": 4, "area": 2739, "gray": 0.86, "dark": 3.33},
    # zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
    # 002.tif 仅重标定 gray/dark 两项（white/near/blocks/area 保留 3.0.3 基线，继续作防退化护栏）
    "002.tif": {"white": 88.61, "near": 0.66, "blocks": 12, "area": 8967, "gray": 2.05, "dark": 8.00},
    "003.tif": {"white": 88.66, "near": 0.95, "blocks": 1, "area": 721, "gray": 2.16, "dark": 8.23},
    "004.tif": {"white": 89.40, "near": 0.84, "blocks": 1, "area": 681, "gray": 2.11, "dark": 7.66},
    "005.tif": {"white": 92.64, "near": 0.66, "blocks": 2, "area": 1134, "gray": 1.46, "dark": 5.23},
}
# B 组 v3.1.04 实测基线（老002，2026-08-18 当前代码 + ENABLE_GRAY_CLUSTER_L15=True 实测）
# xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景
# 判据为"与 v3.1.04 持平（不劣化）"而非 3.0.3 基线：v0.17（2026-08-07）引入的灰色保护区
# 中值滤波会把 L1 内 210-240 纹理提亮到 240-250 段（既有行为，3.0.3 无此步骤故其 82.2%
# 保留率对含 v0.17 步骤的任何版本不可达，v3.1.04 自身实测 59.2%）；本BUG 要求图纸保护不退化
# xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
# 纸面灰雾漂白开启时（产品决策，见 config.EDGE_LIGHTLEAK_WASH_ENABLE 注释），雾档
# 参数为用户文档（电力整改意见书，字缝雾与图纸填充顶部像素特征无差别）放宽：
# MIN_AREA 2500→800、CLEARANCE 12→6、FRAGMENT 1500→400、TEXTURE_MAX→0.20，
# 实测图纸保留率 59.4→58.8（-0.4pp，雾档清掉填充的浅色顶部）。保留率下界随漂白
# 开关条件化；灾难性保护失效仍由 L1 刷白上限与纯白比两道断言守卫
OLD002_RETENTION_BASE = 59.2   # 漂白关闭时口径   # 全图 190-240 保留率下界（v3.1.04 实测）
OLD002_L1_WHITEN_BASE = 10.36  # L1 区域刷白比例（v3.1.04 实测 21,739/209,919）
# xuechong 2026-10-11 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
# 纸面灰雾漂白（EDGE_LIGHTLEAK_WASH_ENABLE，产品默认开）有意清掉 L1 宽口径带内
# 236~252 的纸面灰雾：封面灰雾与图纸浅灰填充像素特征无差别（八类判据实测全部重叠），
# 本系统服务对象为电力工程文档（无图纸灰填充），按用户验收标准"背景必须完全干净"
# 取舍为清。L1 刷白上界放宽 48%；灰矩形本体保留仍由 RETENTION_BASE（59.2%）与
# 纯白比（<98%）两道断言守卫。误漂图纸时置 EDGE_LIGHTLEAK_WASH_ENABLE=False，
# 本断言随漂白关闭自然回到 10.36+1.6 口径。
OLD002_L1_WHITEN_WASH_ALLOW = 48.0  # 漂白开启时的 L1 刷白上界（2026-10-11 实测 47.24%）
OLD002_RETENTION_WASH = 58.5   # 漂白开启时的保留率下界（2026-10-11 实测 58.8）
OLD002_INPUT_GRAY = 247159


def _load_image(path) -> np.ndarray:
    """项目标准加载模式（兼容中文路径，与 test_req012_quantitative.py 一致）"""
    raw = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(raw, cv2.IMREAD_COLOR)


def _gray_metrics(img: np.ndarray) -> dict:
    """灰度指标（口径与研发BUG-0026 复现脚本一致）"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    total = g.size
    m = ((g >= 190) & (g <= 250)).astype(np.uint8) * 255
    num, _, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = areas[areas >= 500]
    return {
        "white": 100.0 * (g > 250).sum() / total,
        "near": 100.0 * ((g > 240) & (g <= 250)).sum() / total,
        "gray": 100.0 * ((g >= 190) & (g <= 240)).sum() / total,
        "dark": 100.0 * (g < 190).sum() / total,
        "blocks": int(len(big)),
        "area": int(big.sum()),
    }


@pytest.fixture(scope="module")
def cleaner_instance():
    """延迟初始化 cleaner 实例（与 test_req012_quantitative.py 相同的 CPU 信息 mock）"""
    import doclayout_yolo.utils.torch_utils as _tu
    _tu.get_cpu_info = lambda: "CPU (mock)"
    from backend.cleaner import DocumentCleaner
    return DocumentCleaner()


# ============================================================
# A 组：客户样张净化恢复（5 张，对照 3.0.3 实测基线）
# ============================================================

class TestGroupA:
    """研发BUG-0026 验收 A 组：L1.5 关闭后净化干净度恢复 3.0.3 水平且内容不损"""

    @pytest.mark.skipif(not SAMPLES_AVAILABLE, reason="客户样张目录不可用")
    @pytest.mark.parametrize("name", sorted(BASELINE_303.keys()))
    def test_metrics_vs_303_baseline(self, cleaner_instance, name):
        img = _load_image(SAMPLE_DIR / name)
        result = cleaner_instance.process(img, debug=False, dpi=300)
        got = _gray_metrics(result["result"])
        base = BASELINE_303[name]
        # 纯白：可更白不可更脏（下界 3.0.3-0.5pp）
        assert got["white"] >= base["white"] - 0.5, \
            f"{name} 纯白 {got['white']:.2f} < 基线-0.5pp（{base['white'] - 0.5:.2f}）"
        # 近白残留：上界 3.0.3+0.3pp
        assert got["near"] <= base["near"] + 0.3, \
            f"{name} 近白 {got['near']:.2f} > 基线+0.3pp（{base['near'] + 0.3:.2f}）"
        # 灰色方块数：max(×1.5, +2)（003/004 基线 1 个，纯倍率过紧加绝对容差）
        assert got["blocks"] <= max(int(base["blocks"] * 1.5), base["blocks"] + 2), \
            f"{name} 方块数 {got['blocks']} 超容差（基线 {base['blocks']}）"
        # 方块总面积：×2
        assert got["area"] <= base["area"] * 2, \
            f"{name} 方块面积 {got['area']} > 基线×2（{base['area'] * 2}）"
        # 内容保留下界：灰 190-240 与深色 <190 与 3.0.3 相差分别 ≤0.3pp / ≤0.1pp
        assert abs(got["gray"] - base["gray"]) <= 0.3, \
            f"{name} 灰190-240 {got['gray']:.2f} 偏离基线 {base['gray']:.2f} 超 0.3pp"
        assert abs(got["dark"] - base["dark"]) <= 0.1, \
            f"{name} 深色<190 {got['dark']:.2f} 偏离基线 {base['dark']:.2f} 超 0.1pp"


# ============================================================
# B 组：图纸场景不回退（老002 灰矩形样张）
# ============================================================

class TestGroupB:
    """研发BUG-0026 验收 B 组：图纸实心灰矩形由 L1/L2 保护，不受 L1.5 关闭影响"""

    @pytest.mark.skipif(not OLD002_AVAILABLE, reason="老002 图纸样张不可用")
    def test_drawing_gray_retention(self, cleaner_instance):
        img = _load_image(OLD002_PATH)
        g_in = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        in_gray = int(((g_in >= 190) & (g_in <= 240)).sum())

        # L1 口径掩码（与 core.py 一致：190-245 低饱和大面积连通域）
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lg = ((g_in >= 190) & (g_in < 245) & (hsv[:, :, 1] < 35)).astype(np.uint8) * 255
        n, labels, stats, _ = cv2.connectedComponentsWithStats(lg, connectivity=8)
        areas = stats[1:, cv2.CC_STAT_AREA]
        l1_mask = np.isin(labels, np.where(areas >= 200)[0] + 1)
        assert int(l1_mask.sum()) > 200000, "老002 L1 区域异常（预期 ≥20 万 px 灰矩形）"

        result = cleaner_instance.process(img, debug=False, dpi=300)
        g_out = cv2.cvtColor(result["result"], cv2.COLOR_BGR2GRAY)
        out_gray = int(((g_out >= 190) & (g_out <= 240)).sum())
        retention = 100.0 * out_gray / max(in_gray, 1)
        l1_whiten = 100.0 * (g_out[l1_mask] > 250).mean()
        white_ratio = 100.0 * (g_out > 250).mean()

        # 下界：不劣化 v3.1.04（实测 59.2%；v0.17 中值提亮为既有行为，3.0.3 的 82.2% 不可比）
        from backend import config as _cfg2
        _ret_floor = (OLD002_RETENTION_WASH
                      if getattr(_cfg2, 'EDGE_LIGHTLEAK_WASH_ENABLE', False)
                      else OLD002_RETENTION_BASE)
        assert retention >= _ret_floor, \
            f"全图灰度保留率 {retention:.1f}% < 下界 {_ret_floor}%"
        # 上界判别力：漂白关闭时与 v3.1.04 持平（10.36%+1.6pp）；漂白开启时按
        # BUG-0073 产品决策放宽到 OLD002_L1_WHITEN_WASH_ALLOW（见常量处注释）
        from backend import config as _cfg
        _whiten_cap = (OLD002_L1_WHITEN_WASH_ALLOW
                       if getattr(_cfg, 'EDGE_LIGHTLEAK_WASH_ENABLE', False)
                       else OLD002_L1_WHITEN_BASE + 1.6)
        assert l1_whiten <= _whiten_cap, \
            f"L1 灰矩形区域被刷白 {l1_whiten:.1f}% 超容差（上限 {_whiten_cap:.1f}%，图纸保护退化）"
        # 健全性：灰色内容未被整体刷白
        assert white_ratio < 98.0, f"输出纯白 {white_ratio:.1f}% ≥98%，灰色保护可能失效"


# ============================================================
# C 组：回归（白盒 + 性能 + 确定性 + 彩色内容 + 开关回退等价）
# ============================================================

class TestGroupC:
    """研发BUG-0026 验收 C 组"""

    @pytest.mark.skipif(not SAMPLES_AVAILABLE, reason="客户样张目录不可用")
    def test_l15_disabled_mask_zero(self, cleaner_instance):
        """L1=0 的客户样张（001.tif）灰色保护掩码应为 0（L1.5 已关闭）"""
        img = _load_image(SAMPLE_DIR / "001.tif")
        h, w = img.shape[:2]
        from backend.cleaner.cache import ImageCache, kernel_cache
        cache = ImageCache(img)
        mask = cleaner_instance._gray_protection_vectorized(cache, h, w, kernel_cache)
        assert int(np.sum(mask > 0)) == 0, \
            f"L1=0 样张掩码应为 0，实际 {int(np.sum(mask > 0))} px（L1.5 可能未关闭）"

    @pytest.mark.skipif(not SAMPLES_AVAILABLE, reason="客户样张目录不可用")
    def test_gray_protection_performance(self, cleaner_instance):
        """灰色保护阶段 ≤1s（L1.5 关闭后应更省）"""
        img = _load_image(SAMPLE_DIR / "002.tif")
        h, w = img.shape[:2]
        from backend.cleaner.cache import ImageCache, kernel_cache
        cache = ImageCache(img)
        t0 = time.time()
        cleaner_instance._gray_protection_vectorized(cache, h, w, kernel_cache)
        elapsed = time.time() - t0
        assert elapsed <= 1.0, f"灰色保护耗时 {elapsed:.2f}s > 1.0s"

    @pytest.mark.skipif(not SAMPLES_AVAILABLE, reason="客户样张目录不可用")
    def test_determinism(self, cleaner_instance):
        """同一张图两次清洁输出完全一致（REQ-010 确定性）"""
        img = _load_image(SAMPLE_DIR / "001.tif")
        r1 = cleaner_instance.process(img, debug=False, dpi=300)
        r2 = cleaner_instance.process(img, debug=False, dpi=300)
        assert np.array_equal(r1["result"], r2["result"]), "两次清洁输出不一致"

    def test_color_content_retention(self, cleaner_instance):
        """普通文档+红章+淡黄标注（彩色占比<15%）彩色像素保留率 ≥99%

        xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景
        彩色回归走普通文档真实受影响路径（散点/激进清理与 color_mask/seal_mask 交互），
        非彩色票据早退路径（恒过无意义）
        """
        img = np.full((1600, 1200, 3), 255, dtype=np.uint8)
        for i in range(12):  # 深色文字行（普通文档特征）
            cv2.putText(img, "Document Scan Test 2026", (100, 150 + i * 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (30, 30, 30), 3)
        cv2.circle(img, (880, 320), 90, (40, 40, 200), -1)          # 红章
        cv2.rectangle(img, (150, 1350), (620, 1500), (200, 225, 245), -1)  # 淡黄标注块
        cv2.putText(img, "NOTE", (200, 1440), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 60, 120), 2)

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        colored = (hsv[:, :, 1] > 40) & (hsv[:, :, 2] > 50) & (hsv[:, :, 2] < 250)
        ratio = colored.mean()
        assert ratio < 0.15, f"合成样本彩色占比 {ratio:.1%} 应 <15%（保证走普通文档路径）"

        result = cleaner_instance.process(img, debug=False, dpi=300)
        out = result["result"]
        out_hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        # 输入彩色像素在输出中变为近白（三通道均 >250）视为丢失
        erased = colored & np.all(out > 250, axis=2)
        retention = 1.0 - erased.sum() / max(colored.sum(), 1)
        assert retention >= 0.99, f"彩色像素保留率 {retention:.2%} < 99%（丢失 {int(erased.sum())} px）"

    @pytest.mark.skipif(not SAMPLES_AVAILABLE, reason="客户样张目录不可用")
    def test_switch_true_restores_l15(self, cleaner_instance):
        """ENABLE_GRAY_CLUSTER_L15=True 时 L1.5 保护恢复（逃生开关有效性，白盒口径）

        xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景
        不做全管线逐像素等价：修复含两处有意行为变更（L1.5 关闭 + 散点清理排除灰色保护区），
        开 True 时输出必然异于 v3.1.04 归档基线；开关有效性以"L1.5 掩码恢复大面积保护"验证
        """
        from backend import config as cfg
        img = _load_image(SAMPLE_DIR / "002.tif")  # 修复前 L1.5 毽子覆盖 68.8% 的样张
        h, w = img.shape[:2]
        from backend.cleaner.cache import ImageCache, kernel_cache
        cache = ImageCache(img)
        old_val = getattr(cfg, "ENABLE_GRAY_CLUSTER_L15", False)
        cfg.ENABLE_GRAY_CLUSTER_L15 = True
        try:
            mask_on = cleaner_instance._gray_protection_vectorized(cache, h, w, kernel_cache)
        finally:
            cfg.ENABLE_GRAY_CLUSTER_L15 = old_val
        mask_off = cleaner_instance._gray_protection_vectorized(cache, h, w, kernel_cache)
        ratio_on = np.sum(mask_on > 0) / (h * w)
        assert ratio_on > 0.10, f"开关 True 时 L1.5 保护未恢复（掩码仅 {ratio_on:.1%}）"
        assert np.sum(mask_off > 0) < np.sum(mask_on > 0), "开关 True/False 掩码应显著不同"
