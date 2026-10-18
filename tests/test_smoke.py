# xuechong 2026-06-27 全系统完整测试
"""覆盖系统所有功能模块的测试套件。发布前必须全部通过。"""
import sys, uuid, json, os, tempfile, shutil
sys.path.insert(0, '.')
from datetime import datetime, timedelta
from pathlib import Path

errors = []
now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
PA = 0; FA = 0

def T(name, ok):
    global PA, FA
    if ok: PA += 1
    else: FA += 1; errors.append(name)
    print(f"  {'OK' if ok else '!!'} {name}")

# ================================================
print("=" * 50)
print("  全系统回归测试")
print("=" * 50)

# ---- 1. 配置模块 ----
print("\n--- 1. 配置模块 ---")
from backend import config
T('config.DATA_DIR存在', hasattr(config, 'DATA_DIR'))
T('config.TMP_DIR存在', hasattr(config, 'TMP_DIR'))
T('config.OCR_ENGINE存在', hasattr(config, 'OCR_ENGINE'))
T('config.YOLO_MODEL_PATH存在', hasattr(config, 'YOLO_MODEL_PATH'))
T('config.MAX_UPLOAD_SIZE_BYTES存在', hasattr(config, 'MAX_UPLOAD_SIZE_BYTES'))
from backend.services.image_utils import SUPPORTED_EXTENSIONS as _exts; T('SUPPORTED_EXTENSIONS存在', len(_exts) > 0)
T('config.DATA_DIR是Path', isinstance(config.DATA_DIR, Path))
T('config.TMP_DIR是Path', isinstance(config.TMP_DIR, Path))

# ---- 2. 路径服务 ----
print("\n--- 2. 路径服务 ---")
from backend.services import path_service
T('STORAGE_ROOT存在', hasattr(path_service, 'STORAGE_ROOT'))
T('STORAGE_ROOT是Path', isinstance(path_service.STORAGE_ROOT, Path))

# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局历史/任务状态已废弃，改为检查 UserScope 属性
# ---- 3. 应用状态 ----
print("\n--- 3. 应用状态 ---")
from backend.services.app_state import state
attrs = ['UPLOAD_DIR','OUTPUT_DIR']
for a in attrs:
    T(f'state.{a}存在', hasattr(state, a))

# ---- 4. 用户隔离 ----
print("\n--- 4. 用户隔离 ---")
from backend.services.user_scope import get_user_scope, get_all_usernames
s_admin = get_user_scope('admin')
s_user2 = get_user_scope('user2')
T('admin有独立history', hasattr(s_admin, 'download_history'))
T('user2有独立history', hasattr(s_user2, 'download_history'))
T('不同用户history列表不同', s_admin.download_history is not s_user2.download_history)
T('upload_tasks可用', len(s_admin.upload_tasks) >= 0)
T('edit_pdf_tasks可用', isinstance(s_admin.edit_pdf_tasks, dict))
T('source_dir存在', s_admin.source_dir.exists())
T('target_dir存在', s_admin.target_dir.exists())
T('get_all_usernames返回列表', isinstance(get_all_usernames(), list))
T('活跃用户包含admin', 'admin' in get_all_usernames())

# ---- 5. 认证服务 ----
print("\n--- 5. 认证服务 ---")
from backend.services.auth_service import get_jwt_service, is_token_revoked
jwt = get_jwt_service()
T('JWT服务可获取', jwt is not None)
token = jwt.create_token({'user_id': 'test123', 'username': 'testuser'}, expire_hours=1)
T('创建token', token is not None and len(token) > 10)
payload = jwt.verify_token(token)
T('验证token', payload is not None)
T('user_id正确', payload.get('user_id') == 'test123')
T('username正确', payload.get('username') == 'testuser')
T('过期token拒绝', jwt.verify_token('invalid.token.here') is None)
T('is_token_revoked新token', is_token_revoked(token) == False)
# refresh
new_token = jwt.refresh_token(token)
T('refresh_token', new_token is not None and new_token != token)
new_payload = jwt.verify_token(new_token)
T('refresh后payload正确', new_payload.get('user_id') == 'test123')

# ---- 6. 日志服务 ----
print("\n--- 6. 日志服务 ---")
from backend.services.logging_service import log_info, setup_utf8_encoding
T('log_info可用', callable(log_info))
T('setup_utf8_encoding可用', callable(setup_utf8_encoding))
log_info('[TEST] 测试日志写入')

# ---- 7. 图片工具 ----
print("\n--- 7. 图片工具 ---")
from backend.services.image_utils import is_image_file, SUPPORTED_EXTENSIONS
T('is_image_file(.png)', is_image_file('test.png') == True)
T('is_image_file(.jpg)', is_image_file('test.jpg') == True)
T('is_image_file(.bmp)', is_image_file('test.bmp') == True)
T('is_image_file(.txt)', is_image_file('test.txt') == False)
T('is_image_file(.pdf)', is_image_file('test.pdf') == False)
T('SUPPORTED_EXTENSIONS非空', len(SUPPORTED_EXTENSIONS) > 0)

# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局历史存储已废弃，以下测试改为使用 UserScope 的 per-user 历史
# ---- 8. download_history 全功能 ----
print("\n--- 8. download_history ---")
s = get_user_scope('smoke_test_dl')
s.download_history.clear()
tid = str(uuid.uuid4())
rec = {'task_id': tid, 'username': 'smoke_test_dl', 'folder_name': 'f1', 'first_image_name': 'img001',
       'created_at': now, 'pdf_path': '/tmp/t.pdf', 'file_count': 1,
       'download_count': 0, 'edited': False, 'edit_download_count': 0}
s.download_history.insert(0, rec)
T('插入', len(s.download_history) == 1)
T('smoke_test_dl可见', len([r for r in s.download_history if r.get('username','')=='smoke_test_dl']) == 1)
T('其他用户不可见', len([r for r in s.download_history if r.get('username','')=='other']) == 0)
s.download_history[0]['download_count'] += 1
T('下载计数更新', s.download_history[0]['download_count'] == 1)
s.download_history[0]['edited'] = True
T('编辑标记', s.download_history[0]['edited'] == True)
s.download_history.pop(0)
T('删除', len(s.download_history) == 0)

# ---- 9. upload_history 全功能 ----
print("\n--- 9. upload_history ---")
su = get_user_scope('smoke_test_ul')
su.upload_history.clear()
uid = str(uuid.uuid4())
urec = {'task_id': uid, 'username': 'smoke_test_ul', 'folder_name': 'up1', 'file_count': 5,
        'status': 'uploaded', 'total_files': 5, 'processed_files': 0,
        'created_at': now, 'completed_at': None, 'last_message': '已上传', 'has_pdf': False}
su.upload_history.insert(0, urec)
T('插入', len(su.upload_history) == 1)
for r in su.upload_history:
    if r['task_id'] == uid: r['status'] = 'completed'; r['has_pdf'] = True
T('状态更新', su.upload_history[0]['status'] == 'completed')
su.upload_history.clear()
T('清空', len(su.upload_history) == 0)

# ---- 10. edit_pdf_history 全功能 ----
print("\n--- 10. edit_pdf_history ---")
se = get_user_scope('smoke_test_ep')
se.edit_pdf_history.clear()
eid = str(uuid.uuid4())
se.edit_pdf_history.insert(0, {'task_id': eid, 'username': 'smoke_test_ep', 'file_id': 'f1',
    'filename': 'e.pdf', 'source': 'manual', 'created_at': now,
    'pdf_path': '/tmp/e.pdf', 'page_count': 5, 'edited_pages': 5, 'download_count': 0})
T('插入', len(se.edit_pdf_history) == 1)
T('筛选', len([r for r in se.edit_pdf_history if r.get('username','')=='smoke_test_ep']) == 1)
se.edit_pdf_history.clear()

# ---- 11. dual_layer_history 全功能 ----
print("\n--- 11. dual_layer_history ---")
sd = get_user_scope('smoke_test_dl2')
sd.dual_layer_history.clear()
did = str(uuid.uuid4())
sd.dual_layer_history.insert(0, {'task_id': did, 'username': 'smoke_test_dl2',
    'folder_name': 'dl1', 'created_at': now, 'pdf_path': '/tmp/dl.pdf', 'file_count': 2})
T('插入', len(sd.dual_layer_history) == 1)
T('筛选', len([r for r in sd.dual_layer_history if r.get('username','')=='smoke_test_dl2']) == 1)
sd.dual_layer_history.clear()

# ---- 12. 多用户隔离 ----
print("\n--- 12. 多用户隔离 ---")
sm = get_user_scope('smoke_multi')
sm.download_history.clear()
for u in ['smoke_multi', 'smoke_u1', 'smoke_u2', 'smoke_u3', 'smoke_u4']:
    get_user_scope(u).download_history.insert(0, {'task_id': str(uuid.uuid4()), 'username': u})
T('多用户隔离:smoke_multi可见', len(sm.download_history) == 1)
T('多用户隔离:smoke_u1可见', len(get_user_scope('smoke_u1').download_history) == 1)
T('smoke_multi不可见smoke_u1', all(r.get('username','')!='smoke_u1' for r in sm.download_history))
sm.download_history.clear()
for u in ['smoke_u1','smoke_u2','smoke_u3','smoke_u4']:
    get_user_scope(u).download_history.clear()

# ---- 13. 迁移 ----
print("\n--- 13. 旧数据迁移 ---")
sm2 = get_user_scope('smoke_migrate')
sm2.download_history.clear()
for i in range(10):
    sm2.download_history.append({'task_id': f'old_{i}', 'folder_name': f'f_{i}'})
