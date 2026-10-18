# -*- coding: utf-8 -*-
# xuechong 2026-08-19 研发BUG-0027-图档扫描-3.1.06-票据单据区分判定逻辑优化 全量测试工具正式化
"""
海棠文档工坊 - 全量样张测试工具（两层测试方法论）

测试必须包含两层（缺一不可，2026-08-19 教训：A/B 一致只能证明"没有变坏"，
不能证明"效果达标"——倾斜欠检缺陷两版本共有，A/B 判 SAME 照样通过）：
  第①层 A/B 回归：基线版本 vs 当前版本全量处理，逐像素对比 → 证明"零回归"
  第②层 绝对质量扫描：对当前版本输出直接度量（剩余倾斜角/边缘空白带）→ 证明"效果达标"

子命令：
    batch    批量处理样张（指定版本的项目根，输出 PNG + 处理记录）
    compare  双版本逐像素对比（第①层）
    quality  绝对质量扫描（第②层，不需要基线）
    retention 双向准确性度量（内容保留率防误删 + 输出残斑计数防残留）
    all      一键执行：batch(基线) → batch(当前) → compare → quality

使用方法（典型全量测试，基线用 git worktree 建旧版本目录）：
    git worktree add ./.tmp/ds-baseline <基线提交>
    python scripts/full_test.py all --baseline-root ./.tmp/ds-baseline \\
        --current-root . --work "./.tmp/test-output"
    git worktree remove ./.tmp/ds-baseline --force

    # 只跑第②层质量扫描（对既有输出目录）：
    python scripts/full_test.py quality --dir <某版本输出目录>

    # 试跑（每子命令均支持 --limit N 只处理前 N 张）

历史教训（脚本内已固化，改动前必读）：
    1. 输出文件名必须含完整相对路径+原始扩展名（曾因仅用 stem 导致不同批次
       001/002 同名互相覆盖，453 张全 SAME 的假结果）；
    2. multiprocessing 必须有 __main__ 保护（曾因缺失导致 Windows spawn 死循环）；
    3. "全部一致"是危险信号：必须有预期差异锚点图交叉对照对比有效性；
    4. 质量告警甄别：样张目录混有历史调试中间图（文件名含 raw/no_correct/
       红框/结果 等），报告单列"疑似调试图"不计入系统缺陷。
"""

import argparse
import os
import json
import random
import sys
import time
import traceback
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

DEFAULT_SAMPLE_DIR = os.environ.get("DOCSTUDIO_SAMPLE_DIR", "samples")
EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
# 疑似历史调试中间图的文件名模式（质量告警甄别用，不计入系统缺陷）
DEBUG_PATTERNS = ("raw", "no_correct", "红框", "结果", "result", "boundary", "preview", "原图", "矫正后")


# ----------------------------------------------------------------------
# 公共工具
# ----------------------------------------------------------------------

def png_name(rel: str) -> str:
    """输出 PNG 文件名：批次目录 + 完整原始文件名（含扩展名），杜绝同名覆盖"""
    p = Path(rel)
    return "_".join(p.parts[:-1]) + "_" + p.name + ".png"


def scan_samples(sample_dir: Path, limit: int = 0) -> list:
    """扫描样张目录，返回 (绝对路径, 相对路径) 列表（排序稳定）"""
    tasks = []
    for p in sorted(sample_dir.rglob("*")):
        if p.suffix.lower() in EXTS and p.is_file():
            tasks.append((str(p), str(p.relative_to(sample_dir))))
            if 0 < limit <= len(tasks):
                break
    return tasks


def load_meta(d: Path) -> dict:
    m = {}
    f = d / "meta.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                m[r["rel"]] = r
    return m


def load_img(p) -> np.ndarray:
    """项目标准加载模式（兼容中文路径）"""
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


# ----------------------------------------------------------------------
# 子命令：batch（批量处理）
# ----------------------------------------------------------------------

_worker = {}


