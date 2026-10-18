# -*- coding: utf-8 -*-
"""
依赖包打包脚本 —— 将离线依赖包打包为独立的 tar.gz

使用方法：
    python scripts/pack_deps.py

输出：
    crabapple-docstudio-deps-v{VERSION}.tar.gz（仅含离线 wheel 文件 + 安装脚本）

说明：
    依赖包只打一次，部署到服务器后长期不变。每次版本更新只打包程序包（pack_release.py）。
"""

import sys
import shutil
import tarfile
import re
from pathlib import Path
from datetime import datetime

# 从 url.conf 加载磁盘路径配置
_url_conf = {}
_conf_path = Path(__file__).parent.parent / "url.conf"
if _conf_path.exists():
    for _line in _conf_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k, _v = _k.strip(), _v.strip()
        for _ref in _url_conf:
            _v = _v.replace(f"${{{_ref}}}", _url_conf[_ref])
        _url_conf[_k] = _v

PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / 'frontend'


def get_version_from_frontend():
    """从前端 package.json 或 pages/HomePage.vue 中动态读取版本号"""
    pkg_json = FRONTEND_DIR / 'package.json'
    if pkg_json.exists():
        import json as _json
        try:
            pkg = _json.loads(pkg_json.read_text(encoding='utf-8'))
            if 'version' in pkg:
                return pkg['version']
        except Exception:
            pass
    home_vue_path = FRONTEND_DIR / 'src' / 'pages' / 'HomePage.vue'
    if home_vue_path.exists():
        content = home_vue_path.read_text(encoding='utf-8')
        match = re.search(r'>V(\d+\.\d+\.\d+)<', content)
        if match:
            return match.group(1)
    return "1.0.0"


VERSION = get_version_from_frontend()


# 路径常量（打包脚本仅在 Windows 上运行，直接读 _WIN 变量）
_DATA_DIR = Path(_url_conf.get("DOCSTUDIO_BASE_DIR_WIN", str(PROJECT_ROOT / "data"))).resolve()
DIST_DIR = Path(_url_conf.get("DOCSTUDIO_DIST_DIR_WIN", str(_DATA_DIR / "dist"))).resolve()
DIST_DIR.mkdir(parents=True, exist_ok=True)


def write_unix_text(filepath: Path, content: str):
    """写入文件时强制使用 Unix 换行符 (LF)"""
    with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)


def print_header(title):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def find_offline_packages():
    """查找离线包目录"""
    candidates = [
        DIST_DIR / 'assets' / 'linux' / 'wheels',
        PROJECT_ROOT / 'assets' / 'linux' / 'wheels',
        PROJECT_ROOT.parent / 'dist' / 'assets' / 'linux' / 'wheels',
    ]
    best = None
    best_count = 0
    for path in candidates:
        if path.exists():
            count = len(list(path.glob('*.whl')))
            if count > best_count:
                best = path
                best_count = count
    return best


