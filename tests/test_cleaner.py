"""测试 DocumentCleaner：初始化、图像处理、输出验证。使用真实 testcase TIF 图片。"""
import time
import numpy as np
import pytest

pytestmark = [pytest.mark.yolo, pytest.mark.testcase, pytest.mark.slow]


class TestDocumentCleanerInit:
    """DocumentCleaner 初始化测试。"""

    def test_cleaner_import(self):
        """DocumentCleaner 通过懒加载导出可访问。"""
        from backend import DocumentCleaner
        assert DocumentCleaner is not None

    def test_cleaner_instantiation(self, cleaner):
        """DocumentCleaner 实例化成功。"""
        assert cleaner is not None

    def test_cleaner_has_process_method(self, cleaner):
        """DocumentCleaner 有 process 方法。"""
        assert callable(cleaner.process)

    def test_cleaner_has_predict_method(self, cleaner):
        """DocumentCleaner 有 _predict 方法。"""
        assert callable(cleaner._predict)


class TestProcessSyntheticImage:
    """使用合成图像测试 cleaner.process() 基本功能。"""

    def test_process_returns_dict(self, cleaner, synthetic_image):
        """process() 返回 dict。"""
        result = cleaner.process(synthetic_image, dpi=300)
        assert isinstance(result, dict)

    def test_process_preserves_dimensions(self, cleaner, synthetic_image):
        """清洁后图像尺寸不变。"""
        h, w = synthetic_image.shape[:2]
        result = cleaner.process(synthetic_image, dpi=300)
        if "image" in result:
            out_h, out_w = result["image"].shape[:2]
            assert out_h == h, f"高度变化: {h} -> {out_h}"
            assert out_w == w, f"宽度变化: {w} -> {out_w}"


class TestProcessRealImage:
    """使用 testcase 真实扫描件测试 cleaner.process()。"""

    def test_process_single_tif(self, cleaner, testcase_first_image):
        """对单张 TIF 执行清洁处理，不崩溃。"""
        import cv2
        img = cv2.imread(str(testcase_first_image))
        if img is None:
            # TIF 可能需要特殊解码
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None, f"无法读取: {testcase_first_image}"
        result = cleaner.process(img, dpi=300)
        assert isinstance(result, dict)

    def test_process_all_testcase(self, cleaner, testcase_images):
        """对 testcase 中所有 TIF 执行清洁处理。"""
        import cv2
        failed = []
        for img_path in testcase_images[:5]:  # 最多测 5 张
            img = cv2.imread(str(img_path))
            if img is None:
                img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
            if img is None:
                failed.append(f"{img_path.name}: 无法读取")
                continue
            try:
                result = cleaner.process(img, dpi=300)
                if not isinstance(result, dict):
                    failed.append(f"{img_path.name}: 返回非 dict: {type(result)}")
            except Exception as e:
                failed.append(f"{img_path.name}: {e}")
        assert len(failed) == 0, f"清洁失败: {failed}"

    def test_process_output_has_expected_keys(self, cleaner, testcase_first_image):
        """清洁结果包含预期的键。"""
        import cv2
        img = cv2.imread(str(testcase_first_image))
        if img is None:
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None

        result = cleaner.process(img, dpi=300)

        # 结果至少应有图像数据
        has_image = "image" in result or "result" in result or "cleaned" in result
        assert has_image, f"结果中无图像数据: {list(result.keys())}"


class TestProcessVariantImages:
    """不同图像类型的清洁处理。"""

    def test_grayscale_image(self, cleaner):
        """灰度图像处理不崩溃。"""
        import cv2
        gray = np.ones((500, 500), dtype=np.uint8) * 200
        cv2.rectangle(gray, (100, 100), (400, 400), 0, 2)
        result = cleaner.process(gray, dpi=300)
        assert isinstance(result, dict)

    def test_rgb_image(self, cleaner):
        """RGB 图像处理不崩溃。"""
        import cv2
        rgb = np.ones((500, 500, 3), dtype=np.uint8) * 255
        cv2.rectangle(rgb, (100, 100), (400, 400), (0, 0, 0), 2)
        result = cleaner.process(rgb, dpi=300)
        assert isinstance(result, dict)

    def test_small_image(self, cleaner):
        """小尺寸图像处理不崩溃。"""
        import cv2
        small = np.ones((200, 150, 3), dtype=np.uint8) * 255
        cv2.putText(small, "Test", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        result = cleaner.process(small, dpi=300)
        assert isinstance(result, dict)

    def test_large_image(self, cleaner):
        """大尺寸图像处理不崩溃。"""
        import cv2
        large = np.ones((2000, 1500, 3), dtype=np.uint8) * 255
        cv2.rectangle(large, (200, 200), (1300, 1800), (0, 0, 0), 2)
        result = cleaner.process(large, dpi=300)
        assert isinstance(result, dict)


class TestCleanerPerformance:
    """清洁器性能基线。"""

    def test_process_time_reasonable(self, cleaner, testcase_first_image):
        """单张图片处理时间应在合理范围（< 60 秒）。"""
        import cv2
        img = cv2.imread(str(testcase_first_image))
        if img is None:
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None

        start = time.time()
        cleaner.process(img, dpi=300)
        elapsed = time.time() - start
        assert elapsed < 60, f"清洁耗时过长: {elapsed:.1f} 秒"