def _batch_init(root: str, out: str):
    import doclayout_yolo.utils.torch_utils as _tu
    _tu.get_cpu_info = lambda: "CPU (mock)"
    # xuechong 2026-08-27 研发需求-0137-图档扫描-3.1.10-目录结构调整以方便备份和管理
    # 兼容新旧包名：backend（本仓库重组后）/ document_scanner（≤3.1.09 发布包，作 A/B 基线时仍为旧包名）
    if (Path(root) / "backend" / "cleaner").is_dir():
        import backend as pkg
        from backend.cleaner import DocumentCleaner
    else:
        import document_scanner as pkg
        from document_scanner.cleaner import DocumentCleaner
    _worker["ver"] = pkg.__version__
    _worker["cleaner"] = DocumentCleaner()
    _worker["out"] = Path(out)  # 经 initargs 传入（spawn 子进程不继承主进程变量）
    print(f"[worker] 加载版本 {pkg.__version__}[{pkg.__name__}] 自 {root}", flush=True)


def _batch_run(task):
    src, rel = task
    t0 = time.time()
    rec = {"rel": rel.replace("\\", "/"), "ok": False}
    try:
        img = load_img(src)
        if img is None:
            rec["error"] = "decode_failed"
            return rec
        result = _worker["cleaner"].process(img, debug=False, dpi=300)
        out = result["result"]
        ok, buf = cv2.imencode(".png", out)
        buf.tofile(str(_worker["out"] / png_name(rec["rel"])))
        rec.update(ok=True, ver=_worker["ver"], shape=f"{out.shape[1]}x{out.shape[0]}",
                   receipt=result.get("is_receipt"), color_receipt=result.get("is_color_receipt"),
                   dt=round(time.time() - t0, 1))
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["tb"] = traceback.format_exc()[-400:]
    return rec


def cmd_batch(args):
    root = Path(args.root).resolve()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tasks = scan_samples(Path(args.sample_dir), args.limit)
    if not tasks:
        print(f"[batch] 样张目录无图片: {args.sample_dir}")
        return 1
    print(f"[batch] 版本根={root} 输出={out} 任务数={len(tasks)}", flush=True)

    sys.path.insert(0, str(root))
    meta_file = out / "meta.jsonl"
    done = 0
    with Pool(args.workers, initializer=_batch_init, initargs=(str(root), str(out))) as pool, \
            open(meta_file, "w", encoding="utf-8") as mf:
        for rec in pool.imap_unordered(_batch_run, tasks, chunksize=1):
            mf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            mf.flush()
            done += 1
            if done % 20 == 0 or done == len(tasks):
                print(f"[batch] 进度 {done}/{len(tasks)}", flush=True)
    print(f"[batch] 完成，记录 {meta_file}")
    return 0


# ----------------------------------------------------------------------
# 子命令：compare（第①层 A/B 回归对比）
# ----------------------------------------------------------------------

def cmd_compare(args):
    d5, d6 = Path(args.baseline_dir), Path(args.current_dir)
    m5, m6 = load_meta(d5), load_meta(d6)
    rels = sorted(set(m5) | set(m6))
    print(f"[compare] 基线 {len(m5)} 张 vs 当前 {len(m6)} 张，并集 {len(rels)} 张")

    rows = []
    for rel in rels:
        r5, r6 = m5.get(rel), m6.get(rel)
        row = {"rel": rel, "batch": rel.split("/")[0]}
        if r5 is None or r6 is None:
            row.update(diff="MISSING")
            rows.append(row)
            continue
        row["p5"] = [r5.get("receipt"), r5.get("color_receipt")]
        row["p6"] = [r6.get("receipt"), r6.get("color_receipt")]
        if not r5["ok"] or not r6["ok"]:
            row.update(diff="ERROR", note=f"{r5.get('error')} / {r6.get('error')}")
            rows.append(row)
            continue
        a, b = load_img(d5 / png_name(rel)), load_img(d6 / png_name(rel))
        if a is None or b is None or a.shape != b.shape:
            row.update(diff="SHAPE", note=f"{r5.get('shape')} / {r6.get('shape')}")
            rows.append(row)
            continue
        d = int(np.sum(np.any(a != b, axis=2)))
        total = a.shape[0] * a.shape[1]
        row["diff_px"] = d
        row["diff_pct"] = round(100.0 * d / total, 3)
        row["diff"] = "SAME" if d == 0 else ("TINY" if d < total * 0.001 else "BIG")
        rows.append(row)

    stat = defaultdict(int)
    for r in rows:
        stat[r["diff"]] += 1
    print(f"\n[compare] === A/B 回归总览（第①层：证明零回归，不证明效果达标）===")
    print(f"完全一致 {stat['SAME']} | 微小差异 {stat['TINY']} | 显著差异 {stat['BIG']} "
          f"| 形状不同 {stat['SHAPE']} | 缺失 {stat['MISSING']} | 异常 {stat['ERROR']}")

    if stat["BIG"] + stat["TINY"] + stat["SHAPE"] > 0:
        print("\n[compare] 差异明细（含判定路径变化，逐张核对是否均为预期修复对象）：")
        for r in rows:
            if r["diff"] in ("TINY", "BIG", "SHAPE"):
                print(f"  [{r['diff']}] {r['rel']} diff={r.get('diff_px', '-')}px "
                      f"({r.get('diff_pct', '-')}%) {r.get('p5')} -> {r.get('p6')} {r.get('note', '')}")

    out_json = Path(args.current_dir).parent / "full_test_AB对比.json"
    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[compare] 明细已保存 {out_json}")
    print("[compare] 提醒：若显著差异非预期修复对象，即为回归，必须排查后才能交付")
    return 0