def create_install_script(deps_dir: Path):
    """生成依赖安装脚本 install_deps.sh"""
    script_content = r'''#!/bin/bash
# 文档扫描系统 - 离线依赖安装脚本
# 本脚本在服务器上执行一次即可，安装后依赖包长期不变

set -e

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WHEELS_DIR="$SCRIPT_DIR/wheels"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "============================================================"
echo "  文档扫描系统 - 离线依赖安装"
echo "============================================================"
echo ""

# [1/5] 检测 Python 3.11
echo "[1/5] 检测 Python 环境..."
PYTHON_CMD=""

for cmd in python3.11 /usr/local/bin/python3.11 /usr/bin/python3.11 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        if [ "$VER" = "3.11" ]; then
            PYTHON_CMD="$cmd"
            echo "  找到 Python 3.11: $cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "  [错误] 找不到 Python 3.11！"
    echo "  请先安装: sudo dnf install python3.11 python3.11-venv python3.11-pip"
    exit 1
fi
echo ""

# [2/5] 创建虚拟环境
echo "[2/5] 创建 Python 虚拟环境..."
if [ -f "$VENV_DIR/bin/python3" ]; then
    echo "  虚拟环境已存在: $VENV_DIR"
    echo "  如需重建，请先删除: rm -rf $VENV_DIR"
else
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    echo "  [成功] 虚拟环境已创建: $VENV_DIR"
fi
echo ""

# [3/5] 激活虚拟环境
echo "[3/5] 激活虚拟环境..."
source "$VENV_DIR/bin/activate"
PYTHON_CMD="python"
echo "  Python: $(python --version 2>&1)"
echo "  Pip:    $(pip --version 2>&1)"
echo ""

# [4/5] 安装依赖（逐个安装，跳过版本解析，已装过的自动跳过）
echo "[4/5] 从离线包安装依赖..."
if [ ! -d "$WHEELS_DIR" ]; then
    echo "  [错误] 离线包目录不存在: $WHEELS_DIR"
    exit 1
fi

WHL_COUNT=$(ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | wc -l)
echo "  离线包数量: $WHL_COUNT"
echo "  安装中（可能需要几分钟）..."

INSTALLED=0
SKIPPED=0
FAILED=0
TOTAL=$WHL_COUNT
IDX=0
for whl in "$WHEELS_DIR"/*.whl; do
    fname=$(basename "$whl")
    IDX=$((IDX + 1))

    # 从文件名提取包名（whl 格式: 包名-版本-...）
    pkg_name=$(echo "$fname" | sed 's/-[0-9].*//' | tr '_' '-')

    # 先检查是否已安装（pip show 找到就跳过）
    if pip show "$pkg_name" >/dev/null 2>&1; then
        echo "  [$IDX/$TOTAL] $fname [已安装，跳过]"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    echo "  [$IDX/$TOTAL] $fname [安装中...]"
    output=$(pip install --no-cache-dir --no-deps "$whl" 2>&1)
    if echo "$output" | grep -qiE "(Successfully installed|already satisfied)"; then
        INSTALLED=$((INSTALLED + 1))
    else
        FAILED=$((FAILED + 1))
        echo "    [FAIL] 安装失败"
    fi
done
echo "  完成: 新安装 $INSTALLED, 已存在跳过 $SKIPPED, 失败 $FAILED"
echo ""

# [5/5] 验证所有依赖模块（一个都不能少）
echo "[5/5] 验证所有依赖模块..."
CRITICAL_MODS=(
    "cv2"
    "numpy"
    "PIL"
    "scipy"
    "fitz"
    "torch"
    "torchvision"
    "doclayout_yolo"
    "ultralytics"
    "huggingface_hub"
    "safetensors"
    "matplotlib"
    "pandas"
    "seaborn"
    "fastapi"
    "uvicorn"
    "python_multipart"
    "watchdog"
    "websockets"
    "aiofiles"
    "rapidocr"
    "onnxruntime"
    "pyclipper"
    "shapely"
    "omegaconf"
    "colorlog"
    "six"
    "coloredlogs"
    "flatbuffers"
    "google.protobuf"
    "reportlab"
    "pyyaml"
    "requests"
    "tqdm"
    "psutil"
    "pydantic"
    "typing_extensions"
    "albumentations"
)
FAIL_LIST=""
for mod in "${CRITICAL_MODS[@]}"; do
    if python -c "import $mod" 2>/dev/null; then
        echo "  $mod: OK"
    else
        echo "  $mod: [缺失]"
        FAIL_LIST="$FAIL_LIST $mod"
    fi
done
echo ""

if [ -z "$FAIL_LIST" ]; then
    echo "============================================================"
    echo "  全部依赖验证通过！"
    echo "  虚拟环境: $VENV_DIR"
    echo ""
    echo "  下一步：启动程序包中的 start.sh"
    echo "    cd ../crabapple-docstudio-v*"
    echo "    ./start.sh"
    echo "============================================================"
else
    echo "============================================================"
    echo "  [错误] 以下模块缺失，安装不完整！"
    echo "  缺失模块:$FAIL_LIST"
    echo ""
    echo "  请检查离线包中对应的 .whl 文件是否存在"
    echo "============================================================"
    exit 1
fi
'''
    script_path = deps_dir / 'install_deps.sh'
    write_unix_text(script_path, script_content)
    script_path.chmod(0o755)
    return script_path


