# -*- coding: utf-8 -*-
# xuechong 2026-07-20 研发BUG-0009 大文件拆分：OCR 引擎缓存（从 __init__.py 提取）
"""OCR 引擎创建与缓存（页面方向检测、OCR 文字保护共用）"""

import os

from . import _log
from .gpu import _check_cuda_available, _setup_cuda_jit_cache

# OCR引擎缓存（用于方向检测，避免每次创建新引擎）
_orientation_ocr_cache = {}
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 cleaner OCR 运行级失败标志
# 与 ocr_rapid.py 的 _ort_gpu_runtime_failed 联动
_cleaner_ocr_gpu_failed = False


def _get_cached_ocr_engine(det_limit: int):
    """获取缓存的OCR引擎用于方向检测

    ★ GPU 强制使用策略 ★
    规则：只要检测到 GPU + CUDA 可用，就必须使用 GPU，不存在降级 CPU。
    首次启动可能因 CUDA JIT 编译需要等待数分钟，耐心等待即可，
    编译结果会缓存到工程外部目录，下次启动秒加载。

    仅在以下情况使用 CPU：
    - 机器没有 GPU
    - CUDA 驱动未安装
    - onnxruntime-gpu 未安装（缺少 CUDAExecutionProvider）
    """
    global _orientation_ocr_cache
    cache_key = f"orientation_{det_limit}"

    if cache_key not in _orientation_ocr_cache:
        cuda_ok = _check_cuda_available()

        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 三层验证：①包级 ②列表级
        ort_cuda = False
        if cuda_ok:
            try:
                import onnxruntime as ort
                ort_ver = ort.__version__
                ort_device = ort.get_device()
                providers = ort.get_available_providers()
                # ①包级：get_device() == "GPU"
                if ort_device != "GPU":
                    _log(f"  [OCR] onnxruntime {ort_ver} device={ort_device}（包级验证失败，非 GPU 包）")
                    ort_cuda = False
                else:
                    # ②列表级：CUDAExecutionProvider
                    ort_cuda = 'CUDAExecutionProvider' in providers
                    _log(f"  [OCR] onnxruntime {ort_ver}, device={ort_device}, providers: {providers}")

                if ort_cuda:
                    # ★ 关键检查：onnxruntime-gpu 版本是否匹配 CUDA 12.x ★
                    try:
                        ver_parts = [int(x) for x in ort_ver.split('.')[:2]]
                        if ver_parts[0] < 1 or (ver_parts[0] == 1 and ver_parts[1] < 19):
                            _log(f"  [OCR] ⚠⚠⚠ onnxruntime-gpu {ort_ver} 是 CUDA 11 编译版本！")
                            _log(f"  [OCR] ⚠ 当前 PyTorch 使用 CUDA 12.x，但 onnxruntime-gpu < 1.19 需要 CUDA 11")
                            _log(f"  [OCR] ⚠ 会导致 'libcublasLt.so.11 not found' 错误，CUDA 加速无效")
                            _log(f"  [OCR] ⚠ 解决：安装 onnxruntime-gpu >= 1.19.0（pip install onnxruntime-gpu>=1.19.0）")
                            _log(f"  [OCR] ⚠ 强制使用 CPU 模式，避免 CUDA 库版本不匹配导致失败")
                            ort_cuda = False  # 版本不对，不用 GPU
                    except (ValueError, IndexError) as e:
                        _log(f"  [OCR] onnxruntime 版本解析失败: {e}")
                else:
                    _log(f"  [OCR] ⚠ onnxruntime 未安装 GPU 版本（缺少 CUDAExecutionProvider）")
                    _log(f"  [OCR] ⚠ 解决：安装 onnxruntime-gpu >= 1.19.0")
            except ImportError:
                _log(f"  [OCR] onnxruntime 未安装")
            except Exception as e:
                _log(f"  [OCR] onnxruntime 检测异常: {e}")

        use_gpu = cuda_ok and ort_cuda

        if use_gpu:
            # ============================================================
            # ★ GPU 模式（强制）：检测到 CUDA 就必须用 GPU ★
            # ============================================================
            _log(f"  [OCR] ★ 检测到 GPU + CUDA，强制使用 GPU 模式 ★")

            # 设置 CUDA JIT 缓存到工程外部（跨版本持久化）
            _setup_cuda_jit_cache()

            try:
                from rapidocr import RapidOCR
                engine = RapidOCR(params={
                    "Global.log_level": "error",
                    "Det.limit_side_len": det_limit,
                    "Det.limit_type": "max",
                    # ★ 启用 CUDA + HEURISTIC 算法搜索（比默认 EXHAUSTIVE 快得多）★
                    "EngineConfig.onnxruntime.use_cuda": True,
                    "EngineConfig.onnxruntime.cuda_ep_cfg.device_id": 0,
                    "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC",
                    "EngineConfig.onnxruntime.cuda_ep_cfg.do_copy_in_default_stream": True,
                    # 限制 OCR 占用的 GPU 显存，避免与 YOLO 争抢
                    "EngineConfig.onnxruntime.cuda_ep_cfg.gpu_mem_limit": 4 * 1024 * 1024 * 1024,
                })

                # ★ 预热推理（不设超时，等待完成）★
                # 首次 CUDA JIT 编译可能需要几分钟，这是正常现象
                # 编译结果会缓存到磁盘，下次启动秒加载
                _log(f"  [OCR] GPU 预热推理开始...")
                _log(f"  [OCR] （首次 CUDA JIT 编译可能需要 1-3 分钟，请耐心等待，编译结果会缓存到磁盘）")

                import time as _time
                t_start = _time.time()

                import numpy as _np
                _dummy = _np.zeros((64, 64, 3), dtype=_np.uint8)
                try:
                    engine(_dummy)
                except Exception as warmup_e:
                    _log(f"  [OCR] 预热时小异常（不影响后续使用）: {warmup_e}")

                elapsed = _time.time() - t_start
                _orientation_ocr_cache[cache_key] = engine
                _log(f"  [OCR缓存] ✓ GPU 引擎预热完成，耗时 {elapsed:.1f}s (det_limit={det_limit}, 设备: GPU)")
                _log(f"  [OCR缓存] ★ 后续 OCR 推理将使用 GPU 加速 ★")

            except Exception as e:
                # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 REQ-007 运行级失败回退 CPU（不再 raise）
                _log(f"  [OCR] ✗ GPU 引擎创建/预热失败（运行级验证失败）: {e}")
                import traceback
                _log(f"  [OCR] {traceback.format_exc()}")
                _log(f"  [OCR] → 回退 CPU 模式（保证方向检测功能可用）")
                use_gpu = False  # 降级标志
                # 同步全局标志：通知 ocr_rapid.py 的 detect_ort_gpu() 也返回 False
                global _cleaner_ocr_gpu_failed
                _cleaner_ocr_gpu_failed = True
                try:
                    from backend.ocr_rapid import _ort_gpu_runtime_failed
                    import backend.ocr_rapid as _ocr_mod
                    _ocr_mod._ort_gpu_runtime_failed = True
                except Exception:
                    pass

        if not use_gpu:
            # ============================================================
            # CPU 模式（仅当机器没有 GPU/CUDA 时）
            # ============================================================
            _log(f"  [OCR] 当前环境无 GPU/CUDA，使用 CPU 模式")

            # 屏蔽 GPU，防止 onnxruntime-gpu 意外尝试 CUDA
            saved_cuda_env = os.environ.get("CUDA_VISIBLE_DEVICES")
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

            try:
                from rapidocr import RapidOCR
                engine = RapidOCR(params={
                    "Global.log_level": "error",
                    "Det.limit_side_len": det_limit,
                    "Det.limit_type": "max"
                })
                # CPU 预热
                import numpy as _np
                _dummy = _np.zeros((64, 64, 3), dtype=_np.uint8)
                try:
                    engine(_dummy)
                except Exception as warmup_e:
                    _log(f"  [OCR缓存] 预热推理失败 (非致命): {warmup_e}")
                _orientation_ocr_cache[cache_key] = engine
                _log(f"  [OCR缓存] 创建方向检测引擎完成 (det_limit={det_limit}, 设备: CPU)")
            except Exception as e:
                _log(f"  [OCR缓存] ✗ RapidOCR 引擎创建失败: {e}")
                raise
            finally:
                if saved_cuda_env is not None:
                    os.environ["CUDA_VISIBLE_DEVICES"] = saved_cuda_env
                elif "CUDA_VISIBLE_DEVICES" in os.environ:
                    del os.environ["CUDA_VISIBLE_DEVICES"]

    return _orientation_ocr_cache[cache_key]