# ----------------------------------------------------------------------
# 子命令：quality（第②层 绝对质量扫描）
# ----------------------------------------------------------------------

def _quality_run(job):
    rel, png = job
    img = load_img(png)
    if img is None:
        return {"rel": rel, "err": "read_fail"}
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 剩余倾斜角：二值化后 HoughLinesP 近水平长线角度中位数（与输出版本无关的绝对指标）
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    lines = cv2.HoughLinesP(bw, 1, np.pi / 360, threshold=120,
                            minLineLength=int(min(g.shape) * 0.3), maxLineGap=8)
    angles = []
    if lines is not None:
        # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
        # 兼容 OpenCV 4.x 返回 (N,1,4) 与 5.0 返回 (N,4)：统一 reshape 为 (N,4) 再逐行解包
        for l in lines.reshape(-1, 4):
            x1, y1, x2, y2 = l
            ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(ang) < 10:
                angles.append(ang)
    skew = round(float(np.median(angles)), 3) if angles else None

    # 边缘空白带（矫正画布外扩指示器）
    row_light = (g > 240).mean(axis=1)
    col_light = (g > 240).mean(axis=0)
    top = int(np.argmax(row_light < 0.99)) if (row_light < 0.99).any() else 0
    left = int(np.argmax(col_light < 0.99)) if (col_light < 0.99).any() else 0
    return {"rel": rel, "residual_skew": skew, "n_lines": len(angles), "edge_top": top, "edge_left": left}


