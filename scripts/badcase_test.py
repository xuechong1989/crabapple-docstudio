# -*- coding: utf-8 -*-
r"""坏例集快速回归脚本（研发需求-0139）

对30张用户标注的净化问题样张（坏例）执行净化，输出净化PNG、三联对比图
（原图｜净化输出｜用户标注坏例）、meta.jsonl 与 index.html 索引页，
供每轮算法迭代分钟级快速验证与视觉评判使用；全量两层测试见 scripts/full_test.py。

用法（项目 .venv）：
    ./.venv/Scripts/python.exe scripts/badcase_test.py --round 0
    ./.venv/Scripts/python.exe scripts/badcase_test.py --round 1 --label 歪斜 --limit 5
"""
import argparse
import os
import json
import sys
import time
from collections import defaultdict
from datetime import date
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

# zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
# 坏例清单：rel=全量样张库相对路径，labels=用户标注问题类型，badcase=用户标注坏例文件名（位于 --badcase-dir）
BADCASES: list[tuple[str, tuple[str, ...], str]] = [
    ("2026-05-16-歪斜/ae/014.tif", ("孔洞",), "2026-05-16-歪斜_ae_014.tif_孔洞.jpg"),
    ("2026-05-16-歪斜/ae/015.tif", ("订书针孔",), "2026-05-16-歪斜_ae_015.tif_订书针孔.jpg"),
    ("2026-05-16-歪斜/af/018.tif", ("污渍",), "2026-05-16-歪斜_af_018.tif_污渍.jpg"),
    ("2026-05-18/004.tif", ("歪斜",), "2026-05-18_004.tif_歪斜.jpg"),
    ("2026-05-19-58/0006.tif", ("污渍",), "2026-05-19-58_0006.tif_污渍.jpg"),
    ("2026-05-19-58/0030.tif", ("污渍",), "2026-05-19-58_0030.tif_污渍.jpg"),
    ("2026-05-19-58/0038.tif", ("污渍",), "2026-05-19-58_0038.tif_污渍.jpg"),
    ("2026-05-19-58/0046.tif", ("污渍",), "2026-05-19-58_0046.tif_污渍.jpg"),
    ("2026-05-19-58/0054.tif", ("折痕",), "2026-05-19-58_0054.tif_折痕.jpg"),
    ("2026-05-19-58/0060.tif", ("污渍",), "2026-05-19-58_0060.tif_污渍.jpg"),
    ("2026-05-19-58/0076.tif", ("歪斜",), "2026-05-19-58_0076.tif_歪斜.jpg"),
    ("2026-05-19-58/0084.tif", ("污渍",), "2026-05-19-58_0084.tif_污渍.jpg"),
    ("2026-05-19-58/0107.tif", ("污渍", "歪斜", "边界不清"), "2026-05-19-58_0107.tif_污渍_歪斜_边界不清.jpg"),
    ("2026-05-19-58/0109.tif", ("歪斜", "污渍", "边界不清"), "2026-05-19-58_0109.tif_歪斜_污渍_边界不清.jpg"),
    ("2026-05-20-8/0002.tif", ("歪斜",), "2026-05-20-8_0002.tif_歪斜.jpg"),
    ("2026-05-20-8/0008.tif", ("折痕",), "2026-05-20-8_0008.tif_折痕.jpg"),
    ("2026-05-21-testcase-4/011.tif", ("过曝",), "2026-05-21-testcase-4_011.tif_过曝.jpg"),
    ("2026-05-27-黑边问题-11/013.tif", ("孔洞",), "2026-05-27-黑边问题-11_013.tif_孔洞.jpg"),
    ("2026-05-27-黑边问题-11/016.tif", ("歪斜",), "2026-05-27-黑边问题-11_016.tif_歪斜.jpg"),
    ("2026-06-01-综合测试-15/e002.tif", ("歪斜",), "2026-06-01-综合测试-15_e002.tif_歪斜.jpg"),
    ("2026-07-03/010.tif", ("污渍",), "2026-07-03_010.tif_污渍.jpg"),
    ("2026-07-03/017.tif", ("歪斜",), "2026-07-03_017.tif_歪斜.jpg"),
    ("2026-07-03/020.tif", ("污渍",), "2026-07-03_020.tif_污渍.jpg"),
    ("2026-07-03/143.tif", ("歪斜",), "2026-07-03_143.tif_歪斜.jpg"),
    ("2026-07-20-文档使用系统发现的问题1/002.tif", ("白化异常",), "2026-07-20-文档使用系统发现的问题1_002.tif_白化异常.jpg"),
    ("2026-07-20-文档使用系统发现的问题1/006.tif", ("Ocr不完整",), "2026-07-20-文档使用系统发现的问题1_006.tif_Ocr不完整.jpg"),
    ("2026-07-20-文档使用系统发现的问题1/007.tif", ("Ocr不完整",), "2026-07-20-文档使用系统发现的问题1_007.tif_Ocr不完整.jpg"),
    ("2026-08-05/008.tif", ("歪斜",), "2026-08-05_008.tif_歪斜.jpg"),
    ("2026-08-05/014.tif", ("方向矫正错误",), "2026-08-05_014.tif_方向矫正错误.jpg"),
    ("2026-08-05/038.tif", ("方向矫正错误",), "2026-08-05_038.tif_方向矫正错误.jpg"),
]

# zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
# 子进程工作变量（Windows spawn 不继承主进程变量，统一经 initargs 传入）
_worker: dict = {}


def png_name(rel: str) -> str:
    """与 full_test.py 一致的输出文件名规则：目录层级用 _ 连接 + 文件名 .png"""
    p = Path(rel)
    return "_".join(p.parts[:-1]) + "_" + p.name + ".png"


def load_img(path) -> np.ndarray | None:
    """项目标准加载模式，兼容中文路径"""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _init_worker(root: str, out: str, sample_root: str, badcase_dir: str) -> None:
    """子进程初始化：加载净化器与各目录（与 full_test.py 的 initargs 模式一致）"""
    import doclayout_yolo.utils.torch_utils as _tu
    _tu.get_cpu_info = lambda: "CPU (mock)"
    # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
    # 兼容新旧包名：backend（3.1.10 重组后）/ document_scanner（旧发布包）
    if (Path(root) / "backend" / "cleaner").is_dir():
        import backend as pkg
        from backend.cleaner import DocumentCleaner
    else:
        import document_scanner as pkg
        from document_scanner.cleaner import DocumentCleaner
    _worker["ver"] = pkg.__version__
    _worker["cleaner"] = DocumentCleaner()
    _worker["out"] = Path(out)
    _worker["sample_root"] = Path(sample_root)
    _worker["badcase_dir"] = Path(badcase_dir)


