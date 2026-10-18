# -*- coding: utf-8 -*-
"""图像处理工具函数"""
from pathlib import Path


SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'}


def is_image_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS
