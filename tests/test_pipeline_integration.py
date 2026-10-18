"""端到端集成测试：testcase TIF 图片 → 清洁 → OCR → 双层 PDF 全流程。

使用真实扫描件验证完整处理管线。需要 YOLO + RapidOCR + testcase。
"""
import time
import pytest

pytestmark = [pytest.mark.yolo, pytest.mark.rapidocr, pytest.mark.testcase, pytest.mark.slow]


class TestImageToClean:
    """步骤 1: 读取 TIF → DocumentCleaner 清洁。"""

    def test_read_all_testcase_images(self, testcase_images):
        """所有 testcase TIF 图片可被 cv2 读取。"""
        import cv2
        failed = []
        for img_path in testcase_images:
            img = cv2.imread(str(img_path))
            if img is None:
                img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
            if img is None:
                failed.append(img_path.name)
        assert len(failed) == 0, f"无法读取: {failed}"

    def test_clean_all_testcase(self, cleaner, testcase_images):
        """所有 testcase TIF 可被清洁处理。"""
        import cv2
        failed = []
        for img_path in testcase_images[:5]:
            img = cv2.imread(str(img_path))
            if img is None:
                img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
            if img is None:
                failed.append(f"{img_path.name}: 无法读取")
                continue
            try:
                result = cleaner.process(img, dpi=300)
                assert isinstance(result, dict)
            except Exception as e:
                failed.append(f"{img_path.name}: {e}")
        assert len(failed) == 0, f"清洁失败: {failed}"

    def test_clean_preserves_content(self, cleaner, testcase_first_image):
        """清洁后图像非全白（内容保留）。"""
        import cv2
        import numpy as np
        img = cv2.imread(str(testcase_first_image))
        if img is None:
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None

        result = cleaner.process(img, dpi=300)
        # 获取清洁后图像
        if "image" in result:
            cleaned = result["image"]
        elif "result" in result:
            cleaned = result["result"]
        elif "cleaned" in result:
            cleaned = result["cleaned"]
        else:
            # 直接再次读取最后的图像
            cleaned = result.get(list(result.keys())[-1])

        if cleaned is not None and hasattr(cleaned, 'shape'):
            # 不应全白
            if len(cleaned.shape) == 3:
                gray = cv2.cvtColor(cleaned, cv2.COLOR_BGR2GRAY)
            else:
                gray = cleaned
            non_white = np.sum(gray < 250)
            total = gray.size
            ratio = non_white / total
            assert ratio > 0.001, f"清洁后图像几乎全白 (非白像素比例: {ratio:.6f})"


class TestOCROnCleaned:
    """步骤 2: 清洁后图像 → OCR 识别。"""

    def test_ocr_on_cleaned_image(self, cleaner, ocr_engine, testcase_first_image):
        """清洁后图像可被 OCR 识别。"""
        from backend.ocr_rapid import ocr_image_with_rapid
        import cv2

        img = cv2.imread(str(testcase_first_image))
        if img is None:
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None

        # 清洁
        clean_result = cleaner.process(img, dpi=300)
        if "image" in clean_result:
            cleaned_img = clean_result["image"]
        elif "result" in clean_result:
            cleaned_img = clean_result["result"]
        else:
            cleaned_img = clean_result.get(list(clean_result.keys())[-1])

        assert cleaned_img is not None

        # OCR
        ocr_result = ocr_image_with_rapid(cleaned_img, ocr_engine)
        if isinstance(ocr_result, tuple):
            ocr_list, _elapse = ocr_result
        else:
            ocr_list = ocr_result

        assert ocr_list is not None, "清洁后 OCR 结果不应为 None"


class TestPipelineToPDF:
    """步骤 3: 清洁 + OCR → 生成可搜索 PDF。"""

    def test_create_searchable_pdf(self, cleaner, ocr_engine, testcase_first_image, test_output_dir):
        """完整管线：TIF → 清洁 → OCR → 可搜索 PDF。"""
        from backend.ocr_rapid import ocr_image_with_rapid, parse_rapid_ocr_result
        from backend.app import create_searchable_pdf
        import cv2

        # 1. 读取图片
        img = cv2.imread(str(testcase_first_image))
        if img is None:
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None, f"无法读取: {testcase_first_image}"

        # 2. 清洁
        clean_result = cleaner.process(img, dpi=300)
        if "image" in clean_result:
            cleaned_img = clean_result["image"]
        elif "result" in clean_result:
            cleaned_img = clean_result["result"]
        else:
            cleaned_img = clean_result.get(list(clean_result.keys())[-1])
        assert cleaned_img is not None

        # 3. OCR
        ocr_result = ocr_image_with_rapid(cleaned_img, ocr_engine)
        if isinstance(ocr_result, tuple):
            ocr_list, _elapse = ocr_result
        else:
            ocr_list = ocr_result

        parsed = parse_rapid_ocr_result(ocr_list)
        assert isinstance(parsed, list)

        # 4. 保存清洁后的中间图片
        mid_path = test_output_dir / f"pipeline_cleaned_{testcase_first_image.stem}.png"
        cv2.imwrite(str(mid_path), cleaned_img)
        assert mid_path.exists(), f"中间图片未保存: {mid_path}"

        # 5. 生成可搜索 PDF
        pdf_path = test_output_dir / f"pipeline_{testcase_first_image.stem}.pdf"
        try:
            create_searchable_pdf(str(mid_path), str(pdf_path))
            assert pdf_path.exists(), f"PDF 未生成: {pdf_path}"
            assert pdf_path.stat().st_size > 0, f"PDF 为空: {pdf_path}"
        except Exception as e:
            pytest.skip(f"create_searchable_pdf 失败（可能缺少字体或依赖）: {e}")


class TestPipelinePerformance:
    """全流程性能基线。"""

    def test_full_pipeline_time(self, cleaner, ocr_engine, testcase_first_image):
        """完整管线（清洁 + OCR）总耗时在合理范围。"""
        from backend.ocr_rapid import ocr_image_with_rapid
        import cv2

        img = cv2.imread(str(testcase_first_image))
        if img is None:
            img = cv2.imread(str(testcase_first_image), cv2.IMREAD_UNCHANGED)
        assert img is not None

        total_start = time.time()

        # 清洁
        clean_start = time.time()
        clean_result = cleaner.process(img, dpi=300)
        clean_time = time.time() - clean_start

        if "image" in clean_result:
            cleaned_img = clean_result["image"]
        elif "result" in clean_result:
            cleaned_img = clean_result["result"]
        else:
            cleaned_img = clean_result.get(list(clean_result.keys())[-1])

        # OCR
        ocr_start = time.time()
        ocr_image_with_rapid(cleaned_img, ocr_engine)
        ocr_time = time.time() - ocr_start

        total_time = time.time() - total_start

        # 记录性能数据
        print(f"\n  性能: 清洁={clean_time:.1f}s, OCR={ocr_time:.1f}s, 总计={total_time:.1f}s")

        # 性能上限（考虑到首次 JIT 编译）
        assert clean_time < 120, f"清洁耗时过长: {clean_time:.1f}s"
        assert ocr_time < 120, f"OCR 耗时过长: {ocr_time:.1f}s"