def cmd_quality(args):
    d = Path(args.dir)
    meta = load_meta(d)
    if not meta:
        print(f"[quality] 无 meta.jsonl: {d}")
        return 1
    jobs = [(rel, d / png_name(rel)) for rel in sorted(meta)]
    print(f"[quality] 扫描 {len(jobs)} 张输出（剩余倾斜角 + 边缘空白，绝对指标无需基线）", flush=True)
    results = []
    with Pool(args.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(_quality_run, jobs, chunksize=4)):
            results.append(r)
            if (i + 1) % 50 == 0:
                print(f"[quality] 进度 {i+1}/{len(jobs)}", flush=True)

    warn, severe, suspect_debug, nolines, ok = [], [], [], 0, 0
    for r in sorted(results, key=lambda x: -abs(x.get("residual_skew") or 0)):
        s = r.get("residual_skew")
        name = Path(r["rel"]).name.lower()
        is_debug = any(p in name for p in DEBUG_PATTERNS)
        if s is None or r.get("n_lines", 0) < 3:
            nolines += 1
            continue
        if abs(s) > args.severe:
            (suspect_debug if is_debug else severe).append(r)
        elif abs(s) > args.warn:
            (suspect_debug if is_debug else warn).append(r)
        else:
            ok += 1

    print(f"\n[quality] === 绝对质量扫描总览（第②层：证明效果达标）===")
    print(f"剩余倾斜正常(<= {args.warn}°): {ok} 张")
    print(f"告警({args.warn}~{args.severe}°): {len(warn)} 张 | 严重(> {args.severe}°): {len(severe)} 张")
    print(f"疑似调试中间图告警（甄别不计入缺陷）: {len(suspect_debug)} 张 | 无可测横线: {nolines} 张")
    if severe:
        print("\n[quality] 严重清单：")
        for r in severe:
            print(f"  {r['rel']} 剩余 {r['residual_skew']}° ({r['n_lines']}线)")
    if warn:
        print(f"\n[quality] 告警清单（前 10）：")
        for r in warn[:10]:
            print(f"  {r['rel']} 剩余 {r['residual_skew']}° ({r['n_lines']}线)")

    batch_stat = defaultdict(int)
    for r in warn + severe:
        batch_stat[r["rel"].split("/")[0]] += 1
    if batch_stat:
        print("\n[quality] 批次分布（告警+严重）：")
        for b, n in sorted(batch_stat.items(), key=lambda x: -x[1]):
            print(f"  {b}: {n} 张")

    out_json = d.parent / "full_test_质量扫描.json"
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[quality] 明细已保存 {out_json}")
    return 0


# ----------------------------------------------------------------------
# 子命令：retention（双向准确性度量，研发BUG-0030 REQ-001）
# ----------------------------------------------------------------------
# xuechong 2026-08-20 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-001
# 内容保留率（防误删）：原图 vs 净化输出分别 OCR，字符数保留率与置信度变化
# 输出残斑计数（防残留）：净化输出二值化连通域，逐斑记录最暗灰度/面积/位置/
#   文字重叠（OCR det 框膨胀扣除文字区），按最暗灰度≤阈值计数，分边缘带内/带外
# 口径说明：残斑面积/尺寸过滤沿用钉痕检测同口径（面积≥15、边长≤150，
#   对应 cfg.PUNCH_HOLE_MIN_AREA/PUNCH_HOLE_MAX_DIM，脚本内不 import config 保持零依赖）；
#   边缘带沿用 cfg.EDGE_MARGIN_RATIO=0.10 四边 margin
# v2 口径（2026-08-21 基线视觉核检修订）：016/0096 等表格类文档的表格线碎片、
#   印章碎墨被误计为残留（视觉已干净但计数数百斑），追加两个正常内容排除：
#   ①长线排除——形态学开运算提取横/竖长线（≥120px）并膨胀，blob 与线区重叠即排除；
#   ②相对彩色排除——blob 平均饱和度比全图中位饱和度高 30 以上视为彩色内容（印章/
#   彩票内容）排除；用相对判据防黄色票据底色（净化后保留黄底）导致全页误排除
def _load_anchor_rels(anchor_file: Path) -> list:
    """解析难例标注清单（markdown 表格行 | rel | 标注 | ... |），取 rel 列"""
    rels = []
    for line in anchor_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and not set(cells[0]) <= set("- ") and "/" in cells[0] and "、" not in cells[0]:
            rels.append(cells[0])
    return rels


