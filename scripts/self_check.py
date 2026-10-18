# -*- coding: utf-8 -*-
"""
海棠文档工坊 - 全面自检脚本

模拟欧拉/Linux 离线部署环境，在打包前自动检测所有潜在问题：
  1.  Python 语法编译检查（所有 .py 文件）
  2.  函数签名 vs 调用一致性（flush=True 等非法参数）
  3.  变量引用完整性（NameError 预防）
  4.  import 依赖 vs requirements.txt 交叉验证
  5.  .sh 脚本换行符检查（必须 LF，不能 CRLF）
  6.  运行时联网操作检测（离线环境禁止）
  7.  离线包完整性验证
  8.  离线包平台一致性（win_amd64 不应混入 linux 目录）
  9.  torch CUDA 版本验证
  10. 日志函数格式一致性检查
  11. GPU 组件 CUDA 版本一致性校验
  12. 离线包重复版本检测
  13. 包内导入完整性检查（裸 import vs from . import）
  14. 包目录树完整性检查
  15. url.conf 路径配置验证
  16. 入口点和控制台命令验证
  17. 前端构建一致性检查

使用方法：
    python scripts/self_check.py            # 完整自检
    python scripts/self_check.py --fix      # 自检并自动修复可修复项

每次打包前务必运行，节省 2 小时的上传和调试时间！
"""

import os
import sys
import re
import py_compile
from pathlib import Path
from datetime import datetime

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 Windows GBK 控制台不支持 Unicode 符号（✓ 等）
# 强制 stdout/stderr 使用 utf-8 编码，避免 UnicodeEncodeError
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

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

# ============================================================
# 颜色输出（Windows 兼容）
# ============================================================
try:
    os.system('')  # 启用 ANSI 转义序列
except Exception as e:
    print(f"[自检] ANSI 转义序列启用失败: {e}", file=sys.stderr)

def RED(s): return f"\033[91m{s}\033[0m"
def GREEN(s): return f"\033[92m{s}\033[0m"
def YELLOW(s): return f"\033[93m{s}\033[0m"
def CYAN(s): return f"\033[96m{s}\033[0m"
def BOLD(s): return f"\033[1m{s}\033[0m"

# ============================================================
# 状态计数
# ============================================================
_pass_count = 0
_fail_count = 0
_warn_count = 0
_errors = []  # (文件, 行号, 错误描述)
_auto_fixed = []  # 自动修复的问题


def PASS(msg):
    global _pass_count
    _pass_count += 1
    print(f"  {GREEN('[PASS]')} {msg}")

def FAIL(msg, file="", line=0):
    global _fail_count
    _fail_count += 1
    _errors.append((file, line, msg))
    loc = f" ({file}:{line})" if file else ""
    print(f"  {RED('[FAIL]')} {msg}{loc}")

def WARN(msg, file="", line=0):
    global _warn_count
    _warn_count += 1
    loc = f" ({file}:{line})" if file else ""
    print(f"  {YELLOW('[WARN]')} {msg}{loc}")

def INFO(msg):
    print(f"  {CYAN('[INFO]')} {msg}")


# ============================================================
# 核心业务文件列表（打包会包含的）
# ============================================================
CORE_FILES = [
    'start_server.py',
    'backend/__init__.py',
    'backend/__main__.py',
    'backend/config.py',
    'backend/cleaner/__init__.py',
    'backend/app.py',
    'backend/ocr_rapid.py',
    'backend/ocr_pdf.py',
    'backend/server.py',
    'backend/service_manager.py',
]

SCRIPT_FILES = [
    'scripts/download_offline_deps.py',
    'scripts/pack_release.py',
    'scripts/pack_deps.py',
    'scripts/self_check.py',
]


def get_all_core_py_files():
    """获取所有核心 Python 文件（排除 tests/build/debug 等）"""
    files = []
    for f in CORE_FILES + SCRIPT_FILES:
        p = PROJECT_ROOT / f
        if p.exists():
            files.append(p)
    return files


def section_header(num, total, title):
    print()
    print(BOLD(CYAN("=" * 60)))
    print(BOLD(CYAN(f"  [{num}/{total}] {title}")))
    print(BOLD(CYAN("=" * 60)))


TOTAL_CHECKS = 17


# ============================================================
# 检查 1: Python 语法编译
# ============================================================
def check_syntax():
    section_header(1, TOTAL_CHECKS, "Python 语法编译检查")
    files = get_all_core_py_files()
    for f in files:
        rel = f.relative_to(PROJECT_ROOT)
        try:
            py_compile.compile(str(f), doraise=True)
            PASS(f"{rel}")
        except py_compile.PyCompileError as e:
            FAIL(f"{rel}: {e}", str(rel))


# ============================================================
# 检查 2: 函数签名 vs 调用一致性
# ============================================================
def check_function_calls():
    section_header(2, TOTAL_CHECKS, "函数调用参数一致性检查")

    # 自定义日志函数，只接受 msg 参数，不能传 flush/end/file
    log_func_names = {'log_info', 'debug_log', '_log'}
    forbidden_kwargs = {'flush', 'end', 'file', 'sep'}

    files_to_check = [
        PROJECT_ROOT / 'start_server.py',
        PROJECT_ROOT / 'backend' / 'app.py',
        PROJECT_ROOT / 'backend' / 'ocr_pdf.py',
        PROJECT_ROOT / 'backend' / 'ocr_rapid.py',
    ]

    found_issues = False
    for filepath in files_to_check:
        if not filepath.exists():
            continue
        rel = filepath.relative_to(PROJECT_ROOT)
        content = filepath.read_text(encoding='utf-8', errors='replace')
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('def '):
                continue
            for func_name in log_func_names:
                pattern = rf'{func_name}\s*\('
                if re.search(pattern, stripped):
                    for kw in forbidden_kwargs:
                        if f'{kw}=' in stripped:
                            FAIL(f"{func_name}() 传了非法参数 {kw}=", str(rel), i)
                            found_issues = True

    if not found_issues:
        PASS("所有日志函数调用参数正确")


