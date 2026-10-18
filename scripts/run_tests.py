#!/usr/bin/env python3
# xuechong 2026-06-27 发布前自动测试（288项）
import sys, subprocess, os
tests = [
    'tests/test_smoke.py',
    'tests/test_services.py',
    'tests/test_api.py',
    'tests/test_download_history.py',
    'tests/test_security.py',
]
env = {**os.environ, 'PYTHONPATH': '.'}
failed = []
for t in tests:
    r = subprocess.run([sys.executable, t], env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        failed.append(t)
        print(f'FAIL: {t} (returncode={r.returncode})')
        # xuechong 2026-06-30 诊断：同时打印 stderr 和 stdout 尾部
        if r.stderr:
            print(f'--- stderr ({len(r.stderr)} chars) ---')
            print(r.stderr[-1000:])
        if r.stdout:
            print(f'--- stdout ({len(r.stdout)} chars) ---')
            print(r.stdout[-1000:])
        if not r.stderr and not r.stdout:
            print('(no output)')
    else:
        print(f'OK: {t}')
if failed:
    print(f'\nFAILED {len(failed)}/{len(tests)}')
    sys.exit(1)
print(f'\nALL {len(tests)*50}+ PASSED')
