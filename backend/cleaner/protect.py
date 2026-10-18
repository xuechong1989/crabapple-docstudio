# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
"""保护区域检测 Mixin 模块"""

import cv2
import numpy as np
from collections import defaultdict
from typing import Tuple

from backend import config as cfg
from .cache import kernel_cache, config_cache, ImageCache
from . import _log


class ProtectMixin:
    """保护区域检测功能"""

    def _detect_protected_regions(self, image: np.ndarray,
                                   low_conf_abandon_regions: list = None,
                                   debug: bool = False) -> tuple:
        """YOLO 检测保护区域；附带产出图片类(figure)框掩码供漏光净化使用"""
        h, w = image.shape[:2]
        results = self._predict(image)

        protect_mask = np.zeros((h, w), dtype=np.uint8)
        # xuechong 2026-10-10 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
        # figure框掩码：文档内的照片/图片本体，其浅色区是真实内容；
        # 纸面灰雾漂白分支尊重它，但无视title/text/table等文字类框（文字框内的纸面
        # 浅灰是背景不是内容，正是灰雾漂白要清的对象）
        figure_mask = np.zeros((h, w), dtype=np.uint8)
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 vis 拷贝条件化：仅 debug 时拷贝，生产零开销
        vis = image.copy() if debug else None

        low_conf_abandon_regions = low_conf_abandon_regions or []

        for box in results[0].boxes:
            label = self.names[int(box.cls[0])]
            conf = float(box.conf[0])
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]

            if label in cfg.TEXT_LABELS:
                threshold = cfg.TEXT_PROTECT_CONF
            elif label in cfg.ABANDON_LABELS:
                threshold = cfg.ABANDON_PROTECT_CONF
            elif label in cfg.OTHER_PROTECT_LABELS:
                threshold = cfg.DEFAULT_PROTECT_CONF
            else:
                threshold = 1.0

            should_protect = conf >= threshold

            if label in cfg.ABANDON_LABELS and should_protect and low_conf_abandon_regions:
                if self._is_overlapping_with_low_conf(x1, y1, x2, y2, low_conf_abandon_regions):
                    should_protect = False
                    _log(f"  [abandon排除] 与矫正前低置信度区域重叠，不保护")

            if should_protect:
                if label in cfg.EXTEND_UP_LABELS:
                    y1_extended = max(0, y1 - cfg.EXTEND_UP_PIXELS)
                    cv2.rectangle(protect_mask, (x1, y1_extended), (x2, y2), 255, -1)
                    if vis is not None:
                        cv2.rectangle(vis, (x1, y1_extended), (x2, y1), (255, 255, 0), 2)
                else:
                    cv2.rectangle(protect_mask, (x1, y1), (x2, y2), 255, -1)
                if vis is not None:
                    cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 0, 0), 3)
                # 图片类框单独记录（与protect同置信度门槛）
                if label in getattr(cfg, 'EDGE_LIGHTLEAK_WASH_KEEP_LABELS', {'figure'}):
                    cv2.rectangle(figure_mask, (x1, y1), (x2, y2), 255, -1)
            else:
                if vis is not None:
                    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
            if vis is not None:
                cv2.putText(vis, f'{label}:{conf:.2f}', (x1, y1-5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        return protect_mask, figure_mask, vis

    def _detect_edge_columns(self, binary, protect_mask, edge_stats, w) -> np.ndarray:
        """四边推土机：检测并清除四边边缘杂质（扫描阴影/黑边）

        xuechong 2026-06-01 重写：支持多段frame_line strip检测 + 四边(上下左右)全覆盖
        核心逻辑：frame_line连续块后若有纯白间隙→边缘杂质；无间隙→文档内容→停止
        """
        h = binary.shape[0]
        edge_mask = np.zeros((h, w), dtype=np.uint8)

        edge_width = int(w * cfg.EDGE_MARGIN_RATIO)
        edge_height = int(h * cfg.EDGE_MARGIN_RATIO)
        min_line_v = int(h * 0.05)  # 纵向最小线长
        min_line_h = int(w * 0.05)  # 横向最小线长
        gap_check = getattr(cfg, 'EDGE_STRIP_GAP_CHECK', 40)
        gap_density_thr = getattr(cfg, 'EDGE_STRIP_GAP_DENSITY', 0.01)

        # zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
        # 推土机散噪标记加文字行豁免：上下边缘行内短暗段整段标记只尊重protect_mask，
        # 但protect不覆盖连字符/标点等字形伴生部件（页码"- N -"两端横条实测被清32px），
        # 与散点预处理共用 _compute_edge_text_exempt 的字高甄别豁免
        _text_exempt = self._compute_edge_text_exempt(binary, edge_height, edge_width)

        # ---- 辅助函数 ----
        def is_frame_line_v(col):
            """纵向列是否有连续长暗段"""
            if np.sum(col > 0) == 0:
                return False
            max_run = 0; cr = 0
            for p in col:
                if p > 0: cr += 1; max_run = max(max_run, cr)
                else: cr = 0
            return max_run >= min_line_v

        def is_frame_line_h(row):
            """横向行是否有连续长暗段"""
            if np.sum(row > 0) == 0:
                return False
            max_run = 0; cr = 0
            for p in row:
                if p > 0: cr += 1; max_run = max(max_run, cr)
                else: cr = 0
            return max_run >= min_line_h

        def scattered_noise_v(col):
            """列中短暗段标记"""
            result = np.zeros_like(col)
            start = -1
            for i, p in enumerate(col):
                if p > 0:
                    if start < 0: start = i
                else:
                    if start >= 0:
                        if i - start < min_line_v:
                            result[start:i] = 255
                        start = -1
            if start >= 0 and len(col) - start < min_line_v:
                result[start:] = 255
            return result

        def scattered_noise_h(row):
            """行中短暗段标记"""
            result = np.zeros_like(row)
            start = -1
            for i, p in enumerate(row):
                if p > 0:
                    if start < 0: start = i
                else:
                    if start >= 0:
                        if i - start < min_line_h:
                            result[start:i] = 255
                        start = -1
            if start >= 0 and len(row) - start < min_line_h:
                result[start:] = 255
            return result

        # ---- 左边缘 ----
        x = 0
        while x < min(edge_width, w):
            col = binary[:, x]
            if np.sum(col > 0) == 0:
                x += 1; continue
            if is_frame_line_v(col):
                # 找到frame_line strip
                strip_start = x
                while x < min(edge_width, w) and is_frame_line_v(binary[:, x]):
                    x += 1
                strip_end = x - 1
                # 检查strip后的间隙
                gs = x
                ge = min(gs + gap_check, w)
                gap_dark = sum(np.sum(binary[:, gx] > 0) for gx in range(gs, ge))
                gap_density = gap_dark / (h * max(1, ge - gs))
                if gap_density < gap_density_thr:
                    # 确认边缘杂质 → 标记整段并继续扫描
                    for sx in range(strip_start, strip_end + 1):
                        edge_mask[:, sx] = binary[:, sx]
                    x = ge  # 跳到间隙后继续
                else:
                    # 无间隙 → 文档内容 → 停止
                    break
            else:
                edge_mask[:, x] = np.where(_text_exempt[:, x], 0, scattered_noise_v(col))
                x += 1

        # ---- 右边缘 ----
        x = w - 1
        while x >= max(w - edge_width, 0):
            col = binary[:, x]
            if np.sum(col > 0) == 0:
                x -= 1; continue
            if is_frame_line_v(col):
                strip_end = x
                while x >= max(w - edge_width, 0) and is_frame_line_v(binary[:, x]):
                    x -= 1
                strip_start = x + 1
                # 检查strip前(内侧)的间隙
                gs = max(0, strip_start - gap_check)
                ge = strip_start
                gap_dark = sum(np.sum(binary[:, gx] > 0) for gx in range(gs, ge))
                gap_density = gap_dark / (h * max(1, ge - gs))
                if gap_density < gap_density_thr:
                    for sx in range(strip_start, strip_end + 1):
                        edge_mask[:, sx] = binary[:, sx]
                    x = gs - 1  # 跳到间隙前继续
                else:
                    break
            else:
                edge_mask[:, x] = np.where(_text_exempt[:, x], 0, scattered_noise_v(col))
                x -= 1

        # ---- 上边缘 ----
        y = 0
        while y < min(edge_height, h):
            row = binary[y, :]
            if np.sum(row > 0) == 0:
                y += 1; continue
            if is_frame_line_h(row):
                strip_start = y
                while y < min(edge_height, h) and is_frame_line_h(binary[y, :]):
                    y += 1
                strip_end = y - 1
                gs = y
                ge = min(gs + gap_check, h)
                gap_dark = sum(np.sum(binary[gy, :] > 0) for gy in range(gs, ge))
                gap_density = gap_dark / (w * max(1, ge - gs))
                if gap_density < gap_density_thr:
                    for sy in range(strip_start, strip_end + 1):
                        edge_mask[sy, :] = np.maximum(edge_mask[sy, :], binary[sy, :])
                    y = ge
                else:
                    break
            else:
                edge_mask[y, :] = np.maximum(edge_mask[y, :], np.where(_text_exempt[y, :], 0, scattered_noise_h(row)))
                y += 1

        # ---- 下边缘 ----
        y = h - 1
        while y >= max(h - edge_height, 0):
            row = binary[y, :]
            if np.sum(row > 0) == 0:
                y -= 1; continue
            if is_frame_line_h(row):
                strip_end = y
                while y >= max(h - edge_height, 0) and is_frame_line_h(binary[y, :]):
                    y -= 1
                strip_start = y + 1
                gs = max(0, strip_start - gap_check)
                ge = strip_start
                gap_dark = sum(np.sum(binary[gy, :] > 0) for gy in range(gs, ge))
                gap_density = gap_dark / (w * max(1, ge - gs))
                if gap_density < gap_density_thr:
                    for sy in range(strip_start, strip_end + 1):
                        edge_mask[sy, :] = np.maximum(edge_mask[sy, :], binary[sy, :])
                    y = gs - 1
                else:
                    break
            else:
                edge_mask[y, :] = np.maximum(edge_mask[y, :], np.where(_text_exempt[y, :], 0, scattered_noise_h(row)))
                y -= 1

        # ---- supplementary scan (edge_stats-based, existing logic) ----
        for side, x_counts in [('left', edge_stats['left']), ('right', edge_stats['right'])]:
            if not x_counts:
                continue
            sorted_x = sorted(x_counts.keys())
            if not sorted_x:
                continue
            groups = [[sorted_x[0]]]
            for x in sorted_x[1:]:
                if x - groups[-1][-1] <= cfg.EDGE_X_MERGE_DISTANCE:
                    groups[-1].append(x)
                else:
                    groups.append([x])
            for group in groups:
                total = sum(x_counts[x] for x in group)
                if total >= cfg.MIN_EDGE_NOISE_COUNT:
                    for x in range(min(group), max(group) + 1):
                        if 0 <= x < w:
                            col = binary[:, x]
                            if not is_frame_line_v(col):
                                edge_mask[:, x] = np.maximum(edge_mask[:, x], np.where(_text_exempt[:, x], 0, scattered_noise_v(col)))

        edge_mask[protect_mask > 0] = 0
        return edge_mask

    # xuechong 2026-06-01 边缘杂质线独立检测（5条标准）
    # zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
    # 边缘清理共用文字行豁免掩码：推土机（_detect_edge_columns，10%边缘带，行内短暗段
    # 整段标记仅尊重protect_mask，但protect不覆盖连字符/标点等字形伴生部件）与散点
    # 预处理（_detect_edge_impurity_strips，3%带，不尊重任何保护）都会把贴边孤立成行
    # 小字（页码"- N -"/网址行）当杂质刷白。统一甄别：带内连通域字高≥
    # EDGE_SCATTER_TEXT_MIN_H 且宽≥3px判为文字，膨胀（横向6倍字高）覆盖同行邻近
    # 小字符后返回豁免掩码；真散点颗粒(1~5px)与细线(宽<3px)不在豁免之列
    def _compute_edge_text_exempt(self, binary: np.ndarray, margin_v: int, margin_h: int) -> np.ndarray:
        """计算边缘清理带的文字行豁免掩码（True=豁免不清）"""
        h, w = binary.shape[:2]
        _text_min_h = self._scale_r(getattr(cfg, 'EDGE_SCATTER_TEXT_MIN_H', 10))
        _band = np.zeros((h, w), dtype=np.uint8)
        _band[:margin_v, :] = 1
        _band[h - margin_v:, :] = 1
        _band[:, :margin_h] = 1
        _band[:, w - margin_h:] = 1
        # zhaoqiaotong 2026-09-18 研发BUG-0060 追加：连通域改在全图binary上做、按
        # "与清理带相交"筛选——带内切割会把斜跨带界的字形（测试_p6"6"仅下部8px入带）
        # 截断成矮组件（8px<10px阈值）误判散点，叠加应用膨胀致字形下部整块被擦
        _n_st, _labels_st, _stats_st, _ = cv2.connectedComponentsWithStats(
            (binary > 0).astype(np.uint8) * 255, connectivity=8)
        _in_band_ids = np.unique(_labels_st[_band > 0])
        _in_band_ids = _in_band_ids[_in_band_ids > 0]
        if not _in_band_ids.size:
            return np.zeros((h, w), dtype=bool)
        _glyph_ids = np.array([_ci for _ci in _in_band_ids
                               if _stats_st[_ci, cv2.CC_STAT_HEIGHT] >= _text_min_h
                               and _stats_st[_ci, cv2.CC_STAT_WIDTH] >= 3], dtype=np.int64)
        if not _glyph_ids.size:
            return np.zeros((h, w), dtype=bool)
        _glyph = np.isin(_labels_st, _glyph_ids).astype(np.uint8) * 255
        # 膨胀核横向加宽（8倍字高）：页码"- N -"连字符(高2~4px不达字高判据)靠字形
        # 成员横向膨胀带豁免；实测"1"的glyph是4px宽竖笔画、到左连字符外缘34px，
        # 6倍字高(半径30px)差4px压线漏半截，8倍(半径40px)覆盖词组内最大部件间距
        _exempt_kernel = kernel_cache.get_rect(_text_min_h * 8 + 1, _text_min_h * 2 + 1)
        return cv2.dilate(_glyph, _exempt_kernel) > 0

    def _detect_edge_impurity_strips(self, image: np.ndarray, cache: 'ImageCache',
                                      is_receipt: bool, is_color_receipt: bool) -> np.ndarray:
        """检测并标记紧贴图片四边的黑色杂质线。

        5条标准（全部满足才标记）：
        1. 非票据图片（票据路径有自己的边缘处理）
        2. 紧贴绝对边缘（起始于 x<5 或 y<5）
        3. 连续但不太长（MIN_RUN <= 连续暗段 <= MAX_RUN）
        4. 周围有空白间隙（暗段结束后 GAP_CHECK 内暗密度 < GAP_DENSITY）
        5. 黑色非印章（灰度 < BLACK_THRESHOLD 且 饱和度 < SEAL_S_THRESHOLD）

        四边对称处理：左右扫描列，上下扫描行。
        返回 impurity_mask，由调用方独立应用（不经过 protect_mask 清除）。
        """
        if not getattr(cfg, 'ENABLE_EDGE_IMPURITY_DETECT', True):
            return np.zeros((cache.h, cache.w), dtype=np.uint8)

        # 标准1：仅普通文档执行
        if is_receipt or is_color_receipt:
            return np.zeros((cache.h, cache.w), dtype=np.uint8)

        h, w = cache.h, cache.w
        binary = cache.get_binary()
        gray = cache.gray
        hue, saturation, value = cache.get_hsv_channels()
        mask = np.zeros((h, w), dtype=np.uint8)

        # 配置
        black_thr = getattr(cfg, 'EDGE_IMPURITY_BLACK_THRESHOLD', 80)
        min_run = getattr(cfg, 'EDGE_IMPURITY_MIN_RUN', 40)
        max_run_ratio = getattr(cfg, 'EDGE_IMPURITY_MAX_RUN_RATIO', 0.25)
        max_strip_w = getattr(cfg, 'EDGE_IMPURITY_MAX_STRIP_WIDTH', 60)
        gap_check = getattr(cfg, 'EDGE_IMPURITY_GAP_CHECK', 40)
        gap_density_thr = getattr(cfg, 'EDGE_IMPURITY_GAP_DENSITY', 0.01)
        seal_s_thr = getattr(cfg, 'EDGE_IMPURITY_SEAL_S_THRESHOLD', 30)
        max_run_v = int(h * max_run_ratio)  # 纵向最大连续暗段
        max_run_h = int(w * max_run_ratio)  # 横向最大连续暗段
        edge_margin = 5  # 标准2：绝对边缘容差

        # 使用 binary（灰度<200）做连续性检测，与管线其他部分统一
        # 然后通过饱和度验证排除印章（标准5）

        # ---- 预处理：清除四边边缘的散点杂质（不满足连续段但紧贴边缘的稀疏暗像素） ----
        scattered_margin_v = int(h * 0.03)  # 上下边缘散点检测范围(3%图高)
        scattered_margin_h = int(w * 0.03)  # 左右边缘散点检测范围(3%图宽)
        max_scattered_density = 0.10  # 密度<10%视为散点杂质

        # zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
        # 散点文字行豁免：贴边孤立成行小字（页码"- N -"/网址/地址行）整行暗密度<10%，
        # 与扫描散点同判据会被整行刷白且不受protect_mask约束（实测PDF页码保留率14~27%、
        # 002.tif www行清除97%）。文字行豁免掩码与推土机共用 _compute_edge_text_exempt
        _text_exempt = self._compute_edge_text_exempt(binary, scattered_margin_v, scattered_margin_h)
        # 左
        for sx in range(min(scattered_margin_h, w)):
            col_dark = np.sum(binary[:, sx] > 0)
            if 0 < col_dark / h < max_scattered_density:
                mask[:, sx] = np.where(_text_exempt[:, sx], 0, binary[:, sx])
        # 右
        for sx in range(w - 1, max(w - scattered_margin_h - 1, 0), -1):
            col_dark = np.sum(binary[:, sx] > 0)
            if 0 < col_dark / h < max_scattered_density:
                mask[:, sx] = np.where(_text_exempt[:, sx], 0, binary[:, sx])
        # 上
        for sy in range(min(scattered_margin_v, h)):
            row_dark = np.sum(binary[sy, :] > 0)
            if 0 < row_dark / w < max_scattered_density:
                mask[sy, :] = np.maximum(mask[sy, :], np.where(_text_exempt[sy, :], 0, binary[sy, :]))
        # 下
        for sy in range(h - 1, max(h - scattered_margin_v - 1, 0), -1):
            row_dark = np.sum(binary[sy, :] > 0)
            if 0 < row_dark / w < max_scattered_density:
                mask[sy, :] = np.maximum(mask[sy, :], np.where(_text_exempt[sy, :], 0, binary[sy, :]))

        # ---- 辅助：找列/行中连续暗段(binary)的最长长度 ----
        def dark_max_run_col(x):
            col = binary[:, x]
            max_r = 0; cr = 0
            for p in col:
                if p > 0: cr += 1; max_r = max(max_r, cr)
                else: cr = 0
            return max_r

        def dark_max_run_row(y):
            row = binary[y, :]
            max_r = 0; cr = 0
            for p in row:
                if p > 0: cr += 1; max_r = max(max_r, cr)
                else: cr = 0
            return max_r

        # ---- 左边缘 ----
        x = 0
        while x < min(max_strip_w + edge_margin, w):
            run_len = dark_max_run_col(x)
            if run_len >= min_run and run_len <= max_run_v:
                strip_start = x
                # 收集整个strip中所有列的行范围（用于饱和度验证）
                all_dark_rows = []
                tx = x
                while tx < min(max_strip_w + edge_margin, w) and dark_max_run_col(tx) >= min_run:
                    dr = np.where(binary[:, tx] > 0)[0]
                    if len(dr) > 0:
                        all_dark_rows.append((dr[0], dr[-1]))
                    tx += 1
                strip_end = tx - 1
                x = tx
                strip_width = strip_end - strip_start + 1
                if strip_start > edge_margin:
                    break
                # 标准5：黑色非印章（检查整个strip合并行范围的平均饱和度）
                if all_dark_rows:
                    rs = min(r[0] for r in all_dark_rows)
                    re = max(r[1] for r in all_dark_rows) + 1
                    strip_sat = saturation[rs:re, strip_start:strip_end+1]
                    if strip_sat.size > 0 and np.sum(strip_sat > seal_s_thr) / strip_sat.size >= 0.15:
                        break
                # 标准4：间隙检测
                gs = strip_end + 1
                ge = min(gs + gap_check, w)
                gap_dark = sum(np.sum(binary[:, gx] > 0) for gx in range(gs, ge))
                gap_density = gap_dark / (h * max(1, ge - gs))
                if gap_density < gap_density_thr and strip_width <= max_strip_w:
                    for sx in range(strip_start, strip_end + 1):
                        mask[:, sx] = binary[:, sx]
                    x = ge
                    continue
                break
            elif run_len > max_run_v:
                break
            x += 1

        # ---- 右边缘 ----
        x = w - 1
        while x >= max(w - max_strip_w - edge_margin, 0):
            run_len = dark_max_run_col(x)
            if run_len >= min_run and run_len <= max_run_v:
                strip_end = x
                all_dark_rows = []
                tx = x
                while tx >= max(w - max_strip_w - edge_margin, 0) and dark_max_run_col(tx) >= min_run:
                    dr = np.where(binary[:, tx] > 0)[0]
                    if len(dr) > 0:
                        all_dark_rows.append((dr[0], dr[-1]))
                    tx -= 1
                strip_start = tx + 1
                x = tx
                strip_width = strip_end - strip_start + 1
                if strip_end < w - 1 - edge_margin:
                    break
                if all_dark_rows:
                    rs = min(r[0] for r in all_dark_rows)
                    re = max(r[1] for r in all_dark_rows) + 1
                    strip_sat = saturation[rs:re, strip_start:strip_end+1]
                    if strip_sat.size > 0 and np.sum(strip_sat > seal_s_thr) / strip_sat.size >= 0.15:
                        break
                gs = max(0, strip_start - gap_check)
                ge = strip_start
                gap_dark = sum(np.sum(binary[:, gx] > 0) for gx in range(gs, ge))
                gap_density = gap_dark / (h * max(1, ge - gs))
                if gap_density < gap_density_thr and strip_width <= max_strip_w:
                    for sx in range(strip_start, strip_end + 1):
                        mask[:, sx] = binary[:, sx]
                    x = gs - 1
                    continue
                break
            elif run_len > max_run_v:
                break
            x -= 1

        # ---- 上边缘 ----
        y = 0
        while y < min(max_strip_w + edge_margin, h):
            run_len = dark_max_run_row(y)
            if run_len >= min_run and run_len <= max_run_h:
                strip_start = y
                all_dark_cols = []
                ty = y
                while ty < min(max_strip_w + edge_margin, h) and dark_max_run_row(ty) >= min_run:
                    dc = np.where(binary[ty, :] > 0)[0]
                    if len(dc) > 0:
                        all_dark_cols.append((dc[0], dc[-1]))
                    ty += 1
                strip_end = ty - 1
                y = ty
                strip_height = strip_end - strip_start + 1
                if strip_start > edge_margin:
                    break
                if all_dark_cols:
                    cs = min(c[0] for c in all_dark_cols)
                    ce = max(c[1] for c in all_dark_cols) + 1
                    strip_sat = saturation[strip_start:strip_end+1, cs:ce]
                    if strip_sat.size > 0 and np.sum(strip_sat > seal_s_thr) / strip_sat.size >= 0.15:
                        break
                gs = strip_end + 1
                ge = min(gs + gap_check, h)
                gap_dark = sum(np.sum(binary[gy, :] > 0) for gy in range(gs, ge))
                gap_density = gap_dark / (w * max(1, ge - gs))
                if gap_density < gap_density_thr and strip_height <= max_strip_w:
                    for sy in range(strip_start, strip_end + 1):
                        mask[sy, :] = np.maximum(mask[sy, :], binary[sy, :])
                    y = ge
                    continue
                break
            elif run_len > max_run_h:
                break
            y += 1

        # ---- 下边缘 ----
        y = h - 1
        while y >= max(h - max_strip_w - edge_margin, 0):
            run_len = dark_max_run_row(y)
            if run_len >= min_run and run_len <= max_run_h:
                strip_end = y
                all_dark_cols = []
                ty = y
                while ty >= max(h - max_strip_w - edge_margin, 0) and dark_max_run_row(ty) >= min_run:
                    dc = np.where(binary[ty, :] > 0)[0]
                    if len(dc) > 0:
                        all_dark_cols.append((dc[0], dc[-1]))
                    ty -= 1
                strip_start = ty + 1
                y = ty
                strip_height = strip_end - strip_start + 1
                if strip_end < h - 1 - edge_margin:
                    break
                if all_dark_cols:
                    cs = min(c[0] for c in all_dark_cols)
                    ce = max(c[1] for c in all_dark_cols) + 1
                    strip_sat = saturation[strip_start:strip_end+1, cs:ce]
                    if strip_sat.size > 0 and np.sum(strip_sat > seal_s_thr) / strip_sat.size >= 0.15:
                        break
                gs = max(0, strip_start - gap_check)
                ge = strip_start
                gap_dark = sum(np.sum(binary[gy, :] > 0) for gy in range(gs, ge))
                gap_density = gap_dark / (w * max(1, ge - gs))
                if gap_density < gap_density_thr and strip_height <= max_strip_w:
                    for sy in range(strip_start, strip_end + 1):
                        mask[sy, :] = np.maximum(mask[sy, :], binary[sy, :])
                    y = gs - 1
                    continue
                break
            elif run_len > max_run_h:
                break
            y -= 1

        return mask

    def _detect_seals_and_colors(self, cache: ImageCache) -> Tuple[np.ndarray, np.ndarray]:
        """
        公章和彩色区域检测（优化版，使用缓存）
        使用 kernel_cache 和 config_cache 进一步优化
        """
        h, w = cache.h, cache.w
        
        seal_mask = np.zeros((h, w), dtype=np.uint8)
        color_mask = np.zeros((h, w), dtype=np.uint8)
        
        # 使用缓存的 HSV 通道（避免重复切片）
        hue, saturation, value = cache.get_hsv_channels()
        hsv = cache.hsv
        
        # 红色公章检测
        if cfg.ENABLE_SEAL_PROTECTION:
            mask1 = cv2.inRange(hsv, 
                np.array([cfg.SEAL_RED_H1_LOW, cfg.SEAL_S_LOW, cfg.SEAL_V_LOW]),
                np.array([cfg.SEAL_RED_H1_HIGH, 255, 255]))
            mask2 = cv2.inRange(hsv,
                np.array([cfg.SEAL_RED_H2_LOW, cfg.SEAL_S_LOW, cfg.SEAL_V_LOW]),
                np.array([cfg.SEAL_RED_H2_HIGH, 255, 255]))
            seal_mask = cv2.bitwise_or(mask1, mask2)
            
            # 使用 kernel 缓存
            kernel = kernel_cache.get_ones(cfg.SEAL_DILATE_KERNEL_SIZE)
            seal_mask = cv2.dilate(seal_mask, kernel, iterations=cfg.SEAL_DILATE_ITERATIONS)
        
        # 彩色区域检测（使用配置缓存，默认启用以保护彩色单据）
        if config_cache.get('ENABLE_COLOR_PROTECTION', True):
            v_min = config_cache.get('COLOR_VALUE_MIN', 30)
            v_max = config_cache.get('COLOR_VALUE_MAX', 250)
            s_threshold = config_cache.get('COLOR_SATURATION_THRESHOLD', 30)
            
            # 检查是否启用全色域保护（保护所有彩色区域，适用于各种颜色的单据）
            if config_cache.get('ENABLE_FULL_COLOR_PROTECTION', True):
                # 全色域保护：保护所有有饱和度的彩色区域
                full_s_threshold = config_cache.get('FULL_COLOR_SATURATION_THRESHOLD', 20)
                color_mask = ((saturation > full_s_threshold) & (value > v_min) & (value < v_max)).astype(np.uint8) * 255
                _log(f"  [彩色保护] 全色域保护模式，饱和度阈值: {full_s_threshold}")
            else:
                # 特定颜色保护模式（原有逻辑）
                # 黄色
                yellow_h_low = config_cache.get('YELLOW_H_LOW', 15)
                yellow_h_high = config_cache.get('YELLOW_H_HIGH', 50)
                yellow_mask = (hue >= yellow_h_low) & (hue <= yellow_h_high) & \
                              (saturation > s_threshold) & (value > v_min) & (value < v_max)
                
                # 粉色
                pink_s_threshold = config_cache.get('PINK_S_THRESHOLD', 20)
                pink_h_low1 = config_cache.get('PINK_H_LOW1', 140)
                pink_h_high1 = config_cache.get('PINK_H_HIGH1', 180)
                pink_h_low2 = config_cache.get('PINK_H_LOW2', 0)
                pink_h_high2 = config_cache.get('PINK_H_HIGH2', 10)
                
                pink_mask = (((hue >= pink_h_low1) & (hue <= pink_h_high1)) | \
                             ((hue >= pink_h_low2) & (hue <= pink_h_high2))) & \
                            (saturation > pink_s_threshold) & (value > v_min) & (value < v_max)
                
                # 蓝青色
                blue_cyan_h_low = config_cache.get('BLUE_CYAN_H_LOW', 80)
                blue_cyan_h_high = config_cache.get('BLUE_CYAN_H_HIGH', 130)
                blue_cyan_s_threshold = config_cache.get('BLUE_CYAN_S_THRESHOLD', 25)
                blue_cyan_v_min = config_cache.get('BLUE_CYAN_V_MIN', 50)
                blue_cyan_v_max = config_cache.get('BLUE_CYAN_V_MAX', 250)
                
                blue_cyan_mask = (hue >= blue_cyan_h_low) & (hue <= blue_cyan_h_high) & \
                                 (saturation > blue_cyan_s_threshold) & \
                                 (value > blue_cyan_v_min) & (value < blue_cyan_v_max)
                
                # 绿色
                green_h_low = config_cache.get('GREEN_H_LOW', 35)
                green_h_high = config_cache.get('GREEN_H_HIGH', 85)
                green_s_threshold = config_cache.get('GREEN_S_THRESHOLD', 25)
                green_mask = (hue >= green_h_low) & (hue <= green_h_high) & \
                             (saturation > green_s_threshold) & (value > v_min) & (value < v_max)
                
                # 橙色
                orange_h_low = config_cache.get('ORANGE_H_LOW', 5)
                orange_h_high = config_cache.get('ORANGE_H_HIGH', 25)
                orange_s_threshold = config_cache.get('ORANGE_S_THRESHOLD', 30)
                orange_mask = (hue >= orange_h_low) & (hue <= orange_h_high) & \
                              (saturation > orange_s_threshold) & (value > v_min) & (value < v_max)
                
                # 紫色
                purple_h_low = config_cache.get('PURPLE_H_LOW', 125)
                purple_h_high = config_cache.get('PURPLE_H_HIGH', 160)
                purple_s_threshold = config_cache.get('PURPLE_S_THRESHOLD', 20)
                purple_mask = (hue >= purple_h_low) & (hue <= purple_h_high) & \
                              (saturation > purple_s_threshold) & (value > v_min) & (value < v_max)
                
                # 合并所有颜色掩码
                color_mask = (yellow_mask | pink_mask | blue_cyan_mask | green_mask | orange_mask | purple_mask).astype(np.uint8) * 255
            
            if np.sum(color_mask > 0) > 0:
                kernel = kernel_cache.get_ones(cfg.COLOR_DILATE_KERNEL_SIZE)
                color_mask = cv2.dilate(color_mask, kernel, iterations=cfg.COLOR_DILATE_ITERATIONS)
                _log(f"  [彩色保护] 检测到 {np.sum(color_mask > 0)} 像素")
        
        return seal_mask, color_mask

    def _detect_dotlines(self, binary: np.ndarray, protect_mask: np.ndarray,
                                    num_labels: int, labels: np.ndarray, 
                                    stats: np.ndarray, centroids: np.ndarray) -> np.ndarray:
        """目录虚线检测（优化版，使用 kernel 缓存）"""
        h, w = binary.shape
        dotline_mask = np.zeros((h, w), dtype=np.uint8)

        dot_candidates = []
        for i in range(1, num_labels):
            x, y, bw, bh, area = stats[i]
            cx, cy = centroids[i]

            if int(cy) < h and int(cx) < w and protect_mask[int(cy), int(cx)] > 0:
                continue

            if (bw <= cfg.DOTLINE_MAX_SIZE and bh <= cfg.DOTLINE_MAX_SIZE
                and area <= cfg.DOTLINE_MAX_AREA and area > 0):
                dot_candidates.append({
                    'id': i, 'x': x, 'y': y, 'cx': cx, 'cy': cy,
                    'w': bw, 'h': bh, 'area': area
                })

        dot_candidates.sort(key=lambda d: d['cy'])
        rows = []
        current_row = []

        for dot in dot_candidates:
            if not current_row:
                current_row.append(dot)
            elif abs(dot['cy'] - current_row[-1]['cy']) <= cfg.DOTLINE_Y_TOLERANCE:
                current_row.append(dot)
            else:
                if len(current_row) >= cfg.DOTLINE_MIN_COUNT:
                    rows.append(current_row)
                current_row = [dot]
        if len(current_row) >= cfg.DOTLINE_MIN_COUNT:
            rows.append(current_row)

        for row in rows:
            row.sort(key=lambda d: d['cx'])
            gaps = []
            for i in range(1, len(row)):
                gap = row[i]['cx'] - row[i-1]['cx']
                gaps.append(gap)

            valid_gaps = [g for g in gaps if cfg.DOTLINE_MIN_GAP <= g <= cfg.DOTLINE_MAX_GAP]

            if len(valid_gaps) >= cfg.DOTLINE_MIN_COUNT - 1:
                for dot in row:
                    dotline_mask[labels == dot['id']] = 255

        # 使用 kernel 缓存
        kernel = kernel_cache.get_ellipse_wh(self._scale_r(cfg.MORPH_ELLIPSE_WIDTH), self._scale_r(cfg.MORPH_ELLIPSE_HEIGHT))
        dotline_mask = cv2.dilate(dotline_mask, kernel)

        return dotline_mask

    def _detect_lines(self, binary: np.ndarray, protect_mask: np.ndarray,
                                 num_labels: int, labels: np.ndarray,
                                 stats: np.ndarray, centroids: np.ndarray) -> np.ndarray:
        """图纸线条检测（优化版，使用 kernel 缓存）"""
        h, w = binary.shape
        line_mask = np.zeros((h, w), dtype=np.uint8)

        for i in range(1, num_labels):
            x, y, bw, bh, area = stats[i]
            cx, cy = int(centroids[i][0]), int(centroids[i][1])

            if protect_mask[cy, cx] > 0:
                continue

            aspect_ratio = max(bw, bh) / max(min(bw, bh), 1)
            max_dim = max(bw, bh)

            if aspect_ratio >= cfg.LINE_ASPECT_RATIO_THRESHOLD and max_dim >= cfg.MIN_LINE_LENGTH:
                line_mask[labels == i] = 255

        # 使用 kernel 缓存（DPI 自适应缩放）
        kernel_size = self._scale_r(cfg.LINE_PROTECT_RADIUS) * 2 + 1
        kernel = kernel_cache.get_ellipse(kernel_size)
        line_mask = cv2.dilate(line_mask, kernel)

        return line_mask

    def _detect_frame_lines(self, cache: ImageCache) -> np.ndarray:
        """框线检测（优化版，使用 kernel 缓存）"""
        h, w = cache.h, cache.w
        binary = cache.get_binary()

        min_line_length = cfg.FRAME_LINE_MIN_LENGTH_DOC

        # 使用 kernel 缓存
        horizontal_kernel = kernel_cache.get_rect(min_line_length, 1)
        horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)

        vertical_kernel = kernel_cache.get_rect(1, min_line_length)
        vertical_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

        frame_mask = cv2.bitwise_or(horizontal_lines, vertical_lines)

        min_span = 500
        min_coverage = 0.05

        h_filled = 0
        v_filled = 0

        for y in range(h):
            row = frame_mask[y, :]
            nonzero = np.where(row > 0)[0]
            if len(nonzero) < 10:
                continue

            span = nonzero[-1] - nonzero[0] + 1
            if span < min_span:
                continue

            coverage = len(nonzero) / span
            if coverage >= min_coverage:
                frame_mask[y, nonzero[0]:nonzero[-1]+1] = 255
                h_filled += 1

        for x in range(w):
            col = frame_mask[:, x]
            nonzero = np.where(col > 0)[0]
            if len(nonzero) < 10:
                continue

            span = nonzero[-1] - nonzero[0] + 1
            if span < min_span:
                continue

            coverage = len(nonzero) / span
            if coverage >= min_coverage:
                frame_mask[nonzero[0]:nonzero[-1]+1, x] = 255
                v_filled += 1

        _log(f"  [推土机] 水平 {h_filled} 行, 垂直 {v_filled} 列")

        if cfg.FRAME_PROTECT_RADIUS > 0:
            kernel_size = self._scale_r(cfg.FRAME_PROTECT_RADIUS) * 2 + 1
            kernel = kernel_cache.get_ellipse(kernel_size)
            frame_mask = cv2.dilate(frame_mask, kernel)

        # xuechong 2026-06-01 清除边缘杂质strip中的误保护框线（必须在 dilation 之后）
        # 边缘杂质特征：frame 列紧贴绝对边缘，且 frame 列后有纯白间隙
        # 真实框线特征：frame 列后紧跟文档内容，无大段空白
        edge_strip_margin = getattr(cfg, 'FRAME_EDGE_STRIP_MARGIN', 30)
        gap_check = getattr(cfg, 'FRAME_EDGE_GAP_CHECK', 40)
        gap_density_thr = getattr(cfg, 'FRAME_EDGE_GAP_DENSITY', 0.01)
        # 左边缘
        has_frame_at_edge = False
        frame_edge_end = 0
        for x in range(min(edge_strip_margin, w)):
            if np.sum(frame_mask[:, x] > 0) > 0:
                has_frame_at_edge = True
                frame_edge_end = x
        if has_frame_at_edge:
            gap_start = frame_edge_end + 1
            gap_end = min(gap_start + gap_check, w)
            gap_dark = sum(np.sum(binary[:, gx] > 0) for gx in range(gap_start, gap_end))
            gap_density = gap_dark / (h * max(1, gap_end - gap_start))
            if gap_density < gap_density_thr:
                frame_mask[:, :edge_strip_margin] = 0
                _log(f"  [推土机] 左边缘{edge_strip_margin}列确认为杂质(间隙密度{gap_density:.3f})，移除框线保护")
        # 右边缘
        has_frame_at_edge = False
        frame_edge_start = w - 1
        for x in range(w - 1, max(w - edge_strip_margin - 1, 0), -1):
            if np.sum(frame_mask[:, x] > 0) > 0:
                has_frame_at_edge = True
                frame_edge_start = x
        if has_frame_at_edge:
            gap_start = max(0, frame_edge_start - gap_check)
            gap_end = frame_edge_start
            gap_dark = sum(np.sum(binary[:, gx] > 0) for gx in range(gap_start, gap_end))
            gap_density = gap_dark / (h * max(1, gap_end - gap_start))
            if gap_density < gap_density_thr:
                frame_mask[:, w - edge_strip_margin:] = 0
                _log(f"  [推土机] 右边缘{edge_strip_margin}列确认为杂质(间隙密度{gap_density:.3f})，移除框线保护")

        return frame_mask

    def _detect_barcode_regions(self, binary: np.ndarray,
                                 num_labels: int, labels: np.ndarray,
                                 stats: np.ndarray) -> np.ndarray:
        """条形码区域检测 — 通过检测密集排列的细竖条来识别条形码区域

        条形码特征：由多根等宽的细竖条密集排列组成，
        每根竖条高度相近、水平方向间距很小。
        通过识别这类"细条聚集"模式来检测条形码区域。
        """
        h, w = binary.shape[:2]
        barcode_mask = np.zeros((h, w), dtype=np.uint8)

        if not getattr(cfg, 'ENABLE_BARCODE_PROTECTION', True):
            return barcode_mask

        # DPI 自适应参数
        max_width = self._scale_r(getattr(cfg, 'BARCODE_BAR_MAX_WIDTH', 8))
        min_height = self._scale_r(getattr(cfg, 'BARCODE_BAR_MIN_HEIGHT', 20))
        cluster_dist = self._scale_r(getattr(cfg, 'BARCODE_CLUSTER_DISTANCE', 30))
        min_cluster_count = getattr(cfg, 'BARCODE_MIN_CLUSTER_COUNT', 8)

        # 第一步：找出所有"细竖条候选"连通域
        # 条件：宽 <= max_width, 高 >= min_height, 纵横比 >= 3
        candidates = []
        for i in range(1, num_labels):
            x, y, bw, bh, area = stats[i]
            if bw <= max_width and bh >= min_height:
                aspect = bh / max(bw, 1)
                if aspect >= 3.0:
                    candidates.append((i, x, y, bw, bh, area))

        if len(candidates) < min_cluster_count:
            return barcode_mask

        # 第二步：按水平位置排序，用滑动窗口检测聚集的细条
        # 条形码的竖条在水平方向上密集排列
        candidates.sort(key=lambda c: c[1])  # 按 x 排序

        # 使用简单的一维聚类：相邻候选条水平间距 < cluster_dist 则属于同一组
        cluster_indices = []
        current_cluster = [0]
        for idx in range(1, len(candidates)):
            # 当前候选条的中心 x 与上一个的间距
            prev_cx = candidates[idx - 1][1] + candidates[idx - 1][3] // 2
            curr_cx = candidates[idx][1] + candidates[idx][3] // 2
            if abs(curr_cx - prev_cx) < cluster_dist:
                current_cluster.append(idx)
            else:
                cluster_indices.append(current_cluster)
                current_cluster = [idx]
        cluster_indices.append(current_cluster)

        # 第三步：判断哪些聚类够密集（>= min_cluster_count）且高度基本一致
        bars_protected = 0
        for cluster in cluster_indices:
            if len(cluster) < min_cluster_count:
                continue

            # 检查高度一致性：所有条的高度中位数，偏差不超过 50%
            heights = [candidates[i][4] for i in cluster]
            median_h = sorted(heights)[len(heights) // 2]
            if median_h < min_height:
                continue

            # 检查水平间距是否紧密：相邻条间距的中位数
            xs = sorted([candidates[i][1] + candidates[i][3] // 2 for i in cluster])
            if len(xs) >= 2:
                gaps = [xs[j + 1] - xs[j] for j in range(len(xs) - 1)]
                median_gap = sorted(gaps)[len(gaps) // 2]
                # 条形码的条间距通常不大于条宽的 4 倍
                if median_gap > cluster_dist:
                    continue

            # 检查整体宽高比：条形码区域宽度 >> 高度
            min_x = min(candidates[i][1] for i in cluster)
            max_x = max(candidates[i][1] + candidates[i][3] for i in cluster)
            cluster_width = max_x - min_x
            cluster_height = median_h
            if cluster_width < cluster_height:
                continue  # 宽度应大于高度才是条形码

            # 通过检测，将该组所有细条所在区域添加到保护蒙版
            # 同时计算聚类的包围盒，确保条间白色间隙也被保护
            cluster_min_x = min(candidates[i][1] for i in cluster)
            cluster_max_x = max(candidates[i][1] + candidates[i][3] for i in cluster)
            cluster_min_y = min(candidates[i][2] for i in cluster)
            cluster_max_y = max(candidates[i][2] + candidates[i][4] for i in cluster)

            # 直接填充包围盒，确保条间白色间隙也被保护
            barcode_mask[cluster_min_y:cluster_max_y, cluster_min_x:cluster_max_x] = 255
            bars_protected += len(cluster)

        if bars_protected > 0:
            _log(f"  [条形码保护] 检测到条形码区域，保护 {bars_protected} 个条形码元素")

            # 膨胀保护蒙版，覆盖条形码整体区域（包括条间的白色间隙）
            protect_radius = self._scale_r(getattr(cfg, 'BARCODE_PROTECT_RADIUS', 10))
            kernel_size = protect_radius * 2 + 1
            kernel = kernel_cache.get_ellipse(kernel_size)
            barcode_mask = cv2.dilate(barcode_mask, kernel)
        else:
            _log(f"  [条形码保护] 未检测到条形码（候选{len(candidates)}个，聚类{len(cluster_indices)}组）")

        return barcode_mask

    def _detect_text_blobs(self, binary: np.ndarray,
                                      num_labels: int, labels: np.ndarray,
                                      stats: np.ndarray, centroids: np.ndarray) -> np.ndarray:
        """文字连通域检测（优化版，使用配置和 kernel 缓存）"""
        h, w = binary.shape[:2]
        text_protect = np.zeros((h, w), dtype=np.uint8)

        # 使用配置缓存
        enable_alpha = config_cache.get('ENABLE_ALPHANUMERIC_PROTECTION', True)
        min_aspect = config_cache.get('ALPHANUMERIC_MIN_ASPECT', 0.2)
        max_aspect = config_cache.get('ALPHANUMERIC_MAX_ASPECT', 4.0)

        # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-006 向量化
        # 过滤条件改 stats 数组布尔运算（与逐域条件逐字对应位等价），全图写入合并为最终一次 np.isin
        if num_labels <= 1:
            return text_protect
        areas = stats[1:, cv2.CC_STAT_AREA]
        bxs = stats[1:, cv2.CC_STAT_LEFT]
        bys = stats[1:, cv2.CC_STAT_TOP]
        bws = stats[1:, cv2.CC_STAT_WIDTH]
        bhs = stats[1:, cv2.CC_STAT_HEIGHT]
        aspect_ratio = bws / np.maximum(bhs, 1)
        is_large_area = areas >= cfg.TEXT_BLOB_MIN_AREA
        is_wide = bws >= cfg.TEXT_BLOB_MIN_WIDTH
        is_valid_height = (cfg.TEXT_BLOB_MIN_HEIGHT <= bhs) & (bhs <= cfg.TEXT_BLOB_MAX_HEIGHT)
        is_not_line = (aspect_ratio < 20) & (1 / np.maximum(aspect_ratio, 0.01) < 20)
        if enable_alpha:
            fill_ratio = areas / np.maximum(bws * bhs, 1)
            is_alphanumeric = ((areas >= 40) & (areas <= 500) & (bhs >= 8) & (bhs <= 40)
                               & (aspect_ratio >= min_aspect) & (aspect_ratio <= max_aspect)
                               & (fill_ratio > 0.15))
        else:
            is_alphanumeric = np.zeros(num_labels - 1, dtype=bool)
        is_text = (is_large_area | is_wide) & is_valid_height & is_not_line & (~is_alphanumeric)

        candidates = []
        # alpha 优先序保持：alpha 命中的域不再进入 text 判定（is_text 已 & ~is_alphanumeric）
        for j in np.nonzero(is_alphanumeric)[0]:
            candidates.append((int(j) + 1, int(bxs[j]), int(bys[j]), int(bws[j]), int(bhs[j]), int(areas[j]), 'alpha'))
        for j in np.nonzero(is_text)[0]:
            candidates.append((int(j) + 1, int(bxs[j]), int(bys[j]), int(bws[j]), int(bhs[j]), int(areas[j]), 'text'))

        ISOLATION_RADIUS = self._scale_r(cfg.TEXT_BLOB_ISOLATION_RADIUS)
        text_count = 0
        alpha_count = 0

        # 网格空间索引加速隔离检查（O(n) 替代 O(n²)）
        cell_size = max(ISOLATION_RADIUS, 1)
        grid = defaultdict(list)
        for idx, item in enumerate(candidates):
            cx = item[1] + item[3] // 2
            cy = item[2] + item[4] // 2
            grid[(cx // cell_size, cy // cell_size)].append(idx)

        # REQ-006 向量化：逐候选全图写入改为收集保留 id 后一次 np.isin（隔离/孤立过滤语义不变）
        kept_alpha_ids = []
        kept_text_ids = []
        for idx, item in enumerate(candidates):

            gx = (item[1] + item[3] // 2) // cell_size
            gy = (item[2] + item[4] // 2) // cell_size

            is_isolated = True
            for dx in (-1, 0, 1):
                if not is_isolated:
                    break
                for dy in (-1, 0, 1):
                    if not is_isolated:
                        break
                    for other_idx in grid.get((gx + dx, gy + dy), ()):
                        if other_idx == idx:
                            continue
                        other = candidates[other_idx]
                        jx, jy, jw, jh = other[1], other[2], other[3], other[4]
                        ddx = max(0, max(item[1], jx) - min(item[1] + item[3], jx + jw))
                        ddy = max(0, max(item[2], jy) - min(item[2] + item[4], jy + jh))
                        dist = (ddx ** 2 + ddy ** 2) ** 0.5
                        if dist < ISOLATION_RADIUS:
                            is_isolated = False
                            break

            if is_isolated:
                if item[6] == 'alpha' and item[5] < 80:
                    continue
                if item[6] == 'text' and item[5] < 500:
                    continue

            (kept_alpha_ids if item[6] == 'alpha' else kept_text_ids).append(item[0])

        alpha_count = len(kept_alpha_ids)
        text_count = len(kept_text_ids)
        if kept_alpha_ids or kept_text_ids:
            all_ids = np.array(kept_alpha_ids + kept_text_ids, dtype=labels.dtype)
            text_protect[np.isin(labels, all_ids)] = 255

        if alpha_count > 0:
            _log(f"  [文字保护] 检测到 {alpha_count} 个英文/数字字符")
        
        if cfg.TEXT_BLOB_PROTECT_RADIUS > 0 and (text_count + alpha_count) > 0:
            kernel_size = self._scale_r(cfg.TEXT_BLOB_PROTECT_RADIUS) * 2 + 1
            kernel = kernel_cache.get_ellipse(kernel_size)
            text_protect = cv2.dilate(text_protect, kernel)

        return text_protect