# ============================================================
# 检查 3: 变量引用完整性（NameError 预防）
# ============================================================
def check_name_references():
    section_header(3, TOTAL_CHECKS, "变量引用完整性检查 (NameError 预防)")

    # 核心检查：__import__ 后是否有对应的 import 语句
    critical_checks = [
        {
            'file': 'start_server.py',
            'desc': 'uvicorn 导入后可用',
            'must_have': r'^\s*import\s+uvicorn\b',
            'usage': r'\buvicorn\.\w+',
        },
    ]

    for check in critical_checks:
        filepath = PROJECT_ROOT / check['file']
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding='utf-8', errors='replace')

        has_import = bool(re.search(check['must_have'], content, re.MULTILINE))
        has_usage = bool(re.search(check['usage'], content))

        if has_usage and not has_import:
            FAIL(f"{check['file']}: 使用了 {check['desc']} 但没有 import 语句", check['file'])
        elif has_usage and has_import:
            PASS(f"{check['file']}: {check['desc']}")
        else:
            PASS(f"{check['file']}: 未使用，无风险")

    # 检查 import 在 usage 之前
    filepath = PROJECT_ROOT / 'start_server.py'
    if filepath.exists():
        content = filepath.read_text(encoding='utf-8', errors='replace')
        lines = content.split('\n')
        import_line = -1
        usage_line = -1
        for i, line in enumerate(lines):
            if re.match(r'^\s+import\s+uvicorn\s*$', line):
                import_line = i
            if 'uvicorn.run(' in line:
                usage_line = i

        if import_line >= 0 and usage_line >= 0:
            if import_line < usage_line:
                PASS(f"start_server.py: import uvicorn (L{import_line+1}) < uvicorn.run() (L{usage_line+1})")
            else:
                FAIL(f"start_server.py: import uvicorn (L{import_line+1}) 在 uvicorn.run() (L{usage_line+1}) 之后!", 'start_server.py', usage_line+1)


# ============================================================
# 检查 4: import 依赖 vs requirements.txt 交叉验证
# ============================================================
def check_dependencies():
    section_header(4, TOTAL_CHECKS, "import 依赖 vs requirements.txt 交叉验证")

    req_file = PROJECT_ROOT / 'requirements.txt'
    req_packages = set()
    if req_file.exists():
        for line in req_file.read_text(encoding='utf-8').split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            pkg = re.split(r'[>=<\[!]', line)[0].strip().lower()
            req_packages.add(pkg)

    MODULE_TO_PACKAGE = {
        'cv2': 'opencv-python-headless',
        'PIL': 'pillow',
        'fitz': 'pymupdf',
        'yaml': 'pyyaml',
        'sklearn': 'scikit-learn',
        'skimage': 'scikit-image',
        'doclayout_yolo': 'doclayout-yolo',
        'rapidocr': 'rapidocr',
        'rapidocr_onnxruntime': 'rapidocr',
        'onnxruntime': 'onnxruntime',
        'paddle': 'paddlepaddle',
        'paddleocr': 'paddleocr',
    }

    STDLIB = {
        'os', 'sys', 'pathlib', 'datetime', 'typing', 'math', 'io', 'uuid',
        'shutil', 'zipfile', 'tarfile', 'asyncio', 'json', 'hashlib', 'base64',
        'signal', 'threading', 'time', 'string', 're', 'traceback', 'logging',
        'webbrowser', 'gc', 'tempfile', 'subprocess', 'inspect', 'abc',
        'collections', 'functools', 'itertools', 'copy', 'struct', 'enum',
        'importlib', 'pkg_resources', 'multiprocessing', 'concurrent',
        'urllib', 'http', 'email', 'platform', 'ctypes', 'dataclasses',
        'fractions', 'decimal', 'textwrap', 'argparse', 'ast', 'py_compile',
    }

    third_party_imports = set()
    for f in [PROJECT_ROOT / x for x in CORE_FILES]:
        if not f.exists():
            continue
        content = f.read_text(encoding='utf-8', errors='replace')
        for match in re.finditer(r'^(?:import|from)\s+(\w+)', content, re.MULTILINE):
            mod = match.group(1)
            if mod not in STDLIB and mod != 'config':
                third_party_imports.add(mod)
        for match in re.finditer(r'^\s+(?:import|from)\s+(\w+)', content, re.MULTILINE):
            mod = match.group(1)
            if mod not in STDLIB and mod != 'config' \
               and mod != 'cleaner' and mod != 'ocr_rapid' and mod != 'ocr_pdf':
                third_party_imports.add(mod)

    for mod in sorted(third_party_imports):
        pkg_name = MODULE_TO_PACKAGE.get(mod, mod).lower()
        pkg_variants = {pkg_name, pkg_name.replace('-', '_'), pkg_name.replace('_', '-')}
        found = any(v in req_packages for v in pkg_variants)

        optional = {'paddleocr', 'paddlepaddle', 'paddle'}
        if mod.lower() in optional or pkg_name in optional:
            PASS(f"import {mod} -> {pkg_name} (可选依赖)")
            continue

        # onnxruntime 是 rapidocr 的间接依赖
        indirect = {'onnxruntime'}
        if mod in indirect:
            PASS(f"import {mod} -> {pkg_name} (rapidocr 间接依赖)")
            continue

        if found:
            PASS(f"import {mod} -> {pkg_name} (在 requirements.txt 中)")
        else:
            WARN(f"import {mod} -> {pkg_name} (不在 requirements.txt 中)", mod)


# ============================================================
# 检查 5: .sh 脚本换行符
# ============================================================
def check_shell_scripts():
    section_header(5, TOTAL_CHECKS, "Shell 脚本换行符检查 (CRLF -> 必须 LF)")

    # 检查 pack_release.py
    pack_file = PROJECT_ROOT / 'scripts' / 'pack_release.py'
    if pack_file.exists():
        content = pack_file.read_text(encoding='utf-8', errors='replace')
        if "newline='\\n'" in content or 'newline="\\n"' in content:
            PASS("pack_release.py: write_unix_text 使用 newline='\\n'")
        else:
            FAIL("pack_release.py: 缺少 newline='\\n'，.sh 可能有 CRLF", 'scripts/pack_release.py')

        if 'write_unix_text(start_sh' in content or 'write_unix_text(start_sh,' in content:
            PASS("pack_release.py: start.sh 通过 write_unix_text 写入")
        else:
            FAIL("pack_release.py: start.sh 未通过 write_unix_text 写入", 'scripts/pack_release.py')

        if 'write_unix_text(stop_sh' in content or 'write_unix_text(stop_sh,' in content:
            PASS("pack_release.py: stop.sh 通过 write_unix_text 写入")
        else:
            FAIL("pack_release.py: stop.sh 未通过 write_unix_text 写入", 'scripts/pack_release.py')

    # 检查 download_offline_deps.py
    dl_file = PROJECT_ROOT / 'scripts' / 'download_offline_deps.py'
    if dl_file.exists():
        content = dl_file.read_text(encoding='utf-8', errors='replace')
        if "newline='\\n'" in content or 'newline="\\n"' in content:
            PASS("download_offline_deps.py: install_offline.sh 使用 newline='\\n'")
        else:
            FAIL("download_offline_deps.py: install_offline.sh 缺少 LF 换行", 'scripts/download_offline_deps.py')


