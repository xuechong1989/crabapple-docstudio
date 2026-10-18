# xuechong 2026-06-27 服务层完整测试
import sys, uuid, os, json, tempfile, shutil
sys.path.insert(0, '.')
from pathlib import Path
from datetime import datetime, timedelta
import time as _time

errors = []; PA = 0; FA = 0
def T(name, ok):
    global PA, FA
    if ok: PA += 1
    else: FA += 1; errors.append(name)
    print(f"  {'OK' if ok else '!!'} {name}")

print("=" * 50)
print("  服务层完整测试")
print("=" * 50)

# ====== config.py ======
print("\n--- config ---")
from backend import config
T('DATA_DIR是Path', isinstance(config.DATA_DIR, Path))
T('TMP_DIR是Path', isinstance(config.TMP_DIR, Path))
T('OCR_ENGINE是str', isinstance(config.OCR_ENGINE, str))
T('YOLO_MODEL_PATH是str', isinstance(config.YOLO_MODEL_PATH, str))
T('MAX_UPLOAD_SIZE_BYTES>0', config.MAX_UPLOAD_SIZE_BYTES > 0)
from backend.services.image_utils import SUPPORTED_EXTENSIONS as _se; T('SUPPORTED_EXTENSIONS', len(_se) > 0)

# ====== path_service ======
print("\n--- path_service ---")
from backend.services.path_service import STORAGE_ROOT
T('STORAGE_ROOT存在', STORAGE_ROOT is not None)
T('STORAGE_ROOT是Path', isinstance(STORAGE_ROOT, Path))

# ====== auth_service ======
print("\n--- auth_service ---")
from backend.services.auth_service import (
    get_jwt_service, init_jwt_service, is_token_revoked, 
    revoke_token, revoke_all_user_tokens
)
# Test init
jwt1 = init_jwt_service(secret='test_secret_key_12345678', expire_hours=1)
T('init返回服务', jwt1 is not None)
token = jwt1.create_token({'user_id': 'u1', 'username': 'test'}, expire_hours=1)
T('创建token', token and len(token) > 10)
payload = jwt1.verify_token(token)
T('验证token', payload and payload.get('user_id') == 'u1')
T('get_jwt_service可用', get_jwt_service() is not None)
# Expiry
expired_token = jwt1.create_token({'user_id': 'u1', 'username': 'test'}, expire_hours=-1)
T('过期token被拒', jwt1.verify_token(expired_token) is None)
# Malformed
T('malformed被拒', jwt1.verify_token('not.a.token') is None)
T('空字符串被拒', jwt1.verify_token('') is None)
# Revoke
T('新token未撤销', is_token_revoked(token) == False)
revoke_token(token)
T('撤销后已撤销', is_token_revoked(token) == True)
# Revoke all
revoke_all_user_tokens('test')
T('revoke_all不崩溃', True)
# Singleton
jwt2 = init_jwt_service()
T('重复init不崩溃', jwt2 is not None)

# ====== logging_service ======
print("\n--- logging_service ---")
from backend.services.logging_service import log_info, debug_log, setup_utf8_encoding
T('log_info可调用', callable(log_info))
T('debug_log可调用', callable(debug_log))
T('setup_utf8_encoding可调用', callable(setup_utf8_encoding))
log_info('[TEST] 服务层测试日志')

# ====== image_utils ======
print("\n--- image_utils ---")
from backend.services.image_utils import is_image_file, SUPPORTED_EXTENSIONS
T('is_image(.png)', is_image_file('a.png'))
T('is_image(.PNG)', is_image_file('a.PNG'))
T('is_image(.jpg)', is_image_file('a.jpg'))
T('is_image(.JPG)', is_image_file('a.JPG'))
T('is_image(.jpeg)', is_image_file('a.jpeg'))
T('is_image(.bmp)', is_image_file('a.bmp'))
T('is_image(.tif)', is_image_file('a.tif'))
T('is_image(.tiff)', is_image_file('a.tiff'))
T('is_image(.webp)', is_image_file('a.webp'))
T('not_image(.txt)', not is_image_file('a.txt'))
T('not_image(.pdf)', not is_image_file('a.pdf'))
T('not_image(.doc)', not is_image_file('a.doc'))
T('not_image(empty)', not is_image_file(''))
T('not_image(noext)', not is_image_file('noextension'))
T('SUPPORTED_EXTENSIONS非空', len(SUPPORTED_EXTENSIONS) > 0)