def _residue_blobs(bgr: np.ndarray, text_boxes: list, enum_thresh: int,
                   edge_ratio: float = 0.10, dilate_r: int = 15) -> list:
    """枚举净化输出上的残留暗斑候选，逐斑记录判定所需全部字段（阈值后置可调）"""
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, enum_thresh, 255, cv2.THRESH_BINARY_INV)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    ex, ey = int(w * edge_ratio), int(h * edge_ratio)
    # OCR det 框膨胀后的文字区矩形（blob 与任一矩形相交即视为文字重叠，排除出残留计数）
    rects = [(max(0, int(x1) - dilate_r), max(0, int(y1) - dilate_r),
              min(w, int(x2) + dilate_r), min(h, int(y2) + dilate_r))
             for x1, y1, x2, y2 in text_boxes]
    # v2 长线掩码：开运算提取 ≥120px 的横/竖长线（表格线/边框线），膨胀 5px
    k_len = 120
    k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (k_len, 1))
    k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, k_len))
    lines_mask = cv2.dilate(cv2.bitwise_or(
        cv2.morphologyEx(binary, cv2.MORPH_OPEN, k_h),
        cv2.morphologyEx(binary, cv2.MORPH_OPEN, k_v)),
        cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11)))
    # v2 相对彩色基准：全图中位饱和度
    med_sat = float(np.median(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 1]))
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 15 or bw > 150 or bh > 150:
            continue
        cx, cy = x + bw / 2.0, y + bh / 2.0
        in_edge = cx < ex or cx > w - ex or cy < ey or cy > h - ey
        overlap = any(not (x > r[2] or x + bw < r[0] or y > r[3] or y + bh < r[1]) for r in rects)
        on_line = bool(lines_mask[y:y + bh, x:x + bw].any())
        blob_sat = float(np.mean(cv2.cvtColor(bgr[y:y + bh, x:x + bw], cv2.COLOR_BGR2HSV)[:, :, 1]))
        min_gray = int(gray[y:y + bh, x:x + bw][labels[y:y + bh, x:x + bw] == i].min())
        out.append({"min_gray": min_gray, "area": int(area), "cx": int(cx), "cy": int(cy),
                    "in_edge": bool(in_edge), "text_overlap": bool(overlap),
                    "on_line": on_line, "color_diff": round(blob_sat - med_sat, 1)})
    return out


