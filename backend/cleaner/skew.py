# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
"""倾斜检测和矫正 Mixin 模块"""

import cv2
import numpy as np

from backend import config as cfg
from .cache import kernel_cache
from . import _log


class SkewMixin:
    """倾斜检测和矫正功能"""

    def _detect_skew_angle(self, image: np.ndarray) -> float:
        """
        检测文档倾斜角度（增强版）
        
        使用多种方法检测倾斜：
        1. 霍夫变换检测直线
        2. 文字行检测（基于连通域）
        3. 加权平均得到最终角度
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        
        # 方法1: 霍夫变换检测直线
        # 使用自适应边缘检测
        edges = cv2.Canny(gray, 30, 100, apertureSize=3)
        
        # 膨胀边缘使线条更连续
        kernel = kernel_cache.get_ones(self._scale_r(cfg.MORPH_KERNEL_TINY))
        edges = cv2.dilate(edges, kernel, iterations=1)

        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=cfg.DESKEW_HOUGH_THRESHOLD,
            minLineLength=cfg.DESKEW_HOUGH_MIN_LINE_LENGTH,
            maxLineGap=cfg.DESKEW_HOUGH_MAX_LINE_GAP
        )

        hough_angles = []
        if lines is not None:
            for line in lines:
                # xuechong 2026-08-17 一键修图HoughLinesP解包异常修复 OpenCV5返回(N,4)而4.x返回(N,1,4)，
                # reshape(-1)展平后取前4元素，两个大版本通吃（研发BUG-0023）
                x1, y1, x2, y2 = line.reshape(-1)[:4]
                length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                if x2 - x1 == 0 or length < 20:
                    continue

                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))

                # 只考虑接近水平的线条
                if -30 < angle < 30:
                    # 根据线条长度加权
                    hough_angles.extend([angle] * int(length / 10))

        # 方法1.5: 饱和度通道霍夫检测（彩色文档补偿）
        # 对于防伪图案票据等彩色文档，灰度霍夫可能被花纹干扰。
        # 饱和度通道检测的是文档颜色边界（粉色底 vs 白色扫描仪背景），
        # 当两通道一致时增强信心，不一致时标记灰度结果不可靠。
        sat_hough_angles = []
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        if np.mean(saturation) > 10:
            sat_edges = cv2.Canny(saturation, 30, 100, apertureSize=3)
            sat_edges = cv2.dilate(sat_edges, kernel, iterations=1)
            sat_lines = cv2.HoughLinesP(
                sat_edges,
                rho=1,
                theta=np.pi / 180,
                threshold=cfg.DESKEW_HOUGH_THRESHOLD,
                minLineLength=cfg.DESKEW_HOUGH_MIN_LINE_LENGTH,
                maxLineGap=cfg.DESKEW_HOUGH_MAX_LINE_GAP
            )
            if sat_lines is not None:
                for line in sat_lines:
                    # xuechong 2026-08-17 一键修图HoughLinesP解包异常修复 同上，OpenCV5/4.x双版本兼容
                    x1, y1, x2, y2 = line.reshape(-1)[:4]
                    length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                    if x2 - x1 == 0 or length < 20:
                        continue
                    angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                    if -30 < angle < 30:
                        sat_hough_angles.extend([angle] * int(length / 10))

        # 方法2: 基于二值化和轮廓检测文字行方向
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # 水平方向膨胀，连接文字形成行
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 20, 1))
        dilated = cv2.dilate(binary, h_kernel, iterations=1)
        
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        text_line_angles = []
        for contour in contours:
            # 忽略太小的轮廓
            if cv2.contourArea(contour) < 500:
                continue
            
            # 使用最小外接矩形
            rect = cv2.minAreaRect(contour)
            angle = rect[2]
            rect_w, rect_h = rect[1]
            
            # 确保是横向的文字行
            if rect_w < rect_h:
                angle = angle - 90 if angle > 0 else angle + 90
                rect_w, rect_h = rect_h, rect_w
            
            # 排除宽度过大或过小的轮廓
            # - rect_w > w * 0.8: 水平膨胀产生的全幅伪影，不代表真实文字行倾斜
            # - rect_w > w * 0.1: 确保是合理的文字行宽度
            if w * 0.1 < rect_w < w * 0.8 and -30 < angle < 30:
                text_line_angles.append(angle)

        # 智能合并两种方法的结果
        # 策略：检查霍夫变换/文字行结果的一致性，如果太分散则视为噪声

        hough_valid = False
        hough_angle = 0.0
        hough_std = 999.0
        if hough_angles:
            hough_arr = np.array(hough_angles)
            hough_std = np.std(hough_arr)
            hough_median = np.median(hough_arr)
            # 如果标准差小于5度，认为霍夫变换结果可靠
            if hough_std < 5.0:
                hough_valid = True
                hough_angle = hough_median
            # 标准差偏高但样本量大：可能是密集表格/竖线导致多集群混合
            # 尝试聚类取主峰，但仅当投影法也确认有倾斜时才信任
            elif len(hough_angles) >= 100 and hough_std < 15.0:
                hist, bins = np.histogram(hough_arr, bins=40, range=(-20, 20))
                peak_idx = np.argmax(hist)
                peak_center = (bins[peak_idx] + bins[peak_idx + 1]) / 2
                cluster_mask = (hough_arr > peak_center - 2) & (hough_arr < peak_center + 2)
                cluster = hough_arr[cluster_mask]
                if len(cluster) >= 50 and np.std(cluster) < 2.0:
                    # 聚类紧致但需投影法交叉验证，避免表格线假阳性
                    proj_angle = self._detect_skew_by_projection(image)
                    if abs(proj_angle) > 1.0 and abs(proj_angle - np.median(cluster)) < 5.0:
                        hough_valid = True
                        hough_angle = np.median(cluster)
                        hough_std = np.std(cluster)

        text_valid = False
        text_angle = 0.0
        if text_line_angles:
            text_arr = np.array(text_line_angles)
            text_std = np.std(text_arr)
            # 文字行角度也需一致性检查，避免多集群混合导致的误导中位数
            # 阈值 10° 比霍夫 5° 宽松，允许文字行的自然变化
            if text_std < 10.0:
                text_angle = np.median(text_arr)
                text_valid = True

        sat_hough_valid = False
        sat_hough_angle = 0.0
        sat_hough_std = 999.0
        if sat_hough_angles:
            sat_arr = np.array(sat_hough_angles)
            sat_hough_std = np.std(sat_arr)
            if sat_hough_std < 5.0:
                sat_hough_valid = True
                sat_hough_angle = np.median(sat_arr)

        # 决策逻辑（三通道：文字行 + 灰度霍夫 + 饱和度霍夫交叉验证）
        if text_valid and hough_valid:
            # 两种方法都有效，检查是否一致
            if abs(hough_angle - text_angle) < 3.0:
                # 结果一致，使用加权平均（文字行权重更高）
                final_angle = text_angle * 0.7 + hough_angle * 0.3
            else:
                # 结果不一致 → 交叉验证
                if sat_hough_valid and abs(hough_angle - sat_hough_angle) > 3.0:
                    # 灰度霍夫与饱和度霍夫也不一致 → 灰度结果不可靠
                    if abs(text_angle) < 0.5:
                        final_angle = 0.0  # 文字说0°，灰度与饱和度矛盾 → 放弃
                    else:
                        final_angle = text_angle
                elif (abs(text_angle) < 0.5 and abs(hough_angle) > 1.0
                        and hough_std < 3.0):
                    # 饱和度与灰度一致（或无饱和度），文字行可能是防伪图案伪影
                    final_angle = hough_angle
                else:
                    final_angle = text_angle
        elif text_valid:
            # 只有文字行检测有效
            final_angle = text_angle
        elif hough_valid:
            # 只有灰度霍夫有效 → 交叉验证
            if sat_hough_valid and abs(hough_angle - sat_hough_angle) > 3.0:
                # 灰度与饱和度不一致：检查灰度霍夫自身置信度
                # 高样本数+低标准差 → 灰度结果仍然可靠（印章边界干扰了饱和度）
                if len(hough_angles) >= 50 and hough_std < 2.0:
                    final_angle = hough_angle
                else:
                    final_angle = 0.0  # 低置信度 → 放弃
            else:
                final_angle = hough_angle
        else:
            # 文字行和灰度霍夫都无效 → 尝试饱和度霍夫
            if sat_hough_valid:
                final_angle = sat_hough_angle
            else:
                # 全部无效 → 投影法兜底（不受表格线干扰）
                final_angle = self._detect_skew_by_projection(image)
                # xuechong 2026-08-19 研发BUG-0028-图档扫描-3.1.07-票据单据倾斜矫正角度矫正问题
                # 原此处有 if final_angle == 0.0: return 0.0 提前返回，收敛为单出口后删除：
                # 继续下落与原提前返回等价（|0| 不触发否决，钳位仍得 0）

        # 投影法最终裁决：霍夫（灰度/饱和度）可能被密集表格线误导，
        # 当投影法认为图像基本正时，否决霍夫的纠偏请求，避免过度纠偏
        if abs(final_angle) > 1.0:
            proj_angle = self._detect_skew_by_projection(image)
            if abs(proj_angle) < 1.5:
                _log(f"  [倾斜矫正] 霍夫检测 {final_angle:.2f}° 与投影法 {proj_angle:.2f}° 矛盾，"
                     f"投影法认为图像已正，放弃纠偏")
                # xuechong 2026-08-19 研发BUG-0028-图档扫描-3.1.07-票据单据倾斜矫正角度矫正问题
                # 原 return 0.0 收敛为赋值下落（与提前返回等价：钳位仍得 0）
                final_angle = 0.0
        elif abs(final_angle) > cfg.DESKEW_MIN_ANGLE:
            # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
            # 小角度假阳性强确认（REQ-003）：|角|≤1.0° 时原裁决不生效，合格证类正图被
            # 霍夫假信号 0.92° 矫歪 -1.47°（016/e002 实测）。投影强置信认为已正
            # （|投影角|<0.3° 且 置信≥1.3）则放弃；真歪小角度图投影角≈自身角度>0.3° 不受影响
            proj_angle, proj_conf = self._detect_skew_by_projection(image, return_conf=True)
            if abs(proj_angle) < 0.3 and proj_conf >= 1.3:
                _log(f"  [倾斜矫正] 小角度 {final_angle:.2f}° 矫正请求被投影法强确认否决"
                     f"（投影 {proj_angle:.2f}°/置信 {proj_conf:.2f}），判定原图已正")
                final_angle = 0.0

        if abs(final_angle) > cfg.DESKEW_MAX_ANGLE:
            final_angle = 0.0
        if abs(final_angle) < cfg.DESKEW_MIN_ANGLE:
            final_angle = 0.0

        # xuechong 2026-08-19 研发BUG-0028-图档扫描-3.1.07-票据单据倾斜矫正角度矫正问题
        # 投影法仲裁门控：手写票据文字行小样本（2~9）既欠检又假阳性（121 欠检/080 假阳性实测），
        # 当文字行样本存在但不可靠、投影法高置信、且与现有决策分歧大时，采纳投影角为最终角。
        # n_text<2 时文字行通道零信息（0=无线，1=单点矩形伪证，拼接画布即此形态），不触发；
        # 参数依据：456 张全样张库仿真，30 张改变全部改善、0 劣化（开发方案 §4.1）
        if (cfg.DESKEW_PROJ_ARBITRATION
                and 2 <= len(text_line_angles) < cfg.DESKEW_TEXT_MIN_SAMPLES):
            proj_angle, proj_conf = self._detect_skew_by_projection(image, return_conf=True)
            if (proj_conf > cfg.DESKEW_PROJ_CONF_MIN
                    and abs(proj_angle - final_angle) > cfg.DESKEW_PROJ_DIFF):
                # 采纳角同样经过既有 MAX/MIN 钳位规则，越界归 0
                arbitrated = proj_angle
                if abs(arbitrated) > cfg.DESKEW_MAX_ANGLE or abs(arbitrated) < cfg.DESKEW_MIN_ANGLE:
                    arbitrated = 0.0
                _log(f"  [倾斜矫正] 投影仲裁触发: 原决策 {final_angle:.2f}° → 投影 {arbitrated:.2f}° | "
                     f"置信度 {proj_conf:.2f} | 文字行样本 {len(text_line_angles)} "
                     f"中位 {np.median(text_line_angles):.2f}° | "
                     f"灰度霍夫中位 {(np.median(hough_angles) if hough_angles else 0.0):.2f}° | "
                     f"饱和度霍夫中位 {(np.median(sat_hough_angles) if sat_hough_angles else 0.0):.2f}°")
                final_angle = arbitrated

        # xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
        # 检测遥测：供 core.py 二次矫正门控读取（n_text 是关键门控信号，返回值签名不变零破坏）
        self._last_skew_telemetry = {
            "n_text": len(text_line_angles),
            "n_hough": len(hough_angles),
            "n_sat_hough": len(sat_hough_angles),
            "text_angle": float(text_angle) if text_valid else None,
            "hough_angle": float(hough_angle) if hough_valid else None,
            "sat_hough_angle": float(sat_hough_angle) if sat_hough_valid else None,
            "final_angle": float(final_angle),
        }

        return final_angle

    def _detect_skew_by_projection(self, image: np.ndarray, search_range: int = 15,
                                   return_conf: bool = False) -> float | tuple[float, float]:
        """
        投影法检测倾斜角度（兜底方法）

        对灰度图在多个角度做水平投影，投影方差最大的角度即为文字行方向。
        不受表格竖线干扰，适合霍夫检测失效的密集表格文档。

        Args:
            image: BGR 格式图片
            search_range: 搜索角度范围（±度数）
            return_conf: 为 True 时返回 (原始最佳角, 置信度)，供仲裁门控使用

        Returns:
            float: 倾斜角度（度），0 表示未检测到倾斜
            tuple[float, float]: return_conf=True 时返回 (原始最佳角, 置信度)，
                                 不经过 0.1°/1.05 置信度截断
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # 缩放加速：限制短边最大 600px
        scale = min(1.0, 600.0 / min(h, w))
        if scale < 1.0:
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
        h, w = gray.shape

        # 粗搜
        best_angle, best_var = 0.0, 0.0
        all_vars = []
        for angle in np.arange(-search_range, search_range + 1, 1.0):
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            rotated = cv2.warpAffine(gray, M, (w, h),
                                     borderMode=cv2.BORDER_CONSTANT, borderValue=255)
            var = np.var(np.mean(rotated, axis=1))
            all_vars.append(var)
            if var > best_var:
                best_var, best_angle = var, angle

        # 精细搜索
        for angle in np.arange(best_angle - 2, best_angle + 2.1, 0.2):
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            rotated = cv2.warpAffine(gray, M, (w, h),
                                     borderMode=cv2.BORDER_CONSTANT, borderValue=255)
            var = np.var(np.mean(rotated, axis=1))
            if var > best_var:
                best_var, best_angle = var, angle

        # 置信度：最佳方差 / 平均方差
        avg_var = np.mean(all_vars) if all_vars else 1.0
        confidence = best_var / avg_var if avg_var > 0 else 1.0

        # 仅在置信度和角度都足够时返回
        # xuechong 2026-08-19 研发BUG-0028-图档扫描-3.1.07-票据单据倾斜矫正角度矫正问题
        # return_conf=True 时返回 (原始最佳角, 置信度)，不经过下方截断逻辑，供仲裁门控使用
        if return_conf:
            return best_angle, confidence
        if confidence > 1.05 and abs(best_angle) > cfg.DESKEW_MIN_ANGLE:
            return best_angle
        return 0.0

    def _deskew_image(self, image: np.ndarray, angle: float) -> np.ndarray:
        """旋转矫正图像"""
        h, w = image.shape[:2]
        center = (w // 2, h // 2)

        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

        cos = np.abs(rotation_matrix[0, 0])
        sin = np.abs(rotation_matrix[0, 1])
        new_w = int((h * sin) + (w * cos))
        new_h = int((h * cos) + (w * sin))

        rotation_matrix[0, 2] += (new_w / 2) - center[0]
        rotation_matrix[1, 2] += (new_h / 2) - center[1]

        rotated = cv2.warpAffine(
            image,
            rotation_matrix,
            (new_w, new_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=cfg.DESKEW_FILL_COLOR
        )

        return rotated
