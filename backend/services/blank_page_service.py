# -*- coding: utf-8 -*-
# zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
"""空白页判定共用服务。

空白页定义（研发需求-0162）：无文字、无签章、无表格等有效内容，完全空白或
只含无效杂质（灰尘、装订孔/钉痕残留等）。判定口径：非白像素掩码 + 8连通域
分析，任一连通域面积达到有效内容阈值（300DPI 基准 60px，对齐 config.TEXT_BLOB_MIN_AREA
最小文字保护阈值）且不属于装订孔豁免，即视为非空白——宁可不删、绝不误删。

装订孔豁免（详见 config 空白页检测段注释）：净化链路的文字连通域保护会把整块
深色圆斑当"文字"保护，钉痕清除被跳过，双面扫描的空白背面透出的装订孔会残留。
对同时满足 近页边+近似圆形+尺寸窗50~150px@300DPI+无彩色 的连通域不计为内容
（彩色圆形签章不豁免，签章必须保留）；只豁免不删除，不改动净化链路。

透印鬼影判据（详见 config.BLANK_GHOST_* 注释）：双面扫描的空白背面透出正面内容
的浅灰鬼影（几何上是文字/表格形状，连通域判据无法识别），按"无彩色非白像素中
深色占比过低"甄别为空白；彩色痕迹足量（红章/黄底票据）时直接判内容绝不判空白。

两个入口：
- is_blank_bgr_image：图片转PDF链路，输入净化后的 BGR 图像（净化后空白页已成
  纯白；带签章页因彩色印章保护签章仍在，会被判定为非空白而保留）。
- is_blank_pdf_page：编辑PDF链路，渲染 PDF 单页判定，自动排除底部页码带内的
  本系统旧页码文字（否则"只有页码的空白页"会被误判为有内容）。

zhaoqiaotong 2026-09-14 研发BUG-0052-图档扫描-3.2.11-修复编辑PDF模块对已有页码PDF
添加页码时，部分旧页码残留 追加旧页码检测入口：
- find_old_pagenum_rects_in_doc：编辑PDF防双重页码链路，跨页一致性校验检测全文档
  旧页码文本（词组候选+序号连续+位置一致+字体一致取最长链），页码带内混有正文
  仍可检出；单页整带保守判定 find_old_pagenum_rects 原样保留供 is_blank_pdf_page
  使用（空白页判定零回归）。宁漏检不误删：判据不满足即按无旧页码处理。

零误删红线：任何检测异常一律返回"非空白"（页面保留），仅记日志。
"""

import re
from typing import List, Optional, Tuple

import cv2
import numpy as np
import fitz  # PyMuPDF

from backend import config as cfg
from backend.services.logging_service import log_info

# zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
# 按分析 DPI 折算的有效内容最小连通域面积（px）；下限2防止折算后过小失去意义
_MIN_CONTENT_AREA = max(2, round(cfg.BLANK_MIN_CONTENT_AREA_300DPI * (cfg.BLANK_ANALYSIS_DPI / 300.0) ** 2))

# 孤立散点内容确认阈值（折算到分析 DPI）：全部连通域均小于此值 → 整页只有孤立
# 灰尘点/透印痕等无效杂质 → 空白（口径来源与实测依据见 config 同名常量注释）
_ISOLATED_CONTENT_AREA = max(_MIN_CONTENT_AREA + 1, round(
    cfg.BLANK_ISOLATED_CONTENT_AREA_300DPI * (cfg.BLANK_ANALYSIS_DPI / 300.0) ** 2))

# 透印判据的有效痕迹下限（折算到分析 DPI）：
# ① 无彩色非白像素总量低于此值时不下"整页鬼影"结论（大概率是彩色内容页的零星
#    伴生，保守保留）；② 彩色像素达到"真实彩色内容下限"（config.
#    BLANK_GHOST_COLORED_FLOOR_300DPI，红章/彩色签名量级）时直接判内容——
#    彩色印章的透印鬼影（约175px@120DPI稀疏）不触发，真章（上万px实心）触发
_GHOST_TRACE_FLOOR = max(10, round(100 * (cfg.BLANK_ANALYSIS_DPI / 300.0) ** 2))
_GHOST_COLORED_FLOOR = max(_GHOST_TRACE_FLOOR, round(
    cfg.BLANK_GHOST_COLORED_FLOOR_300DPI * (cfg.BLANK_ANALYSIS_DPI / 300.0) ** 2))

