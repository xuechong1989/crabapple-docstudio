# -*- coding: utf-8 -*-
"""
海棠文档工坊 - 离线依赖包下载脚本

用于在有网络的 Windows 开发机上，下载目标 Linux 平台的全部依赖包。

使用方法：
    python scripts/download_offline_deps.py --platform linux
    python scripts/download_offline_deps.py --platform linux --cuda 12.8
    python scripts/download_offline_deps.py --platform windows

核心原理：
    1. 生成一份不含 torch/torchvision 的临时 requirements 文件
    2. 用 pip download -r 一次性下载全部依赖（自动解析依赖树）
    3. 单独下载 torch/torchvision（指定平台 + CUDA/CPU）
    4. 单独下载 onnxruntime（确保跨平台正确性）
    5. 验证关键包是否齐全
    6. 清理错误平台包

重要限制：
    跨平台下载（Windows 上下载 Linux 包）时，fallback 不能去掉 --platform，
    否则 pip 会下载当前系统（Windows）的包，导致在 Linux 上无法安装！
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent

# 离线包放在项目目录下（跟代码在一起，不会被 dist 清理掉）
OFFLINE_PACKAGES_DIR = PROJECT_ROOT / 'assets'
# xuechong 2026-08-27 研发需求-0137-图档扫描-3.1.10-目录结构调整以方便备份和管理
# 目录结构调整：linux whl 实际位于 assets/linux/wheels/（与 assets/windows/wheels 对称），windows 侧保持平台根不变
PLATFORM_SUBDIR = {'linux': 'linux/wheels', 'windows': 'windows'}

PYTHON_CMD = sys.executable


def _extract_whl_requires(whl_path: Path) -> list:
    """从 wheel 文件中提取所有 Requires-Dist（忽略 extras 条件）"""
    import zipfile
    deps = []
    try:
        with zipfile.ZipFile(whl_path) as z:
            for name in z.namelist():
                if name.endswith('METADATA'):
                    content = z.read(name).decode('utf-8')
                    for line in content.split('\n'):
                        line = line.strip()
                        if not line.startswith('Requires-Dist:'):
                            continue
                        if 'extra ==' in line:
                            continue  # 跳过 optional extras
                        spec = line.replace('Requires-Dist:', '').strip()
                        parts = spec.split(';')[0].strip()
                        parts = parts.replace('(', '').replace(')', '').replace(' ', '')
                        deps.append(parts)
                    break
    except Exception as e:
        print(f"  [依赖提取] 从 {whl_path.name} 提取 Requires-Dist 失败: {e}")
    return deps


def _extract_torch_nvidia_deps(platform_dir: Path) -> list:
    """
    从已下载的 torch wheel 中提取 Linux 平台的 nvidia-*/triton 依赖。
    返回类似 ['nvidia-cublas-cu12==12.1.3.1', 'triton==3.1.00', ...] 的列表。
    """
    import zipfile
    torch_whls = list(platform_dir.glob('torch-*.whl'))
    if not torch_whls:
        return []
    deps = []
    try:
        with zipfile.ZipFile(torch_whls[0]) as z:
            for name in z.namelist():
                if name.endswith('METADATA'):
                    content = z.read(name).decode('utf-8')
                    for line in content.split('\n'):
                        line = line.strip()
                        if not line.startswith('Requires-Dist:'):
                            continue
                        # 只提取 Linux x86_64 条件的 nvidia-*/triton 包
                        if 'platform_system == "Linux"' not in line:
                            continue
                        # 解析包名和版本
                        spec = line.replace('Requires-Dist:', '').strip()
                        parts = spec.split(';')[0].strip()
                        parts = parts.replace('(', '').replace(')', '').replace(' ', '')
                        deps.append(parts)
                    break
    except Exception as e:
        print(f"    [WARNING] Failed to parse torch wheel: {e}")
    return deps


def run(cmd: str, desc: str = "") -> subprocess.CompletedProcess:
    """执行命令并返回结果"""
    result = subprocess.run(
        cmd, shell=True, capture_output=True,
        text=True, encoding='utf-8', errors='replace',
        timeout=1800
    )
    return result


def _get_linux_platform_args(python_ver: str) -> list:
    """返回 Linux 平台的多种 --platform 参数组合，按优先级排列"""
    return [
        f'--platform manylinux_2_28_x86_64 --python-version {python_ver} --implementation cp --abi cp311 --only-binary=:all:',
        f'--platform manylinux_2_17_x86_64 --python-version {python_ver} --implementation cp --abi cp311 --only-binary=:all:',
        f'--platform manylinux2014_x86_64 --python-version {python_ver} --implementation cp --abi cp311 --only-binary=:all:',
        f'--platform linux_x86_64 --python-version {python_ver} --implementation cp --abi cp311 --only-binary=:all:',
    ]


def _pip_download_with_fallback(pkg_spec: str, platform_dir: Path, platform: str, python_ver: str, no_deps: bool = False, index_url: str = None) -> bool:
    """
    带 fallback 的 pip download，但绝不去掉 --platform（防止下载错误平台包）
    返回 True 表示成功
    """
    no_deps_flag = '--no-deps' if no_deps else ''
    index_flag = f'--index-url {index_url}' if index_url else ''

    if platform == 'linux':
        platform_variants = _get_linux_platform_args(python_ver)
    else:
        platform_variants = [
            f'--platform win_amd64 --python-version {python_ver} --only-binary=:all:',
        ]

    for plat_arg in platform_variants:
        cmd = f'"{PYTHON_CMD}" -m pip download "{pkg_spec}" {no_deps_flag} --dest "{platform_dir}" {index_flag} {plat_arg}'
        r = run(cmd)
        if r.returncode == 0:
            return True

    # 最后尝试纯 Python 包（py3-none-any，跨平台的）
    cmd = f'"{PYTHON_CMD}" -m pip download "{pkg_spec}" {no_deps_flag} --dest "{platform_dir}" {index_flag} --python-version {python_ver} --only-binary=:all: --platform any'
    r = run(cmd)
    return r.returncode == 0


def _clean_wrong_platform(platform_dir: Path, target_platform: str):
    """清理错误平台的 wheel 文件"""
    removed = []
    for whl in platform_dir.glob('*.whl'):
        fname = whl.name.lower()
        if target_platform == 'linux':
            if 'win_amd64' in fname or 'win32' in fname:
                removed.append(whl.name)
                whl.unlink()
        elif target_platform == 'windows':
            if 'manylinux' in fname or 'linux' in fname:
                removed.append(whl.name)
                whl.unlink()
    return removed


def _clean_duplicate_versions(platform_dir: Path):
    """清理同一个包的重复版本（保留最新版本）
    
    例如:
      filelock-3.20.0-py3-none-any.whl
      filelock-3.20.3-py3-none-any.whl
    保留 3.20.3，删除 3.20.0
    """
    import re
    from collections import defaultdict

    # 按包名分组
    pkg_groups = defaultdict(list)
    for whl in platform_dir.glob('*.whl'):
        fname = whl.name
        # 从文件名提取包名（标准化：小写 + 下划线）
        # wheel 命名规范: {name}-{version}(-...)-{python}-{abi}-{platform}.whl
        match = re.match(r'^([a-zA-Z0-9_]+(?:[-_][a-zA-Z0-9_]+)*?)-(\d+[\w.]*)', fname)
        if match:
            pkg_name = match.group(1).lower().replace('-', '_')
            pkg_groups[pkg_name].append(whl)

    removed = []
    for pkg_name, files in pkg_groups.items():
        if len(files) <= 1:
            continue

        # 按文件修改时间排序（最新的在最后）
        files.sort(key=lambda f: f.stat().st_mtime)

        # 如果有平台特定版本（manylinux），优先保留
        platform_specific = [f for f in files if 'manylinux' in f.name or 'linux' in f.name]
        generic = [f for f in files if 'none-any' in f.name]

        if platform_specific and generic:
            # 保留平台特定版本，删除纯 Python 版本
            for f in generic:
                removed.append(f.name)
                f.unlink()
        else:
            # 保留最新（按文件名版本号排序）
            # 简单策略：保留最后下载的
            to_remove = files[:-1]
            for f in to_remove:
                removed.append(f.name)
                f.unlink()

    return removed


def download_packages_for_platform(platform: str, cuda_version: str = None, python_ver: str = '3.11'):
    """下载指定平台的全部依赖包"""
    print(f"\n{'='*70}")
    print(f"  Download {platform} dependencies" + (f" (CUDA {cuda_version})" if cuda_version else " (CPU)") + f" (Python {python_ver})")
    print(f"{'='*70}\n")

    platform_dir = OFFLINE_PACKAGES_DIR / PLATFORM_SUBDIR[platform]
    platform_dir.mkdir(parents=True, exist_ok=True)

    requirements_file = PROJECT_ROOT / 'requirements.txt'
    if not requirements_file.exists():
        print(f"  [ERROR] requirements.txt not found: {requirements_file}")
        return False

    # ==============================================================
    # Step 1: Download PyTorch (separate, needs special index-url)
    # ==============================================================
    print("  [1/5] Download PyTorch + torchvision ...")

    if cuda_version:
        cuda_tag = "cu" + cuda_version.replace(".", "")   # "12.1" -> "cu121"
        torch_index = f"https://download.pytorch.org/whl/{cuda_tag}"
        print(f"         CUDA: {cuda_version}  index: {torch_index}")
    else:
        torch_index = "https://download.pytorch.org/whl/cpu"
        print(f"         CPU  index: {torch_index}")

    # PyTorch CUDA wheel 使用自定义平台标签 (linux_x86_64)，不能用 --platform 过滤
    # 直接用 --index-url + --no-deps 从 CUDA index 下载，pip 自动选择匹配的 wheel
    # 然后验证下载的文件确实是 CUDA 版本（文件名含 +cu）
    torch_ok = True
    for pkg in ['torch', 'torchvision']:
        print(f"    Downloading {pkg} from CUDA index...")
        # 先清理旧版本（避免下载多个版本混淆）
        for old in platform_dir.glob(f'{pkg}-*.whl'):
            old.unlink()

        cmd = f'"{PYTHON_CMD}" -m pip download {pkg} --no-deps --dest "{platform_dir}" --index-url {torch_index} --python-version {python_ver} --platform manylinux2014_x86_64 --implementation cp --abi cp311 --only-binary=:all:'
        r = run(cmd)
        if r.returncode == 0:
            downloaded = [f.name for f in platform_dir.glob(f'{pkg}-*.whl')]
            if downloaded:
                fname = downloaded[0]
                if '+cu' in fname:
                    print(f"    [OK] {fname}")
                else:
                    print(f"    [错误] 下载到 CPU 版本: {fname}")
                    # 删除错误的 CPU 版本
                    for f in platform_dir.glob(f'{pkg}-*.whl'):
                        f.unlink()
                    torch_ok = False
            else:
                print(f"    [OK] {pkg} (下载完成，文件名待确认)")
        else:
            print(f"    [FAIL] {pkg}: {r.stderr[:300]}")
            torch_ok = False

    if not torch_ok:
        print("")
        print("  [错误] torch/torchvision CUDA 版本下载失败！")
        print("  目标服务器需要 GPU 加速版本，CPU 版本无法使用 GPU。")
        print("")
        print("  解决方法：手动下载以下文件，放到 assets/linux/wheels/ 目录：")
        print(f"    1. https://download.pytorch.org/whl/cu128/torch-2.8.0%2Bcu128-cp311-cp311-linux_x86_64.whl")
        print(f"    2. https://download.pytorch.org/whl/cu128/torchvision-0.23.0%2Bcu128-cp311-cp311-linux_x86_64.whl")
        print("  然后删除 CPU 版本文件（manylinux1），重新运行打包。")
        print("")
        return False

    # ==============================================================
    # Step 1.5: Download PyTorch NVIDIA CUDA runtime deps (Linux only)
    # ==============================================================
    if platform == 'linux' and cuda_version:
        print()
        print("  [1.5/5] Download PyTorch CUDA runtime deps ...")

        nvidia_deps = _extract_torch_nvidia_deps(platform_dir)
        if nvidia_deps:
            print(f"    Need {len(nvidia_deps)} NVIDIA/triton packages")
            for dep_spec in nvidia_deps:
                dep_name = dep_spec.split('==')[0].split('>=')[0].strip()
                print(f"    Downloading {dep_spec} ...")
                ok = _pip_download_with_fallback(dep_spec, platform_dir, platform, python_ver, no_deps=True, index_url=torch_index)
                if ok:
                    print(f"    [OK] {dep_name}")
                else:
                    print(f"    [FAIL] {dep_name}")

            # 二级依赖
            print(f"    Checking NVIDIA sub-deps ...")
            sub_deps = set()
            for nv_whl in platform_dir.glob('nvidia_*.whl'):
                for sd in _extract_whl_requires(nv_whl):
                    sd_name = sd.split('==')[0].split('>=')[0].strip()
                    if sd_name.startswith('nvidia-'):
                        sd_lower = sd_name.lower().replace('-', '_')
                        already = any(sd_lower in f.name.lower() for f in platform_dir.iterdir())
                        if not already:
                            sub_deps.add(sd)

            if sub_deps:
                for sd_spec in sub_deps:
                    sd_name = sd_spec.split('==')[0].strip()
                    print(f"    [SUB] {sd_spec} ...")
                    ok = _pip_download_with_fallback(sd_spec, platform_dir, platform, python_ver, no_deps=True, index_url=torch_index)
                    print(f"    [{'OK' if ok else 'FAIL'}] {sd_name}")
            else:
                print(f"    [OK] No missing sub-deps")
        else:
            print("    [SKIP] No torch wheel found or no NVIDIA deps")

    # ==============================================================
    # Step 2: Download all other deps (with full dependency resolution)
    #   CRITICAL: Always specify --platform to avoid downloading Windows packages!
    # ==============================================================
    print()
    print("  [2/5] Download remaining deps (full dependency tree) ...")

    # 生成去掉 torch/torchvision/onnxruntime 的临时 requirements
    with open(requirements_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    tmp_req = platform_dir / '_requirements_no_torch.txt'
    with open(tmp_req, 'w', encoding='utf-8') as f:
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            pkg_name = stripped.split('>=')[0].split('==')[0].split('[')[0].strip().lower()
            # xuechong 2026-10-14 研发需求-0179 口径修正：cython 不排除——内网 Linux 构建机
            # 装 cython 只能靠离线依赖包里的 wheel（装不上就编不了保护模块），必须随包分发
            if pkg_name in ('torch', 'torchvision', 'onnxruntime', 'onnxruntime-gpu'):
                continue
            f.write(stripped + '\n')

    if platform == 'linux':
        plat_arg_general = f'--platform manylinux2014_x86_64 --python-version {python_ver} --implementation cp --abi cp311 --only-binary=:all:'
    else:
        plat_arg_general = f'--platform win_amd64 --python-version {python_ver} --only-binary=:all:'

    # 尝试 1：指定目标平台，only-binary
    cmd = f'"{PYTHON_CMD}" -m pip download -r "{tmp_req}" --dest "{platform_dir}" {plat_arg_general}'
    print(f"    pip download -r requirements (platform={platform}) ...")
    r = run(cmd)

    if r.returncode != 0 and platform == 'linux':
        # 尝试 2：manylinux_2_17（更宽松的兼容性）
        print(f"    [RETRY] manylinux_2_17 ...")
        plat_arg2 = f'--platform manylinux_2_17_x86_64 --python-version {python_ver} --implementation cp --abi cp311 --only-binary=:all:'
        cmd2 = f'"{PYTHON_CMD}" -m pip download -r "{tmp_req}" --dest "{platform_dir}" {plat_arg2}'
        r = run(cmd2)

        if r.returncode != 0:
            # 尝试 3：允许源码包（但仍然限定平台！）
            print(f"    [RETRY] Allow source packages (still Linux platform) ...")
            plat_arg3 = f'--platform manylinux2014_x86_64 --python-version {python_ver} --implementation cp --abi cp311'
            cmd3 = f'"{PYTHON_CMD}" -m pip download -r "{tmp_req}" --dest "{platform_dir}" {plat_arg3}'
            r = run(cmd3)

            if r.returncode != 0:
                print(f"    [WARN] Some packages may have failed: {r.stderr[:300]}")

    # 补充下载纯 Python 包（py3-none-any）：--platform any 不会被 --platform manylinux 匹配到
    print(f"    pip download pure-Python packages (py3-none-any) ...")
    cmd_pure = f'"{PYTHON_CMD}" -m pip download -r "{tmp_req}" --dest "{platform_dir}" --python-version {python_ver} --only-binary=:all: --platform any'
    run(cmd_pure)

    # 清理临时文件
    tmp_req.unlink(missing_ok=True)

    # ==============================================================
    # Step 2.5: Clean up wrong-platform packages + duplicate torch
    # ==============================================================
    print()
    print(f"  [2.5/5] Cleanup: wrong-platform packages & duplicate torch ...")

    # 清理错误平台的包
    removed = _clean_wrong_platform(platform_dir, platform)
    for f in removed:
        print(f"    [REMOVED] {f} (wrong platform)")

    # 清理重复的 torch/torchvision（保留 CUDA 版本）
    if platform == 'linux' and cuda_version:
        cuda_tag = "cu" + cuda_version.replace(".", "")
        for prefix in ['torch-', 'torchvision-']:
            all_pkg = list(platform_dir.glob(f'{prefix}*.whl'))
            if len(all_pkg) > 1:
                # 优先保留 CUDA 版本
                cuda_files = [f for f in all_pkg if cuda_tag in f.name]
                if cuda_files:
                    for f in all_pkg:
                        if f not in cuda_files:
                            print(f"    [REMOVED] {f.name} (non-CUDA duplicate)")
                            f.unlink()
                else:
                    # 没有明确的 CUDA 标记，保留 Linux 版本
                    linux_files = [f for f in all_pkg if 'manylinux' in f.name or 'linux' in f.name]
                    for f in all_pkg:
                        if f not in linux_files:
                            print(f"    [REMOVED] {f.name} (non-Linux duplicate)")
                            f.unlink()

    if not removed:
        print(f"    [OK] No cleanup needed")

    # ==============================================================
    # Step 2.7: Download onnxruntime + onnxruntime-gpu
    #   onnxruntime 是 RapidOCR 的关键依赖，必须确保下载
    #   onnxruntime-gpu 提供 CUDAExecutionProvider，GPU 加速 OCR
    #   ★ onnxruntime-gpu >= 1.19.0 才是 CUDA 12.x 编译！
    #     低于此版本是 CUDA 11 编译，在 CUDA 12 环境会报
    #     libcublasLt.so.11 找不到的错误
    # ==============================================================
    print()
    print("  [2.7/5] Download onnxruntime (CPU) ...")

    # 先下载 onnxruntime (CPU版本，保底)
    ok = _pip_download_with_fallback('onnxruntime', platform_dir, platform, python_ver, no_deps=True)
    if ok:
        ort_files = [f.name for f in platform_dir.glob('onnxruntime-*.whl')]
        print(f"    [OK] onnxruntime: {ort_files[0] if ort_files else '?'}")
    else:
        print(f"    [FAIL] onnxruntime download failed!")

    # CUDA 平台额外下载 onnxruntime-gpu（★必须 >= 1.19.0 才是 CUDA 12 编译★）
    if cuda_version:
        print()
        print("  [2.8/5] Download onnxruntime-gpu >= 1.19.0 (CUDA 12.x GPU OCR) ...")
        ok = _pip_download_with_fallback('onnxruntime-gpu>=1.19.0', platform_dir, platform, python_ver, no_deps=True)
        if ok:
            ort_gpu_files = [f.name for f in platform_dir.glob('onnxruntime_gpu-*.whl')]
            downloaded_name = ort_gpu_files[0] if ort_gpu_files else '?'
            print(f"    [OK] onnxruntime-gpu: {downloaded_name}")
            # 校验版本号确保 >= 1.19（防止缓存旧版本）
            if ort_gpu_files:
                import re
                ver_match = re.search(r'onnxruntime_gpu-(\d+\.\d+)', ort_gpu_files[0])
                if ver_match:
                    ver_parts = ver_match.group(1).split('.')
                    major, minor = int(ver_parts[0]), int(ver_parts[1])
                    if major < 1 or (major == 1 and minor < 19):
                        print(f"    [WARN] 下载的版本 {ver_match.group(1)} < 1.19，这是 CUDA 11 编译版本！")
                        print(f"    [WARN] CUDA 12.x 环境需要 >= 1.19.0，请检查 pip 缓存")
        else:
            print(f"    [WARN] onnxruntime-gpu download failed, OCR will use CPU")

    # ==============================================================
    # Step 3: Validate critical packages
    # ==============================================================
    print()
    print("  [3/5] Validate critical packages ...")

    critical = [
        # Core
        'opencv_python_headless', 'numpy', 'pillow', 'scipy',
        # PyTorch
        'torch', 'torchvision',
        # YOLO
        'doclayout_yolo', 'ultralytics', 'huggingface_hub', 'safetensors',
        # YOLO indirect deps
        'matplotlib', 'pandas', 'seaborn',
        # Web framework
        'fastapi', 'uvicorn', 'watchdog', 'pydantic',
        # OCR
        'rapidocr', 'onnxruntime',
        # OCR indirect deps
        'pyclipper', 'shapely', 'omegaconf', 'colorlog',
        # PDF
        'PyMuPDF', 'reportlab',
        # Utils
        'pyyaml', 'requests', 'tqdm', 'psutil',
    ]
    if cuda_version:
        critical.append('onnxruntime_gpu')

    def _check_pkg(pkg_name, file_list):
        pkg_lower = pkg_name.lower().replace('-', '_')
        pkg_hyphen = pkg_name.lower().replace('_', '-')
        return any(pkg_lower in fn or pkg_hyphen in fn for fn in file_list)

    all_files = [f.name.lower() for f in platform_dir.iterdir() if f.is_file()]
    missing = []
    for pkg in critical:
        if _check_pkg(pkg, all_files):
            pkg_lower = pkg.lower().replace('-', '_')
            matched = [f.name for f in platform_dir.iterdir()
                       if pkg_lower in f.name.lower() or pkg.lower().replace('_', '-') in f.name.lower()]
            print(f"    [OK] {pkg}: {matched[0] if matched else '?'}")
        else:
            missing.append(pkg)
            print(f"    [MISSING!] {pkg}")

    # ==============================================================
    # Step 3.5: Auto-supplement missing critical packages
    # ==============================================================
    if missing:
        print()
        print(f"  [3.5/5] Auto-supplement {len(missing)} missing packages ...")

        still_missing = []
        for pkg in missing:
            pkg_pip = pkg.replace('_', '-')
            print(f"    Downloading {pkg_pip} ...")
            ok = _pip_download_with_fallback(pkg_pip, platform_dir, platform, python_ver, no_deps=False)
            if ok:
                print(f"    [OK] {pkg_pip}")
            else:
                still_missing.append(pkg)
                print(f"    [FAIL] {pkg_pip}")

        missing = still_missing

    # ==============================================================
    # Step 4: Final cleanup
    #   4a. Remove wrong-platform packages
    #   4b. Remove duplicate versions (keep newest)
    # ==============================================================
    print()
    print(f"  [4/5] Final cleanup ...")

    # 4a: 错误平台
    removed = _clean_wrong_platform(platform_dir, platform)
    for f in removed:
        print(f"    [REMOVED] {f} (wrong platform)")

    # 4b: 重复版本
    dup_removed = _clean_duplicate_versions(platform_dir)
    for f in dup_removed:
        print(f"    [REMOVED] {f} (duplicate version)")

    if not removed and not dup_removed:
        print(f"    [OK] No cleanup needed")

    # ==============================================================
    # Step 5: Summary
    # ==============================================================
    whl_files = list(platform_dir.glob('*.whl'))
    tar_files = list(platform_dir.glob('*.tar.gz'))
    total_size = sum(f.stat().st_size for f in platform_dir.iterdir() if f.is_file())

    print()
    print(f"  Downloaded: {len(whl_files)} .whl + {len(tar_files)} source packages")
    print(f"  Total size: {total_size / 1024 / 1024:.1f} MB")
    print(f"  Location:   {platform_dir}")

    if missing:
        print(f"\n  [WARNING] Still missing: {', '.join(missing)}")
        print(f"         Please check network or manually download .whl files")
    else:
        print(f"\n  [SUCCESS] All {len(critical)} critical packages ready!")

    return len(missing) == 0


def create_install_script(platform_dir: Path, platform: str):
    """创建离线安装脚本"""
    if platform == 'linux':
        script = platform_dir / 'install_offline.sh'
        # 必须用 LF 换行符，否则 Linux 上报 "找不到需要的文件"
        with open(script, 'w', encoding='utf-8', newline='\n') as f:
            f.write('''#!/bin/bash
# 离线依赖安装脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "============================================================"
echo "  离线依赖安装"
echo "============================================================"
echo "安装包目录: $SCRIPT_DIR"

# 检查 Python
PYTHON_CMD=""
for cmd in python3.11 python3.10 python3 python; do
    if command -v $cmd &> /dev/null; then
        PYTHON_CMD=$cmd
        break
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    echo "[错误] 找不到 python3"
    exit 1
fi
echo "Python: $($PYTHON_CMD --version 2>&1)"

# 安装方式1：如果有 requirements.txt，用 find-links 安装（pip 自动解析正确版本）
REQ_FILE="$(dirname "$SCRIPT_DIR")/requirements.txt"
if [ -f "$REQ_FILE" ]; then
    echo ""
    echo "[步骤1] pip install -r requirements.txt --find-links ..."
    $PYTHON_CMD -m pip install --no-cache-dir --no-index --find-links="$SCRIPT_DIR" -r "$REQ_FILE" 2>&1 | tee "$SCRIPT_DIR/install.log"
fi

# 安装方式2：逐个安装剩余 wheel（捕获未在 requirements 中的间接依赖）
echo ""
echo "[步骤2] 逐个安装剩余 wheel 包..."
for whl in "$SCRIPT_DIR"/*.whl; do
    $PYTHON_CMD -m pip install --no-cache-dir --no-index --find-links="$SCRIPT_DIR" "$whl" 2>/dev/null || true
done

if ls "$SCRIPT_DIR"/*.tar.gz &>/dev/null; then
    echo ""
    echo "安装源码包..."
    for pkg in "$SCRIPT_DIR"/*.tar.gz; do
        $PYTHON_CMD -m pip install --no-cache-dir --no-index "$pkg" 2>&1 | tee -a "$SCRIPT_DIR/install.log"
    done
fi

echo ""
echo "============================================================"
echo "  安装完成！日志: $SCRIPT_DIR/install.log"
echo "============================================================"
''')
        print(f"  Created install script: {script}")


def _find_whl_by_prefix(platform_dir: Path, prefix: str, exclude: str = None) -> list:
    """在目录中查找指定包名前缀的 whl 文件（忽略大小写）"""
    prefix_lower = prefix.lower().replace('-', '_')
    exc_lower = exclude.lower().replace('-', '_') if exclude else None
    results = []
    for f in platform_dir.glob('*.whl'):
        fname = f.name.lower().replace('-', '_')
        if fname.startswith(prefix_lower):
            if exc_lower and fname.startswith(exc_lower):
                continue
            results.append(f)
    return results


def validate_and_download(platform: str, cuda_version: str = None, python_ver: str = '3.11'):
    """
    增量验证 + 下载模式：
    逐个检查 assets/linux/wheels/（或 windows 平台根）下的关键 whl 文件，
    如果存在且大小完整则跳过，如果缺失或不完整则动态下载。
    不会删除已有的正确文件！
    """
    print()
    print("=" * 70)
    print("  Validate & Download Missing Dependencies")
    print("=" * 70)
    print(f"  Platform:    {platform}")
    print(f"  Python:      {python_ver}")
    print(f"  CUDA:        {cuda_version or 'CPU'}")
    print(f"  Directory:   {OFFLINE_PACKAGES_DIR / PLATFORM_SUBDIR[platform]}")
    print()

    platform_dir = OFFLINE_PACKAGES_DIR / PLATFORM_SUBDIR[platform]
    platform_dir.mkdir(parents=True, exist_ok=True)

    cuda_tag = ("cu" + cuda_version.replace(".", "")) if cuda_version else "cpu"
    torch_index = f"https://download.pytorch.org/whl/{cuda_tag}" if cuda_version else "https://download.pytorch.org/whl/cpu"

    # ============================================================
    # 定义关键包：(显示名, 文件名前缀, 最小大小MB, 下载来源)
    #   文件名前缀用于匹配 whl 文件（忽略大小写，- 和 _ 互通）
    #   最小大小用于判断文件是否完整（太小说明下载不完整）
    #   下载来源: "torch"=PyTorch index, "nvidia"=PyTorch index, "pip"=标准 pip
    # ============================================================
    critical_packages = []

    # PyTorch 核心
    cuda_suffix = cuda_tag if cuda_version else 'cpu'
    critical_packages.append((f'torch+{cuda_suffix}', 'torch-', 750, 'torch', 'torchvision'))
    critical_packages.append((f'torchvision+{cuda_suffix}', 'torchvision-', 5, 'torch'))

    # PyTorch NVIDIA runtime deps (Linux CUDA only)
    if platform == 'linux' and cuda_version:
        nvidia_names = [
            ('nvidia-cublas-cu12', 'nvidia_cublas_cu12', 300, 'nvidia'),
            ('nvidia-cuda-cupti-cu12', 'nvidia_cuda_cupti_cu12', 3, 'nvidia'),
            ('nvidia-cuda-nvrtc-cu12', 'nvidia_cuda_nvrtc_cu12', 80, 'nvidia'),
            ('nvidia-cuda-runtime-cu12', 'nvidia_cuda_runtime_cu12', 1, 'nvidia'),
            ('nvidia-cudnn-cu12', 'nvidia_cudnn_cu12', 600, 'nvidia'),
            ('nvidia-cufft-cu12', 'nvidia_cufft_cu12', 200, 'nvidia'),
            ('nvidia-curand-cu12', 'nvidia_curand_cu12', 60, 'nvidia'),
            ('nvidia-cusolver-cu12', 'nvidia_cusolver_cu12', 150, 'nvidia'),
            ('nvidia-cusparse-cu12', 'nvidia_cusparse_cu12', 4, 'nvidia'),
            ('nvidia-cusparselt-cu12', 'nvidia_cusparselt_cu12', 3, 'nvidia'),
            ('nvidia-nccl-cu12', 'nvidia_nccl_cu12', 300, 'nvidia'),
            ('nvidia-nvjitlink-cu12', 'nvidia_nvjitlink_cu12', 20, 'nvidia'),
            ('triton', 'triton-', 150, 'nvidia'),
        ]
        critical_packages.extend(nvidia_names)

    # Core dependencies
    critical_packages.extend([
        ('opencv-python-headless', 'opencv_python_headless-', 30, 'pip'),
        ('numpy', 'numpy-', 15, 'pip'),
        ('Pillow', 'pillow-', 3, 'pip'),
        ('scipy', 'scipy-', 20, 'pip'),
    ])

    # YOLO
    critical_packages.extend([
        ('doclayout-yolo', 'doclayout_yolo-', 0.5, 'pip'),
        ('ultralytics', 'ultralytics-', 3, 'pip'),
        ('huggingface-hub', 'huggingface_hub-', 3, 'pip'),
        ('safetensors', 'safetensors-', 0.5, 'pip'),
    ])

    # YOLO transitive deps
    critical_packages.extend([
        ('matplotlib', 'matplotlib-', 8, 'pip'),
        ('pandas', 'pandas-', 10, 'pip'),
        ('seaborn', 'seaborn-', 3, 'pip'),
    ])

    # Web framework
    critical_packages.extend([
        ('fastapi', 'fastapi-', 0.05, 'pip'),
        ('uvicorn', 'uvicorn-', 0.01, 'pip'),
        ('watchdog', 'watchdog-', 0.01, 'pip'),
        ('pydantic', 'pydantic-', 0.1, 'pip'),
    ])

    # OCR
    critical_packages.extend([
        ('rapidocr', 'rapidocr', 1, 'pip'),
        ('onnxruntime', 'onnxruntime-', 5, 'pip', 'onnxruntime_gpu'),
    ])
    if cuda_version:
        critical_packages.append(('onnxruntime-gpu', 'onnxruntime_gpu-', 150, 'pip'))

    # OCR transitive deps
    critical_packages.extend([
        ('pyclipper', 'pyclipper-', 0.01, 'pip'),
        ('Shapely', 'shapely-', 0.5, 'pip'),
        ('omegaconf', 'omegaconf-', 0.1, 'pip'),
        ('colorlog', 'colorlog-', 0.01, 'pip'),
        ('six', 'six-', 0.01, 'pip'),
        ('coloredlogs', 'coloredlogs-', 0.01, 'pip'),
        ('flatbuffers', 'flatbuffers-', 0.01, 'pip'),
        ('protobuf', 'protobuf-', 0.1, 'pip'),
    ])

    # PDF
    critical_packages.extend([
        ('reportlab', 'reportlab-', 3, 'pip'),
        ('PyMuPDF', 'pymupdf-', 15, 'pip'),
    ])

    # Utils
    critical_packages.extend([
        ('pyyaml', 'pyyaml-', 0.1, 'pip'),
        ('requests', 'requests-', 0.05, 'pip'),
        ('tqdm', 'tqdm-', 0.05, 'pip'),
        ('psutil', 'psutil-', 0.2, 'pip'),
        ('websockets', 'websockets-', 0.01, 'pip'),
        ('aiofiles', 'aiofiles-', 0.01, 'pip'),
        ('python-multipart', 'python_multipart-', 0.01, 'pip'),
        ('typing-extensions', 'typing_extensions-', 0.01, 'pip'),
        ('py-cpuinfo', 'py_cpuinfo-', 0.01, 'pip'),
        ('ultralytics-thop', 'ultralytics_thop-', 0.01, 'pip'),
    ])

    # ============================================================
    # 逐个验证
    # ============================================================
    skip_count = 0
    download_count = 0
    fail_count = 0
    recheck_count = 0

    for entry in critical_packages:
        display_name = entry[0]
        prefix = entry[1]
        min_size_mb = entry[2]
        source = entry[3]
        exclude = entry[4] if len(entry) > 4 else None

        # 查找匹配的 whl 文件
        matched = _find_whl_by_prefix(platform_dir, prefix, exclude=exclude)

        if matched:
            # 检查文件大小
            largest = max(matched, key=lambda f: f.stat().st_size)
            size_mb = largest.stat().st_size / 1024 / 1024

            if size_mb >= min_size_mb:
                print(f"  [SKIP] {display_name:<35s} {largest.name:<65s} ({size_mb:.1f} MB)")
                skip_count += 1
                continue
            else:
                print(f"  [INCOMPLETE] {display_name:<32s} {largest.name} ({size_mb:.1f} MB < expected {min_size_mb} MB)")
                # 删除不完整的文件，重新下载
                for f in matched:
                    f.unlink()
                recheck_count += 1
        else:
            pass  # 不存在，下面会下载

        # 下载缺失或不完整的包
        print(f"  [DOWNLOAD] {display_name} ...", end=" ", flush=True)
        pkg_pip = prefix.rstrip('-').replace('_', '-')

        if source == 'torch':
            # 从 PyTorch CUDA index 下载
            cmd = f'"{PYTHON_CMD}" -m pip download {pkg_pip} --no-deps --dest "{platform_dir}" --index-url {torch_index} --python-version {python_ver} --platform manylinux2014_x86_64 --implementation cp --abi cp311 --only-binary=:all:'
            r = run(cmd)
            if r.returncode != 0:
                # 尝试 manylinux_2_28
                cmd2 = f'"{PYTHON_CMD}" -m pip download {pkg_pip} --no-deps --dest "{platform_dir}" --index-url {torch_index} --python-version {python_ver} --platform manylinux_2_28_x86_64 --implementation cp --abi cp311 --only-binary=:all:'
                r = run(cmd2)

            # 验证下载结果
            new_matched = _find_whl_by_prefix(platform_dir, prefix)
            if new_matched:
                fname = new_matched[0].name
                if source == 'torch' and '+cu' not in fname and cuda_version:
                    print(f"FAIL (got CPU version: {fname})")
                    for f in new_matched:
                        f.unlink()
                    fail_count += 1
                else:
                    sz = new_matched[0].stat().st_size / 1024 / 1024
                    print(f"OK ({fname}, {sz:.1f} MB)")
                    download_count += 1
            else:
                print(f"FAIL (no file after download)")
                fail_count += 1

        elif source == 'nvidia':
            # NVIDIA runtime 包，从 PyTorch CUDA index 下载
            ok = _pip_download_with_fallback(pkg_pip, platform_dir, platform, python_ver, no_deps=True, index_url=torch_index)
            new_matched = _find_whl_by_prefix(platform_dir, prefix)
            if new_matched and new_matched[0].stat().st_size > 100:
                sz = new_matched[0].stat().st_size / 1024 / 1024
                print(f"OK ({new_matched[0].name}, {sz:.1f} MB)")
                download_count += 1
            elif ok or new_matched:
                # 有文件但可能太小
                if new_matched:
                    sz = new_matched[0].stat().st_size / 1024 / 1024
                    print(f"WARN ({new_matched[0].name}, {sz:.1f} MB - small)")
                    download_count += 1
                else:
                    print(f"FAIL (no file)")
                    fail_count += 1
            else:
                print(f"FAIL")
                fail_count += 1

        else:
            # 标准 pip 下载
            ok = _pip_download_with_fallback(pkg_pip, platform_dir, platform, python_ver, no_deps=True)
            new_matched = _find_whl_by_prefix(platform_dir, prefix)
            if new_matched:
                sz = new_matched[0].stat().st_size / 1024 / 1024
                print(f"OK ({new_matched[0].name}, {sz:.1f} MB)")
                download_count += 1
            else:
                print(f"FAIL (no file)")
                fail_count += 1

    # ============================================================
    # 汇总
    # ============================================================
    print()
    print("=" * 70)
    print(f"  Summary:")
    print(f"    Skip (already complete):  {skip_count}")
    print(f"    Downloaded:               {download_count}")
    print(f"    Incomplete (re-download): {recheck_count}")
    print(f"    Failed:                   {fail_count}")
    print("=" * 70)

    # 统计总量
    whl_files = list(platform_dir.glob('*.whl'))
    total_size = sum(f.stat().st_size for f in whl_files) / 1024 / 1024
    print(f"  Total: {len(whl_files)} whl files, {total_size:.1f} MB")
    print()

    if fail_count > 0:
        print(f"  [ERROR] {fail_count} packages failed to download!")
        print(f"  Check network connection or download manually.")
        print()
        return False

    if len(whl_files) < 50:
        print(f"  [WARNING] Only {len(whl_files)} whl files (expected 80+)")
        print(f"  Some dependencies may be missing.")
        print()

    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Download offline dependencies')
    parser.add_argument('--platform', '-p', choices=['linux', 'windows', 'all'],
                        default='linux', help='Target platform (default: linux)')
    parser.add_argument('--cuda', '-c', default='12.8',
                        help='CUDA version (default: 12.8, set "cpu" for CPU-only)')
    parser.add_argument('--python-version', default='3.11',
                        help='Target Python version (default: 3.11)')
    parser.add_argument('--validate', '-v', action='store_true',
                        help='Validate & download missing only (incremental mode)')
    args = parser.parse_args()

    cuda_version = None if args.cuda.lower() == 'cpu' else args.cuda
    python_ver = args.python_version

    print()
    print("=" * 70)
    print("  Document Scanner - Offline Dependency Downloader")
    print("=" * 70)
    print(f"  Platform:    {args.platform}")
    print(f"  Python:      {python_ver}")
    print(f"  PyTorch:     {'CUDA ' + cuda_version if cuda_version else 'CPU'}")
    print(f"  Output:      {OFFLINE_PACKAGES_DIR}")
    print(f"  Mode:        {'Validate & Download Missing' if args.validate else 'Full Download'}")
    print(f"  Time:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    OFFLINE_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

    platforms = ['linux', 'windows'] if args.platform == 'all' else [args.platform]

    all_ok = True
    for p in platforms:
        if args.validate:
            ok = validate_and_download(p, cuda_version, python_ver)
        else:
            ok = download_packages_for_platform(p, cuda_version, python_ver)
        if not ok:
            all_ok = False
        create_install_script(OFFLINE_PACKAGES_DIR / PLATFORM_SUBDIR[p], p)

    print()
    print("=" * 70)
    if all_ok:
        print("  Download complete!")
    else:
        print("  Download FAILED — see errors above!")
    print("=" * 70)
    print()

    if not all_ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
