# -*- coding: utf-8 -*-
# xuechong 2026-07-19 用户隔离机制测试用例
"""用户隔离机制测试 — 验证 UserScope 的数据隔离、持久化、边界条件"""
import sys, os, json, shutil
sys.path.insert(0, '.')
from pathlib import Path
from datetime import datetime

errors = []; PA = 0; FA = 0
def T(name, ok):
    global PA, FA
    if ok: PA += 1
    else: FA += 1; errors.append(name)
    print(f"  {'OK' if ok else '!!'} {name}")

print("=" * 50)
print("  用户隔离机制测试")
print("=" * 50)

# ====== 准备临时测试目录 ======
TEST_ROOT = Path("/tmp/ds_isolation_test")
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
TEST_ROOT.mkdir(parents=True)

# 覆盖 USERS_ROOT 以使用临时目录
import backend.services.path_service as _ps
_original_users_root = _ps.USERS_ROOT
_ps.USERS_ROOT = TEST_ROOT

from backend.services.user_scope import (
    UserScope, get_user_scope, get_all_usernames, remove_user_scope, _user_scopes, _scopes_lock
)
from backend.models.user import validate_username

# ====== 1. 用户名校验 ======
print("\n--- 1. 用户名校验 ---")
ok, msg = validate_username("admin")
T("合法用户名 admin", ok)
ok, msg = validate_username("test_user-01")
T("合法用户名 test_user-01", ok)
ok, msg = validate_username("")
T("空用户名拒绝", not ok)
ok, msg = validate_username("a")
T("单字符用户名拒绝", not ok)
ok, msg = validate_username("logs")
T("保留名 logs 拒绝", not ok)
ok, msg = validate_username("CONFIG")
T("保留名 CONFIG 拒绝（大小写）", not ok)
ok, msg = validate_username("normal_user")
T("合法用户名 normal_user", ok)

# ====== 2. UserScope 创建和目录隔离 ======
print("\n--- 2. UserScope 创建和目录隔离 ---")
scope_a = UserScope("alice")
scope_b = UserScope("bob")

T("alice scope 创建", scope_a.username == "alice")
T("bob scope 创建", scope_b.username == "bob")
T("alice.upload_dir 存在", scope_a.upload_dir.exists())
T("bob.upload_dir 存在", scope_b.upload_dir.exists())
T("alice.user_root 存在", scope_a.user_root.exists())
T("目录不同", scope_a.user_root != scope_b.user_root)
T("upload_dir 不同", scope_a.upload_dir != scope_b.upload_dir)
T("output_dir 不同", scope_a.output_dir != scope_b.output_dir)
T("history_dir 不同", scope_a.history_dir != scope_b.history_dir)
T("tasks_file 不同", scope_a.tasks_file != scope_b.tasks_file)

# ====== 3. 任务隔离 ======
print("\n--- 3. 任务隔离 ---")
scope_a.upload_tasks["task001"] = {
    "task_id": "task001", "status": "processing", "username": "alice",
    "total_files": 5, "processed_files": 2
}
scope_b.upload_tasks["task002"] = {
    "task_id": "task002", "status": "completed", "username": "bob",
    "total_files": 3, "processed_files": 3
}

T("alice 有 task001", "task001" in scope_a.upload_tasks)
T("alice 无 task002", "task002" not in scope_a.upload_tasks)
T("bob 有 task002", "task002" in scope_b.upload_tasks)
T("bob 无 task001", "task001" not in scope_b.upload_tasks)
T("alice task001 状态正确", scope_a.upload_tasks["task001"]["status"] == "processing")
T("bob task002 状态正确", scope_b.upload_tasks["task002"]["status"] == "completed")

# ====== 4. edit_pdf_tasks 隔离 ======
print("\n--- 4. edit_pdf_tasks 隔离 ---")
scope_a.edit_pdf_tasks["ep001"] = {"folder_name": "test.pdf", "username": "alice"}
scope_b.edit_pdf_tasks["ep002"] = {"folder_name": "doc.pdf", "username": "bob"}

