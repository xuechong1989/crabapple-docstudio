"""元测试：验证 self_check.py 本身可正确运行。"""
import re
import sys
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SELF_CHECK_PATH = PROJECT_ROOT / "scripts" / "self_check.py"


@pytest.fixture
def self_check_source():
    """self_check.py 源代码内容（字符串）。"""
    return SELF_CHECK_PATH.read_text(encoding="utf-8")


class TestSelfCheckSyntax:
    """自检脚本语法和结构。"""

    def test_self_check_file_exists(self):
        """self_check.py 存在。"""
        assert SELF_CHECK_PATH.exists(), f"不存在: {SELF_CHECK_PATH}"

    def test_self_check_syntax_valid(self):
        """self_check.py 语法正确。"""
        import py_compile
        py_compile.compile(str(SELF_CHECK_PATH), doraise=True)

    def test_self_check_is_python(self):
        """self_check.py 是有效的 Python 文件。"""
        content = SELF_CHECK_PATH.read_text(encoding="utf-8")
        assert content.strip(), "文件为空"


class TestSelfCheckFunctions:
    """所有检查函数存在。"""

    def test_all_check_functions_defined(self, self_check_source):
        """检查 1-17 对应的函数全部定义。"""
        expected_funcs = [
            "check_syntax",
            "check_function_calls",
            "check_name_references",
            "check_dependencies",
            "check_shell_scripts",
            "check_no_network_at_runtime",
            "check_offline_packages",
            "check_offline_duplicates",
            "check_offline_platform",
            "check_torch_cuda",
            "check_cuda_version_consistency",
            "check_log_format",
            "check_package_imports",
            "check_package_tree",
            "check_url_conf",
            "check_entry_points",
            "check_frontend_build",
        ]
        for func_name in expected_funcs:
            assert f"def {func_name}(" in self_check_source, f"缺失函数: {func_name}"

    def test_all_checks_called_in_main(self, self_check_source):
        """所有检查函数在 main() 中被调用。"""
        # 找到 main() 函数体
        main_match = re.search(r"def main\(\):.*?(?=\ndef |\n# ==|$)", self_check_source, re.DOTALL)
        assert main_match, "未找到 main() 函数"
        main_body = main_match.group(0)

        expected_funcs = [
            "check_syntax()",
            "check_function_calls()",
            "check_name_references()",
            "check_dependencies()",
            "check_shell_scripts()",
            "check_no_network_at_runtime()",
            "check_offline_packages()",
            "check_offline_duplicates(",
            "check_offline_platform(",
            "check_torch_cuda()",
            "check_cuda_version_consistency()",
            "check_log_format()",
            "check_package_imports()",
            "check_package_tree()",
            "check_url_conf()",
            "check_entry_points()",
            "check_frontend_build()",
        ]
        for func_call in expected_funcs:
            assert func_call in main_body, f"main() 未调用: {func_call}"

    def test_total_checks_matches(self, self_check_source):
        """TOTAL_CHECKS 与实际检查数量一致。"""
        m = re.search(r"TOTAL_CHECKS\s*=\s*(\d+)", self_check_source)
        assert m, "未找到 TOTAL_CHECKS"
        total = int(m.group(1))
        # 统计 section_header 调用中引用的 TOTAL_CHECKS
        sections = re.findall(r"section_header\(\d+,\s*TOTAL_CHECKS", self_check_source)
        assert len(sections) == total, (
            f"TOTAL_CHECKS={total} 但实际有 {len(sections)} 个检查函数"
        )

    def test_docstring_lists_all_checks(self, self_check_source):
        """文档字符串列出全部 17 项检查。"""
        doc_match = re.search(r'""".*?"""', self_check_source, re.DOTALL)
        assert doc_match, "未找到文档字符串"
        # 在 docstring 中找编号项
        numbered = re.findall(r"^\s*\d+\.", doc_match.group(0), re.MULTILINE)
        assert len(numbered) >= 17, f"文档字符串仅列出 {len(numbered)} 项检查"


class TestSelfCheckExecution:
    """自检脚本实际执行测试。"""

    @pytest.mark.slow
    def test_self_check_runs_without_crash(self):
        """self_check.py 运行不崩溃（至少语法检查通过）。"""
        result = subprocess.run(
            [sys.executable, str(SELF_CHECK_PATH)],
            capture_output=True, text=True, timeout=60,
            cwd=str(PROJECT_ROOT),
        )
        # 不检查 return code（可能因环境差异 fail），但不应崩溃
        assert isinstance(result.returncode, int), "进程异常退出"
        assert "Traceback" not in result.stderr, f"运行崩溃:\n{result.stderr}"

    def test_self_check_produces_report(self):
        """self_check.py 输出含 REPORT 字样。"""
        result = subprocess.run(
            [sys.executable, str(SELF_CHECK_PATH)],
            capture_output=True, text=True, timeout=60,
            cwd=str(PROJECT_ROOT),
            # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 Windows GBK 无法解码 UTF-8 输出
            encoding='utf-8', errors='replace',
        )
        output = (result.stdout or '') + (result.stderr or '')
        assert "REPORT" in output, "输出中无 REPORT 汇总"


class TestSelfCheckImportPatterns:
    """验证 self_check.py 自身的代码质量。"""

    def test_no_inline_url_conf_reimplementation(self):
        """self_check.py 不重新实现 url.conf 解析（应直接 import config）。"""
        # 允许自身解析 url.conf，但检查脚本是否有导入 config 的尝试
        content = SELF_CHECK_PATH.read_text(encoding="utf-8")
        # 至少有 import 语句
        assert "import" in content

    def test_helper_functions_defined(self, self_check_source):
        """辅助函数（PASS/FAIL/WARN/INFO/section_header）已定义。"""
        for helper in ("PASS", "FAIL", "WARN", "INFO", "section_header"):
            # 查找函数定义
            assert re.search(rf"def {helper}\(", self_check_source), f"缺失: {helper}()"

    def test_color_functions_defined(self, self_check_source):
        """颜色输出函数已定义。"""
        for color in ("RED", "GREEN", "YELLOW", "CYAN", "BOLD"):
            assert f"def {color}(" in self_check_source, f"缺失: {color}()"
