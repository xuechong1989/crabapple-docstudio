#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 设置 UTF-8 编码环境
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

echo "============================================================"
echo "  海棠文档工坊 - 启动服务"
echo "============================================================"
echo ""

# 工具函数：获取占用端口的PID列表
find_pids_by_port() {
    local port="$1"
    local pids=""
    if command -v lsof &> /dev/null; then
        pids=$(lsof -t -i:"$port" 2>/dev/null)
    elif command -v ss &> /dev/null; then
        pids=$(ss -tlnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $NF}' | grep -o 'pid=[0-9]\+' | cut -d= -f2 | sort -u)
    elif command -v netstat &> /dev/null; then
        pids=$(netstat -tlnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $7}' | cut -d/ -f1 | sort -u)
    fi
    echo "$pids"
}

# 切换到项目根目录（脚本在 bin 目录下，需要返回上层）
cd "$(dirname "$0")/.."
echo "当前目录: $(pwd)"

# 优先加载 url.conf 路径配置（在 Python 检测前，确保 DOCSTUDIO_PYTHON 生效）
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$SCRIPT_DIR/url.conf" ]; then
    set -a
    . "$SCRIPT_DIR/url.conf"
    set +a
    echo "  已加载 url.conf 路径配置"
fi
echo ""

# 检查并停止已运行的服务
echo "[1/8] 检查是否有已运行的服务..."
PIDS=$(find_pids_by_port 8000)
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo "  发现端口8000被占用，正在停止旧服务 PID: $PID"
        kill -9 "$PID" 2>/dev/null
    done
    sleep 2
fi
echo "  端口8000已就绪"
echo ""

# 检测 Python
echo "[2/8] 检测Python环境..."

if [ -n "$DOCSTUDIO_PYTHON" ] && [ -x "$DOCSTUDIO_PYTHON" ]; then
    PYTHON_CMD="$DOCSTUDIO_PYTHON"
    echo "  使用: $DOCSTUDIO_PYTHON"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    echo "  使用系统Python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
    echo "  使用系统Python"
else
    echo ""
    echo "============================================================"
    echo "  [错误] 找不到Python环境!"
    echo "============================================================"
    echo ""
    echo "  请安装 Python 3.11+"
    echo ""
    printf "按回车键退出..."
    read
    exit 1
fi
echo ""

# 检查虚拟环境（不自动创建/下载）
echo "[3/8] 检查Python虚拟环境..."
VENV_DIR="${DOCSTUDIO_VENV_DIR:-.venv}"
if [ -f "$VENV_DIR/bin/activate" ]; then
    # shellcheck disable=SC1090
    . "$VENV_DIR/bin/activate"
    echo "  已激活虚拟环境: $VENV_DIR"
    PYTHON_CMD="python"
else
    echo "  [提示] 未检测到虚拟环境，将使用系统Python"
fi
echo ""

# 系统依赖检测（不在线安装）
echo "[4/8] 检查系统依赖..."
if ! command -v dnf &> /dev/null; then
    echo "  [提示] 未检测到 dnf，无法检查系统依赖"
else
    echo "  [提示] 启动不会在线安装系统依赖，请确保已预装依赖包"
fi
echo ""

# xuechong 2026-07-03 检查前端构建产物（优先自动构建，node 不可用时使用已有 dist）
echo "[5/8] 检查前端构建产物..."
FRONTEND_STALE=0
if [ -d "frontend/dist" ]; then
    # 检查源码是否比 dist 新（有源码变更但未重建）
    NEWEST_SRC=$(find frontend/src -type f -name '*.vue' -o -name '*.js' -o -name '*.css' 2>/dev/null | xargs -r stat -c '%Y' 2>/dev/null | sort -rn | head -1)
    NEWEST_DIST=$(find frontend/dist -type f -name '*.js' -o -name '*.css' 2>/dev/null | xargs -r stat -c '%Y' 2>/dev/null | sort -rn | head -1)
    if [ -n "$NEWEST_SRC" ] && [ -n "$NEWEST_DIST" ] && [ "$NEWEST_SRC" -gt "$NEWEST_DIST" ]; then
        FRONTEND_STALE=1
        echo "  [警告] 前端源码有更新，dist 已过期"
    else
        echo "  前端构建产物已就绪"
    fi
fi

