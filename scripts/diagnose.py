"""下载历史诊断 - 在项目目录下运行: python diagnose.py"""
from backend.services.app_state import state
from backend.services.user_scope import get_user_scope
import json

print("1. scope共享state:", get_user_scope('_default_admin').download_history is state.download_history)
print("2. state记录数:", len(state.download_history))
print("3. scope记录数:", len(get_user_scope('_default_admin').download_history))
for i, r in enumerate(state.download_history[:5]):
    print(f"   [{i}] {r.get('folder_name','?')} | {r.get('created_at','?')} | task={r.get('task_id','?')[:16]}")

# 检查文件
from pathlib import Path
gf = Path(str(state.DOWNLOAD_HISTORY_FILE)) if state.DOWNLOAD_HISTORY_FILE else None
if gf and gf.exists():
    with open(gf) as f: gd = json.load(f)
    print(f"4. 文件记录数: {len(gd)} (路径: {gf})")
else:
    print(f"4. 文件不存在: {gf}")