def pack_deps():
    """主函数：打包依赖包"""
    print()
    print("=" * 70)
    print("  依赖包打包工具")
    print("=" * 70)
    print(f"  版本: V{VERSION}")
    print(f"  日期: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"  项目: {PROJECT_ROOT}")
    print(f"  输出: {DIST_DIR}")
    print()

    # 1. 查找离线包
    print_header("步骤 1/3: 查找离线包")
    offline_src = find_offline_packages()
    if not offline_src:
        print("  [错误] 未找到离线包目录！")
        print()
        print("  已搜索的路径:")
        candidates = [
            DIST_DIR / 'assets' / 'linux' / 'wheels',
            PROJECT_ROOT / 'assets' / 'linux' / 'wheels',
            PROJECT_ROOT.parent / 'dist' / 'assets' / 'linux' / 'wheels',
        ]
        for p in candidates:
            exists = p.exists()
            count = len(list(p.glob('*.whl'))) if exists else 0
            size_mb = sum(f.stat().st_size for f in p.glob('*.whl')) / 1024 / 1024 if count > 0 else 0
            status = "[OK]" if count > 0 else ("[empty]" if exists else "[--]")
            print(f"    {status} {p} ({count} whl, {size_mb:.0f} MB)")
        print()
        print("  请先运行: python scripts/download_offline_deps.py --platform linux --cuda 12.8 --python-version 3.11")
        return False

    whl_count = len(list(offline_src.glob('*.whl')))
    total_size = sum(f.stat().st_size for f in offline_src.glob('*.whl'))
    total_size_mb = total_size / 1024 / 1024
    print(f"  找到 {whl_count} 个 wheel 文件 ({total_size_mb:.1f} MB)")
    print(f"  路径: {offline_src}")
    # 打印前5个和后5个文件名，方便诊断
    all_whls = sorted(offline_src.glob('*.whl'))
    if all_whls:
        print(f"  前5个: {', '.join(w.name for w in all_whls[:5])}")
        if len(all_whls) > 5:
            print(f"  后5个: {', '.join(w.name for w in all_whls[-5:])}")

    if whl_count < 50:
        print()
        print(f"  [错误] wheel 文件数量不足（仅 {whl_count} 个，正常应有 80+ 个）！")
        print(f"  离线包可能不完整，请重新下载:")
        print(f"    python scripts/download_offline_deps.py --platform linux --cuda 12.8 --python-version 3.11")
        return False

    if total_size_mb < 500:
        print()
        print(f"  [警告] 离线包总大小异常（{total_size_mb:.1f} MB，正常应有 800+ MB）")
        print(f"  可能缺少大型依赖（torch、nvidia-*、onnxruntime-gpu 等）")
        print(f"  建议重新下载完整离线包")

    # 2. 准备输出目录
    print_header("步骤 2/3: 准备打包目录")
    folder_name = "dependence"
    staging_dir = DIST_DIR / folder_name

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    # 复制 wheel 文件到 wheels/ 子目录
    wheels_dest = staging_dir / 'wheels'
    shutil.copytree(offline_src, wheels_dest)
    copied = len(list(wheels_dest.glob('*.whl')))
    copied_size = sum(f.stat().st_size for f in wheels_dest.glob('*.whl'))
    print(f"  已复制 {copied} 个 wheel 文件 ({copied_size / 1024 / 1024:.1f} MB) 到 {wheels_dest}")

    # 生成安装脚本
    install_script = create_install_script(staging_dir)
    print(f"  已生成安装脚本: {install_script}")

    # 复制 requirements.txt（安装脚本需要引用）
    req_src = PROJECT_ROOT / 'requirements.txt'
    if req_src.exists():
        shutil.copy(req_src, staging_dir / 'requirements.txt')
        print(f"  已复制 requirements.txt")

    # 3. 打包
    print_header("步骤 3/3: 创建压缩包")
    tar_name = f"crabapple-docstudio-deps-v{VERSION}.tar.gz"
    tar_path = DIST_DIR / tar_name

    with tarfile.open(tar_path, 'w:gz') as tar:
        tar.add(staging_dir, arcname=folder_name)

    tar_size = tar_path.stat().st_size / (1024 * 1024)
    print(f"  [成功] {tar_name} ({tar_size:.1f} MB)")

    # 清理临时目录
    shutil.rmtree(staging_dir)

    # 完成
    print()
    print("=" * 70)
    print("  依赖包打包完成!")
    print("=" * 70)
    print()
    print(f"  输出: {tar_path}")
    print()
    print("  服务器部署步骤:")
    print(f"    1. 上传 {tar_name} 到服务器")
    print(f"    2. tar -xzf {tar_name}")
    print(f"    3. cd dependence")
    print(f"    4. chmod +x install_deps.sh")
    print(f"    5. ./install_deps.sh")
    print(f"    6. cd .. && mv dependence /data/crabapple-docstudio/dependence")
    print()

    return True


if __name__ == '__main__':
    try:
        success = pack_deps()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n用户取消操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
