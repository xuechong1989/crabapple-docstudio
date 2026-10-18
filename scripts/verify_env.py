# -*- coding: utf-8 -*-
# xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# 迁移环境自检脚本（REQ-004）：内网机迁移/部署后一键体检，只报告不修改
# 用法: python scripts/verify_env.py
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
RESULTS = []


def report(name, level, detail=""):
    # level: PASS / WARN / FAIL
    RESULTS.append((name, level, detail))
    print(f"[{level}] {name}  {detail}")


def check_python():
    v = sys.version_info
    if v[:2] == (3, 11):
        report("Python 版本", "PASS", f"{v.major}.{v.minor}.{v.micro}")
    else:
        report("Python 版本", "FAIL", f"当前 {v.major}.{v.minor}.{v.micro}，要求 3.11.x")


def check_venv_deps():
    missing = []
    versions = {}
    for mod in ("cv2", "torch", "fastapi", "ultralytics", "onnxruntime"):
        try:
            m = __import__(mod)
            versions[mod] = getattr(m, "__version__", "?")
        except Exception as e:
            missing.append(f"{mod}({e.__class__.__name__})")
    if missing:
        report("venv 依赖", "FAIL", "缺失: " + ", ".join(missing))
    else:
        report("venv 依赖", "PASS", f"torch={versions['torch']} cv2={versions['cv2']} "
                                    f"fastapi={versions['fastapi']}")


def check_data_dir():
    conf = PROJECT_ROOT / "url.conf"
    if not conf.exists():
        report("url.conf", "FAIL", "文件不存在")
        return
    win_val = linux_val = None
    for line in conf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DOCSTUDIO_BASE_DIR_WIN="):
            win_val = line.split("=", 1)[1]
        elif line.startswith("DOCSTUDIO_BASE_DIR=") and not line.startswith("DOCSTUDIO_BASE_DIR_WIN"):
            linux_val = line.split("=", 1)[1]
    target = win_val if os.name == "nt" and win_val else linux_val
    if not target:
        report("数据目录配置", "WARN", "url.conf 未配置 DOCSTUDIO_BASE_DIR(_WIN)")
        return
    p = Path(target)
    if p.exists():
        users = p / "users"
        n_users = len(list(users.iterdir())) if users.exists() else 0
        report("数据目录", "PASS", f"{p}（users 下 {n_users} 个用户）")
    else:
        report("数据目录", "WARN", f"{p} 不存在（start.bat 首次启动会自动创建，全新环境属正常）")


def check_stale_paths():
    """扫描 users/**/*.json 中非当前数据根前缀的绝对路径（只报告；REQ-001 服务启动时会自愈）"""
    abs_re = re.compile(r'^([A-Za-z]:[\\/]|/)')
    anchor_re = re.compile(r'/users/([^/]+)/')
    conf_win = None
    for line in (PROJECT_ROOT / "url.conf").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("DOCSTUDIO_BASE_DIR_WIN="):
            conf_win = line.strip().split("=", 1)[1]
    data_root = Path(conf_win or "/data/crabapple-docstudio")
    users_root = data_root / "users"
    stale = []
    scanned = 0
    if users_root.exists():
        for fp in users_root.rglob("*.json"):
            scanned += 1
            try:
                content = fp.read_text(encoding="utf-8")
            except Exception:
                continue
            data = json.loads(content) if content.strip() else None

            def walk(o):
                if isinstance(o, dict):
                    return any(walk(v) for v in o.values())
                if isinstance(o, list):
                    return any(walk(v) for v in o)
                if isinstance(o, str) and abs_re.match(o):
                    norm = o.replace('\\', '/')
                    m = anchor_re.search(norm)
                    if m and not norm.lower().startswith(
                            str(data_root).replace('\\', '/').lower() + '/'):
                        return True
                return False

            if data is not None and walk(data):
                stale.append(str(fp))
    if scanned == 0:
        report("陈旧路径扫描", "PASS", "无持久化 JSON（全新环境）")
    elif stale:
        report("陈旧路径扫描", "WARN",
               f"{len(stale)}/{scanned} 个文件含旧前缀绝对路径，服务启动时 REQ-001 将自动自愈："
               + "; ".join(stale[:3]) + ("..." if len(stale) > 3 else ""))
    else:
        report("陈旧路径扫描", "PASS", f"已扫描 {scanned} 个 JSON，无旧前缀路径")


def check_models_and_frontend():
    models = list((PROJECT_ROOT / "assets" / "models").glob("*.pt")) if (PROJECT_ROOT / "assets" / "models").exists() else []
    if models:
        report("YOLO 模型", "PASS", f"{len(models)} 个: " + ", ".join(m.name for m in models[:3]))
    else:
        report("YOLO 模型", "FAIL", "assets/models/ 下无 .pt 模型文件")
    dist = PROJECT_ROOT / "frontend" / "dist" / "index.html"
    report("前端构建产物", "PASS" if dist.exists() else "WARN",
           "frontend/dist 存在" if dist.exists() else "frontend/dist 缺失（无 Node.js 环境将无法出页面，需从联网机带来）")


def main():
    print(f"=== 迁移环境自检 === 项目根: {PROJECT_ROOT}\n")
    check_python()
    check_venv_deps()
    check_data_dir()
    check_stale_paths()
    check_models_and_frontend()
    n_fail = sum(1 for _, lv, _ in RESULTS if lv == "FAIL")
    n_warn = sum(1 for _, lv, _ in RESULTS if lv == "WARN")
    print(f"\n=== 汇总: {len(RESULTS)} 项，FAIL {n_fail}，WARN {n_warn} ===")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
