# -*- coding: utf-8 -*-
# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
"""编辑PDF模块添加页码功能测试。

覆盖以下验收路径（2026-09-14 研发BUG-0052 同步适配 3.2.10「一键处理」流程：
下载端点已移除 add_page_number 等查询参数，配方由 clean-all-pages 端点设置、
长期生效，下载为统一构建结果取货——旧用例仍用查询参数导致失效，一并修正）：
1. 不设置页码配方下载 → 与现网行为一致，产物无页码（零回归）
2. 设置添加页码配方下载 → 每页底部出现 - X - 页码，从 1 连续编号，原内容保留
3. 页码字体缺失兜底 → 下载仍成功，返回不带页码的正常结果（零回归红线）
4. 研发BUG-0052 回归：带旧页码PDF（含页码带内混正文场景）添加页码不残留旧页码；
   不成链的带内正文绝不误删（宁漏检不误删）
"""
import time
from pathlib import Path

import fitz
import pytest


# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
# 生成不含页码的测试 PDF（模拟 3.2.00 之前的存量图片转PDF产物）
def _make_pdf_bytes(pages: int = 3) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)  # A4 竖版
        page.insert_text((72, 96), f"content-{i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
# 上传 PDF 到编辑PDF模块，返回 (task_id, file_id)
def _upload_edit_pdf(app_client, pages: int = 3):
    resp = app_client.post(
        "/api/edit-pdf/upload-multiple",
        files={"files": ("old-no-pagenum.pdf", _make_pdf_bytes(pages), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    return data["task_id"], data["files"][0]["file_id"]


# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
# 提取下载产物每页文本（列表，下标即页号）
def _extract_page_texts(pdf_bytes: bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [page.get_text() for page in doc]
    finally:
        doc.close()


# zhaoqiaotong 2026-09-14 研发BUG-0052-图档扫描-3.2.11-修复编辑PDF模块对已有页码PDF添加页码时，部分旧页码残留
# 适配 3.2.10「一键处理」流程的测试辅助：clean-all-pages（apply_clean=False 仅设置
# 配方并统一构建，不触发AI修图/OCR）→ 轮询进度至完成 → 下载取货。recipe 关键字
# 透传配方项（add_page_number/remove_blank_pages/shrink）。
def _process_and_download(app_client, task_id: str, file_id: str,
                          timeout_s: float = 30.0, **recipe) -> bytes:
    resp = app_client.post(
        "/api/edit-pdf/clean-all-pages",
        json={"task_id": task_id, "file_id": file_id, "apply_clean": False, **recipe},
    )
    assert resp.status_code == 200, resp.text

    deadline = time.time() + timeout_s
    prog = {}
    while time.time() < deadline:
        prog = app_client.get(f"/api/edit-pdf/clean-all-progress/{task_id}/{file_id}").json()
        if prog.get("status") in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert prog.get("status") == "completed", f"一键处理未完成: {prog}"

    resp = app_client.get(f"/api/edit-pdf/download/{task_id}/{file_id}")
    assert resp.status_code == 200, resp.text
    return resp.content


# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
# 不带参数下载：产物无页码，与现网行为一致（零回归验证）
def test_download_without_flag_has_no_page_numbers(app_client):
    task_id, file_id = _upload_edit_pdf(app_client, pages=3)

    resp = app_client.get(f"/api/edit-pdf/download/{task_id}/{file_id}")
    assert resp.status_code == 200, resp.text

    texts = _extract_page_texts(resp.content)
    assert len(texts) == 3
    for i, text in enumerate(texts):
        assert f"- {i + 1} -" not in text, f"未开启页码的下载不应含页码，第{i + 1}页出现页码文本"
        assert f"content-{i + 1}" in text, "原内容不应变化"


# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
# 添加页码配方下载：每页 - X - 连续编号、原内容保留（页码规格与图片转PDF同一函数保证）
# zhaoqiaotong 2026-09-14 研发BUG-0052 同步适配 3.2.10「一键处理」流程（配方端点设置）
def test_download_with_add_page_number_true(app_client):
    task_id, file_id = _upload_edit_pdf(app_client, pages=3)

    content = _process_and_download(app_client, task_id, file_id, add_page_number=True)

    texts = _extract_page_texts(content)
    assert len(texts) == 3
    for i, text in enumerate(texts):
        assert f"- {i + 1} -" in text, f"第{i + 1}页缺少页码 - {i + 1} -"
        assert f"content-{i + 1}" in text, f"第{i + 1}页原内容被破坏"
        # 页码位于底部：文字基线距下边缘 7mm 约 19.84pt，A4 高 842pt，校验 y0 在底部区域
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        for i, page in enumerate(doc):
            rects = page.search_for(f"- {i + 1} -")
            assert rects, f"第{i + 1}页页码不可检索"
            # 页码基线距下边缘 7mm≈19.84pt（基线≈822.16），含字形上行/下行高度后
            # 文本框顶部约在距底部 20~35pt 范围（y0 > 842-35），实测 y0≈810.6、y1≈825.0
            assert rects[0].y0 > 842 - 35, f"第{i + 1}页页码不在页面底部（y0={rects[0].y0}）"
            # 水平居中（允许 2pt 容差）
            center = (rects[0].x0 + rects[0].x1) / 2
            assert abs(center - 595 / 2) < 2, f"第{i + 1}页页码未水平居中（center={center}）"
    finally:
        doc.close()


# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
# 单页 PDF 边界：仅 - 1 -，无多余页码
# zhaoqiaotong 2026-09-14 研发BUG-0052 同步适配 3.2.10「一键处理」流程（配方端点设置）
def test_download_with_add_page_number_single_page(app_client):
    task_id, file_id = _upload_edit_pdf(app_client, pages=1)

    content = _process_and_download(app_client, task_id, file_id, add_page_number=True)

    texts = _extract_page_texts(content)
    assert len(texts) == 1
    assert "- 1 -" in texts[0]
    assert "- 2 -" not in texts[0]


# zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能
# 字体缺失兜底（零回归红线）：模拟页码宋体字体文件不可用，下载仍成功且返回不带页码的正常结果
# zhaoqiaotong 2026-09-14 研发BUG-0052 同步适配 3.2.10「一键处理」流程：兜底发生在
# 统一构建线程内，monkeypatch 需在触发构建前生效
def test_download_page_number_font_missing_fallback(app_client, monkeypatch):
    from backend import app as app_module

    task_id, file_id = _upload_edit_pdf(app_client, pages=2)

    # 模拟字体缺失：路径指向不存在的文件并清空模块级缓存（monkeypatch 测试后自动还原）
    monkeypatch.setattr(app_module, "_PAGENUM_FONT_PATH", Path("Z:/nonexistent_pagenum_font.ttf"))
    monkeypatch.setattr(app_module, "_PAGENUM_FONT_CACHE", None)

    content = _process_and_download(app_client, task_id, file_id, add_page_number=True)

    texts = _extract_page_texts(content)
    assert len(texts) == 2
    for i, text in enumerate(texts):
        assert f"- {i + 1} -" not in text, "字体缺失兜底时不应输出页码"
        assert f"content-{i + 1}" in text, "兜底时原内容不应变化"


# ======================================================================
# zhaoqiaotong 2026-09-14 研发BUG-0052-图档扫描-3.2.11-修复编辑PDF模块对已有页码PDF添加页码时，部分旧页码残留
# 旧页码跨页链校验回归用例：页码带内混有正文的旧页码必须检出移除（修复"部分旧页码
# 残留"）；不成页码链的带内正文绝不误删（宁漏检不误删红线）。
# ======================================================================

# 生成带旧页码的测试 PDF：每页右侧旧页码 "- N -"（10pt，模拟旧版/他方工具产物，
# 故意偏离新页码的居中位置以便区分残留）；band_body=True 时在页码带内左下角混入
# 正文文字（复现 pic2.pdf 第1/2页"页脚信息与旧页码共存"场景）。
# fonts/x_offsets 供链判据反例构造：逐页不同字体 / 逐页水平位置错开。
def _make_pdf_with_old_pagenums(pages: int = 3, band_body: bool = True,
                                fonts=None, x_offsets=None) -> bytes:
    doc = fitz.open()
    w, h = 595, 842  # A4 竖版，与既有用例一致
    fonts = fonts or ["helv"] * pages
    x_offsets = x_offsets or [0] * pages
    for i in range(pages):
        page = doc.new_page(width=w, height=h)
        page.insert_text((72, 96), f"content-{i + 1}")
        if band_body:
            # 页码带内正文（左下角 8pt，基线距底15pt 落在底部40pt带内）
            page.insert_text((60, h - 15), f"footer-note-{i + 1} Address No.1699",
                             fontname="helv", fontsize=8)
        # 旧页码：右侧距边40pt、基线距底19.84pt（与系统页码同带高度）
        text = f"- {i + 1} -"
        tw = fitz.get_text_length(text, fontname="helv", fontsize=10)
        page.insert_text((w - tw - 40 + x_offsets[i], h - 19.84),
                         text, fontname=fonts[i], fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def _upload_bytes(app_client, data: bytes, name: str = "old-with-pagenum.pdf"):
    resp = app_client.post(
        "/api/edit-pdf/upload-multiple",
        files={"files": (name, data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    return body["task_id"], body["files"][0]["file_id"]


# 核心验收（研发BUG-0052 复现场景）：页码带内混有正文+旧页码 → 旧页码全部检出移除，
# 新页码居中连续一套，带内正文零删改。修复前第1/2页（带内有正文）旧页码残留。
def test_old_pagenum_with_band_body_removed(app_client):
    task_id, file_id = _upload_bytes(
        app_client, _make_pdf_with_old_pagenums(pages=3, band_body=True))

    content = _process_and_download(app_client, task_id, file_id, add_page_number=True)

    w, h = 595, 842
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        assert len(doc) == 3
        for i, page in enumerate(doc):
            rects = page.search_for(f"- {i + 1} -")
            assert len(rects) == 1, f"第{i + 1}页应只保留一套新页码，实测{len(rects)}套（旧页码残留）"
            center = (rects[0].x0 + rects[0].x1) / 2
            assert abs(center - w / 2) < 2, f"第{i + 1}页保留的页码不是居中的新页码"
            assert rects[0].y0 > h - 35, "页码不在页面底部"
            assert f"footer-note-{i + 1}" in page.get_text(), "页码带内正文被误删"
    finally:
        doc.close()


# 防误删红线：带内正文形似页码但数字为小数（"- 12.5 -"，词组判据不成立）→ 不检出、
# 不误删，正文原样保留，新页码照常添加（走增量追加路径）。
def test_band_body_decimal_not_pagenum_untouched(app_client):
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 96), f"content-{i + 1}")
        page.insert_text((72, 842 - 15), f"note - 12.5 - section", fontname="helv", fontsize=8)
    data = doc.tobytes()
    doc.close()

    task_id, file_id = _upload_bytes(app_client, data)
    content = _process_and_download(app_client, task_id, file_id, add_page_number=True)

    result = fitz.open(stream=content, filetype="pdf")
    try:
        assert len(result) == 2
        for i, page in enumerate(result):
            text = page.get_text()
            assert "note - 12.5 - section" in text, "带内正文被误删（判据应拒绝小数页码）"
            assert f"- {i + 1} -" in text, "新页码应照常添加"
    finally:
        result.close()


# 链判据反例①（字体一致）：序号连续、位置一致，但逐页字体不同 → 不成链 → 不检出不误删
# （残留=修复前行为；绝不因孤立候选误删正文，宁漏检不误删）
def test_chain_font_mismatch_not_removed(app_client):
    task_id, file_id = _upload_bytes(
        app_client, _make_pdf_with_old_pagenums(pages=2, band_body=False,
                                                fonts=["helv", "tiro"]))

    content = _process_and_download(app_client, task_id, file_id, add_page_number=True)

    w = 595
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        for i, page in enumerate(doc):
            rects = page.search_for(f"- {i + 1} -")
            assert len(rects) == 2, f"第{i + 1}页字体不成链应保留旧页码（新增1+旧1）"
            assert any(r.x0 > w * 0.7 for r in rects), "右侧旧页码应保留（字体不一致不误删）"
    finally:
        doc.close()


# 链判据反例②（位置一致）：序号连续、字体一致，但逐页水平位置错开 → 不成链 → 不检出不误删
def test_chain_position_mismatch_not_removed(app_client):
    task_id, file_id = _upload_bytes(
        app_client, _make_pdf_with_old_pagenums(pages=2, band_body=False,
                                                x_offsets=[0, -100]))

    content = _process_and_download(app_client, task_id, file_id, add_page_number=True)

    w = 595
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        for i, page in enumerate(doc):
            rects = page.search_for(f"- {i + 1} -")
            assert len(rects) == 2, f"第{i + 1}页位置不成链应保留旧页码（新增1+旧1）"
            assert any(r.x0 > w * 0.7 for r in rects), "右侧旧页码应保留（位置不一致不误删）"
    finally:
        doc.close()


# 单页文档边界：带内仅旧页码 → 链长1采信（单页放宽），检出移除后重编为 - 1 -
# （与修复前单页整带匹配行为一致，验证链最短页数规则的放宽分支）
def test_single_page_old_pagenum_removed(app_client):
    task_id, file_id = _upload_bytes(
        app_client, _make_pdf_with_old_pagenums(pages=1, band_body=False))

    content = _process_and_download(app_client, task_id, file_id, add_page_number=True)

    doc = fitz.open(stream=content, filetype="pdf")
    try:
        page = doc[0]
        assert not page.search_for("- 5 -"), "单页旧页码 - 5 - 应被检出移除"
        rects = page.search_for("- 1 -")
        assert len(rects) == 1 and abs((rects[0].x0 + rects[0].x1) / 2 - 595 / 2) < 2, \
            "应重编为居中的 - 1 -"
    finally:
        doc.close()
