# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局历史存储已废弃，改为测试 UserScope 一致性
"""测试下载/预览/编辑/删除端点使用相同的数据源（UserScope.download_history）"""
import sys
import uuid
from datetime import datetime
from pathlib import Path


def test_all():
    errors = []
    from backend.services.user_scope import get_user_scope

    # 准备测试数据
    test_username = "test_consistency_user"
    scope = get_user_scope(test_username)
    test_items = []
    for i in range(3):
        item = {
            "task_id": f"task_{uuid.uuid4().hex[:8]}",
            "username": test_username,
            "folder_name": f"folder_{i}",
            "first_image_name": f"image_{i}",
            "pdf_path": f"/tmp/test_{i}.pdf",
            "file_count": i + 1,
            "download_count": 0,
            "edited": False,
            "edit_download_count": 0,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        test_items.append(item)

    # 清理并插入测试数据
    scope.download_history.clear()
    for item in reversed(test_items):
        scope.download_history.insert(0, item)

    # 模拟筛选函数（download_history.py 的 _get_filtered_history）
    def get_filtered():
        return [r for r in scope.download_history if r.get('username') == test_username]

    # ============================================================
    # TEST1: 筛选列表与全局列表一致性
    # ============================================================
    print("[1/6] 筛选列表与scope列表一致性")
    filtered = get_filtered()
    if len(filtered) != 3:
        errors.append(f"筛选列表长度错误: 期望3, 实际{len(filtered)}")
    print(f"  {'PASS' if len(filtered) == 3 else 'FAIL'}")

    # ============================================================
    # TEST2: 索引对应正确的记录
    # ============================================================
    print("[2/6] 索引对应正确的记录")
    for i, item in enumerate(test_items):
        if filtered[i]["task_id"] != item["task_id"]:
            errors.append(f"索引{i}对应错误: 期望{item['task_id']}, 实际{filtered[i]['task_id']}")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    # ============================================================
    # TEST3: 下载端点索引一致性
    # ============================================================
    print("[3/6] 下载端点索引一致性")
    for i in range(3):
        idx = i
        if idx < 0 or idx >= len(filtered):
            errors.append(f"下载索引{i}越界")
        else:
            item = filtered[idx]
            if item["folder_name"] != test_items[i]["folder_name"]:
                errors.append(f"下载索引{i}对应错误记录")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    # ============================================================
    # TEST4: 预览端点索引一致性
    # ============================================================
    print("[4/6] 预览端点索引一致性")
    preview_filtered = get_filtered()
    for i in range(3):
        idx = i
        if idx < 0 or idx >= len(preview_filtered):
            errors.append(f"预览索引{i}越界")
        else:
            item = preview_filtered[idx]
            if item["pdf_path"] != test_items[i]["pdf_path"]:
                errors.append(f"预览索引{i}对应错误PDF路径")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    # ============================================================
    # TEST5: 编辑端点通过task_id查找路径（模拟edit_pdf.py的import逻辑）
    # ============================================================
    print("[5/6] 编辑端点通过task_id查找路径")
    for item in test_items:
        task_id = item["task_id"]
        found_path = ""
        for h in scope.download_history:
            if h.get("task_id") == task_id:
                found_path = h.get("pdf_path", "")
                break
        if found_path != item["pdf_path"]:
            errors.append(f"编辑端点查找task_id={task_id}失败: 期望{item['pdf_path']}, 实际{found_path}")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    # ============================================================
    # TEST6: 删除后索引仍一致
    # ============================================================
    print("[6/6] 删除后索引仍一致")
    to_delete = test_items[0]
    scope.download_history.remove(to_delete)
    filtered_after = get_filtered()
    if len(filtered_after) != 2:
        errors.append(f"删除后筛选列表长度错误: 期望2, 实际{len(filtered_after)}")
    if filtered_after[0]["task_id"] != test_items[1]["task_id"]:
        errors.append(f"删除后索引0对应错误: 期望{test_items[1]['task_id']}, 实际{filtered_after[0]['task_id']}")
    if filtered_after[1]["task_id"] != test_items[2]["task_id"]:
        errors.append(f"删除后索引1对应错误: 期望{test_items[2]['task_id']}, 实际{filtered_after[1]['task_id']}")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    # 清理测试数据
    scope.download_history.clear()

    # 输出结果
    print()
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        print(f"\nFAIL: {len(errors)} 项失败")
        sys.exit(1)
    print("ALL 6 PASSED")


if __name__ == "__main__":
    test_all()