T("alice 有 ep001", "ep001" in scope_a.edit_pdf_tasks)
T("alice 无 ep002", "ep002" not in scope_a.edit_pdf_tasks)
T("bob 有 ep002", "ep002" in scope_b.edit_pdf_tasks)
T("bob 无 ep001", "ep001" not in scope_b.edit_pdf_tasks)

# ====== 5. 取消标志隔离 ======
print("\n--- 5. 取消标志隔离 ---")
scope_a.tasks_cancel_flags["task001"] = True
T("alice task001 已取消", scope_a.tasks_cancel_flags.get("task001") == True)
T("bob 无取消标志", scope_b.tasks_cancel_flags.get("task001") is None)

# ====== 6. 历史记录隔离 ======
print("\n--- 6. 历史记录隔离 ---")
scope_a.download_history.append({"task_id": "t1", "folder_name": "a_folder"})
scope_b.download_history.append({"task_id": "t2", "folder_name": "b_folder"})
scope_a.upload_history.append({"task_id": "t1", "status": "uploaded"})
scope_b.upload_history.append({"task_id": "t2", "status": "completed"})

T("alice 下载历史 1 条", len(scope_a.download_history) == 1)
T("bob 下载历史 1 条", len(scope_b.download_history) == 1)
T("alice 历史是 a_folder", scope_a.download_history[0]["folder_name"] == "a_folder")
T("bob 历史是 b_folder", scope_b.download_history[0]["folder_name"] == "b_folder")
T("alice 上传历史 1 条", len(scope_a.upload_history) == 1)
T("bob 上传历史 1 条", len(scope_b.upload_history) == 1)

# ====== 7. 任务持久化（save/load） ======
print("\n--- 7. 任务持久化 ---")
scope_a.save_tasks()
T("alice tasks.json 存在", scope_a.tasks_file.exists())

# 创建新 scope 实例验证加载
scope_a2 = UserScope("alice")
T("alice 重新加载有 task001", "task001" in scope_a2.upload_tasks)
T("alice 加载状态正确（processing→interrupted）", scope_a2.upload_tasks["task001"]["status"] == "interrupted")
T("alice 加载 username 正确", scope_a2.upload_tasks["task001"]["username"] == "alice")

# ====== 8. 历史持久化 ======
print("\n--- 8. 历史持久化 ---")
scope_a.save_download_history()
scope_a.save_upload_history()
scope_a3 = UserScope("alice")
T("alice 下载历史持久化", len(scope_a3.download_history) == 1)
T("alice 上传历史持久化", len(scope_a3.upload_history) == 1)
T("alice 下载历史内容正确", scope_a3.download_history[0]["folder_name"] == "a_folder")

# ====== 9. get_user_scope 缓存 ======
print("\n--- 9. get_user_scope 缓存 ---")
# 清理缓存
with _scopes_lock:
    _user_scopes.clear()

s1 = get_user_scope("charlie")
s2 = get_user_scope("charlie")
T("同一用户返回同一实例", s1 is s2)
T("charlie scope 正确", s1.username == "charlie")

# ====== 10. get_all_usernames ======
print("\n--- 10. get_all_usernames ---")
with _scopes_lock:
    _user_scopes.clear()
get_user_scope("user_a")
get_user_scope("user_b")
names = get_all_usernames()
T("get_all_usernames 返回 2 个", len(names) == 2)
T("包含 user_a", "user_a" in names)
T("包含 user_b", "user_b" in names)

# ====== 11. remove_user_scope ======
print("\n--- 11. remove_user_scope ---")
remove_user_scope("user_a")
names = get_all_usernames()
T("删除后只剩 1 个", len(names) == 1)
T("user_a 已移除", "user_a" not in names)
T("user_b 仍在", "user_b" in names)

# ====== 12. 边界条件 ======
print("\n--- 12. 边界条件 ---")
scope_empty = UserScope("empty_user")
T("空 scope 初始化不崩溃", scope_empty.username == "empty_user")
T("空 scope tasks 为空", len(scope_empty.upload_tasks) == 0)
T("空 scope history 为空", len(scope_empty.download_history) == 0)