# ============================================================
# 检查 6: 联网操作检测
# ============================================================
def check_no_network_at_runtime():
    section_header(6, TOTAL_CHECKS, "运行时联网操作检测 (离线环境禁止)")

    runtime_files = [PROJECT_ROOT / f for f in CORE_FILES]

    patterns = [
        (r'os\.system\(.+pip\s+install', '运行时执行 pip install (离线会失败)'),
        (r'urllib\.request\.urlretrieve', '运行时下载文件'),
        (r'hf_hub_download\s*\(', '运行时从 HuggingFace 下载模型'),
    ]

    found_issues = False
    for filepath in runtime_files:
        if not filepath.exists():
            continue
        rel = filepath.relative_to(PROJECT_ROOT)
        content = filepath.read_text(encoding='utf-8', errors='replace')
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for pattern, desc in patterns:
                if re.search(pattern, stripped):
                    FAIL(desc, str(rel), i)
                    found_issues = True

    if not found_issues:
        PASS("所有运行时文件无联网操作")


# ============================================================
# 检查 7: 离线包完整性
# ============================================================
def _find_offline_dir():
    """查找离线包目录（优先使用 download_offline_deps.py 的输出目录）"""
    # 优先级顺序：环境变量 > download_offline_deps 默认输出 > 项目本地
    search_paths = []

    _data_dir = _url_conf.get('DOCSTUDIO_DATA_DIR', '')
    if _data_dir:
        search_paths.append(Path(_data_dir) / 'dist' / 'assets' / 'linux' / 'wheels')

    # download_offline_deps.py 的默认输出目录
    search_paths.append(PROJECT_ROOT / 'assets' / 'linux' / 'wheels')

    # 项目本地目录（download_offline_deps.py 实际输出到 PROJECT_ROOT/assets/linux/wheels/）
    search_paths.append(PROJECT_ROOT / 'assets' / 'linux' / 'wheels')
    search_paths.append(PROJECT_ROOT / 'dist' / 'assets' / 'linux' / 'wheels')
    search_paths.append(PROJECT_ROOT.parent / 'dist' / 'assets' / 'linux' / 'wheels')

    found = []
    for p in search_paths:
        if p.exists() and any(p.glob('*.whl')):
            return p
        elif p.exists():
            found.append(f"    [exists but no whl] {p}")
        else:
            found.append(f"    [not found] {p}")

    # 输出所有搜索路径状态
    FAIL("未找到离线包目录！已搜索以下路径:")
    for line in found:
        print(line)
    return None


def check_offline_packages():
    section_header(7, TOTAL_CHECKS, "离线包完整性验证")

    offline_dir = _find_offline_dir()
    if offline_dir is None:
        return

    all_files = [f.name for f in offline_dir.iterdir() if f.is_file()]
    all_files_lower = [f.lower() for f in all_files]
    whl_count = len([f for f in all_files_lower if f.endswith('.whl')])
    INFO(f"离线包目录: {offline_dir}")
    INFO(f"共 {whl_count} 个 .whl 文件")

    critical = [
        'torch', 'torchvision',
        'doclayout_yolo', 'ultralytics',
        'fastapi', 'uvicorn',
        'opencv_python_headless', 'numpy', 'pillow', 'PyMuPDF',
        'rapidocr', 'onnxruntime',
        'pyclipper', 'shapely', 'omegaconf', 'colorlog',
        'coloredlogs', 'flatbuffers', 'protobuf',
        'matplotlib', 'pandas', 'seaborn',
        'reportlab', 'pydantic', 'watchdog',
        'pyyaml', 'requests', 'tqdm', 'psutil', 'scipy',
        'huggingface_hub', 'safetensors',
    ]

    for pkg in critical:
        pkg_lower = pkg.lower().replace('-', '_')
        pkg_hyphen = pkg.lower().replace('_', '-')
        found = any(pkg_lower in fn or pkg_hyphen in fn for fn in all_files_lower)
        if found:
            PASS(f"离线包包含: {pkg}")
        else:
            FAIL(f"离线包缺失: {pkg} (运行时会 ModuleNotFoundError!)", str(offline_dir))

    # 检查 onnxruntime-gpu
    ort_gpu = any('onnxruntime_gpu' in fn or 'onnxruntime-gpu' in fn for fn in all_files_lower)
    if ort_gpu:
        PASS("离线包包含: onnxruntime-gpu (GPU 加速 OCR)")
    else:
        WARN("离线包缺少 onnxruntime-gpu (OCR 将使用 CPU)")

    # 检查 NVIDIA CUDA 运行时
    nvidia_files = [f for f in all_files if 'nvidia' in f.lower()]
    if nvidia_files:
        PASS(f"离线包包含 {len(nvidia_files)} 个 NVIDIA CUDA 运行时包")
    else:
        WARN("离线包缺少 NVIDIA CUDA 运行时包 (GPU PyTorch 可能无法运行)")


# ============================================================
# 检查 8: 离线包平台一致性 (关键！)
# ============================================================
def check_offline_duplicates(auto_fix=False):
    """检查离线包中是否有重复版本"""
    section_header(8, TOTAL_CHECKS, "离线包重复版本检测 (pip install *.whl 会冲突)")

    offline_dir = _find_offline_dir()
    if offline_dir is None:
        WARN("未找到离线包目录，跳过")
        return

    import re
    from collections import defaultdict

    pkg_groups = defaultdict(list)
    for whl in offline_dir.glob('*.whl'):
        fname = whl.name
        match = re.match(r'^([a-zA-Z0-9_]+(?:[-_][a-zA-Z0-9_]+)*?)-(\d+[\w.]*)', fname)
        if match:
            pkg_name = match.group(1).lower().replace('-', '_')
            pkg_groups[pkg_name].append(whl)

    found_dups = False
    for pkg_name, files in sorted(pkg_groups.items()):
        if len(files) <= 1:
            continue
        found_dups = True
        file_names = [f.name for f in files]
        if auto_fix:
            # 保留平台特定版本或最新版本
            platform_specific = [f for f in files if 'manylinux' in f.name or 'linux' in f.name]
            generic = [f for f in files if 'none-any' in f.name]
            if platform_specific and generic:
                for f in generic:
                    f.unlink()
                    _auto_fixed.append(f"Deleted duplicate: {f.name}")
                    PASS(f"[AUTO-FIX] Deleted duplicate: {f.name}")
            else:
                files.sort(key=lambda f: f.stat().st_mtime)
                for f in files[:-1]:
                    f.unlink()
                    _auto_fixed.append(f"Deleted duplicate: {f.name}")
                    PASS(f"[AUTO-FIX] Deleted duplicate: {f.name}")
        else:
            FAIL(f"{pkg_name} has {len(files)} versions: {file_names}", str(offline_dir))

    if not found_dups:
        PASS("No duplicate package versions found")


def check_offline_platform(auto_fix=False):
    section_header(9, TOTAL_CHECKS, "离线包平台一致性 (win_amd64 不应混入 linux 目录)")

    offline_dir = _find_offline_dir()
    if offline_dir is None:
        WARN("未找到离线包目录，跳过")
        return

    all_files = [f.name for f in offline_dir.iterdir() if f.is_file() and f.suffix == '.whl']

    wrong_platform_files = []
    for fname in all_files:
        # 检查 Windows 专用 wheel 混入 Linux 目录
        if 'win_amd64' in fname or 'win32' in fname:
            wrong_platform_files.append(fname)
            if auto_fix:
                (offline_dir / fname).unlink()
                _auto_fixed.append(f"Deleted wrong-platform: {fname}")
                PASS(f"[AUTO-FIX] Deleted: {fname}")
            else:
                FAIL(f"Windows package in Linux dir: {fname}", str(offline_dir))

    if not wrong_platform_files:
        PASS("All .whl files have correct platform (no Windows packages)")

    # 检查是否有关键包缺少 Linux 版本
    # 核心 C 扩展包，必须有 manylinux 版本
    c_ext_packages = {
        'numpy': False,
        'opencv_python_headless': False,
        'pillow': False,
        'pydantic_core': False,
        'pyyaml': False,
        'scipy': False,
        'psutil': False,
    }

    for fname in all_files:
        fname_lower = fname.lower()
        for pkg in c_ext_packages:
            if pkg.lower() in fname_lower and ('manylinux' in fname_lower or 'linux' in fname_lower):
                c_ext_packages[pkg] = True

    for pkg, has_linux in c_ext_packages.items():
        if has_linux:
            PASS(f"{pkg}: 有 Linux (manylinux) 版本")
        else:
            # 检查是否有纯 Python 版本 (py3-none-any)
            has_pure = any(pkg.lower() in f.lower() and 'none-any' in f.lower() for f in all_files)
            if has_pure:
                PASS(f"{pkg}: 纯 Python 包 (跨平台)")
            else:
                FAIL(f"{pkg}: 缺少 Linux 版本! (可能只有 Windows 版)", str(offline_dir))


# ============================================================
# 检查 9: torch CUDA 版本验证 (关键！)
# ============================================================
def check_torch_cuda():
    section_header(10, TOTAL_CHECKS, "torch CUDA 版本验证 (GPU 加速)")

    offline_dir = _find_offline_dir()
    if offline_dir is None:
        WARN("未找到离线包目录，跳过")
        return

    all_files = [f.name for f in offline_dir.iterdir() if f.is_file() and f.suffix == '.whl']

    # 找出所有 torch 相关的 wheel
    torch_files = [f for f in all_files if f.startswith('torch-')]
    torchvision_files = [f for f in all_files if f.startswith('torchvision-')]

    INFO(f"torch wheels: {torch_files}")
    INFO(f"torchvision wheels: {torchvision_files}")

    if not torch_files:
        FAIL("离线包中没有 torch!", str(offline_dir))
        return

    # 检查是否有 CUDA 版本
    cuda_torch = [f for f in torch_files if '+cu' in f]
    cpu_torch = [f for f in torch_files if '+cpu' in f or '+cu' not in f]

    # 检查是否有 Linux CUDA 版本
    linux_cuda_torch = [f for f in cuda_torch if 'manylinux' in f or 'linux' in f]
    linux_cpu_torch = [f for f in cpu_torch if 'manylinux' in f or 'linux' in f]
    win_torch = [f for f in torch_files if 'win' in f]

    if linux_cuda_torch:
        PASS(f"torch CUDA Linux 版本: {linux_cuda_torch[0]}")
    elif linux_cpu_torch:
        FAIL(f"torch 只有 CPU Linux 版本: {linux_cpu_torch[0]} (GPU 无法加速!)", str(offline_dir))
        INFO("torch 从 CUDA index 下载时，文件名可能不含 +cu 标记")
        INFO("请确认 build_openeuler.bat 使用 --cuda 12.8")
    elif win_torch:
        FAIL(f"torch 只有 Windows 版本: {win_torch[0]} (Linux 无法使用!)", str(offline_dir))
    else:
        FAIL("torch 版本异常，无法判断平台", str(offline_dir))

    # 检查 torchvision
    if not torchvision_files:
        FAIL("离线包中没有 torchvision!", str(offline_dir))
    else:
        linux_tv = [f for f in torchvision_files if 'manylinux' in f or 'linux' in f]
        if linux_tv:
            PASS(f"torchvision Linux 版本: {linux_tv[0]}")
        else:
            # 检查是否有纯 Python 的 torchvision (某些旧版本)
            pure_tv = [f for f in torchvision_files if 'none-any' in f]
            if pure_tv:
                # 旧版本的 torchvision 可能是纯 Python
                WARN(f"torchvision 是纯 Python 版本: {pure_tv[0]} (可能版本过低)")
            else:
                FAIL(f"torchvision 缺少 Linux 版本: {torchvision_files}", str(offline_dir))

    # 检查版本一致性: torch 和 torchvision 版本要匹配
    if torch_files and torchvision_files:
        # 提取 torch 大版本
        torch_ver_match = re.search(r'torch-(\d+\.\d+)', torch_files[0])
        if torch_ver_match:
            torch_major = torch_ver_match.group(1)
            INFO(f"torch 版本: {torch_major}")

    # 检查是否有重复版本 (CPU + GPU 都存在)
    if len(torch_files) > 1:
        WARN(f"torch 有 {len(torch_files)} 个版本，建议只保留一个: {torch_files}")