# 底部页码带高度pt（与 app.py 页码腾位常量 _PAGENUM_RESERVE_PT 对齐：页码+白底衬+
# 检测外扩均落在该带内，超出该带的正文按有效内容计入）
_PAGENUM_BAND_PT = 40.0

# 本系统页码文本格式（add_page_numbers 生成 "- N -"），用于识别存量 PDF 旧页码
_PAGENUM_TEXT_RE = re.compile(r"^-\s*\d+\s*-$")

# zhaoqiaotong 2026-09-14 研发BUG-0052-图档扫描-3.2.11-修复编辑PDF模块对已有页码PDF添加页码时，部分旧页码残留
# 旧页码链判据常量（整带全匹配在页码带内混有正文时整体放弃——pic2.pdf 第1/2页表格表头/
# 厂商页脚与旧页码"- N -"共存即漏检、残留双重页码，故升级为"词组候选+跨页链校验"）：
# ① 三词连排的相邻词间距上限（×最小词高）："- N -"视觉上是一组，间距远小于词高
_CAND_GAP_H_RATIO = 1.5
# ② 同行判据：三词y区间重叠 ≥ 50%最小词高（排除跨行词意外成组）
_CAND_LINE_OVERLAP = 0.5
# ③ 三词高度相近上限（×最小词高）：同页同字号词组高度理论一致，防御性上限
_CAND_HEIGHT_RATIO = 1.5
# ④ 链水平位置容差：词组中心x/页宽 比值极差（相对量，兼容各页尺寸不同；
#    实测本系统页码 pic2.pdf 三页极差0.001，余量充足）
_CHAIN_X_TOL = 0.04
# ⑤ 链垂直位置容差：词组底边距页底 pt 极差（实测系统页码三页极差0.0pt）
_CHAIN_Y_TOL = 8.0
# ⑥ 链字号容差 pt（浮点噪声）
_CHAIN_SIZE_TOL = 0.5
# ⑦ 多页文档采信链的最短页数：单页孤立候选更可能是正文巧合（宁漏检不误删），
#    单页文档放宽为1（带内"- N -"几乎必为页码，与修复前行为一致）
_CHAIN_MIN_PAGES_MULTI = 2
# 单词形态旧页码（"-12-"无空格书写，PyMuPDF 提取为单词）
_PAGENUM_SINGLE_RE = re.compile(r"^-(\d+)-$")
# 字体子集化随机前缀（PDF规范：6个大写字母+'+'，如 ABCDEF+NotoSerifSC-Regular）
_FONT_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
# 链假设数量上限（同页大量候选的病态文档防御性截断，保留最长的前一半）
_CHAIN_HYPOTHESIS_CAP = 500