# 空 scope save 不崩溃
try:
    scope_empty.save_tasks()
    scope_empty.save_download_history()
    scope_empty.save_upload_history()
    scope_empty.save_edit_pdf_history()
    scope_empty.save_dual_layer_history()
    T("空 scope 全部 save 不崩溃", True)
except Exception as e:
    T("空 scope 全部 save 不崩溃", False)

# ====== 13. 路径安全性 ======
print("\n--- 13. 路径安全性 ---")
T("user_root 不含 ..", ".." not in str(scope_a.user_root))
T("upload_dir 在 user_root 内", str(scope_a.upload_dir).startswith(str(scope_a.user_root)))
T("output_dir 在 user_root 内", str(scope_a.output_dir).startswith(str(scope_a.user_root)))
T("history_dir 在 user_root 内", str(scope_a.history_dir).startswith(str(scope_a.user_root)))

# ====== 14. _find_task_scope 跨用户查找 ======
print("\n--- 14. _find_task_scope 跨用户查找 ---")
from backend.routes.edit_pdf import _find_task_scope, _scope_from_task

# 重新注册 alice/bob 到缓存（测试 9 清空了缓存）并恢复数据
get_user_scope("alice").edit_pdf_tasks["ep001"] = {"folder_name": "test.pdf", "username": "alice"}
get_user_scope("bob").edit_pdf_tasks["ep002"] = {"folder_name": "doc.pdf", "username": "bob"}
get_user_scope("bob").upload_tasks["task002"] = {
    "task_id": "task002", "status": "completed", "username": "bob",
    "total_files": 3, "processed_files": 3
}

task_a, scope_found_a = _find_task_scope("ep001")
T("跨用户查找 ep001 找到", task_a is not None)
T("ep001 属于 alice", scope_found_a.username == "alice")

task_b, scope_found_b = _find_task_scope("ep002")
T("跨用户查找 ep002 找到", task_b is not None)
T("ep002 属于 bob", scope_found_b.username == "bob")

task_none, scope_none = _find_task_scope("nonexistent")
T("不存在的 task 返回 None", task_none is None)
T("不存在的 task scope 为 None", scope_none is None)

# _scope_from_task
scope_from = _scope_from_task("ep001")
T("_scope_from_task 返回 scope", scope_from is not None)
T("_scope_from_task 正确用户", scope_from.username == "alice")

scope_from_none = _scope_from_task("nonexistent")
T("_scope_from_task 不存在返回 None", scope_from_none is None)

# ====== 15. _aggregate_tasks 聚合 ======
print("\n--- 15. _aggregate_tasks 聚合 ---")
from backend.routes.system import _aggregate_tasks

# alice 有 task001，bob 有 task002
all_tasks = _aggregate_tasks()
T("聚合包含 task001", "task001" in all_tasks)
T("聚合包含 task002", "task002" in all_tasks)
T("聚合总数 2", len(all_tasks) == 2)

# ====== 16. dual_layer 用户隔离目录 ======
print("\n--- 16. dual_layer 用户隔离目录 ---")
T("alice dual_layer_dir 存在", scope_a.dual_layer_dir.exists())
T("bob dual_layer_dir 存在", scope_b.dual_layer_dir.exists())
T("dual_layer_dir 不同", scope_a.dual_layer_dir != scope_b.dual_layer_dir)
T("alice dual_layer 在 user_root 内", str(scope_a.dual_layer_dir).startswith(str(scope_a.user_root)))
T("bob dual_layer 在 user_root 内", str(scope_b.dual_layer_dir).startswith(str(scope_b.user_root)))

# ====== 17. dual_layer_history 隔离 ======
print("\n--- 17. dual_layer_history 隔离 ---")
scope_a.dual_layer_history.append({"id": "dl001", "name": "a.pdf", "username": "alice"})
scope_b.dual_layer_history.append({"id": "dl002", "name": "b.pdf", "username": "bob"})
T("alice dual_layer_history 1 条", len(scope_a.dual_layer_history) == 1)
T("bob dual_layer_history 1 条", len(scope_b.dual_layer_history) == 1)
T("alice dl 记录正确", scope_a.dual_layer_history[0]["name"] == "a.pdf")
T("bob dl 记录正确", scope_b.dual_layer_history[0]["name"] == "b.pdf")

