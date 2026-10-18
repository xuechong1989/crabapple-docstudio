# -*- coding: utf-8 -*-
# zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题 存量PDF一键瘦身运维脚本
"""存量 PDF 一键瘦身脚本（运维人员使用）。

背景：3.2.05 之前生成的图片转PDF/编辑PDF输出，每页重复内嵌一份全量中文字库
（PyMuPDF china-s 对应 Droid Sans Fallback，约 1.6~3.5MB/页），实测字库占整本
PDF 体积的 62%~75%。本脚本对存量 PDF 执行与生成侧相同的修复：先 doc.subset_fonts()
（整本只保留实际使用字形），再以 garbage=4 + deflate=True 保存，旧全量字库流被
垃圾回收；图片流、页面尺寸、页码与OCR文字层内容不变。

用法（生产环境建议先停服或低峰执行，替换为原子操作）：
    python scripts/shrink_pdf_fonts.py --root ./data/users --dry-run   # 仅扫描报告
    python scripts/shrink_pdf_fonts.py --root ./data/users --apply     # 备份+瘦身+校验+替换
    python scripts/shrink_pdf_fonts.py --file 某.pdf --apply              # 只处理单文件

默认 --root 取 url.conf 配置的数据根目录下 users 目录；处理前先备份原文件到
{数据根}/backup/pdf_font_shrink_{时间戳}/，校验不通过时保留原文件并删除临时文件。
"""

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 候选判定阈值：存在>=2份且单份>=512KB的字库程序流，或单份>=2MB的全量字库
# （覆盖"每页重复嵌全量字库"与"单页整份字库"两类场景，跳过普通小字体PDF）
_MIN_DUP_FONT_BYTES = 512 * 1024
_MIN_SINGLE_FONT_BYTES = 2 * 1024 * 1024


