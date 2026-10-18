"""测试 RapidOCR 引擎：初始化、图像识别、结果格式。使用真实 testcase TIF 图片。"""
import time
import numpy as np
import pytest

pytestmark = [pytest.mark.rapidocr]


class TestRapidOCREngineInit:
    """RapidOCR 引擎初始化测试。"""

    def test_get_engine_returns_engine(self, ocr_engine):
        assert ocr_engine is not None

    def test_engine_is_callable(self, ocr_engine):
        # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 get_rapid_ocr_engine 返回 dict{'engine':..., 'use_cls':...}
        engine_obj = ocr_engine['engine'] if isinstance(ocr_engine, dict) else ocr_engine
        assert callable(engine_obj)

    def test_engine_release(self):
        from backend.ocr_rapid import release_rapid_ocr_engine
        release_rapid_ocr_engine("__test_engine__")


class TestOCRImageFormat:
    """OCR 结果格式验证（合成图像，无需 testcase）。"""

    def test_ocr_synthetic_image(self, ocr_engine):
        from backend.ocr_rapid import ocr_image_with_rapid
        import cv2

        img = np.ones((400, 600, 3), dtype=np.uint8) * 255
        cv2.putText(img, "Test 123", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)

        result = ocr_image_with_rapid(img, ocr_engine)
        if isinstance(result, tuple):
            ocr_list, _elapse = result
        else:
            ocr_list = result
        assert isinstance(ocr_list, list), "OCR 结果应为 list"

    def test_ocr_result_structure(self, ocr_engine):
        from backend.ocr_rapid import ocr_image_with_rapid, parse_rapid_ocr_result
        import cv2

        img = np.ones((400, 600, 3), dtype=np.uint8) * 255
        cv2.putText(img, "Hello World", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)

        result = ocr_image_with_rapid(img, ocr_engine)
        if isinstance(result, tuple):
            ocr_list, _elapse = result
        else:
            ocr_list = result

        parsed = parse_rapid_ocr_result(ocr_list)
        assert isinstance(parsed, list)
        for item in parsed:
            assert "text" in item, f"缺少 text: {item}"
            assert "box" in item or "boxes" in item, f"缺少坐标: {item}"

    def test_ocr_empty_image(self, ocr_engine):
        from backend.ocr_rapid import ocr_image_with_rapid
        blank = np.ones((400, 600, 3), dtype=np.uint8) * 255

        result = ocr_image_with_rapid(blank, ocr_engine)
        if isinstance(result, tuple):
            ocr_list, _elapse = result
        else:
            ocr_list = result

        if isinstance(ocr_list, list):
            assert len(ocr_list) <= 3, f"空白图像误识别过多: {len(ocr_list)} 条"


@pytest.mark.testcase
class TestOCRRealImage:
    """使用 testcase 真实扫描件测试 OCR。"""

    def test_ocr_single_tif(self, ocr_engine, testcase_first_image):
        from backend.ocr_rapid import ocr_image_with_rapid
        import cv2

        img = cv2.imread(str(testcase_first_image))
        if img is None:
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None

        result = ocr_image_with_rapid(img, ocr_engine)
        if isinstance(result, tuple):
            ocr_list, _elapse = result
        else:
            ocr_list = result
        assert ocr_list is not None

    def test_ocr_all_testcase(self, ocr_engine, testcase_images):
        from backend.ocr_rapid import ocr_image_with_rapid
        import cv2

        failed = []
        empty = []
        for img_path in testcase_images[:5]:
            img = cv2.imread(str(img_path))
            if img is None:
                img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
            if img is None:
                failed.append(f"{img_path.name}: 无法读取")
                continue
            try:
                result = ocr_image_with_rapid(img, ocr_engine)
                if isinstance(result, tuple):
                    ocr_list, _elapse = result
                else:
                    ocr_list = result
                if not ocr_list:
                    empty.append(img_path.name)
            except Exception as e:
                failed.append(f"{img_path.name}: {e}")

        assert len(failed) == 0, f"OCR 失败: {failed}"
        if len(empty) == len(testcase_images[:5]) and len(testcase_images[:5]) > 0:
            pytest.fail(f"全部 {len(testcase_images[:5])} 张图片 OCR 结果为空")


class TestOCREngineFeatures:
    """引擎特性测试。"""

    def test_version_function(self):
        from backend.ocr_rapid import get_rapidocr_version
        ver = get_rapidocr_version()
        assert ver
        assert "." in ver

    def test_gpu_detection(self):
        from backend.ocr_rapid import detect_ort_gpu
        result = detect_ort_gpu()
        assert isinstance(result, bool)

    def test_font_cache(self):
        from backend.ocr_rapid import get_cached_font
        font = get_cached_font("china-s")
        if font is not None:
            # xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 get_cached_font 返回 fitz.Font 对象，非路径字符串
            assert hasattr(font, 'name') or 'Font' in str(type(font))


@pytest.mark.testcase
class TestOCRPerformance:
    """OCR 性能基线。"""

    def test_ocr_time_reasonable(self, ocr_engine, testcase_first_image):
        from backend.ocr_rapid import ocr_image_with_rapid
        import cv2

        img = cv2.imread(str(testcase_first_image))
        if img is None:
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None

        start = time.time()
        ocr_image_with_rapid(img, ocr_engine)
        elapsed = time.time() - start
        assert elapsed < 120, f"OCR 耗时过长: {elapsed:.1f} 秒"
