# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
"""页面方向检测 Mixin 模块"""

import cv2
import numpy as np

from typing import TYPE_CHECKING

from backend import config as cfg
from . import _log, _get_cached_ocr_engine

if TYPE_CHECKING:
    from rapidocr import RapidOCR


class OrientationMixin:
    """页面方向检测功能"""

    def _detect_page_orientation(self, image: np.ndarray) -> int:
        """
        检测页面方向，判断是否需要旋转90度倍数
        
        使用快速策略：
        1. 如果图片明显横向（宽 > 高 * 1.3），不需要旋转
        2. 如果图片明显纵向（高 > 宽 * 1.3），检查是否需要旋转（可能是票据放错方向）
        3. 使用OCR文字框方向分析确认
        
        Args:
            image: BGR 格式的图片数组
            
        Returns:
            int: 需要旋转的角度 (0, 90, 180, 270)
                 0 = 不需要旋转
                 90 = 逆时针旋转90度
                 180 = 旋转180度
                 270 = 顺时针旋转90度（最常见的扫描方向错误）
        """
        h, w = image.shape[:2]
        aspect_ratio = w / h
        
        # 获取配置
        receipt_ratio = getattr(cfg, 'PAGE_ORIENTATION_RECEIPT_RATIO', 1.3)
        min_boxes = getattr(cfg, 'PAGE_ORIENTATION_MIN_BOXES', 5)
        max_dim = getattr(cfg, 'PAGE_ORIENTATION_MAX_DIM', 960)
        confidence = getattr(cfg, 'PAGE_ORIENTATION_CONFIDENCE', 0.6)
        
        _log(f"  [页面方向] 图像尺寸: {w}x{h}, 宽高比: {aspect_ratio:.2f}")
        
        # 如果图片明显是横向的（宽 > 高 * 1.3），基本确认方向正确
        if aspect_ratio > receipt_ratio:
            _log(f"  [页面方向] 宽高比 {aspect_ratio:.2f} > {receipt_ratio}，横向文档，无需旋转")
            return 0
        
        # 图片是纵向或接近正方形，需要进一步检测
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-006 优先使用快速 det+cls 方向检测
        try:
            fast_result = self._detect_orientation_fast(image, max_dim, min_boxes, confidence)
            if fast_result is not None:
                return fast_result
            # 快速检测不确定，回退原 4 方向 det+rec 方法
            _log(f"  [页面方向] 快速检测不确定，回退 4 方向 det+rec")
            rotation = self._detect_orientation_by_ocr(image, max_dim, min_boxes, confidence)
            return rotation
        except Exception as e:
            _log(f"  [页面方向] OCR检测失败: {e}")
            
            # OCR失败时，对于明显纵向的图片（可能是票据放错了），尝试旋转
            if aspect_ratio < 0.77:  # 高 > 宽 * 1.3
                _log(f"  [页面方向] 图片明显纵向，可能需要旋转，但OCR检测失败，不自动旋转")
            return 0
    
    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-006 快速方向检测：det+cls 替代 4次det+rec
    def _detect_orientation_fast(self, image: np.ndarray, max_dim: int,
                                  min_boxes: int, confidence: float):
        """快速方向检测：1 次 det + 1 次 cls（90°/270° 场景 2 次 det）
        
        算法：
        Phase 1: 原图 det → 文本框裁剪 → cls 投票判定 0°/180°
        Phase 2: 顺时针旋转 90° 后 det+cls → 判定 90°/270°
        两阶段均不确定 → 返回 None（由调用方回退 4 方向 det+rec）
        
        Returns:
            int: 旋转角度 (0, 90, 180, 270)，或 None 表示需要回退
        """
        h, w = image.shape[:2]
        
        # 缩放图像
        scale = 1.0
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img_small = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            _log(f"  [页面方向] 缩放图像到 {new_w}x{new_h} 进行快速检测")
        else:
            img_small = image
        
        engine = _get_cached_ocr_engine(max_dim)
        
        # ---- Phase 1: 原图 det + cls → 判定 0°/180° ----
        angle_p1 = self._cls_vote(engine, img_small, min_boxes, confidence, "原图")
        if angle_p1 is not None:
            _log(f"  [页面方向] Phase 1 det+cls 判定: {angle_p1}°")
            return angle_p1
        
        _log(f"  [页面方向] Phase 1 未确定（框不足或投票不明确）")
        
        # ---- Phase 2: 顺时针旋转 90° 后 det + cls → 判定 90°/270° ----
        img_cw = cv2.rotate(img_small, cv2.ROTATE_90_CLOCKWISE)
        angle_p2 = self._cls_vote(engine, img_cw, min_boxes, confidence, "90°CW")
        if angle_p2 is not None:
            # xuechong 2026-08-07 研发BUG-0016 修复 Phase 2 旋转映射反向
            # img_cw = rotate(original, CW90)，对 img_cw 跑 cls：
            # cls=0°  → img_cw 已正向 → 原图需 CW90 = angle 270
            # cls=180° → img_cw 偏 180° → 原图需 CCW90 = angle 90
            final = 270 if angle_p2 == 0 else 90
            _log(f"  [页面方向] Phase 2 det+cls (90°CW): cls={angle_p2}° → 原图需旋转 {final}°")
            return final
        
        _log(f"  [页面方向] Phase 2 未确定，需回退 4 方向 det+rec")
        return None
    
    def _cls_vote(self, engine: "RapidOCR", img: np.ndarray, min_boxes: int,
                  confidence: float, tag: str) -> int:
        """对单张图执行 det + cls 投票，返回 0 或 180，None 表示不确定"""
        try:
            result = engine.detect_and_crop(img, {})
            if not isinstance(result, tuple) or len(result) < 2:
                return None
            crops = result[0]
            det_out = result[1]
            
            boxes = getattr(det_out, 'boxes', None)
            if boxes is None or len(boxes) == 0:
                _log(f"  [页面方向] {tag} det: 无文本框")
                return None
            
            n_boxes = len(boxes)
            
            # 统计横向文本框比例（排除 90°/270° 场景）
            n_horizontal = 0
            for box in boxes:
                box_list = box.tolist() if hasattr(box, 'tolist') else box
                xs = [p[0] for p in box_list]
                ys = [p[1] for p in box_list]
                if max(xs) - min(xs) > max(ys) - min(ys):
                    n_horizontal += 1
            
            h_ratio = n_horizontal / n_boxes if n_boxes > 0 else 0
            _log(f"  [页面方向] {tag} det: {n_boxes} 框, 横向 {n_horizontal} ({h_ratio:.0%})")
            
            # 横向文本框占比 < 50% → 可能是 90°/270° 旋转页
            if h_ratio < 0.5:
                _log(f"  [页面方向] {tag} 横向框占比 {h_ratio:.0%} < 50%，跳过 cls")
                return None
            
            if n_boxes < min_boxes:
                _log(f"  [页面方向] {tag} 文本框 {n_boxes} < {min_boxes}，跳过 cls")
                return None
            
            # cls 投票
            cls_result = engine.cls_and_rotate(crops)
            if not isinstance(cls_result, tuple) or len(cls_result) < 2:
                return None
            
            cls_out = cls_result[1]
            cls_res = getattr(cls_out, 'cls_res', None)
            if cls_res is None or len(cls_res) == 0:
                _log(f"  [页面方向] {tag} cls: 无结果")
                return None
            
            vote_0 = 0.0
            vote_180 = 0.0
            for item in cls_res:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    label = str(item[0])
                    score = float(item[1])
                    if '180' in label:
                        vote_180 += score
                    else:
                        vote_0 += score
            
            total = vote_0 + vote_180
            _log(f"  [页面方向] {tag} cls 投票: 0°={vote_0:.2f}, 180°={vote_180:.2f} (总置信度 {total:.2f})")

            if total <= 0:
                return None

            ratio_0 = vote_0 / total
            ratio_180 = vote_180 / total

            # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
            # 翻转整页属大动作，须强证据（FLIP_CONFIDENCE）；判0°保持现状用宽松阈值即可；
            # 中间地带返回 None 交由调用方回退 4 方向 det+rec 复核（修复表格类正页被微弱多数误转180°）
            flip_conf = getattr(cfg, 'PAGE_ORIENTATION_FLIP_CONFIDENCE', 0.7)
            if ratio_180 > flip_conf:
                return 180
            elif ratio_0 > confidence:
                return 0
            else:
                _log(f"  [页面方向] {tag} 投票不明确 (0°={ratio_0:.0%}, 180°={ratio_180:.0%}, 判0阈值={confidence}, 翻转阈值={flip_conf})")
                return None
                
        except Exception as e:
            _log(f"  [页面方向] {tag} det+cls 异常: {e}")
            return None
    
    def _detect_orientation_by_ocr(self, image: np.ndarray, max_dim: int, 
                                    min_boxes: int, confidence: float) -> int:
        """
        使用OCR文字框方向分析判断页面方向
        
        原理：
        - 正常阅读方向的文字框通常是"宽 > 高"（横向文字行）
        - 旋转90度的页面，文字框会变成"高 > 宽"（竖向文字框）
        - 通过统计横向和竖向文字框的比例来判断页面方向
        
        Args:
            image: BGR 格式的图片
            max_dim: 检测时的最大边长
            min_boxes: 最少需要的文字框数量
            confidence: 置信度阈值
            
        Returns:
            int: 旋转角度 (0, 90, 180, 270)
        """
        h, w = image.shape[:2]
        
        # 缩放图像以提升检测速度
        scale = 1.0
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img_small = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            _log(f"  [页面方向] 缩放图像到 {new_w}x{new_h} 进行检测")
        else:
            img_small = image
        
        # 使用 RapidOCR 进行快速文字检测（复用缓存的引擎）
        try:
            # 获取缓存的OCR引擎（避免每次创建新引擎）
            engine = _get_cached_ocr_engine(max_dim)

            # OCR识别函数：只统计正向文字框（宽>高）中的文字个数
            def ocr_count_text(img, angle_name):
                try:
                    result = engine(img, use_det=True, use_cls=False, use_rec=True)
                    if result is None or result.boxes is None or len(result.boxes) == 0:
                        return 0
                    
                    boxes = result.boxes
                    txts = result.txts if result.txts else []
                    total_chars = 0
                    
                    for i, box in enumerate(boxes):
                        if hasattr(box, 'tolist'):
                            box = box.tolist()
                        # 计算文字框宽高
                        x_coords = [p[0] for p in box]
                        y_coords = [p[1] for p in box]
                        box_w = max(x_coords) - min(x_coords)
                        box_h = max(y_coords) - min(y_coords)
                        
                        # 只统计正向文字框（宽>高，即横向文字行）
                        if box_w > box_h and i < len(txts) and txts[i]:
                            total_chars += len(txts[i])
                    
                    return total_chars
                except Exception as e:
                    _log(f"  [页面方向] {angle_name} OCR异常: {e}")
                    return 0
            
            # 准备四个方向的图像
            images = [
                (0, img_small, "原图(0°)"),
                (90, cv2.rotate(img_small, cv2.ROTATE_90_COUNTERCLOCKWISE), "旋转90°"),
                (180, cv2.rotate(img_small, cv2.ROTATE_180), "旋转180°"),
                (270, cv2.rotate(img_small, cv2.ROTATE_90_CLOCKWISE), "旋转270°")
            ]
            
            # 串行执行OCR识别（onnxruntime CUDA EP 不保证线程安全）
            results = {0: 0, 90: 0, 180: 0, 270: 0}  # 预初始化
            for angle, img, name in images:
                char_count = ocr_count_text(img, name)
                results[angle] = char_count
                _log(f"  [页面方向] {name}: 文字={char_count}个")
            
            orig_count = results[0]
            _log(f"  [页面方向] 汇总: 原图={orig_count}, 90°={results[90]}, 180°={results[180]}, 270°={results[270]}")
            
            # 简单逻辑：找出文字最多的方向
            best_angle = max(results, key=results.get)
            best_count = results[best_angle]
            
            # 如果原图文字最多，不旋转
            if best_angle == 0:
                _log(f"  [页面方向] 原图文字最多({orig_count}个)，无需旋转")
                return 0
            
            # 如果原图文字数等于最佳，不旋转（原图优先）
            if orig_count == best_count:
                _log(f"  [页面方向] 原图与最佳相同({orig_count}个)，无需旋转")
                return 0
            
            # 最佳方向文字更多，旋转
            _log(f"  [页面方向] 旋转{best_angle}° (文字{best_count}个 > 原图{orig_count}个)")
            return best_angle
            
        except ImportError:
            _log(f"  [页面方向] RapidOCR 未安装")
            raise
        except Exception as e:
            _log(f"  [页面方向] 检测异常: {e}")
            raise
    
    def _rotate_image_90(self, image: np.ndarray, angle: int) -> np.ndarray:
        """
        旋转图像90度的倍数
        
        Args:
            image: 输入图像
            angle: 旋转角度 (90, 180, 270)
            
        Returns:
            np.ndarray: 旋转后的图像
        """
        if angle == 90:
            return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif angle == 180:
            return cv2.rotate(image, cv2.ROTATE_180)
        elif angle == 270:
            return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        return image
