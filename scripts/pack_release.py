# -*- coding: utf-8 -*-
"""
海棠文档工坊 - 打包发布脚本

使用方法：
    双击 pack.bat 或运行 python scripts/pack_release.py

输出目录：默认外部目录 dist，可通过环境变量 DOCSTUDIO_DIST_DIR 覆盖
文件名格式：crabapple-docstudio-vX.X.X (版本号从 App.vue 自动读取)
"""

import sys
import shutil
import subprocess
import zipfile
import tarfile
import re
from pathlib import Path
from datetime import datetime

# ============================================================
# 从 url.conf 加载磁盘路径配置
# ============================================================
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

# ============================================================
# 配置
# ============================================================

PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / 'frontend'
PKG_DIR = PROJECT_ROOT / 'backend'

def get_version_from_frontend():
    """从前端 package.json 或 pages/HomePage.vue 中动态读取版本号"""
    # 优先从 package.json 读取
    pkg_json = FRONTEND_DIR / 'package.json'
    if pkg_json.exists():
        import json as _json
        try:
            pkg = _json.loads(pkg_json.read_text(encoding='utf-8'))
            if 'version' in pkg:
                return pkg['version']
        except Exception:
            pass
    # 回退：从 pages/HomePage.vue 读取
    home_vue_path = FRONTEND_DIR / 'src' / 'pages' / 'HomePage.vue'
    if home_vue_path.exists():
        content = home_vue_path.read_text(encoding='utf-8')
        match = re.search(r'>V(\d+\.\d+\.\d+)<', content)
        if match:
            return match.group(1)
    # 默认版本号
    return "1.0.0"

# 动态获取版本号
VERSION = get_version_from_frontend()

# 路径常量：根据当前平台选择
# 注意 — url.conf 的 Linux 路径是生产服务器部署路径，构建输出不要用
if sys.platform == 'win32':
    _DATA_DIR = Path(_url_conf.get("DOCSTUDIO_BASE_DIR_WIN", str(PROJECT_ROOT / "data"))).resolve()
    DIST_DIR = Path(_url_conf.get("DOCSTUDIO_DIST_DIR_WIN", str(_DATA_DIR / "dist"))).resolve()
    TMP_DIR = Path(_url_conf.get("DOCSTUDIO_TMP_DIR_WIN", str(_DATA_DIR / "tmp"))).resolve()
else:
    # Linux/WSL 构建：输出到项目本地 dist/，不使用生产路径
    DIST_DIR = (PROJECT_ROOT / "dist").resolve()
    TMP_DIR = Path(_url_conf.get("DOCSTUDIO_TMP_DIR", str(PROJECT_ROOT / "tmp"))).resolve()
    _DATA_DIR = PROJECT_ROOT
# PLUGINS_DIR — 构建依赖缓存（CPython 包、get-pip.py 等），位于 assets/ 下
PLUGINS_DIR = (PROJECT_ROOT / 'assets').resolve()

# 确保目录存在
DIST_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

# Python 嵌入式版本
PYTHON_EMBED_VERSION = '3.11.11'
PYTHON_EMBED_URL = f'https://www.python.org/ftp/python/{PYTHON_EMBED_VERSION}/python-{PYTHON_EMBED_VERSION}-embed-amd64.zip'
PYTHON_EMBED_URL_CN = f'https://registry.npmmirror.com/-/binary/python/{PYTHON_EMBED_VERSION}/python-{PYTHON_EMBED_VERSION}-embed-amd64.zip'
GET_PIP_URL = 'https://bootstrap.pypa.io/get-pip.py'

# python-build-standalone（Linux 可迁移 Python 运行时，自带 _ssl）
#   GitHub 仓库已从 indygreg 改名为 astral-sh
#   release tag 20240415 对应 Python 3.10.14（不是 3.10.11）
PBS_VERSION = '3.11.11'
PBS_RELEASE_TAG = '20240415'
PBS_FILENAME = f'cpython-{PBS_VERSION}+{PBS_RELEASE_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz'
PBS_URL = f'https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE_TAG}/{PBS_FILENAME}'
PBS_URL_CN = f'https://ghproxy.com/{PBS_URL}'

def write_unix_text(filepath: Path, content: str):
    """写入文件时强制使用 Unix 换行符 (LF)，避免 Windows CRLF 导致 Linux 无法执行 .sh"""
    with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)

def print_header(title):
    """打印标题"""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)

def run_command(cmd, cwd=None, timeout=600):
    """运行命令"""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, 
            text=True, encoding='utf-8', errors='replace',  # 指定UTF-8编码，忽略解码错误
            timeout=timeout
        )
        if result.returncode != 0:
            print(f"  [警告] 命令返回非零: {result.returncode}")
            if result.stderr:
                print(f"  {result.stderr[:500]}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  [警告] 命令超时")
        return False
    except Exception as e:
        print(f"  [错误] {e}")
        return False

def build_frontend():
    """构建前端"""
    print_header("步骤 1/6: 构建前端 (Vue 3 + Vite)")
    
    if not FRONTEND_DIR.exists():
        print(f"  [错误] 前端目录不存在: {FRONTEND_DIR}")
        return False
    
    # xuechong 2026-09-01 修复打包脚本 前端产物已存在且版本号一致时跳过重复构建（无 npm 环境也可直接打包）
    dist_dir = FRONTEND_DIR / 'dist'
    dist_index = dist_dir / 'index.html'
    if dist_dir.exists() and dist_index.exists():
        _dist_content = dist_index.read_text(encoding='utf-8', errors='replace')
        _meta_match = re.search(r'<meta name="app-version" content="([^"]+)"', _dist_content)
        if _meta_match and _meta_match.group(1) == VERSION:
            print(f"  [跳过] 前端产物已存在且版本一致 (V{VERSION})，跳过重复构建")
            return True
        print(f"  [提示] 前端产物版本不一致或缺失版本标记，重新构建")
    
    print("  安装依赖...")
    run_command("npm install", cwd=str(FRONTEND_DIR))
    
    print("  构建前端...")
    if run_command("npm run build", cwd=str(FRONTEND_DIR)):
        if dist_dir.exists():
            print(f"  [成功] 前端构建完成: {dist_dir}")
            return True
    
    print("  [错误] 前端构建失败")
    return False

