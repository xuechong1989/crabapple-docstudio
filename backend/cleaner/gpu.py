# -*- coding: utf-8 -*-
# xuechong 2026-07-20 研发BUG-0009 大文件拆分：GPU/CUDA 检测函数（从 __init__.py 提取）
"""GPU/CUDA 可用性检测与 YOLO 设备选择"""

import os

from backend import config as cfg
from . import _log

# CUDA 可用性全局状态（由 get_yolo_device 检测后共享给 OCR）
_cuda_verified = None  # None=未检测, True=可用, False=不可用


def _set_cuda_unavailable():
    """标记 CUDA 不可用（YOLO GPU 初始化/推理回退 CPU 时调用，同步状态给 OCR）

    xuechong 2026-07-20 修复：原 core.py 中 `global _cuda_verified` 写的是 core
    模块自己的命名空间，对本模块状态无效；提取后统一由本函数更新。
    """
    global _cuda_verified
    _cuda_verified = False


def _check_cuda_available():
    """检查 CUDA 是否真正可用（结果缓存，全局共享）

    会输出详细的诊断信息，帮助定位 GPU 不可用的原因。
    """
    global _cuda_verified
    if _cuda_verified is not None:
        return _cuda_verified

    _log("  [CUDA诊断] 开始检测 CUDA 可用性...")

    try:
        import torch
        _log(f"  [CUDA诊断] PyTorch 版本: {torch.__version__}")
        _log(f"  [CUDA诊断] PyTorch CUDA 编译版本: {torch.version.cuda or '无 (CPU版本!)'}")

        if not torch.version.cuda:
            _log(f"  [CUDA诊断] ✗✗✗ 严重: 安装的 PyTorch 是 CPU 版本，不含 CUDA 支持 ✗✗✗")
            _log(f"  [CUDA诊断] 解决方案: 离线包需要包含 CUDA 版 PyTorch (如 torch+cu128)")
            _cuda_verified = False
            return _cuda_verified

        _log(f"  [CUDA诊断] cuDNN: {'可用 v' + str(torch.backends.cudnn.version()) if torch.backends.cudnn.is_available() else '不可用'}")
        _log(f"  [CUDA诊断] CUDA_VISIBLE_DEVICES = {os.environ.get('CUDA_VISIBLE_DEVICES', '(未设置)')}")
        _log(f"  [CUDA诊断] LD_LIBRARY_PATH = {os.environ.get('LD_LIBRARY_PATH', '(未设置)')}")

        _cuda_verified = torch.cuda.is_available()

        if _cuda_verified:
            gpu_count = torch.cuda.device_count()
            for i in range(gpu_count):
                name = torch.cuda.get_device_name(i)
                props = torch.cuda.get_device_properties(i)
                mem = (getattr(props, 'total_memory', 0) or getattr(props, 'total_mem', 0)) / (1024**3)
                _log(f"  [CUDA诊断] ✓ GPU {i}: {name} ({mem:.1f} GB)")
            _log(f"  [CUDA诊断] ✓ CUDA 可用，共 {gpu_count} 块 GPU")
        else:
            _log(f"  [CUDA诊断] ✗ torch.cuda.is_available() = False")
            _log(f"  [CUDA诊断] ✗ PyTorch 有 CUDA {torch.version.cuda} 编译支持，但运行时不可用")
            _log(f"  [CUDA诊断] ✗ 可能原因:")
            _log(f"  [CUDA诊断]   1. NVIDIA 驱动未安装或版本过低 (需要 >= CUDA {torch.version.cuda} 对应驱动)")
            _log(f"  [CUDA诊断]   2. libcudart.so 未找到 (检查 LD_LIBRARY_PATH)")
            _log(f"  [CUDA诊断]   3. /usr/local/cuda/lib64 目录不存在")
            _log(f"  [CUDA诊断]   4. CUDA_VISIBLE_DEVICES 被设置为无效值")
            # 运行 nvidia-smi 获取驱动信息
            try:
                import subprocess
                result = subprocess.run(
                    ['nvidia-smi', '--query-gpu=driver_version,name,memory.total', '--format=csv,noheader'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().split('\n'):
                        _log(f"  [CUDA诊断] nvidia-smi: {line.strip()}")
                    _log(f"  [CUDA诊断] → 驱动正常，GPU 存在，问题在 CUDA 运行时库")
                else:
                    _log(f"  [CUDA诊断] nvidia-smi 失败 (returncode={result.returncode}): {result.stderr.strip()}")
                    _log(f"  [CUDA诊断] → NVIDIA 驱动可能未安装")
            except FileNotFoundError:
                _log(f"  [CUDA诊断] nvidia-smi 命令不存在，NVIDIA 驱动未安装")
            except Exception as nv_e:
                _log(f"  [CUDA诊断] nvidia-smi 执行异常: {nv_e}")
            # 检查关键 CUDA 库文件
            cuda_lib_paths = [
                '/usr/local/cuda/lib64/libcudart.so',
                '/usr/local/cuda-13.2/lib64/libcudart.so',
                '/usr/local/cuda-12.8/lib64/libcudart.so',
                '/usr/local/cuda-12/lib64/libcudart.so',
                '/usr/lib64/libcudart.so',
            ]
            found_any = False
            for lib_path in cuda_lib_paths:
                if os.path.exists(lib_path):
                    _log(f"  [CUDA诊断] ✓ 找到: {lib_path}")
                    found_any = True
            if not found_any:
                _log(f"  [CUDA诊断] ✗ 未找到 libcudart.so! 这是 CUDA 不可用的直接原因")
                _log(f"  [CUDA诊断] ✗ 解决: 安装 CUDA Toolkit 或设置 LD_LIBRARY_PATH 指向 CUDA 库目录")
    except ImportError:
        _log(f"  [CUDA诊断] ✗ PyTorch 未安装!")
        _cuda_verified = False
    except Exception as e:
        _log(f"  [CUDA诊断] ✗ 检测异常: {e}")
        import traceback
        _log(f"  [CUDA诊断] {traceback.format_exc()}")
        _cuda_verified = False

    return _cuda_verified


def _setup_cuda_jit_cache():
    """确保 CUDA JIT 编译缓存目录存在（环境变量已由 config.py 设置）"""
    cache_dir = str(cfg.CUDA_CACHE_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    _log(f"  [CUDA缓存] JIT 编译缓存目录: {cache_dir}")


def get_yolo_device():
    """获取 YOLO 运行设备（GPU 优先，无 GPU 则回退 CPU）

    同时更新全局 _cuda_verified 状态，供 OCR 模块共享。
    """
    global _cuda_verified
    device_override = cfg.YOLO_DEVICE or os.environ.get("DOCSTUDIO_YOLO_DEVICE", "")
    use_gpu = cfg.USE_GPU and cfg._is_truthy_env(os.environ.get("DOCSTUDIO_USE_GPU", "1"))

    if device_override:
        if device_override.lower() == "cpu":
            _cuda_verified = False
            return "cpu", "forced cpu by env"
        _cuda_verified = True
        return device_override, f"forced device={device_override} by env"

    if not use_gpu:
        _cuda_verified = False
        return "cpu", "gpu disabled by DOCSTUDIO_USE_GPU=0"

    try:
        import torch
        _log(f"  [GPU诊断] PyTorch 版本: {torch.__version__}")
        _log(f"  [GPU诊断] CUDA 编译版本: {torch.version.cuda or '无(CPU版本)'}")
        _log(f"  [GPU诊断] cuDNN 版本: {torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else '不可用'}")
        _log(f"  [GPU诊断] CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', '(未设置)')}")
        _log(f"  [GPU诊断] LD_LIBRARY_PATH={os.environ.get('LD_LIBRARY_PATH', '(未设置)')}")

        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            # 列出所有 GPU 信息
            for i in range(gpu_count):
                name = torch.cuda.get_device_name(i)
                props = torch.cuda.get_device_properties(i)
                mem = (getattr(props, 'total_memory', 0) or getattr(props, 'total_mem', 0)) / (1024**3)
                _log(f"  [GPU {i}] {name} ({mem:.1f} GB)")

            # 默认使用 cuda:0（可通过 DOCSTUDIO_YOLO_DEVICE 覆盖）
            default_device = "cuda:0"
            gpu_name = torch.cuda.get_device_name(0)
            _props0 = torch.cuda.get_device_properties(0)
            gpu_mem = (getattr(_props0, 'total_memory', 0) or getattr(_props0, 'total_mem', 0)) / (1024**3)
            _cuda_verified = True
            return default_device, f"{gpu_count}x GPU detected, using GPU 0: {gpu_name} ({gpu_mem:.1f}GB)"
        else:
            _cuda_verified = False
            _log("  [GPU] ✗ torch.cuda.is_available() = False")
            if not torch.version.cuda:
                _log("  [GPU] ✗ 原因: 安装的是 CPU 版 PyTorch（缺少 CUDA 支持）")
                _log("  [GPU] ✗ 解决: 需要安装 CUDA 版 PyTorch，如 torch+cu128")
            else:
                _log(f"  [GPU] ✗ PyTorch 编译的 CUDA 版本: {torch.version.cuda}")
                _log("  [GPU] ✗ 可能原因:")
                _log("  [GPU]   1. NVIDIA 驱动未安装或版本过低")
                _log("  [GPU]   2. CUDA 运行时库 (libcudart.so) 未找到")
                _log("  [GPU]   3. LD_LIBRARY_PATH 未包含 CUDA 库路径")
                _log("  [GPU]   4. 请运行 nvidia-smi 检查驱动状态")
                # 尝试运行 nvidia-smi 获取更多信息
                try:
                    import subprocess
                    result = subprocess.run(['nvidia-smi', '--query-gpu=driver_version,name,memory.total', '--format=csv,noheader'],
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        _log(f"  [GPU] nvidia-smi 输出: {result.stdout.strip()}")
                    else:
                        _log(f"  [GPU] nvidia-smi 失败: {result.stderr.strip()}")
                except Exception as nv_e:
                    _log(f"  [GPU] nvidia-smi 不可用: {nv_e}")
    except ImportError:
        _cuda_verified = False
        _log("  [GPU] PyTorch 未安装，无法使用 GPU")
    except Exception as e:
        _cuda_verified = False
        _log(f"  [GPU] GPU 检测异常: {e}")

    return "cpu", "cuda unavailable, using CPU"
