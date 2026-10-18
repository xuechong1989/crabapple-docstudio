# -*- coding: utf-8 -*-
"""海棠文档工坊 - 服务启动入口（薄封装）

向后兼容入口。核心逻辑在 backend/server.py。
也可通过以下方式启动：
    python -m backend
    crabapple-docstudio-server
"""
# xuechong 2026-08-17 研发BUG-0023-图档扫描-3.1.04-双环境防护提示
# 非 bin\start.bat（项目 .venv）直接运行时（如 PATH 中的系统 python start_server.py）醒目提示，
# 避免双环境依赖版本分叉导致的行为差异（如 opencv 5/4 API 不一致事故）；仅 Windows 检测，
# Linux 生产环境经 url.conf 的 DOCSTUDIO_PYTHON 多路径启动，不适用本检测
import sys
from pathlib import Path

if sys.platform == "win32":
    _venv_python = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
    if _venv_python.exists() and Path(sys.executable).resolve() != _venv_python.resolve():
        print("=" * 60)
        print("  [警告] 当前未使用项目虚拟环境运行，依赖版本可能与已锁定环境不一致！")
        print(f"  当前解释器: {sys.executable}")
        print(f"  项目环境:   {_venv_python}")
        print("  推荐双击 bin\\start.bat 启动（自动使用项目 .venv）")
        print("=" * 60)

from backend.server import main

if __name__ == "__main__":
    main()