# ============================================================
# 检查 10.5: GPU 组件 CUDA 版本一致性 (关键！)
#   PyTorch CUDA 版本、onnxruntime-gpu 版本、NVIDIA 运行时包
#   三者必须匹配同一 CUDA 大版本，否则运行时会找不到 .so
# ============================================================
def check_cuda_version_consistency():
    section_header(11, TOTAL_CHECKS, "GPU 组件 CUDA 版本一致性校验 (防止 .so 找不到)")

    offline_dir = _find_offline_dir()
    if offline_dir is None:
        WARN("未找到离线包目录，跳过 CUDA 一致性校验")
        return

    all_files = [f.name for f in offline_dir.iterdir() if f.is_file() and f.suffix == '.whl']
    [f.lower() for f in all_files]

    # ============================================================
    # 1. 检测 PyTorch 的 CUDA 版本
    # ============================================================
    torch_cuda_ver = None  # 如 "12.8" 或 None(CPU)
    torch_cuda_major = None  # 如 12
    for f in all_files:
        if f.startswith('torch-') and ('cu1' in f):
            match = re.search(r'cu(\d+)', f)
            if match:
                tag = match.group(1)  # 如 "124"
                if len(tag) >= 2:
                    torch_cuda_ver = f"{tag[0:2]}.{tag[2:]}" if len(tag) == 3 else f"{tag[0]}.{tag[1:]}"
                    torch_cuda_major = int(tag[:2])
                    break

    if torch_cuda_ver:
        INFO(f"PyTorch CUDA 版本: {torch_cuda_ver} (大版本: {torch_cuda_major})")
    else:
        # 检查是否是无 CUDA 标记的 torch (从 CUDA index 下载的可能不带 +cu)
        has_torch = any(f.startswith('torch-') for f in all_files)
        if has_torch:
            WARN("torch wheel 文件名无 CUDA 标记（可能是 CPU 版本或从 CUDA index 下载）")
            WARN("无法进行 CUDA 版本一致性校验")
        else:
            WARN("未找到 torch wheel，跳过 CUDA 一致性校验")
        return

    # ============================================================
    # 2. 检测 onnxruntime-gpu 版本，校验 CUDA 兼容性
    #    onnxruntime-gpu < 1.19 → CUDA 11 编译
    #    onnxruntime-gpu >= 1.19 → CUDA 12 编译
    # ============================================================
    ort_gpu_ver = None
    ort_gpu_cuda = None  # 推断出的 CUDA 大版本
    for f in all_files:
        if 'onnxruntime_gpu' in f.lower() or 'onnxruntime-gpu' in f.lower():
            ver_match = re.search(r'onnxruntime[_-]gpu-(\d+)\.(\d+)', f, re.IGNORECASE)
            if ver_match:
                ort_major = int(ver_match.group(1))
                ort_minor = int(ver_match.group(2))
                ort_gpu_ver = f"{ort_major}.{ort_minor}"
                # 推断 CUDA 版本
                if ort_major > 1 or (ort_major == 1 and ort_minor >= 19):
                    ort_gpu_cuda = 12  # >= 1.19 → CUDA 12
                else:
                    ort_gpu_cuda = 11  # < 1.19 → CUDA 11
                break

    if ort_gpu_ver:
        INFO(f"onnxruntime-gpu 版本: {ort_gpu_ver} (推断 CUDA: {ort_gpu_cuda})")

        # ★ 核心校验：torch CUDA 大版本 vs onnxruntime-gpu CUDA 大版本 ★
        if torch_cuda_major == ort_gpu_cuda:
            PASS(f"torch CUDA {torch_cuda_major} ←→ onnxruntime-gpu {ort_gpu_ver} (CUDA {ort_gpu_cuda}) 版本匹配 ✓")
        else:
            FAIL(
                f"★ CUDA 版本不匹配！torch 需要 CUDA {torch_cuda_major}，"
                f"但 onnxruntime-gpu {ort_gpu_ver} 是 CUDA {ort_gpu_cuda} 编译的！\n"
                f"         运行时会报 'libcublasLt.so.{ort_gpu_cuda}: cannot open shared object file'\n"
                f"         解决: {'升级 onnxruntime-gpu >= 1.19.0' if torch_cuda_major == 12 else '降级 onnxruntime-gpu < 1.19'}",
                str(offline_dir)
            )

        # cuDNN 版本兼容性提示
        if ort_major == 1 and ort_minor >= 18:
            INFO(f"onnxruntime-gpu >= 1.18 需要 cuDNN 9.x（目标系统请确认 cuDNN 版本）")
    else:
        WARN("离线包中未找到 onnxruntime-gpu，OCR 将使用 CPU")

    # ============================================================
    # 3. 检测 NVIDIA 运行时包的 CUDA 版本
    # ============================================================
    nvidia_pkgs = [f for f in all_files if f.lower().startswith('nvidia')]
    if nvidia_pkgs:
        nvidia_cu_versions = set()
        for f in nvidia_pkgs:
            # 提取 nvidia-*-cu12 或 nvidia-*-cu11 中的版本
            match = re.search(r'cu(\d+)', f.lower())
            if match:
                nvidia_cu_versions.add(int(match.group(1)))

        INFO(f"NVIDIA 运行时包: {len(nvidia_pkgs)} 个, CUDA 标签: {sorted(nvidia_cu_versions)}")

        for cu_ver in nvidia_cu_versions:
            if cu_ver == torch_cuda_major:
                PASS(f"NVIDIA 运行时包 CUDA {cu_ver} 与 torch CUDA {torch_cuda_major} 一致 ✓")
            else:
                FAIL(
                    f"NVIDIA 运行时包含 CUDA {cu_ver}，但 torch 需要 CUDA {torch_cuda_major}！",
                    str(offline_dir)
                )

        # 检查是否有混合版本
        if len(nvidia_cu_versions) > 1:
            FAIL(
                f"NVIDIA 运行时包混合了多个 CUDA 版本: {sorted(nvidia_cu_versions)}！应只有一个版本",
                str(offline_dir)
            )
    else:
        if torch_cuda_ver:
            WARN("离线包中无 NVIDIA 运行时包（GPU torch 可能缺少依赖）")

    # ============================================================
    # 4. 检查代码中的版本引用一致性
    # ============================================================
    # requirements.txt 注释中的 CUDA 版本
    req_file = PROJECT_ROOT / 'requirements.txt'
    if req_file.exists():
        req_content = req_file.read_text(encoding='utf-8', errors='replace')
        # 检查 cu121/cu124 等引用
        cu_refs = re.findall(r'cu(\d{3,4})', req_content)
        if cu_refs:
            str(torch_cuda_major) + torch_cuda_ver.replace('.', '')[2:] if torch_cuda_ver else ''
            for ref in cu_refs:
                ref_major = int(ref[:2])
                if ref_major != torch_cuda_major:
                    FAIL(
                        f"requirements.txt 中引用了 cu{ref} (CUDA {ref_major})，"
                        f"但实际打包用 CUDA {torch_cuda_major}！注释可能过时",
                        'requirements.txt'
                    )

    # download_offline_deps.py 默认 CUDA 版本
    dl_file = PROJECT_ROOT / 'scripts' / 'download_offline_deps.py'
    if dl_file.exists():
        dl_content = dl_file.read_text(encoding='utf-8', errors='replace')
        default_match = re.search(r"default='(\d+\.\d+)'.*CUDA", dl_content)
        if default_match:
            default_cuda = default_match.group(1)
            if default_cuda != torch_cuda_ver:
                WARN(
                    f"download_offline_deps.py 默认 CUDA={default_cuda}，"
                    f"但打包的 torch 是 CUDA {torch_cuda_ver}",
                    'scripts/download_offline_deps.py'
                )
            else:
                PASS(f"download_offline_deps.py 默认 CUDA 版本 ({default_cuda}) 与打包一致 ✓")

    # build_openeuler.bat 中的 --cuda 参数
    bat_file = PROJECT_ROOT / 'bin' / 'build_openeuler.bat'
    if bat_file.exists():
        bat_content = bat_file.read_text(encoding='utf-8', errors='replace')
        bat_cuda_match = re.search(r'--cuda\s+(\d+\.\d+)', bat_content)
        if bat_cuda_match:
            bat_cuda = bat_cuda_match.group(1)
            if bat_cuda != torch_cuda_ver:
                WARN(
                    f"build_openeuler.bat --cuda {bat_cuda}，"
                    f"但离线包中 torch 是 CUDA {torch_cuda_ver}（可能已过时）",
                    'bin/build_openeuler.bat'
                )
            else:
                PASS(f"build_openeuler.bat --cuda {bat_cuda} 与离线包一致 ✓")


