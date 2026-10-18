"""crabapple-docstudio 测试套件 — 共享夹具、条件跳过标记、测试工具。"""
import os
from pathlib import Path

import pytest

# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 测试默认认证口令哈希（与环境变量 DOCSTUDIO_AUTH_HASH 对齐）
# xuechong 2026-08-17 研发BUG-0023-图档扫描-3.1.04-测试认证哈希不同步修复 V3.1.03 服务端默认口令改为 测试口令（auth.py _DEFAULT_PASSWORD_HASH）时本默认值未同步，test_admin_status 等 401
_TEST_AUTH_HASH = os.environ.get(
    'DOCSTUDIO_AUTH_HASH',
    '103e4cce4376cf4c1a32f3c49d8a75dec4674f0b639fa3ebe308b74059d54d92'
)
# 测试专用：在导入 backend 之前注入旧版兼容登录哈希，避免测试依赖生产默认口令。
os.environ.setdefault('DOCSTUDIO_AUTH_HASH', _TEST_AUTH_HASH)

# ============================================================
# 条件跳过检测（模块级别，在导入 backend 之前）
# ============================================================

def _has_rapidocr():
    try:
        import rapidocr  # noqa: F401
        return True
    except ImportError:
        return False




def _has_gpu():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _has_yolo():
    try:
        from doclayout_yolo import YOLOv10  # noqa: F401
        return True
    except ImportError:
        return False


# ============================================================
# 自定义 pytest 标记
# ============================================================

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 耗时较长的测试（需 --run-slow）")
    config.addinivalue_line("markers", "gpu: 需要 GPU/CUDA 的测试（需 --run-gpu）")
    config.addinivalue_line("markers", "rapidocr: 需要 RapidOCR 的测试")
    config.addinivalue_line("markers", "yolo: 需要 YOLO 模型的测试")
    config.addinivalue_line("markers", "testcase: 需要真实扫描件 testcase 的测试")


def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", default=False, help="运行耗时测试")
    parser.addoption("--run-gpu", action="store_true", default=False, help="运行 GPU 依赖测试")


def pytest_collection_modifyitems(config, items):
    """根据标记和命令行参数自动跳过测试。"""
    run_slow = config.getoption("--run-slow")
    run_gpu = config.getoption("--run-gpu")

    for item in items:
        # GPU 测试：仅在 --run-gpu 时运行
        if "gpu" in item.keywords and not run_gpu:
            item.add_marker(pytest.mark.skip(reason="GPU 测试，使用 --run-gpu 启用"))
        # 慢测试：仅在 --run-slow 时运行
        if "slow" in item.keywords and not run_slow:
            item.add_marker(pytest.mark.skip(reason="耗时测试，使用 --run-slow 启用"))
        # RapidOCR 不可用时跳过
        if "rapidocr" in item.keywords and not _has_rapidocr():
            item.add_marker(pytest.mark.skip(reason="RapidOCR 未安装"))
        # YOLO 不可用时跳过
        if "yolo" in item.keywords and not _has_yolo():
            item.add_marker(pytest.mark.skip(reason="doclayout_yolo 或 YOLO 模型不可用"))
        # testcase 目录不存在时跳过
        if "testcase" in item.keywords:
            tc = _get_testcase_dir()
            if tc is None:
                item.add_marker(pytest.mark.skip(
                    reason="testcase 目录不存在，可通过 DOCSTUDIO_TESTCASE_DIR 指定"
                ))


def _get_testcase_dir():
    """获取 testcase 目录路径（不存在时返回 None）。"""
    candidates = []
    env_dir = os.environ.get("DOCSTUDIO_TESTCASE_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.extend([Path("tests/testcase"), Path("testcase")])
    for p in candidates:
        if p.is_dir():
            return p
    return None


# ============================================================
# Session 级夹具
# ============================================================

@pytest.fixture(scope="session")
def project_config():
    """加载项目配置（session 级，整个测试运行只加载一次）。"""
    from backend import config
    return config


@pytest.fixture(scope="session")
def testcase_dir():
    """真实测试扫描件目录。"""
    tc = _get_testcase_dir()
    if tc is None:
        pytest.skip("testcase 目录不可用")
    return tc


@pytest.fixture(scope="session")
def app_client():
    """FastAPI TestClient（session 级，复用避免重复初始化）。

    xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 创建后自动登录，避免所有受保护端点返回 401。
    """
    from backend.app import app
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 使用兼容口令自动登录，获取 JWT cookie
        client.post("/api/auth/verify", json={"password": _TEST_AUTH_HASH})
        yield client


@pytest.fixture(scope="session")
def ocr_engine():
    """RapidOCR 引擎实例（session 级，复用避免重复加载模型）。"""
    pytest.importorskip("rapidocr", reason="RapidOCR 未安装")
    from backend.ocr_rapid import get_rapid_ocr_engine
    return get_rapid_ocr_engine(ocr_lang="ch")


@pytest.fixture(scope="session")
def cleaner():
    """DocumentCleaner 实例（session 级，预热 YOLO 模型）。"""
    pytest.importorskip("doclayout_yolo", reason="doclayout_yolo 未安装")
    from backend import DocumentCleaner
    return DocumentCleaner()


# ============================================================
# Function 级夹具
# ============================================================

@pytest.fixture
def test_output_dir(project_config):
    """测试输出目录（每个测试函数独立，function 级）。"""
    out = project_config.DATA_DIR / "test_output"
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture
def synthetic_image():
    """合成测试文档图像：白色背景 + 黑色文字 + 圆圈。返回 BGR numpy array。"""
    import numpy as np
    from PIL import Image, ImageDraw

    w, h = 800, 1100
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    lines = [
        "测试文档 Test Document",
        "第二行文字 Second Line",
        "12345 67890 ABCDE",
        "智能文档扫描系统",
    ]
    y = 50
    for line in lines:
        draw.text((50, y), line, fill="black")
        y += 60
    # 模拟装订孔
    draw.ellipse([w - 100, h - 100, w - 60, h - 60], outline="black", width=2)
    arr = np.array(img)
    # RGB → BGR
    return arr[:, :, ::-1].copy()


@pytest.fixture
def testcase_images(testcase_dir):
    """testcase 目录下所有 TIF/TIFF 图片路径列表。"""
    images = []
    for ext in ("*.tif", "*.tiff", "*.TIF", "*.TIFF"):
        images.extend(testcase_dir.glob(ext))
    if not images:
        pytest.skip("testcase 目录中没有 TIF 图片")
    return sorted(images)


@pytest.fixture
def testcase_first_image(testcase_images):
    """testcase 中第一张 TIF 图片路径。"""
    return testcase_images[0]