def cmd_retention(args):
    d = Path(args.dir)
    meta = load_meta(d)
    if not meta:
        print(f"[retention] 无 meta.jsonl: {d}")
        return 1
    rels_ok = [rel for rel in sorted(meta) if meta[rel].get("ok")]

    anchors = []
    if args.anchors:
        all_anchors = _load_anchor_rels(Path(args.anchors))
        anchors = [r for r in all_anchors if r in meta]
        missing = [r for r in all_anchors if r not in meta]
        if missing:
            print(f"[retention] 警告：{len(missing)} 个锚点不在 meta 中（跳过）：{missing[:5]}")

    if args.sample > 0:
        rng = random.Random(20260820)  # 固定种子保证抽样可复现
        pool = [r for r in rels_ok if r not in set(anchors)]
        need = max(0, args.sample - len(anchors))
        sel = anchors + (rng.sample(pool, need) if need < len(pool) else pool)
    else:
        sel = anchors + [r for r in rels_ok if r not in set(anchors)] if anchors else rels_ok
    print(f"[retention] 样本 {len(sel)} 张（锚点 {len(anchors)} + 随机 {len(sel) - len(anchors)}），"
          f"残斑枚举阈值 {args.residue_enum_thresh} / 计数阈值 {args.residue_thresh}", flush=True)

    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    # 兼容新旧包名（backend=重组后本仓库；document_scanner=旧版基线发布包）
    if (root / "backend").is_dir():
        from backend.ocr_rapid import get_rapid_ocr_engine, ocr_image_with_rapid
    else:
        from document_scanner.ocr_rapid import get_rapid_ocr_engine, ocr_image_with_rapid
    engine_info = get_rapid_ocr_engine()

    sample_dir = Path(args.sample_dir)
    records = []
    for idx, rel in enumerate(sel, 1):
        rec = {"rel": rel}
        try:
            raw = load_img(sample_dir / rel)
            clean = load_img(d / png_name(rel))
            if raw is None or clean is None:
                rec["error"] = "read_fail"
                records.append(rec)
                continue
            ocr_raw = ocr_image_with_rapid(raw, engine_info)
            ocr_clean = ocr_image_with_rapid(clean, engine_info)
            chars_raw = sum(len(it["text"]) for it in ocr_raw)
            chars_clean = sum(len(it["text"]) for it in ocr_clean)
            conf_raw = float(np.mean([it["confidence"] for it in ocr_raw])) if ocr_raw else None
            conf_clean = float(np.mean([it["confidence"] for it in ocr_clean])) if ocr_clean else None
            rec.update(chars_raw=chars_raw, chars_clean=chars_clean,
                       retention=round(chars_clean / chars_raw, 4) if chars_raw > 0 else None,
                       conf_raw=round(conf_raw, 4) if conf_raw is not None else None,
                       conf_clean=round(conf_clean, 4) if conf_clean is not None else None)

            gray = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
            boxes = []
            for it in ocr_clean:
                xs = [p[0] for p in it["box"]]
                ys = [p[1] for p in it["box"]]
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
            # v2 口径：_residue_blobs 内部执行文字框/长线/相对彩色三项正常内容排除
            blobs = _residue_blobs(clean, boxes, args.residue_enum_thresh)
            counted = [b for b in blobs if b["min_gray"] <= args.residue_thresh
                       and not b["text_overlap"] and not b["on_line"] and b["color_diff"] <= 30]
            rec.update(residue_threshold=args.residue_thresh,
                       residue_blobs_edge=sum(1 for b in counted if b["in_edge"]),
                       residue_blobs_inner=sum(1 for b in counted if not b["in_edge"]),
                       residue_area_edge=sum(b["area"] for b in counted if b["in_edge"]),
                       residue_area_inner=sum(b["area"] for b in counted if not b["in_edge"]),
                       blobs=blobs)
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        records.append(rec)
        if idx % 5 == 0 or idx == len(sel):
            print(f"[retention] 进度 {idx}/{len(sel)}", flush=True)

    # 汇总：内容保留率
    rets = [r["retention"] for r in records if r.get("retention") is not None]
    low = [(r["rel"], r["retention"]) for r in records if r.get("retention") is not None and r["retention"] < 0.98]
    conf_deltas = [r["conf_clean"] - r["conf_raw"] for r in records
                   if r.get("conf_clean") is not None and r.get("conf_raw") is not None]
    print(f"\n[retention] === 内容保留率（防误删）===")
    if rets:
        print(f"样本 {len(rets)} 张：均值 {np.mean(rets):.4f} / 中位 {np.median(rets):.4f} / 最小 {min(rets):.4f}")
    print(f"保留率 <0.98 共 {len(low)} 张" + (f"：{low[:10]}" if low else ""))
    if conf_deltas:
        print(f"OCR 置信度变化均值：{np.mean(conf_deltas):+.4f}")

    # 汇总：输出残斑（按当前计数阈值）+ 最暗灰度分布（供阈值锚定）
    edge_n = sum(r.get("residue_blobs_edge", 0) for r in records)
    inner_n = sum(r.get("residue_blobs_inner", 0) for r in records)
    print(f"\n[retention] === 输出残斑计数（防残留，阈值 {args.residue_thresh}，已扣文字区/长线/彩色）===")
    print(f"边缘带内（应清区）共 {edge_n} 斑 / 带外共 {inner_n} 斑")
    hist_bins = [(0, 180), (181, 200), (201, 220), (221, 235), (236, 245), (246, 250)]
    non_text = [b["min_gray"] for r in records for b in r.get("blobs", [])
                if not b["text_overlap"] and not b["on_line"] and b["color_diff"] <= 30]
    if non_text:
        print("非文字斑最暗灰度分布：" + " | ".join(
            f"{lo}-{hi}:{sum(1 for g in non_text if lo <= g <= hi)}" for lo, hi in hist_bins))
    text_n = sum(1 for r in records for b in r.get("blobs", []) if b["text_overlap"])
    line_n = sum(1 for r in records for b in r.get("blobs", []) if b["on_line"] and not b["text_overlap"])
    color_n = sum(1 for r in records for b in r.get("blobs", [])
                  if b["color_diff"] > 30 and not b["text_overlap"] and not b["on_line"])
    print(f"正常内容排除：文字重叠 {text_n} 斑 / 长线附近 {line_n} 斑 / 相对彩色 {color_n} 斑")

    out = Path(args.out) if args.out else d.parent / "full_test_retention.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    print(f"\n[retention] 明细已保存 {out}")
    return 0


# ----------------------------------------------------------------------
# 子命令：all（一键两层测试）
# ----------------------------------------------------------------------

