# -*- coding: utf-8 -*-
"""
海棠文档工坊 - 服务启动模块
同时启动后端 API 服务和前端静态文件服务

位于 backend/ 包内，入口点为 main() 函数。
可用方式启动：
    python start_server.py           # 根目录薄封装
    python -m backend             # 标准 Python 模块方式
    crabapple-docstudio-server                # pip install -e . 后控制台命令
"""

import os
import sys

# PaddlePaddle 环境变量（必须在导入 paddle 之前设置）
os.environ.setdefault('FLAGS_use_mkldnn', '0')
os.environ.setdefault('FLAGS_pir_apply_shape_optimization_pass', '0')
os.environ.setdefault('FLAGS_enable_pir_api', '0')
os.environ.setdefault('FLAGS_enable_pir_in_executor', '0')
os.environ.setdefault('FLAGS_enable_pir_with_pt_in_dy2st', '0')
os.environ.setdefault('FLAGS_pir_apply_inplace_pass', '0')
import logging
import webbrowser
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import TextIO

def _log(msg: str):
    """带时间戳的日志输出（格式：年-月-日 时:分:秒.毫秒）"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {msg}", flush=True)

# 设置控制台编码
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception as e:
        sys.stderr.write(f"[编码设置] stdout UTF-8 设置失败: {e}\n")

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-017 日志轮转 stdout/stderr 替代流（500MB/份 x 10份）
class _RotatingLogFile:
    """支持大小轮转的 stdout/stderr 替代流。

    - tty 模式（前台运行）：同时写入终端 + 轮转文件
    - 非 tty 模式（nohup/systemd 后台）：仅写入轮转文件（避免与 shell 重定向双写）
    - 超过 max_bytes 自动轮转，保留 backup_count 份历史
    """

    def __init__(self, original: "TextIO", log_path: Path,
                 max_bytes: int = 500 * 1024 * 1024, backup_count: int = 10):
        self._original = original
        self._log_path = Path(log_path)
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._is_tty = hasattr(original, "isatty") and original.isatty()
        # 日志流自身异常时降级到原始 stderr 提示（仅首次，避免刷屏）
        self._warned_fallback = False
        self._f = open(self._log_path, "a", encoding="utf-8", errors="replace")

    def _warn(self, msg: str) -> None:
        """日志流内部异常降级提示（写入原始 stderr，仅首次）"""
        if self._warned_fallback:
            return
        self._warned_fallback = True
        try:
            self._original.write(f"[日志轮转] {msg}\n")
            self._original.flush()
        except Exception:
            pass

    def _rotate(self) -> None:
        """日志轮转：当前→.1, .1→.2, ..., .{n-1}→.{n}, .{n}删除"""
        try:
            self._f.close()
        except Exception as e:
            self._warn(f"关闭旧日志文件失败: {e}")
        name = str(self._log_path)
        try:
            oldest = f"{name}.{self._backup_count}"
            if os.path.exists(oldest):
                os.remove(oldest)
            for i in range(self._backup_count - 1, 0, -1):
                src = f"{name}.{i}"
                dst = f"{name}.{i + 1}"
                if os.path.exists(src):
                    os.rename(src, dst)
            if os.path.exists(name):
                os.rename(name, f"{name}.1")
        except Exception as e:
            self._warn(f"轮转日志文件失败: {e}")
        self._f = open(self._log_path, "a", encoding="utf-8", errors="replace")

    def write(self, text: str) -> int:
        if not text:
            return 0
        # tty 模式下同时写入终端
        if self._is_tty:
            try:
                self._original.write(text)
            except Exception as e:
                self._warn(f"终端写入失败: {e}")
        # 写入轮转文件并检查大小
        try:
            self._f.write(text)
            if self._f.tell() >= self._max_bytes:
                self._rotate()
        except Exception as e:
            self._warn(f"日志文件写入失败: {e}")
        return len(text)

    def flush(self) -> None:
        if self._is_tty:
            try:
                self._original.flush()
            except Exception as e:
                self._warn(f"终端 flush 失败: {e}")
        try:
            self._f.flush()
        except Exception as e:
            self._warn(f"日志文件 flush 失败: {e}")

    def isatty(self) -> bool:
        return self._is_tty

    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", "utf-8")

    @property
    def errors(self) -> str:
        return getattr(self._original, "errors", "replace")

    def reconfigure(self, **kwargs) -> None:
        """转发到原始流（不影响文件写入编码，始终 utf-8）"""
        try:
            self._original.reconfigure(**kwargs)
        except Exception as e:
            self._warn(f"reconfigure 转发失败（不影响文件写入）: {e}")

    def __getattr__(self, name: str):
        """未显式实现的方法转发到原始流"""
        return getattr(self._original, name)

class EndpointFilter(logging.Filter):
    """过滤掉特定端点的访问日志（uvicorn.access 过滤器）"""
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        filtered_paths = [
            '/api/dual-layer/progress',
            '/api/progress',
            '/health',
            '/api/health',
        ]
        for path in filtered_paths:
            if path in message:
                return False
        return True


def _get_storage_root():
    """获取存储根目录（从 url.conf 派生，config.py 已初始化）"""
    from . import config as _cfg
    path = Path(str(_cfg.DATA_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path

def main():
    # 获取项目路径（从 backend/ 向上一级到项目根目录）
    base_dir = Path(__file__).parent.parent

    # 添加项目路径
    sys.path.insert(0, str(base_dir))
    
    storage_root = _get_storage_root()

    data_dir = storage_root / "data"
    logs_dir = storage_root / "logs"
    tmp_dir = storage_root / "tmp"
    plugins_dir = storage_root / "plugins"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "original").mkdir(parents=True, exist_ok=True)
    (data_dir / "target").mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir.mkdir(parents=True, exist_ok=True)

    # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-017 日志轮转：替换 stdout/stderr 为轮转文件流
    # 生产环境 8.7GB 日志无限增长问题修复（500MB/份, 保留 10 份, 自动轮转）
    # tty 模式同时写终端；非 tty（nohup/systemd）仅写文件，避免与 shell 重定向双写
    _log_file = logs_dir / "crabapple-docstudio.log"
    sys.stdout = _RotatingLogFile(sys.stdout, _log_file)
    sys.stderr = _RotatingLogFile(sys.stderr, _log_file)

    # 检查核心依赖（离线环境不联网安装，给出明确提示）
    _missing_deps = []
    for _mod_name, _pkg_name in [("uvicorn", "uvicorn"), ("fastapi", "fastapi"), ("cv2", "opencv-python"),
                                  ("numpy", "numpy"), ("PIL", "Pillow"), ("fitz", "PyMuPDF")]:
        try:
            __import__(_mod_name)
        except ImportError:
            _missing_deps.append(_pkg_name)
    
    if _missing_deps:
        _log("=" * 60)
        _log("  [错误] 缺少必要依赖，无法启动！")
        _log(f"  缺失: {', '.join(_missing_deps)}")
        _log("")
        _log("  离线环境请执行:")
        _log(f"    {sys.executable} -m pip install --no-cache-dir --no-index \\")
        _log(f"      --find-links=assets assets/linux/wheels/*.whl")
        _log("")
        _log("  联网环境请执行:")
        _log(f"    {sys.executable} -m pip install -r requirements.txt")
        _log("=" * 60)
        sys.exit(1)
    
    # 依赖检查通过，正式导入（确保后续代码可用）
    import uvicorn
    
    # ================================================================
    # GPU 硬件检测（启动时打印摘要，GPU 优先）
    # ================================================================
    _log("=" * 60)
    _log("  [硬件环境检测]")
    _log("=" * 60)
    _log(f"  Python:   {sys.version.split()[0]}")
    _log(f"  平台:     {sys.platform}")
    
    # PyTorch + CUDA 检测
    torch_cuda_ok = False
    try:
        import torch
        _log(f"  PyTorch:  {torch.__version__}")
        _log(f"  CUDA编译: {torch.version.cuda or 'CPU版本(无CUDA)'}")
        _log(f"  CUDA_VISIBLE_DEVICES: {os.environ.get('CUDA_VISIBLE_DEVICES', '(未设置)')}")
        _log(f"  LD_LIBRARY_PATH: {os.environ.get('LD_LIBRARY_PATH', '(未设置)')}")
        if torch.cuda.is_available():
            torch_cuda_ok = True
            gpu_count = torch.cuda.device_count()
            _log(f"  GPU 数量: {gpu_count}")
            for i in range(gpu_count):
                name = torch.cuda.get_device_name(i)
                _props = torch.cuda.get_device_properties(i)
                mem_gb = (getattr(_props, 'total_memory', 0) or getattr(_props, 'total_mem', 0)) / (1024**3)
                _log(f"  GPU {i}:    {name} ({mem_gb:.1f} GB)")
            _log(f"  ★ YOLO 修图: GPU 加速已启用 ✓")
        else:
            _log(f"  CUDA:     ✗ 不可用 (torch.cuda.is_available()=False)")
            if not torch.version.cuda:
                _log(f"  ✗ 原因: 安装的是 CPU 版 PyTorch，缺少 CUDA 支持")
                _log(f"  ✗ 解决: 离线包需包含 CUDA 版 PyTorch (如 torch+cu128)")
            else:
                _log(f"  ✗ PyTorch 有 CUDA {torch.version.cuda} 支持，但 CUDA 运行时不可用")
                _log(f"  ✗ 请检查:")
                _log(f"    1. nvidia-smi 是否正常运行")
                _log(f"    2. LD_LIBRARY_PATH 是否包含 /usr/local/cuda/lib64")
                _log(f"    3. libcudart.so 是否存在")
                # 运行 nvidia-smi 辅助诊断
                try:
                    import subprocess
                    result = subprocess.run(['nvidia-smi', '--query-gpu=driver_version,name,memory.total',
                                           '--format=csv,noheader'], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        _log(f"  nvidia-smi: {result.stdout.strip()}")
                    else:
                        _log(f"  nvidia-smi 失败: {result.stderr.strip()}")
                except Exception as nv_e:
                    _log(f"  nvidia-smi 不可用: {nv_e}")
            _log(f"  ★ YOLO 修图: CPU 模式（速度较慢）")
    except ImportError:
        _log(f"  PyTorch:  未安装")
    except Exception as e:
        _log(f"  PyTorch:  检测异常 ({e})")
    
    # ONNX Runtime 检测（RapidOCR 依赖）
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if 'CUDAExecutionProvider' in providers and torch_cuda_ok:
            _log(f"  ONNX RT:  {ort.__version__} (GPU CUDA 加速)")
            _log(f"  ★ OCR 识别: GPU 加速已启用 ✓")
        elif 'CUDAExecutionProvider' in providers and not torch_cuda_ok:
            _log(f"  ONNX RT:  {ort.__version__} (有CUDA支持但PyTorch CUDA不可用)")
            _log(f"  ⚠ OCR 识别: onnxruntime 有 CUDA 支持但 PyTorch CUDA 不可用，请检查驱动/环境配置")
        else:
            _log(f"  ONNX RT:  {ort.__version__} (CPU)")
            _log(f"  ★ OCR 识别: CPU 模式（机器无GPU或未安装onnxruntime-gpu）")
    except ImportError:
        _log(f"  ONNX RT:  未安装")
    except Exception as e:
        _log(f"  ONNX RT:  检测异常: {e}")
    
    _log("=" * 60)
    
    # 服务配置
    host = "0.0.0.0"
    port = 8000
    
    # 服务地址直接通过 init_storage_dirs 传递，不依赖环境变量

    # 加载后端应用
    try:
        from backend.app import app, init_storage_dirs
        _log("  后端模块加载成功")
    except ImportError as e:
        _log(f"  无法加载后端模块: {e}")
        sys.exit(1)
    
    # 重新初始化存储目录
    init_storage_dirs(host, port)

    # xuechong 2026-08-17 研发BUG-0023-图档扫描-3.1.04-SPA子路由404修复
    # 此处原有裸 StaticFiles 挂载先于 app.py lifespan 的 SPAStaticFiles（带 index.html 兜底）注册，
    # 导致 /login、/edit-pdf 等前端路由直访/刷新返回 404（V3.1.00 的 SPA 修复因此从未生效）；
    # 前端挂载统一由 app.py mount_frontend() 在服务启动时执行，此处不再重复挂载

    _log("=" * 60)
    _log("  [海棠文档工坊] Web 服务")
    _log("=" * 60)
    _log("")
    _log(f"  [API]  后端接口:  http://localhost:{port}/api")
    _log(f"  [WEB]  前端界面:  http://localhost:{port}")
    _log("")
    _log("  按 Ctrl+C 停止服务")
    _log("=" * 60)
    
    # 延迟打开浏览器
    if not os.environ.get("NO_BROWSER"):
        def open_browser():
            time.sleep(2)
            webbrowser.open(f"http://localhost:{port}")
        
        threading.Thread(target=open_browser, daemon=True).start()
    
    # 为 uvicorn.access 添加过滤器
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.addFilter(EndpointFilter())
    
    # 启动服务（超时配置为1小时=3600秒）
    uvicorn.run(
        app, 
        host=host, 
        port=port, 
        log_level="info",
        timeout_keep_alive=3600,  # Keep-alive 超时1小时
        limit_concurrency=100     # 并发限制
    )

if __name__ == "__main__":
    main()
