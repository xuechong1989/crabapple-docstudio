# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
"""噪点检测 Mixin 模块"""

import cv2
import numpy as np

from backend import config as cfg
from .cache import kernel_cache, config_cache, ImageCache
from . import _log


class NoiseMixin:
    """噪点检测功能"""

    def _detect_noise(self, image: np.ndarray, cache: ImageCache,
                                 protect_mask: np.ndarray, debug: bool) -> tuple:
        """噪点检测（优化版，使用 kernel 缓存）"""
        h, w = cache.h, cache.w
        edge_left = int(w * cfg.EDGE_MARGIN_RATIO)
        edge_right = int(w * (1 - cfg.EDGE_MARGIN_RATIO))
        
        num_labels, labels, stats, centroids = cache.get_connected_components()

        # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-006 向量化
        # 两段逐域循环改为 stats 数组布尔过滤 + np.isin 一次写入；质心花式索引替代逐点采样；
        # 覆盖率用积分图一次算全；小噪点例外距离用 bbox 广播计算——各条件与逐域版本逐字对应位等价
        areas = stats[1:, cv2.CC_STAT_AREA]
        bws = stats[1:, cv2.CC_STAT_WIDTH]
        bhs = stats[1:, cv2.CC_STAT_HEIGHT]
        lefts = stats[1:, cv2.CC_STAT_LEFT]
        tops = stats[1:, cv2.CC_STAT_TOP]
        is_text = (areas > cfg.MIN_TEXT_AREA) | (bws > cfg.MIN_TEXT_DIM) | (bhs > cfg.MIN_TEXT_DIM)

        text_mask = np.zeros((h, w), dtype=np.uint8)
        text_ids = np.nonzero(is_text)[0] + 1
        if text_ids.size:
            text_mask[np.isin(labels, text_ids)] = 255

        # 使用 kernel 缓存（DPI 自适应缩放）
        kernel_size = self._scale_r(cfg.TEXT_PROTECT_RADIUS) * 2 + 1
        kernel = kernel_cache.get_ellipse(kernel_size)
        text_protect = cv2.dilate(text_mask, kernel)

        # REQ-002 小噪点例外 + REQ-004 覆盖率保护（OR 语义）配置读取
        gap_exception = config_cache.get('NOISE_TEXT_GAP_EXCEPTION', False)
        gap_max_area = config_cache.get('NOISE_TEXT_GAP_NOISE_MAX_AREA', 60)
        gap_min_dist = config_cache.get('NOISE_TEXT_GAP_MIN_DIST', 8)
        cover_mode = config_cache.get('NOISE_PROTECT_COVER_MODE', False)
        cover_ratio = config_cache.get('NOISE_PROTECT_COVER_RATIO', 0.3)

        vis = image.copy() if debug else None
        noise_mask = np.zeros((h, w), dtype=np.uint8)

        if num_labels <= 1:
            return noise_mask, text_protect, vis, {'left': {}, 'right': {}}

        # 质心数组化（astype 截断与原 int() 等价，坐标非负）
        cxs = centroids[1:, 0].astype(np.int64)
        cys = centroids[1:, 1].astype(np.int64)
        aspects = np.maximum(bws, bhs) / np.maximum(np.minimum(bws, bhs), 1)

        alive = (protect_mask[cys, cxs] == 0) & (~is_text)

        # text_protect 膨胀保护区：小噪点例外（面积小且距文字本体足够远）才放行
        tp_hit = text_protect[cys, cxs] > 0
        if gap_exception:
            exc_cand = np.nonzero(tp_hit & (areas <= gap_max_area))[0]
            exc_ok = np.zeros(num_labels - 1, dtype=bool)
            if exc_cand.size:
                if text_ids.size:
                    tx = lefts[text_ids - 1]; ty = tops[text_ids - 1]
                    tw = bws[text_ids - 1]; th = bhs[text_ids - 1]
                    ex = lefts[exc_cand]; ey = tops[exc_cand]
                    ew = bws[exc_cand]; eh = bhs[exc_cand]
                    # 候选×文字框广播求 bbox 最小间距（与逐域 _min_dist_to_boxes 同式）
                    dx = np.maximum(np.maximum(tx[None, :] - (ex[:, None] + ew[:, None]),
                                               ex[:, None] - (tx[None, :] + tw[None, :])), 0)
                    dy = np.maximum(np.maximum(ty[None, :] - (ey[:, None] + eh[:, None]),
                                               ey[:, None] - (ty[None, :] + th[None, :])), 0)
                    dmin = np.sqrt(dx * dx + dy * dy).min(axis=1)
                    exc_ok[exc_cand] = dmin >= gap_min_dist
                else:
                    exc_ok[exc_cand] = True  # 无文字框时全部视为孤立（与原空列表返回 1e9 一致）
            alive &= (~tp_hit) | exc_ok
        else:
            alive &= ~tp_hit

        # 噪点尺寸/长宽比条件
        alive &= (areas < cfg.MAX_NOISE_AREA) & (bws < cfg.MAX_NOISE_DIM) & (bhs < cfg.MAX_NOISE_DIM) & (aspects < cfg.MAX_NOISE_ASPECT)

        # REQ-004 覆盖率保护（OR 新增）：bbox 内文字本体像素数（积分图一次算全）≥ cover_ratio*area 即保护（不清除）
        if cover_mode and np.any(alive):
            sat = cv2.integral((text_mask > 0).astype(np.uint8))  # (h+1, w+1) 积分图
            idx = np.nonzero(alive)[0]
            x0 = lefts[idx]; y0 = tops[idx]
            x1 = x0 + bws[idx]; y1 = y0 + bhs[idx]
            overlap = (sat[y1, x1] - sat[y0, x1] - sat[y1, x0] + sat[y0, x0]).astype(np.float64)
            alive[idx[overlap >= cover_ratio * areas[idx]]] = False

        keep_ids = np.nonzero(alive)[0] + 1
        if keep_ids.size:
            noise_mask[np.isin(labels, keep_ids)] = 255

        # 边缘列计数（仅对保留为噪点的域，语义同原 if/elif；键为 int 与原 dict 一致）
        kc = cxs[alive]
        lv, lc = np.unique(kc[kc < edge_left], return_counts=True)
        rv, rc = np.unique(kc[kc > edge_right], return_counts=True)
        left_edge_x = {int(a): int(b) for a, b in zip(lv, lc)}
        right_edge_x = {int(a): int(b) for a, b in zip(rv, rc)}

        if debug and keep_ids.size:
            for i in keep_ids:
                x, y, bw, bh = stats[i, :4]
                cv2.rectangle(vis, (int(x), int(y)), (int(x + bw), int(y + bh)), (0, 0, 255), 1)

        return noise_mask, text_protect, vis, {'left': left_edge_x, 'right': right_edge_x}

    def _detect_tiny_spots(self, cache: ImageCache, seal_mask: np.ndarray,
                           dotline_protect: np.ndarray = None) -> np.ndarray:
        """微小深色孤立斑强制检测（REQ-004）
        复用 cache 的 BINARY_THRESHOLD(200) 口径连通域——与黑斑检测同口径，文字完整不碎化、
        淡化文字（灰度>200）天然不可见。0006/0038 实测幸存黑点为实心暗域（面积 47~189、
        宽高 7~18），在此口径下可见且可清。
        防误清判据（四条）：面积/尺寸上限（排除数字/字母——高度 35px+ 超尺寸上限）、
        灰度深度（bbox 均值<100——淡印刷件的文字笔画碎片在 200 阈值下碎化成小域且
        开运算无残留，几何判据不可分，唯灰度深度可分；p4 全量实测 024 整页文字被误清）、
        印章/点线保护区外（印章笔画、点线的"点"都是小域且彼此疏离，几何判据不可分）、
        孤立性（9x9 开运算去除小斑后环带内几乎无残留暗结构才判孤立——句号等标点紧邻
        文字有残留不清，成群碎屑斑被开运算消除邻斑后各自孤立、全部清除）。
        历史教训（不要重蹈）：曾改用 245 阈值以捕获更淡的斑，但细笔画印刷字在 245 下
        碎化成小域且开运算后无残留，被孤立性大规模误清（0006 文字只剩单字），已回退。
        """
        h, w = cache.h, cache.w
        spot_mask = np.zeros((h, w), dtype=np.uint8)
        max_area = config_cache.get('TINY_SPOT_MAX_AREA', 450)
        max_dim = config_cache.get('TINY_SPOT_MAX_DIM', 28)
        ring = 20
        num_labels, labels, stats, centroids = cache.get_connected_components()
        if num_labels <= 1:
            return spot_mask
        areas = stats[1:, cv2.CC_STAT_AREA]
        bws = stats[1:, cv2.CC_STAT_WIDTH]
        bhs = stats[1:, cv2.CC_STAT_HEIGHT]
        lefts = stats[1:, cv2.CC_STAT_LEFT]
        tops = stats[1:, cv2.CC_STAT_TOP]
        cand = np.nonzero((areas > 0) & (areas <= max_area)
                          & (bws <= max_dim) & (bhs <= max_dim))[0] + 1
        if cand.size == 0:
            return spot_mask
        cxs = centroids[cand - 1, 0].astype(np.int64)
        cys = centroids[cand - 1, 1].astype(np.int64)
        ok = np.ones(cand.size, dtype=bool)
        # 灰度深度判据：真黑屑斑深黑（bbox 均值<100，0006 实测 29~196 深浅不一），
        # 淡印刷件的文字笔画碎片（024 实测）虽尺寸小且开运算无残留，但其灰度浅
        # （均值>120）——以 100 为界排除，防止淡印刷文字被整页误清（p4 教训）
        gray = cache.gray
        ii_g = cv2.integral(gray.astype(np.float64))
        ix0 = lefts[cand - 1]; iy0 = tops[cand - 1]
        ix1 = ix0 + bws[cand - 1]; iy1 = iy0 + bhs[cand - 1]
        box_sum = ii_g[iy1, ix1] - ii_g[iy0, ix1] - ii_g[iy1, ix0] + ii_g[iy0, ix0]
        box_mean = box_sum / np.maximum(areas[cand - 1], 1)
        ok &= box_mean < 100
        if seal_mask is not None and np.sum(seal_mask > 0) > 0:
            ok &= seal_mask[cys, cxs] == 0
        if dotline_protect is not None and np.sum(dotline_protect > 0) > 0:
            ok &= dotline_protect[cys, cxs] == 0
        idx = np.nonzero(ok)[0] + 1
        if idx.size == 0:
            return spot_mask
        # 孤立性：9x9 开运算去除小斑后，环带内几乎无残留暗结构（文字/线/大内容）才算孤立。
        # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
        # 不能直接用原始暗像素判孤立——碎屑斑常成群（0006 实测 3~4 粒彼此相距 8~40px），
        # 互相把对方判为"非孤立"；开运算消除邻斑后仅剩文字/线/大内容的残留。
        # OpenCV 5.0 的 integral 不再支持整型输入，须转 float64
        binary = cache.get_binary()
        kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        big_dark = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_open)
        ii_big = cv2.integral((big_dark > 0).astype(np.float64))
        ex0 = np.clip(lefts[idx - 1] - ring, 0, w)
        ey0 = np.clip(tops[idx - 1] - ring, 0, h)
        ex1 = np.clip(lefts[idx - 1] + bws[idx - 1] + ring, 0, w)
        ey1 = np.clip(tops[idx - 1] + bhs[idx - 1] + ring, 0, h)
        ix0 = lefts[idx - 1]; iy0 = tops[idx - 1]
        ix1 = ix0 + bws[idx - 1]; iy1 = iy0 + bhs[idx - 1]
        outer = ii_big[ey1, ex1] - ii_big[ey0, ex1] - ii_big[ey1, ex0] + ii_big[ey0, ex0]
        inner = ii_big[iy1, ix1] - ii_big[iy0, ix1] - ii_big[iy1, ix0] + ii_big[iy0, ix0]
        ring_dark = outer - inner
        isolated = ring_dark <= 20
        keep = idx[isolated]
        if keep.size:
            spot_mask[np.isin(labels, keep)] = 255
            _log(f"  [微斑清除] 强制清除保护区内微小深色孤立斑 {keep.size} 个（{np.sum(spot_mask > 0)} 像素）")
        return spot_mask

    def _detect_punch_holes(self, cache: ImageCache, protect_mask: np.ndarray) -> np.ndarray:
        """钉痕检测（优化版，使用配置缓存）"""
        h, w = cache.h, cache.w
        punch_mask = np.zeros((h, w), dtype=np.uint8)

        # 使用专门的阈值进行二值化
        gray = cache.gray
        _, binary_punch = cv2.threshold(gray, cfg.PUNCH_HOLE_BINARY_THRESHOLD, 255, cv2.THRESH_BINARY_INV)

        binary_punch[protect_mask > 0] = 0

        # 使用配置缓存
        full_image = config_cache.get('PUNCH_HOLE_FULL_IMAGE', False)
        
        if not full_image:
            edge_mask = np.zeros((h, w), dtype=np.uint8)
            edge_x = int(w * cfg.EDGE_MARGIN_RATIO)
            edge_y = int(h * cfg.EDGE_MARGIN_RATIO)

            edge_mask[:, :edge_x] = 255
            edge_mask[:, w - edge_x:] = 255
            edge_mask[:edge_y, :] = 255
            edge_mask[h - edge_y:, :] = 255

            binary_punch = cv2.bitwise_and(binary_punch, edge_mask)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary_punch, connectivity=8)

        max_aspect = config_cache.get('PUNCH_HOLE_MAX_ASPECT', 5.0)
        # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-003 钉痕严格模式
        # 带外（四边 margin=EDGE_MARGIN_RATIO 之外）候选追加 bbox填充率/面积判定；
        # 带内（装订边）维持宽松判定，真钉痕清除能力不变。统计依据见工作目录研发BUG-0030-钉痕候选分布.jsonl
        strict_mode = config_cache.get('PUNCH_HOLE_STRICT_MODE', False)
        min_extent = config_cache.get('PUNCH_HOLE_MIN_EXTENT', 0.5)
        strict_min_area = config_cache.get('PUNCH_HOLE_STRICT_MIN_AREA', 50)
        edge_x = int(w * cfg.EDGE_MARGIN_RATIO)
        edge_y = int(h * cfg.EDGE_MARGIN_RATIO)

        # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-006 向量化
        # stats 数组布尔过滤 + np.isin 一次写入替代逐域循环（条件与逐域版本逐字对应，位等价）
        if num_labels <= 1:
            return punch_mask
        areas = stats[1:, cv2.CC_STAT_AREA]
        bws = stats[1:, cv2.CC_STAT_WIDTH]
        bhs = stats[1:, cv2.CC_STAT_HEIGHT]
        lefts = stats[1:, cv2.CC_STAT_LEFT]
        tops = stats[1:, cv2.CC_STAT_TOP]
        aspects = np.maximum(bws, bhs) / np.maximum(np.minimum(bws, bhs), 1)
        valid = ((cfg.PUNCH_HOLE_MIN_AREA <= areas) & (areas <= cfg.PUNCH_HOLE_MAX_AREA)
                 & (bws <= cfg.PUNCH_HOLE_MAX_DIM) & (bhs <= cfg.PUNCH_HOLE_MAX_DIM)
                 & (aspects <= max_aspect))
        if strict_mode and np.any(valid):
            cxs = lefts + bws / 2.0
            cys = tops + bhs / 2.0
            in_edge = (cxs < edge_x) | (cxs > w - edge_x) | (cys < edge_y) | (cys > h - edge_y)
            extents = areas / np.maximum(bws * bhs, 1)
            valid &= in_edge | ((extents >= min_extent) & (areas >= strict_min_area))
        valid_ids = np.nonzero(valid)[0] + 1
        if valid_ids.size:
            punch_mask[np.isin(labels, valid_ids)] = 255
            _log(f"  [钉痕检测] 检测到 {valid_ids.size} 个钉痕区域")

        return punch_mask

    def _detect_creases(self, cache: ImageCache, protect_mask: np.ndarray) -> np.ndarray:
        """折痕检测（优化版，使用配置缓存）"""
        h, w = cache.h, cache.w
        crease_mask = np.zeros((h, w), dtype=np.uint8)
        
        # 使用配置缓存
        if not config_cache.get('ENABLE_CREASE_DETECTION', False):
            return crease_mask
        
        gray = cache.gray
        threshold = config_cache.get('CREASE_BINARY_THRESHOLD', 220)
        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)
        
        binary[protect_mask > 0] = 0
        
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        
        min_length = config_cache.get('CREASE_MIN_LENGTH', 200)
        max_width = config_cache.get('CREASE_MAX_WIDTH', 15)
        min_aspect = config_cache.get('CREASE_MIN_ASPECT_RATIO', 15.0)
        
        crease_count = 0
        for i in range(1, num_labels):
            x, y, bw, bh, area = stats[i]
            
            max_dim = max(bw, bh)
            min_dim = min(bw, bh)
            
            if max_dim >= min_length and min_dim <= max_width:
                aspect = max_dim / max(min_dim, 1)
                if aspect >= min_aspect:
                    crease_mask[labels == i] = 255
                    crease_count += 1
        
        if crease_count > 0:
            _log(f"  [折痕检测] 检测到 {crease_count} 条折痕")
        
        return crease_mask

    def _detect_stray_lines(self, binary: np.ndarray, protect_mask: np.ndarray,
                                       num_labels: int, labels: np.ndarray,
                                       stats: np.ndarray) -> np.ndarray:
        """杂质线条检测（优化版，复用连通域分析结果）"""
        h, w = binary.shape[:2]
        stray_line_mask = np.zeros((h, w), dtype=np.uint8)
        
        if not getattr(cfg, 'ENABLE_STRAY_LINE_DETECTION', True):
            return stray_line_mask
        
        max_width = self._scale_r(getattr(cfg, 'STRAY_LINE_MAX_WIDTH', 4))
        min_length = self._scale_r(getattr(cfg, 'STRAY_LINE_MIN_LENGTH', 30))
        min_aspect = getattr(cfg, 'STRAY_LINE_MIN_ASPECT', 10.0)
        protect_distance = self._scale_r(getattr(cfg, 'STRAY_LINE_PROTECT_DISTANCE', 20))

        # 预先膨胀保护区（使用 kernel 缓存）
        kernel = kernel_cache.get_ellipse(protect_distance * 2 + 1)
        expanded_protect = cv2.dilate(protect_mask, kernel)
        
        stray_count = 0
        for i in range(1, num_labels):
            bx, by, bw, bh, area = stats[i]
            
            max_dim = max(bw, bh)
            min_dim = min(bw, bh)
            
            if min_dim > max_width:
                continue
            if max_dim < min_length:
                continue
            
            aspect = max_dim / max(min_dim, 1)
            if aspect < min_aspect:
                continue
            
            # 多点采样检查是否靠近保护区（9点：中心 + 4角 + 4边中点）
            sample_points = [
                (bx + bw // 2, by + bh // 2),          # 中心
                (bx, by), (bx + bw - 1, by),            # 上边两角
                (bx, by + bh - 1), (bx + bw - 1, by + bh - 1),  # 下边两角
                (bx + bw // 2, by), (bx + bw // 2, by + bh - 1),  # 上下边中点
                (bx, by + bh // 2), (bx + bw - 1, by + bh // 2),  # 左右边中点
            ]
            overlaps_protect = False
            for px, py in sample_points:
                py = min(max(py, 0), h - 1)
                px = min(max(px, 0), w - 1)
                if expanded_protect[py, px] > 0:
                    overlaps_protect = True
                    break
            if overlaps_protect:
                continue
            # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-004
            # 覆盖率保护（OR 新增）：bbox 与膨胀保护区重叠率达标亦保护（细长形态阈值取低值）
            if config_cache.get('NOISE_PROTECT_COVER_MODE', False) and bw > 0 and bh > 0:
                cover = float(np.count_nonzero(expanded_protect[by:by + bh, bx:bx + bw] > 0)) / (bw * bh)
                if cover >= getattr(cfg, 'STRAY_LINE_PROTECT_COVER_RATIO', 0.05):
                    continue
            
            stray_line_mask[labels == i] = 255
            stray_count += 1
        
        if stray_count > 0:
            _log(f"  [杂质线条] 检测到 {stray_count} 条杂质线条")
        
        return stray_line_mask
