# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
"""票据处理 Mixin 模块"""

import cv2
import numpy as np

from backend import config as cfg
from .cache import kernel_cache, config_cache, ImageCache
# xuechong 2026-07-20 修复：补齐缺失的导入（原 line 554 直接使用但未导入，运行时被 except 静默吞掉）
from . import _log, _get_cached_ocr_engine


class ReceiptMixin:
    """票据处理功能"""

    # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 印章形状判别
    # 印章形状先验：圆形/椭圆（公章）/方形（业务章/检验章），轮廓可能残缺不清晰；
    # 外边界不规则的深色块才可放心抹除。判别算法：
    # ①椭圆拟合：cv2.fitEllipse 拟合轮廓，计算轮廓点到椭圆的归一化径向残差 → 拟合分；
    # ②残缺容忍：剔除残差最大 30% 的轮廓点后重新拟合（支持半圆章/缺角章等残缺印章）；
    # ③矩形度：minAreaRect 面积比 + 多边形逼近顶点数（方形/长方形章）。
    # 返回 (类型, 置信度)：类型 ellipse/rect/irregular；置信度>=0.5 视为规则形状（疑似印章）。
    @staticmethod
    def _blob_shape_regular(blob_mask: np.ndarray) -> tuple:
        # CHAIN_APPROX_NONE 取完整轮廓点（SIMPLE 会把矩形压成4角点导致形状判别失真）
        contours, _ = cv2.findContours(blob_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            return 'irregular', 0.0
        cnt = max(contours, key=cv2.contourArea)
        pts = cnt.reshape(-1, 2).astype(np.float64)
        if len(pts) < 20 or cv2.contourArea(cnt) < 100:
            return 'irregular', 0.0

        def _ellipse_score(points: np.ndarray) -> tuple:
            if len(points) < 5:
                return 0.0, None
            try:
                (cx, cy), (MA, ma), ang = cv2.fitEllipse(points.reshape(-1, 1, 2).astype(np.float32))
            except cv2.error:
                return 0.0, None
            a, b = MA / 2.0, ma / 2.0
            if min(a, b) < 2:
                return 0.0, None
            xr, yr = points[:, 0] - cx, points[:, 1] - cy
            ct, st = np.cos(np.deg2rad(ang)), np.sin(np.deg2rad(ang))
            xe, ye = xr * ct + yr * st, -xr * st + yr * ct
            phi = np.arctan2(ye, xe)
            r_pred = a * b / np.sqrt((b * np.cos(phi)) ** 2 + (a * np.sin(phi)) ** 2)
            r_real = np.sqrt(xr ** 2 + yr ** 2)
            err = np.abs(r_real - r_pred) / np.maximum(r_pred, 1.0)
            return max(0.0, 1.0 - float(np.sqrt((err ** 2).mean())) * 4.0), err

        # 全轮廓拟合 + 残缺容忍（剔除残差最大 30% 点重新拟合，取较高分）
        s_full, err = _ellipse_score(pts)
        s_trim = 0.0
        if err is not None and len(pts) >= 40:
            keep = pts[np.argsort(err)[:int(len(pts) * 0.7)]]
            s_trim, _ = _ellipse_score(keep)
        ellipse_score = max(s_full, s_trim)
        # 椭圆填充率+厚度约束：真实圆/椭圆/残缺章 contourArea/(πab)≥0.45（标准圆≈0.785、
        # 半圆≈0.5）；椭圆短轴≥30px（真章有厚度，细长线短轴~20 由细长判据处理）
        if ellipse_score > 0:
            try:
                (cx, cy), (MA, ma), _ = cv2.fitEllipse(pts.reshape(-1, 1, 2).astype(np.float32))
                _fill = cv2.contourArea(cnt) / (np.pi * (MA / 2.0) * (ma / 2.0) + 1e-6)
                if _fill < 0.45 or min(MA, ma) < 30:
                    ellipse_score = 0.0
            except cv2.error:
                ellipse_score = 0.0

        # 矩形度（方形章）：minAreaRect 面积比 + 顶点数（≤6 允许轻微畸变）。
        # 矩形度>=0.75 才可能是章（方形章填充率≈1.0，L 形等凹形≈0.68 拦掉）；
        # 短边>=30px 排除细长线（细线矩形度=1.0 但不是章，线由细长判据处理）。
        rect = cv2.minAreaRect(cnt)
        rect_area = rect[1][0] * rect[1][1]
        rect_fill = cv2.contourArea(cnt) / max(rect_area, 1.0)
        approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
        if rect_fill >= 0.75 and min(rect[1]) >= 30:
            rect_score = rect_fill if len(approx) <= 6 else rect_fill * 0.5
        else:
            rect_score = 0.0

        if ellipse_score >= rect_score:
            # 阈值 0.6：残缺圆/半圆 0.78+ 通过，L 形等凹形 0.53 拦掉；不规则时分数归零
            if ellipse_score >= 0.6:
                return 'ellipse', ellipse_score
            return 'irregular', 0.0
        if rect_score >= 0.5:
            return 'rect', rect_score
        return 'irregular', 0.0

    def _find_receipt_boundary_by_texture(self, gray_img: np.ndarray) -> tuple:
        """
        基于纸张亮度检测票据/文档的矩形边界

        核心思路：票据纸张整体有统一的亮度（浅灰），背景是纯白。
        通过大尺度高斯模糊抹去文字内容，保留纸张与背景的亮度差异，
        再通过 Otsu 阈值分离纸张与背景。

        Args:
            gray_img: 灰度图像

        Returns:
            tuple: (x, y, w, h) 票据矩形区域，或 None 表示检测失败
        """
        h, w = gray_img.shape[:2]

        # 步骤1：大尺度模糊 — 抹去文字内容，保留纸张整体亮度
        blur_ksize = max(101, min(h, w) // 15)
        if blur_ksize % 2 == 0:
            blur_ksize += 1
        heavy_blur = cv2.GaussianBlur(gray_img, (blur_ksize, blur_ksize), 0)

        # 步骤2：Otsu 阈值分离纸张与背景
        _, binary = cv2.threshold(heavy_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        bright_ratio = np.sum(binary > 0) / (h * w)

        # 判断哪边是纸张：四角通常是背景，比较四角与中心的亮度
        corners = np.array([
            heavy_blur[0, 0], heavy_blur[0, -1],
            heavy_blur[-1, 0], heavy_blur[-1, -1]
        ])
        corner_mean = corners.mean()
        center_val = heavy_blur[h // 2, w // 2]
        paper_is_dark = corner_mean > center_val

        # 选择纸张掩码
        if 0.20 < bright_ratio < 0.80:
            if paper_is_dark:
                paper_mask = cv2.bitwise_not(binary)
            else:
                paper_mask = binary
        else:
            paper_mask = (heavy_blur < corner_mean - 15).astype(np.uint8) * 255

        paper_ratio = np.sum(paper_mask > 0) / (h * w)

        if paper_ratio < 0.05 or paper_ratio > 0.95:
            _log(f"  [纸张边界] 纸张面积比 {paper_ratio*100:.1f}% 异常，跳过")
            return None

        # 步骤3：形态学闭运算 — 填充纸张内部孔洞
        close_ksize = max(21, min(h, w) // 60)
        if close_ksize % 2 == 0:
            close_ksize += 1
        kernel = kernel_cache.get_rect(close_ksize, close_ksize)
        paper_closed = cv2.morphologyEx(paper_mask, cv2.MORPH_CLOSE, kernel)

        # 步骤4：找最大连通区域
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            paper_closed, connectivity=8
        )
        if num_labels <= 1:
            return None

        areas = stats[1:, cv2.CC_STAT_AREA]
        max_idx = np.argmax(areas) + 1
        max_area = areas[max_idx - 1]

        if max_area / (h * w) < 0.05:
            return None

        # 步骤5：取外接矩形
        x = int(stats[max_idx, cv2.CC_STAT_LEFT])
        y = int(stats[max_idx, cv2.CC_STAT_TOP])
        cw = int(stats[max_idx, cv2.CC_STAT_WIDTH])
        ch = int(stats[max_idx, cv2.CC_STAT_HEIGHT])

        _log(f"  [纸张边界] 粗检测: ({x},{y}) {cw}x{ch}, 面积={max_area/(h*w)*100:.1f}%")

        # 步骤6：安全边距（向内缩进，避免包含边缘阴影）
        # BOUNDARY_MARGIN_ADJUST: 向外保留的额外像素数，正值=更宽松，负值=更收紧
        # 当前值2：在默认缩进基础上向外多保留2px，避免切掉票据边缘内容
        BOUNDARY_MARGIN_ADJUST = 2
        margin = max(5, min(cw, ch) // 100) - BOUNDARY_MARGIN_ADJUST
        margin = max(1, margin)  # 确保至少缩进1px
        x = max(0, x + margin)
        y = max(0, y + margin)
        cw = min(w - x, cw - 2 * margin)
        ch = min(h - y, ch - 2 * margin)

        _log(f"  [纸张边界] 最终: ({x},{y}) 尺寸={cw}x{ch}")
        return (x, y, cw, ch)

    def _clean_outside_boundary(self, image: np.ndarray, protect_mask: np.ndarray, original_image: np.ndarray = None) -> np.ndarray:
        """
        文档/票据边界外强力净化

        算法（按优先级尝试）：
        0. 纸张亮度方法（新增）：大尺度模糊 + Otsu 检测纸张整体区域，适用于白色/浅色纸张
        1. 饱和度方法（回退）：基于饱和度检测有色纸张区域（蓝/黄/粉票据）
        2. 腐蚀去噪 → 闭运算填充 → 腐蚀收紧
        3. 找最大连通区域的外接矩形
        4. 矩形外全部刷白（保护红色印章）
        
        Args:
            image: BGR 格式的图片数组（要处理的图片）
            protect_mask: 保护区域掩码
            original_image: 原始图片（用于边界检测，可选）
            
        Returns:
            np.ndarray: 处理后的图片
        """
        h, w = image.shape[:2]
        result = image.copy()

        # 重要：使用原始图片检测边界，因为处理后的图片饱和度可能已改变
        detect_image = original_image if original_image is not None else image

        # ============================================================
        # 步骤0：先尝试基于纸张亮度的边界检测（适用于白底/浅色票据）
        # ============================================================
        if self.config.get('ENABLE_RECEIPT_BOUNDARY_BY_TEXTURE', True):
            gray_detect = cv2.cvtColor(detect_image, cv2.COLOR_BGR2GRAY)
            texture_rect = self._find_receipt_boundary_by_texture(gray_detect)
            if texture_rect is not None:
                x, y, cw, ch = texture_rect
                # 安全检查：如果检测到的边界占整个图片的比例 < 60%，
                # 说明纹理方法误将普通文档的内容区域当成了"纸张"，
                # 此时跳过边界净化，避免删除大量正常内容。
                # 真正的票据已在阶段零-B被 _process_receipt_document 处理，
                # 能到达此处的都是普通文档，不应做激进裁剪。
                boundary_area_ratio = cw * ch / (h * w)
                if boundary_area_ratio < 0.60:
                    _log(f"  [边界净化] 纹理方法检测到小边界({boundary_area_ratio*100:.1f}%)，"
                         f"疑似普通文档误检，跳过边界净化")
                    return result
                receipt_mask = np.zeros((h, w), dtype=np.uint8)
                receipt_mask[y:y+ch, x:x+cw] = 255

                hsv_temp = cv2.cvtColor(detect_image, cv2.COLOR_BGR2HSV)
                hue_temp = hsv_temp[:, :, 0]
                sat_temp = hsv_temp[:, :, 1]
                red_seal = ((hue_temp < 10) | (hue_temp > 170)) & (sat_temp > 80)
                red_seal_dilated = cv2.dilate(
                    red_seal.astype(np.uint8) * 255,
                    kernel_cache.get_ellipse(self._scale_r(cfg.MORPH_KERNEL_XLARGE)),
                    iterations=2
                )

                outside = (receipt_mask == 0) & (red_seal_dilated == 0)
                result[outside] = (255, 255, 255)

                outside_pixels = np.sum(outside)
                seal_protected = np.sum((receipt_mask == 0) & (red_seal_dilated > 0))
                _log(f"  [边界净化] 纸张方法 - 票据矩形: ({x},{y}) 尺寸={cw}x{ch}")
                _log(f"  [边界净化] 外部区域: {outside_pixels} 像素 ({100*outside_pixels/(h*w):.1f}%)")
                if seal_protected > 0:
                    _log(f"  [边界净化] 边界外印章保护: {seal_protected} 像素")
                return result

        # ============================================================
        # 步骤1：回退到饱和度方法（检测有色纸张区域）
        # ============================================================
        hsv = cv2.cvtColor(detect_image, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0]
        saturation = hsv[:, :, 1]

        # 是否保存调试图片
        save_debug = getattr(cfg, 'BOUNDARY_DEBUG', False)
        debug_path = getattr(cfg, 'BOUNDARY_DEBUG_PATH', str(getattr(cfg, 'TMP_DIR', 'tmp')) + '/boundary_debug')
        paper_mask = (saturation > 30).astype(np.uint8) * 255
        color_pixels = np.sum(paper_mask > 0)
        color_ratio = color_pixels / (h * w)
        
        # 如果彩色像素太少（<10%），可能不是彩色票据，跳过边界净化
        if color_ratio < 0.10:
            _log(f"  [边界净化] 彩色像素占比 {color_ratio*100:.1f}% < 10%，非彩色票据，跳过")
            return result
        
        _log(f"  [边界净化] 有色纸张: {color_pixels} 像素 ({color_ratio*100:.1f}%)")
        
        # ============================================================
        # 步骤2：形态学处理 - 精确定位票据边界
        # ============================================================
        # 2.1 腐蚀去噪点（去除边缘的彩色杂点）
        kernel_erode = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_MEDIUM), self._scale_r(cfg.MORPH_KERNEL_MEDIUM))
        paper_eroded = cv2.erode(paper_mask, kernel_erode, iterations=2)
        
        # 2.2 闭运算填充票据内的空洞（文字区域等）
        kernel_close = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_XXLARGE), self._scale_r(cfg.MORPH_KERNEL_XXLARGE))
        paper_closed = cv2.morphologyEx(paper_eroded, cv2.MORPH_CLOSE, kernel_close)
        
        # 2.3 最后腐蚀收紧边界（关键！让边界贴合票据）
        kernel_shrink = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_SMALL), self._scale_r(cfg.MORPH_KERNEL_SMALL))
        paper_closed = cv2.erode(paper_closed, kernel_shrink, iterations=3)
        
        # ============================================================
        # 步骤3：找最大连通区域的外接矩形
        # ============================================================
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(paper_closed, connectivity=8)
        
        receipt_rect = None
        if num_labels > 1:
            areas = stats[1:, cv2.CC_STAT_AREA]
            if len(areas) > 0:
                max_label = np.argmax(areas) + 1
                max_area = areas[max_label - 1]
                
                # 最大区域至少占5%才认为是票据
                if max_area > 0.05 * h * w:
                    x = stats[max_label, cv2.CC_STAT_LEFT]
                    y = stats[max_label, cv2.CC_STAT_TOP]
                    bw = stats[max_label, cv2.CC_STAT_WIDTH]
                    bh = stats[max_label, cv2.CC_STAT_HEIGHT]
                    receipt_rect = (x, y, x + bw, y + bh)
                    _log(f"  [边界净化] 票据矩形: ({x},{y}) - ({x+bw},{y+bh}), 尺寸: {bw}x{bh}")
        
        if receipt_rect is None:
            _log(f"  [边界净化] 未检测到有效票据区域，跳过")
            return result
        
        # ============================================================
        # 步骤4：创建保护区域（精确到票据边界，不扩展）
        # ============================================================
        x1, y1, x2, y2 = receipt_rect
        receipt_mask = np.zeros((h, w), dtype=np.uint8)
        receipt_mask[y1:y2, x1:x2] = 255
        
        # ============================================================
        # 步骤5：红色印章保护（可能盖在票据外面）
        # ============================================================
        red_seal = ((hue < 10) | (hue > 170)) & (saturation > 80)
        red_seal_dilated = cv2.dilate(red_seal.astype(np.uint8) * 255,
                                       kernel_cache.get_ellipse(self._scale_r(cfg.MORPH_KERNEL_XLARGE)),
                                       iterations=2)
        
        # ============================================================
        # 步骤6：边界外强力净化
        # ============================================================
        # 外部区域 = 不在票据矩形内 且 不是红色印章
        outside = (receipt_mask == 0) & (red_seal_dilated == 0)
        
        # 全部刷白
        result[outside] = (255, 255, 255)
        
        outside_pixels = np.sum(outside)
        seal_protected = np.sum((receipt_mask == 0) & (red_seal_dilated > 0))
        _log(f"  [边界净化] 外部区域: {outside_pixels} 像素 ({100*outside_pixels/(h*w):.1f}%)")
        if seal_protected > 0:
            _log(f"  [边界净化] 边界外印章保护: {seal_protected} 像素")
        
        # ============================================================
        # 保存调试图片（可选）
        # ============================================================
        if save_debug:
            import os
            os.makedirs(debug_path, exist_ok=True)
            import time
            ts = int(time.time() * 1000)
            
            cv2.imwrite(f"{debug_path}/{ts}_1_paper_mask.jpg", paper_mask)
            cv2.imwrite(f"{debug_path}/{ts}_2_paper_closed.jpg", paper_closed)
            
            debug_img = image.copy()
            debug_img[outside] = [0, 0, 255]
            cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 3)
            cv2.imwrite(f"{debug_path}/{ts}_3_outside.jpg", debug_img)
            cv2.imwrite(f"{debug_path}/{ts}_4_result.jpg", result)
            
            _log(f"  [边界净化] 调试图片已保存: {debug_path}/{ts}_*.jpg")
        
        return result
    def _detect_color_receipt(self, image: np.ndarray, cache: 'ImageCache') -> tuple:
        """
        检测图片是否为彩色票据
        
        彩色票据特点：
        1. 整张图片就是一张票据（不是粘贴在A4纸上的）
        2. 包含大量彩色内容（饱和度 > 阈值的像素占比超过配置值）
        
        Args:
            image: BGR 格式的图片数组
            cache: 图像缓存对象
            
        Returns:
            tuple: (is_color_receipt, color_ratio)
                - is_color_receipt: 是否为彩色票据
                - color_ratio: 彩色像素占比
        """
        h, w = image.shape[:2]
        total_pixels = h * w
        
        # 使用缓存的 HSV 通道
        hue, saturation, value = cache.get_hsv_channels()
        
        # xuechong 2026-06-30 获取配置（统一使用 config.py 定义的阈值 0.15）
        color_receipt_threshold = getattr(cfg, 'COLOR_RECEIPT_THRESHOLD', 0.15)
        full_s_threshold = getattr(cfg, 'FULL_COLOR_SATURATION_THRESHOLD', 20)
        v_min = getattr(cfg, 'COLOR_VALUE_MIN', 30)
        v_max = getattr(cfg, 'COLOR_VALUE_MAX', 250)
        
        # 计算彩色像素数量
        # 彩色像素：饱和度 > 阈值 且 亮度在合理范围内
        color_pixels = np.sum((saturation > full_s_threshold) & (value > v_min) & (value < v_max))
        color_ratio = color_pixels / total_pixels

        is_color_receipt = color_ratio >= color_receipt_threshold

        # xuechong 2026-06-01 饱和度中位数回退检测：解决高亮彩色票据漏判问题
        # 当纸张本身有颜色但 V 值偏高时（如黄色票据 V 频繁 > 250），
        # 标准 S+V 检测会严重低估彩色像素占比，导致彩色票据漏判进入普通文档路径
        # 饱和度中位数独立于 V 值，能准确反映纸张是否整体偏色：
        #   - 白底文档：中位数 S ≈ 0-5
        #   - 彩色票据：中位数 S ≈ 50-100+
        # 注意：_process_color_receipt() 内部有 strict_color_ratio<10% 的二次校验，
        # 误判的白底文档会在那里被安全回退到普通文档模式
        if not is_color_receipt:
            sat_median = float(np.median(saturation))
            if sat_median > 30:
                is_color_receipt = True
                _log(f"  [彩色票据检测] S+V占比仅{color_ratio*100:.1f}%，但饱和度中位数{sat_median:.0f}>30，判定为彩色票据")

        return is_color_receipt, color_ratio

    def _process_color_receipt(self, image: np.ndarray, skew_angle: float, 
                                page_rotation: int = 0, debug: bool = False) -> dict:
        """
        彩色票据专用处理模式
        
        检测票据的矩形边界，边界内完全保护，边界外强力净化
        
        Args:
            image: BGR 格式的图片数组
            skew_angle: 倾斜矫正角度
            page_rotation: 页面旋转角度（90度倍数）
            debug: 是否返回调试信息
            
        Returns:
            dict: 包含处理结果和各阶段掩码
        """
        h, w = image.shape[:2]
        result = image.copy()
        
        _log(f"  [彩色票据模式] 启用彩色票据保护模式")
        _log(f"  [彩色票据模式] 图像尺寸: {w}x{h}")
        
        # 转换颜色空间
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # ============================================================
        # 步骤1：检测票据边界
        # ============================================================
        # 优先使用纸张亮度方法（大尺度模糊 + Otsu），适用于白色/浅色票据纸张
        # 失败时回退到投影法（综合饱和度 + 灰度内容）

        receipt_mask = np.zeros((h, w), dtype=np.uint8)
        color_region = (saturation > 20)  # 用于后面返回
        boundary_detected = False

        # 1.0 先尝试纸张亮度方法
        if self.config.get('ENABLE_RECEIPT_BOUNDARY_BY_TEXTURE', True):
            paper_rect = self._find_receipt_boundary_by_texture(gray)
            if paper_rect is not None:
                px, py, pcw, pch = paper_rect
                # 安全检查：如果边界占比 < 60%，说明纹理方法可能误将
                # 普通文档的内容区域当成了票据，跳过以避免误删大量内容
                paper_area_ratio = pcw * pch / (h * w)
                if paper_area_ratio < 0.60:
                    _log(f"  [彩色票据模式] 纸张边界过小({paper_area_ratio*100:.1f}%)，"
                         f"疑似普通文档误检，回退到投影法")
                else:
                    receipt_mask[py:py+pch, px:px+pcw] = 255
                    boundary_detected = True
                    receipt_area = pcw * pch
                    _log(f"  [彩色票据模式] 纸张方法 - 票据边界: ({px},{py}) 尺寸={pcw}x{pch}")
                    _log(f"  [彩色票据模式] 票据尺寸: {pcw}x{pch} ({100*receipt_area/(h*w):.1f}%)")

        # 1.1 纸张方法失败，回退到投影法
        if not boundary_detected:
            # 创建综合内容掩码（彩色区域 + 深色文字/图形）
            content_mask = (saturation > 30) | (gray < 200)
            content_pixels = np.sum(content_mask)
            _log(f"  [彩色票据模式] 内容像素: {content_pixels} ({100*content_pixels/(h*w):.1f}%)")

            # 使用水平和垂直投影确定文档边界
            row_content = np.sum(content_mask, axis=1) / w
            col_content = np.sum(content_mask, axis=0) / h

            density_threshold = 0.05
            content_rows = np.where(row_content > density_threshold)[0]
            content_cols = np.where(col_content > density_threshold)[0]

            if len(content_rows) > 0 and len(content_cols) > 0:
                margin = 20
                y_min = max(0, content_rows[0] - margin)
                y_max = min(h, content_rows[-1] + margin)
                x_min = max(0, content_cols[0] - margin)
                x_max = min(w, content_cols[-1] + margin)

                receipt_area = (y_max - y_min) * (x_max - x_min)

                if receipt_area > 0.05 * h * w:
                    receipt_mask[y_min:y_max, x_min:x_max] = 255
                    boundary_detected = True
                    _log(f"  [彩色票据模式] 投影法 - 票据边界: ({x_min},{y_min}) - ({x_max},{y_max})")
                    _log(f"  [彩色票据模式] 票据尺寸: {x_max-x_min}x{y_max-y_min} ({100*receipt_area/(h*w):.1f}%)")

        # 如果没有检测到明显的边界，需要判断处理策略
        boundary_detected = np.sum(receipt_mask > 0) > 0
        if not boundary_detected:
            # 边界检测失败，检查真正的彩色比例（使用更严格的阈值S>30）
            strict_color_ratio = np.sum(saturation > 30) / (h * w)

            if strict_color_ratio >= 0.10:  # 真正的彩色超过10%，是彩色票据
                # 保守策略：保护深色内容和彩色区域
                # 使用更宽松的灰度阈值(gray<230)保护浅色文字和表单元素
                _log(f"  [彩色票据模式] 未检测到边界，但彩色比例高({strict_color_ratio*100:.1f}%)，使用保守策略")

                # 保护深色/浅色文字（gray<230）和彩色区域（S>20）
                fallback_mask = (gray < 230) | (saturation > 20)
                receipt_mask = fallback_mask.astype(np.uint8) * 255

                # 使用膨胀扩展保护区，确保文字边缘也被保护
                kernel_dilate = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_MEDIUM), self._scale_r(cfg.MORPH_KERNEL_MEDIUM))
                receipt_mask = cv2.dilate(receipt_mask, kernel_dilate, iterations=2)

                protected_pixels = np.sum(receipt_mask > 0)
                _log(f"  [彩色票据模式] 保护区域: {protected_pixels} 像素 ({100*protected_pixels/(h*w):.1f}%)")
            else:
                # 彩色比例不高，可能是被误识别的普通文档
                # 返回None，让调用者使用普通文档模式处理
                _log(f"  [彩色票据模式] 未检测到边界，且彩色比例低({strict_color_ratio*100:.1f}%<10%)，回退到普通文档模式")
                return None  # 返回None表示需要用普通文档模式处理
        
        # ============================================================
        # 步骤2：边界外区域净化
        # ============================================================
        outside_receipt = receipt_mask == 0
        result[outside_receipt] = (255, 255, 255)
        
        outside_cleaned = np.sum(outside_receipt)
        _log(f"  [彩色票据模式] 背景净化: {outside_cleaned} 像素 ({100*outside_cleaned/(h*w):.1f}%)")
        
        # ============================================================
        # 步骤3：边界内的灰白背景也净化（可选）
        # ============================================================
        # 票据内部的浅灰色背景区域也净化成纯白
        # 条件：在票据内部、亮度很高（>240）、饱和度很低（<10）
        inside_bg = (receipt_mask > 0) & (gray > 240) & (saturation < 10)
        result[inside_bg] = (255, 255, 255)
        
        inside_bg_cleaned = np.sum(inside_bg)
        _log(f"  [彩色票据模式] 票据内背景净化: {inside_bg_cleaned} 像素 ({100*inside_bg_cleaned/(h*w):.1f}%)")
        
        total_cleaned = outside_cleaned + inside_bg_cleaned
        _log(f"  [彩色票据模式] 总计净化: {total_cleaned} 像素 ({100*total_cleaned/(h*w):.1f}%)")
        _log(f"  [彩色票据模式] 处理完成")
        
        # 用于返回的彩色掩码
        color_mask = (color_region.astype(np.uint8) * 255)
        
        return {
            'result': result,
            'original': image.copy() if debug else None,
            'noise_mask': np.zeros((h, w), dtype=np.uint8),
            'edge_mask': np.zeros((h, w), dtype=np.uint8),
            'punch_mask': np.zeros((h, w), dtype=np.uint8),
            'crease_mask': np.zeros((h, w), dtype=np.uint8),
            'protect_mask': receipt_mask,
            'seal_mask': np.zeros((h, w), dtype=np.uint8),
            'color_mask': color_mask,
            'receipt_mask': receipt_mask,
            'stray_line_mask': np.zeros((h, w), dtype=np.uint8),
            'dotline_protect': np.zeros((h, w), dtype=np.uint8),
            'line_protect': None,
            'frame_protect': None,
            'text_blob_protect': None,
            'enhanced_image': None,
            'vis_yolo': None,
            'vis_noise': None,
            'vis_receipt': None,
            'skew_angle': skew_angle,
            'page_rotation': page_rotation,
            'is_receipt': True,
            'is_color_receipt': True,
        }

    def _process_receipt_document(self, image: np.ndarray, receipt_mask: np.ndarray, 
                                     skew_angle: float, page_rotation: int = 0,
                                     debug: bool = False) -> dict:
        """
        单据/票据专用处理模式
        
        完全保护单据区域内的所有内容，仅对外部A4纸背景进行刷白
        但要用OCR检测并保护背景区域中的文字（避免误删）
        
        Args:
            image: BGR 格式的图片数组
            receipt_mask: 单据区域掩码（255=单据区域，0=背景）
            skew_angle: 倾斜矫正角度
            page_rotation: 页面旋转角度（90度倍数）
            debug: 是否返回调试信息
            
        Returns:
            dict: 包含处理结果和各阶段掩码
        """
        h, w = image.shape[:2]
        result = image.copy()
        
        _log(f"  [单据模式] 启用单据/票据专用处理模式")
        _log(f"    原单据区域(饱和度): {np.sum(receipt_mask > 0)} 像素 ({100*np.sum(receipt_mask > 0)/(h*w):.1f}%)")

        # xuechong 2026-08-19 研发BUG-0027-图档扫描-3.1.06-票据单据区分判定逻辑优化
        # 保存并入纸界前的原始彩色区域面积（REQ-001 重叠率分母 / REQ-002 彩域占比共用）
        _orig_color_area = int(np.sum(receipt_mask > 0))

        # 尝试用纸张亮度方法获取完整纸张边界（包含白色空白区域）
        paper_boundary_used = False
        gray_for_paper = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        paper_rect = self._find_receipt_boundary_by_texture(gray_for_paper)
        if paper_rect is not None:
            px, py, pcw, pch = paper_rect
            paper_full_mask = np.zeros((h, w), dtype=np.uint8)
            paper_full_mask[py:py+pch, px:px+pcw] = 255

            # xuechong 2026-08-19 研发BUG-0027-图档扫描-3.1.06-票据单据区分判定逻辑优化
            # REQ-001 纸张边界并入前与彩色区域重叠校验（治本例 002.tif 表格误判）：
            # 真票据的纸界与彩域是同一张纸，重叠必然高（实测票据-粉色 0.997/票据-绿色 0.999）；
            # 普通文档误入单据模式时，纸界（密集印刷区重模糊后整体偏暗被当成"暗色纸张"）与
            # 彩域（彩色印刷条带/标题）位置零重叠（实测 002.tif 为 0.000）。
            # 重叠率低于阈值 → 两者不是同一张纸 → 拒绝并入，回退普通文档模式（core.py 既有回退链路）
            _paper_area = int(np.sum(paper_full_mask > 0))
            _overlap = int(np.sum(cv2.bitwise_and(receipt_mask, paper_full_mask) > 0))
            _overlap_ratio = _overlap / max(min(_orig_color_area, _paper_area), 1)
            if _overlap_ratio < cfg.RECEIPT_PAPER_OVERLAP_MIN_RATIO:
                _log(f"  [单据模式] ⚠ 纸张边界 ({px},{py}){pcw}x{pch} 与彩色区域重叠率 {_overlap_ratio:.3f}"
                     f" < {cfg.RECEIPT_PAPER_OVERLAP_MIN_RATIO}（零/近零重叠，非同一张纸）"
                     f"，拒绝并入并回退普通文档模式")
                return None

            # xuechong 2026-06-01 与饱和度mask取并集，而非替换
            # 纸张边界(Blur+Otsu)可能比饱和度mask小（如黄色票据边界模糊导致Otsu切分不准），
            # 替换会丢失饱和度mask中已正确标记的彩色票据区域，导致黄色纸张被误刷白
            # 并集策略：饱和度mask保护彩色区域，纸张边界补充白色空白区域（如票据内白边）
            receipt_mask = cv2.bitwise_or(receipt_mask, paper_full_mask)
            paper_boundary_used = True
            _log(f"  [单据模式] 纸张方法 - 完整票据边界: ({px},{py}) 尺寸={pcw}x{pch}")
            _log(f"    与饱和度mask并集后单据区域: {np.sum(receipt_mask > 0)} 像素 ({100*np.sum(receipt_mask > 0)/(h*w):.1f}%)")
        
        # ============================================================
        # 误判检测：单据掩码外存在大量内容时回退普通文档模式
        # ============================================================
        # 判定标准（双条件AND，确保真正票据不受影响）：
        #   1. 纸张边界面积占比 < 15%（真正票据+A4纸通常 >15%）
        #   2. 掩码外深色像素(gray<200)占比 > 2%（真票据掩码外 <1%，2%留2倍余量）
        # 依据：单个条形码≈0.15%~0.3%图片面积，单个标签文字≈0.5%~1%，
        #       2个以上标签在掩码外必然超过2%；真票据掩码外仅有扫描噪声 <1%
        paper_area_ratio = np.sum(receipt_mask > 0) / (h * w)
        if paper_area_ratio < 0.15:
            outside_pixels = gray_for_paper[receipt_mask == 0]
            outside_dark_count = np.sum(outside_pixels < 200)
            outside_dark_ratio = outside_dark_count / max(len(outside_pixels), 1)
            if outside_dark_ratio > 0.02:
                _log(f"  [单据模式] ⚠ 误判检测：纸张边界仅{paper_area_ratio*100:.1f}%，"
                     f"掩码外深色像素{outside_dark_ratio*100:.1f}%（阈值2%）")
                _log(f"  [单据模式] 掩码外存在大量文字/条形码内容，回退到普通文档模式")
                return None
            else:
                _log(f"  [单据模式] 纸张边界{paper_area_ratio*100:.1f}%，"
                     f"掩码外深色{outside_dark_ratio*100:.1f}%（正常）")
        
        # ============================================================
        # OCR文字保护：检测背景区域中的文字，避免误删
        # ============================================================
        ocr_protect_mask = np.zeros((h, w), dtype=np.uint8)
        if getattr(cfg, 'ENABLE_OCR_TEXT_PROTECT', True):
            try:
                ocr_engine = _get_cached_ocr_engine(960)
                
                # 缩放图片用于OCR检测
                scale = min(1.0, 960 / max(h, w))
                if scale < 1.0:
                    small_img = cv2.resize(image, None, fx=scale, fy=scale)
                else:
                    small_img = image
                    scale = 1.0
                
                # OCR检测
                ocr_result = ocr_engine(small_img, use_det=True, use_cls=False, use_rec=False)
                
                if ocr_result is not None and ocr_result.boxes is not None and len(ocr_result.boxes) > 0:
                    for box in ocr_result.boxes:
                        pts = np.array(box, dtype=np.float32) / scale
                        x_min = max(0, int(np.min(pts[:, 0])) - 5)
                        y_min = max(0, int(np.min(pts[:, 1])) - 5)
                        x_max = min(w, int(np.max(pts[:, 0])) + 5)
                        y_max = min(h, int(np.max(pts[:, 1])) + 5)
                        ocr_protect_mask[y_min:y_max, x_min:x_max] = 255
                    
                    _log(f"    [OCR保护] 检测到 {len(ocr_result.boxes)} 个文字区域")
            except Exception as e:
                import traceback
                _log(f"    [OCR保护] 检测异常: {e}（票据模式，继续处理）")
                _log(f"    [OCR保护] 详细堆栈:\n{traceback.format_exc()}")
                # 不中断管线，继续处理

        # ============================================================
        # 内容保护：保护单据区域外的所有有意义内容
        # xuechong 2026-08-07 研发BUG-0019 修复边界外文字被误删
        #   原逻辑在 paper_boundary_used=True 时跳过内容保护（假设边界外为扫描垃圾），
        #   但实际边界外可能有大量正常文字/表格（002.tif 边界外22万像素文字被刷白43.7%）
        #   修正：内容保护始终执行，保护边界外的深色文字/线条内容
        # ============================================================
        content_protect = np.zeros((h, w), dtype=np.uint8)
        # zhaoqiaotong 2026-09-17 研发BUG-0060 票外页码词组保护掩码（try 内检出，try 外并入 full_protect）
        _pn_protect = None
        try:
            gray_for_content = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

            # 1. 深色内容保护：灰度 < 200 的像素（文字、条形码、深色印章等）
            dark_content = (gray_for_content < 200).astype(np.uint8) * 255

            # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化
            # 修复票外大块扫描污染被内容保护误保（d001.tif 票据下方大块黑渍保留）：
            # 深色保护按连通域甄别"内容"与"扫描污染"——
            # ①面积甄别：真文字/条码/印章为小连通域（实测票外文字连片最大 21029px），
            #   黑渍/扫描黑框为巨型连通域（实测 16万~196万px，与真内容差 1~2 个数量级）；
            # ②形态甄别：票外孤立细长横线（高<=30 且长宽比>=10，如 d001 纸外黑线段
            #   348x14 aspect≈25）不是内容——文字块 aspect<=4.1（实测 827x201），
            #   细长线判据与文字完全可分。
            # 彩色印章保护通道不受影响；RECEIPT_OUTSIDE_CONTENT_MAX_AREA 置足够大（如 10^9）
            # 且线判据放宽即回退"全深色保护"现行行为。
            _n_cc, _labels_cc, _stats_cc, _ = cv2.connectedComponentsWithStats(dark_content, connectivity=8)
            _max_cc_area = getattr(cfg, 'RECEIPT_OUTSIDE_CONTENT_MAX_AREA', 50000)
            _cc_w = _stats_cc[1:, cv2.CC_STAT_WIDTH]
            _cc_h = _stats_cc[1:, cv2.CC_STAT_HEIGHT]
            _is_content = (_stats_cc[1:, cv2.CC_STAT_AREA] <= _max_cc_area) & \
                          ~((_cc_h <= 30) & (_cc_w / np.maximum(_cc_h, 1) >= 10))
            # 印章形状豁免：被上述判据剔除的域若呈规则形状（圆/椭圆/方，含残缺形态），
            # 且外接尺寸达到印章最小尺寸（默认120px≈300DPI 下10mm），判为疑似印章恢复保护
            # ——只有外边界不规则的深色块才放心抹除（用户确认的保护原则）。
            _seal_min_dim = getattr(cfg, 'SEAL_SHAPE_MIN_DIM', 120)
            for _j in np.nonzero(~_is_content)[0]:
                if max(_cc_w[_j], _cc_h[_j]) < _seal_min_dim:
                    continue
                _bx, _by, _bw, _bh = [int(v) for v in _stats_cc[_j + 1, :4]]
                _blob = (_labels_cc[_by:_by + _bh, _bx:_bx + _bw] == _j + 1).astype(np.uint8) * 255
                _shape, _score = self._blob_shape_regular(_blob)
                if _score >= 0.5:
                    _is_content[_j] = True
                    _log(f"    [内容保护] 票外规则形状域(疑似印章 {_shape} 分{_score:.2f} {_bw}x{_bh})恢复保护")
            _content_ids = np.nonzero(_is_content)[0] + 1
            dark_content = np.zeros((h, w), dtype=np.uint8)
            if _content_ids.size:
                dark_content[np.isin(_labels_cc, _content_ids)] = 255

            # 2. 彩色内容保护：高饱和度区域（红色/蓝色印章等，receipt_mask可能未覆盖）
            hsv_for_content = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            high_sat_content = (hsv_for_content[:, :, 1] > 40).astype(np.uint8) * 255

            # 合并深色+彩色内容
            content_protect = cv2.bitwise_or(dark_content, high_sat_content)

            # 膨胀保护：保护内容边缘，避免被部分擦除
            kernel_dilate = kernel_cache.get_ellipse(self._scale_r(cfg.MORPH_KERNEL_MEDIUM))
            content_protect = cv2.dilate(content_protect, kernel_dilate, iterations=2)

            # 只保护receipt_mask外部的内容（receipt_mask内部已经受保护）
            # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化
            # 距离判据：只保护票据 30px 邻域内的票外内容（紧贴票据的骑缝章/溢出文字等）；
            # 远离票据的孤立深色物（d001 纸外 150px 处的滚轴压痕黑线）= 扫描垃圾不保护。
            # 与 BUG-0019 案例兼容（票外文字紧贴纸缘）。
            # zhaoqiaotong 2026-09-17 研发BUG-0060 订正：上文"60px"系注释笔误，代码自引入起即 30px（_scale_r(30)）
            outside_receipt = cv2.bitwise_not(receipt_mask)
            _near_r = self._scale_r(30)
            _near_receipt = cv2.dilate(receipt_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_near_r * 2 + 1, _near_r * 2 + 1)))
            outside_receipt = cv2.bitwise_and(outside_receipt, _near_receipt)
            content_protect = cv2.bitwise_and(content_protect, outside_receipt)

            # zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
            # 票外页码词组保护（用户确认：页码不管在什么模式下都需要保留）：
            # 紧贴票底边的页码"- N -"字符骑在 30px 邻域带界上会留半截残迹（带内受保护、
            # 带外被背景刷白，BUG-0053 后续遗留）；远离票边的页码（>30px）在票外刷白
            # 设计下会被整体清除。词组形态判据（三段结构/等高/对齐/底部/居中）命中的
            # 页码词组并入 full_protect 完整保留（见背景刷白合并处）；漏检维持现状，
            # 骑缝章为高饱和内容走 high_sat 通道不受影响
            _pn_protect = self._detect_pagenum_phrase_outside(gray_for_content, receipt_mask)
            if _pn_protect is not None:
                _log(f"    [内容保护] 票外页码词组保护 {int(np.sum(_pn_protect > 0))} 像素（页码全模式保留）")

            protected_pixels = np.sum(content_protect > 0)
            if protected_pixels > 0:
                _log(f"    [内容保护] 保护单据区域外 {protected_pixels} 像素内容（文字/条形码/印章等）")
        except Exception as e:
            import traceback
            _log(f"    [内容保护] 检测异常: {e}（票据模式，继续处理）")
            _log(f"    [内容保护] 详细堆栈:\n{traceback.format_exc()}")
            # 不中断管线，继续处理

        # ============================================================
        # V3.1.01 xuechong 2026-07-25 印章和彩色区域保护（始终执行，不依赖paper_boundary_used）
        # 印章/彩色元素可能位于receipt_mask边界外（如骑缝章、溢出盖章等），
        # 必须独立保护，避免被背景刷白清除
        # ============================================================
        seal_mask = np.zeros((h, w), dtype=np.uint8)
        color_mask = np.zeros((h, w), dtype=np.uint8)
        try:
            # HSV转换（用于印章和彩色区域检测）
            hsv_img = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            hue = hsv_img[:, :, 0]
            saturation = hsv_img[:, :, 1]
            value = hsv_img[:, :, 2]

            # 1. 红色印章保护（与 protect.py _detect_seals_and_colors 一致）
            if cfg.ENABLE_SEAL_PROTECTION:
                red_seal = (((hue < cfg.SEAL_RED_H1_HIGH) | (hue > cfg.SEAL_RED_H2_LOW))
                            & (saturation > cfg.SEAL_S_LOW)
                            & (value > cfg.SEAL_V_LOW))
                seal_mask = cv2.dilate(
                    red_seal.astype(np.uint8) * 255,
                    kernel_cache.get_ellipse(self._scale_r(cfg.MORPH_KERNEL_XLARGE)),
                    iterations=cfg.SEAL_DILATE_ITERATIONS
                )
                seal_pixels = np.sum(seal_mask > 0)
                if seal_pixels > 0:
                    _log(f"    [印章保护] 保护红色印章区域 {seal_pixels} 像素")

            # 2. 彩色区域保护（与 protect.py 全色域保护一致，含亮度过滤）
            if config_cache.get('ENABLE_COLOR_PROTECTION', True):
                v_min = config_cache.get('COLOR_VALUE_MIN', 30)
                v_max = config_cache.get('COLOR_VALUE_MAX', 250)
                color_region = (saturation > config_cache.get('COLOR_VALUE_MIN', 30)) & (value > v_min) & (value < v_max)
                color_mask = cv2.dilate(
                    color_region.astype(np.uint8) * 255,
                    kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_MEDIUM), self._scale_r(cfg.MORPH_KERNEL_MEDIUM)),
                    iterations=1
                )
                color_pixels = np.sum(color_mask > 0)
                if color_pixels > 0:
                    _log(f"    [彩色保护] 保护彩色区域 {color_pixels} 像素")
        except Exception as e:
            import traceback
            _log(f"    [印章/彩色保护] 检测异常: {e}（继续处理）")
            _log(f"    [印章/彩色保护] 详细堆栈:\n{traceback.format_exc()}")

        # xuechong 2026-08-07 研发BUG-0017 修复票据外部彩色噪点未清理
        # xuechong 2026-08-07 研发BUG-0019 修复票据边界裁剪误切真实印章
        #   BUG-0017原方案一刀切裁掉边界外所有印章/彩色保护，导致边界外的真实印章被误切
        #   （002.tif 15个红色印章消失，含2个大印章 area=43983/16535）
        #   修正：用连通域面积过滤，只裁剪散落的小面积噪点，保留大连通域（真实印章/彩色内容）
        if paper_boundary_used:
            _margin = self._scale_r(15)
            _kernel = kernel_cache.get_rect(_margin, _margin)
            receipt_expanded = cv2.dilate(receipt_mask, _kernel, iterations=1)
            outside_receipt_exp = cv2.bitwise_not(receipt_expanded)

            # OCR保护：直接裁剪（票据外文字为扫描噪声）
            ocr_outside = np.sum(cv2.bitwise_and(ocr_protect_mask, outside_receipt_exp) > 0)
            ocr_protect_mask = cv2.bitwise_and(ocr_protect_mask, receipt_expanded)

            # 印章/彩色保护：连通域面积过滤，保留真实印章，只裁剪小面积噪点
            _noise_threshold = max(500, int(self._scale_r(20) ** 2))
            for _mask_name, _mask_var in [('seal', seal_mask), ('color', color_mask)]:
                _outside_part = cv2.bitwise_and(_mask_var, outside_receipt_exp)
                _outside_total = int(np.sum(_outside_part > 0))
                if _outside_total == 0:
                    continue
                _n_cc, _labels_cc, _stats_cc, _ = cv2.connectedComponentsWithStats(_outside_part, connectivity=8)
                # 向量化面积过滤：用查找表避免逐连通域循环（性能优化，避免数万连通域遍历）
                _keep_lut = np.ones(_n_cc, dtype=np.uint8)
                _areas = _stats_cc[1:, cv2.CC_STAT_AREA]
                _small_labels = np.where(_areas < _noise_threshold)[0] + 1
                _keep_lut[_small_labels] = 0
                # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化
                # 票外保留的大域加"域平均饱和度"下限：真彩色内容（印章/彩纸延伸）平均 S 高
                # （实测粉纸≈115、印章更高），黑线/晕影借彩色膨胀混入的域平均 S 低（黑线≈15）。
                # 域平均 S < 50 视为非彩色内容（扫描污染）一并裁剪；真印章不受影响。
                _sat_plane = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1]
                _domain_sat = np.bincount(_labels_cc.ravel(),
                                          weights=_sat_plane.ravel().astype(np.float64),
                                          minlength=_n_cc)
                _domain_cnt = np.bincount(_labels_cc.ravel(), minlength=_n_cc)
                _avg_sat = np.where(_domain_cnt > 0, _domain_sat / np.maximum(_domain_cnt, 1), 0)
                _low_sat_labels = np.where(_avg_sat < 50)[0]
                _low_sat_labels = _low_sat_labels[_low_sat_labels > 0]
                _keep_lut[_low_sat_labels] = 0
                _large_count = _n_cc - 1 - len(_small_labels) - len([x for x in _low_sat_labels if x not in _small_labels])
                # zhaoqiaotong 2026-09-14 研发BUG-0053-图档扫描-3.2.11-修复编辑PDF模块带页码单据修图异常
                # 噪点裁剪块自efa02806（研发BUG-0017/0019）起本在for循环体内逐mask执行；f75c8d03
                # （研发BUG-0030）在循环后插入低饱和剔除块时未同步移动本块，使其悬挂到循环外if块内：
                # 两mask票外均无像素时_keep_lut等未定义，遇票外低饱和暗像素（如页码"- N -"）即抛
                # UnboundLocalError（带页码单据修图必崩），且逐mask裁剪语义自3.1.08起静默失效。移回循环内恢复原始行为。
                _outside_pixels = _outside_part > 0
                _noise_mask = ((_keep_lut[_labels_cc] == 0) & _outside_pixels).astype(np.uint8) * 255
                _noise_pixels = int(np.sum(_noise_mask > 0))
                if _noise_pixels > 0:
                    if _mask_name == 'seal':
                        seal_mask = cv2.bitwise_and(seal_mask, cv2.bitwise_not(_noise_mask))
                    else:
                        color_mask = cv2.bitwise_and(color_mask, cv2.bitwise_not(_noise_mask))
                    _log(f"    [票据边界裁剪] {_mask_name}裁掉噪点{_noise_pixels}像素，保留{_large_count}个大连通域（真实印章/内容）")

            # xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化
            # 票外低饱和深色像素从印章/彩色保护剔除（像素级，防域平均被粉色稀释）：
            # 纸缘晕影/黑线（S<50 且 V<150）借彩色膨胀混入 seal/color 通道被保留（d001 实证）；
            # 红章/粉纸像素 S 高不受影响；票外黑文字仍由 content_protect（带甄别）保护。
            # 印章形状豁免：剔除前对低饱和深色域做形状判别，规则形状（圆/椭圆/方）疑似印章不剔。
            _hsv_out = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            _lowsat_dark = ((_hsv_out[:, :, 1] < 50) & (_hsv_out[:, :, 2] < 150)).astype(np.uint8) * 255
            _lowsat_outside = cv2.bitwise_and(_lowsat_dark, outside_receipt_exp)
            if int(np.sum(_lowsat_outside > 0)) > 0:
                _ls_n, _ls_lab, _ls_st, _ = cv2.connectedComponentsWithStats(_lowsat_outside, connectivity=8)
                _seal_min_dim = getattr(cfg, 'SEAL_SHAPE_MIN_DIM', 120)
                _ls_keep = np.zeros(_ls_n, dtype=bool)
                _ls_keep[0] = True  # 背景不剔
                for _j in range(1, _ls_n):
                    _bw, _bh = int(_ls_st[_j, cv2.CC_STAT_WIDTH]), int(_ls_st[_j, cv2.CC_STAT_HEIGHT])
                    if max(_bw, _bh) < _seal_min_dim:
                        continue
                    _bx, _by = int(_ls_st[_j, cv2.CC_STAT_LEFT]), int(_ls_st[_j, cv2.CC_STAT_TOP])
                    _blob = (_ls_lab[_by:_by + _bh, _bx:_bx + _bw] == _j).astype(np.uint8) * 255
                    _shape, _score = self._blob_shape_regular(_blob)
                    if _score >= 0.5:
                        _ls_keep[_j] = True
                        _log(f"    [印章/彩色保护] 票外规则形状域(疑似印章 {_shape} 分{_score:.2f})不剔除")
                _lowsat_outside = np.where(_ls_keep[_ls_lab], 0, 255).astype(np.uint8)
                _lowsat_outside = cv2.bitwise_and(_lowsat_outside, _lowsat_dark)
                _cut_px = int(np.sum((cv2.bitwise_and(cv2.bitwise_or(seal_mask, color_mask), _lowsat_outside) > 0)))
                seal_mask = cv2.bitwise_and(seal_mask, cv2.bitwise_not(_lowsat_outside))
                color_mask = cv2.bitwise_and(color_mask, cv2.bitwise_not(_lowsat_outside))
                _log(f"    [票据边界裁剪] 印章/彩色保护剔除票外低饱和深色 {_cut_px} 像素（晕影/黑线）")

            if ocr_outside > 0:
                _log(f"    [票据边界裁剪] OCR裁掉{ocr_outside}像素（票据外文字）")

        # 合并保护区：单据区域 + OCR文字区域 + 外部内容保护 + 印章 + 彩色区域
        full_protect = cv2.bitwise_or(receipt_mask, ocr_protect_mask)
        full_protect = cv2.bitwise_or(full_protect, content_protect)
        full_protect = cv2.bitwise_or(full_protect, seal_mask)
        full_protect = cv2.bitwise_or(full_protect, color_mask)
        # zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
        # 页码词组保护并入：用户确认页码不管在什么模式下都需要保留（紧贴票边半截残迹
        # 与远离票边整体清除两种形态一并解决）
        if _pn_protect is not None:
            full_protect = cv2.bitwise_or(full_protect, _pn_protect)

        # TEMP-DEBUG 研发BUG-0030 票外黑渍通道定位插桩（用后即删）

        # 背景区域 = 非保护区
        background_mask = full_protect == 0
        
        # 刷白背景区域
        result[background_mask] = (255, 255, 255)
        
        background_pixels = np.sum(background_mask)
        _log(f"    背景刷白: {background_pixels} 像素 ({100*background_pixels/(h*w):.1f}%)")

        # xuechong 2026-08-19 研发BUG-0027-图档扫描-3.1.06-票据单据区分判定逻辑优化
        # REQ-002 单据底色近白时纸内背景白化兜底：黑白打印单据误入单据模式时，
        # 纸内 250-254 近白底色与外部刷白 255 形成肉眼可见色差，此处把纸内"接近底色
        # 且无彩色且未被任何保护覆盖"的像素统一白化到 255（noteshrink 思路）。
        # 红线（b001/b002 教训）：彩色底票据不得触发白化，行为与修改前完全一致。
        # 双重判定（缺一不可，防止单一条件失效）：
        #   ①单据区【整体】（含彩色保护区）中位饱和度<20 且中位亮度>230——必须用整体采样：
        #     彩色票据的彩色底已被 color_mask 保护，"未保护像素"中位S恒为0，会导致粉/绿票据被
        #     误判为黑白单据（实测教训，第一版即踩此坑：票据-粉色被误白化 40 万像素）；
        #   ②原始彩色区域占单据区比例<0.3——彩色票据彩域≈纸界（实测粉 99.98%/绿 99.9%），
        #     占比高即为彩色纸；002 类误判图彩域仅为彩色印刷条带（18.8%）。
        # 开关 RECEIPT_NEARWHITE_WHITEN（config.py）可整体关闭本兜底而不影响 REQ-001 重叠校验。
        if cfg.RECEIPT_NEARWHITE_WHITEN:
            try:
                _region_nw = receipt_mask > 0
                _region_area_nw = int(np.sum(_region_nw))
                if _region_area_nw > 0:
                    _hsv_nw = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
                    _med_s_nw = float(np.median(_hsv_nw[:, :, 1][_region_nw]))
                    _med_v_nw = float(np.median(_hsv_nw[:, :, 2][_region_nw]))
                    _color_ratio_nw = _orig_color_area / _region_area_nw
                    if _med_s_nw < 20 and _med_v_nw > 230 and _color_ratio_nw < 0.3:
                        # 纸内未保护像素 = 单据区域内未被 OCR文字/印章/彩色保护覆盖的部分
                        _inner_protect_nw = cv2.bitwise_or(ocr_protect_mask, seal_mask)
                        _inner_protect_nw = cv2.bitwise_or(_inner_protect_nw, color_mask)
                        _v_dev_nw = np.abs(_hsv_nw[:, :, 2].astype(np.int16) - int(_med_v_nw))
                        _near_bg_nw = _region_nw & (_inner_protect_nw == 0) & \
                                      (_hsv_nw[:, :, 1] < 25) & (_v_dev_nw < 20)
                        _near_count_nw = int(np.sum(_near_bg_nw))
                        if _near_count_nw > 0:
                            result[_near_bg_nw] = (255, 255, 255)
                            _log(f"    [单据近白白化] 黑白打印单据（整体中位S={_med_s_nw:.0f} V={_med_v_nw:.0f} "
                                 f"彩域占比{_color_ratio_nw*100:.1f}%），纸内近底色白化 {_near_count_nw} 像素 "
                                 f"({100*_near_count_nw/(h*w):.1f}%)")
                    else:
                        _log(f"    [单据近白白化] 彩色底单据（整体中位S={_med_s_nw:.0f} V={_med_v_nw:.0f} "
                             f"彩域占比{_color_ratio_nw*100:.1f}%），跳过白化")
            except Exception as _e_nw:
                _log(f"    [单据近白白化] 异常: {_e_nw}（跳过）")

        # xuechong 2026-08-07 研发BUG-0018 票据内部散点灰噪清理
        # receipt_mask 覆盖整个票据区域（含背景纸），背景纸上的纯灰散点噪声未被清理
        # 严格限制条件：仅清理低饱和度(无颜色S<25) + 远离深色内容 + 未被任何保护掩码覆盖的像素
        # 注意：必须保留 color_mask 保护，否则黄色/彩色票据底色会被误清（b001/b002教训）
        try:
            _content_all = cv2.bitwise_or(ocr_protect_mask, seal_mask)
            _content_all = cv2.bitwise_or(_content_all, color_mask)
            _content_all = cv2.bitwise_or(_content_all, content_protect)
            _gray_ir = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            _hsv_ir = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
            _sat_ir = _hsv_ir[:, :, 1]
            _dark_ir = _gray_ir < 180
            _kernel_ir = kernel_cache.get_rect(self._scale_r(2), self._scale_r(2))
            _dark_dil_ir = cv2.dilate(_dark_ir.astype(np.uint8), _kernel_ir, iterations=2)
            _interior_noise = ((_content_all == 0) &
                               (_sat_ir < 25) &
                               (_gray_ir >= 210) & (_gray_ir < 250) &
                               (_dark_dil_ir == 0))
            _interior_count = int(np.sum(_interior_noise))
            if _interior_count > 0:
                result[_interior_noise] = (255, 255, 255)
                _log(f"    [票据内部清理] 清除纯灰噪 {_interior_count} 像素 ({100*_interior_count/(h*w):.1f}%)")
        except Exception as _e_ir:
            _log(f"    [票据内部清理] 异常: {_e_ir}（跳过）")

        # ============================================================
        # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
        # REQ-005 票据边缘带浅色划痕修补（ae/014 实测：底边链轮孔排旁纸张划伤呈浅白细长痕）。
        # 四重防护防误清内容：①仅限票据边缘带（票据 bbox 向内 100px 环带——表格/标题/文字
        # 都在票据中部）；②浅色异常（V 高于票据底色中位 +35 且 S<40，露白划痕特征）；
        # ③细长或小面积（细长比≥3 或 面积≤1500，排除白色印刷栏目等大块）；④远离深色内容
        # （表格线/文字膨胀 30px 外）。填充色取划痕膨胀环带的底色中值，非纯白，保持票据观感。
        # ============================================================
        if getattr(cfg, 'ENABLE_RECEIPT_SCRATCH_FIX', False):
            try:
                _hsv_fx = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
                _v_fx = _hsv_fx[:, :, 2]
                _s_fx = _hsv_fx[:, :, 1]
                _rx, _ry, _rw, _rh = cv2.boundingRect(cv2.findNonZero(receipt_mask))
                _band = self._scale_r(150)
                _edge = np.zeros((h, w), dtype=np.uint8)
                _edge[_ry:_ry + _rh, _rx:_rx + _rw] = 255
                _edge_in = cv2.erode(_edge, kernel_cache.get_rect(_band * 2 + 1, _band * 2 + 1))
                _edge_band = cv2.subtract(_edge, _edge_in)
                _v_med = float(np.median(_v_fx[receipt_mask > 0]))
                # ae/014 实测：粉底 V 中位 231，划痕露白 V≈250，差值仅 ~20，阈值取 +12；
                # 露白划痕带粉色染色（S 40~80），S 上限取 70（粉底 S≈100 仍排除）
                _pale = ((receipt_mask > 0) & (_edge_band > 0) &
                         (_v_fx > _v_med + 12) & (_s_fx < 70)).astype(np.uint8) * 255
                _n_fx, _lab_fx, _st_fx, _ = cv2.connectedComponentsWithStats(_pale, connectivity=8)
                _keep_fx = np.zeros(_n_fx, dtype=bool)
                for _j in range(1, _n_fx):
                    _a, _cw, _ch = int(_st_fx[_j, cv2.CC_STAT_AREA]), int(_st_fx[_j, cv2.CC_STAT_WIDTH]), int(_st_fx[_j, cv2.CC_STAT_HEIGHT])
                    if _a < 30 or _a > 8000:
                        continue
                    if not (max(_cw, _ch) / max(min(_cw, _ch), 1) >= 3 or _a <= 1500):
                        continue
                    _bx, _by = int(_st_fx[_j, cv2.CC_STAT_LEFT]), int(_st_fx[_j, cv2.CC_STAT_TOP])
                    _blob = (_lab_fx[_by:_by + _ch, _bx:_bx + _cw] == _j).astype(np.uint8) * 255
                    _blob_d = cv2.dilate(_blob, kernel_cache.get_rect(self._scale_r(10), self._scale_r(10)))
                    _gray_roi = cv2.cvtColor(result[_by:_by + _ch, _bx:_bx + _cw], cv2.COLOR_BGR2GRAY)
                    _near_dark = (_gray_roi < 120) & (_blob_d > 0)
                    if int(np.sum(_near_dark)) > _a * 0.5:
                        continue  # 邻近深色笔画/框线，非孤立划痕
                    _keep_fx[_j] = True
                if np.any(_keep_fx):
                    _fix_ids = np.nonzero(_keep_fx)[0] + 1
                    _fix_mask = np.isin(_lab_fx, _fix_ids)
                    _fix_mask = cv2.dilate(_fix_mask.astype(np.uint8) * 255,
                                           kernel_cache.get_ellipse(self._scale_r(3)), iterations=1) > 0
                    _fix_mask = _fix_mask & (receipt_mask > 0)
                    # 底色填充：划痕外扩环带的票据底色中值
                    _ring = cv2.dilate(_fix_mask.astype(np.uint8) * 255,
                                       kernel_cache.get_rect(self._scale_r(8), self._scale_r(8)))
                    _ring_px = result[(_ring > 0) & (~_fix_mask) & (receipt_mask > 0)]
                    if len(_ring_px) > 0:
                        _fill = np.median(_ring_px, axis=0)
                        result[_fix_mask] = _fill
                        _log(f"    [划痕修补] 票据边缘带浅色划痕 {len(_fix_ids)} 处（{int(np.sum(_fix_mask))} 像素），"
                             f"底色填充 BGR={_fill.astype(int)}")
            except Exception as _e_fx:
                _log(f"    [划痕修补] 异常: {_e_fx}（跳过）")

        _log(f"  [单据模式] 处理完成")
        
        # 创建可视化图（debug模式）
        vis_receipt = None
        if debug:
            vis_receipt = image.copy()
            # 用绿色边框标记单据区域
            contours, _ = cv2.findContours(receipt_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(vis_receipt, contours, -1, (0, 255, 0), 3)
        
        return {
            'result': result,
            'original': image.copy() if debug else None,
            'noise_mask': np.zeros((h, w), dtype=np.uint8),
            'edge_mask': np.zeros((h, w), dtype=np.uint8),
            'punch_mask': np.zeros((h, w), dtype=np.uint8),
            'crease_mask': np.zeros((h, w), dtype=np.uint8),
            'protect_mask': receipt_mask,  # 单据区域作为保护区
            'seal_mask': seal_mask,
            'color_mask': color_mask,
            'receipt_mask': receipt_mask,  # 单据区域掩码
            'dotline_protect': np.zeros((h, w), dtype=np.uint8),
            'line_protect': None,
            'frame_protect': None,
            'text_blob_protect': None,
            'enhanced_image': None,
            'vis_yolo': None,
            'stray_line_mask': np.zeros((h, w), dtype=np.uint8),
            'vis_noise': None,
            'vis_receipt': vis_receipt,  # 单据检测可视化
            'skew_angle': skew_angle,
            'page_rotation': page_rotation,  # 页面旋转角度（90度倍数）
            'is_receipt': True,  # 标记为单据模式
            'is_color_receipt': False,
        }

    # zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
    # 票外页码词组检测：在票外底部区域寻找"- N -"形态词组（与 BUG-0052 旧页码
    # 检测、BUG-0060 散点豁免同思路：词组外形+底部+居中多重判据，宁漏检不误删）。
    # 检测范围用"底部15%∩票外"而非30px邻域带——紧贴页码的连字符位于词组底部、
    # 落在邻域带外，限定带内会拼不齐三段结构导致漏检。
    # 检出返回词组 bbox 掩码（调用方并入 full_protect 完整保留），未检出返回 None
    def _detect_pagenum_phrase_outside(self, gray: np.ndarray, receipt_mask: np.ndarray) -> np.ndarray:
        """检测票外底部的页码词组"- N -"（五重判据，全部满足才保护）：
        1. 位于图像底部（组中心 y > 85% 图高）——系统页码固定底部
        2. 组水平居中（组中心 x 距页面中心 < 8% 图宽）
        3. 三段结构：细横条 + 1~2 个块状字符 + 细横条（支持"- 10 -"两位数）
        4. 块状字符高度 ≥ 散点文字豁免阈值且组内等高（极差 < 50%）
        5. 横条与字符垂直居中对齐（中心 y 偏差 < 字符高 50%）
        """
        h, w = gray.shape[:2]
        _min_h = self._scale_r(getattr(cfg, 'EDGE_SCATTER_TEXT_MIN_H', 10))
        # 检测区域：底部 15% 与票外的交集，只看深色像素
        _zone = np.zeros((h, w), dtype=np.uint8)
        _zone[int(h * 0.85):, :] = 255
        _zone = cv2.bitwise_and(_zone, cv2.bitwise_and((gray < 200).astype(np.uint8) * 255,
                                                       cv2.bitwise_not(receipt_mask)))
        _n_cc, _labels, _stats, _ = cv2.connectedComponentsWithStats(_zone, connectivity=8)
        _members = []
        for _k in range(1, _n_cc):
            _x, _y, _bw, _bh, _area = [int(v) for v in _stats[_k]]
            # 过滤噪点（面积<8）与异常大块（超过 8% 图高必不是页码字符）
            if _area < 8 or _bh > h * 0.08:
                continue
            _members.append({'x': _x, 'y': _y, 'w': _bw, 'h': _bh})
        if len(_members) < 3:
            return None
        # 两级分组：①按垂直区间重叠聚行（细横线与页码字符垂直区间不相交不得同行，
        # 中心差贪心聚类会被中间杂线桥接成大组导致漏检，实测 pic3 场景）；②行内按
        # 水平间距分词组（间隙>3倍最大字高另起一组，左右双页码互不干扰）
        _rows = []
        for _m in sorted(_members, key=lambda m: m['y']):
            _placed = False
            for _row in _rows:
                _top = min(mm['y'] for mm in _row)
                _bot = max(mm['y'] + mm['h'] for mm in _row)
                if _m['y'] <= _bot + 2 and _m['y'] + _m['h'] >= _top - 2:
                    _row.append(_m)
                    _placed = True
                    break
            if not _placed:
                _rows.append([_m])
        _groups = []
        for _row in _rows:
            _row.sort(key=lambda m: m['x'])
            _cur = [_row[0]]
            for _m in _row[1:]:
                _gap = _m['x'] - (_cur[-1]['x'] + _cur[-1]['w'])
                _max_h = max(max(mm['h'] for mm in _cur), _m['h'])
                # 间距阈值1倍最大字高：页码词组内间距实测13~20px(300DPI)，双联版式
                # 相邻正文块距页码仅70px（pic2_p2 实测3倍字高=90px误串组致漏检）
                if _gap < _max_h:
                    _cur.append(_m)
                else:
                    _groups.append(_cur)
                    _cur = [_m]
            _groups.append(_cur)
        # 逐组匹配三段结构（横条-字符-横条）
        # zhaoqiaotong 2026-09-18 研发BUG-0060 追加：以候选字符为锚点做行内垂直中心
        # 过滤后再匹配——双联版式中缝装订虚线段会垂直混入词组x区间（pic2_p2 实测
        # 4x18竖条插入"2"上方，长宽比0.22恰过字符判据，破坏等高检查致整组否决），
        # 其中心与页码行偏差远超字高，按对齐过滤剔除；命中组全部收集
        _pn_hit = None
        _seen_boxes = set()
        for _g in _groups:
            _g.sort(key=lambda m: m['x'])
            if not (3 <= len(_g) <= 6):
                continue
            for _m in _g:
                # 连字符判据：实测页码"- N -"横条 10x4（长宽比2.5），按高矮+够宽判
                _m['is_dash'] = _m['h'] <= max(5, _min_h // 2) and _m['w'] >= max(2 * _m['h'], _min_h)
                _m['is_glyph'] = _m['h'] >= _min_h and 0.2 <= _m['w'] / max(_m['h'], 1) <= 2.5
            for _anchor in [m for m in _g if m['is_glyph']]:
                _acy = _anchor['y'] + _anchor['h'] / 2
                _sel = [m for m in _g if abs(m['y'] + m['h'] / 2 - _acy) <= _anchor['h'] * 0.5]
                if len(_sel) < 3:
                    continue
                _sel.sort(key=lambda m: m['x'])
                _dashes = [m for m in _sel if m['is_dash']]
                _glyphs = [m for m in _sel if m['is_glyph']]
                if len(_dashes) < 2 or not (1 <= len(_glyphs) <= 2) or len(_dashes) + len(_glyphs) != len(_sel):
                    continue
                if not _sel[0]['is_dash'] or not _sel[-1]['is_dash']:
                    continue
                _ghs = [m['h'] for m in _glyphs]
                if max(_ghs) > min(_ghs) * 1.5:
                    continue
                # 紧邻性：相邻成员间距 < 2倍字符高（防隔空拼凑）
                _ok = True
                for _a, _b in zip(_sel[:-1], _sel[1:]):
                    if _b['x'] - (_a['x'] + _a['w']) >= 2 * max(_ghs):
                        _ok = False
                        break
                if not _ok:
                    continue
                _gx0, _gx1 = _sel[0]['x'], _sel[-1]['x'] + _sel[-1]['w']
                _gy0, _gy1 = min(m['y'] for m in _sel), max(m['y'] + m['h'] for m in _sel)
                if (_gy0 + _gy1) / 2 < h * 0.85:
                    continue
                if abs((_gx0 + _gx1) / 2 - w / 2) > w * 0.08:
                    continue
                _box = (_gx0, _gy0, _gx1, _gy1)
                if _box in _seen_boxes:
                    continue
                _seen_boxes.add(_box)
                _log(f"    [内容保护] 票外页码词组命中: bbox=({_gx0},{_gy0})-({_gx1},{_gy1}) 成员{len(_sel)}个")
                if _pn_hit is None:
                    _pn_hit = np.zeros((h, w), dtype=np.uint8)
                _pn_hit[_gy0:_gy1, _gx0:_gx1] = 255
        return _pn_hit

    # ============================================================
    # 性能优化版方法 - 使用 ImageCache 避免重复计算
    # ============================================================

    def _is_receipt_document(self, image: np.ndarray, cache: ImageCache) -> tuple:
        """单据检测（优化版，使用缓存和配置缓存）"""
        if not config_cache.get('ENABLE_RECEIPT_DETECTION', True):
            _log(f"    单据检测已禁用")
            return False, None
        
        # 复用缓存的灰度图
        gray = cache.gray
        h, w = cache.h, cache.w
        total_area = h * w
        
        # 边缘检测边距
        edge_margin = max(int(min(h, w) * 0.02), 20)
        
        # 采样边缘区域确定背景色（使用配置缓存）
        sample_margin = max(int(min(h, w) * config_cache.get('RECEIPT_BG_SAMPLE_MARGIN', 0.05)), 10)
        
        edge_pixels = []
        edge_pixels.extend(image[:sample_margin, :].reshape(-1, 3).tolist())
        edge_pixels.extend(image[-sample_margin:, :].reshape(-1, 3).tolist())
        edge_pixels.extend(image[sample_margin:-sample_margin, :sample_margin].reshape(-1, 3).tolist())
        edge_pixels.extend(image[sample_margin:-sample_margin, -sample_margin:].reshape(-1, 3).tolist())
        
        edge_pixels = np.array(edge_pixels, dtype=np.uint8)
        bg_color = np.median(edge_pixels, axis=0).astype(np.uint8)
        
        # 检查背景是否为白色/浅色（使用配置缓存）
        bg_brightness = np.mean(bg_color)
        white_threshold = config_cache.get('RECEIPT_EDGE_WHITE_THRESHOLD', 230)
        if bg_brightness < white_threshold - 10:
            _log(f"    ✗ 不符合单据特征 (原因: background_not_white)")
            return False, None
        
        # 检查四边白色像素占比
        top_edge = gray[:edge_margin, :]
        bottom_edge = gray[-edge_margin:, :]
        left_edge = gray[:, :edge_margin]
        right_edge = gray[:, -edge_margin:]
        
        min_white_ratio = config_cache.get('RECEIPT_EDGE_WHITE_RATIO', 0.70)
        white_edge_count = sum([
            np.sum(top_edge > white_threshold) / top_edge.size >= min_white_ratio,
            np.sum(bottom_edge > white_threshold) / bottom_edge.size >= min_white_ratio,
            np.sum(left_edge > white_threshold) / left_edge.size >= min_white_ratio,
            np.sum(right_edge > white_threshold) / right_edge.size >= min_white_ratio
        ])
        
        min_white_edges = config_cache.get('RECEIPT_MIN_WHITE_EDGES', 3)
        if white_edge_count < min_white_edges:
            _log(f"    ✗ 不符合单据特征 (原因: insufficient_white_edges({white_edge_count}/{min_white_edges}))")
            return False, None
        
        # 使用缓存的 HSV 通道
        hue, saturation, value = cache.get_hsv_channels()
        
        # ============================================================
        # 单据检测核心逻辑：基于饱和度检测彩色票据
        # ============================================================
        # 彩色票据特征：纸张饱和度较高（> 30）
        # 普通文档特征：白底黑字，饱和度低（除了印章）
        # 
        # 【重要】只用饱和度来检测单据边界，比颜色差异更精确！
        
        # 1. 饱和度 > 30 的区域视为彩色票据纸张
        sat_threshold = config_cache.get('RECEIPT_SATURATION_THRESHOLD', 30)
        sat_mask = (saturation > sat_threshold).astype(np.uint8) * 255
        
        # 检查彩色区域是否足够大（至少占5%）
        color_pixel_ratio = np.sum(sat_mask > 0) / total_area
        if color_pixel_ratio < 0.05:
            # 彩色像素太少，不是彩色单据
            _log(f"    ✗ 不符合单据特征 (原因: saturation_ratio_too_low({color_pixel_ratio*100:.1f}%<5%))")
            return False, None
        
        # 2. 腐蚀去除噪点（边缘的彩色杂点）
        kernel_erode = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_MEDIUM), self._scale_r(cfg.MORPH_KERNEL_MEDIUM))
        sat_eroded = cv2.erode(sat_mask, kernel_erode, iterations=2)
        
        # 3. 闭运算填充内部空洞（票据内的空白区域）
        kernel_close = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_HUGE), self._scale_r(cfg.MORPH_KERNEL_HUGE))
        sat_closed = cv2.morphologyEx(sat_eroded, cv2.MORPH_CLOSE, kernel_close)
        
        # 4. 再次腐蚀收紧边界（精确到票据边缘）
        kernel_shrink = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_SMALL), self._scale_r(cfg.MORPH_KERNEL_SMALL))
        color_mask = cv2.erode(sat_closed, kernel_shrink, iterations=3)
        
        # 连通域分析
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(color_mask, connectivity=8)
        
        if num_labels <= 1:
            _log(f"    ✗ 不符合单据特征 (原因: no_distinct_region)")
            return False, None
        
        # 筛选有效区域
        min_area_ratio = config_cache.get('RECEIPT_MIN_AREA_RATIO', 0.03)
        max_area_ratio = config_cache.get('RECEIPT_MAX_AREA_RATIO', 0.67)
        min_contour_area = config_cache.get('RECEIPT_MIN_CONTOUR_AREA', 5000)
        
        valid_regions = []
        for i in range(1, num_labels):
            x, y, bw, bh, area = stats[i]
            
            if area < min_contour_area:
                continue
            
            area_ratio = area / total_area
            if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
                continue
            
            # 单据应该不贴边
            if x < edge_margin or y < edge_margin:
                continue
            if x + bw > w - edge_margin or y + bh > h - edge_margin:
                continue
            
            aspect_ratio = max(bw, bh) / max(min(bw, bh), 1)
            if aspect_ratio > 5:
                continue
            
            rect_area = bw * bh
            rectangularity = area / rect_area
            if rectangularity < 0.3:
                continue
            
            valid_regions.append({
                'label': i, 'x': x, 'y': y, 'w': bw, 'h': bh,
                'area': area, 'area_ratio': area_ratio
            })
        
        if not valid_regions:
            _log(f"    ✗ 不符合单据特征 (原因: no_valid_receipt_region)")
            return False, None
        
        # 找最佳区域
        best_region = max(valid_regions, key=lambda r: r['area'])
        
        # ============================================================
        # 精确边界检测：票据是矩形，用四个顶点确定边界
        # ============================================================
        
        # 1. 获取颜色区域的初始掩码
        color_region_mask = (labels == best_region['label']).astype(np.uint8) * 255
        
        # 2. 闭运算填充内部空洞，但不扩大边界
        kernel_close = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_LARGE), self._scale_r(cfg.MORPH_KERNEL_LARGE))
        color_region_mask = cv2.morphologyEx(color_region_mask, cv2.MORPH_CLOSE, kernel_close)
        
        # 3. 找轮廓
        contours, _ = cv2.findContours(color_region_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            _log(f"    ✗ 不符合单据特征 (原因: no_contour_found)")
            return False, None
        
        # 4. 找最大轮廓
        largest_contour = max(contours, key=cv2.contourArea)
        
        # 5. 使用最小外接矩形（考虑旋转）找边界
        rect = cv2.minAreaRect(largest_contour)
        box = cv2.boxPoints(rect)
        box = np.int32(box)
        
        # 6. 计算轴对齐的边界框（从旋转矩形的四个顶点）
        x_coords = box[:, 0]
        y_coords = box[:, 1]
        x_min = max(0, int(np.min(x_coords)))
        x_max = min(w, int(np.max(x_coords)))
        y_min = max(0, int(np.min(y_coords)))
        y_max = min(h, int(np.max(y_coords)))
        
        # 7. 精确收紧边界：在边界框内找实际内容边界
        # 向内收缩，找到实际有颜色的边界（±5像素浮动）
        margin = 5
        
        # 检查每条边，找到实际内容的位置
        # 上边界：从y_min向下扫描，找到第一行有颜色的位置
        for y in range(y_min, min(y_min + 100, y_max)):
            row_colors = np.sum(color_region_mask[y, x_min:x_max] > 0)
            if row_colors > (x_max - x_min) * 0.1:  # 超过10%的像素有颜色
                y_min = max(0, y - margin)
                break
        
        # 下边界：从y_max向上扫描
        for y in range(y_max - 1, max(y_max - 100, y_min), -1):
            row_colors = np.sum(color_region_mask[y, x_min:x_max] > 0)
            if row_colors > (x_max - x_min) * 0.1:
                y_max = min(h, y + margin)
                break
        
        # 左边界：从x_min向右扫描
        for x in range(x_min, min(x_min + 100, x_max)):
            col_colors = np.sum(color_region_mask[y_min:y_max, x] > 0)
            if col_colors > (y_max - y_min) * 0.1:
                x_min = max(0, x - margin)
                break
        
        # 右边界：从x_max向左扫描
        for x in range(x_max - 1, max(x_max - 100, x_min), -1):
            col_colors = np.sum(color_region_mask[y_min:y_max, x] > 0)
            if col_colors > (y_max - y_min) * 0.1:
                x_max = min(w, x + margin)
                break
        
        # 8. 生成精确的矩形掩码
        receipt_mask = np.zeros((h, w), dtype=np.uint8)
        receipt_mask[y_min:y_max, x_min:x_max] = 255
        
        final_area_ratio = np.sum(receipt_mask > 0) / total_area
        _log(f"    ✓ 符合单据/票据特征:")
        _log(f"      - 背景色 BGR: {bg_color.tolist()}")
        _log(f"      - 单据边界: ({x_min},{y_min}) - ({x_max},{y_max})")
        _log(f"      - 单据面积占比: {final_area_ratio*100:.1f}%")
        
        return True, receipt_mask