def cmd_all(args):
    work = Path(args.work)
    base_dir = work / "baseline"
    cur_dir = work / "current"
    rc = cmd_batch(argparse.Namespace(root=args.baseline_root, out=str(base_dir),
                                      sample_dir=args.sample_dir, workers=args.workers, limit=args.limit))
    if rc:
        return rc
    rc = cmd_batch(argparse.Namespace(root=args.current_root, out=str(cur_dir),
                                      sample_dir=args.sample_dir, workers=args.workers, limit=args.limit))
    if rc:
        return rc
    rc = cmd_compare(argparse.Namespace(baseline_dir=str(base_dir), current_dir=str(cur_dir)))
    if rc:
        return rc
    rc = cmd_quality(argparse.Namespace(dir=str(cur_dir), workers=args.workers,
                                        warn=args.warn, severe=args.severe))
    print("\n[all] 两层测试完成：A/B 对比结论只代表'零回归'，质量扫描结论代表'效果达标'，两者都通过才可交付")
    return rc


def main():
    ap = argparse.ArgumentParser(description="全量样张两层测试工具（A/B 回归 + 绝对质量扫描）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("batch", help="批量处理样张（指定版本项目根）")
    p.add_argument("--root", required=True, help="要加载的项目根（含 backend\\ 或 document_scanner\\ 包）")
    p.add_argument("--out", required=True, help="输出目录（PNG + meta.jsonl）")
    p.add_argument("--sample-dir", default=DEFAULT_SAMPLE_DIR, help=f"样张目录（默认 {DEFAULT_SAMPLE_DIR}）")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0, help=">0 时仅处理前 N 张（试跑）")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("compare", help="双版本逐像素对比（第①层 A/B 回归）")
    p.add_argument("--baseline-dir", required=True, help="基线版本输出目录")
    p.add_argument("--current-dir", required=True, help="当前版本输出目录")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("quality", help="绝对质量扫描（第②层，无需基线）")
    p.add_argument("--dir", required=True, help="待扫描的输出目录（含 meta.jsonl）")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--warn", type=float, default=0.5, help="剩余倾斜告警阈值（度，默认 0.5）")
    p.add_argument("--severe", type=float, default=1.0, help="剩余倾斜严重阈值（度，默认 1.0）")
    p.set_defaults(func=cmd_quality)

    # xuechong 2026-08-20 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 REQ-001 retention 子命令
    p = sub.add_parser("retention", help="双向准确性度量：内容保留率 + 输出残斑计数")
    p.add_argument("--dir", required=True, help="净化输出目录（含 meta.jsonl 与 PNG）")
    p.add_argument("--root", default=".", help="OCR 引擎加载的项目根（默认当前目录）")
    p.add_argument("--sample-dir", default=DEFAULT_SAMPLE_DIR, help=f"样张目录（默认 {DEFAULT_SAMPLE_DIR}）")
    p.add_argument("--anchors", default=None, help="难例标注清单（markdown 表格），锚点全量纳入")
    p.add_argument("--sample", type=int, default=60, help="抽样总数（锚点+随机普通），0=全量")
    p.add_argument("--residue-thresh", type=int, default=245,
                   help="残斑计数阈值：非文字斑最暗灰度 ≤ 此值计为残留（默认 245 初值，基线后按分布锚定）")
    p.add_argument("--residue-enum-thresh", type=int, default=250, help="残斑枚举二值化阈值（须 ≥ 计数阈值）")
    p.add_argument("--out", default=None, help="结果 jsonl 输出路径（默认 <dir> 上级 full_test_retention.jsonl）")
    p.set_defaults(func=cmd_retention)

    p = sub.add_parser("all", help="一键两层测试：batch×2 → compare → quality")
    p.add_argument("--baseline-root", required=True, help="基线版本项目根（建议 git worktree）")
    p.add_argument("--current-root", default=".", help="当前版本项目根（默认 .）")
    p.add_argument("--work", required=True, help="测试工作目录（输出 baseline/current 两子目录）")
    p.add_argument("--sample-dir", default=DEFAULT_SAMPLE_DIR)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--warn", type=float, default=0.5)
    p.add_argument("--severe", type=float, default=1.0)
    p.set_defaults(func=cmd_all)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