def _punch_like_content_ids(labels: np.ndarray, stats: np.ndarray,
                            content_ids: np.ndarray, analysis_img: np.ndarray) -> List[int]:
    """从达到内容阈值的连通域中筛出装订孔形态组件（返回 labels id 列表）。

    四重条件（全部满足才豁免，见 config.BLANK_PUNCH_* 注释）：
    近页边 + 近似圆形（填充率/宽高比）+ 尺寸窗 + 无彩色（保护彩色圆形签章）。
    全程数组运算，通道极差均值用 bincount 一次算完（避免逐域取像素的 O(N*M) 开销）。
    """
    try:
        h, w = labels.shape
        k = cfg.BLANK_ANALYSIS_DPI / 300.0  # 分析像素 → 300DPI 等效尺寸换算
        idx = content_ids  # labels id 与 stats 行号一一对应（背景=第0行，content_ids 已排除背景）
        areas = stats[idx, cv2.CC_STAT_AREA]
        bws = stats[idx, cv2.CC_STAT_WIDTH].astype(float)
        bhs = stats[idx, cv2.CC_STAT_HEIGHT].astype(float)
        lefts = stats[idx, cv2.CC_STAT_LEFT]
        tops = stats[idx, cv2.CC_STAT_TOP]
        dims300 = np.maximum(bws, bhs) / k
        # ① 尺寸窗
        ok = (dims300 >= cfg.BLANK_PUNCH_MIN_DIM_300DPI) & (dims300 <= cfg.BLANK_PUNCH_MAX_DIM_300DPI)
        # ② 近似圆形：填充率 + 宽高比（含边缘裁半孔）
        extents = areas / np.maximum(bws * bhs, 1.0)
        aspects = bws / np.maximum(bhs, 1.0)
        ok &= (extents >= cfg.BLANK_PUNCH_MIN_EXTENT)
        ok &= (aspects >= cfg.BLANK_PUNCH_ASPECT_MIN) & (aspects <= cfg.BLANK_PUNCH_ASPECT_MAX)
        # ③ 近页边（组件中心距最近页边 ≤ 页宽/高的 EDGE_RATIO）
        cxs = lefts + bws / 2.0
        cys = tops + bhs / 2.0
        mx, my = w * cfg.BLANK_PUNCH_EDGE_RATIO, h * cfg.BLANK_PUNCH_EDGE_RATIO
        near_edge = (cxs <= mx) | (cxs >= w - mx) | (cys <= my) | (cys >= h - my)
        ok &= near_edge
        if not ok.any():
            return []
        # ④ 无彩色：候选组件内 RGB 通道极差均值 < 阈值（彩色签章不豁免）
        cand = content_ids[ok]
        sat = analysis_img.max(axis=2).astype(np.int16) - analysis_img.min(axis=2).astype(np.int16)
        num = int(labels.max()) + 1
        sums = np.bincount(labels.ravel(), weights=sat.ravel().astype(np.float64), minlength=num)
        cnts = np.bincount(labels.ravel(), minlength=num)
        sat_mean = sums[cand] / np.maximum(cnts[cand], 1)
        colorless = sat_mean < cfg.BLANK_PUNCH_MAX_SATURATION
        return [int(i) for i in cand[colorless]]
    except Exception as e:
        # 豁免判定异常：一个都不豁免（全部按内容处理，保守保留）
        log_info(f"[空白页检测] 装订孔豁免判定异常（不豁免任何组件）: {e}")
        return []


def _is_ghost_page(mask: np.ndarray, analysis_img: np.ndarray, gray: np.ndarray,
                   labels: np.ndarray, punch_ids: list) -> bool:
    """透印鬼影页判定：无彩色非白像素中深色占比过低 → 整页痕迹以浅色鬼影为主 → 空白。

    双面扫描的空白背面会透出正面内容的浅灰鬼影（几何上是文字/表格形状，连通域判据
    无法识别），其特征是"大量浅色痕迹、深色极少"。实测与阈值依据见
    config.BLANK_GHOST_* 注释。双重安全阀：
    ① 彩色痕迹足量（红章/黄票底色）→ 直接判内容（彩色签章必须保留）；
    ② 计算剔除装订孔豁免组件（深色孔不拉高占比）；无彩色痕迹过少不下结论（保守保留）。
    任何异常返回 False（按非空白保留，零误删红线）。
    """
    try:
        sat = analysis_img.max(axis=2).astype(np.int16) - analysis_img.min(axis=2).astype(np.int16)
        colored = (mask > 0) & (sat >= cfg.BLANK_PUNCH_MAX_SATURATION)
        # 安全阀①：彩色痕迹达到真实彩色内容量级（红章/黄底票据）→ 绝不判空白；
        # 彩色印章的透印鬼影（稀疏少量）不触发
        if int(colored.sum()) >= _GHOST_COLORED_FLOOR:
            return False
        colorless = (mask > 0) & (sat < cfg.BLANK_PUNCH_MAX_SATURATION)
        # 安全阀②：剔除装订孔豁免组件像素，深色孔不参与深色占比
        if punch_ids and labels is not None:
            colorless = colorless & ~np.isin(labels, punch_ids)
        cn = int(colorless.sum())
        # 无彩色痕迹太少不足以下"整页鬼影"结论，保守保留
        if cn < _GHOST_TRACE_FLOOR:
            return False
        dark = int((colorless & (gray < cfg.BLANK_GHOST_DARK_GRAY)).sum())
        return dark / cn < cfg.BLANK_GHOST_DARK_RATIO
    except Exception as e:
        log_info(f"[空白页检测] 透印判定异常（按非空白保留）: {e}")
        return False


