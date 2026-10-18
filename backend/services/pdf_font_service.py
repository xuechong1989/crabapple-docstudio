# -*- coding: utf-8 -*-
# zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题 PDF字体子集化保存公共工具
"""PDF 字体子集化保存公共函数。

背景：OCR 透明文字层使用 PyMuPDF 内置 CJK 字体 china-s（Droid Sans Fallback），
每页独立生成单页 PDF 再 insert_pdf 合并时，全量字库随页数重复内嵌（实测约
1.6~3.5MB/页），导致图片转PDF/编辑PDF输出体积约放大 3 倍。

方案：所有最终保存点统一先执行 doc.subset_fonts()（整本只保留实际使用的字形，
同时合并相同字体），再以 garbage=4 + deflate=True 保存，旧的全量字库流会被
垃圾回收。实测 3 页 PDF 字库由约 10.4MB 降至约 16KB，逐页渲染与文字层零变化。

零回归红线：子集化任何异常只记日志，PDF 照常按原逻辑保存，绝不阻断生成流程。
"""

from pathlib import Path
from typing import Union

import fitz  # PyMuPDF

from backend.services.logging_service import log_info


def save_pdf_with_font_subset(doc: fitz.Document, output_path: Union[str, Path]) -> None:
    """字体子集化后保存 PDF（garbage=4 回收旧全量字库流）。

    Args:
        doc: PyMuPDF Document 对象（调用方负责 close）
        output_path: 输出 PDF 路径
    """
    try:
        doc.subset_fonts()
    except Exception as e:
        # 零回归红线：子集化失败不影响保存，PDF 照常生成
        log_info(f"[PDF字体子集化] 子集化失败（PDF照常保存，体积可能偏大）: {e}")

    doc.save(str(output_path), garbage=4, deflate=True)