scope_a.save_dual_layer_history()
scope_a_reload = UserScope("alice")
T("dual_layer_history 持久化", len(scope_a_reload.dual_layer_history) == 1)
T("dual_layer_history 内容正确", scope_a_reload.dual_layer_history[0]["id"] == "dl001")

# ====== 18. edit_pdf_history 隔离 ======
print("\n--- 18. edit_pdf_history 隔离 ---")
scope_a.edit_pdf_history.append({"task_id": "ep001", "filename": "test.pdf", "username": "alice"})
scope_b.edit_pdf_history.append({"task_id": "ep002", "filename": "doc.pdf", "username": "bob"})
T("alice edit_pdf_history 1 条", len(scope_a.edit_pdf_history) == 1)
T("bob edit_pdf_history 1 条", len(scope_b.edit_pdf_history) == 1)

scope_a.save_edit_pdf_history()
scope_a_reload2 = UserScope("alice")
T("edit_pdf_history 持久化", len(scope_a_reload2.edit_pdf_history) == 1)
T("edit_pdf_history 内容正确", scope_a_reload2.edit_pdf_history[0]["filename"] == "test.pdf")

# ====== 19. tasks_cancel_flags 操作 ======
print("\n--- 19. tasks_cancel_flags 操作 ---")
scope_c = UserScope("charlie")
scope_c.upload_tasks["t1"] = {"status": "processing"}
T("charlie 初始无取消标志", not scope_c.is_cancelled("t1"))
scope_c.cancel_task("t1")
T("charlie t1 已取消", scope_c.is_cancelled("t1"))
scope_c.clear_cancel_flag("t1")
T("charlie t1 取消标志已清除", not scope_c.is_cancelled("t1"))

# ====== 20. process_task username 参数签名 ======
print("\n--- 20. process_task 参数签名 ---")
import inspect
from backend.services.history_service import process_task as hsvc_process_task
sig = inspect.signature(hsvc_process_task)
params = list(sig.parameters.keys())
T("process_task 有 task_id 参数", "task_id" in params)
T("process_task 有 file_paths 参数", "file_paths" in params)
T("process_task 有 username 参数", "username" in params)
T("username 默认值为 admin", sig.parameters["username"].default == "admin")

# ====== 21. batch_tasks 隔离（BUG3 修复验证） ======
print("\n--- 21. batch_tasks 隔离 ---")
scope_a.batch_tasks["bt001"] = {"task_id": "bt001", "status": "processing", "username": "alice"}
scope_b.batch_tasks["bt002"] = {"task_id": "bt002", "status": "completed", "username": "bob"}
T("alice 有 bt001", "bt001" in scope_a.batch_tasks)
T("alice 无 bt002", "bt002" not in scope_a.batch_tasks)
T("bob 有 bt002", "bt002" in scope_b.batch_tasks)
T("bob 无 bt001", "bt001" not in scope_b.batch_tasks)
T("batch_tasks 字典独立", scope_a.batch_tasks is not scope_b.batch_tasks)

# xuechong 2026-07-20 BUG3: process_batch_convert 必须有 username 参数以定位 scope
from backend.routes.directory import process_batch_convert
sig2 = inspect.signature(process_batch_convert)
params2 = list(sig2.parameters.keys())
T("process_batch_convert 有 task_id 参数", "task_id" in params2)
T("process_batch_convert 有 username 参数", "username" in params2)
T("username 是第 2 个参数", params2.index("username") == 1)

# ====== 清理 ======
_ps.USERS_ROOT = _original_users_root
shutil.rmtree(TEST_ROOT, ignore_errors=True)

# ====== 结果 ======
print("\n" + "=" * 50)
if FA == 0:
    print(f"  ALL {PA} TESTS PASSED")
else:
    print(f"  PASS: {PA}  FAIL: {FA}")
    print(f"  失败项: {errors}")
print("=" * 50)
# xuechong 2026-08-06 研发BUG-0016-图档扫描-3.1.03-图片转PDF性能优化 pytest 收集时不触发 sys.exit，仅直接运行时退出
if __name__ == "__main__":
    sys.exit(0 if FA == 0 else 1)