# ============================================================
# 检查 11: 日志函数格式一致性
# ============================================================
def check_log_format():
    section_header(12, TOTAL_CHECKS, "日志函数格式一致性检查")

    files_to_check = {
        'start_server.py': '_log',
        'backend/cleaner/__init__.py': '_log',
        'backend/app.py': ['log_info', 'debug_log'],
        'backend/ocr_pdf.py': 'log',
        'backend/ocr_rapid.py': 'log',
    }

    for rel_path, func_names in files_to_check.items():
        filepath = PROJECT_ROOT / rel_path
        if not filepath.exists():
            continue
        if isinstance(func_names, str):
            func_names = [func_names]

        content = filepath.read_text(encoding='utf-8', errors='replace')

        for func_name in func_names:
            def_pattern = rf'def\s+{re.escape(func_name)}\s*\('
            def_match = re.search(def_pattern, content)
            if def_match:
                start_pos = def_match.start()
                func_body = content[start_pos:start_pos + 500]

                if '%Y-%m-%d %H:%M:%S' in func_body or 'strftime' in func_body:
                    PASS(f"{rel_path}: {func_name}() 包含时间戳格式")
                elif 'timestamp' in func_body.lower():
                    PASS(f"{rel_path}: {func_name}() 使用时间戳变量")
                else:
                    WARN(f"{rel_path}: {func_name}() 可能缺少时间戳", rel_path)

                if 'stdout.write' in func_body or 'print(' in func_body:
                    PASS(f"{rel_path}: {func_name}() 输出方式正确")
                else:
                    WARN(f"{rel_path}: {func_name}() 可能缺少输出语句", rel_path)


# ============================================================
# 额外检查: download_offline_deps.py 安全性
# ============================================================
# 检查 13: 包内导入完整性（检测裸 import 而非 from . import）
# ============================================================
# 包内模块名（在 backend/ 内部的模块）
_PKG_MODULES = {'config', 'cleaner', 'ocr_pdf', 'ocr_rapid', 'app', 'server', 'service_manager'}


def check_package_imports():
    section_header(13, TOTAL_CHECKS, "包内导入完整性检查（裸 import vs from . import）")

    pkg_dir = PROJECT_ROOT / 'backend'
    if not pkg_dir.is_dir():
        FAIL("backend/ 目录不存在")
        return

    py_files = sorted(pkg_dir.glob('*.py'))
    bare_import_re = re.compile(
        r'^\s*import\s+(%s)\b' % '|'.join(_PKG_MODULES)
    )
    bare_from_re = re.compile(
        r'^\s*from\s+(%s)\s+import' % '|'.join(_PKG_MODULES)
    )

    found_issues = 0
    for py_file in py_files:
        mod_name = py_file.stem
        if mod_name == '__init__':
            continue
        try:
            lines = py_file.read_text(encoding='utf-8').splitlines()
        except Exception as e:
            WARN(f"{py_file.relative_to(PROJECT_ROOT)}: 无法读取 ({e})")
            continue

        for i, line in enumerate(lines, 1):
            # 跳过注释和文档字符串
            stripped = line.strip()
            if stripped.startswith('#'):
                continue

            # 检测裸 import config / import cleaner 等
            m = bare_import_re.match(stripped)
            if m:
                imported = m.group(1)
                FAIL(
                    f"裸 'import {imported}' 应为 'from . import {imported}'",
                    str(py_file.relative_to(PROJECT_ROOT)), i
                )
                found_issues += 1

            # 检测裸 from config import / from cleaner import 等
            m2 = bare_from_re.match(stripped)
            if m2:
                imported = m2.group(1)
                FAIL(
                    f"裸 'from {imported} import ...' 应为 'from .{imported} import ...'",
                    str(py_file.relative_to(PROJECT_ROOT)), i
                )
                found_issues += 1

    if found_issues == 0:
        PASS("所有包内导入均使用正确的相对导入（from . import）")


