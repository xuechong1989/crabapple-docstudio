"""测试服务启动模块：导入、依赖检测、GPU 诊断。"""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


class TestServerImport:
    """server 模块导入和结构检查。"""

    def test_server_module_importable(self):
        """server.py 可导入。"""
        from backend import server
        assert server is not None

    def test_main_function_exists(self):
        """server.py 有 callable 的 main() 函数。"""
        from backend.server import main
        assert callable(main)

    def test_get_storage_root(self):
        """_get_storage_root() 返回基于 config.DATA_DIR 的路径。"""
        from backend.server import _get_storage_root
        result = _get_storage_root()
        assert result is not None
        assert result.exists()

    def test_log_function(self):
        """_log() 函数存在且可调用。"""
        from backend.server import _log
        assert callable(_log)


class TestServerStructure:
    """server.py 代码结构检查。"""

    @pytest.fixture
    def server_source(self):
        return (PROJECT_ROOT / "backend" / "server.py").read_text(encoding="utf-8")

    def test_has_dependency_check(self, server_source):
        """main() 包含依赖检查逻辑。"""
        assert "uvicorn" in server_source
        assert "fastapi" in server_source

    def test_has_gpu_detection(self, server_source):
        """main() 包含 GPU 检测逻辑。"""
        assert "torch" in server_source
        assert "cuda" in server_source.lower()

    def test_has_storage_init(self, server_source):
        """main() 初始化存储目录。"""
        assert "data_dir" in server_source
        assert "logs_dir" in server_source
        assert "tmp_dir" in server_source

    def test_no_bare_config_import(self, server_source):
        """server.py 不使用裸 import config。"""
        import re
        bare = re.findall(r"^\s*import config\b", server_source, re.MULTILINE)
        assert len(bare) == 0, "server.py 包含裸 'import config'"

    def test_uses_relative_config_import(self, server_source):
        """server.py 使用 from . import config。"""
        assert "from . import config" in server_source


class TestDependencyDetection:
    """依赖缺失时的检测逻辑。"""

    def test_missing_dep_list_complete(self):
        """缺失依赖列表覆盖核心包。"""
        server_source = (PROJECT_ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        for pkg in ("uvicorn", "fastapi", "cv2", "numpy", "PIL", "fitz"):
            assert pkg in server_source, f"依赖检测未覆盖: {pkg}"


class TestEndpointFilter:
    """日志过滤类检查。"""

    def test_endpoint_filter_class(self):
        """EndpointFilter 类存在。"""
        from backend.server import EndpointFilter
        assert EndpointFilter is not None

    def test_endpoint_filter_filters_health(self):
        """EndpointFilter 过滤 /api/health 请求。"""
        import logging
        from backend.server import EndpointFilter
        f = EndpointFilter()
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, "", 0,
            "GET /api/health HTTP/1.1 200", (), None
        )
        assert f.filter(record) is False

    def test_endpoint_filter_passes_normal(self):
        """EndpointFilter 不过滤普通请求。"""
        import logging
        from backend.server import EndpointFilter
        f = EndpointFilter()
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, "", 0,
            "GET /api/some-endpoint HTTP/1.1 200", (), None
        )
        assert f.filter(record) is True
