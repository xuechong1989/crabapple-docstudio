#!/bin/bash
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
echo "  安装中（已装过的会跳过）..."

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
