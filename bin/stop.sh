#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 设置 UTF-8 编码环境
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

echo "============================================================"
echo "  海棠文档工坊 - 停止服务"
echo "============================================================"
echo ""

FOUND=0

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

# 工具函数：通过进程名查找PID列表
find_pids_by_name() {
    local pattern="$1"
    local pids=""
    if command -v pgrep &> /dev/null; then
        pids=$(pgrep -f "$pattern" 2>/dev/null)
    else
        pids=$(ps -ef | grep -v grep | grep -F "$pattern" | awk '{print $2}')
    fi
    echo "$pids"
}

# 方法1: 通过端口查找进程
echo "[1/2] 检查端口 8000..."
PIDS=$(find_pids_by_port 8000)
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo "  发现进程 PID: $PID"
        kill -9 "$PID" 2>/dev/null
        echo "  已停止进程 $PID"
        FOUND=1
    done
fi

# 方法2: 通过进程名查找
echo ""
echo "[2/2] 检查 Python 服务进程..."
PIDS=$(find_pids_by_name "start_server.py")
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo "  发现 Python 进程 PID: $PID"
        kill -9 "$PID" 2>/dev/null
        echo "  已停止进程 $PID"
        FOUND=1
    done
fi

# 等待进程结束
echo ""
echo "等待进程结束..."
sleep 2

# 验证端口是否释放
echo ""
echo "验证端口状态..."
if [ -n "$(find_pids_by_port 8000)" ]; then
    echo ""
    echo "  [警告] 端口 8000 仍被占用!"
    echo "  请使用 'kill -9 PID' 手动结束相关进程"
else
    echo "  端口 8000 已释放"
    echo ""
    echo "============================================================"
    echo "  服务已停止 (浏览器窗口保持打开)"
    echo "============================================================"
fi

echo ""
printf "按回车键关闭..."
read