def prepare_output_dir():
    """准备输出目录"""
    print_header("步骤 2/6: 准备输出目录")
    
    # 生成文件夹名称：crabapple-docstudio-v1.2.02
    folder_name = f"crabapple-docstudio-v{VERSION}"
    
    output_dir = DIST_DIR / folder_name
    
    # 如果已存在，先删除
    if output_dir.exists():
        print(f"  删除已有目录: {output_dir}")
        shutil.rmtree(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  [成功] 输出目录: {output_dir}")
    
    return output_dir, folder_name

def setup_python_embed(output_dir):
    """设置 Python 嵌入式版本"""
    print_header("步骤 3/6: 配置 Python 嵌入式版本")
    
    python_dir = output_dir / 'python'
    python_zip = PLUGINS_DIR / f'python-{PYTHON_EMBED_VERSION}-embed-amd64.zip'
    
    # 下载 Python 嵌入式版本
    if not python_zip.exists():
        print(f"  下载 Python {PYTHON_EMBED_VERSION} 嵌入式版本...")
        import urllib.request
        
        for url in [PYTHON_EMBED_URL_CN, PYTHON_EMBED_URL]:
            try:
                print(f"    尝试: {url[:50]}...")
                urllib.request.urlretrieve(url, python_zip)
                print(f"  [成功] 下载完成")
                break
            except Exception as e:
                print(f"    失败: {e}")
                continue
        else:
            print("  [错误] Python 下载失败")
            return False
    else:
        print(f"  使用缓存: {python_zip}")
    
    # 解压
    print(f"  解压到: {python_dir}")
    import zipfile
    with zipfile.ZipFile(python_zip, 'r') as zip_ref:
        zip_ref.extractall(python_dir)
    
    # 配置 Python 路径（修改 pth 文件）
    pth_files = list(python_dir.glob('*._pth'))
    for pth_file in pth_files:
        content = pth_file.read_text()
        content = content.replace('#import site', 'import site')
        content += '\nLib\\site-packages\n'
        pth_file.write_text(content)
    
    print("  [成功] Python 配置完成")
    return True

def setup_python_standalone(output_dir):
    """下载并配置 python-build-standalone（Linux 可迁移 Python，自带 _ssl）"""
    print_header("步骤 3/6: 配置 Linux Python 运行时 (python-build-standalone)")

    python_dir = output_dir / 'python'
    pbs_tar = PLUGINS_DIR / PBS_FILENAME

    # 下载（优先使用国内镜像）
    if not pbs_tar.exists() or pbs_tar.stat().st_size < 1024 * 1024:
        # 文件不存在或小于 1MB（可能是上次下载的错误页面），重新下载
        if pbs_tar.exists():
            print(f"  缓存文件过小 ({pbs_tar.stat().st_size} bytes)，重新下载...")
            pbs_tar.unlink()
        print(f"  下载 python-build-standalone {PBS_VERSION}...")
        print(f"  文件大小约 30MB，请耐心等待...")
        import urllib.request
        download_ok = False
        for url in [PBS_URL_CN, PBS_URL]:
            try:
                print(f"    尝试: {url}")
                urllib.request.urlretrieve(url, pbs_tar)
                # 下载后校验：文件必须是有效的 gzip（以 0x1f 0x8b 开头）
                with open(pbs_tar, 'rb') as f:
                    magic = f.read(2)
                if magic != b'\x1f\x8b':
                    size = pbs_tar.stat().st_size
                    # 读取前 200 字节看看是什么（可能是 HTML 错误页）
                    with open(pbs_tar, 'rb') as f:
                        preview = f.read(200)
                    print(f"    [失败] 下载的文件不是有效的 tar.gz（{size} bytes）")
                    print(f"    内容预览: {preview[:100]}")
                    pbs_tar.unlink()
                    continue
                print(f"  [成功] 下载完成: {pbs_tar.name} ({pbs_tar.stat().st_size / 1024 / 1024:.1f} MB)")
                download_ok = True
                break
            except Exception as e:
                print(f"    [失败] {e}")
                continue
        if not download_ok:
            print("")
            print("  [错误] python-build-standalone 下载失败！")
            print("")
            print("  解决方法：")
            print(f"  1. 手动下载文件:")
            print(f"     {PBS_URL}")
            print(f"  2. 放到: {pbs_tar}")
            print(f"  3. 重新运行打包脚本")
            print("")
            return False
    else:
        size_mb = pbs_tar.stat().st_size / 1024 / 1024
        print(f"  使用缓存: {pbs_tar.name} ({size_mb:.1f} MB)")

    # 解压（archive 内顶层目录就是 python/）
    # Windows 文件系统不允许 Linux 特殊字符（如 terminfo 中的文件名），需逐个解压并跳过
    print(f"  解压到: {python_dir}")
    try:
        with tarfile.open(pbs_tar, 'r:gz') as tar:
            skipped = 0
            for member in tar.getmembers():
                try:
                    tar.extract(member, path=output_dir)
                except (OSError, IOError):
                    skipped += 1
        if skipped > 0:
            print(f"  跳过 {skipped} 个 Windows 不兼容的文件（如 terminfo）")
    except Exception as e:
        print(f"  [错误] 解压失败: {e}")
        print(f"  文件可能已损坏，请删除 {pbs_tar} 后重新下载")
        return False

    # 验证关键文件存在（不能在 Windows 上执行 Linux 二进制，只检查文件）
    python_bin = python_dir / 'bin' / 'python3'
    if not python_bin.exists():
        print(f"  [错误] 解压后找不到 {python_bin}")
        return False

    lib_dir = python_dir / 'lib' / 'python3.11'
    if not lib_dir.exists():
        print(f"  [错误] 解压后找不到标准库: {lib_dir}")
        return False

    # 检查 _ssl 动态库是否存在（不能在 Windows 上执行 import ssl，只检查文件）
    ssl_so = list(lib_dir.glob('lib-dynload/_ssl*.so'))
    if not ssl_so:
        # 也检查 _ssl.cpython*.so 格式
        ssl_so = list((lib_dir / 'lib-dynload').glob('_ssl*.so')) if (lib_dir / 'lib-dynload').exists() else []
    if ssl_so:
        print(f"  SSL 模块: {ssl_so[0].name}")
    else:
        print(f"  [警告] 未找到 _ssl 动态库文件，将在目标服务器上验证")

    print(f"  解释器: {python_bin.name}")
    print(f"  标准库: {lib_dir}")
    print("  [成功] Linux Python 运行时配置完成（Windows 上跳过执行验证，目标服务器上自动验证）")
    return True

def install_dependencies(output_dir):
    """安装 Python 依赖"""
    print_header("步骤 4/6: 安装 Python 依赖")
    
    python_exe = output_dir / 'python' / 'python.exe'
    if not python_exe.exists():
        print(f"  [错误] Python 不存在: {python_exe}")
        return False
    
    # 下载并安装 pip
    get_pip_path = PLUGINS_DIR / 'get-pip.py'
    if not get_pip_path.exists():
        print("  下载 pip...")
        import urllib.request
        urllib.request.urlretrieve(GET_PIP_URL, get_pip_path)
    
    print("  安装 pip...")
    run_command(f'"{python_exe}" "{get_pip_path}"', timeout=300)
    
    # 复制 requirements.txt
    req_src = PROJECT_ROOT / 'requirements.txt'
    req_dst = output_dir / 'requirements.txt'
    if req_src.exists():
        shutil.copy(req_src, req_dst)
    
    # ============================================================
    # 第一步：安装 PyTorch CPU 版本（必须先安装，避免下载 GPU 版本）
    # ============================================================
    print("  [1/2] 安装 PyTorch CPU 版本（约200MB，请耐心等待）...")
    pytorch_cpu_url = "https://download.pytorch.org/whl/cpu"
    torch_cmd = f'"{python_exe}" -m pip install torch torchvision --index-url {pytorch_cpu_url}'
    
    if not run_command(torch_cmd, timeout=1800):
        print("  [警告] PyTorch CPU 安装失败，尝试国内镜像...")
        # 国内镜像备选（清华源有 CPU 版本）
        torch_cmd = f'"{python_exe}" -m pip install torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple'
        run_command(torch_cmd, timeout=1800)
    
    # ============================================================
    # 第二步：安装其他依赖
    # ============================================================
    print("  [2/2] 安装其他项目依赖...")
    pip_cmd = f'"{python_exe}" -m pip install -r "{req_dst}" -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn'
    
    if not run_command(pip_cmd, timeout=1800):
        print("  [警告] 国内镜像失败，尝试默认源...")
        pip_cmd = f'"{python_exe}" -m pip install -r "{req_dst}"'
        run_command(pip_cmd, timeout=1800)
    
    print("  [成功] 依赖安装完成")
    return True

def install_dependencies_linux(output_dir):
    """通过 WSL 将依赖预装到内置 Linux Python 中"""
    print_header("步骤 5/6: WSL 预装依赖到内置 Python")

    python_bin = output_dir / 'python' / 'bin' / 'python3'
    offline_dir = output_dir / 'assets' / 'linux' / 'wheels'
    req_file = output_dir / 'requirements.txt'

    # 检测 WSL 是否可用
    wsl_check = subprocess.run('wsl echo OK', shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if wsl_check.returncode != 0:
        print("  [错误] WSL 不可用！")
        print("  目标服务器无法联网，必须在打包阶段预装所有依赖。")
        print("  请安装 WSL2 后重新打包，或手动在 WSL 中安装依赖。")
        return False

    print("  WSL 已就绪")

    # 检查前置条件
    if not python_bin.exists():
        print(f"  [错误] 内置 Python 不存在: {python_bin}")
        return False
    if not offline_dir.exists():
        print(f"  [错误] 离线包目录不存在: {offline_dir}")
        return False

    # requirements.txt 可能还没被复制到 output_dir，先从项目根目录复制
    if not req_file.exists():
        req_src = PROJECT_ROOT / 'requirements.txt'
        if req_src.exists():
            shutil.copy(req_src, req_file)
            print(f"  已复制 requirements.txt 到输出目录")
        else:
            print(f"  [错误] requirements.txt 不存在: {req_src}")
            return False

    # 统计离线包数量
    whl_count = len(list(offline_dir.glob('*.whl')))
    print(f"  离线包目录: {offline_dir} ({whl_count} 个 whl 文件)")

    # Windows 路径 → WSL 路径转换
    def to_wsl(path):
        r = subprocess.run(f'wsl wslpath "{path}"', shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode != 0 or not r.stdout.strip():
            print(f"  [错误] WSL 路径转换失败: {path}")
            return None
        return r.stdout.strip()

    wsl_python = to_wsl(python_bin)
    wsl_offline = to_wsl(offline_dir)
    wsl_req = to_wsl(req_file)

    if not all([wsl_python, wsl_offline, wsl_req]):
        print("  [错误] WSL 路径转换失败，终止！")
        return False

    print(f"  WSL Python: {wsl_python}")
    print(f"  WSL 离线目录: {wsl_offline}")

    # 步骤1：用 requirements.txt + --find-links 安装（pip 自动解析依赖树，最高效）
    print("  [1/3] pip install -r requirements.txt --find-links (依赖树解析)")
    cmd1 = f'wsl "{wsl_python}" -m pip install --no-cache-dir --no-index --find-links="{wsl_offline}" -r "{wsl_req}"'
    print(f"  命令: {cmd1[:120]}...")
    r1 = subprocess.run(cmd1, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
    if r1.returncode == 0:
        print("  [成功] pip install --find-links 完成，所有依赖已安装")
    else:
        print(f"  [警告] pip install --find-links 返回非零 ({r1.returncode})，尝试逐个安装作为补充...")
        if r1.stderr:
            err_lines = r1.stderr.strip().split('\n')
            for line in err_lines[-5:]:
                print(f"    {line}")

        # 步骤2：逐个安装所有 whl（--no-deps，绕过平台标签检查，作为 fallback）
        print("  [2/3] 逐个安装所有 wheel 包 (--no-deps)")
        install_script = (
            'import subprocess, glob, sys\n'
            f'whls = sorted(glob.glob("{wsl_offline}/*.whl"))\n'
            'ok, fail = 0, 0\n'
            'for i, whl in enumerate(whls):\n'
            f'    r = subprocess.run(\n'
            f'        ["{wsl_python}", "-m", "pip", "install", "--no-cache-dir", "--no-deps", whl],\n'
            '        capture_output=True, text=True\n'
            '    )\n'
            '    if r.returncode == 0:\n'
            '        ok += 1\n'
            '    else:\n'
            '        fail += 1\n'
            "        if fail <= 5:\n"
            "            print(f'  [FAIL] {whl.rsplit(chr(47), 1)[-1]}: {r.stderr[:200]}', file=sys.stderr)\n"
            '    if (i+1) % 50 == 0:\n'
            "        print(f'  进度: {i+1}/{len(whls)}')\n"
            "print(f'  完成: {ok} 成功, {fail} 失败')\n"
            'sys.exit(1 if fail > 10 else 0)\n'
        )
        # 写入临时脚本文件
        tmp_script = output_dir / '_install_wheels.py'
        tmp_script.write_text(install_script, encoding='utf-8')
        wsl_tmp = to_wsl(tmp_script)
        if wsl_tmp:
            cmd2 = f'wsl "{wsl_python}" "{wsl_tmp}"'
            r2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=3600)
            if r2.stdout:
                for line in r2.stdout.strip().split('\n'):
                    print(f"  {line}")
            if r2.returncode != 0:
                print(f"  [警告] 部分 wheel 安装失败")
        tmp_script.unlink(missing_ok=True)

    # 步骤3：验证关键模块
    print("  [3/3] 验证关键模块...")
    critical = ['fastapi', 'uvicorn', 'cv2', 'numpy', 'PIL', 'fitz', 'doclayout_yolo', 'rapidocr', 'torch']
    missing = []
    for mod in critical:
        verify_cmd = f'wsl "{wsl_python}" -c "import {mod}"'
        r = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        if r.returncode == 0:
            print(f"    {mod}: OK")
        else:
            print(f"    {mod}: MISSING")
            missing.append(mod)

    if missing:
        print(f"\n  [错误] 以下关键模块缺失: {', '.join(missing)}")
        print("  目标服务器无法联网，依赖不完整将导致启动失败！")
        print("  请检查离线包目录是否包含所有必要的 whl 文件。")
        return False

    print("  [成功] 所有依赖安装完成")
    return True

def copy_source_files(output_dir):
    """复制源代码文件"""
    # print_header 由调用方统一输出，避免步骤编号冲突
    backend_src = PKG_DIR
    backend_dest = output_dir / 'backend'
    if backend_dest.exists():
        shutil.rmtree(backend_dest)
    shutil.copytree(backend_src, backend_dest,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.log'))

    # 复制核心文件
    print("  复制核心文件...")
    for file in ['start_server.py', 'requirements.txt', 'url.conf']:
        src = PROJECT_ROOT / file
        if src.exists():
            shutil.copy(src, output_dir / file)
            print(f"    {file}")
    
    # 复制前端构建产物
    frontend_dist = FRONTEND_DIR / 'dist'
    if frontend_dist.exists():
        print("  复制前端构建产物...")
        frontend_dest = output_dir / 'frontend' / 'dist'
        if frontend_dest.exists():
            shutil.rmtree(frontend_dest)
        shutil.copytree(frontend_dist, frontend_dest)
    
    # 复制 YOLO 模型文件（避免运行时从 Hugging Face 下载）
    print("  复制 YOLO 模型文件...")
    models_dir = output_dir / 'models'
    models_dir.mkdir(exist_ok=True)
    
    model_filename = 'doclayout_yolo_docstructbench_imgsz1024.pt'
    
    # 按优先级查找模型文件
    possible_model_paths = [
        # 1. 外部存储目录
        _DATA_DIR / 'models' / model_filename,
        # 2. 项目根目录
        PROJECT_ROOT / 'assets' / 'models' / model_filename,
    ]
    # 3. HF 缓存目录（从 url.conf 的 HF_HOME 读取）
    _hf_home = _url_conf.get('HF_HOME', '')
    if _hf_home:
        possible_model_paths.append(Path(_hf_home) / 'hub' / 'models--juliozhao--DocLayout-YOLO-DocStructBench')
    
    model_src = None
    for path in possible_model_paths:
        if path.is_file():
            model_src = path
            break
        elif path.is_dir():
            # 搜索目录中的模型文件
            for pt_file in path.rglob(model_filename):
                model_src = pt_file
                break
        if model_src:
            break
    
    if model_src and model_src.exists():
        model_dest = models_dir / model_filename
        shutil.copy(model_src, model_dest)
        print(f"    {model_filename} ({model_src.stat().st_size / 1024 / 1024:.1f} MB)")
        print(f"    来源: {model_src}")
    else:
        print(f"  [警告] 未找到模型文件，目标电脑需要能访问 huggingface.co")
        print(f"         或手动将 {model_filename} 放入 models 目录")
        print(f"         已搜索的路径:")
        for p in possible_model_paths:
            print(f"           - {p}")
    
    print("  [成功] 文件复制完成")
    return True

def create_scripts(output_dir):
    """创建启动和停止脚本"""
    print("  创建启动/停止脚本...")
    
    # Windows 启动脚本
    start_bat = output_dir / 'start.bat'
    start_bat.write_text(r'''@echo off
chcp 65001 >nul 2>&1
title 海棠文档工坊

echo ============================================================
echo   海棠文档工坊 - 启动服务
echo ============================================================
echo.

cd /d "%~dp0"
echo 当前目录: %CD%
echo.

echo [1/4] 检查是否有已运行的服务...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   发现端口8000被占用，正在停止旧服务 PID: %%a
    taskkill /F /PID %%a >nul 2>&1
    timeout /t 2 /nobreak >nul
)
echo   端口8000已就绪
echo.

echo [2/4] 检测Python环境...
if exist "%~dp0python\python.exe" (
    set "PYTHON_CMD=%~dp0python\python.exe"
    echo   使用内嵌Python: %~dp0python\python.exe
    goto check_dirs
)

where python >nul 2>&1
if %errorlevel% == 0 (
    set "PYTHON_CMD=python"
    echo   使用系统Python
    goto check_dirs
)

echo   [错误] 找不到Python环境!
pause
exit /b 1

:check_dirs
echo.
echo [3/4] 检查目录结构...

:: 从 url.conf 加载路径配置（仅在 Windows 上使用，Linux 用 start.sh）
if exist "url.conf" (
    for /f "usebackq eol=# tokens=1,2 delims==" %%a in ("url.conf") do (
        if not "%%a"=="" if not "%%b"=="" set "%%a=%%b"
    )
)

:: 检测 Linux 绝对路径（以 / 开头），Windows 上无效 → 清空触发回退
if defined DOCSTUDIO_BASE_DIR (
    echo %DOCSTUDIO_BASE_DIR%| findstr /b "/" >nul 2>&1
    if not errorlevel 1 set "DOCSTUDIO_BASE_DIR="
)

:: 统一回退默认值
if not defined DOCSTUDIO_BASE_DIR set "DOCSTUDIO_BASE_DIR=%CD%\data"

:: 衍生路径（自行计算，覆盖 url.conf 中含 ${} 的无效值）
set "DOCSTUDIO_DATA_DIR=%DOCSTUDIO_BASE_DIR%"
set "DOCSTUDIO_TMP_DIR=%DOCSTUDIO_BASE_DIR%\tmp"
set "DOCSTUDIO_DIST_DIR=%DOCSTUDIO_BASE_DIR%\dist"

:: 创建必要子目录
if not exist "%DOCSTUDIO_BASE_DIR%" mkdir "%DOCSTUDIO_BASE_DIR%"
if not exist "%DOCSTUDIO_BASE_DIR%\data" mkdir "%DOCSTUDIO_BASE_DIR%\data"
if not exist "%DOCSTUDIO_BASE_DIR%\data\original" mkdir "%DOCSTUDIO_BASE_DIR%\data\original"
if not exist "%DOCSTUDIO_BASE_DIR%\data\target" mkdir "%DOCSTUDIO_BASE_DIR%\data\target"
if not exist "%DOCSTUDIO_BASE_DIR%\logs" mkdir "%DOCSTUDIO_BASE_DIR%\logs"
if not exist "%DOCSTUDIO_BASE_DIR%\tmp" mkdir "%DOCSTUDIO_BASE_DIR%\tmp"
if not exist "%DOCSTUDIO_BASE_DIR%\plugins" mkdir "%DOCSTUDIO_BASE_DIR%\plugins"

echo   目录结构已就绪
echo.

:start_server
echo [4/4] 启动服务...
echo.

if not exist "start_server.py" (
    echo   [错误] 找不到 start_server.py!
    pause
    exit /b 1
)

echo ============================================================
echo   服务即将启动，日志将显示在下方
echo   按 Ctrl+C 可以停止服务
echo ============================================================
echo.

if exist "%~dp0python\python.exe" (
    "%~dp0python\python.exe" start_server.py
) else (
    python start_server.py
)

echo.
echo ============================================================
echo   服务已停止
echo ============================================================
echo.
echo 按任意键关闭此窗口...
pause >nul
''', encoding='utf-8')
    
    # Windows 停止脚本
    stop_bat = output_dir / 'stop.bat'
    stop_bat.write_text(r'''@echo off
chcp 65001 >nul 2>&1
title 海棠文档工坊 - 停止服务

echo ============================================================
echo   海棠文档工坊 - 停止服务
echo ============================================================
echo.

set FOUND=0

echo 正在查找8000端口的服务进程...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    set FOUND=1
    echo   发现服务进程 PID: %%a
    for /f "tokens=*" %%b in ('tasklist /FI "PID eq %%a" /FO CSV /NH 2^>nul') do (
        echo   进程信息: %%b
    )
    echo   正在停止进程...
    taskkill /F /PID %%a >nul 2>&1
    if errorlevel 1 (
        taskkill /F /T /PID %%a >nul 2>&1
    ) else (
        echo   进程 %%a 已停止
    )
)

if "%FOUND%"=="0" (
    echo.
    echo 未发现正在运行的服务（端口8000未被占用）
) else (
    echo.
    echo ============================================================
    echo   服务已停止，端口8000已释放
    echo   浏览器页面会显示"服务离线"提示
    echo ============================================================
)

echo.
echo 按任意键关闭此窗口...
pause >nul
''', encoding='utf-8')
    
    # Linux 启动脚本（必须用 LF 换行，否则 Linux 上无法执行）
    start_sh = output_dir / 'start.sh'
    write_unix_text(start_sh, r'''#!/bin/bash
# 海棠文档工坊 - Linux启动脚本

echo "============================================================"
echo "  海棠文档工坊 - 启动服务"
echo "============================================================"
echo ""

# 切换到脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
echo "当前目录: $(pwd)"
echo ""

# =============================================================
# 加载 url.conf 路径配置（必须在所有步骤之前，后续依赖查找需要 BASE_DIR）
# =============================================================
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
URL_CONF=""
if [ -f "$PARENT_DIR/url.conf" ]; then
    URL_CONF="$PARENT_DIR/url.conf"
elif [ -f "$SCRIPT_DIR/url.conf" ]; then
    URL_CONF="$SCRIPT_DIR/url.conf"
fi
if [ -n "$URL_CONF" ]; then
    set -a
    . "$URL_CONF"
    set +a
    echo "  已加载 url.conf: $URL_CONF"
else
    echo "  [提示] 未找到 url.conf，使用默认数据路径"
fi
BASE_DIR="${DOCSTUDIO_BASE_DIR:-${DOCSTUDIO_DATA_DIR:-/data/crabapple-docstudio}}"
export DOCSTUDIO_BASE_DIR="$BASE_DIR"
export DOCSTUDIO_DATA_DIR="$BASE_DIR"
echo "  数据目录: $BASE_DIR"
echo ""

# =============================================================
# [1/6] 检查并停止已运行的服务
# =============================================================
echo "[1/6] 检查是否有已运行的服务..."
PID=$(lsof -t -i:8000 2>/dev/null)
if [ -n "$PID" ]; then
    echo "  发现端口8000被占用，正在停止旧服务 PID: $PID"
    kill -9 "$PID" 2>/dev/null
    sleep 2
fi
echo "  端口8000已就绪"
echo ""

# =============================================================
# [2/6] 检测 Python 环境（优先使用依赖包的 .venv）
# =============================================================
echo "[2/6] 检测Python环境..."
PYTHON_CMD=""

# 验证 Python 可执行且 _ssl 模块可用
check_python() {
    local py="$1"
    if "$py" -c "import ssl" 2>/dev/null; then
        return 0
    fi
    return 1
}

# 查找依赖包的 .venv（$BASE_DIR/dependence/ 目录，位于持久化数据目录下）
DEPS_VENV=""
if [ -f "$BASE_DIR/dependence/.venv/bin/python3" ]; then
    if check_python "$BASE_DIR/dependence/.venv/bin/python3"; then
        DEPS_VENV="$BASE_DIR/dependence/.venv"
    fi
fi

# 优先级1: 依赖包的虚拟环境（推荐）
if [ -n "$DEPS_VENV" ]; then
    PYTHON_CMD="$DEPS_VENV/bin/python3"
    echo "  使用依赖包虚拟环境: $DEPS_VENV"
    echo "  Python: $($PYTHON_CMD --version 2>&1)"

# 优先级2: 程序包内置的虚拟环境（兼容旧版一体包）
elif [ -f "$SCRIPT_DIR/.venv/bin/python3" ] && check_python "$SCRIPT_DIR/.venv/bin/python3"; then
    PYTHON_CMD="$SCRIPT_DIR/.venv/bin/python3"
    echo "  使用内置虚拟环境: $SCRIPT_DIR/.venv"
    echo "  Python: $($PYTHON_CMD --version 2>&1)"

# 优先级3: 打包内置的 python-build-standalone
elif [ -f "$SCRIPT_DIR/python/bin/python3" ] && check_python "$SCRIPT_DIR/python/bin/python3"; then
    PYTHON_CMD="$SCRIPT_DIR/python/bin/python3"
    echo "  使用内置Python: $SCRIPT_DIR/python/bin/python3"
    echo "  Python: $($PYTHON_CMD --version 2>&1)"

# 优先级4: 系统 Python（兜底）
else
    for cmd in python3.11 /usr/local/bin/python3.11 /usr/bin/python3.11 python3.10 python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            PYTHON_CMD="$cmd"
            echo "  使用系统Python: $cmd"
            echo "  Python: $($PYTHON_CMD --version 2>&1)"
            break
        fi
    done
fi

if [ -z "$PYTHON_CMD" ]; then
    echo ""
    echo "  [错误] 找不到任何可用的 Python 环境！"
    echo "  请安装 Python 3.11 或先部署依赖包到 \$BASE_DIR/dependence/"
    exit 1
fi

# 最终验证 _ssl
if ! $PYTHON_CMD -c "import ssl" 2>/dev/null; then
    echo "  [警告] Python 缺少 _ssl 模块，pip 和网络功能将不可用"
fi
echo ""

# 设置服务器环境变量（无桌面环境不打开浏览器）
export NO_BROWSER=1

# =============================================================
# [3/6] 检测 GPU 环境（GPU 优先，无 GPU 则回退 CPU）
# =============================================================
echo "[3/6] 检测 GPU 环境..."
GPU_AVAILABLE=0
GPU_COUNT=0

if command -v nvidia-smi &> /dev/null; then
    echo "  nvidia-smi 已找到"
    # 获取 GPU 信息
    GPU_INFO=$(nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$GPU_INFO" ]; then
        GPU_AVAILABLE=1
        GPU_COUNT=$(echo "$GPU_INFO" | wc -l)
        echo "  ★★★ 检测到 $GPU_COUNT 块 NVIDIA GPU ★★★"
        echo "$GPU_INFO" | while IFS= read -r line; do
            echo "    GPU $line"
        done

        # 显示 CUDA 驱动版本
        DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
        CUDA_VER=$(nvidia-smi 2>/dev/null | grep "CUDA Version" | sed 's/.*CUDA Version: \([0-9.]*\).*/\1/')
        echo "  NVIDIA 驱动版本: $DRIVER_VER"
        echo "  CUDA 驱动版本:   $CUDA_VER"
    else
        echo "  nvidia-smi 执行失败，GPU 可能未正确安装驱动"
    fi
else
    echo "  未检测到 nvidia-smi，将使用 CPU 模式运行"
fi

# 设置 CUDA 环境变量
if [ "$GPU_AVAILABLE" -eq 1 ]; then
    # CUDA_VISIBLE_DEVICES：如果用户未设置，默认使用所有 GPU
    if [ -z "$CUDA_VISIBLE_DEVICES" ]; then
        # 使用所有检测到的 GPU
        ALL_GPU_IDS=$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | tr '\n' ',' | sed 's/,$//')
        export CUDA_VISIBLE_DEVICES="$ALL_GPU_IDS"
        echo "  CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES（使用全部 GPU）"
    else
        echo "  CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES（用户指定）"
    fi

    # LD_LIBRARY_PATH：确保能找到 CUDA 运行时库
    CUDA_LIB_PATHS="/usr/local/cuda-12.8/lib64:/usr/local/cuda-12/lib64:/usr/local/cuda/lib64:/usr/lib64"
    if [ -n "$LD_LIBRARY_PATH" ]; then
        export LD_LIBRARY_PATH="$CUDA_LIB_PATHS:$LD_LIBRARY_PATH"
    else
        export LD_LIBRARY_PATH="$CUDA_LIB_PATHS"
    fi
    echo "  LD_LIBRARY_PATH 已设置（包含 CUDA 库路径）"

    # 设置环境变量告知 Python 程序 GPU 可用
    export DOCSTUDIO_USE_GPU=1
    echo "  DOCSTUDIO_USE_GPU=1（GPU 加速已启用）"
else
    export DOCSTUDIO_USE_GPU=0
    echo "  DOCSTUDIO_USE_GPU=0（CPU 模式）"
fi
echo ""

# =============================================================
# [4/6] 验证依赖完整性（优先使用外部依赖包，兼容旧版一体包）
# =============================================================
echo "[4/6] 验证依赖..."
MISSING_DEPS=""
for mod in fastapi uvicorn cv2 numpy PIL fitz doclayout_yolo rapidocr torch; do
    if ! $PYTHON_CMD -c "import $mod" 2>/dev/null; then
        MISSING_DEPS="$MISSING_DEPS $mod"
    fi
done

if [ -n "$MISSING_DEPS" ]; then
    echo "  缺失模块:$MISSING_DEPS"

    # 查找离线包目录（优先外部依赖包，兼容旧版一体包）
    OFFLINE_DIR=""
    if [ -d "$BASE_DIR/dependence/wheels" ]; then
        OFFLINE_DIR="$BASE_DIR/dependence/wheels"
        echo "  使用外部依赖包: $OFFLINE_DIR"
    elif [ -d "$SCRIPT_DIR/assets/linux/wheels" ]; then
        OFFLINE_DIR="$SCRIPT_DIR/assets/linux/wheels"
        echo "  使用内置离线包: $OFFLINE_DIR"
    fi

    if [ -n "$OFFLINE_DIR" ]; then
        echo "  尝试从离线包补充安装..."

        # 方式1：用 requirements.txt + --find-links
        if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
            $PYTHON_CMD -m pip install --no-cache-dir --no-index --find-links="$OFFLINE_DIR" -r "$SCRIPT_DIR/requirements.txt" 2>&1 | tee -a "$SCRIPT_DIR/install.log"
        fi

        # 方式2：逐个安装所有 whl（--no-deps，绕过平台标签检查）
        for whl in "$OFFLINE_DIR"/*.whl; do
            $PYTHON_CMD -m pip install --no-cache-dir --no-deps "$whl" 2>/dev/null
        done

        # 重新验证
        STILL_MISSING=""
        for mod in fastapi uvicorn cv2 numpy PIL fitz doclayout_yolo rapidocr torch; do
            if ! $PYTHON_CMD -c "import $mod" 2>/dev/null; then
                STILL_MISSING="$STILL_MISSING $mod"
            fi
        done

        if [ -n "$STILL_MISSING" ]; then
            echo "  [错误] 以下模块安装后仍缺失:$STILL_MISSING"
            echo ""
            echo "  排查方法:"
            echo "    查看安装日志: cat $SCRIPT_DIR/install.log"
            echo "    手动测试: $PYTHON_CMD -c \"import fastapi, uvicorn, cv2, torch\""
            exit 1
        else
            echo "  [成功] 所有依赖已就绪"
        fi
    else
        echo "  [错误] 未找到离线包！"
        echo ""
        echo "  请先部署依赖包:"
        echo "    1. 解压依赖包: tar -xzf crabapple-docstudio-deps-v*.tar.gz"
        echo "    2. 安装依赖: cd dependence && ./install_deps.sh"
        echo "    3. 移动到持久化目录: mv dependence \$BASE_DIR/dependence/"
        exit 1
    fi
else
    echo "  所有关键依赖已就绪"
fi

# GPU 可用时，确保使用 onnxruntime-gpu（提升 OCR 速度）
if [ "$GPU_AVAILABLE" -eq 1 ]; then
    ORT_GPU_INSTALLED=$($PYTHON_CMD -c "import onnxruntime; print('CUDAExecutionProvider' in onnxruntime.get_available_providers())" 2>/dev/null)
    if [ "$ORT_GPU_INSTALLED" != "True" ]; then
        echo "  [GPU] 尝试安装 onnxruntime-gpu..."
        # 查找离线包
        ORT_OFFLINE_DIR=""
        if [ -d "$BASE_DIR/dependence/wheels" ]; then
            ORT_OFFLINE_DIR="$BASE_DIR/dependence/wheels"
        elif [ -d "$SCRIPT_DIR/assets/linux/wheels" ]; then
            ORT_OFFLINE_DIR="$SCRIPT_DIR/assets/linux/wheels"
        fi
        if [ -n "$ORT_OFFLINE_DIR" ]; then
            ORT_GPU_WHL=$(ls -1 "$ORT_OFFLINE_DIR"/onnxruntime_gpu-*.whl 2>/dev/null | head -1)
            if [ -n "$ORT_GPU_WHL" ]; then
                $PYTHON_CMD -m pip install --no-cache-dir --no-deps "$ORT_GPU_WHL" 2>/dev/null
                echo "  [GPU] onnxruntime-gpu 安装完成"
            fi
        fi
    else
        echo "  [GPU] onnxruntime-gpu 已就绪（CUDA 加速 OCR）"
    fi
fi
echo ""

# =============================================================
# [5/6] 检查目录结构
# =============================================================
echo "[5/6] 检查目录结构..."
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

# =============================================================
# [6/6] 启动服务（后台守护进程）
# =============================================================
echo "[6/6] 启动服务..."
echo ""

if [ ! -f "start_server.py" ]; then
    echo "  [错误] 找不到 start_server.py!"
    echo "  当前目录: $(pwd)"
    exit 1
fi

# 统一日志文件（一个文件包含所有日志）
LOG_FILE="$BASE_DIR/logs/crabapple-docstudio.log"
PID_FILE="$SCRIPT_DIR/DOCSTUDIO.pid"

echo "============================================================"
echo "  服务配置:"
echo "    GPU: $([ "$GPU_AVAILABLE" -eq 1 ] && echo "${GPU_COUNT}x NVIDIA GPU (已启用)" || echo "未检测到 (CPU模式)")"
echo "    日志文件: $LOG_FILE"
echo "    PID文件:  $PID_FILE"
echo "============================================================"
echo ""

# 以守护进程方式启动（nohup + 后台运行，所有输出统一到一个日志文件）
nohup $PYTHON_CMD start_server.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# 等待几秒检查服务是否成功启动
sleep 3
if kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "============================================================"
    echo "  [成功] 服务已在后台启动"
    echo "    PID:  $SERVER_PID"
    echo "    端口: http://0.0.0.0:8000"
    echo ""
    echo "  日志文件: $LOG_FILE"
    echo ""
    echo "  常用命令:"
    echo "    查看实时日志: tail -f $LOG_FILE"
    echo "    停止服务:     ./stop.sh"
    echo "    查看进程:     ps -p $SERVER_PID"
    echo "============================================================"
else
    echo "  [错误] 服务启动失败！查看日志:"
    echo "    tail -50 $LOG_FILE"
    echo ""
    tail -20 "$LOG_FILE" 2>/dev/null
    exit 1
fi
''')
    
    # Linux 停止脚本
    stop_sh = output_dir / 'stop.sh'
    write_unix_text(stop_sh, r'''#!/bin/bash
# 海棠文档工坊 - Linux停止脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/DOCSTUDIO.pid"

echo "============================================================"
echo "  海棠文档工坊 - 停止服务"
echo "============================================================"
echo ""

FOUND=0

# 方法1: 通过 PID 文件停止
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    echo "[1/3] 通过 PID 文件停止 (PID: $PID)..."
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        sleep 2
        # 如果还没退出，强制杀
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null
        fi
        echo "  已停止进程 $PID"
        FOUND=1
    else
        echo "  PID $PID 已不存在"
    fi
    rm -f "$PID_FILE"
else
    echo "[1/3] 未找到 PID 文件，跳过"
fi

# 方法2: 通过端口查找进程
echo ""
echo "[2/3] 检查端口 8000..."
PIDS=$(lsof -t -i:8000 2>/dev/null)
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo "  发现进程 PID: $PID"
        kill -9 "$PID" 2>/dev/null
        echo "  已停止进程 $PID"
        FOUND=1
    done
fi

# 方法3: 通过进程名查找
echo ""
echo "[3/3] 检查 Python 服务进程..."
PIDS=$(pgrep -f "start_server.py" 2>/dev/null)
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        echo "  发现 Python 进程 PID: $PID"
        kill -9 "$PID" 2>/dev/null
        echo "  已停止进程 $PID"
        FOUND=1
    done
fi

# 等待进程结束
sleep 2

# 验证端口是否释放
echo ""
if lsof -i:8000 >/dev/null 2>&1; then
    echo "  [警告] 端口 8000 仍被占用!"
    echo "  请使用 'kill -9 PID' 手动结束相关进程"
else
    if [ "$FOUND" -eq 1 ]; then
        echo "============================================================"
        echo "  服务已停止，端口 8000 已释放"
        echo "============================================================"
    else
        echo "  未发现运行中的服务"
    fi
fi
echo ""
''')
    
    print("  [成功] 脚本创建完成")

def copy_offline_packages(output_dir, platform: str):
    """复制离线依赖包到输出目录"""
    print("  复制离线依赖包...")
    
    # 查找离线包目录
    offline_packages_paths = [
        DIST_DIR / 'assets' / 'linux' / 'wheels',
        PROJECT_ROOT.parent / 'dist' / 'assets' / 'linux' / 'wheels',
        PROJECT_ROOT / 'assets' / 'linux' / 'wheels',
    ]
    
    offline_src = None
    for path in offline_packages_paths:
        if path.exists() and list(path.glob('*.whl')):
            offline_src = path
            break
    
    if offline_src:
        offline_dest = output_dir / 'assets' / 'linux' / 'wheels'
        if offline_dest.exists():
            shutil.rmtree(offline_dest)
        shutil.copytree(offline_src, offline_dest)
        
        whl_count = len(list(offline_dest.glob('*.whl')))
        total_size = sum(f.stat().st_size for f in offline_dest.iterdir() if f.is_file())
        print(f"    复制了 {whl_count} 个包 ({total_size / 1024 / 1024:.1f} MB)")
        print(f"    来源: {offline_src}")
        return True
    else:
        print(f"  [警告] 未找到离线依赖包！")
        print(f"         请先运行: python scripts/download_offline_deps.py --platform {platform}")
        print(f"         已搜索的路径:")
        for p in offline_packages_paths:
            print(f"           - {p}")
        return False

def create_readme(output_dir, folder_name, has_offline_packages=False):
    """创建 README"""
    readme = output_dir / 'README.md'

    # 检查是否包含内置 Python 运行时
    has_bundled_python = (output_dir / 'python' / 'bin' / 'python3').exists()

    if has_bundled_python:
        # 内置 Python：部署最简
        linux_install_steps = f'''```bash
# 解压
tar -xzf {folder_name}.tar.gz
cd {folder_name}

# 启动（内置 Python + 依赖，无需额外安装）
chmod +x start.sh stop.sh
./start.sh

# 停止
./stop.sh
```'''
    else:
        # 精简程序包：依赖通过外部 dependence 目录提供（位于持久化数据目录下）
        linux_install_steps = f'''```bash
# 1. 部署依赖包（只需一次，版本更新不用重复部署）
tar -xzf crabapple-docstudio-deps-v*.tar.gz
cd dependence
chmod +x install_deps.sh
./install_deps.sh
cd .. && mv dependence /data/crabapple-docstudio/dependence

# 2. 部署程序包
tar -xzf {folder_name}.tar.gz
cd {folder_name}

# 3. 启动（自动找到 /data/crabapple-docstudio/dependence/.venv）
chmod +x start.sh stop.sh
./start.sh

# 停止
./stop.sh
```'''
    
    readme.write_text(f'''# 海棠文档工坊

版本: V{VERSION}
打包时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Windows 使用方法

1. 解压 `{folder_name}.zip`
2. 双击 `start.bat` 启动服务
3. 浏览器访问 http://localhost:8000
4. 双击 `stop.bat` 停止服务

## Linux 使用方法（支持离线部署）

{linux_install_steps}

## 日志文件位置

统一日志文件：`~/crabapple-docstudio/logs/crabapple-docstudio.log`

> 说明：`~/crabapple-docstudio` 为默认数据目录（`$BASE_DIR`），所有日志（服务日志、应用日志、uvicorn 访问日志）统一输出到一个文件。

**查看日志命令：**
```bash
# 实时查看日志
tail -f ~/crabapple-docstudio/logs/crabapple-docstudio.log

# 查看最近100行
tail -n 100 ~/crabapple-docstudio/logs/crabapple-docstudio.log
```

## 功能特点

- 支持中文目录名和文件名
- 拖拽上传或点击上传
- 一键修图（批量净化图片）
- 一键合成 PDF
- 下载历史记录（持久化存储）
- 实时进度显示
- 服务状态心跳检测

## 技术栈

- 前端: Vue 3 + Vite
- 后端: FastAPI + YOLO
- PDF: PyMuPDF

## 故障排查

1. **缺少模块错误**: 确保已运行离线安装脚本
2. **日志无时间戳**: 查看 `~/crabapple-docstudio/logs/crabapple-docstudio.log`，所有日志格式为 `[年-月-日 时:分:秒.毫秒]`
3. **YOLO模型缺失**: 确保 `models/` 目录下有 `.pt` 模型文件
''', encoding='utf-8')
    
    print("  [成功] README 创建完成")

def create_packages(output_dir, folder_name, target_platform='windows'):
    """创建压缩包

    Args:
        output_dir: 输出目录
        folder_name: 文件夹名称
        target_platform: 目标平台 'windows' 或 'linux'
    """
    
    zip_path = None
    tar_path = None
    
    if target_platform == 'windows':
        # 只创建 Windows ZIP
        print("  创建 Windows 压缩包...")
        zip_path = DIST_DIR / f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in output_dir.rglob('*'):
                if file_path.is_file():
                    arcname = f"{folder_name}/{file_path.relative_to(output_dir)}"
                    zipf.write(file_path, arcname)
        
        zip_size = zip_path.stat().st_size / (1024 * 1024)
        print(f"  [成功] {zip_path.name} ({zip_size:.1f} MB)")
    
    elif target_platform == 'linux':
        # 只创建 Linux tar.gz
        print("  创建 Linux 压缩包...")
        tar_path = DIST_DIR / f"{folder_name}.tar.gz"
        with tarfile.open(tar_path, 'w:gz') as tar:
            tar.add(output_dir, arcname=folder_name)
        
        tar_size = tar_path.stat().st_size / (1024 * 1024)
        print(f"  [成功] {tar_path.name} ({tar_size:.1f} MB)")
    
    else:
        # 兼容模式：两个都创建
        print("  创建 Windows 压缩包...")
        zip_path = DIST_DIR / f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in output_dir.rglob('*'):
                if file_path.is_file():
                    arcname = f"{folder_name}/{file_path.relative_to(output_dir)}"
                    zipf.write(file_path, arcname)
        zip_size = zip_path.stat().st_size / (1024 * 1024)
        print(f"  [成功] {zip_path.name} ({zip_size:.1f} MB)")
        
        print("  创建 Linux 压缩包...")
        tar_path = DIST_DIR / f"{folder_name}.tar.gz"
        with tarfile.open(tar_path, 'w:gz') as tar:
            tar.add(output_dir, arcname=folder_name)
        tar_size = tar_path.stat().st_size / (1024 * 1024)
        print(f"  [成功] {tar_path.name} ({tar_size:.1f} MB)")
    
    return zip_path, tar_path

def main():
    """主函数"""
    import argparse
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='海棠文档工坊 - 打包发布')
    parser.add_argument('--platform', '-p', choices=['windows', 'linux', 'all'],
                        default='windows', help='目标平台: windows, linux, all (默认: windows)')
    args = parser.parse_args()
    
    target_platform = args.platform
    
    print()
    print("=" * 70)
    print("  海棠文档工坊 - 打包发布")
    print("=" * 70)
    print(f"  版本: V{VERSION} (从 App.vue 自动读取)")
    print(f"  目标平台: {target_platform}")

    print(f"  项目路径: {PROJECT_ROOT}")
    print(f"  输出路径: {DIST_DIR}")
    print(f"  输出名称: crabapple-docstudio-v{VERSION}")
    print(f"  日期: {datetime.now().strftime('%Y-%m-%d')}")
    print()
    
    # 1. 构建前端
    if not build_frontend():
        print("\n[错误] 前端构建失败，终止打包")
        return False
    
    # 2. 准备输出目录
    output_dir, folder_name = prepare_output_dir()
    
    # 3. 配置 Python / 平台相关设置
    has_offline = False
    if target_platform == 'windows' and sys.platform == 'win32':
        if not setup_python_embed(output_dir):
            print("\n[警告] Python 嵌入式版本配置失败，继续打包...")
        else:
            # 4. 安装依赖（Windows 在线安装）
            install_dependencies(output_dir)
    elif target_platform == 'linux':
        # Linux 精简打包：不包含离线依赖包和 Python 运行时
        # 依赖包通过 pack_deps.py 单独打包，部署到服务器后长期不变
        print_header("步骤 3/6: Linux 精简模式（不含离线依赖）")
        print("  依赖包需通过 pack_deps.py 单独打包")
        print("  程序包启动时自动从 \\$BASE_DIR/dependence/.venv 读取依赖")

    # 5. 复制源代码
    print_header("步骤 4/6: 复制项目文件")
    copy_source_files(output_dir)

    # 6. 创建脚本
    print_header("步骤 5/6: 创建启动脚本")
    create_scripts(output_dir)

    # 7. 创建 README
    create_readme(output_dir, folder_name, has_offline)

    # 8. 创建压缩包
    print_header("步骤 6/6: 创建压缩包")
    zip_path, tar_path = create_packages(output_dir, folder_name, target_platform)
    
    # 完成
    print()
    print("=" * 70)
    print("  打包完成!")
    print("=" * 70)
    print()
    print(f"  输出目录: {output_dir}")
    print()
    print("  压缩包:")
    if zip_path:
        print(f"    Windows: {zip_path}")
    if tar_path:
        print(f"    Linux:   {tar_path}")
    print()
    
    return True

if __name__ == '__main__':
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n用户取消操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