# ============================================================
# 检查 14: 包目录树完整性
# ============================================================
def check_package_tree():
    section_header(14, TOTAL_CHECKS, "包目录树完整性检查")

    # 检查核心文件存在
    for rel_path in CORE_FILES:
        fp = PROJECT_ROOT / rel_path
        if fp.exists():
            PASS(f"{rel_path}")
        else:
            FAIL(f"缺失: {rel_path}")

    # 检查 pyproject.toml
    ppt = PROJECT_ROOT / 'pyproject.toml'
    if ppt.exists():
        PASS("pyproject.toml")
        try:
            content = ppt.read_text(encoding='utf-8')
            # 验证 [project.scripts] 入口点指向存在的函数
            if 'crabapple-docstudio-server' in content and 'crabapple-docstudio-manager' in content:
                PASS("pyproject.toml: console_scripts 入口点已配置")
            else:
                WARN("pyproject.toml: 缺少 crabapple-docstudio-server/crabapple-docstudio-manager 入口点")
        except Exception as e:
            WARN(f"pyproject.toml: 读取失败 ({e})")
    else:
        FAIL("缺失: pyproject.toml")

    # 检查 __init__.py 导出
    init_file = PROJECT_ROOT / 'backend' / '__init__.py'
    try:
        content = init_file.read_text(encoding='utf-8')
        if 'DocumentCleaner' in content and 'config' in content:
            PASS("__init__.py: 导出 DocumentCleaner 和 config")
        else:
            WARN("__init__.py: 缺少预期的公开导出")
    except Exception as e:
        WARN(f"__init__.py: 读取失败 ({e})")

    # 检查 __main__.py
    main_file = PROJECT_ROOT / 'backend' / '__main__.py'
    try:
        content = main_file.read_text(encoding='utf-8')
        if 'server' in content and 'main' in content:
            PASS("__main__.py: 正确委托到 server.main()")
        else:
            WARN("__main__.py: 未委托到 server.main()")
    except Exception as e:
        WARN(f"__main__.py: 读取失败 ({e})")

    # 检查 start_server.py 薄封装
    start_file = PROJECT_ROOT / 'start_server.py'
    try:
        content = start_file.read_text(encoding='utf-8')
        if 'backend.server' in content:
            PASS("start_server.py: 正确导入 backend.server")
        else:
            WARN("start_server.py: 未从 backend.server 导入")
    except Exception as e:
        WARN(f"start_server.py: 读取失败 ({e})")

    # 检查根目录无残留 .py 文件（start_server.py 除外）
    stray_py = [f for f in PROJECT_ROOT.glob('*.py')
                if f.name != 'start_server.py']
    if stray_py:
        for f in stray_py:
            FAIL(f"根目录残留 .py: {f.name}（应移入 backend/）")
    else:
        PASS("根目录无残留 .py 文件（start_server.py 除外）")


# ============================================================
# 检查 15: url.conf 路径验证
# ============================================================
def check_url_conf():
    section_header(15, TOTAL_CHECKS, "url.conf 路径配置验证")

    conf_path = PROJECT_ROOT / 'url.conf'
    if not conf_path.exists():
        FAIL("url.conf 不存在")
        return
    PASS("url.conf 存在")

    # 解析 url.conf
    conf = {}
    for line in conf_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k, v = k.strip(), v.strip()
        for ref in conf:
            v = v.replace(f"${{{ref}}}", conf[ref])
        conf[k] = v

    # 检查关键变量存在
    key_vars = ['DOCSTUDIO_DATA_DIR', 'TMPDIR', 'DOCSTUDIO_PYTHON']
    for var in key_vars:
        if var in conf:
            PASS(f"url.conf: {var} = {conf[var]}")
        else:
            FAIL(f"url.conf: 缺少必需变量 {var}")

    # 检查 _WIN 平台变体
    win_vars = [k for k in conf if k.endswith('_WIN')]
    if win_vars:
        INFO(f"url.conf: 含 {len(win_vars)} 个 Windows (_WIN) 平台变体")
    else:
        WARN("url.conf: 缺少 Windows (_WIN) 平台变体")

    # 检查源代码中无硬编码路径
    hardcoded_patterns = [
        (r'["\']D:/internal/', '硬编码 Windows D:/internal 路径'),
        (r'["\']/root/', '硬编码 /root 路径'),
        (r'["\']/home/', '硬编码 /home 路径'),
        (r'["\']/data1/', '硬编码 /data1 路径'),
    ]
    found_hardcoded = 0
    for py_file in sorted((PROJECT_ROOT / 'backend').glob('*.py')):
        try:
            content = py_file.read_text(encoding='utf-8')
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            for pattern, desc in hardcoded_patterns:
                if re.search(pattern, line) and 'url.conf' not in line and 'example' not in line.lower():
                    FAIL(desc, str(py_file.relative_to(PROJECT_ROOT)), i)
                    found_hardcoded += 1
    if found_hardcoded == 0:
        PASS("源代码中无硬编码路径")


