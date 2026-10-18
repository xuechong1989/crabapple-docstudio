# -*- coding: utf-8 -*-
# xuechong 2026-07-19 研发需求-0204-cleaner模块拆分重构
"""DocumentCleaner 主类模块"""

import cv2
import numpy as np
import inspect
from typing import Tuple

from doclayout_yolo import YOLOv10

from backend import config as cfg
from .cache import kernel_cache, config_cache, ImageCache, KernelCache
from . import _log, get_model_path, get_yolo_device
# xuechong 2026-07-20 修复：补齐缺失的导入（原 line 382 直接使用但未导入，运行时被 except 静默吞掉）
from .ocr_engine import _get_cached_ocr_engine
# xuechong 2026-07-20 修复：原 `global _cuda_verified` 写的是本模块命名空间，对 gpu 状态无效
from .gpu import _set_cuda_unavailable
from .skew import SkewMixin
from .orientation import OrientationMixin
from .receipt import ReceiptMixin
from .protect import ProtectMixin
from .noise import NoiseMixin
from .background import BackgroundMixin


class DocumentCleaner(SkewMixin, OrientationMixin, ReceiptMixin, ProtectMixin, NoiseMixin, BackgroundMixin):
    """文档图片清洁处理器"""
    
    def __init__(self, model_path: str = None):
        """
        初始化清洁器
        
        Args:
            model_path: YOLO 模型路径，默认自动从 Hugging Face 下载
        """
        model_path = model_path or get_model_path()
        self.config = config_cache
        self.device, reason = get_yolo_device()
        _log(f"  [YOLO] 设备: {self.device} ({reason})")
        self.model = YOLOv10(model_path)
        self._predict_has_device = "device" in inspect.signature(self.model.predict).parameters
        if self.device != "cpu":
            try:
                if hasattr(self.model, "to"):
                    self.model.to(self.device)
                elif hasattr(self.model, "model") and hasattr(self.model.model, "to"):
                    self.model.model.to(self.device)
            except Exception as e:
                _log(f"  [YOLO] GPU 初始化失败，回退 CPU: {e}")
                self.device = "cpu"
                _set_cuda_unavailable()
        self.names = self.model.names

    def _predict(self, image: np.ndarray):
        """统一 YOLO 预测入口，按需传递 device 参数

        GPU 推理失败时自动回退 CPU（如 CUDA kernel 架构不匹配等不可恢复错误），
        避免整张图片被跳过。回退后后续所有预测都使用 CPU。
        """
        if self._predict_has_device and self.device != "cpu":
            try:
                return self.model.predict(
                    image,
                    imgsz=cfg.YOLO_IMGSZ,
                    conf=cfg.YOLO_CONF,
                    verbose=False,
                    device=self.device
                )
            except Exception as e:
                error_msg = str(e)
                if "CUDA" in error_msg or "cuda" in error_msg or "no kernel image" in error_msg:
                    _log(f"  [YOLO] ⚠ GPU 推理失败 ({error_msg[:80]})，自动回退到 CPU 模式")
                    _log(f"  [YOLO] ⚠ 后续所有图片将使用 CPU 进行 YOLO 检测（速度会变慢但不会跳过图片）")
                    self.device = "cpu"
                    self._predict_has_device = False
                    _set_cuda_unavailable()
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception as cache_e:
                        _log(f"  [YOLO] CUDA cache 清理失败 (非致命): {cache_e}")
                    return self.model.predict(
                        image,
                        imgsz=cfg.YOLO_IMGSZ,
                        conf=cfg.YOLO_CONF,
                        verbose=False
                    )
                raise
        return self.model.predict(
            image,
            imgsz=cfg.YOLO_IMGSZ,
            conf=cfg.YOLO_CONF,
            verbose=False
        )

    def _scale_r(self, radius: int) -> int:
        """将半径从参考 DPI 缩放到当前处理图像的 DPI"""
        return cfg.scale_radius(radius, getattr(self, '_current_dpi', 300))

    def process(self, image: np.ndarray, debug: bool = False, dpi: int = 300) -> dict:
        """
        处理单张图片

        Args:
            image: BGR 格式的图片数组
            debug: 是否返回调试信息
            dpi: 图像 DPI，用于自适应缩放半径参数

        Returns:
            dict: 包含处理结果和各阶段掩码/可视化
        """
        return self._process_document(image, debug, dpi=dpi)

    def _process_document(self, image: np.ndarray, debug: bool = False, dpi: int = 300) -> dict:
        """
        文档处理主流程（性能优化版）
        
        首先判断文件类型，然后根据类型选择处理模式：
        
        【文件类型判断】
        ├─ 单据/票据 → 单据保护模式
        │   特征：粘贴在A4纸上的小尺寸彩色票据
        │   处理：完全保护单据区域，仅刷白外部背景
        │
        └─ 普通文档/表格 → 标准处理模式
            特征：内容铺满整页的文档
            处理：YOLO检测 + 噪点清理 + 背景白化
        
        【标准处理模式流程】
        0. 倾斜矫正（可选）
        1. YOLO 检测保护区（表格、文字、图片等）
        2. 公章/印章检测
        3. 文字连通域保护（英文、数字等）
        4. 噪点/钉痕/黑边/杂质线条检测与清除
        5. 背景白化
        
        【性能优化】
        - 使用 ImageCache 避免重复的图像转换
        - 连通域分析只做一次
        - HSV转换只做一次
        - 二值化只做一次
        """
        # 存储当前 DPI，供 _scale_r 使用
        self._current_dpi = dpi

        # ============================================================
        # 设备信息（帮助确认 GPU 是否启用）
        # ============================================================
        _log(f"  [处理引擎] YOLO设备: {self.device} | 图像尺寸: {image.shape[1]}x{image.shape[0]} | DPI: {dpi}")

        # ============================================================
        # 阶段零：倾斜矫正（可选）
        # ============================================================
        skew_angle = 0.0
        page_rotation = 0  # 页面旋转角度（90度倍数）
        low_conf_abandon_regions = []
        orig_shape = image.shape[:2]

        if cfg.ENABLE_DESKEW:
            skew_angle = self._detect_skew_angle(image)
            if skew_angle != 0.0:
                # 只有确实倾斜时才预检测，用于排除矫正后误识别的污渍
                low_conf_abandon_regions = self._pre_detect_low_conf_abandon(image)
                if low_conf_abandon_regions:
                    _log(f"  [预检测] 发现 {len(low_conf_abandon_regions)} 个低置信度 abandon 区域")

                _log(f"  [倾斜矫正] 检测到倾斜角度: {skew_angle:.2f}°，正在矫正...")
                image = self._deskew_image(image, skew_angle)
                _log(f"  [倾斜矫正] 矫正完成，新尺寸: {image.shape[1]}x{image.shape[0]}")

                # 变换预检测区域坐标到矫正后的坐标系
                if low_conf_abandon_regions:
                    low_conf_abandon_regions = self._transform_regions_after_deskew(
                        low_conf_abandon_regions, orig_shape, image.shape[:2], skew_angle
                    )

        # ============================================================
        # 阶段零-A：页面方向矫正（90度旋转检测）
        # ============================================================
        if getattr(cfg, 'ENABLE_PAGE_ORIENTATION', True):
            page_rotation = self._detect_page_orientation(image)
            if page_rotation != 0:
                _log(f"  [页面方向] 正在旋转 {page_rotation} 度...")
                image = self._rotate_image_90(image, page_rotation)
                _log(f"  [页面方向] 旋转完成，新尺寸: {image.shape[1]}x{image.shape[0]}")

        # ============================================================
        # 阶段零-A2：二次倾斜矫正（90°旋转场景专用，REQ-003）
        # ============================================================
        # xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
        # 竖版A4扫描+票据内容横放场景：首轮倾斜检测在旋转前执行，票据文字行近垂直致
        # 文字通道0样本，灰度霍夫测得页框角过矫（d001实测-6.96°过矫残留+3.6°）。
        # 旋转后内容文字行才近水平，补一次检测矫正；四重门控（开关/90°旋转/
        # 首轮文字行<2/累计角上限）保证普通文档路径零行为变化。
        # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
        # REQ-003 门控放宽：竖版图上文字通道可产生"伪正"样本（0107 实测 n_text=15 伪 0°、
        # 霍夫真角 2.95°，分歧≥2° 被加权稀释成 0.885° 欠矫），仅看 n_text<2 拦不住。
        # 当文字角与霍夫角均有效且分歧≥2° 时首轮文字通道不可信，同样放行二次检测；
        # 二次结果仍受投影一致性门控与累计角上限双重保护，正常文档路径行为不变。
        _skew_tel = getattr(self, '_last_skew_telemetry', {})
        _tel_text = _skew_tel.get('text_angle')
        _tel_hough = _skew_tel.get('hough_angle')
        _text_unreliable = (_tel_text is not None and _tel_hough is not None
                            and abs(_tel_hough - _tel_text) >= 2.0)
        if (cfg.ENABLE_DESKEW and getattr(cfg, 'DESKEW_SECOND_PASS', False)
                and page_rotation != 0
                and (_skew_tel.get('n_text', 99) < 2 or _text_unreliable)):
            n_text_first = _skew_tel.get('n_text', '?')
            angle2 = self._detect_skew_angle(image)
            # xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
            # 二次矫正投影一致性门控（首轮回归暴露6张劣化后收紧）：
            # 二次检测必须与投影法一致（改善组|差|≤0.25 vs 劣化组≥0.84），不一致=假信号，拒绝
            proj2, proj2_conf = self._detect_skew_by_projection(image, return_conf=True)
            if angle2 != 0.0 and abs(angle2 - proj2) > cfg.DESKEW_SECOND_PASS_PROJ_DIFF:
                _log(f"  [二次矫正] 拒绝：二次 {angle2:.2f}° 与投影 {proj2:.2f}° 不一致"
                     f"（|差|>{cfg.DESKEW_SECOND_PASS_PROJ_DIFF}°），判定为假信号")
                angle2 = 0.0
            if angle2 != 0.0 and abs(skew_angle + angle2) <= cfg.DESKEW_SECOND_PASS_MAX_TOTAL:
                _log(f"  [二次矫正] 首轮 {skew_angle:.2f}°(文字行样本{n_text_first}) "
                     f"+ 二次 {angle2:.2f}°，执行矫正")
                pre_shape = image.shape[:2]
                image = self._deskew_image(image, angle2)
                skew_angle = skew_angle + angle2
                _log(f"  [二次矫正] 完成，累计 {skew_angle:.2f}°，新尺寸: {image.shape[1]}x{image.shape[0]}")
                # 首轮预检测的低置信区域坐标同步变换到二次矫正后坐标系
                if low_conf_abandon_regions:
                    low_conf_abandon_regions = self._transform_regions_after_deskew(
                        low_conf_abandon_regions, pre_shape, image.shape[:2], angle2
                    )
            elif angle2 != 0.0:
                _log(f"  [二次矫正] 跳过：累计 |{skew_angle:.2f}+{angle2:.2f}|° "
                     f"超上限 {cfg.DESKEW_SECOND_PASS_MAX_TOTAL}°")
            else:
                _log("  [二次矫正] 无可执行角度（二次检测为0或被一致性门控拒绝），跳过")

        h, w = image.shape[:2]
        
        # ============================================================
        # 【性能优化】创建图像缓存，避免重复计算
        # ============================================================
        cache = ImageCache(image)

        # ============================================================
        # 阶段零-B：文件类型判断
        # ============================================================
        # 判断上传的文件类型：
        # - 单据/票据：粘贴在A4纸上的小尺寸彩色票据
        # - 普通文档/表格：内容铺满整页的文档
        _log(f"  [文件类型判断] 正在检测文件类型...")
        
        is_receipt, receipt_mask = self._is_receipt_document(image, cache)
        
        if is_receipt and receipt_mask is not None:
            # ==========================================
            # 单据/票据模式（粘贴在A4纸上的单据）
            # ==========================================
            # 完全保护单据区域内容，仅刷白外部A4纸背景
            _log(f"  [文件类型判断] → 检测为【单据/票据】，启用单据保护模式")
            receipt_result = self._process_receipt_document(image, receipt_mask, skew_angle, page_rotation, debug)
            if receipt_result is not None:
                return receipt_result
            # 单据模式误判回退：掩码外存在大量内容（文字/条形码），回退普通文档模式
            _log(f"  [文件类型判断] → 单据模式检测到误判，回退为【普通文档/表格】模式")
            is_receipt = False
        
        # ============================================================
        # 阶段零-C：彩色票据检测（独立的彩色票据图片）
        # ============================================================
        # 检测图片是否为彩色票据：彩色像素占比超过阈值
        # 彩色票据特点：整张图片就是一张票据，包含大量彩色内容
        is_color_receipt, color_ratio = self._detect_color_receipt(image, cache)
        
        if is_color_receipt:
            # ==========================================
            # 彩色票据模式
            # ==========================================
            # 完全保护票据内容，不做任何净化处理
            _log(f"  [文件类型判断] → 检测为【彩色票据】（彩色占比 {color_ratio*100:.1f}%），跳过所有净化处理")
            result = self._process_color_receipt(image, skew_angle, page_rotation, debug)
            if result is not None:
                return result
            # 如果返回None，说明边界检测失败且彩色比例不高，回退到普通文档模式
            _log(f"  [文件类型判断] → 回退为【普通文档/表格】模式，启用标准处理")
        else:
            # ==========================================
            # 普通文档/表格模式
            # ==========================================
            # 按原有逻辑处理：YOLO检测 + 噪点清理 + 背景白化
            _log(f"  [文件类型判断] → 检测为【普通文档/表格】（彩色占比 {color_ratio*100:.1f}%），启用标准处理模式")

        # ============================================================
        # 阶段一：保护区检测（使用原图）- 普通文档模式
        # ============================================================

        # 1. YOLO 检测保护区（表格、文字、图片等）
            # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-002 传入 debug 控制 vis 拷贝
        protect_mask, figure_mask, vis_yolo = self._detect_protected_regions(image, low_conf_abandon_regions, debug=debug)

        # 2. 公章/硬章保护 + 彩色区域保护（使用缓存的 HSV 图像，一次性检测）
        seal_mask = np.zeros((h, w), dtype=np.uint8)
        color_mask = np.zeros((h, w), dtype=np.uint8)
        
        # 彩色保护默认启用，保护所有彩色单据内容
        enable_color_protection = getattr(cfg, 'ENABLE_COLOR_PROTECTION', True)
        if cfg.ENABLE_SEAL_PROTECTION or enable_color_protection:
            seal_mask, color_mask = self._detect_seals_and_colors(cache)
            if cfg.ENABLE_SEAL_PROTECTION:
                protect_mask = cv2.bitwise_or(protect_mask, seal_mask)
            if enable_color_protection:
                protect_mask = cv2.bitwise_or(protect_mask, color_mask)
                _log(f"  [彩色保护] 已启用，保护 {np.sum(color_mask > 0)} 像素")

        # ============================================================
        # 阶段二：基于连通域的检测（使用缓存，只分析一次）
        # ============================================================
        
        # 获取缓存的二值图和连通域分析结果
        binary = cache.get_binary()
        num_labels, labels, stats, centroids = cache.get_connected_components()
        
        # 3. 检测目录虚线并保护（使用缓存的连通域）
        dotline_protect = self._detect_dotlines(
            binary, protect_mask, num_labels, labels, stats, centroids
        )

        # 4. 图纸模式 - 线条保护（使用缓存的连通域）
        line_protect = np.zeros((h, w), dtype=np.uint8)
        if cfg.ENABLE_DRAWING_MODE:
            line_protect = self._detect_lines(
                binary, protect_mask, num_labels, labels, stats, centroids
            )

        # 5. 框线保护（检测横竖直线，防止表格框线被误删）
        frame_protect = np.zeros((h, w), dtype=np.uint8)
        if cfg.ENABLE_FRAME_PROTECTION:
            frame_protect = self._detect_frame_lines(cache)
            _log(f"  [框线保护] 检测到 {np.sum(frame_protect > 0)} 像素")

        # 6. 文字连通域保护（使用缓存的连通域）
        text_blob_protect = np.zeros((h, w), dtype=np.uint8)
        if cfg.ENABLE_TEXT_BLOB_PROTECTION:
            text_blob_protect = self._detect_text_blobs(
                binary, num_labels, labels, stats, centroids
            )
            _log(f"  [文字保护] 检测到 {np.sum(text_blob_protect > 0)} 像素")

        # 7. 条形码保护（检测密集细竖条模式）
        barcode_protect = np.zeros((h, w), dtype=np.uint8)
        if getattr(cfg, 'ENABLE_BARCODE_PROTECTION', True):
            barcode_protect = self._detect_barcode_regions(
                binary, num_labels, labels, stats
            )

        # V3.1.01 xuechong 2026-07-25 新增：8. 大面积灰色内容保护（工程图纸剖面线、阴影、材料标识）
        # 四层渐进保护：Layer1 核心区域 → Layer1.5 碎片聚合 → Layer2 几何规则性 → Layer3 边缘缓冲
        gray_content_protect = np.zeros((h, w), dtype=np.uint8)
        if getattr(cfg, 'ENABLE_GRAY_CONTENT_PROTECTION', True):
            # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-016 向量化实现（性能优化，算法改进见 _gray_protection_vectorized）
            gray_content_protect = self._gray_protection_vectorized(cache, h, w, kernel_cache)

        # 合并所有保护区
        combined_protect = cv2.bitwise_or(protect_mask, dotline_protect)
        combined_protect = cv2.bitwise_or(combined_protect, line_protect)
        combined_protect = cv2.bitwise_or(combined_protect, frame_protect)
        combined_protect = cv2.bitwise_or(combined_protect, text_blob_protect)
        combined_protect = cv2.bitwise_or(combined_protect, barcode_protect)
        combined_protect = cv2.bitwise_or(combined_protect, gray_content_protect)
        _log(f"  [合并保护区] 总计 {np.sum(combined_protect > 0)} 像素")

        # ============================================================
        # 阶段三：噪点检测（使用缓存的连通域）- 可选
        # ============================================================

        noise_mask = np.zeros((h, w), dtype=np.uint8)
        punch_mask = np.zeros((h, w), dtype=np.uint8)
        crease_mask = np.zeros((h, w), dtype=np.uint8)
        edge_mask = np.zeros((h, w), dtype=np.uint8)
        stray_line_mask = np.zeros((h, w), dtype=np.uint8)
        vis_noise = image.copy() if debug else None

        if cfg.ENABLE_NOISE_DETECT:
            # 5. 黑斑噪点检测（使用缓存的连通域）
            noise_mask, text_protect, vis_noise, edge_noise_stats = self._detect_noise(
                image, cache, combined_protect, debug
            )

            # 创建不含彩色保护的掩码（用于钉痕/折痕检测）
            # 钉痕/折痕可能有轻微颜色，不应该被彩色保护误保护
            non_color_protect = cv2.bitwise_or(protect_mask, dotline_protect)
            non_color_protect = cv2.bitwise_or(non_color_protect, frame_protect)
            non_color_protect = cv2.bitwise_or(non_color_protect, text_blob_protect)
            non_color_protect = cv2.bitwise_or(non_color_protect, barcode_protect)
            # 排除彩色保护掩码，只保留seal_mask（红色印章需要保护）
            non_color_protect = cv2.bitwise_or(non_color_protect, seal_mask)

            # 6. 钉痕迹检测（使用缓存）
            punch_mask = self._detect_punch_holes(cache, non_color_protect)

            # 7. 折痕检测（使用缓存）
            crease_mask = self._detect_creases(cache, non_color_protect)

            # 8. 纵向推土机黑边检测
            edge_mask = self._detect_edge_columns(binary, combined_protect, edge_noise_stats, w)
            
            # 9. 杂质线条检测（使用缓存的连通域）
            stray_line_mask = self._detect_stray_lines(
                binary, combined_protect, num_labels, labels, stats
            )

        # ============================================================
        # 阶段四：清除噪点（置白）- 仅当启用噪点检测时
        # ============================================================

        result = image.copy()

        if cfg.ENABLE_NOISE_DETECT:
            combined = cv2.bitwise_or(noise_mask, edge_mask)
            combined = cv2.bitwise_or(combined, punch_mask)
            combined = cv2.bitwise_or(combined, crease_mask)
            combined = cv2.bitwise_or(combined, stray_line_mask)  # 添加杂质线条
            kernel = kernel_cache.get_ellipse(self._scale_r(cfg.EXPAND_PIXELS) * 2 + 1)
            expanded = cv2.dilate(combined, kernel)
            expanded[combined_protect > 0] = 0
            # zhaoqiaotong 2026-09-17 研发BUG-0060-图档扫描-3.2.14-修复pdf修图流程误伤页码
            # 贴边孤立成行小字（页码"- N -"/网址行）不在combined_protect（YOLO/文字保护
            # 不认连字符等字形伴生部件），噪点/钉痕按孤立小暗斑清除——统一在阶段四
            # 清除处应用文字行豁免兜底（噪点+钉痕+折痕+杂线+推土机五合一）
            _text_exempt_s4 = self._compute_edge_text_exempt(
                binary, int(h * 0.03), int(w * 0.03))
            expanded[_text_exempt_s4] = 0
            # 页码词组保护（普通模式，用户确认页码全模式保留）：页码距页底超出散点带
            # 时（pic2_p2 实测136px>75px带）散点豁免不覆盖，噪点/钉痕按孤立小暗斑清除
            # 页码部件；与单据模式同判据检测词组并入保护（receipt_mask 传零掩码=全图
            # 视为票外，仅底部15%+居中+三段结构命中的词组受保护，宁漏检不误删）
            _pn_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _pn_mask_normal = self._detect_pagenum_phrase_outside(
                _pn_gray, np.zeros((h, w), dtype=np.uint8))
            if _pn_mask_normal is not None:
                expanded[_pn_mask_normal > 0] = 0
            result[expanded > 0] = (255, 255, 255)

            # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
            # REQ-004 微小深色孤立斑强制清除：布局保护框与彩色保护内幸存的淡灰小斑（扫描碎屑），
            # 独立按 245 阈值检测（低于黑斑检测口径的 200~240 灰度段），四重防护防误清内容
            if getattr(cfg, 'ENABLE_TINY_SPOT_CLEAN', False):
                spot_mask = self._detect_tiny_spots(cache, seal_mask, dotline_protect)
                if np.sum(spot_mask > 0) > 0:
                    result[spot_mask > 0] = (255, 255, 255)

        # xuechong 2026-06-01 边缘杂质线独立检测（5条标准，不受protect_mask清除）
        # 在普通文档路径中检测紧贴图片四边的黑色杂质线（扫描阴影/黑边）
        impurity_mask = self._detect_edge_impurity_strips(
            image, cache, is_receipt, is_color_receipt)
        if np.sum(impurity_mask > 0) > 0:
            kernel_imp = kernel_cache.get_ellipse(self._scale_r(cfg.MORPH_KERNEL_TINY) * 2 + 1)  # 轻度膨胀
            impurity_expanded = cv2.dilate(impurity_mask, kernel_imp)
            result[impurity_expanded > 0] = (255, 255, 255)
            _log(f"  [边缘杂质] 清除 {np.sum(impurity_mask > 0)} 像素四边黑色杂质线")

        # ============================================================
        # 阶段四-B：OCR文字保护 + 激进清理
        # ============================================================
        # 先用OCR检测文字区域，添加到保护掩码，再进行激进清理
        # xuechong 2026-10-11 研发BUG-0073 掩码提升到块外初始化：阶段六-B漏光净化的
        # 字缝灰雾档需要尊重OCR文字行（a001实测浅色细笔画文字被误当雾清掉字），与
        # ENABLE_AGGRESSIVE_CLEAN 开关解耦
        ocr_protect_mask = np.zeros((h, w), dtype=np.uint8)
        if cfg.ENABLE_AGGRESSIVE_CLEAN:
            # OCR 文字保护（可选，默认开启）
            if getattr(cfg, 'ENABLE_OCR_TEXT_PROTECT', True):
                try:
                    # 使用缓存的OCR引擎检测文字
                    ocr_engine = _get_cached_ocr_engine(960)  # 使用较大尺寸提高检测精度
                    
                    # 缩放图片用于OCR检测（提高速度）
                    scale = min(1.0, 960 / max(h, w))
                    if scale < 1.0:
                        small_img = cv2.resize(result, None, fx=scale, fy=scale)
                    else:
                        small_img = result
                        scale = 1.0
                    
                    # OCR检测（只检测，不识别，提高速度）
                    ocr_result = ocr_engine(small_img, use_det=True, use_cls=False, use_rec=False)
                    
                    if ocr_result is not None and ocr_result.boxes is not None and len(ocr_result.boxes) > 0:
                        # 将OCR检测到的文字框添加到保护掩码
                        for box in ocr_result.boxes:
                            # box 是 4个点的坐标 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                            pts = np.array(box, dtype=np.float32)
                            # 还原到原图尺寸
                            pts = pts / scale
                            # 获取外接矩形
                            x_min = max(0, int(np.min(pts[:, 0])) - 3)
                            y_min = max(0, int(np.min(pts[:, 1])) - 3)
                            x_max = min(w, int(np.max(pts[:, 0])) + 3)
                            y_max = min(h, int(np.max(pts[:, 1])) + 3)
                            # 添加到保护掩码
                            ocr_protect_mask[y_min:y_max, x_min:x_max] = 255
                        
                        ocr_text_count = len(ocr_result.boxes)
                        _log(f"  [OCR保护] 检测到 {ocr_text_count} 个文字区域，已添加到保护掩码")
                    else:
                        _log(f"  [OCR保护] 未检测到文字区域")
                except Exception as e:
                    import traceback
                    _log(f"  [OCR保护] 检测异常: {e}")
                    _log(f"  [OCR保护] 详细堆栈:\n{traceback.format_exc()}")
                    raise  # 异常即停：OCR保护失败会导致文字被误删

            # 合并OCR保护区到总保护区
            full_protect = cv2.bitwise_or(combined_protect, ocr_protect_mask)

            # 激进清理：保护区外的深色像素刷白
            gray_result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            dark_pixels = gray_result < cfg.AGGRESSIVE_CLEAN_THRESHOLD
            outside_protect = full_protect == 0
            aggressive_mask = np.logical_and(dark_pixels, outside_protect)
            # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
            # REQ-008 深核邻域保护：OCR 检测不到的小号浅色文字（006/007 实测被淡化致 OCR
            # 漏识别）无保护框，其笔画被 <245 一刀切刷白。真文字必有深色笔画核心（<180），
            # 膨胀 15px 保护其周边浅像素；污渍/灰噪无深核，仍正常清除
            _dark_core = (gray_result < 180).astype(np.uint8) * 255
            _core_dil = cv2.dilate(_dark_core,
                                   kernel_cache.get_ellipse(self._scale_r(15) * 2 + 1))
            aggressive_mask &= (_core_dil == 0)
            result[aggressive_mask] = (255, 255, 255)
            _log(f"  [激进清理] 保护区外刷白 {np.sum(aggressive_mask)} 像素")

        # ============================================================
        # 阶段五：背景白化（最后做，抠图式处理）
        # 注意：彩色票据/单据需要整体保护，不做背景白化
        # 注意：已经是白色背景的图片（白色比例>85%）跳过背景白化，避免误伤文字
        # ============================================================
        enhanced_image = None
        if cfg.ENABLE_BACKGROUND_ENHANCE:
            # 检测彩色像素比例，判断是否为彩色票据/单据
            # 使用更严格的彩色检测（S>40），避免把灰色污渍误判为彩色
            hue, saturation, value = cache.get_hsv_channels()
            strict_color_pixels = np.sum((saturation > 40) & (value > 50) & (value < 250))
            total_pixels = h * w
            color_ratio = strict_color_pixels / total_pixels
            
            # xuechong 2026-06-30 彩色票据阈值：统一使用 config.py 定义的阈值 0.15
            color_receipt_threshold = getattr(cfg, 'COLOR_RECEIPT_THRESHOLD', 0.15)
            
            # 【关键修复】检测图片是否已经是白色背景（白色比例>85%）
            # 如果图片已经很白，使用保守的背景白化策略，避免误伤淡色文字
            white_threshold = 240
            white_pixels = np.sum(np.all(result > white_threshold, axis=2))
            white_ratio = white_pixels / total_pixels
            
            # 白色背景阈值：如果白色像素超过85%，使用保守白化
            high_white_threshold = getattr(cfg, 'HIGH_WHITE_SKIP_THRESHOLD', 0.85)
            
            if white_ratio >= high_white_threshold:
                # 已经是白色背景的图片：使用保守的背景白化策略
                # 只将接近白色的像素（>250）变成纯白，保护淡色文字
                _log(f"  [背景白化] 高白比例图片（{white_ratio*100:.1f}%），使用保守白化策略")
                
                # 保守策略：只白化非常接近白色的像素（RGB都>250）
                # 这样#FEFEFE(254,254,254)会变成#FFFFFF，但文字不会受影响
                near_white_threshold = getattr(cfg, 'NEAR_WHITE_THRESHOLD', 250)
                near_white_mask = np.all(result > near_white_threshold, axis=2)
                # V3.1.01 xuechong 2026-07-25 修复：排除大面积灰色内容保护区，防止工程图纸灰色区域被白化
                if np.sum(gray_content_protect > 0) > 0:
                    near_white_mask = near_white_mask & (gray_content_protect == 0)
                result[near_white_mask] = (255, 255, 255)
                
                near_white_count = np.sum(near_white_mask)
                _log(f"  [背景白化] 保守白化完成：{near_white_count} 像素 ({100*near_white_count/total_pixels:.1f}%) 变为纯白")

                # xuechong 2026-08-07 研发BUG-0018 高白图片散点灰噪补充清理
                # 保守白化只清理>250像素，210-250区间的散点灰噪未被清理
                # 严格限制：低饱和度(S<25无颜色) + 远离深色内容 + 未被彩色/印章保护
                # 注意：必须保留 color_mask 保护，否则黄色/浅色内容会被误清（b001/b002教训）
                _gray_sc = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
                _hsv_sc = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
                _sat_sc = _hsv_sc[:, :, 1]
                _dark_sc = _gray_sc < 180
                _kernel_sc = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_SMALL), self._scale_r(cfg.MORPH_KERNEL_SMALL))
                _dark_dil_sc = cv2.dilate(_dark_sc.astype(np.uint8), _kernel_sc, iterations=2)
                _scatter = (_gray_sc >= 210) & (_gray_sc < 250) & (_sat_sc < 25) & (_dark_dil_sc == 0)
                if color_mask is not None and np.sum(color_mask > 0) > 0:
                    _scatter = _scatter & (color_mask == 0)
                if seal_mask is not None and np.sum(seal_mask > 0) > 0:
                    _scatter = _scatter & (seal_mask == 0)
                # xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景
                # 散点清理必须排除灰色保护区：L1.5 关闭后图纸类图片的散碎灰雾被清理、白度跨过
                # 高白阈值进入保守路径，散点清理曾把 L1 保护的实心灰矩形（206-218，≥210 部分
                # 落在散点射程）当作灰噪刷白（实测刷白 53.3%，比 3.0.3 的 34.9% 更狠）；
                # 保护区内的噪声由"灰色保护区噪声清理"两步（中值滤波+纯白碎片）负责，不归散点清理管
                if np.sum(gray_content_protect > 0) > 0:
                    _scatter = _scatter & (gray_content_protect == 0)
                _scatter_count = np.sum(_scatter)
                if _scatter_count > 0:
                    result[_scatter] = (255, 255, 255)
                    _log(f"  [保守白化-散点清理] 清除纯灰噪 {_scatter_count} 像素 ({100*_scatter_count/total_pixels:.1f}%)")
            elif color_ratio >= color_receipt_threshold:
                # 彩色票据/单据：跳过背景白化，保护整个图片
                _log(f"  [背景白化] ⚠️ 检测到彩色票据/单据（彩色像素占比 {color_ratio*100:.1f}% >= {color_receipt_threshold*100:.0f}%）")
                _log(f"  [背景白化] ⚠️ 跳过背景白化，保护票据内容完整性")
                # 不做任何处理，保留原图
            else:
                # 普通文档：执行背景白化
                # 保护彩色区域（印章 + 其他彩色内容）+ 条形码区域
                # 文字等黑色内容会通过亮度差异自动被识别为前景
                # 但条形码的细竖条可能因亮度与背景接近而被误白化，需显式保护
                color_protect_mask = cv2.bitwise_or(seal_mask, color_mask)
                color_protect_mask = cv2.bitwise_or(color_protect_mask, barcode_protect)
                color_protect_mask = cv2.bitwise_or(color_protect_mask, gray_content_protect)  # V3.1.01 灰色内容保护
                result = self._enhance_background(result, color_protect_mask)
                enhanced_image = result.copy() if debug else None
                _log(f"  [背景白化] 已完成（彩色像素占比 {color_ratio*100:.1f}%, 白色占比 {white_ratio*100:.1f}%）")

                # ============================================================
                # 智能污渍清除：清除灰色低饱和度污渍
                # ============================================================
                # 背景白化可能没有完全清除灰色污渍（如扫描阴影、纸张老化痕迹等）
                # 这里进行二次清理：只保护真正的内容，清除其他灰色区域
                if getattr(cfg, 'ENABLE_SMART_STAIN_CLEAN', True):
                    gray_result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
                    hsv_result = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
                    sat_result = hsv_result[:, :, 1]

                    # 真正的内容：深色文字(<180) 或 高饱和度彩色(>40) 或 条形码保护区
                    real_content = (gray_result < 180) | (sat_result > 40) | (barcode_protect > 0)
                    # 膨胀保护文字边缘
                    kernel_content = kernel_cache.get_rect(self._scale_r(cfg.MORPH_KERNEL_SMALL), self._scale_r(cfg.MORPH_KERNEL_SMALL))
                    real_content_dilated = cv2.dilate(real_content.astype(np.uint8), kernel_content, iterations=2)

                    # 可以安全清除的灰色污渍：灰度>180, 饱和度<30, 不在内容保护区，不在大面积灰色内容保护区
                    safe_to_clean = (gray_result > 180) & (sat_result < 30) & (real_content_dilated == 0) & (gray_content_protect == 0)

                    # 应用清除
                    stain_cleaned_count = np.sum(safe_to_clean)
                    if stain_cleaned_count > 0:
                        result[safe_to_clean] = (255, 255, 255)
                        _log(f"  [智能污渍清除] 清除灰色污渍: {stain_cleaned_count} 像素 ({100*stain_cleaned_count/total_pixels:.1f}%)")

        # ============================================================
        # 阶段五后：灰色保护区噪声清理（中值滤波 + 纯白碎片清理）
        # ============================================================
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化
        # 灰色保护掩码内含大量扫描仪噪声（240-250 的散点），不清理则输出“稀碎花里胡哨”
        # 但灰度阈值刷白（≥238）会误删灰色矩形内容（002.tif 灰色保留率仅 24%）
        # 新策略两步：①中值滤波平滑保护区内边缘噪声，保留灰色矩形大块结构；
        # ②只清理“纯白噪声碎片”（面积<min_area 且平均灰度>mean_threshold），不伤灰色内容
        # 实测：002.tif 灰色保留率从 24% 提升至 87%，小碎片从 14192 降至 349
        if np.sum(gray_content_protect > 0) > 0:
            _gp_median_ksize = getattr(cfg, 'GRAY_PROTECT_MEDIAN_KSIZE', 3)
            _gp_noise_min = getattr(cfg, 'GRAY_PROTECT_NOISE_MIN_AREA', 200)
            _gp_noise_mean = getattr(cfg, 'GRAY_PROTECT_NOISE_MEAN_GRAY', 235)

            # xuechong 2026-08-07 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 修复彩色被灰度化
            # 彩色像素排除掩码：饱和度 >=15 的像素视为彩色内容（印章/手写/淡色标注等）
            # 原阈值 25 会误伤低饱和度彩色（浅黄/浅蓝印章），降至 15 确保彩色零影响
            _hsv_gp = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
            _non_color_mask = _hsv_gp[:, :, 1] < 15

            # Step 1：中值滤波平滑保护区内边缘噪声
            # ⚠ 安全约束：只替换保护区内非彩色像素
            if _gp_median_ksize > 0:
                _gray_gp = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
                _medianed = cv2.medianBlur(_gray_gp, _gp_median_ksize)
                _medianed_bgr = cv2.cvtColor(_medianed, cv2.COLOR_GRAY2BGR)
                _gp_safe = (gray_content_protect > 0) & _non_color_mask
                result[_gp_safe] = _medianed_bgr[_gp_safe]
                _log(f"  [灰色保护区噪声清理] 中值滤波({_gp_median_ksize}x{_gp_median_ksize})平滑保护区（排除彩色像素）")

            # Step 2：只清理纯白噪声碎片（不伤灰色内容、不伤彩色内容）
            # xuechong 2026-08-07 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 向量化Step2
            # 旧版逐连通域循环 _labels_nw == _ni 复杂度 O(N×pixels)，数千碎片耗时数分钟
            # 新版用 np.bincount + np.isin 一次性计算，复杂度 O(pixels + N)
            if _gp_noise_min > 0:
                _gray_gp2 = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
                _nonwhite_gp = ((_gray_gp2 <= 240) & (gray_content_protect > 0) & _non_color_mask).astype(np.uint8) * 255
                _num_nw, _labels_nw, _stats_nw, _ = cv2.connectedComponentsWithStats(_nonwhite_gp, connectivity=8)
                if _num_nw > 1:
                    _nw_areas = _stats_nw[1:, cv2.CC_STAT_AREA]
                    _small_mask = _nw_areas < _gp_noise_min
                    if np.any(_small_mask):
                        _gray_flat = _gray_gp2.ravel()
                        _labels_flat = _labels_nw.ravel()
                        _sum_gray = np.bincount(_labels_flat, weights=_gray_flat.astype(np.float64), minlength=_num_nw)
                        _cnt_gray = np.bincount(_labels_flat, minlength=_num_nw)
                        _mean_gray = _sum_gray[1:] / np.maximum(_cnt_gray[1:], 1)
                        _to_clean = _small_mask & (_mean_gray > _gp_noise_mean)
                        _to_clean_ids = np.where(_to_clean)[0] + 1
                        if len(_to_clean_ids) > 0:
                            _clean_mask = np.isin(_labels_nw, _to_clean_ids)
                            result[_clean_mask] = (255, 255, 255)
                            _log(f"  [灰色保护区噪声清理] 纯白噪声碎片(<{_gp_noise_min}px, gray>{_gp_noise_mean})清理: {len(_to_clean_ids)} 个 ({int(np.sum(_clean_mask))} 像素)")

        # ============================================================
        # 阶段六：文档边界外强力净化
        # ============================================================
        # 检测文档/票据的矩形边界，边界外的污渍、曝光等全部刷白
        # 重要：使用原始图片(image)检测边界，因为result可能已被处理导致饱和度改变
        if getattr(cfg, 'ENABLE_BOUNDARY_CLEAN', True):
            result = self._clean_outside_boundary(result, combined_protect, image)

        # xuechong 2026-10-10 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
        # 阶段六-B：贴边漏光净化（普通文档路径漏光渍无任何机制负责，本步骤补位）。
        # 硬保护=印章/YOLO/文字/框线等全部保护剔除灰色内容保护后的并集（绝对排除）；
        # 彩色保护单独传入，由净化方法按域级饱和度判定区分渍与真彩色内容。
        # 灰色内容保护不传入——本步骤清理的正是它在边缘带误罩的漏光渍
        if getattr(cfg, 'ENABLE_EDGE_LIGHTLEAK_CLEAN', False):
            _ll_hard = cv2.bitwise_and(protect_mask, cv2.bitwise_not(color_mask))
            _ll_hard = cv2.bitwise_or(_ll_hard, seal_mask)
            _ll_hard = cv2.bitwise_or(_ll_hard, dotline_protect)
            _ll_hard = cv2.bitwise_or(_ll_hard, line_protect)
            _ll_hard = cv2.bitwise_or(_ll_hard, frame_protect)
            _ll_hard = cv2.bitwise_or(_ll_hard, text_blob_protect)
            _ll_hard = cv2.bitwise_or(_ll_hard, barcode_protect)
            result = self._clean_edge_lightleak(result, _ll_hard, color_mask, binary,
                                                figure_mask, seal_mask, frame_protect, ocr_protect_mask)
            # 页内蓝灰云斑补扫 + 灰雾页纸面灰雾漂白（封面页中部，贴边带够不着）
            result = self._clean_interior_lightleak(result, _ll_hard, color_mask, seal_mask, figure_mask, binary, image, ocr_protect_mask)

        # ============================================================
        # 可视化（debug 模式）
        # ============================================================
        if debug:
            vis_noise[dotline_protect > 0] = [255, 200, 0]  # 青色标记虚线保护
            vis_noise[edge_mask > 0] = [0, 255, 255]  # 黄色标记黑边
            vis_noise[punch_mask > 0] = [255, 0, 255]  # 紫色标记钉痕迹
            vis_noise[crease_mask > 0] = [255, 128, 0]  # 蓝橙色标记折痕
            vis_noise[stray_line_mask > 0] = [128, 0, 128]  # 深紫色标记杂质线条
            vis_noise[seal_mask > 0] = [0, 0, 255]  # 红色标记公章保护
            vis_noise[color_mask > 0] = [0, 165, 255]  # 橙色标记彩色区域保护
            if cfg.ENABLE_DRAWING_MODE:
                vis_noise[line_protect > 0] = [0, 255, 0]  # 绿色标记线条保护

        return {
            'result': result,
            'original': image.copy() if debug else None,  # 原图（矫正后、清理前）
            'noise_mask': noise_mask,
            'edge_mask': edge_mask,
            'punch_mask': punch_mask,
            'crease_mask': crease_mask,  # 折痕掩码
            'stray_line_mask': stray_line_mask,  # 杂质线条掩码
            'protect_mask': protect_mask,
            'seal_mask': seal_mask,
            'color_mask': color_mask,  # 彩色区域保护掩码
            'dotline_protect': dotline_protect,
            'line_protect': line_protect if cfg.ENABLE_DRAWING_MODE else None,
            'frame_protect': frame_protect if debug else None,
            'text_blob_protect': text_blob_protect if debug else None,
            'enhanced_image': enhanced_image,
            'vis_yolo': vis_yolo if debug else None,
            'vis_noise': vis_noise if debug else None,
            'skew_angle': skew_angle,  # 倾斜角度（度）
            'page_rotation': page_rotation,  # 页面旋转角度（90度倍数）
            'receipt_mask': None,
            'vis_receipt': None,
            'is_receipt': False,
            'is_color_receipt': False,
        }
    
    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-016 灰色保护旧实现（保留供对比回归）
    def _gray_protection_legacy(self, cache: "ImageCache", h: int, w: int,
                                kernel_cache: "KernelCache") -> np.ndarray:
        """灰色保护旧实现（逐连通域循环，性能差但掩码正确，供回归验证）"""
        _gray_ch = cache.gray
        _, _sat_ch, _ = cache.get_hsv_channels()
        _light_gray = (_gray_ch >= 190) & (_gray_ch < 245) & (_sat_ch < 35)
        _gray_uint8 = _light_gray.astype(np.uint8) * 255
        _num_g, _labels_g, _stats_g, _ = cv2.connectedComponentsWithStats(_gray_uint8, connectivity=8)
        _min_area = getattr(cfg, 'GRAY_CONTENT_MIN_AREA', 200)

        # Layer 1: 逐循环大面积过滤
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-003 面积上限过滤，防止大块浅灰背景被保护
        _max_area_ratio_l = getattr(cfg, 'GRAY_CONTENT_MAX_AREA_RATIO', 0.05)
        _max_area_l = int(h * w * _max_area_ratio_l) if _max_area_ratio_l > 0 else 0
        _layer1 = np.zeros((h, w), dtype=np.uint8)
        for _gi in range(1, _num_g):
            _area_g = _stats_g[_gi, cv2.CC_STAT_AREA]
            if _area_g >= _min_area and (_max_area_l <= 0 or _area_g <= _max_area_l):
                _layer1[_labels_g == _gi] = 255

        # Layer 1.5: 小碎片聚合
        _layer15 = np.zeros((h, w), dtype=np.uint8)
        _cluster_min_area = getattr(cfg, 'GRAY_CLUSTER_MIN_AREA', 5000)
        _cluster_close_ksize = getattr(cfg, 'GRAY_CLUSTER_CLOSE_KSIZE', 15)
        _small_fragments = np.zeros((h, w), dtype=np.uint8)
        for _gi in range(1, _num_g):
            if _stats_g[_gi, cv2.CC_STAT_AREA] < _min_area:
                _small_fragments[_labels_g == _gi] = 255
        _small_count = np.sum(_small_fragments > 0)
        if _small_count > 0:
            _k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (_cluster_close_ksize, _cluster_close_ksize))
            _clustered = cv2.morphologyEx(_small_fragments, cv2.MORPH_CLOSE, _k_close, iterations=2)
            _num_c, _labels_c, _stats_c, _ = cv2.connectedComponentsWithStats(_clustered, connectivity=8)
            for _ci in range(1, _num_c):
                _c_area = _stats_c[_ci, cv2.CC_STAT_AREA]
                if _c_area >= _cluster_min_area:
                    _cx = _stats_c[_ci, cv2.CC_STAT_LEFT]
                    _cy = _stats_c[_ci, cv2.CC_STAT_TOP]
                    _cbw = _stats_c[_ci, cv2.CC_STAT_WIDTH]
                    _cbh = _stats_c[_ci, cv2.CC_STAT_HEIGHT]
                    _cy2 = min(_cy + _cbh, h)
                    _cx2 = min(_cx + _cbw, w)
                    _layer15[_cy:_cy2, _cx:_cx2] = 255

        # Layer 2: 几何规则性
        _layer2 = np.zeros((h, w), dtype=np.uint8)
        _fill_threshold = getattr(cfg, 'GRAY_FILL_RATIO_THRESHOLD', 0.65)
        _rect_min_area = getattr(cfg, 'GRAY_RECT_MIN_AREA', 500)
        for _gi in range(1, _num_g):
            _area = _stats_g[_gi, cv2.CC_STAT_AREA]
            if _area < _rect_min_area:
                continue
            _x = _stats_g[_gi, cv2.CC_STAT_LEFT]
            _y = _stats_g[_gi, cv2.CC_STAT_TOP]
            _bw = _stats_g[_gi, cv2.CC_STAT_WIDTH]
            _bh = _stats_g[_gi, cv2.CC_STAT_HEIGHT]
            _bbox_area = _bw * _bh
            if _bbox_area == 0:
                continue
            _fill_ratio = _area / _bbox_area
            if _fill_ratio >= _fill_threshold:
                _y2 = min(_y + _bh, h)
                _x2 = min(_x + _bw, w)
                _layer2[_y:_y2, _x:_x2] = 255

        # Layer 3: 边缘缓冲
        _core_mask = cv2.bitwise_or(_layer1, _layer15)
        _core_mask = cv2.bitwise_or(_core_mask, _layer2)
        gray_content_protect = np.zeros((h, w), dtype=np.uint8)
        if np.sum(_core_mask > 0) > 0:
            _k_edge = kernel_cache.get_ellipse(self._scale_r(5) * 2 + 1)
            gray_content_protect = cv2.dilate(_core_mask, _k_edge, iterations=2)

        _l1_px = np.sum(_layer1 > 0)
        _l15_px = np.sum((_layer15 > 0) & (_layer1 == 0))
        _l2_px = np.sum((_layer2 > 0) & (_layer1 == 0) & (_layer15 == 0))
        _l3_px = np.sum(gray_content_protect > 0) - np.sum(_core_mask > 0)
        _log(f"  [灰色保护-旧] L1核心:{_l1_px} L1.5聚合:{_l15_px} L2几何:{_l2_px} L3边缘:{_l3_px} 总计:{np.sum(gray_content_protect > 0)} 像素")
        return gray_content_protect

    # xuechong 2026-10-10 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
    # 贴边漏光净化：扫描仪漏光在纸张边界外留下浅色污渍（灰度190~245、几乎无颜色），
    # 灰色内容保护把它误当成图纸灰内容罩住（002.tif 实测渍区 31.2% 被罩），背景白化清不动；
    # 浓渍块的个别深点（饱和度≥20）还会被彩色保护当种子膨胀罩住整块，两条保护一起拦。
    # 本方法按域处理：四边边缘带内的浅灰候选连成片后，整片区域满足"主体低饱和 + 深灰纹理
    # 比低于上限"才整域清白；印章等硬保护、深色内容净空圈、页码文字豁免区像素级绝对排除。
    # 首版只清贴边带，封面页中部的大块蓝灰云斑漏网（用户实测001封面两块425x223/472x245
    # 残留），追加页内补扫：页内没有"贴边"这道位置保险，收紧为只清带蓝偏的大块
    # （图纸实心灰色填充/灰矩形是中性灰不带蓝偏，BUG-0026 的保护对象从这里排除）。
    # 页面中间的真内容不碰；config.ENABLE_EDGE_LIGHTLEAK_CLEAN=False 时调用方直接跳过
    def _clean_edge_lightleak(self, result: np.ndarray, hard_protect: np.ndarray,
                              color_mask: np.ndarray, binary: np.ndarray,
                              figure_mask_e: np.ndarray = None,
                              seal_mask_e: np.ndarray = None,
                              frame_protect_e: np.ndarray = None,
                              ocr_mask_e: np.ndarray = None) -> np.ndarray:
        """四边边缘带内漏光浅渍净化（普通文档路径专用，参数全部走 config）"""
        h, w = result.shape[:2]
        gray_ch = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
        sat_ch = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)[:, :, 1]

        margin_ratio = getattr(cfg, 'EDGE_LIGHTLEAK_MARGIN_RATIO', 0.05)
        gray_low = getattr(cfg, 'EDGE_LIGHTLEAK_GRAY_LOW', 190)
        gray_high = getattr(cfg, 'EDGE_LIGHTLEAK_GRAY_HIGH', 245)
        sat_max = getattr(cfg, 'EDGE_LIGHTLEAK_SAT_MAX', 20)
        sat_domain_ratio = getattr(cfg, 'EDGE_LIGHTLEAK_SAT_DOMAIN_RATIO', 0.6)
        texture_max = getattr(cfg, 'EDGE_LIGHTLEAK_TEXTURE_MAX', 0.03)
        clearance = self._scale_r(getattr(cfg, 'EDGE_LIGHTLEAK_CLEARANCE', 15))

        # 判据1：四边边缘带（渍块跨出边界的部分不清，属于"漏清"，可接受）
        band_v = max(1, int(h * margin_ratio))
        band_h = max(1, int(w * margin_ratio))
        candidate = np.zeros((h, w), dtype=bool)
        candidate[:band_v, :] = True
        candidate[h - band_v:, :] = True
        candidate[:, :band_h] = True
        candidate[:, w - band_h:] = True

        # 判据2/6：灰保护带同区间灰度；印章/YOLO/文字/框线等硬保护绝对排除。
        # 彩色保护区域不排除、参与成域——浓渍块被彩色保护当种子罩住，靠域级饱和度
        # 判定（判据3）区分渍与真彩色内容
        candidate &= (gray_ch >= gray_low) & (gray_ch < gray_high)
        candidate &= (hard_protect == 0)
        if not candidate.any():
            _log(f"  [贴边漏光净化] 边缘带内无候选像素，跳过")
            return result

        # 判据3+4（域级）：候选连成片后整域判定，两关都过才整域保留——
        # 域内低饱和（S<sat_max）占比达标：漏光渍主体浅淡，真彩色内容（印章/彩笔迹）
        # 域内高饱和像素占比高，进不来；
        # 邻域深色密度低于上限：剖面线/网纹的线条紧贴域像素（17px窗口圈进来），
        # 密度高整域拒绝；漏光渍浮在空白处密度趋近0（_lightleak_domain_filter）
        num_ll, labels_ll, stats_ll, _ = cv2.connectedComponentsWithStats(
            candidate.astype(np.uint8) * 255, connectivity=8)
        keep = self._lightleak_domain_filter(labels_ll, stats_ll, num_ll, gray_ch, sat_ch,
                                             sat_max, sat_domain_ratio, texture_max, 0)

        # 判据5：距深色内容（灰度<180，文字/框线/页码本体）净空半径内的像素剔除，
        # 页码与贴边文字周边的抗锯齿灰边因此安全
        k_clear = kernel_cache.get_ellipse(clearance * 2 + 1)
        keep &= (cv2.dilate((gray_ch < 180).astype(np.uint8) * 255, k_clear) == 0)

        # 判据6：页码文字行豁免（与推土机/散点清理共用，BUG-0060 建立的页码保护）；
        # 彩色保护种子（S≥sat_max）像素仍不清——只清膨胀带，不动彩色判定本体
        keep &= ~self._compute_edge_text_exempt(binary, int(h * 0.03), int(w * 0.03))
        keep &= ~((color_mask > 0) & (sat_ch >= sat_max))

        final = candidate & keep
        clean_count = int(np.sum(final))
        if clean_count == 0:
            _log(f"  [贴边漏光净化] 判据过滤后无剩余像素，跳过")
            result_edge = 0
        else:
            result[final] = (255, 255, 255)
            result_edge = clean_count
            _log(f"  [贴边漏光净化] 边缘带清除浅渍 {clean_count} 像素 ({100*clean_count/(h*w):.2f}%)")

        # xuechong 2026-10-11 研发BUG-0073 渍尾补扫（用户验收发现的页顶残余碎渣）：
        # 漏光渍边缘碎渣（几百~两千px）亮度245~254超出白化/漂白带、面积不够页内蓝灰
        # 门槛、且部分像素蓝偏不足（B-R≈3）过不了蓝偏判据——三档全漏网。
        # 贴边带内有"位置贴边"这道天然保险（真实内容不会出现在纸张边界之外），
        # 带内低饱和非白碎片直接清（灰度下限190保深色内容、四道像素级保护保留）
        # xuechong 2026-10-11 研发BUG-0073 渍尾碎渣档重构（用户复验右边缘仍有4粒小斑点）：
        # 旧档三处漏网——面积150px门槛漏掉7~100px碎渣、灰度下限190漏掉185的蓝点、
        # 饱和度上限漏掉S=40的蓝核、灰度上限254漏掉254的浅尾、且5%带宽漏掉6.5%处的碎渣。
        # 边缘带有"位置保险"（真实内容不在纸边，页码有文字行豁免+净空圈、框线在硬保护），
        # 本档放宽为：带内灰度180~254、饱和度<45（红章S≥80仍被挡）、碎片≥3px一律清，
        # 不再要求蓝偏（中性灰尘/纸屑也是该清的对象）
        tail_min_e = max(3, int(getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_MIN_AREA', 3)
                                * (self._current_dpi / 300.0) ** 2))
        tail_high_e = getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_GRAY_HIGH', 255)
        tail_low_e = getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_GRAY_LOW', 180)
        tail_sat_e = getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_SAT_MAX', 45)
        tail_band_e = getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_BAND', 0.08)
        tail_v_e = max(band_v, int(h * tail_band_e))
        tail_h_e = max(band_h, int(w * tail_band_e))
        tail_zone_e = np.zeros((h, w), dtype=bool)
        tail_zone_e[:tail_v_e, :] = True
        tail_zone_e[h - tail_v_e:, :] = True
        tail_zone_e[:, :tail_h_e] = True
        tail_zone_e[:, w - tail_h_e:] = True
        # xuechong 2026-10-11 研发BUG-0073 渍尾碎渣档（双集合架构，修复三轮用户复验迭代）：
        # 集合a（YOLO框内小碎屑）：表格/标题的YOLO矩形框会罩住框内大片空白纸面，框内
        #   空白处的孤立小渍（5~400px、距深色内容≥5px）清——用户复验的页顶/右边缘
        #   斑点全部在此；距深色≥5px保证不碰字缘/线缘过渡带（过渡带仅1~3px宽）
        # 集合b（框外页边距碎屑）：框外页边距的渍屑（3~2000px、距深色≥3px）清
        # 共同判据：灰度180~254、饱和度<45（红章S≥80挡住）、figure框/印章(S≥20)/
        # 文字行豁免排除。尺寸上限挡大块内容（图纸灰填充/长线数千~数万px不受影响，
        # 这是BUG-0026图纸红线的安全边界，pytest test_bug0026 验证）
        _text_exempt_e = self._compute_edge_text_exempt(binary, int(h * 0.03), int(w * 0.03))
        # xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-净化误删正常内容修复
        # 四档清除共用的内容救援上下文（每页构建一次）：条带OCR检测框（判据A）、
        # HSV色相通道（判据F）、长线共线基准掩码（判据E）。总开关关闭时为None，
        # 四档清除行为与3.3.03完全一致
        _rescue_ctx = None
        if getattr(cfg, 'EDGE_LIGHTLEAK_CONTENT_RESCUE_ENABLE', True):
            _rescue_ctx = self._build_rescue_context(result, gray_ch, tail_v_e, tail_h_e)
        # xuechong 2026-10-11 研发BUG-0073 暗色碎屑档：页边距空白处的深色小标记（笔痕/
        # 渍核，整体含晕仅几十~几百px）——"深色=内容"的底线在纸边不成立。真内容排除：
        # 页码词组掩码、照片框、印章、文字行豁免；面积上限200px（页码字符/长线远超）。
        # 有意不尊重YOLO框（框罩住页边距空白纸面，用户复验斑点实测在框内被拦）。
        # 核心清掉后置白，后续浅色档的净空随之释放，整个标记连晕清干净
        _dark_max_e = int(getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_DARK_MAX', 200)
                          * (self._current_dpi / 300.0) ** 2)
        _dd_cand = (gray_ch < 180) & tail_zone_e                    & (figure_mask_e == 0) & (seal_mask_e == 0) & ~_text_exempt_e
        if ocr_mask_e is not None:
            _dd_cand &= (ocr_mask_e == 0)
        _pn_mask_e = self._detect_pagenum_phrase_outside(gray_ch, np.zeros((h, w), dtype=np.uint8))
        if _pn_mask_e is not None:
            _dd_cand &= ~(_pn_mask_e > 0)
        if _dd_cand.any():
            _n_dd, _l_dd, _st_dd, _ = cv2.connectedComponentsWithStats(
                _dd_cand.astype(np.uint8) * 255, connectivity=8)
            # xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-净化误删正常内容修复
            # 暗屑档候选内容救援：面积合格标签先过六条判据（A~F）过滤，任一命中即
            # 从清除名单排除——008序号数字/010条形码/10-09页码/044行线段均由本档误删
            _dd_ids = self._lightleak_content_rescue(
                _st_dd,
                np.where(_st_dd[1:, cv2.CC_STAT_AREA] <= _dark_max_e)[0] + 1,
                _rescue_ctx, "暗屑档")
            _dd_ok = np.isin(_l_dd, _dd_ids)
            _dd_final = _dd_cand & _dd_ok
            if _dd_final.any():
                result[_dd_final] = (255, 255, 255)
                gray_ch[_dd_final] = 255
                _log(f"  [贴边漏光净化] 边缘带暗色碎屑清除 {int(_dd_final.sum())} 像素")
        # xuechong 2026-10-11 研发BUG-0073 细长黑痕条档：划痕/针痕（黑边样张014/015右缘
        # 实测13x181/7x99，深黑灰度46~154、面积347~1291px超出暗屑档200px上限）。
        # 三道误保护实测：①图纸线条检测line_protect 100%罩住（划痕形态似线条）；
        # ②文字行豁免掩码罩住（竖条被当成贴边文字字形）。故本档不尊重line_protect、
        # YOLO框与文字行豁免；仍排除frame_protect（真表格线本体）、figure框（照片）、
        # 印章、页码词组掩码（页码字符高约45px够不到60px长边门槛，双保险）。
        # 位置判据：连通域外接框距某一条纸边≤30px（贴边划痕014距右纸边9px、015为18px；
        # 图纸/文字内容距纸边一般远大于此），加细长形态双条件，窄口径保安全。
        # 面积50~8000px防零星噪点与纸边整条阴影带误清
        _sl_dpi = (self._current_dpi / 300.0) if getattr(self, '_current_dpi', None) else 1.0
        _sl_thin = max(6, self._scale_r(getattr(cfg, 'EDGE_LIGHTLEAK_STREAK_THICK', 14)))
        _sl_long = self._scale_r(getattr(cfg, 'EDGE_LIGHTLEAK_STREAK_MIN_LEN', 60))
        _sl_max = int(getattr(cfg, 'EDGE_LIGHTLEAK_STREAK_MAX_AREA', 8000) * _sl_dpi * _sl_dpi)
        _sl_edge = max(band_v, band_h, self._scale_r(getattr(cfg, 'EDGE_LIGHTLEAK_STREAK_EDGE', 30)))
        _sl_cand = (gray_ch < 180) & tail_zone_e \
                   & (frame_protect_e == 0) & (figure_mask_e == 0) & (seal_mask_e == 0)
        if _pn_mask_e is not None:
            _sl_cand &= ~(_pn_mask_e > 0)
        if _sl_cand.any():
            _n_sl, _l_sl, _st_sl, _ = cv2.connectedComponentsWithStats(
                _sl_cand.astype(np.uint8) * 255, connectivity=8)
            _sl_ids = []
            for i in range(1, _n_sl):
                a = int(_st_sl[i, 4])
                if a < 50 or a > _sl_max:
                    continue
                bw, bh = int(_st_sl[i, 2]), int(_st_sl[i, 3])
                if min(bw, bh) > _sl_thin or max(bw, bh) < _sl_long:
                    continue
                x, y = int(_st_sl[i, 0]), int(_st_sl[i, 1])
                near_edge = (x <= _sl_edge or (x + bw) >= w - _sl_edge
                             or y <= _sl_edge or (y + bh) >= h - _sl_edge)
                if near_edge:
                    _sl_ids.append(i)
            if _sl_ids:
                # xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-净化误删正常内容修复
                # 细长档候选内容救援：本档候选全部贴边（距纸边≤30px），判据E的贴边
                # 排除对它们永不生效（右缘黑痕014/015继续清）；判据A/B/C/D/F仍可救回
                # 贴边真实内容（07-20批009右缘折叠虚线由判据C成列等距救回）
                _sl_ids = list(self._lightleak_content_rescue(
                    _st_sl, np.array(_sl_ids, dtype=np.int64),
                    _rescue_ctx, "细长黑痕条档"))
                if _sl_ids:
                    _sl_final = _sl_cand & np.isin(_l_sl, np.array(_sl_ids))
                    result[_sl_final] = (255, 255, 255)
                    gray_ch[_sl_final] = 255
                    _log(f"  [贴边漏光净化] 细长黑痕条清除 {int(_sl_final.sum())} 像素（{len(_sl_ids)}条）")
        _dark_dil3 = cv2.dilate((gray_ch < 180).astype(np.uint8) * 255,
                                kernel_cache.get_ellipse(self._scale_r(3) * 2 + 1))
        _b_e2, _g_e2, _r_e2 = cv2.split(result.astype(np.int16))
        _base_e = tail_zone_e & (gray_ch >= tail_low_e) & (gray_ch < tail_high_e)                   & (sat_ch < tail_sat_e) & (figure_mask_e == 0)                   & ~((seal_mask_e > 0) & (sat_ch >= 20)) & ~_text_exempt_e
        if ocr_mask_e is not None:
            _base_e &= (ocr_mask_e == 0)
        _dpi2 = (self._current_dpi / 300.0) ** 2
        _frag_min = max(3, int(getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_MIN_AREA', 3) * _dpi2))
        _frag_max_in = int(getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_FRAGMENT_MAX_IN', 400) * _dpi2)
        _frag_max_out = int(getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_FRAGMENT_MAX_OUT', 2000) * _dpi2)

        def _clean_frag_range(cand_mask, lo, hi, tag):
            if not cand_mask.any():
                return 0
            _n, _l, _st, _ = cv2.connectedComponentsWithStats(
                cand_mask.astype(np.uint8) * 255, connectivity=8)
            # xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-净化误删正常内容修复
            # 渍尾碎屑档（集合a/b）候选内容救援：044红章淡笔画残块由本档误删
            # （seal_mask按饱和度识别挡不住低饱和淡红笔画），判据F红域色相在此救回
            _ids = self._lightleak_content_rescue(
                _st,
                np.where((_st[1:, cv2.CC_STAT_AREA] >= lo)
                         & (_st[1:, cv2.CC_STAT_AREA] <= hi))[0] + 1,
                _rescue_ctx, tag)
            _ok = np.isin(_l, _ids)
            _final = cand_mask & _ok
            _cnt = int(np.sum(_final))
            if _cnt > 0:
                result[_final] = (255, 255, 255)
                _log(f"  [贴边漏光净化] {tag} 清除 {_cnt} 像素")
            return _cnt

        # 集合a：YOLO框内、距深色内容20px外的孤立小碎屑
        # 蓝偏门槛（B-R>6）：框内贴线碎屑与图纸灰填充几何相同（都贴深色线3~20px），
        # 唯一可靠区分是颜色——渍带蓝调，灰填充是中性灰；净空3px护住线缘过渡带
        _cand_a = _base_e & (hard_protect > 0) & (_dark_dil3 == 0) \
                  & ((_b_e2 - _r_e2) > 6) & (_b_e2 >= _g_e2)
        _clean_frag_range(_cand_a, _frag_min, _frag_max_in, "框内小碎屑")
        # 集合b：YOLO框外页边距碎屑（距深色3px外）。蓝偏下限B-R>4：图纸灰填充是
        # 中性灰（B-R≈0）从这里挡住（BUG-0026红线），漏光雾带蓝偏5~10正常通过
        _b_b2, _g_b2, _r_b2 = cv2.split(result.astype(np.int16))
        _cand_b = _base_e & (hard_protect == 0) & (_dark_dil3 == 0)                   & (((_b_b2 - _r_b2) > 4) & (_b_b2 >= _g_b2))
        _clean_frag_range(_cand_b, _frag_min, _frag_max_out, "页边距碎屑")
        return result

    # xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-净化误删正常内容修复
    # 内容救援上下文构建（每页一次，贴边漏光净化四档清除共用）：条带OCR检测框
    # （判据A）、HSV色相/饱和度通道（判据F）、长线共线基准掩码及其膨胀带（判据E）、
    # DPI缩放后的全部判据阈值。四个清除档各自调用 _lightleak_content_rescue 时共享
    # 同一份上下文，避免每档重复跑OCR与形态学
    def _build_rescue_context(self, result: np.ndarray, gray_ch: np.ndarray,
                              band_v: int, band_h: int) -> dict:
        h, w = gray_ch.shape[:2]
        _dpi = self._current_dpi if getattr(self, '_current_dpi', None) else 300
        _len_s = _dpi / 300.0  # 长度阈值DPI缩放系数（300dpi基准）
        ctx = {
            'h': h, 'w': w, 'dpi_len': _len_s,
            # 判据B 条形码条纹群参数
            'bar_min_bars': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_BAR_MIN_BARS', 5)),
            'bar_w_min': max(1, int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_BAR_W_MIN', 2) * _len_s)),
            'bar_w_max': max(2, int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_BAR_W_MAX', 8) * _len_s)),
            'bar_min_h': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_BAR_MIN_H', 40) * _len_s),
            'bar_tol': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_BAR_TOL', 0.40)),
            'bar_text_ratio': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_BAR_TEXT_RATIO', 1.5)),
            # 判据C 成排成列等距群体参数
            'row_min_count': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_ROW_MIN_COUNT', 3)),
            'row_tol': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_ROW_TOL', 0.40)),
            'hole_ar_min': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_HOLE_AR_MIN', 0.7)),
            'hole_ar_max': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_HOLE_AR_MAX', 1.4)),
            'hole_edge': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_HOLE_EDGE', 30) * _len_s),
            'dot_max_dim': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_DOT_MAX_DIM', 14) * _len_s),
            # 判据D 页码位置先验参数
            'pn_x_lo': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_PAGENUM_X_LO', 0.35)),
            'pn_x_hi': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_PAGENUM_X_HI', 0.65)),
            'pn_y_lo': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_PAGENUM_Y_LO', 0.88)),
            'pn_y_hi': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_PAGENUM_Y_HI', 0.985)),
            'pn_h_min': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_PAGENUM_H_MIN', 20) * _len_s),
            'pn_h_max': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_PAGENUM_H_MAX', 60) * _len_s),
            'pn_max_blocks': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_PAGENUM_MAX_BLOCKS', 3)),
            # 判据E 行线共线延伸参数
            'line_min_len': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_LINE_MIN_LEN', 150) * _len_s),
            'line_tol': max(1, int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_LINE_TOL', 3) * _len_s)),
            'line_gap': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_LINE_GAP', 30) * _len_s),
            'line_edge_min': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_LINE_EDGE_MIN', 30) * _len_s),
            # 判据F 红域色相参数
            'red_h_low': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_RED_H_LOW', 10)),
            'red_h_high': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_RED_H_HIGH', 170)),
            'red_s_min': int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_RED_S_MIN', 25)),
            'red_ratio': float(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_RED_RATIO', 0.30)),
        }
        # 判据A：三张条带图OCR文字检测（引擎异常降级为空框，B~F判据继续工作）
        ctx['ocr_boxes'] = self._ocr_band_veto(result, band_v, band_h)
        # 判据F：HSV色相/饱和度通道（白色背景像素色相值恰为0，红域判定必须叠加
        # 饱和度下限才不会把白背景误算进红域）
        _hsv_ll = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
        ctx['hue_ch'] = _hsv_ll[:, :, 0]
        ctx['sat_ch'] = _hsv_ll[:, :, 1]
        # 判据E：长线共线基准掩码——灰度<180的≥line_min_len连续横/竖暗线（开运算
        # 保留），及其膨胀带（沿线的间隙方向±line_gap、垂直方向±line_tol）；表格线
        # 本体在框线保护内不作清除候选，但作为共线基准参与判定
        _dark_ll = (gray_ch < 180).astype(np.uint8)
        _k_llh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, ctx['line_min_len']), 1))
        _k_llv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, ctx['line_min_len'])))
        ctx['long_h'] = cv2.morphologyEx(_dark_ll, cv2.MORPH_OPEN, _k_llh)
        ctx['long_v'] = cv2.morphologyEx(_dark_ll, cv2.MORPH_OPEN, _k_llv)
        _k_lld = cv2.getStructuringElement(
            cv2.MORPH_RECT, (ctx['line_gap'] * 2 + 1, ctx['line_tol'] * 2 + 1))
        ctx['long_h_dil'] = cv2.dilate(ctx['long_h'], _k_lld)
        ctx['long_v_dil'] = cv2.dilate(ctx['long_v'], _k_lld)
        return ctx

    # xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-净化误删正常内容修复
    # 判据A条带OCR文字检测：四边10%带裁成三张条带图（上带+下带垂直拼接、左中带、
    # 右中带）各跑一次现成RapidOCR检测（只检测不识别，条带原尺寸进模型——全图缩放
    # 检测对8×28px小字符召回不足，008实测标题字符检不出），返回原图坐标系的检测框
    # 列表[(x1,y1,x2,y2)]。检测器对条形码也报框，条形码救援顺带受益；全白条带跳过
    # 省一次前向；引擎/推理异常降级为空列表，不阻断净化流程
    def _ocr_band_veto(self, result: np.ndarray, band_v: int, band_h: int) -> list:
        boxes = []
        h, w = result.shape[:2]
        # 小图保护：条带厚度不超过图高/宽的一半
        band_v = max(1, min(band_v, h // 2))
        band_h = max(1, min(band_h, w // 2))
        try:
            engine = _get_cached_ocr_engine(
                int(getattr(cfg, 'EDGE_LIGHTLEAK_RESCUE_OCR_DET_LIMIT', 4000)))
        except Exception as e:
            _log(f"  [内容救援] OCR引擎获取异常（判据A降级为无框）: {e}")
            return boxes

        def _det_boxes(strip_img):
            """单条带OCR文字检测，返回条带坐标系检测框列表；异常降级为空"""
            if strip_img is None or strip_img.size == 0:
                return []
            if int(np.min(cv2.cvtColor(strip_img, cv2.COLOR_BGR2GRAY))) >= 250:
                return []  # 全白条带无内容，跳过前向
            try:
                _ret = engine(strip_img, use_det=True, use_cls=False, use_rec=False)
            except Exception as e:
                _log(f"  [内容救援] 条带OCR检测异常（该条带降级为无框）: {e}")
                return []
            if _ret is None or _ret.boxes is None:
                return []
            _out = []
            for _box in _ret.boxes:
                _pts = np.array(_box, dtype=np.float32)
                _out.append((float(_pts[:, 0].min()), float(_pts[:, 1].min()),
                             float(_pts[:, 0].max()), float(_pts[:, 1].max())))
            return _out

        # 上带+下带垂直拼接（中间白隔行防检测框跨带连线），下带框平移回页底
        _gap_rows = 8
        _tb_img = np.vstack([
            result[:band_v],
            np.full((_gap_rows, w, 3), 255, dtype=np.uint8),
            result[h - band_v:]])
        _bot_y_off = (h - band_v) - (band_v + _gap_rows)
        for _x1, _y1, _x2, _y2 in _det_boxes(_tb_img):
            if _y1 > band_v + _gap_rows // 2:
                boxes.append((int(_x1), int(_y1 + _bot_y_off),
                              int(_x2), int(_y2 + _bot_y_off)))
            else:
                boxes.append((int(_x1), int(_y1), int(_x2), int(_y2)))
        # 左中带、右中带（原尺寸，y平移回原位）
        for _x1, _y1, _x2, _y2 in _det_boxes(result[band_v:h - band_v, :band_h]):
            boxes.append((int(_x1), int(_y1 + band_v), int(_x2), int(_y2 + band_v)))
        for _x1, _y1, _x2, _y2 in _det_boxes(result[band_v:h - band_v, w - band_h:]):
            boxes.append((int(_x1 + w - band_h), int(_y1 + band_v),
                          int(_x2 + w - band_h), int(_y2 + band_v)))
        if boxes:
            _log(f"  [内容救援] 条带OCR检测到 {len(boxes)} 个文字形状框")
        return boxes

    # xuechong 2026-10-12 研发BUG-0075-图档扫描-3.3.04-净化误删正常内容修复
    # 贴边漏光净化内容救援判据A~F：输入本档清除候选的连通域统计与面积合格标签
    # 集合，六条判据任一命中的候选块从清除名单排除（返回剩余标签数组）。
    # 红线：只扩保护、不扩清除——本方法只做排除，绝不新增任何清除。
    # 判据分工：B~F为确定性几何/色相判据管住已知形态；A为文字形状识别兜底网，
    # 管住B~F没想到的新形态（A对孤立小字符召回不足，不能单独担纲，必须并联）
    def _lightleak_content_rescue(self, stats: np.ndarray, ok_ids: np.ndarray,
                                  ctx: dict, tag: str) -> np.ndarray:
        if ctx is None or len(ok_ids) == 0:
            return ok_ids
        h, w = ctx['h'], ctx['w']
        # 候选块几何收集（只遍历面积合格、即将被清除的候选）
        blocks = []
        for _i in np.asarray(ok_ids).tolist():
            _x, _y = int(stats[_i, cv2.CC_STAT_LEFT]), int(stats[_i, cv2.CC_STAT_TOP])
            _bw, _bh = int(stats[_i, cv2.CC_STAT_WIDTH]), int(stats[_i, cv2.CC_STAT_HEIGHT])
            blocks.append({'id': int(_i), 'x': _x, 'y': _y, 'bw': _bw, 'bh': _bh,
                           'cx': _x + _bw / 2.0, 'cy': _y + _bh / 2.0})
        rescued = {}  # 候选标签 -> 命中判据名（同块多判据命中记首条）

        def _rescue(_b, _why):
            if _b['id'] not in rescued:
                rescued[_b['id']] = _why

        # 判据A：候选外接框与OCR检测框相交即排除（检测框自带padding，相交判定
        # 天然从宽——符合只扩保护红线：宁可漏清贴字碎屑，不可误删文字）
        for _b in blocks:
            for (_bx1, _by1, _bx2, _by2) in ctx['ocr_boxes']:
                if _b['x'] < _bx2 and _b['x'] + _b['bw'] > _bx1 \
                        and _b['y'] < _by2 and _b['y'] + _b['bh'] > _by1:
                    _rescue(_b, 'A')
                    break

        # 判据F：块内红域像素（红色环色相且饱和度达标）占比≥阈值——红章淡笔画
        # （seal_mask按饱和度识别挡不住的低饱和淡红笔画）
        for _b in blocks:
            if _b['id'] in rescued:
                continue
            _roi_hue = ctx['hue_ch'][_b['y']:_b['y'] + _b['bh'], _b['x']:_b['x'] + _b['bw']]
            _roi_sat = ctx['sat_ch'][_b['y']:_b['y'] + _b['bh'], _b['x']:_b['x'] + _b['bw']]
            if _roi_hue.size == 0:
                continue
            _red_px = ((_roi_hue < ctx['red_h_low']) | (_roi_hue > ctx['red_h_high'])) \
                      & (_roi_sat >= ctx['red_s_min'])
            if float(np.count_nonzero(_red_px)) / _roi_hue.size >= ctx['red_ratio']:
                _rescue(_b, 'F')

        # 判据D：页码位置先验——页底水平中央的1~3个孤立字符块（坐标基准为传入
        # 净化方法的图，页面方向矫正之后，横版样本转正后按实际页底判定）
        _pn_x1, _pn_x2 = w * ctx['pn_x_lo'], w * ctx['pn_x_hi']
        _pn_y1, _pn_y2 = h * ctx['pn_y_lo'], h * ctx['pn_y_hi']
        _pn_blocks = [_b for _b in blocks
                      if _pn_x1 <= _b['cx'] <= _pn_x2 and _pn_y1 <= _b['cy'] <= _pn_y2]
        if 0 < len(_pn_blocks) <= ctx['pn_max_blocks']:
            for _b in _pn_blocks:
                if ctx['pn_h_min'] <= _b['bh'] <= ctx['pn_h_max']:
                    _rescue(_b, 'D')

        # 判据E：行线共线延伸——候选外接框与长线膨胀带相交即认定为同一条线的
        # 延伸段；补强：候选距每条纸边须大于line_edge_min才救——贴边黑痕是细长
        # 黑痕条档的本职清理对象，永不救（防纸边黑痕与表格边框共线误救014/015）
        for _b in blocks:
            if _b['id'] in rescued:
                continue
            if not (_b['x'] > ctx['line_edge_min'] and _b['y'] > ctx['line_edge_min']
                    and (_b['x'] + _b['bw']) < w - ctx['line_edge_min']
                    and (_b['y'] + _b['bh']) < h - ctx['line_edge_min']):
                continue
            _roi_hd = ctx['long_h_dil'][_b['y']:_b['y'] + _b['bh'], _b['x']:_b['x'] + _b['bw']]
            if _roi_hd.any():
                _rescue(_b, 'E横')
                continue
            _roi_vd = ctx['long_v_dil'][_b['y']:_b['y'] + _b['bh'], _b['x']:_b['x'] + _b['bw']]
            if _roi_vd.any():
                _rescue(_b, 'E竖')

        # 判据B：条形码条纹群——≥5根等宽等高紧密排列的平行细竖条判定为条形码，
        # 群体及正下方人读字符区一并救援（010封底条形码14根条纹+MOH0025700-6）；
        # 不要求等距——条形码宽窄条编码的相邻间距天然不等，等距判定会漏真条码
        _bar_cands = [_b for _b in blocks
                      if ctx['bar_w_min'] <= _b['bw'] <= ctx['bar_w_max']
                      and _b['bh'] >= ctx['bar_min_h']]
        if len(_bar_cands) >= ctx['bar_min_bars']:
            _bar_sorted = sorted(_bar_cands, key=lambda _b: (_b['cy'], _b['cx']))
            _bar_groups, _bg = [], []
            for _b in _bar_sorted:
                if _bg and abs(_b['cy'] - _bg[-1]['cy']) > max(10 * ctx['dpi_len'],
                                                               ctx['bar_min_h'] * 0.3):
                    _bar_groups.append(_bg)
                    _bg = []
                _bg.append(_b)
            if _bg:
                _bar_groups.append(_bg)
            for _grp in _bar_groups:
                if len(_grp) < ctx['bar_min_bars']:
                    continue
                _grp = sorted(_grp, key=lambda _b: _b['cx'])
                _ws = [_b['bw'] for _b in _grp]
                _hs = [_b['bh'] for _b in _grp]
                _w_med = sorted(_ws)[len(_ws) // 2]
                _h_med = sorted(_hs)[len(_hs) // 2]
                if _w_med <= 0 or _h_med <= 0:
                    continue
                # 等宽+等高（极差/中位≤容差，宽度容差带2px绝对下限——010实测条纹
                # 宽3~5px，像素级取整抖动就有2px，纯比例容差会误拒真条纹）
                if (max(_ws) - min(_ws)) > max(_w_med * ctx['bar_tol'], 2):
                    continue
                if (max(_hs) - min(_hs)) > _h_med * ctx['bar_tol']:
                    continue
                # 有序排列：相邻中心距≥1px（不重叠）且不超过双基准上限——窄条之间
                # 可能夹着面积超上限、不进候选的宽黑条，跨宽条的相邻中心距实测达
                # 92px，需以条高为基准容纳（010封底条形码实测）
                _cxs = [_b['cx'] for _b in _grp]
                _dists = [(_cxs[_k + 1] - _cxs[_k]) for _k in range(len(_cxs) - 1)]
                if min(_dists) <= 0:
                    continue
                if max(_dists) > max(_w_med * 6, _h_med * 2.5):
                    continue
                for _b in _grp:
                    _rescue(_b, 'B')
                # 群体正下方人读字符区（x范围=群体bbox左右各外扩一个中位条高，
                # 高=中位条高×比例）内的块（010字符区实测有块略悬出条纹群bbox）
                _pad = int(_h_med)
                _gx1 = min(_b['x'] for _b in _grp) - _pad
                _gx2 = max(_b['x'] + _b['bw'] for _b in _grp) + _pad
                _gy2 = max(_b['y'] + _b['bh'] for _b in _grp)
                _ty2 = min(h, _gy2 + int(_h_med * ctx['bar_text_ratio']))
                for _b in blocks:
                    if _gx1 <= _b['cx'] <= _gx2 and _b['y'] >= _gy2 and _b['cy'] <= _ty2:
                        _rescue(_b, 'B字符')

        # 判据C：成排/成列等距群体——印刷内容有等距规律（08-05批标题字符行、序号
        # 列1~9、页眉虚线段），污渍没有；近圆形且贴纸边的走纸孔链同样等距成排但
        # 该清，按形态+位置豁免本判据（07-03批蓝单/05-18批链轮孔）
        def _hole_exempt(_b):
            if _b['bh'] <= 0:
                return False
            _ar = _b['bw'] / float(_b['bh'])
            if not (ctx['hole_ar_min'] <= _ar <= ctx['hole_ar_max']):
                return False
            return (_b['x'] <= ctx['hole_edge'] or _b['y'] <= ctx['hole_edge']
                    or (_b['x'] + _b['bw']) >= w - ctx['hole_edge']
                    or (_b['y'] + _b['bh']) >= h - ctx['hole_edge'])

        # xuechong 2026-10-12 研发BUG-0075 微圆块豁免（全量验证发现的漏清回归修正）：
        # 灰尘点/走纸孔残点的特征形态是近圆形微小连通域（487张全量实测6~12px），
        # 它们在页边凑成等距列是伪影的偶然规律而非印刷内容——视觉复核确认05-19批
        # 左缘微点列、05-27批右缘孔残点列全部为该清杂质。真字符被碎成微圆块的场景
        # 由判据A（OCR框）/B（条码字符区）/E（行线共线）兜底，不走判据C
        def _dot_exempt(_b):
            if _b['bh'] <= 0:
                return False
            _ar = _b['bw'] / float(_b['bh'])
            if not (ctx['hole_ar_min'] <= _ar <= ctx['hole_ar_max']):
                return False
            return max(_b['bw'], _b['bh']) <= ctx['dot_max_dim']

        _avg_bh = sum(_b['bh'] for _b in blocks) / float(len(blocks))
        _cl_gap = max(6 * ctx['dpi_len'], _avg_bh * 0.5)  # 同行/列聚类容差

        def _rescue_aligned(_key):
            """_key='cy'按行聚类判成排等距；_key='cx'按列聚类判成列等距。
            簇内先按相邻间距的中位做离群剔除并切分成等距段（链式聚类会被cx/cy
            恰好接近的无关块桥接连成大簇，直接判簇内等距会被桥接块拉爆极差——
            008序号列3个数字等距精度1.1%仍被拒的实测根因），每段独立判等距，
            只救等距段上的块"""
            _by_key = sorted(blocks, key=lambda _b: _b[_key])
            _clusters, _cl = [], []
            for _b in _by_key:
                if _cl and abs(_b[_key] - _cl[-1][_key]) > _cl_gap:
                    _clusters.append(_cl)
                    _cl = []
                _cl.append(_b)
            if _cl:
                _clusters.append(_cl)
            _pos_key = 'cx' if _key == 'cy' else 'cy'
            for _cl in _clusters:
                if len(_cl) < ctx['row_min_count']:
                    continue
                _cl = sorted(_cl, key=lambda _b: _b[_pos_key])
                _poss = [_b[_pos_key] for _b in _cl]
                _gaps = [(_poss[_k + 1] - _poss[_k]) for _k in range(len(_poss) - 1)]
                _gaps_all = [_g for _g in _gaps if _g > 0]
                if len(_gaps_all) < ctx['row_min_count'] - 1:
                    continue
                _med_all = sorted(_gaps_all)[len(_gaps_all) // 2]
                if _med_all <= 0:
                    continue
                # 离群间距（<0.6倍或>1.4倍中位）处断段，各段独立判等距
                _segs, _seg = [], [_cl[0]]
                for _k, _g in enumerate(_gaps):
                    if _g <= 0 or _g < _med_all * 0.6 or _g > _med_all * 1.4:
                        _segs.append(_seg)
                        _seg = []
                    _seg.append(_cl[_k + 1])
                _segs.append(_seg)
                for _seg in _segs:
                    if len(_seg) < ctx['row_min_count']:
                        continue
                    _sp = [_b[_pos_key] for _b in _seg]
                    _sg = [(_sp[_k + 1] - _sp[_k]) for _k in range(len(_sp) - 1)]
                    _sg = [_g for _g in _sg if _g > 0]
                    if len(_sg) < ctx['row_min_count'] - 1:
                        continue
                    _med = sorted(_sg)[len(_sg) // 2]
                    if _med <= 0:
                        continue
                    if (max(_sg) - min(_sg)) / _med <= ctx['row_tol']:
                        for _b in _seg:
                            if not _hole_exempt(_b) and not _dot_exempt(_b):
                                _rescue(_b, 'C排' if _key == 'cy' else 'C列')

        _rescue_aligned('cy')
        _rescue_aligned('cx')

        # xuechong 2026-10-12 研发BUG-0075 同列同尺寸串（判据C补充分支，08-05批032实测驱动）：
        # 序号列只有部分行被清时，被清块的行距残缺（032实测间距521/202/265/524），
        # 等距判定失配漏救。字符列的本质规律是"x对齐+同尺寸+独立行"而非行距等距：
        # ≥3块、x中心链式聚类（容差max(8,0.6×相邻块宽)）、高度≥15px且极差≤45%、
        # cy间距≥60px（排除同一字符的上下断块）即判定为字符列，簇范围内（x在簇
        # x区间、cy在簇首尾±20px内）的候选小断块一并救援。灰尘点被高度≥15px与
        # 微圆豁免双重挡住，走纸孔链由走纸孔豁免挡住
        _col_sorted = sorted(
            [_b for _b in blocks if _b['bh'] >= 15 and not _hole_exempt(_b) and not _dot_exempt(_b)],
            key=lambda _b: _b['cx'])
        if len(_col_sorted) >= ctx['row_min_count']:
            _col_groups, _cg = [], []
            for _b in _col_sorted:
                if _cg:
                    _prev = _cg[-1]
                    if abs(_b['cx'] - _prev['cx']) > max(8, 0.6 * max(_prev['bw'], _b['bw'])):
                        _col_groups.append(_cg)
                        _cg = []
                _cg.append(_b)
            if _cg:
                _col_groups.append(_cg)
            for _cg in _col_groups:
                if len(_cg) < ctx['row_min_count']:
                    continue
                _hs = [_b['bh'] for _b in _cg]
                if (max(_hs) - min(_hs)) > 0.45 * max(_hs):
                    continue
                # 同字符断块合并成字符位（cy间距≤25px的块属同一行字符，
                # 032实测数字6断块垂直间距仅4.5px，不合并会误拒整簇），
                # 字符位数≥3且相邻字符位间距≥60px（独立行）才判字符列
                _ys = sorted(_b['cy'] for _b in _cg)
                _rows, _cur = [], [_ys[0]]
                for _v in _ys[1:]:
                    if _v - _cur[-1] <= 25 * ctx['dpi_len']:
                        _cur.append(_v)
                    else:
                        _rows.append(_cur)
                        _cur = [_v]
                _rows.append(_cur)
                if len(_rows) < ctx['row_min_count']:
                    continue
                _row_cy = [sum(_r) / len(_r) for _r in _rows]
                if min(_row_cy[_k + 1] - _row_cy[_k]
                       for _k in range(len(_row_cy) - 1)) < 60 * ctx['dpi_len']:
                    continue
                _gx1 = min(_b['x'] for _b in _cg)
                _gx2 = max(_b['x'] + _b['bw'] for _b in _cg)
                for _b in blocks:
                    if _gx1 <= _b['cx'] <= _gx2 and _ys[0] - 20 <= _b['cy'] <= _ys[-1] + 20:
                        _rescue(_b, 'C列串')

        if rescued:
            _why_cnt = {}
            for _why in rescued.values():
                _why_cnt[_why] = _why_cnt.get(_why, 0) + 1
            _why_txt = "、".join(f"{_k}×{_v}" for _k, _v in sorted(_why_cnt.items()))
            _log(f"  [内容救援] {tag} 排除 {len(rescued)} 块（{_why_txt}）")
        return np.array([_b['id'] for _b in blocks if _b['id'] not in rescued],
                        dtype=np.int64)

    # xuechong 2026-10-10 研发BUG-0073-图档扫描-3.3.02-图片转PDF模块漏光净化质量优化
    # 页内漏光补扫：盖板漏光在页面中部形成的蓝灰云斑（封面页最明显）。页内没有
    # "贴边"这道位置保险，在贴边带判据之上追加两道收紧：①必须带蓝偏（蓝色通道比
    # 红色通道高出阈值，图纸实心灰色填充/灰矩形是中性灰不带蓝偏，从这里排除）；
    # ②连通域面积达标（只清大块云斑，零碎小点不碰，防误伤细碎内容）
    def _clean_interior_lightleak(self, result: np.ndarray, hard_protect: np.ndarray,
                                  color_mask: np.ndarray, seal_mask: np.ndarray,
                                  figure_mask: np.ndarray, binary: np.ndarray,
                                  orig_image: np.ndarray = None,
                                  ocr_mask: np.ndarray = None) -> np.ndarray:
        """页内蓝灰漏光云斑净化 + 灰雾页纸面灰雾漂白（参数全部走 config）"""
        h, w = result.shape[:2]
        gray_ch = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
        sat_ch = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)[:, :, 1]

        gray_low = getattr(cfg, 'EDGE_LIGHTLEAK_GRAY_LOW', 190)
        gray_high = getattr(cfg, 'EDGE_LIGHTLEAK_GRAY_HIGH', 245)
        sat_max = getattr(cfg, 'EDGE_LIGHTLEAK_SAT_MAX', 20)
        sat_domain_ratio = getattr(cfg, 'EDGE_LIGHTLEAK_SAT_DOMAIN_RATIO', 0.6)
        texture_max = getattr(cfg, 'EDGE_LIGHTLEAK_TEXTURE_MAX', 0.03)
        clearance = self._scale_r(getattr(cfg, 'EDGE_LIGHTLEAK_CLEARANCE', 15))
        bluish_diff = getattr(cfg, 'EDGE_LIGHTLEAK_BLUISH_DIFF', 8)
        # 面积阈值按DPI平方缩放（面积是二维量），300dpi基准3000px
        _dpi_scale = (self._current_dpi if getattr(self, '_current_dpi', None) else 300) / 300.0
        min_area = int(getattr(cfg, 'EDGE_LIGHTLEAK_INTERIOR_MIN_AREA', 3000) * _dpi_scale * _dpi_scale)

        # 页内候选：贴边带之外 & 灰保护带同区间 & 低饱和 & 带蓝偏 & 硬保护外
        margin_ratio = getattr(cfg, 'EDGE_LIGHTLEAK_MARGIN_RATIO', 0.05)
        band_v = max(1, int(h * margin_ratio))
        band_h = max(1, int(w * margin_ratio))
        edge_band = np.zeros((h, w), dtype=bool)
        edge_band[:band_v, :] = True
        edge_band[h - band_v:, :] = True
        edge_band[:, :band_h] = True
        edge_band[:, w - band_h:] = True

        _text_exempt = self._compute_edge_text_exempt(binary, int(h * 0.03), int(w * 0.03))
        total_cleaned = 0

        b_ch, g_ch, r_ch = cv2.split(result.astype(np.int16))
        bluish = (b_ch - r_ch > bluish_diff) & (b_ch >= g_ch)
        candidate = (~edge_band) & (gray_ch >= gray_low) & (gray_ch < gray_high) \
                    & (sat_ch < sat_max) & bluish & (hard_protect == 0)
        if ocr_mask is not None:
            candidate &= (ocr_mask == 0)

        k_clear = kernel_cache.get_ellipse(clearance * 2 + 1)
        clear_zone = cv2.dilate((gray_ch < 180).astype(np.uint8) * 255, k_clear) == 0

        # 域级判定：主体低饱和 + 邻域深色密度低于上限（剖面线/网纹的线条落在邻域圈内，从这里挡住）
        if candidate.any():
            num_li, labels_li, stats_li, _ = cv2.connectedComponentsWithStats(
                candidate.astype(np.uint8) * 255, connectivity=8)
            keep = self._lightleak_domain_filter(
                labels_li, stats_li, num_li, gray_ch, sat_ch, sat_max,
                sat_domain_ratio, texture_max, min_area)
            keep &= clear_zone
            keep &= ~_text_exempt
            keep &= ~((color_mask > 0) & (sat_ch >= sat_max))
            final = candidate & keep
            cnt = int(np.sum(final))
            if cnt > 0:
                result[final] = (255, 255, 255)
                total_cleaned += cnt
                _log(f"  [页内漏光净化] 清除蓝灰云斑 {cnt} 像素 ({100*cnt/(h*w):.2f}%)")

        # xuechong 2026-10-11 研发BUG-0073 渍尾补扫（用户验收发现的页顶残余碎渣）：
        # 漏光渍的边缘碎渣会碎成几百~两千px的小块，主体亮度245~254在漂白带（236~252）
        # 上沿之外、又达不到页内蓝灰净化的面积门槛（3000px），两档之间漏网。
        # 补扫带蓝偏的小碎片（≥ EDGE_LIGHTLEAK_TAIL_MIN_AREA），位置不设限（页顶页内都清），
        # 但四道像素级保护一个不少：净空圈、页码豁免、彩色种子、印章/figure/硬保护；
        # 带蓝偏+低饱和双保险保证真内容（文字黑、框线黑、图纸中性灰、印章彩）进不来
        tail_min = int(getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_MIN_AREA', 150)
                       * _dpi_scale * _dpi_scale)
        tail_high = getattr(cfg, 'EDGE_LIGHTLEAK_TAIL_GRAY_HIGH', 254)
        tail_cand = (gray_ch >= gray_low) & (gray_ch < tail_high) \
                    & (sat_ch < sat_max) & bluish \
                    & (hard_protect == 0) & (figure_mask == 0) & (seal_mask == 0)
        tail_cand &= clear_zone
        tail_cand &= ~_text_exempt
        tail_cand &= ~((color_mask > 0) & (sat_ch >= sat_max))
        if tail_cand.any():
            num_t, labels_t, stats_t, _ = cv2.connectedComponentsWithStats(
                tail_cand.astype(np.uint8) * 255, connectivity=8)
            ok_t = np.isin(labels_t, np.where(stats_t[1:, cv2.CC_STAT_AREA] >= tail_min)[0] + 1)
            final_t = tail_cand & ok_t
            cnt_t = int(np.sum(final_t))
            if cnt_t > 0:
                result[final_t] = (255, 255, 255)
                total_cleaned += cnt_t
                _log(f"  [页内漏光净化] 清除渍尾碎渣 {cnt_t} 像素 ({100*cnt_t/(h*w):.2f}%)")

        # 灰雾页纸面灰雾漂白（默认关闭，取舍见 config.EDGE_LIGHTLEAK_WASH_ENABLE 注释）：
        # 封面页中部的灰雾被 YOLO 文字大框和灰色保护同时罩住，尊重保护框的清理绕不开；
        # 图纸浅灰填充与封面灰雾像素特征无差别，无法算法区分，由配置开关显式决策。
        # 生效时六道保护齐上：figure框（照片浅色区）、印章、彩色种子、页码豁免、
        # 深色净空、漂白碎片最小面积兜底
        if getattr(cfg, 'EDGE_LIGHTLEAK_WASH_ENABLE', False) and orig_image is not None:
            wash_low = getattr(cfg, 'EDGE_LIGHTLEAK_WASH_GRAY_LOW', 236)
            wash_high = getattr(cfg, 'EDGE_LIGHTLEAK_WASH_GRAY_HIGH', 252)
            wash_min_area = int(getattr(cfg, 'EDGE_LIGHTLEAK_WASH_MIN_AREA', 2500)
                                * _dpi_scale * _dpi_scale)
            wash_clearance = self._scale_r(getattr(cfg, 'EDGE_LIGHTLEAK_WASH_CLEARANCE', 12))
            wash_cand = (gray_ch >= wash_low) & (gray_ch < wash_high) & (sat_ch < sat_max)
            wash_cand &= (seal_mask == 0)
            wash_cand &= (figure_mask == 0)
            wash_cand &= ~((color_mask > 0) & (sat_ch >= sat_max))
            if wash_cand.any():
                num_w, labels_w, stats_w, _ = cv2.connectedComponentsWithStats(
                    wash_cand.astype(np.uint8) * 255, connectivity=8)
                # 域级判定：面积达标 + 邻域内容密度低于上限（内容类=灰度<235全部非白：
                # 图纸剖面线（深）与灰填充206-218（中灰）都算内容；阈值0.20放行文字页
                # 雾域（文字薄晕致密度0.065~0.09），实心填充邻域密度≈1.0仍被拦）
                keep_w = self._lightleak_domain_filter(
                    labels_w, stats_w, num_w, gray_ch, sat_ch, sat_max,
                    0.0, getattr(cfg, 'EDGE_LIGHTLEAK_WASH_TEXTURE_MAX', 0.20),
                    wash_min_area, content_below=wash_low - 1)
                k_w = kernel_cache.get_ellipse(wash_clearance * 2 + 1)
                keep_w &= (cv2.dilate((gray_ch < 180).astype(np.uint8) * 255, k_w) == 0)
                keep_w &= ~_text_exempt
                final_w = wash_cand & keep_w
                # 漂白碎片门槛：过滤后漂白区过小的碎片不漂（图纸结构内碎屑兜底）
                _min_frag = int(getattr(cfg, 'EDGE_LIGHTLEAK_WASH_MIN_FRAGMENT', 1500)
                                * _dpi_scale * _dpi_scale)
                _fn, _fl, _fs, _ = cv2.connectedComponentsWithStats(
                    final_w.astype(np.uint8) * 255, connectivity=8)
                _frag_ok = np.isin(_fl, np.where(_fs[1:, cv2.CC_STAT_AREA] >= _min_frag)[0] + 1)
                final_w = final_w & _frag_ok
                cnt_w = int(np.sum(final_w))
                if cnt_w > 0:
                    result[final_w] = (255, 255, 255)
                    total_cleaned += cnt_w
                    _log(f"  [页内漏光净化] 纸面灰雾漂白 {cnt_w} 像素 ({100*cnt_w/(h*w):.2f}%)")

        # xuechong 2026-10-11 研发BUG-0073 蓝渍碎屑档（用户复验发现的标题周围小斑点）：
        # 漏光渍深入到标题文字周围时，碎片 100% 落在 YOLO 标题框内+距字 15px 净空圈内，
        # 被两个"内容保护"挡住；其灰度 207~245 又低于漂白带下限 236 的部分够不着。
        # 本档专收带蓝偏的小碎屑：B-R>5（文字抗锯齿晕是中性灰 B-R≈0，天然排除）、
        # 灰度190~252、S<25、碎片≥80px，限定页顶/页底 15% 带（漏光渍的活动范围）。
        # 有意不尊重 YOLO 文字框（框内空白处的蓝渍不是内容，文字本体是黑色够不到
        # 灰度下限）；figure框（照片）、印章、彩色种子（S≥25）、净空3px（护字缘）、
        # 页码豁免五道保护保留
        if getattr(cfg, 'EDGE_LIGHTLEAK_CLEAN_ENABLE_SPECK', True):
            _sp_band = getattr(cfg, 'EDGE_LIGHTLEAK_SPECK_BAND', 0.15)
            _sp_zone = np.zeros((h, w), dtype=bool)
            _sp_v = int(h * _sp_band)
            _sp_zone[:_sp_v, :] = True
            _sp_zone[h - _sp_v:, :] = True
            _b_sp, _g_sp, _r_sp = cv2.split(result.astype(np.int16))
            _sp_cand = (gray_ch >= gray_low) & (gray_ch < 252) \
                       & (sat_ch < 22) & ((_b_sp - _r_sp) > 6) & (_b_sp >= _g_sp) \
                       & _sp_zone \
                       & (figure_mask == 0) & (seal_mask == 0)
            _sp_cand &= ~((color_mask > 0) & (sat_ch >= 22))
            # 尊重OCR文字行（a001实测浅色细笔画文字被蓝屑档误清字）
            if ocr_mask is not None:
                _sp_cand &= (ocr_mask == 0)
            # 净空收到1px：渍渗进标题字缝、紧贴字缘，3px净空会挡掉75%；
            # 字缘抗锯齿晕是中性灰（B-R≈0~3）够不到B-R>6，1px圈足以保住字形本体
            _k_sp = kernel_cache.get_ellipse(1 * 2 + 1)
            _sp_cand &= (cv2.dilate((gray_ch < 180).astype(np.uint8) * 255, _k_sp) == 0)
            _sp_cand &= ~_text_exempt
            if _sp_cand.any():
                _n_sp, _l_sp, _st_sp, _ = cv2.connectedComponentsWithStats(
                    _sp_cand.astype(np.uint8) * 255, connectivity=8)
                _min_sp = int(getattr(cfg, 'EDGE_LIGHTLEAK_SPECK_MIN_AREA', 80)
                              * _dpi_scale * _dpi_scale)
                _sp_ok = np.isin(_l_sp, np.where(_st_sp[1:, cv2.CC_STAT_AREA] >= _min_sp)[0] + 1)
                _sp_final = _sp_cand & _sp_ok
                cnt_sp = int(np.sum(_sp_final))
                if cnt_sp > 0:
                    result[_sp_final] = (255, 255, 255)
                    total_cleaned += cnt_sp
                    _log(f"  [页内漏光净化] 蓝渍碎屑清除 {cnt_sp} 像素 ({100*cnt_sp/(h*w):.2f}%)")

            # 局部背景雾档：渗进标题字缝的渍在JPEG色度抽样下失去蓝调（B-R≈0~6），
            # 蓝屑档够不到；且字形密集处雾都在字周3px内，距离净空也挡不住。
            # 用闭运算估计局部背景亮度（背景比字形亮，闭运算填掉字形后取局部亮水平），
            # "接近局部背景的浅灰像素"就是雾——雾的灰度≈背景亮度，字形远低于背景。
            # 只在页顶/页底15%带生效（漏光活动范围），碎片≥60px
            _k_bg = kernel_cache.get_ellipse(self._scale_r(21) * 2 + 1)
            _bg_est = cv2.morphologyEx(gray_ch, cv2.MORPH_CLOSE, _k_bg)
            _bg_delta = getattr(cfg, 'EDGE_LIGHTLEAK_SPECK_BG_DELTA', 14)
            _bg_cand = (gray_ch >= _bg_est - _bg_delta) & (gray_ch >= 190) & (gray_ch < 252) \
                       & (sat_ch < 30) & _sp_zone \
                       & (figure_mask == 0) & (seal_mask == 0)
            _bg_cand &= ~((color_mask > 0) & (sat_ch >= 25))
            _bg_cand &= ~_text_exempt
            # 字缝灰雾档尊重OCR文字行（a001实测浅色细笔画文字被误当雾清字，回归修复）
            if ocr_mask is not None:
                _bg_cand &= (ocr_mask == 0)
            if _bg_cand.any():
                _n_bg, _l_bg, _st_bg, _ = cv2.connectedComponentsWithStats(
                    _bg_cand.astype(np.uint8) * 255, connectivity=8)
                _min_bg = int(getattr(cfg, 'EDGE_LIGHTLEAK_SPECK_BG_MIN_AREA', 60)
                              * _dpi_scale * _dpi_scale)
                _bg_ok = np.isin(_l_bg, np.where(_st_bg[1:, cv2.CC_STAT_AREA] >= _min_bg)[0] + 1)
                _bg_final = _bg_cand & _bg_ok
                cnt_bg = int(np.sum(_bg_final))
                if cnt_bg > 0:
                    result[_bg_final] = (255, 255, 255)
                    total_cleaned += cnt_bg
                    _log(f"  [页内漏光净化] 字缝灰雾清除 {cnt_bg} 像素 ({100*cnt_bg/(h*w):.2f}%)")

        return result

    def _lightleak_domain_filter(self, labels: np.ndarray, stats: np.ndarray, num: int,
                                 gray_ch: np.ndarray, sat_ch: np.ndarray, sat_max: int,
                                 sat_domain_ratio: float, texture_max: float,
                                 min_area: int, content_below: int = 200,
                                 content_above: int = 0) -> np.ndarray:
        """漏光净化域级判定：主体低饱和 + 邻域内容密度低于上限 + 面积达标。

        邻域内容密度用 boxFilter 计算域像素周边17px窗口内指定灰度带像素的占比均值
        ——域本身由浅色候选构成，直接数域内像素恒为0（等于没判），必须看邻域。
        content_below/content_above 圈定"内容"灰度带：贴边带用<200（拦剖面线/文字线条，
        候选≥190自身像素几乎不计入）；灰雾漂白用中灰带[180,236)——只认图纸灰填充
        206-218这类中灰邻居，文字笔画（<180）不算内容（雾夹在文字行之间本就该清），
        候选≥236自身像素天然不计入
        """
        flat_lab = labels.ravel()
        areas = np.maximum(stats[1:, cv2.CC_STAT_AREA], 1)
        low_sat_count = np.bincount(flat_lab, weights=(sat_ch.ravel() < sat_max).astype(np.float64), minlength=num)
        content = ((gray_ch >= content_above) & (gray_ch < content_below)).astype(np.float32)
        dark_local = cv2.boxFilter(content, -1, (17, 17), borderType=cv2.BORDER_REFLECT)
        dark_density = np.bincount(flat_lab, weights=dark_local.ravel(), minlength=num)
        domain_ok = ((low_sat_count[1:] / areas) >= sat_domain_ratio) & \
                    ((dark_density[1:] / areas) < texture_max) & \
                    (stats[1:, cv2.CC_STAT_AREA] >= min_area)
        return np.isin(labels, np.where(domain_ok)[0] + 1)

    def _gray_protection_vectorized(self, cache: "ImageCache", h: int, w: int,
                                    kernel_cache: "KernelCache") -> np.ndarray:
        """灰色保护向量化实现（np.isin + stats 数组过滤 + 算法改进）。

        性能优化原理：
        - 旧版：每个连通域一次 _labels_g == _gi 全图布尔比较 → O(N×pixels)
        - 新版：np.isin(_labels_g, valid_ids) 一次全图操作 → O(pixels + N)
        - 生产 2435×3527 大图连通域数千个，旧版 ~58s/张 → 新版目标 ≤1s/张

        实现说明（xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景 更新）：
        L1.5 碎片聚合由 ENABLE_GRAY_CLUSTER_L15 控制，v3.1.05 起默认关闭（False）——
        正常白底文档的文字抗锯齿碎片经闭运算聚合后会生成覆盖全页 23%~69% 的虚假
        保护掩码，阻断高白保守白化，输出残留灰色背景（研发BUG-0026 根因）；
        图纸实心灰色内容由 Layer1/Layer2 承担保护。开关置 True 时 L1.5 保持
        v3.1.04 的外接矩形填充行为（诊断/对比/回退用）。
        L1 的填充率、深灰纹理过滤参数与 L1.5 的填充率、比例上限参数当前均为 0
        （不生效，config.py 对应注释保留历史调优记录）；L2.5 内容通道默认关闭
        （ENABLE_GRAY_CONTENT_CHANNEL）；L3 膨胀由 GRAY_EDGE_DILATE_RADIUS/
        ITERATIONS 控制（当前 5/2）。掩码验收由 test_req012_quantitative.py 的
        "保护面积不劣化"断言覆盖。
        """
        _gray_ch = cache.gray
        _, _sat_ch, _ = cache.get_hsv_channels()
        _light_gray = (_gray_ch >= 190) & (_gray_ch < 245) & (_sat_ch < 35)

        # zhaoqiaotong 2026-08-31 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
        # REQ-010 整页灰雾门控：浅灰覆盖率超阈值的页判为扫描灰雾页（灰雾整页发生，图纸剖面线/
        # 表格印刷底纹为局部灰内容，Phase 1 实测两侧覆盖率间隔 2~3 倍而域级特征全部重叠不可分），
        # 灰色保护整体跳过，灰雾由既有清除链路（智能污渍清除/散点清理）自动接管；
        # 未触发路径在本判定之后，与既有行为完全一致，开关关闭即完全回退。
        if getattr(cfg, 'ENABLE_GRAY_MOTTLE_EXEMPT', False):
            _mottle_cov = float(np.count_nonzero(_light_gray)) / float(h * w)
            if _mottle_cov > getattr(cfg, 'GRAY_MOTTLE_PAGE_RATIO', 0.15):
                _log(f"  [灰色保护-向量化] 灰雾页门控：浅灰覆盖 {_mottle_cov * 100:.1f}% > "
                     f"{getattr(cfg, 'GRAY_MOTTLE_PAGE_RATIO', 0.15) * 100:.0f}%，跳过灰色保护")
                return np.zeros((h, w), dtype=np.uint8)

        _gray_uint8 = _light_gray.astype(np.uint8) * 255
        _num_g, _labels_g, _stats_g, _ = cv2.connectedComponentsWithStats(_gray_uint8, connectivity=8)
        _min_area = getattr(cfg, 'GRAY_CONTENT_MIN_AREA', 200)

        # 向量化提取 stats（跳过背景索引 0）
        if _num_g <= 1:
            _log(f"  [灰色保护-向量化] 无灰色连通域")
            return np.zeros((h, w), dtype=np.uint8)
        _g_areas = _stats_g[1:, cv2.CC_STAT_AREA]
        _g_lefts = _stats_g[1:, cv2.CC_STAT_LEFT]
        _g_tops = _stats_g[1:, cv2.CC_STAT_TOP]
        _g_widths = _stats_g[1:, cv2.CC_STAT_WIDTH]
        _g_heights = _stats_g[1:, cv2.CC_STAT_HEIGHT]

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-003 深灰纹理判定
        # 纯浅灰区域（扫描底色/阴影）无深灰纹理 → 不保护；剖面线/线纹区域有深灰纹理 → 保护
        # 用 bincount 一次统计每连通域深灰像素数，避免逐域全图比较
        _texture_high = getattr(cfg, 'GRAY_CONTENT_DARK_TEXTURE_HIGH', 190)
        _texture_min = getattr(cfg, 'GRAY_CONTENT_TEXTURE_MIN_RATIO', 0.005)
        _dark_texture = (_gray_ch < _texture_high)
        _dark_count_g = np.bincount(
            _labels_g.ravel(),
            weights=_dark_texture.ravel().astype(np.float64),
            minlength=_num_g,
        )
        _texture_ratio_g = _dark_count_g[1:] / np.maximum(_g_areas, 1)

        # --- Layer 1: 高置信度核心区域（大面积连通域） ---
        # 过滤条件仅在配置阈值 > 0 时生效，阈值为 0 表示不过滤（对齐 3.0.03 行为）
        _max_area_ratio = getattr(cfg, 'GRAY_CONTENT_MAX_AREA_RATIO', 0.0)
        _max_area_l1 = int(h * w * _max_area_ratio) if _max_area_ratio > 0 else 0
        _l1_fill_ratio = getattr(cfg, 'GRAY_CONTENT_L1_FILL_RATIO', 0.0)
        _l1_mask = (_g_areas >= _min_area)
        if _max_area_l1 > 0:
            _l1_mask = _l1_mask & (_g_areas <= _max_area_l1)
        if _l1_fill_ratio > 0:
            _bbox_areas_l1 = _g_widths.astype(np.int64) * _g_heights.astype(np.int64)
            _fill_l1 = np.zeros(_num_g - 1, dtype=np.float64)
            np.divide(_g_areas, _bbox_areas_l1, out=_fill_l1, where=_bbox_areas_l1 > 0)
            _l1_mask = _l1_mask & (_fill_l1 >= _l1_fill_ratio)
        if _texture_min > 0:
            _l1_mask = _l1_mask & (_texture_ratio_g >= _texture_min)
        _valid_l1 = np.where(_l1_mask)[0] + 1
        _layer1 = np.zeros((h, w), dtype=np.uint8)
        if len(_valid_l1) > 0:
            _layer1[np.isin(_labels_g, _valid_l1)] = 255

        # --- Layer 1.5: 小碎片空间聚合 ---
        # 闭运算连接附近的小碎片→大区域→外接矩形填充（对齐 3.0.03 的平滑保护方式）
        _layer15 = np.zeros((h, w), dtype=np.uint8)
        # xuechong 2026-08-18 研发BUG-0026-图档扫描-3.1.05-图片转PDF净化之后出现灰色背景 L1.5 默认关闭
        # 正常文档的抗锯齿碎片聚合会生成覆盖全页的虚假保护掩码、阻断保守白化（本BUG根因）；
        # 图纸实心灰色内容由 Layer1/Layer2 承担。True=恢复 v3.1.04 行为（诊断/回退用）
        if getattr(cfg, 'ENABLE_GRAY_CLUSTER_L15', False):
            _cluster_min_area = getattr(cfg, 'GRAY_CLUSTER_MIN_AREA', 5000)
            _cluster_close_ksize = getattr(cfg, 'GRAY_CLUSTER_CLOSE_KSIZE', 15)
            _cluster_fill_ratio = getattr(cfg, 'GRAY_CLUSTER_FILL_RATIO', 0.0)
            _valid_l15 = np.where(_g_areas < _min_area)[0] + 1
            if len(_valid_l15) > 0:
                _small_fragments = np.zeros((h, w), dtype=np.uint8)
                _small_fragments[np.isin(_labels_g, _valid_l15)] = 255
                if np.sum(_small_fragments > 0) > 0:
                    _k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (_cluster_close_ksize, _cluster_close_ksize))
                    _clustered = cv2.morphologyEx(_small_fragments, cv2.MORPH_CLOSE, _k_close, iterations=2)
                    _num_c, _labels_c, _stats_c, _ = cv2.connectedComponentsWithStats(_clustered, connectivity=8)
                    if _num_c > 1:
                        _c_areas = _stats_c[1:, cv2.CC_STAT_AREA]
                        _c_widths = _stats_c[1:, cv2.CC_STAT_WIDTH].astype(np.int64)
                        _c_heights = _stats_c[1:, cv2.CC_STAT_HEIGHT].astype(np.int64)
                        _c_bbox_areas = _c_widths * _c_heights
                        _c_valid_bbox = _c_bbox_areas > 0
                        _c_valid_mask = (_c_areas >= _cluster_min_area) & _c_valid_bbox
                        if _cluster_fill_ratio > 0:
                            _c_fill = np.zeros(_num_c - 1, dtype=np.float64)
                            np.divide(_c_areas, _c_bbox_areas, out=_c_fill, where=_c_valid_bbox)
                            _c_valid_mask = _c_valid_mask & (_c_fill >= _cluster_fill_ratio)
                        if _texture_min > 0:
                            _dark_count_c = np.bincount(
                                _labels_c.ravel(),
                                weights=_dark_texture.ravel().astype(np.float64),
                                minlength=_num_c,
                            )
                            _c_texture = _dark_count_c[1:] / np.maximum(_c_areas, 1)
                            _c_valid_mask = _c_valid_mask & (_c_texture >= _texture_min)
                        _valid_c = np.where(_c_valid_mask)[0] + 1
                        if len(_valid_c) > 0:
                            # xuechong 2026-08-07 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 修复L1.5回归
                            # 恢复 3.1.02 行为：外接矩形填充，与 legacy 实现一致
                            # bbox 填充确保碎片间空白区域也得到保护（剖面线交叉填充区域）
                            for _ci in _valid_c:
                                _cx = int(_stats_c[_ci, cv2.CC_STAT_LEFT])
                                _cy = int(_stats_c[_ci, cv2.CC_STAT_TOP])
                                _cbw = int(_stats_c[_ci, cv2.CC_STAT_WIDTH])
                                _cbh = int(_stats_c[_ci, cv2.CC_STAT_HEIGHT])
                                _cy2 = min(_cy + _cbh, h)
                                _cx2 = min(_cx + _cbw, w)
                                _layer15[_cy:_cy2, _cx:_cx2] = 255
        else:
            _log(f"  [灰色保护-向量化] L1.5 碎片聚合已禁用（ENABLE_GRAY_CLUSTER_L15=False），跳过")

        # Layer1.5 面积比例检查：阈值为 0 时跳过（不限制）
        _l15_ratio = np.sum(_layer15 > 0) / (h * w)
        _l15_max_ratio = getattr(cfg, 'GRAY_CLUSTER_MAX_RATIO', 0.0)
        if _l15_max_ratio > 0 and _l15_ratio > _l15_max_ratio:
            _log(f"  [灰色保护-向量化] L1.5 聚合 {_l15_ratio*100:.1f}% > {_l15_max_ratio*100:.0f}% 上限，跳过碎片聚合")
            _layer15[:] = 0

        # --- Layer 2: 几何规则性扩展（填充率向量化过滤，bbox 填充循环保留） ---
        _layer2 = np.zeros((h, w), dtype=np.uint8)
        _fill_threshold = getattr(cfg, 'GRAY_FILL_RATIO_THRESHOLD', 0.65)
        _rect_min_area = getattr(cfg, 'GRAY_RECT_MIN_AREA', 500)
        _bbox_areas = _g_widths.astype(np.int64) * _g_heights.astype(np.int64)
        _valid_bbox = _bbox_areas > 0
        _fill_ratios = np.zeros(_num_g - 1, dtype=np.float64)
        np.divide(_g_areas, _bbox_areas, out=_fill_ratios, where=_valid_bbox)
        _valid_l2_mask = (_g_areas >= _rect_min_area) & (_fill_ratios >= _fill_threshold) & _valid_bbox
        _valid_l2_mask = _valid_l2_mask & (_texture_ratio_g >= _texture_min)
        _valid_l2 = np.where(_valid_l2_mask)[0] + 1
        for _gi in _valid_l2:
            _x = int(_stats_g[_gi, cv2.CC_STAT_LEFT])
            _y = int(_stats_g[_gi, cv2.CC_STAT_TOP])
            _bw = int(_stats_g[_gi, cv2.CC_STAT_WIDTH])
            _bh = int(_stats_g[_gi, cv2.CC_STAT_HEIGHT])
            _y2 = min(_y + _bh, h)
            _x2 = min(_x + _bw, w)
            _layer2[_y:_y2, _x:_x2] = 255

        _layer25 = np.zeros((h, w), dtype=np.uint8)
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-003 Layer2.5: 灰色内容保护通道（文字/手写/细线）
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-003 默认关闭（ENABLE_GRAY_CONTENT_CHANNEL=False）
        # 实测 005 样张：通道保护像素中 83.6% 被 3.0.03 刷白（背景/噪点），仅 16.4% 真内容
        # （且已被文字/框线/OCR 保护覆盖）→ 开启时保留此段，真实图纸样张验证后再启用
        if getattr(cfg, 'ENABLE_GRAY_CONTENT_CHANNEL', False):
            _deep_gray_high = getattr(cfg, 'GRAY_CONTENT_DEEP_HIGH', 220)
            _deep_gray = (_gray_ch >= 190) & (_gray_ch < _deep_gray_high) & (_sat_ch < 35)
            _deep_gray_uint8 = _deep_gray.astype(np.uint8) * 255
            _num_dg, _labels_dg, _stats_dg, _ = cv2.connectedComponentsWithStats(_deep_gray_uint8, connectivity=8)
            if _num_dg > 1:
                _dg_areas = _stats_dg[1:, cv2.CC_STAT_AREA]
                _dg_widths = _stats_dg[1:, cv2.CC_STAT_WIDTH].astype(np.float64)
                _dg_heights = _stats_dg[1:, cv2.CC_STAT_HEIGHT].astype(np.float64)
                _dg_bbox_areas = (_dg_widths * _dg_heights).astype(np.int64)
                _dg_valid_bbox = _dg_bbox_areas > 0
                # 填充率向量化
                _dg_fill = np.zeros(_num_dg - 1, dtype=np.float64)
                np.divide(_dg_areas, _dg_bbox_areas, out=_dg_fill, where=_dg_valid_bbox)
                # 宽高比向量化
                _dg_wh_ratio = np.ones(_num_dg - 1, dtype=np.float64)
                np.divide(_dg_widths, _dg_heights, out=_dg_wh_ratio, where=_dg_heights > 0)
                # 文字/手写形态：小面积 + 高填充率
                _text_min = getattr(cfg, 'GRAY_CONTENT_TEXT_MIN_AREA', 5)
                _text_max = getattr(cfg, 'GRAY_CONTENT_TEXT_MAX_AREA', 2000)
                _text_fill = getattr(cfg, 'GRAY_CONTENT_TEXT_FILL_RATIO', 0.3)
                _is_text = (_dg_areas >= _text_min) & (_dg_areas <= _text_max) & (_dg_fill >= _text_fill)
                # 细线形态：面积足够 + 极宽或极高
                _line_ar = getattr(cfg, 'GRAY_CONTENT_LINE_ASPECT_RATIO', 3.0)
                _line_min = getattr(cfg, 'GRAY_CONTENT_LINE_MIN_AREA', 20)
                _is_line = (_dg_areas >= _line_min) & ((_dg_wh_ratio >= _line_ar) | (_dg_wh_ratio <= 1.0 / _line_ar))
                _valid_l25_mask = (_is_text | _is_line) & _dg_valid_bbox
                _valid_l25 = np.where(_valid_l25_mask)[0] + 1
                if len(_valid_l25) > 0:
                    _layer25[np.isin(_labels_dg, _valid_l25)] = 255

        # --- Layer 3: 边缘缓冲区（与旧版完全一致） ---
        _core_mask = cv2.bitwise_or(_layer1, _layer15)
        _core_mask = cv2.bitwise_or(_core_mask, _layer2)
        _core_mask = cv2.bitwise_or(_core_mask, _layer25)

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-003 Layer3 膨胀收窄
        # 旧版：核半径 5 + 迭代 2（边缘扩展过大）
        # 新版：核半径 3 + 迭代 1（参数化到 config.py，减少边缘扩展面积）
        gray_content_protect = np.zeros((h, w), dtype=np.uint8)
        if np.sum(_core_mask > 0) > 0:
            _edge_radius = getattr(cfg, 'GRAY_EDGE_DILATE_RADIUS', 3)
            _edge_iter = getattr(cfg, 'GRAY_EDGE_DILATE_ITERATIONS', 1)
            _k_edge = kernel_cache.get_ellipse(self._scale_r(_edge_radius) * 2 + 1)
            gray_content_protect = cv2.dilate(_core_mask, _k_edge, iterations=_edge_iter)

        _l1_px = np.sum(_layer1 > 0)
        _l15_px = np.sum((_layer15 > 0) & (_layer1 == 0))
        _l2_px = np.sum((_layer2 > 0) & (_layer1 == 0) & (_layer15 == 0))
        _l25_px = np.sum((_layer25 > 0) & (_layer1 == 0) & (_layer15 == 0) & (_layer2 == 0))
        _l3_px = np.sum(gray_content_protect > 0) - np.sum(_core_mask > 0)
        _log(f"  [灰色保护-向量化] L1核心:{_l1_px} L1.5聚合:{_l15_px} L2几何:{_l2_px} L2.5内容:{_l25_px} L3边缘:{_l3_px} 总计:{np.sum(gray_content_protect > 0)} 像素")
        return gray_content_protect

    def _pre_detect_low_conf_abandon(self, image: np.ndarray) -> list:
        """矫正前预检测：记录低置信度的 abandon 区域"""
        results = self._predict(image)
        low_conf_regions = []

        for box in results[0].boxes:
            label = self.names[int(box.cls[0])]
            conf = float(box.conf[0])

            if label in cfg.ABANDON_LABELS and conf < cfg.ABANDON_PROTECT_CONF:
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                low_conf_regions.append((x1, y1, x2, y2, conf))

        return low_conf_regions

    def _transform_regions_after_deskew(self, regions: list, orig_shape: tuple,
                                         new_shape: tuple, angle: float) -> list:
        """将矫正前的区域坐标变换到矫正后的坐标系"""
        if not regions or angle == 0.0:
            return regions

        orig_h, orig_w = orig_shape
        new_h, new_w = new_shape

        center = (orig_w / 2, orig_h / 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        M[0, 2] += (new_w - orig_w) / 2
        M[1, 2] += (new_h - orig_h) / 2

        transformed = []
        for x1, y1, x2, y2, conf in regions:
            corners = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32)
            ones = np.ones((4, 1), dtype=np.float32)
            corners_h = np.hstack([corners, ones])
            new_corners = corners_h @ M.T

            new_x1 = max(0, int(np.min(new_corners[:, 0])))
            new_y1 = max(0, int(np.min(new_corners[:, 1])))
            new_x2 = min(new_w, int(np.max(new_corners[:, 0])))
            new_y2 = min(new_h, int(np.max(new_corners[:, 1])))

            transformed.append((new_x1, new_y1, new_x2, new_y2, conf))

        return transformed

    def _is_overlapping_with_low_conf(self, x1: int, y1: int, x2: int, y2: int,
                                       low_conf_regions: list, iou_threshold: float = 0.3) -> bool:
        """检查当前区域是否与低置信度区域重叠"""
        for lx1, ly1, lx2, ly2, _ in low_conf_regions:
            inter_x1 = max(x1, lx1)
            inter_y1 = max(y1, ly1)
            inter_x2 = min(x2, lx2)
            inter_y2 = min(y2, ly2)

            if inter_x1 < inter_x2 and inter_y1 < inter_y2:
                inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                area1 = (x2 - x1) * (y2 - y1)
                area2 = (lx2 - lx1) * (ly2 - ly1)
                union_area = area1 + area2 - inter_area

                iou = inter_area / union_area if union_area > 0 else 0
                if iou > iou_threshold:
                    return True

        return False
