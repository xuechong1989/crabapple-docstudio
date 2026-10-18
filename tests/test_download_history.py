# xuechong 2026-06-27 下载历史自检测试
"""每个用户独立scope，写入自己scope，API读自己scope"""
import sys, uuid
from datetime import datetime

def test_all():
    errors = []
    from backend.services.app_state import state
    from backend.services.user_scope import get_user_scope

    # TEST1: 每个用户独立 scope
    print("[1/5] 独立scope")
    admin = get_user_scope('admin_user')
    other = get_user_scope('other_user')
    if admin.download_history is other.download_history:
        errors.append("不同用户共享scope")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    # TEST2: 写入自己scope→自己可见
    print("[2/5] 写入自己scope")
    tid = str(uuid.uuid4())
    admin.download_history.insert(0, {"task_id": tid, "folder_name": "test"})
    admin.save_download_history()
    v = get_user_scope('admin_user')
    ok = any(r.get("task_id") == tid for r in v.download_history)
    if not ok: errors.append("写入后自己看不到")
    v.download_history.pop(0); v.save_download_history()
    print(f"  {'PASS' if ok else 'FAIL'}")

    # TEST3: 持久化
    print("[3/5] 持久化")
    tid2 = str(uuid.uuid4())
    admin.download_history.insert(0, {"task_id": tid2})
    admin.save_download_history()
    v2 = get_user_scope('admin_user')
    ok2 = any(r.get("task_id") == tid2 for r in v2.download_history)
    if not ok2: errors.append("持久化失败")
    v2.download_history.pop(0); v2.save_download_history()
    print(f"  {'PASS' if ok2 else 'FAIL'}")

    # TEST4: 用户隔离
    print("[4/5] 用户隔离")
    admin.download_history.insert(0, {"owner": "admin_only"})
    other_see = any(r.get("owner") == "admin_only" for r in other.download_history)
    admin.download_history.pop(0); admin.save_download_history()
    if other_see: errors.append("other看到admin数据")
    other.download_history.insert(0, {"owner": "other_only"})
    admin_see = any(r.get("owner") == "other_only" for r in admin.download_history)
    other.download_history.pop(0); other.save_download_history()
    if admin_see: errors.append("admin看到other数据")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    # TEST5: 模拟处理完成写入
    print("[5/5] 模拟处理→API可见")
    tid3 = str(uuid.uuid4())
    item = {"task_id": tid3, "folder_name": "processed", "first_image_name": "img",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pdf_path": "/f.pdf", "file_count": 1,
            "download_count": 0, "edited": False, "edit_download_count": 0}
    # 模拟 process_uploaded_folder_task 写入
    us = get_user_scope('admin_user')
    us.download_history.insert(0, item)
    us.save_download_history()
    # API 读取
    api_scope = get_user_scope('admin_user')
    ok3 = any(r.get("task_id") == tid3 for r in api_scope.download_history)
    if not ok3: errors.append("模拟写入后API不可见")
    api_scope.download_history.pop(0); api_scope.save_download_history()
    print(f"  {'PASS' if ok3 else 'FAIL'}")

    print()
    if errors:
        print(f"FAIL: {' / '.join(errors)}")
        sys.exit(1)
    print("ALL 5 PASSED")

if __name__ == "__main__":
    test_all()


# xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# 重命名接口单测：form-in智能收集整理步骤4转换记录重命名（PUT /api/download-history-item/{index}/rename）
# 覆盖：正常改名并持久化、新名为空、新名含路径分隔符/非法字符、index越界
def test_rename():
    import base64
    import json as _json
    import uuid
    from pathlib import Path as _Path
    from fastapi.testclient import TestClient
    from backend.app import app
    from backend.services.user_scope import get_user_scope

    errors = []
    client = TestClient(app)
    # 登录拿令牌（默认管理员口令测试口令的10万轮SHA-256哈希，与test_api.py一致）
    resp = client.post("/api/auth/verify", json={"password": "103e4cce4376cf4c1a32f3c49d8a75dec4674f0b639fa3ebe308b74059d54d92"})
    token = resp.json().get("token", "")
    if not token:
        print("FAIL: 登录失败，无法测试重命名接口")
        raise AssertionError("login failed")
    headers = {"Authorization": f"Bearer {token}"}
    # 从令牌payload解出用户名，历史记录要种到同一用户的scope里
    payload_b64 = token.split(".")[1]
    payload = _json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    username = payload.get("username", "")
    scope = get_user_scope(username)

    print("[rename] 准备种子记录")
    tid = str(uuid.uuid4())
    seed = {"task_id": tid, "folder_name": "重命名前文件夹", "first_image_name": "旧首页图",
            "created_at": "2026-09-28 10:00:00", "pdf_path": "/not-exist/rename-test.pdf",
            "file_count": 2, "download_count": 0, "edited": False, "edit_download_count": 0}
    scope.download_history.insert(0, seed)
    scope.save_download_history()

    print("[rename/1] 正常重命名并持久化")
    r1 = client.put("/api/download-history-item/0/rename", params={"new_name": "光伏前期文件"}, headers=headers)
    j1 = r1.json()
    if r1.status_code != 200 or j1.get("success") is not True:
        errors.append(f"正常重命名失败: {r1.status_code} {j1}")
    reloaded = get_user_scope(username)
    rec = next((x for x in reloaded.download_history if x.get("task_id") == tid), None)
    if rec is None:
        errors.append("重命名后记录丢失")
    else:
        if rec.get("folder_name") != "光伏前期文件":
            errors.append(f"folder_name未更新: {rec.get('folder_name')}")
        if rec.get("first_image_name") != "光伏前期文件":
            errors.append(f"first_image_name未更新: {rec.get('first_image_name')}")
        if rec.get("pdf_path") != "/not-exist/rename-test.pdf":
            errors.append("pdf_path不应变化")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    print("[rename/2] 新名为空")
    r2 = client.put("/api/download-history-item/0/rename", params={"new_name": ""}, headers=headers)
    if r2.status_code != 400:
        errors.append(f"空名应400: {r2.status_code}")
    r2b = client.put("/api/download-history-item/0/rename", params={"new_name": "   "}, headers=headers)
    if r2b.status_code != 400:
        errors.append(f"纯空格名应400: {r2b.status_code}")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    print("[rename/3] 新名含非法字符")
    for bad in ["a/b", "a\\b", "a<b", "a:b"]:
        rb = client.put("/api/download-history-item/0/rename", params={"new_name": bad}, headers=headers)
        if rb.status_code != 400:
            errors.append(f"非法字符{bad!r}应400: {rb.status_code}")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    print("[rename/4] index越界")
    r4 = client.put("/api/download-history-item/99999/rename", params={"new_name": "越界"}, headers=headers)
    if r4.status_code != 404:
        errors.append(f"越界应404: {r4.status_code}")
    print(f"  {'PASS' if not errors else 'FAIL'}")

    # 清理种子记录
    scope2 = get_user_scope(username)
    scope2.download_history = [x for x in scope2.download_history if x.get("task_id") != tid]
    scope2.save_download_history()

    print()
    if errors:
        print(f"RENAME FAIL: {' / '.join(errors)}")
        raise AssertionError("; ".join(errors))
    print("RENAME ALL PASSED")