def _mask_is_blank(mask: np.ndarray, min_area: int, analysis_img: Optional[np.ndarray] = None,
                   gray: Optional[np.ndarray] = None) -> bool:
    """掩码核心判定：存在有效内容连通域则非空白。

    判定顺序：
    1. 非白像素总数为 0 → 空白（完全空白）
    2. 非白像素总数 < min_area → 空白（杂质总量微小，不可能存在达阈值的连通域）
    3. 全部连通域面积 < 孤立散点阈值（500px@300DPI 等效）→ 空白：整页只有孤立
       灰尘点/透印痕/细线碎片等无效杂质，无一达到"可确认内容"规模（口径与实测
       依据见 config.BLANK_ISOLATED_CONTENT_AREA_300DPI 注释）
    4. 任一连通域 ≥ min_area 且不属于装订孔豁免 → 非空白
    5. 透印鬼影判据：无彩色非白像素中深色占比过低（整页浅色鬼影）→ 空白
    6. 其余 → 非空白

    Args:
        analysis_img: 分析图（3通道，与掩码同尺寸），供装订孔豁免/透印判据用；
            None 时跳过相应判据（所有达阈值组件均按内容处理）
        gray: 分析图灰度（与掩码同尺寸），供透印判据的深色判定；None 时跳过透印判据
    """
    total = int(mask.sum())
    if total == 0:
        return True
    if total < min_area:
        return True
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    # stats 第0行为背景，跳过
    areas = stats[1:, cv2.CC_STAT_AREA]
    if areas.max() < _ISOLATED_CONTENT_AREA:
        return True  # 全部为孤立散点（小于可确认内容的规模），整页按无效杂质判空白
    content_ids = np.nonzero(areas >= min_area)[0] + 1
    if content_ids.size == 0:
        return True
    punch_ids = []
    if cfg.BLANK_PUNCH_EXEMPT and analysis_img is not None:
        punch_ids = _punch_like_content_ids(labels, stats, content_ids, analysis_img)
        if content_ids.size == len(punch_ids):
            return True  # 达阈值组件全部为装订孔形态 → 空白
    # zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能
    # 透印鬼影判据：双面扫描空白背面透出的浅灰鬼影（文字/表格形状，连通域判据无法
    # 识别），按"深色占比"甄别，实测依据见 config.BLANK_GHOST_* 注释
    if cfg.BLANK_GHOST_EXEMPT and analysis_img is not None and gray is not None:
        if _is_ghost_page(mask, analysis_img, gray, labels, punch_ids):
            return True
    return False