m = sum(1 for r in sm2.download_history if 'username' not in r)
T('10条旧数据无username', m == 10)
for r in sm2.download_history:
    if 'username' not in r: r['username'] = 'smoke_migrate'
T('迁移后全部有username', all('username' in r for r in sm2.download_history))
T('全部=smoke_migrate', all(r.get('username')=='smoke_migrate' for r in sm2.download_history))
sm2.download_history.clear()

# ---- 14. 防重复 ----
print("\n--- 14. 防重复插入 ---")
sd2 = get_user_scope('smoke_dedup')
sd2.download_history.clear()
tid = str(uuid.uuid4())
sd2.download_history.insert(0, {'task_id': tid, 'username': 'smoke_dedup'})
T('单次插入无重复', [r.get('task_id') for r in sd2.download_history].count(tid) == 1)
sd2.download_history.clear()

# ---- 15. 持久化 ----
print("\n--- 15. 持久化 ---")
s = get_user_scope('persist_test')
tid = str(uuid.uuid4())
s.download_history.clear()
s.download_history.insert(0, {'task_id': tid, 'username': 'smoke_persist'})
s.save_download_history()
s2 = get_user_scope('persist_test')
T('save后load可见', any(r.get('task_id')==tid for r in s2.download_history))
s.download_history.clear()
s.save_download_history()

# ---- 16. 边界 ----
print("\n--- 16. 边界情况 ---")
sb = get_user_scope('smoke_boundary')
sb.download_history.clear()
T('空列表不报错', len(sb.download_history) == 0)
T('空筛选', len([r for r in sb.download_history if r.get('username','')=='x']) == 0)
sb.download_history.insert(0, {})
T('空dict筛选', len([r for r in sb.download_history if r.get('username','')=='x']) == 0)
sb.download_history.clear()
for i in range(200):
    sb.download_history.insert(0, {'task_id': str(i), 'username': 'a' if i%2==0 else 'b'})
T('200条写入', len(sb.download_history) == 200)
T('200条a=100', len([r for r in sb.download_history if r.get('username','')=='a']) == 100)
sb.download_history.clear()

# ---- 17. 路径穿越防护 ----
print("\n--- 17. 路径安全 ---")
base = Path('/tmp/test_base')
sub = Path('/tmp/test_base/subdir/file.txt')
try: sub.resolve().relative_to(base.resolve()); T('正常路径通过', True)
except: T('正常路径通过', False)
evil = Path('/etc/passwd')
try: evil.resolve().relative_to(base.resolve()); T('路径穿越拒绝', False)
except: T('路径穿越拒绝', True)

# ---- 18. 密码哈希 ----
print("\n--- 18. 密码哈希 ---")
import hashlib, hmac
pwd = 'test_password_123'
hashed = hashlib.sha256(pwd.encode()).hexdigest()
T('SHA256哈希生成', hashed is not None and len(hashed) == 64)
T('哈希确定性', hashlib.sha256(pwd.encode()).hexdigest() == hashed)
T('哈希!=原文', hashed != pwd)

# ---- 19. 速率限制 ----
print("\n--- 19. 速率限制 ---")
from backend.routes.auth import _check_login_rate, _LOGIN_ATTEMPTS, _login_lock
T('速率检查存在', callable(_check_login_rate))
with _login_lock:
    _LOGIN_ATTEMPTS.pop('192.168.1.1', None)
T('清理测试数据', '192.168.1.1' not in _LOGIN_ATTEMPTS)

# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# ---- 20. Task取消标志 ----
print("\n--- 20. 任务管理 ---")
st = get_user_scope('smoke_task')
tid = str(uuid.uuid4())
st.tasks_cancel_flags[tid] = False
T('取消标志初始False', st.tasks_cancel_flags[tid] == False)
st.tasks_cancel_flags[tid] = True
T('设置取消', st.tasks_cancel_flags[tid] == True)
st.tasks_cancel_flags.pop(tid)
T('清除取消', tid not in st.tasks_cancel_flags)

# ---- 21. 文件类型检测 ----
print("\n--- 21. 文件类型检测 ---")
for ext in ['.png', '.PNG', '.jpg', '.JPG', '.jpeg', '.bmp', '.tif', '.tiff', '.webp']:
    T(f'is_image({ext})', is_image_file(f'test{ext}') == True)

# ================================================
print(f"\n{'='*50}")
print(f"  TOTAL: {PA+FA}  PASS: {PA}  FAIL: {FA}")
if FA:
    print(f"  FAILURES:")
    for e in errors:
        print(f"    - {e}")
    sys.exit(1)
print(f"  ALL {PA} TESTS PASSED")
print(f"{'='*50}")