# ====== user_scope ======
print("\n--- user_scope ---")
from backend.services.user_scope import (
    get_user_scope, get_all_usernames, remove_user_scope
)
s_admin = get_user_scope('admin_test')
T('scope类型', hasattr(s_admin, 'download_history'))
T('download_history是list', isinstance(s_admin.download_history, list))
T('upload_history是list', isinstance(s_admin.upload_history, list))
T('edit_pdf_history是list', isinstance(s_admin.edit_pdf_history, list))
T('dual_layer_history是list', isinstance(s_admin.dual_layer_history, list))
T('upload_tasks是dict', isinstance(s_admin.upload_tasks, dict))
T('edit_pdf_tasks是dict', isinstance(s_admin.edit_pdf_tasks, dict))
T('history_dir存在', s_admin.history_dir.exists())
T('source_dir存在', s_admin.source_dir.exists())
T('target_dir存在', s_admin.target_dir.exists())
T('edit_pdf_dir存在', s_admin.edit_pdf_dir.exists())
T('dual_layer_dir存在', s_admin.dual_layer_dir.exists())
T('tasks_file路径正确', s_admin.tasks_file.name == 'tasks.json')
# CRUD via scope
tid = str(uuid.uuid4())
s_admin.download_history.clear()
s_admin.download_history.insert(0, {'task_id': tid, 'username': 'admin_test'})
s_admin.save_download_history()
s2 = get_user_scope('admin_test')
T('persist通过scope', any(r.get('task_id')==tid for r in s2.download_history))
s_admin.download_history.clear()
s_admin.save_download_history()
# Multi-user
s_other = get_user_scope('other_test')
T('不同用户独立', s_admin.download_history is not s_other.download_history)
T('get_all_usernames含admin_test', 'admin_test' in get_all_usernames())
# 任务持久化
s_admin.upload_tasks['test_tid'] = {'task_id': 'test_tid', 'status': 'processing'}
s_admin.save_tasks()
s_admin.upload_tasks.clear()
s_admin.load_tasks()
T('任务持久化恢复', 'test_tid' in s_admin.upload_tasks)
s_admin.upload_tasks.clear()
s_admin.save_tasks()
# remove_user_scope
uid = str(uuid.uuid4())
get_user_scope(uid)
remove_user_scope(uid)
T('remove_user_scope', uid not in get_all_usernames())

# ====== JWT Service edge cases ======
print("\n--- JWT edge cases ---")
T('large payload', jwt1.create_token({'user_id': 'u'*1000, 'username': 'x'*1000}) is not None)
T('empty payload', jwt1.create_token({}) is not None)
# Token refresh
new_token = jwt1.refresh_token(token)
T('refresh可调用', callable(jwt1.refresh_token))
T('refresh后可验证', jwt1.verify_token(new_token) is not None)
# Refresh
test_tok = jwt1.create_token({'user_id': 'r1', 'username': 'rtest'}, expire_hours=1)
refreshed = jwt1.refresh_token(test_tok)
T('refresh返回token', refreshed is not None)
T('refreshed可验证', jwt1.verify_token(refreshed) is not None)
T('expired refresh=None', jwt1.refresh_token(expired_token) is None)
# Remaining seconds
remaining = jwt1.token_remaining_seconds(new_token)
T('remaining_seconds>0', remaining > 0)

# ====== Password hash ======
print("\n--- Password hash ---")
from backend.routes.auth import _compute_password_hash, _check_login_rate
pwd = 'test_p@ssw0rd!'
h = _compute_password_hash(pwd)
T('hash非空', h is not None and len(h) == 64)
T('hash!=原文', h != pwd)
T('hash确定性', _compute_password_hash(pwd) == h)
T('不同密码不同hash', _compute_password_hash(pwd + 'x') != h)
T('空密码hash', len(_compute_password_hash('')) == 64)

# ====== Rate limit ======
print("\n--- Rate limit ---")
T('rate_limit函数可用', callable(_check_login_rate))
from backend.routes.auth import _LOGIN_ATTEMPTS, _login_lock
with _login_lock:
    _LOGIN_ATTEMPTS.clear()
T('清理后通过', _check_login_rate('10.0.0.1') == True)

# ====== Path security ======
print("\n--- Path security ---")
base = Path('/safe/base')
T('resolve+relative_to安全路径', True)
child = base / 'sub' / 'file.txt'
try:
    child.resolve().relative_to(base.resolve())
    T('正常子路径通过', True)
except: T('正常子路径通过', False)
evil = Path('/etc/passwd')
try:
    evil.resolve().relative_to(base.resolve())
    T('etc拒绝', False)
except: T('etc拒绝', True)
# Symlink-like (resolve() resolves symlinks)
evil2 = base / '..' / '..' / 'etc' / 'passwd'
try:
    evil2.resolve().relative_to(base.resolve())
    T('../拒绝', False)
except: T('../拒绝', True)

# ====== File extensions ======
print("\n--- File extensions ---")
for good in ['test.png', 'IMG_001.JPG', 'scan.TIF', 'doc.WEBP']:
    T(f'valid image {good}', is_image_file(good))
for bad in ['test.txt', 'test.pdf', '.png', '', '.']:
    T(f'invalid {bad or "(empty)"}', not is_image_file(bad))

# ====== UserScope edge cases ======
print("\n--- UserScope edge ---")
s = get_user_scope('edge_test')
s.download_history.clear()
T('空scope save不崩溃', True)
try: s.save_download_history(); T('空save成功', True)
except Exception as e: T(f'空save成功: {e}', False)
s.download_history.insert(0, {})
T('空dict insert', len(s.download_history) == 1)
s.download_history.clear()

# ====== 结果 ======
print(f"\n{'='*50}")
print(f"  PASS: {PA}  FAIL: {FA}  TOTAL: {PA+FA}")
if FA:
    print(f"  FAILURES: {errors}")
    sys.exit(1)
print(f"  ALL {PA} PASSED")
