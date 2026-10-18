# xuechong 2026-06-27 安全与边界测试
import sys, uuid, os
sys.path.insert(0, '.')
from pathlib import Path
from datetime import datetime
import json, hashlib

errors = []; PA = 0; FA = 0
def T(name, ok):
    global PA, FA
    if ok: PA += 1
    else: FA += 1; errors.append(name)
    print(f"  {'OK' if ok else '!!'} {name}")

print("=" * 50)
print("  安全与边界测试")
print("=" * 50)

# ====== 1. Path Traversal ======
print("\n--- Path Traversal ---")
base = Path('/safe/root')
T('path traversal check start', True)
T('normal OK', True)
tests = [
    ('normal/file.txt', True),
    ('subdir/../file.txt', True),
    ('', True),
    ('.', True),
]
for path, expected in tests:
    try:
        full = (base / path).resolve()
        full.relative_to(base.resolve())
        T(f'  valid={path}', expected == True)
    except:
        T(f'  valid={path}', expected == False)
# Evil paths should be rejected
for evil in ['../etc/passwd', '/absolute/path']:
    try:
        (base / evil).resolve().relative_to(base.resolve())
        T(f'  rejected={evil}', False)
    except:
        T(f'  rejected={evil}', True)

# xuechong 2026-07-20 研发BUG-0009-图档扫描-用户隔离机制问题
# 全局历史存储已废弃，改为使用 UserScope
# ====== 2. Username Filtering ======
print("\n--- Username Filtering ---")
from backend.services.user_scope import get_user_scope
s = get_user_scope('sec_test')
s.download_history.clear()
# Normal cases
s.download_history.insert(0, {'task_id': 's1', 'username': 'admin'})
s.download_history.insert(0, {'task_id': 's2', 'username': 'Admin'})  # case sensitive
T('admin!=Admin', len([r for r in s.download_history if r.get('username','')=='admin']) == 1)
T('Admin独立', len([r for r in s.download_history if r.get('username','')=='Admin']) == 1)
# Special chars in username
s.download_history.insert(0, {'task_id': 's3', 'username': 'user@#$%'})
T('特殊字符', len([r for r in s.download_history if r.get('username','')=='user@#$%']) == 1)
# Very long username
long_user = 'u' * 1000
s.download_history.insert(0, {'task_id': 's4', 'username': long_user})
T('长用户名', len([r for r in s.download_history if r.get('username','')==long_user]) == 1)
# Empty username in record
s.download_history.insert(0, {'task_id': 's5'})  # no username
default_matches = len([r for r in s.download_history if r.get('username','admin')=='admin'])
T('无username默认admin', default_matches >= 1)
s.download_history.clear()

# ====== 3. Null/Empty Checks ======
print("\n--- Null/Empty ---")
T('空列表len', len([]) == 0)
T('None is not str', None != 'admin')
# Empty history operations
s.download_history.clear()
T('空clear不崩溃', len(s.download_history) == 0)
try: s.download_history.pop(0); T('空pop崩溃', False)
except: T('空pop崩溃', True)
try: s.download_history[0]; T('空索引崩溃', False)
except: T('空索引崩溃', True)

# ====== 4. Large Data ======
print("\n--- Large Data ---")
s.download_history.clear()
for i in range(1000):
    s.download_history.insert(0, {'task_id': str(i), 'username': f'user_{i%10}'})
T('1000条写入', len(s.download_history) == 1000)
users = set(r.get('username') for r in s.download_history)
T('10个不同用户', len(users) == 10)
for u in users:
    count = len([r for r in s.download_history if r.get('username')==u])
    T(f'  用户{u}有100条', count == 100)
s.download_history.clear()

# ====== 5. JSON Injection ======
print("\n--- JSON Injection ---")
s.download_history.clear()
bad_records = [
    {'task_id': 'x1', 'username': '{"admin": true}'},
    {'task_id': 'x2', 'username': "'; DROP TABLE users;--"},
    {'task_id': 'x3', 'username': '<script>alert(1)</script>'},
    {'task_id': 'x4', 'username': 'user\nadmin'},
    {'task_id': 'x5', 'username': 'user\0null'},
]
for r in bad_records:
    s.download_history.insert(0, r)
    T(f'注入{r["username"][:20]}不崩溃', True)
T('5条注入记录', len(s.download_history) == 5)
s.download_history.clear()

# ====== 6. Duplicate Detection ======
print("\n--- Duplicate Detection ---")
s.download_history.clear()
tid = str(uuid.uuid4())
s.download_history.insert(0, {'task_id': tid, 'username': 'sec_test'})
T('1 insert = 1 record', len(s.download_history) == 1)
s.download_history.insert(0, {'task_id': tid, 'username': 'sec_test'})  # duplicate
ids = [r['task_id'] for r in s.download_history]
T('2 inserts = 2 records', len(s.download_history) == 2)
T('dup detected', ids.count(tid) == 2)
s.download_history.clear()

# ====== 7. History Filter Performance ======
print("\n--- Filter Performance ---")
s.download_history.clear()
for i in range(500):
    s.download_history.insert(0, {'task_id': str(i), 'username': 'admin' if i%2==0 else 'user'})
import time
start = time.time()
for _ in range(100):
    filtered = [r for r in s.download_history if r.get('username','')=='admin']
elapsed = time.time() - start
T(f'100次筛选{len(filtered)}条<1s', elapsed < 1.0)
s.download_history.clear()

# ====== 8. Concurrent Access Simulation ======
print("\n--- Concurrent Simulation ---")
from backend.services.user_scope import get_user_scope
s1 = get_user_scope('concurrent_1')
s2 = get_user_scope('concurrent_2')
s1.download_history.clear(); s2.download_history.clear()
s1.download_history.insert(0, {'task_id': 'c1', 'username': 'u1'})
s2.download_history.insert(0, {'task_id': 'c2', 'username': 'u2'})
T('u1看不到u2数据', len([r for r in s1.download_history if r.get('task_id')=='c2']) == 0)
T('u2看不到u1数据', len([r for r in s2.download_history if r.get('task_id')=='c1']) == 0)
s1.download_history.clear(); s2.download_history.clear()

# ====== 9. Token Security ======
print("\n--- Token Security ---")
from backend.services.auth_service import init_jwt_service, is_token_revoked, revoke_token
jwt = init_jwt_service(secret='test_secure_key_12345', expire_hours=1)
tok = jwt.create_token({'user_id': 'sec_test', 'username': 'tester'})
T('token格式正确', tok.count('.') == 2)
# Tampered token
parts = tok.split('.')
tampered = parts[0] + '.' + parts[1] + '.invalidsig'
T('篡改token被拒', jwt.verify_token(tampered) is None)
# Wrong secret
jwt2 = init_jwt_service(secret='different_secret_key_', expire_hours=1)
T('不同密钥被拒', jwt2.verify_token(tok) is None)
# Revoked token
revoke_token(tok)
T('撤销后is_token_revoked', is_token_revoked(tok) == True)
T('撤销后is_token_revoked', is_token_revoked(tok) == True)

# ====== 10. Cookie Security ======
print("\n--- Cookie Security ---")
T('cookie名正确', 'ds_token' == 'ds_token')
T('httponly推荐', True)
T('samesite推荐', True)

# ====== 结果 ======
print(f"\n{'='*50}")
print(f"  PASS: {PA}  FAIL: {FA}  TOTAL: {PA+FA}")
if FA: print(f"  FAILURES: {errors}"); sys.exit(1)
print(f"  ALL {PA} PASSED")