def _log(msg: str) -> None:
    """带时间戳的控制台输出（UTF-8 环境已由 setup_utf8_encoding 保证）"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
    sys.stdout.flush()


def _font_program_stats(doc) -> Tuple[int, int, int]:
    """统计字体程序流(/Length1)数量、最大长度、总长度（只读元数据，不读流内容）"""
    count = 0
    max_len = 0
    total_len = 0
    for xref in range(1, doc.xref_length()):
        try:
            kind, val = doc.xref_get_key(xref, "Length1")
            if kind == "int":
                n = int(val)
                count += 1
                max_len = max(max_len, n)
                total_len += n
        except Exception:
            continue
    return count, max_len, total_len


def _is_candidate(doc) -> bool:
    """是否疑似"每页重复嵌全量字库/单页整份字库"的 PDF"""
    count, max_len, _ = _font_program_stats(doc)
    if count >= 2 and max_len >= _MIN_DUP_FONT_BYTES:
        return True
    if count >= 1 and max_len >= _MIN_SINGLE_FONT_BYTES:
        return True
    return False


def _sample_pages(page_count: int) -> list:
    """抽样页：<=8页全查，否则均匀取首/1/4/1/2/3/4/尾共5页"""
    if page_count <= 8:
        return list(range(page_count))
    picks = {0, page_count // 4, page_count // 2, page_count * 3 // 4, page_count - 1}
    return sorted(picks)


def _verify_reduced(orig_path: Path, reduced_path: Path) -> Tuple[bool, str]:
    """逐项校验瘦身后 PDF：页数、抽样页文字层、抽样页图像、抽样页渲染像素"""
    try:
        import fitz  # PyMuPDF

        with fitz.open(str(orig_path)) as orig_doc, fitz.open(str(reduced_path)) as new_doc:
            if len(orig_doc) != len(new_doc):
                return False, f"页数不一致: 原{len(orig_doc)} -> 新{len(new_doc)}"

            for idx in _sample_pages(len(orig_doc)):
                orig_page = orig_doc[idx]
                new_page = new_doc[idx]

                if orig_page.get_text() != new_page.get_text():
                    return False, f"第{idx + 1}页文字层内容不一致"

                def _image_dims(page):
                    return sorted((im[2], im[3]) for im in page.get_images(full=True))

                if _image_dims(orig_page) != _image_dims(new_page):
                    return False, f"第{idx + 1}页图像数量/尺寸不一致"

                orig_pix = orig_page.get_pixmap(dpi=72).samples
                new_pix = new_page.get_pixmap(dpi=72).samples
                if orig_pix != new_pix:
                    return False, f"第{idx + 1}页渲染像素不一致"
        return True, ""
    except Exception as e:
        return False, f"校验异常: {e}"


def _backup_path_for(pdf: Path, root: Optional[Path], backup_dir: Path) -> Path:
    """备份目标路径：镜像扫描根相对结构；--file 模式直接按文件名存放"""
    if root is not None:
        try:
            rel = pdf.relative_to(root)
            return backup_dir / rel
        except ValueError:
            pass
    return backup_dir / pdf.name


def _is_edit_pdf_intermediate(pdf: Path) -> bool:
    """是否编辑PDF任务目录下的中间单页（pages/page_*_dual.pdf）。

    中间页只是编辑PDF合并的素材，不直接下载，合并输出时已做字库子集化；
    仅当路径含 edit_pdf 任务目录且存在 pages 段时才跳过，避免误伤用户自建 pages 目录产物。
    """
    parts = pdf.parts
    for idx, part in enumerate(parts):
        if part == "pages" and "edit_pdf" in parts[:idx]:
            return True
    return False


def _shrink_one(pdf: Path, root: Optional[Path], backup_dir: Path, dry_run: bool) -> dict:
    """处理单个 PDF：返回 {status, orig_kb, new_kb, note}"""
    import fitz  # PyMuPDF
    from backend.services.pdf_font_service import save_pdf_with_font_subset

    tmp_path = None
    try:
        with fitz.open(str(pdf)) as doc:
            count, max_len, _ = _font_program_stats(doc)
            if not _is_candidate(doc):
                return {"status": "SKIP", "orig_kb": pdf.stat().st_size / 1024, "new_kb": None,
                        "note": f"无全量/重复字库特征 (font={count}, max={max_len / 1024:.0f}KB)"}
        orig_kb = pdf.stat().st_size / 1024
        if dry_run:
            return {"status": "CANDIDATE", "orig_kb": orig_kb, "new_kb": None,
                    "note": f"font流={count}, 最大={max_len / 1024:.0f}KB"}

        # 先备份原文件（镜像相对结构），保证任何失败都可恢复
        backup_path = _backup_path_for(pdf, root, backup_dir)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(pdf), str(backup_path))

        # 写同目录临时文件，校验通过后再原子替换
        tmp_path = pdf.with_name(f"{pdf.stem}.shrinking.tmp.pdf")
        if tmp_path.exists():
            tmp_path.unlink()
        with fitz.open(str(pdf)) as doc:
            save_pdf_with_font_subset(doc, tmp_path)

        ok, reason = _verify_reduced(pdf, tmp_path)
        new_kb = tmp_path.stat().st_size / 1024
        if not ok:
            tmp_path.unlink(missing_ok=True)
            return {"status": "FAIL", "orig_kb": orig_kb, "new_kb": new_kb, "note": reason}

        if new_kb >= orig_kb - 1.0:
            tmp_path.unlink(missing_ok=True)
            return {"status": "NO_SAVING", "orig_kb": orig_kb, "new_kb": new_kb,
                    "note": "瘦身后体积未缩小，保留原文件"}

        os.replace(str(tmp_path), str(pdf))
        return {"status": "OK", "orig_kb": orig_kb, "new_kb": new_kb,
                "note": f"备份: {backup_path}"}
    except Exception as e:
        # 临时文件残留清理，原文件不受影响（替换前失败）
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return {"status": "FAIL", "orig_kb": None, "new_kb": None, "note": str(e)}


def _write_report(report_path: Path, lines: list) -> None:
    """报告同时落盘到数据根 logs 目录（UTF-8），供运维留档"""
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _log(f"报告已写入: {report_path}")
    except Exception as e:
        _log(f"[报告写入失败] {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="存量PDF一键瘦身（字体子集化+垃圾回收）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--root", default="", help="扫描根目录（默认: url.conf 数据根/users）")
    group.add_argument("--file", default="", help="只处理单个PDF文件")
    parser.add_argument("--dry-run", dest="apply", action="store_false",
                        help="仅扫描报告不修改（默认）")
    parser.add_argument("--apply", dest="apply", action="store_true",
                        help="执行：备份+瘦身+校验+原地替换")
    parser.add_argument("--backup-dir", default="", help="备份目录（默认: 数据根/backup/pdf_font_shrink_时间戳）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N个候选文件（测试用）")
    parser.set_defaults(apply=False)
    args = parser.parse_args()

    from backend.services.logging_service import setup_utf8_encoding
    setup_utf8_encoding()

    from backend import config as cfg

    data_dir = cfg.DATA_DIR
    if args.file:
        root = None
        pdfs = [Path(args.file)]
        if not pdfs[0].is_file():
            _log(f"[错误] 文件不存在: {args.file}")
            return 2
    else:
        root = Path(args.root) if args.root else data_dir / "users"
        if not root.is_dir():
            _log(f"[错误] 扫描根目录不存在: {root}")
            _log("请用 --root 显式指定数据 users 目录，或检查 url.conf 数据根配置")
            return 2
        pdfs = sorted(
            p for p in root.rglob("*.pdf")
            if ".shrinking.tmp." not in p.name and not _is_edit_pdf_intermediate(p)
        )

    if not pdfs:
        _log("未找到任何 PDF 文件")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(args.backup_dir) if args.backup_dir else data_dir / "backup" / f"pdf_font_shrink_{ts}"
    report_path = data_dir / "logs" / f"pdf_font_shrink_{ts}.log"

    mode = "apply" if args.apply else "dry-run"
    _log(f"模式: {mode} | 扫描: {len(pdfs)} 个PDF | 根目录: {root or '单文件'}")
    _log(f"备份目录: {backup_dir if args.apply else '（dry-run 不备份）'}")

    lines = []
    summary = {"OK": 0, "NO_SAVING": 0, "FAIL": 0, "SKIP": 0, "CANDIDATE": 0}
    total_orig_kb = 0.0
    total_new_kb = 0.0
    processed = 0

    for pdf in pdfs:
        result = _shrink_one(pdf, root, backup_dir, dry_run=not args.apply)
        status = result["status"]
        summary[status] = summary.get(status, 0) + 1
        if status == "CANDIDATE":
            total_orig_kb += result["orig_kb"] or 0
        elif status in ("OK", "NO_SAVING", "FAIL"):
            total_orig_kb += result["orig_kb"] or 0
            total_new_kb += result["new_kb"] or 0
        orig_kb_str = f"{result['orig_kb']:.1f}" if result["orig_kb"] is not None else "?"
        new_kb_str = f"{result['new_kb']:.1f}" if result["new_kb"] is not None else ""
        line = (f"[{status}] {pdf} 原={orig_kb_str}KB"
                + (f" 新={new_kb_str}KB" if result["new_kb"] is not None else "")
                + f" {result['note']}")
        _log(line)
        lines.append(line)
        if status in ("OK", "NO_SAVING", "FAIL", "CANDIDATE"):
            processed += 1
            if args.limit and processed >= args.limit:
                _log(f"已达 --limit {args.limit}，停止")
                break

    if summary.get("OK") and total_orig_kb > 0:
        saved_pct = (1 - total_new_kb / total_orig_kb) * 100
        summary_line = (f"汇总: 成功={summary['OK']} 无收益={summary['NO_SAVING']} "
                        f"失败={summary['FAIL']} 跳过={summary['SKIP']} 候选={summary['CANDIDATE']} | "
                        f"已处理原体积={total_orig_kb / 1024:.1f}MB 瘦身后={total_new_kb / 1024:.1f}MB "
                        f"节省={saved_pct:.1f}%")
    else:
        summary_line = (f"汇总: 成功={summary['OK']} 无收益={summary['NO_SAVING']} "
                        f"失败={summary['FAIL']} 跳过={summary['SKIP']} 候选={summary['CANDIDATE']}")
    _log(summary_line)
    lines.append(summary_line)
    _write_report(report_path, lines)

    return 1 if summary.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