# 尝试自动构建前端（node/npm 可用时）
if [ ! -d "frontend/dist" ] || [ "$FRONTEND_STALE" -eq 1 ]; then
    if command -v node &>/dev/null && command -v npm &>/dev/null; then
        echo "  检测到 Node.js，自动构建前端..."
        cd frontend
        if [ ! -d "node_modules" ]; then
            echo "  安装前端依赖..."
            npm install --no-audit --no-fund 2>&1 | tail -1
        fi
        if npm run build 2>&1 | tail -3; then
            echo "  前端构建成功"
        else
            echo "  [错误] 前端构建失败！请检查 frontend/ 目录"
            cd ..
        fi
        cd ..
    else
        if [ ! -d "frontend/dist" ]; then
            echo "  [错误] 未找到 frontend/dist 且 Node.js 不可用，无法构建前端！"
            echo "  请先在开发机上打包后再部署，或安装 Node.js 18+"
            printf "按回车键退出..."
            read
            exit 1
        else
            echo "  [警告] Node.js 不可用，将使用已有 dist（可能不是最新版本）"
        fi
    fi
fi
echo ""

# 检查 Python 依赖（不在线安装）
echo "[6/8] 检查Python依赖..."
"$PYTHON_CMD" - <<'PY' >/dev/null 2>&1
import importlib.util as iu
mods = ["cv2", "rapidocr", "fitz", "torch", "doclayout_yolo", "uvicorn", "fastapi", "numpy", "PIL"]
missing = [m for m in mods if iu.find_spec(m) is None]
raise SystemExit(1 if missing else 0)
PY
if [ $? -ne 0 ]; then
    echo "  [错误] Python依赖不完整，启动将失败"
    echo "  请使用打包版本或离线安装完整依赖后再启动"
    printf "按回车键退出..."
    read
    exit 1
else
    echo "  Python依赖已满足"
fi
echo ""

echo "[7/8] 检查目录结构..."
BASE_DIR="${DOCSTUDIO_BASE_DIR:-${DOCSTUDIO_DATA_DIR:-/data/crabapple-docstudio}}"
export DOCSTUDIO_BASE_DIR="$BASE_DIR"
export DOCSTUDIO_DATA_DIR="$BASE_DIR"
export HF_HOME="$BASE_DIR/cache/huggingface"
export TORCH_HOME="$BASE_DIR/cache/torch"
export CUDA_CACHE_PATH="$BASE_DIR/cache/cuda"
export MPLCONFIGDIR="$BASE_DIR/cache/matplotlib"
export ULTRALYTICS_CONFIG_DIR="$BASE_DIR/cache/ultralytics"
mkdir -p "$BASE_DIR" \
    "$BASE_DIR/data/original" "$BASE_DIR/data/target" \
    "$BASE_DIR/logs" "$BASE_DIR/tmp" "$BASE_DIR/plugins" \
    "$BASE_DIR/cache/huggingface" "$BASE_DIR/cache/torch" \
    "$BASE_DIR/cache/cuda" "$BASE_DIR/cache/matplotlib" \
    "$BASE_DIR/cache/ultralytics"
echo "  目录结构已就绪"
echo ""

# 启动服务
echo "[8/8] 启动服务..."
echo ""

if [ ! -f "start_server.py" ]; then
    echo "  [错误] 找不到 start_server.py!"
    echo "  当前目录: $(pwd)"
    echo ""
    printf "按回车键退出..."
    read
    exit 1
fi

echo "============================================================"
echo "  服务即将启动，日志将显示在下方"
echo "  按 Ctrl+C 可以停止服务"
echo "============================================================"
echo ""

# PaddlePaddle 优化设置（解决 CPU 环境兼容性问题）
export FLAGS_use_mkldnn=0
export FLAGS_pir_apply_shape_optimization_pass=0
export FLAGS_enable_pir_api=0
export FLAGS_enable_pir_in_executor=0
export FLAGS_enable_pir_with_pt_in_dy2st=0
export FLAGS_pir_apply_inplace_pass=0

# 提高文件描述符限制（默认1024远不够图像/PDF并发处理需求）
ulimit -n 65536

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-017 日志轮转说明
# server.py 已内置 _RotatingLogFile（500MB/份 x 10份自动轮转）：
#   前台运行（本脚本）：日志同时显示终端 + 写入 $BASE_DIR/logs/crabapple-docstudio.log
#   后台运行（nohup/systemd）：日志仅写入文件（自动轮转，不依赖 shell 重定向）
# 若需要额外的系统级轮转，参考 bin/crabapple-docstudio.logrotate
# 直接运行，日志显示在当前窗口
$PYTHON_CMD start_server.py

# 如果服务退出
echo ""
echo "============================================================"
echo "  服务已停止"
echo "============================================================"
echo ""
printf "按回车键关闭..."
read
