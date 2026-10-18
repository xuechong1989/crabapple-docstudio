# -*- coding: utf-8 -*-
# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局历史存储函数已废弃，所有历史读写统一使用 user_scope.py 的 UserScope
# 本文件仅保留 app.py 函数的懒加载代理（避免 routes/ 和 app.py 循环导入）

# ============================================================
# app.py 函数懒加载代理（避免循环导入）
# 所有 routes/*.py 已导入 _hsvc，通过 _hsvc.xxx() 调用
# ============================================================

def get_cleaner():
    from backend.app import get_cleaner as _fn
    return _fn()


def get_image_dpi(image_path):
    from backend.app import get_image_dpi as _fn
    return _fn(image_path)


def save_image_with_dpi(image, output_path, **kwargs):
    from backend.app import save_image_with_dpi as _fn
    return _fn(image, output_path, **kwargs)


def merge_pdfs_to_single(pdf_paths, output_path, add_page_number=True):
    from backend.app import merge_pdfs_to_single as _fn
    return _fn(pdf_paths, output_path, add_page_number)


def add_page_numbers(pdf_doc):
    from backend.app import add_page_numbers as _fn
    return _fn(pdf_doc)


def image_to_searchable_pdf(image, output_pdf_path, **kwargs):
    from backend.app import image_to_searchable_pdf as _fn
    return _fn(image, output_pdf_path, **kwargs)


def create_searchable_pdf(image_path, output_pdf_path):
    from backend.app import create_searchable_pdf as _fn
    return _fn(image_path, output_pdf_path)


# xuechong 2026-07-18 透传 username 参数以支持用户隔离
def process_task(task_id, file_paths, username="admin"):
    from backend.app import process_task as _fn
    return _fn(task_id, file_paths, username)


def get_dual_layer_executor():
    from backend.app import _dual_layer_executor
    return _dual_layer_executor


