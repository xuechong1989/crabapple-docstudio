# -*- coding: utf-8 -*-
# xuechong 2026-06-01 数据迁移脚本 — 将现有全局数据迁移到多用户系统
"""
将 V3.0.00 及之前版本的全局数据迁移为按用户隔离的多用户格式。

使用方式:
    python scripts/migrate_to_multi_user.py [--dry-run] [--admin-user admin]

迁移内容:
    1. upload_tasks 内存字典 → 不做迁移（重启后自然清空）
    2. download_history.json → history/admin/download_history.json
    3. edit_pdf_history.json → history/admin/edit_pdf_history.json
    4. dual_layer_history.json → history/admin/dual_layer_history.json
    5. upload_history.json → history/admin/upload_history.json
    6. tmp/uploads/{task_id}/ → tmp/uploads/admin/{task_id}/
    7. tmp/outputs/{task_id}/ → tmp/outputs/admin/{task_id}/
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# xuechong 2026-06-01 添加项目根目录到 Python 路径
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_json(filepath: Path):
    """安全加载 JSON 文件"""
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_json(filepath: Path, data):
    """安全保存 JSON 文件"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def migrate(admin_user: str = "admin", dry_run: bool = False):
    """执行数据迁移"""
    print("=" * 60)
    print("  crabapple-docstudio 数据迁移工具")
    print(f"  目标用户: {admin_user}")
    print(f"  模式: {'试运行（不修改文件）' if dry_run else '正式迁移'}")
    print("=" * 60)

    # 读取 url.conf 获取存储根目录
    url_conf_path = PROJECT_ROOT / "url.conf"
    storage_root = None

    if url_conf_path.exists():
        with open(url_conf_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('DOCSTUDIO_STORAGE_ROOT=') or \
                   line.startswith('DOCSTUDIO_STORAGE_ROOT_WIN='):
                    val = line.split('=', 1)[1].strip().strip('"').strip("'")
                    storage_root = Path(val)
                    break

    if not storage_root:
        # 回退到项目根目录下的 data 目录
        storage_root = PROJECT_ROOT / "data"
        print(f"  [警告] 未找到 url.conf 中的存储路径，使用回退路径: {storage_root}")

    print(f"  存储根目录: {storage_root}")

    if not storage_root.exists():
        print(f"  [错误] 存储根目录不存在: {storage_root}")
        return False

    # xuechong 2026-06-01 迁移历史文件
    history_files = {
        "download_history.json": "download_history.json",
        "edit_pdf_history.json": "edit_pdf_history.json",
        "upload_history.json": "upload_history.json",
    }

    history_target_dir = storage_root / "history" / admin_user

    for src_name, dst_name in history_files.items():
        src_path = storage_root / src_name
        if not src_path.exists():
            print(f"  [跳过] {src_name} — 文件不存在")
            continue

        dst_path = history_target_dir / dst_name
        data = load_json(src_path)
        if data:
            print(f"  [迁移] {src_name} → history/{admin_user}/{dst_name} ({len(data) if isinstance(data, list) else 'object'})")
            if not dry_run:
                save_json(dst_path, data)

    # xuechong 2026-06-01 迁移双层 PDF 历史
    dual_layer_src = storage_root / "dual_layer" / "dual_layer_history.json"
    if dual_layer_src.exists():
        dst_path = history_target_dir / "dual_layer_history.json"
        data = load_json(dual_layer_src)
        if data:
            print(f"  [迁移] dual_layer/dual_layer_history.json → history/{admin_user}/dual_layer_history.json")
            if not dry_run:
                save_json(dst_path, data)

    # xuechong 2026-06-01 迁移上传和输出目录
    for subdir in ["tmp/uploads", "tmp/outputs"]:
        src_dir = storage_root / subdir
        if not src_dir.exists():
            continue

        dst_dir = storage_root / subdir / admin_user
        task_dirs = [d for d in src_dir.iterdir() if d.is_dir() and d.name != admin_user]
        if task_dirs:
            print(f"  [迁移] {subdir}/ — {len(task_dirs)} 个任务目录 → {subdir}/{admin_user}/")
            if not dry_run:
                dst_dir.mkdir(parents=True, exist_ok=True)
                for task_dir in task_dirs:
                    target = dst_dir / task_dir.name
                    if not target.exists():
                        shutil.move(str(task_dir), str(target))

    # xuechong 2026-06-01 创建默认管理员用户
    users_file = storage_root / "users.json"
    existing_users = load_json(users_file) or {}

    if admin_user not in existing_users:
        print(f"  [创建] 默认管理员账户: {admin_user}")
        if not dry_run:
            from backend.models.user import hash_password
            import uuid
            from datetime import datetime

            existing_users[admin_user] = {
                "user_id": str(uuid.uuid4()),
                "username": admin_user,
                "password_hash": hash_password("admin123"),
                "display_name": "管理员",
                "role": "admin",
                "created_at": datetime.now().isoformat(),
                "last_login": None
            }
            save_json(users_file, existing_users)
            print(f"  [提示] 默认密码: admin123，请登录后立即修改")
    else:
        print(f"  [跳过] 用户 {admin_user} 已存在")

    print("=" * 60)
    if dry_run:
        print("  试运行完成。使用 --no-dry-run 执行正式迁移。")
    else:
        print("  迁移完成！")
    print("=" * 60)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="crabapple-docstudio 数据迁移工具")
    parser.add_argument("--dry-run", action="store_true", help="试运行模式，不修改文件")
    parser.add_argument("--admin-user", default="admin", help="管理员用户名（默认: admin）")
    parser.add_argument("--no-dry-run", action="store_true", help="执行正式迁移")
    args = parser.parse_args()

    dry_run = args.dry_run and not args.no_dry_run
    success = migrate(admin_user=args.admin_user, dry_run=dry_run)
    sys.exit(0 if success else 1)