def is_blank_bgr_image(image_bgr: np.ndarray, dpi: float = 300.0) -> Tuple[bool, str]:
    """判定净化后的 BGR 图像是否为空白页。

    Args:
        image_bgr: 净化后的 BGR 图像（numpy 数组）
        dpi: 原图 DPI（用于将图像归一到分析 DPI；无效时按 300）

    Returns:
        (is_blank, reason)：is_blank=True 时空白（reason 为判定依据，日志用）；
        任何异常返回 (False, 原因)——零误删红线：检测失败按非空白处理。
    """
    try:
        if image_bgr is None or image_bgr.size == 0:
            return False, "图像为空（按非空白保留）"
        eff_dpi = float(dpi) if dpi and float(dpi) > 0 else 300.0
        # 归一缩放到分析 DPI（只缩小不放大）。曾短暂改为含放大以兼容 DPI 标签失真的
        # 图片（pic5/空白2.png 标96实为300密度），经用户决策回退：此类非标准输入不在
        # 生产范围，且低标签图不放大时所有测量值偏大 → 判定偏向保留（宁可不删的保守方向）
        scale = cfg.BLANK_ANALYSIS_DPI / eff_dpi
        if scale < 1.0:
            analysis = cv2.resize(
                image_bgr,
                (max(1, int(round(image_bgr.shape[1] * scale))),
                 max(1, int(round(image_bgr.shape[0] * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            analysis = image_bgr
        gray = cv2.cvtColor(analysis, cv2.COLOR_BGR2GRAY)
        mask = (gray < cfg.BLANK_NON_WHITE_THRESHOLD).astype(np.uint8)
        total = int(mask.sum())
        if _mask_is_blank(mask, _MIN_CONTENT_AREA, analysis, gray):
            return True, f"非白像素{total}px，无有效内容连通域（含装订孔/透印判据）"
        return False, f"存在有效内容连通域（非白像素{total}px）"
    except Exception as e:
        log_info(f"[空白页检测] 图像判定异常，按非空白保留: {e}")
        return False, f"检测异常: {e}"


def find_old_pagenum_rects(page: "fitz.Page") -> Optional[List["fitz.Rect"]]:
    """检测页底带内是否仅有本系统旧页码文本。

    带内全部文字恰好匹配 "- N -" 格式 → 返回页码词矩形列表（供掩码排除与
    redact 移除复用）；带内有其他文字（正文/OCR文字层）或无文字 → 返回 None
    （保守：页码像素计入内容，避免把底部有正文的页误判空白）。
    """
    try:
        band = fitz.Rect(0, page.rect.height - _PAGENUM_BAND_PT, page.rect.width, page.rect.height)
        words = page.get_text("words", clip=band)
        if not words:
            return None
        text = " ".join(w[4] for w in words).strip()
        if not _PAGENUM_TEXT_RE.match(text):
            return None
        return [fitz.Rect(w[0], w[1], w[2], w[3]) for w in words]
    except Exception as e:
        log_info(f"[空白页检测] 旧页码文本检测失败（按无旧页码处理）: {e}")
        return None


# zhaoqiaotong 2026-09-14 研发BUG-0052-图档扫描-3.2.11-修复编辑PDF模块对已有页码PDF添加页码时，部分旧页码残留
def _find_pagenum_candidates(page: "fitz.Page") -> List[Tuple[int, List["fitz.Rect"], str, float]]:
    """提取单页旧页码词组候选（研发BUG-0052 第一层判据）。

    与 find_old_pagenum_rects 的"整带全匹配"不同：不要求页码带内只有页码，而是按词
    匹配页码外形，带内混有正文（页脚地址/表格表头等）仍可检出。两类形态：
    ① 三词连排 '-' + 纯数字 + '-'：水平相邻（间距 < 1.5×词高）、同行（y区间重叠
       ≥ 50%词高）、高度相近；
    ② 单词 "-N-"（无空格书写形态）。
    候选附记字体名与字号（dict 模式建立词矩形→span 字体映射；字体名剥离子集化随机
    前缀 "XXXXXX+"），供跨页链校验比对。绑定"同一套字"而非"特定字体"——pic2.pdf
    实测旧页码为 Droid Sans Fallback（旧版产物），硬编码现行字体会把这些文件挡在门外。

    Returns:
        候选列表 [(页码数字N, 词矩形组, 字体名, 字号), ...]；任何异常返回空列表
        （按无候选处理，行为与修复前一致）。
    """
    try:
        band = fitz.Rect(0, page.rect.height - _PAGENUM_BAND_PT, page.rect.width, page.rect.height)
        words = page.get_text("words", clip=band)
        if not words:
            return []
        words = sorted(words, key=lambda w: w[0])
        # dict 模式 span 字体表：words 与 dict 同源同坐标系，词矩形中心落入哪个 span 即取其字体
        font_spans = []
        for blk in page.get_text("dict", clip=band).get("blocks", []):
            for line in blk.get("lines", []):
                for sp in line.get("spans", []):
                    font_spans.append(
                        (fitz.Rect(sp["bbox"]), str(sp.get("font", "")), float(sp.get("size", 0.0))))

        def _font_at(rect: "fitz.Rect") -> Tuple[str, float]:
            cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
            for sr, fname, fsize in font_spans:
                if sr.x0 <= cx <= sr.x1 and sr.y0 <= cy <= sr.y1:
                    return _FONT_SUBSET_PREFIX_RE.sub("", fname), fsize
            return "", 0.0

        cands: List[Tuple[int, List["fitz.Rect"], str, float]] = []
        n = len(words)
        for i in range(n):
            t1 = words[i][4].strip()
            # 形态②：单词 "-N-"
            m = _PAGENUM_SINGLE_RE.match(t1)
            if m:
                r = fitz.Rect(words[i][0], words[i][1], words[i][2], words[i][3])
                cands.append((int(m.group(1)), [r], *_font_at(r)))
                continue
            # 形态①：三词 '-' 数字 '-'。词按 x 排序后对每个 '-' 向右找配对 '-'，再在
            # 两词之间找数字词——中段插入的正文词不破坏配对（x序相邻不等于下标相邻）
            if t1 != "-":
                continue
            matched = False
            for j in range(i + 1, n):
                if words[j][4].strip() != "-":
                    continue
                for k in range(i + 1, j):
                    w2 = words[k]
                    t2 = w2[4].strip()
                    if not t2.isdecimal():
                        continue
                    w1, w3 = words[i], words[j]
                    h_min = min(w1[3] - w1[1], w2[3] - w2[1], w3[3] - w3[1])
                    h_max = max(w1[3] - w1[1], w2[3] - w2[1], w3[3] - w3[1])
                    if h_min <= 0 or h_max > _CAND_HEIGHT_RATIO * h_min:
                        continue
                    y_overlap = min(w1[3], w2[3], w3[3]) - max(w1[1], w2[1], w3[1])
                    if y_overlap < _CAND_LINE_OVERLAP * h_min:
                        continue
                    if (w2[0] - w1[2]) > _CAND_GAP_H_RATIO * h_min or \
                            (w3[0] - w2[2]) > _CAND_GAP_H_RATIO * h_min:
                        continue
                    group = [fitz.Rect(w[0], w[1], w[2], w[3]) for w in (w1, w2, w3)]
                    cands.append((int(t2), group, *_font_at(group[1])))
                    matched = True
                    break
                if matched:
                    break  # 该 '-' 已配对成功，不再向右找更远的 '-'
        return cands
    except Exception as e:
        log_info(f"[空白页检测] 旧页码词组候选提取失败（按无候选处理）: {e}")
        return []


# zhaoqiaotong 2026-09-14 研发BUG-0052-图档扫描-3.2.11-修复编辑PDF模块对已有页码PDF添加页码时，部分旧页码残留
def find_old_pagenum_rects_in_doc(doc: "fitz.Document") -> List[Optional[List["fitz.Rect"]]]:
    """跨页一致性校验检测全文档旧页码（研发BUG-0052 第二层判据），返回逐页结果列表。

    每项为该页旧页码词矩形列表（检出，供 redact 移除与掩码排除复用）或 None
    （未检出，不移除）。链判据（延续须同时满足）：
    ① 序号连续：候选页的 N = 链尾 N + 页间隔（允许个别页无候选跳过，数字断档不接链）；
    ② 位置一致：词组中心x/页宽 比值、词组底边距页底距离与链内已录页全部相符
       （相对量判据，合法文档各页尺寸可以不同——pic2.pdf 三页尺寸均不同，已验证）；
    ③ 字体一致：候选字体名与字号和链首相同（字号容差 _CHAIN_SIZE_TOL）。
    取最长链为检出结果；多页文档链长 ≥ 2 才采信（单页孤立候选更可能是正文巧合，
    宁漏检不误删），单页文档放宽为 ≥ 1。任何异常按全文档未检出处理（行为与修复前一致，
    下载永不失败红线延续）。
    """
    page_count = len(doc)
    result: List[Optional[List["fitz.Rect"]]] = [None] * page_count
    try:
        per_page = [_find_pagenum_candidates(doc[i]) for i in range(page_count)]
    except Exception as e:
        log_info(f"[空白页检测] 旧页码跨页校验失败（按无旧页码处理）: {e}")
        return result

    def _group_rect(page_idx: int, group: List["fitz.Rect"]) -> Tuple[float, float]:
        """词组合并矩形的（中心x/页宽 比值, 底边距页底pt）——跨页可比的相对量"""
        r = fitz.Rect(group[0])
        for g in group[1:]:
            r |= g
        pw, ph = doc[page_idx].rect.width, doc[page_idx].rect.height
        return ((r.x0 + r.x1) / 2) / pw, ph - r.y1

    def _new_chain(page_idx: int, cand) -> dict:
        num, group, font, size = cand
        ratio, dist = _group_rect(page_idx, group)
        return {
            "pages": [page_idx],
            "groups": {page_idx: group},
            "last_num": num,
            "last_idx": page_idx,
            "ratios": [ratio],
            "dists": [dist],
            "font": _FONT_SUBSET_PREFIX_RE.sub("", font),
            "size": size,
        }

    # 链假设并行推进：每页先用现有链尝试延续（取第一个序号/位置/字体全符的候选），
    # 再让未消耗的候选各开一条新链假设（同页多候选存疑并行，最终取最长链定案）
    chains: List[dict] = []
    for idx in range(page_count):
        cands = per_page[idx]
        width, height = doc[idx].rect.width, doc[idx].rect.height
        next_chains: List[dict] = []
        used = [False] * len(cands)
        for ch in chains:
            expected = ch["last_num"] + (idx - ch["last_idx"])
            hit = None
            for ci, cand in enumerate(cands):
                if cand[0] != expected:
                    continue
                ratio, dist = _group_rect(idx, cand[1])
                if any(abs(ratio - x) > _CHAIN_X_TOL for x in ch["ratios"]):
                    continue
                if any(abs(dist - y) > _CHAIN_Y_TOL for y in ch["dists"]):
                    continue
                if _FONT_SUBSET_PREFIX_RE.sub("", cand[2]) != ch["font"] or \
                        abs(cand[3] - ch["size"]) > _CHAIN_SIZE_TOL:
                    continue
                hit = (ci, cand, ratio, dist)
                break
            if hit is None:
                next_chains.append(ch)  # 该页无合适候选：链休眠，等待后续页跳号延续
                continue
            ci, cand, ratio, dist = hit
            ch = dict(ch)
            ch["pages"] = ch["pages"] + [idx]
            ch["groups"] = dict(ch["groups"])
            ch["groups"][idx] = cand[1]
            ch["last_num"] = cand[0]
            ch["last_idx"] = idx
            ch["ratios"] = ch["ratios"] + [ratio]
            ch["dists"] = ch["dists"] + [dist]
            next_chains.append(ch)
            used[ci] = True
        for ci, cand in enumerate(cands):
            if not used[ci]:
                next_chains.append(_new_chain(idx, cand))
        # 病态防御：候选过多的文档链假设可能膨胀，截断保留最长的前一半
        if len(next_chains) > _CHAIN_HYPOTHESIS_CAP:
            next_chains.sort(key=lambda c: len(c["pages"]), reverse=True)
            next_chains = next_chains[:_CHAIN_HYPOTHESIS_CAP // 2]
        chains = next_chains

    if chains:
        best = max(chains, key=lambda c: len(c["pages"]))
        min_len = 1 if page_count <= 1 else _CHAIN_MIN_PAGES_MULTI
        if len(best["pages"]) >= min_len:
            for pi in best["pages"]:
                result[pi] = best["groups"][pi]
    return result


def is_blank_pdf_page(page: "fitz.Page") -> Tuple[bool, str]:
    """判定 PDF 单页是否为空白页（渲染分析 DPI，排除底部旧页码文字像素）。

    Returns:
        (is_blank, reason)：任何异常返回 (False, 原因)——零误删红线。
    """
    try:
        dpi = cfg.BLANK_ANALYSIS_DPI
        pix = page.get_pixmap(dpi=dpi)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        mask = (arr[:, :, :3].min(axis=2) < cfg.BLANK_NON_WHITE_THRESHOLD).astype(np.uint8)
        # 排除底部带内旧页码文字像素：只有页码的"空白页"才能被正确识别为空白；
        # 带内有其他文字时 find_old_pagenum_rects 返回 None，页码像素计入内容（保守保留）
        num_rects = find_old_pagenum_rects(page)
        if num_rects:
            k = dpi / 72.0  # PDF pt 坐标 → 像素坐标
            for r in num_rects:
                x0 = max(0, int(r.x0 * k))
                y0 = max(0, int(r.y0 * k))
                x1 = min(mask.shape[1], int(np.ceil(r.x1 * k)))
                y1 = min(mask.shape[0], int(np.ceil(r.y1 * k)))
                if x1 > x0 and y1 > y0:
                    mask[y0:y1, x0:x1] = 0
        total = int(mask.sum())
        # 装订孔豁免/透印判据用渲染 RGB（与图像侧 BGR 仅通道序不同，极差判定不受影响）；
        # 灰度必须按 RGB 通道序换算（copy 保证 cv2 可写）
        rgb = np.ascontiguousarray(arr[:, :, :3]).copy()
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        if _mask_is_blank(mask, _MIN_CONTENT_AREA, rgb, gray):
            return True, f"非白像素{total}px（已排除旧页码），无有效内容连通域（含装订孔/透印判据）"
        return False, f"存在有效内容连通域（非白像素{total}px）"
    except Exception as e:
        log_info(f"[空白页检测] PDF页判定异常，按非空白保留: {e}")
        return False, f"检测异常: {e}"