# ============================================================
# 检查 16: 入口点和控制台命令验证
# ============================================================
def check_entry_points():
    section_header(16, TOTAL_CHECKS, "入口点和控制台命令验证")

    # 验证 python -m backend 可用
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, '-c', 'from backend.server import main'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, cwd=str(PROJECT_ROOT)
        )
        if result.returncode == 0:
            PASS("python -c 'from backend.server import main'")
        else:
            FAIL(f"backend.server 导入失败: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        FAIL("backend.server 导入超时（可能卡在模型加载）")
    except Exception as e:
        FAIL(f"backend.server 导入异常: {e}")

    # 验证 backend 包可导入
    try:
        result = subprocess.run(
            [sys.executable, '-c', 'from backend import config, DocumentCleaner'],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, cwd=str(PROJECT_ROOT)
        )
        if result.returncode == 0:
            PASS("from backend import config, DocumentCleaner")
        else:
            # DocumentCleaner 可能因 GPU 依赖失败，单独检查 config
            result2 = subprocess.run(
                [sys.executable, '-c', 'from backend import config; print(config.DATA_DIR)'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10, cwd=str(PROJECT_ROOT)
            )
            if result2.returncode == 0:
                WARN(f"config 可导入但 DocumentCleaner 不可用: {result.stderr.strip()}")
            else:
                FAIL(f"backend 导入失败: {result2.stderr.strip()}")
    except Exception as e:
        FAIL(f"backend 导入异常: {e}")


# ============================================================
# 检查 17: 前端构建一致性
# ============================================================
def check_frontend_build():
    section_header(17, TOTAL_CHECKS, "前端构建一致性检查")

    dist_dir = PROJECT_ROOT / 'frontend' / 'dist'

    if not dist_dir.exists():
        INFO("frontend/dist/ 不存在（跳过，打包前再检查）")
        return

    # 检查 index.html
    index_file = dist_dir / 'index.html'
    if index_file.exists():
        PASS("frontend/dist/index.html 存在")
    else:
        FAIL("frontend/dist/index.html 缺失")

    # 检查 assets 目录
    assets_dir = dist_dir / 'assets'
    if assets_dir.is_dir():
        asset_count = len(list(assets_dir.glob('*')))
        if asset_count > 0:
            PASS(f"frontend/dist/assets/ 含 {asset_count} 个文件")
        else:
            WARN("frontend/dist/assets/ 为空")
    else:
        WARN("frontend/dist/assets/ 目录不存在")

    # xuechong 2026-06-30 全面版本号一致性检查（17个文件）
    try:
        import json

        # 从 pyproject.toml 获取基准版本号
        ppt_content = (PROJECT_ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        m = re.search(r'^version\s*=\s*"([^"]+)"', ppt_content, re.MULTILINE)
        base_version = m.group(1) if m else ''

        if not base_version:
            FAIL("无法从 pyproject.toml 读取版本号")
            return

        INFO(f"基准版本号: {base_version}")

        # 定义所有需要检查版本号的文件和匹配模式
        version_checks = [
            # 后端 Python
            ("pyproject.toml", rf'version\s*=\s*"{re.escape(base_version)}"', "version ="),
            ("backend/__init__.py", rf"__version__\s*=\s*'{re.escape(base_version)}'", "__version__ ="),
            ("backend/config.py", rf'版本:\s*{re.escape(base_version)}', "版本:"),
            ("backend/app.py", rf'version="{re.escape(base_version)}"', "FastAPI version="),
            ("backend/routes/system.py", rf'"version":\s*"{re.escape(base_version)}"', "API version"),
            ("backend/service_manager.py", rf'V{re.escape(base_version)}', "GUI 版权"),
            # 前端
            ("frontend/package.json", rf'"version":\s*"{re.escape(base_version)}"', "package.json"),
            ("frontend/index.html", rf'V{re.escape(base_version)}', "title 标签"),
            ("frontend/src/pages/LoginPage.vue", rf'V{re.escape(base_version)}', "登录页标题"),
            ("frontend/src/pages/HomePage.vue", rf'V{re.escape(base_version)}', "首页版本号"),
            # 文档（xuechong 2026-08-17 研发BUG-0023 CLAUDE.md/.claude 目录已删除，过时检查项移除）
            # 测试
            ("tests/test_api.py", r'j\["version"\]\s*==\s*app\.version', "版本测试(动态比较)"),
        ]

        all_ok = True
        for file_path, pattern, desc in version_checks:
            full_path = PROJECT_ROOT / file_path
            if not full_path.exists():
                WARN(f"{file_path}: 文件不存在")
                continue

            content = full_path.read_text(encoding='utf-8', errors='replace')
            if re.search(pattern, content, re.MULTILINE):
                PASS(f"{file_path}: {desc} = {base_version} ✓")
            else:
                FAIL(f"{file_path}: {desc} 版本号不是 {base_version}！", file_path)
                all_ok = False

        # 检查 package-lock.json（2处）
        lock_file = PROJECT_ROOT / 'frontend' / 'package-lock.json'
        if lock_file.exists():
            lock_content = lock_file.read_text(encoding='utf-8')
            lock_count = lock_content.count(f'"version": "{base_version}"')
            if lock_count >= 2:
                PASS(f"frontend/package-lock.json: 版本号 {base_version} 出现 {lock_count} 处 ✓")
            else:
                FAIL(f"frontend/package-lock.json: 版本号 {base_version} 只出现 {lock_count} 处（应>=2）")

        if all_ok:
            PASS(f"所有文件版本号一致: {base_version}")
        else:
            FAIL(f"版本号不一致！请运行: python scripts/update_version.py {base_version}")

    except Exception as e:
        WARN(f"版本一致性检查失败: {e}")


# ============================================================
# 主入口
# ============================================================
def main():
    auto_fix = '--fix' in sys.argv

    start_time = datetime.now()

    print()
    print(BOLD("=" * 60))
    print(BOLD("  [SELF-CHECK] Document Scanner - Full System Check"))
    print(BOLD("=" * 60))
    print(f"  Project:  {PROJECT_ROOT}")
    print(f"  Time:     {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python:   {sys.version.split()[0]}")
    print(f"  Platform: {sys.platform}")
    if auto_fix:
        print(f"  Mode:     AUTO-FIX")

    # 运行所有检查
    check_syntax()
    check_function_calls()
    check_name_references()
    check_dependencies()
    check_shell_scripts()
    check_no_network_at_runtime()
    check_offline_packages()
    check_offline_duplicates(auto_fix=auto_fix)
    check_offline_platform(auto_fix=auto_fix)
    check_torch_cuda()
    check_cuda_version_consistency()
    check_log_format()
    check_package_imports()
    check_package_tree()
    check_url_conf()
    check_entry_points()
    check_frontend_build()

    # 汇总报告
    elapsed = (datetime.now() - start_time).total_seconds()
    print()
    print(BOLD("=" * 60))
    print(BOLD("  REPORT"))
    print(BOLD("=" * 60))
    print(f"  {GREEN(f'PASS: {_pass_count}')}")
    print(f"  {YELLOW(f'WARN: {_warn_count}')}")
    print(f"  {RED(f'FAIL: {_fail_count}')}")
    print(f"  Time: {elapsed:.1f}s")

    if _auto_fixed:
        print()
        print(GREEN(f"  Auto-fixed {len(_auto_fixed)} issues:"))
        for fix in _auto_fixed:
            print(f"    - {fix}")

    if _fail_count > 0:
        print()
        print(RED(BOLD("  [X] FAILED - Fix before packaging!")))
        print()
        print(RED("  Failures:"))
        for file, line, msg in _errors:
            loc = f"  {file}:{line}" if file else ""
            print(f"    {RED('-')} {msg}{loc}")
        print()
        return 1
    elif _warn_count > 0:
        print()
        print(YELLOW(BOLD("  [!] WARNINGS - Review before packaging")))
        print()
        return 0
    else:
        print()
        print(GREEN(BOLD("  [OK] All checks passed - Safe to package!")))
        print()
        return 0


if __name__ == '__main__':
    sys.exit(main())