def _draw_label(canvas: np.ndarray, texts: list[str], widths: list[int], gap: int, label_h: int) -> np.ndarray:
    """在三联画布顶部标签条绘制各联中文标签（PIL 中文字体优先，失败回退英文）"""
    try:
        from PIL import Image, ImageDraw, ImageFont

        pil_img = Image.fromarray(canvas)
        draw = ImageDraw.Draw(pil_img)
        font = None
        for fp in (
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\msyh.ttf",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
        ):
            if Path(fp).exists():
                font = ImageFont.truetype(fp, 34)
                break
        if font is None:
            font = ImageFont.load_default()
        x = 0
        for i, t in enumerate(texts):
            draw.text((x + 16, 10), t, fill=(20, 20, 20), font=font)
            x += widths[i] + gap
        return np.array(pil_img)
    except Exception as e:  # noqa: BLE001 - 字体缺失等环境问题回退英文，不中断批处理
        print(f"[compare3] 中文标签绘制失败，回退英文: {e}", flush=True)
        cv2.putText(canvas, "Original", (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2)
        cv2.putText(canvas, "Cleaned", (widths[0] + gap + 16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2)
        cv2.putText(canvas, "Badcase", (widths[0] + widths[1] + 2 * gap + 16, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2)
        return canvas


def make_compare3(orig: np.ndarray, cleaned: np.ndarray, badcase: np.ndarray | None,
                  height: int, gap: int = 24) -> np.ndarray:
    """三联对比图：原图｜净化输出｜用户标注坏例，等高缩放并排+顶部标签条"""
    # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
    # 标注坏例缺失时以白底占位，保证三联结构稳定，便于轮次间对比
    def _fit(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        scale = height / h
        return cv2.resize(img, (max(1, int(w * scale)), height), interpolation=cv2.INTER_AREA)

    a, b = _fit(orig), _fit(cleaned)
    label_h = 56
    if badcase is None:
        c = np.full((height, 640, 3), 255, dtype=np.uint8)
        cv2.putText(c, "no badcase file", (24, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (120, 120, 120), 2)
    else:
        c = _fit(badcase)
    widths = [a.shape[1], b.shape[1], c.shape[1]]
    canvas_w = sum(widths) + 2 * gap
    canvas = np.full((height + label_h, canvas_w, 3), 255, dtype=np.uint8)
    x0 = 0
    for i, part in enumerate((a, b, c)):
        canvas[label_h:, x0: x0 + widths[i]] = part
        if i < 2:
            canvas[label_h:, x0 + widths[i]: x0 + widths[i] + gap] = (200, 200, 200)
        x0 += widths[i] + gap
    canvas = _draw_label(canvas, ["原图", "净化输出", "用户标注坏例"], widths, gap, label_h)
    return canvas


def _run_one(task: tuple) -> dict:
    """单张坏例处理：净化→保存PNG→生成三联对比图，异常记录不中断批次"""
    idx, rel, labels, badcase_name, height = task
    t0 = time.time()
    rec: dict = {"idx": idx, "rel": rel.replace("\\", "/"), "labels": list(labels), "ok": False}
    try:
        src = _worker["sample_root"] / rel
        img = load_img(src)
        if img is None:
            rec["error"] = f"decode_failed: {src}"
            return rec
        result = _worker["cleaner"].process(img, debug=False, dpi=300)
        out_img = result["result"]
        out_png = _worker["out"] / png_name(rec["rel"])
        ok, buf = cv2.imencode(".png", out_img)
        if not ok:
            rec["error"] = "encode_png_failed"
            return rec
        buf.tofile(str(out_png))
        badcase_img = load_img(_worker["badcase_dir"] / badcase_name)
        canvas = make_compare3(img, out_img, badcase_img, height)
        cmp_name = png_name(rec["rel"]).replace(".png", "_compare3.jpg")
        ok2, buf2 = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if ok2:
            buf2.tofile(str(_worker["out"] / cmp_name))
            rec["compare3"] = cmp_name
        rec.update(ok=True, ver=_worker["ver"], shape=f"{out_img.shape[1]}x{out_img.shape[0]}",
                   receipt=result.get("is_receipt"), color_receipt=result.get("is_color_receipt"),
                   dt=round(time.time() - t0, 1))
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        import traceback
        rec["tb"] = traceback.format_exc()[-400:]
    return rec


def write_index(out_dir: Path, recs: list[dict]) -> None:
    """生成 index.html 索引页：卡片式三联对比图，点击看大图"""
    cards = []
    for r in sorted(recs, key=lambda x: x.get("idx", 0)):
        if r.get("ok") and r.get("compare3"):
            cap = f"{r['rel']}  [{' / '.join(r['labels'])}]"
            cards.append(
                f'<div style="margin:8px"><a href="{r["compare3"]}"><img src="{r["compare3"]}" width="460" '
                f'alt="{cap}"></a><br><span style="font-size:12px">{cap}</span></div>'
            )
        else:
            cards.append(f'<div style="margin:8px;color:red">✗ {r["rel"]} — {r.get("error", "unknown")}</div>')
    html = (
        '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
        "<title>坏例三联对比（原图｜净化｜标注坏例）</title></head><body>"
        f"<h1>坏例三联对比（{out_dir.name}）</h1>"
        f'<div style="display:flex;flex-wrap:wrap">{"".join(cards)}</div></body></html>'
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="坏例集快速回归（30张，分钟级，研发需求-0139）")
    ap.add_argument("--round", type=int, default=0, help="轮次号（0=修复前基线），仅影响默认输出目录名")
    ap.add_argument("--out", default=None, help="输出目录（默认 ./badcase-output/round-{N}-{日期}）")
    ap.add_argument("--root", default=".", help="项目根（含 backend 包，默认当前目录）")
    ap.add_argument("--sample-dir", default=os.environ.get("DOCSTUDIO_SAMPLE_DIR", "samples"), help="全量样张库根目录")
    ap.add_argument("--badcase-dir", default=os.environ.get("DOCSTUDIO_BADCASE_DIR", "badcase"), help="用户标注坏例目录")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help=">0 时仅处理前 N 张（试跑）")
    ap.add_argument("--label", default=None, help="按问题标注过滤（不区分大小写的包含匹配）")
    ap.add_argument("--height", type=int, default=1200, help="三联对比图高度（像素）")
    args = ap.parse_args()

    items: list[tuple[str, tuple[str, ...], str]] = list(BADCASES)
    if args.label:
        key = args.label.casefold()
        items = [x for x in items if any(key in lb.casefold() for lb in x[1])]
    if args.limit > 0:
        items = items[: args.limit]
    if not items:
        print("[badcase] 过滤后无任务，请检查 --label/--limit")
        return 1

    root = Path(args.root).resolve()
    # zhaoqiaotong 2026-08-30 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化
    # 必须在创建 Pool 之前把项目根加入 sys.path（与 full_test.py 一致）：
    # Windows spawn 子进程继承主进程 sys.path，缺失则 worker 内 import backend 失败并反复重启
    sys.path.insert(0, str(root))
    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = Path("badcase-output") / f"round-{args.round}-{date.today().isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[badcase] 项目根={root} 输出={out_dir} 任务数={len(items)}", flush=True)

    tasks = [(i, rel, labels, bc, args.height) for i, (rel, labels, bc) in enumerate(items)]
    meta_file = out_dir / "meta.jsonl"
    recs: list[dict] = []
    with Pool(args.workers, initializer=_init_worker,
              initargs=(str(root), str(out_dir), args.sample_dir, args.badcase_dir)) as pool, \
            open(meta_file, "w", encoding="utf-8") as mf:
        for rec in pool.imap_unordered(_run_one, tasks, chunksize=1):
            mf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            mf.flush()
            recs.append(rec)
            done = len(recs)
            if done % 5 == 0 or done == len(tasks):
                print(f"[badcase] 进度 {done}/{len(tasks)}", flush=True)

    ok_n = sum(1 for r in recs if r.get("ok"))
    dt_total = round(sum(r.get("dt", 0) for r in recs), 1)
    print(f"[badcase] 完成：成功 {ok_n}/{len(recs)}，总耗时 {dt_total}s")
    if ok_n < len(recs):
        for r in recs:
            if not r.get("ok"):
                print(f"  ✗ {r['rel']} — {r.get('error')}")
    write_index(out_dir, recs)
    print(f"[badcase] meta={meta_file}")
    print(f"[badcase] 索引页={out_dir / 'index.html'}")
    return 0 if ok_n == len(recs) else 2


if __name__ == "__main__":
    raise SystemExit(main())
