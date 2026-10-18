"""测试包导入完整性：模块导入、相对导入、入口点。"""
import re
import sys
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
PKG_DIR = PROJECT_ROOT / "backend"

# 包内模块名
_PKG_MODULES = {"config", "cleaner", "ocr_pdf", "ocr_rapid", "app", "server", "service_manager"}
# 预期可导入的模块
_EXPECTED_MODULES = [
    "backend",
    "backend.config",
    "backend.server",
    "backend.app",
    "backend.ocr_rapid",
    "backend.ocr_pdf",
    "backend.__init__",
    "backend.__main__",
]


class TestImportIntegrity:
    """每个 backend 模块都应可被导入。"""

    @pytest.mark.parametrize("module_name", _EXPECTED_MODULES)
    def test_module_importable(self, module_name):
        """验证模块可直接导入，无 ImportError。"""
        __import__(module_name)

    def test_config_importable(self):
        """验证 config 从包导入可用。"""
        from backend import config
        assert hasattr(config, "DATA_DIR")

    def test_document_cleaner_lazy_import(self):
        """DocumentCleaner 通过懒加载导出。"""
        from backend import DocumentCleaner
        assert DocumentCleaner is not None


class TestRelativeImports:
    """包内模块之间必须使用 from . import，不能裸 import。"""

    _bare_import_re = re.compile(
        r"^\s*import\s+(%s)\b" % "|".join(_PKG_MODULES)
    )
    _bare_from_re = re.compile(
        r"^\s*from\s+(%s)\s+import" % "|".join(_PKG_MODULES)
    )

    @pytest.mark.parametrize("py_file", sorted(PKG_DIR.glob("*.py")))
    def test_no_bare_intra_package_imports(self, py_file):
        """包内 .py 文件不应使用裸 import config 等。"""
        if py_file.stem == "__init__":
            return  # __init__.py 可以用 from . import

        lines = py_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            m = self._bare_import_re.match(stripped)
            if m:
                imported = m.group(1)
                msg = (
                    f"{py_file.name}:{i} 使用裸 'import {imported}'，"
                    f"应改为 'from . import {imported}'"
                )
                pytest.fail(msg)

            m2 = self._bare_from_re.match(stripped)
            if m2:
                imported = m2.group(1)
                msg = (
                    f"{py_file.name}:{i} 使用裸 'from {imported} import ...'，"
                    f"应改为 'from .{imported} import ...'"
                )
                pytest.fail(msg)

    def test_config_import_style(self):
        """检查各模块中 config 的导入方式均为 from . import config。"""
        for py_file in PKG_DIR.glob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            # 检查是否有裸 import config
            bare = re.findall(r"^\s*import config\b", content, re.MULTILINE)
            assert len(bare) == 0, f"{py_file.name} 包含裸 'import config'"


class TestEntryPoints:
    """验证入口点正常工作。"""

    def test_start_server_imports_correctly(self):
        """start_server.py 从 backend.server 导入 main。"""
        start_file = PROJECT_ROOT / "start_server.py"
        content = start_file.read_text(encoding="utf-8")
        assert "backend.server" in content

    def test_main_module_delegates(self):
        """__main__.py 委托到 server.main()。"""
        main_file = PKG_DIR / "__main__.py"
        content = main_file.read_text(encoding="utf-8")
        assert "server" in content and "main" in content

    def test_server_main_exists(self):
        """server.py 有 main() 函数。"""
        from backend.server import main
        assert callable(main)

    def test_python_m_backend(self):
        """python -m backend 入口不报错（至少导入成功）。"""
        result = subprocess.run(
            [sys.executable, "-c", "from backend.__main__ import main"],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, f"__main__ 导入失败: {result.stderr}"


class TestPackageStructure:
    """包目录结构完整性。"""

    def test_pyproject_toml_exists(self):
        assert (PROJECT_ROOT / "pyproject.toml").exists()

    def test_pyproject_has_console_scripts(self):
        ppt = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "crabapple-docstudio-server" in ppt
        assert "crabapple-docstudio-manager" in ppt

    def test_no_stray_py_in_root(self):
        """根目录不应有残留 .py 文件（start_server.py 除外）。"""
        stray = [
            f for f in PROJECT_ROOT.glob("*.py")
            if f.name != "start_server.py"
        ]
        assert len(stray) == 0, f"根目录残留 .py: {[f.name for f in stray]}"

    def test_init_exports(self):
        """__init__.py 导出 DocumentCleaner 和 config。"""
        init = (PKG_DIR / "__init__.py").read_text(encoding="utf-8")
        assert "DocumentCleaner" in init
        assert "config" in init
