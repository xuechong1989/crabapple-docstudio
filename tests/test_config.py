"""测试配置模块：url.conf 加载、路径常量、关键参数。"""
import os
from pathlib import Path



class TestConfigLoading:
    """url.conf 加载和路径验证。"""

    def test_data_dir_is_path(self, project_config):
        """DATA_DIR 是 Path 对象且非空。"""
        assert isinstance(project_config.DATA_DIR, Path)
        assert str(project_config.DATA_DIR).strip() != ""

    def test_tmp_dir_is_path(self, project_config):
        """TMP_DIR 是 Path 对象。"""
        assert isinstance(project_config.TMP_DIR, Path)

    def test_hf_home_env_set(self, project_config):
        """HF_HOME 环境变量由 config 模块设置。"""
        hf_home = os.environ.get("HF_HOME", "")
        assert hf_home, "HF_HOME 环境变量未设置"

    def test_cuda_cache_env_set(self, project_config):
        """CUDA_CACHE_PATH 环境变量由 config 模块设置。"""
        cuda_cache = os.environ.get("CUDA_CACHE_PATH", "")
        assert cuda_cache, "CUDA_CACHE_PATH 环境变量未设置"

    def test_tmpdir_env_set(self):
        """TMPDIR 环境变量由 config 模块设置。"""
        tmpdir = os.environ.get("TMPDIR", "")
        assert tmpdir, "TMPDIR 环境变量未设置"


class TestConfigConstants:
    """关键配置常量存在且类型正确。"""

    def test_yolo_constants(self, project_config):
        """YOLO 相关配置常量。"""
        assert hasattr(project_config, "YOLO_MODEL_PATH")
        assert hasattr(project_config, "YOLO_IMGSZ")
        assert isinstance(project_config.YOLO_IMGSZ, int)
        assert project_config.YOLO_IMGSZ > 0

    def test_ocr_constants(self, project_config):
        """OCR 相关配置常量。"""
        assert hasattr(project_config, "OCR_ENGINE")
        assert project_config.OCR_ENGINE in ("rapidocr", "paddleocr", "rapid")
        assert hasattr(project_config, "OCR_DET_LIMIT_SIDE_LEN")
        assert hasattr(project_config, "OCR_DEFAULT_DPI")
        assert project_config.OCR_DEFAULT_DPI > 0

    def test_cleaner_constants(self, project_config):
        """图像清洁相关配置常量。"""
        assert hasattr(project_config, "ENABLE_NOISE_DETECT")
        assert hasattr(project_config, "ENABLE_SEAL_PROTECTION")
        assert hasattr(project_config, "ENABLE_DESKEW")
        assert hasattr(project_config, "ENABLE_PAGE_ORIENTATION")

    def test_device_constants(self, project_config):
        """设备相关配置常量。"""
        assert hasattr(project_config, "USE_GPU")
        assert hasattr(project_config, "OCR_DEVICE")
        assert hasattr(project_config, "YOLO_DEVICE")

    def test_binary_threshold(self, project_config):
        """二值化阈值在合理范围。"""
        assert 0 <= project_config.BINARY_THRESHOLD <= 255

    def test_boundary_constants(self, project_config):
        """边界清洁相关常量在合理范围。"""
        assert hasattr(project_config, "ENABLE_BOUNDARY_CLEAN")


class TestScaleRadius:
    """DPI 相关的 scale_radius 函数。"""

    def test_scale_radius_default_dpi(self, project_config):
        """默认 DPI (300) 时缩放因子为 1.0。"""
        assert hasattr(project_config, "scale_radius")
        result = project_config.scale_radius(10, 300)
        assert result == 10

    def test_scale_radius_double_dpi(self, project_config):
        """DPI 600 时半径翻倍。"""
        result = project_config.scale_radius(10, 600)
        assert result == 20

    def test_scale_radius_half_dpi(self, project_config):
        """DPI 150 时半径减半。"""
        result = project_config.scale_radius(10, 150)
        assert result == 5


class TestUrlConf:
    """url.conf 文件验证。"""

    def test_url_conf_exists(self):
        """url.conf 存在于项目根目录。"""
        url_conf = Path(__file__).parent.parent / "url.conf"
        assert url_conf.exists(), f"url.conf 不存在: {url_conf}"

    def test_url_conf_has_data_dir(self):
        """url.conf 包含 DATA_DIR 定义。"""
        url_conf = Path(__file__).parent.parent / "url.conf"
        content = url_conf.read_text(encoding="utf-8")
        assert "DATA_DIR" in content
        assert "TMP_DIR" in content

    def test_url_conf_no_env_var_paths(self):
        """url.conf 不包含 $HOME / $USERPROFILE 等环境变量引用（应全是固定变量）。"""
        url_conf = Path(__file__).parent.parent / "url.conf"
        content = url_conf.read_text(encoding="utf-8")
        # 不应使用 shell 环境变量来推导路径
        assert "$HOME" not in content, "url.conf 不应使用 $HOME"
        assert "$USERPROFILE" not in content, "url.conf 不应使用 $USERPROFILE"


class TestPathSafety:
    """磁盘路径安全性检查。"""

    def test_no_tempfile_gettempdir_in_source(self):
        """源代码中不应使用 tempfile.gettempdir()。"""
        pkg_dir = Path(__file__).parent.parent / "backend"
        for py_file in sorted(pkg_dir.glob("*.py")):
            content = py_file.read_text(encoding="utf-8")
            assert "tempfile.gettempdir()" not in content, (
                f"{py_file.name} 使用了 tempfile.gettempdir()"
            )

    def test_no_path_home_in_source(self):
        """源代码中不应使用 Path.home() / os.path.expanduser('~')。"""
        pkg_dir = Path(__file__).parent.parent / "backend"
        for py_file in sorted(pkg_dir.glob("*.py")):
            content = py_file.read_text(encoding="utf-8")
            assert "Path.home()" not in content, (
                f"{py_file.name} 使用了 Path.home()"
            )
            assert "expanduser" not in content, (
                f"{py_file.name} 使用了 os.path.expanduser()"
            )
