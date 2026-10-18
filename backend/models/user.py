# -*- coding: utf-8 -*-
# xuechong 2026-06-01 用户模型与 JSON 文件存储
"""用户模型 — 用户注册、登录验证、JSON 文件持久化"""
import hashlib
import json
import os as _os_module
import re
import secrets
from pathlib import Path
from typing import Optional, List, Dict

from backend.services.logging_service import log_info


# xuechong 2026-07-18 PBKDF2 配置（内置实现，无需第三方库）
_PBKDF2_ITERATIONS = 100000
_PBKDF2_HASH_FUNC = 'sha256'
_SALT_LENGTH = 32

# xuechong 2026-07-18 用户名校验规则
_USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{2,32}$')
_RESERVED_NAMES = {'logs', 'config', 'users', 'tmp', 'data', '_deleted'}


def validate_username(username: str) -> tuple[bool, str]:
    """校验用户名合法性，返回 (是否合法, 错误信息)"""
    if not username:
        return False, "用户名不能为空"
    if not _USERNAME_PATTERN.match(username):
        return False, "用户名只能包含字母、数字、下划线、连字符，长度2-32"
    if username.lower() in _RESERVED_NAMES:
        return False, f"'{username}' 是系统保留名"
    return True, ""


def hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 对密码加盐哈希"""
    salt = secrets.token_hex(_SALT_LENGTH)
    dk = hashlib.pbkdf2_hmac(
        _PBKDF2_HASH_FUNC,
        password.encode('utf-8'),
        salt.encode('utf-8'),
        _PBKDF2_ITERATIONS
    )
    # 格式: iterations$salt$hex_hash
    return f"{_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """验证密码是否匹配存储的哈希值（兼容 PBKDF2 和旧版 SHA-256 两种格式）"""
    try:
        # xuechong 2026-07-21 兼容旧版 SHA-256 纯哈希格式（64位十六进制，无 $ 分隔符）
        if len(hashed) == 64 and '$' not in hashed:
            return secrets.compare_digest(password, hashed)
        # 标准 PBKDF2 格式: iterations$salt$hex_hash
        parts = hashed.split('$', 2)
        if len(parts) != 3:
            return False
        iterations, salt, stored_hash = int(parts[0]), parts[1], parts[2]
        dk = hashlib.pbkdf2_hmac(
            _PBKDF2_HASH_FUNC,
            password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
        return secrets.compare_digest(dk.hex(), stored_hash)
    except (ValueError, TypeError, IndexError):
        return False


class UserManager:
    """用户管理器 — JSON 文件存储的轻量用户系统"""

    def __init__(self, users_file: Path):
        # xuechong 2026-06-01 确保始终是 Path 对象
        self._users_file = Path(users_file) if not isinstance(users_file, Path) else users_file
        self._users: Dict[str, dict] = {}
        self._lock = __import__('threading').Lock()

    # xuechong 2026-06-01 从 JSON 文件加载用户数据
    def load(self) -> None:
        if self._users_file.exists():
            try:
                with open(self._users_file, 'r', encoding='utf-8') as f:
                    self._users = json.load(f)
                log_info(f"[用户管理] 已加载 {len(self._users)} 个用户")
                # xuechong 2026-06-01 迁移旧格式密码（SHA-256 纯哈希 → PBKDF2 加盐）
                self._migrate_passwords()
            except Exception as e:
                log_info(f"[用户管理] 加载用户文件失败: {e}")
                self._users = {}
        else:
            log_info(f"[用户管理] 用户文件不存在: {self._users_file}")
            self._users = {}

    # xuechong 2026-06-01 保存用户数据到 JSON 文件
    def save(self) -> None:
        try:
            self._users_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._users_file, 'w', encoding='utf-8') as f:
                json.dump(self._users, f, ensure_ascii=False, indent=2)
                f.flush()
                _os_module.fsync(f.fileno())
        except Exception as e:
            log_info(f"[用户管理] 保存用户文件失败: {e}")

    # xuechong 2026-06-01 创建新用户
    def create_user(self, username: str, password: str, display_name: str = "",
                    role: str = "user") -> Optional[dict]:
        # xuechong 2026-07-18 用户名校验
        valid, err_msg = validate_username(username)
        if not valid:
            log_info(f"[用户管理] 用户名校验失败: {err_msg}")
            return None

        with self._lock:
            if username in self._users:
                return None  # 用户名已存在

            from datetime import datetime
            import uuid

            user = {
                "user_id": str(uuid.uuid4()),
                "username": username,
                "password_hash": hash_password(password),
                "display_name": display_name or username,
                "role": role,
                "created_at": datetime.now().isoformat(),
                "last_login": None
            }
            self._users[username] = user
            self.save()
            log_info(f"[用户管理] 已创建用户: {username} (role={role})")
            return user

    # xuechong 2026-06-01 验证用户登录
    def authenticate(self, username: str, password: str) -> Optional[dict]:
        with self._lock:
            user = self._users.get(username)
            if not user:
                return None

            if not verify_password(password, user.get("password_hash", "")):
                return None

            # xuechong 2026-07-21 透明升级：旧版 SHA-256 格式登录成功后自动迁移为 PBKDF2
            pwd_hash = user.get("password_hash", "")
            if len(pwd_hash) == 64 and '$' not in pwd_hash:
                user["password_hash"] = hash_password(password)
                user.pop("_password_reset", None)
                log_info(f"[用户管理] 用户 {username} 密码格式已透明升级为 PBKDF2")

            # 更新最后登录时间
            from datetime import datetime
            user["last_login"] = datetime.now().isoformat()
            self.save()
            return user

    # xuechong 2026-06-01 根据用户名获取用户
    def get_user(self, username: str) -> Optional[dict]:
        return self._users.get(username)

    # xuechong 2026-06-01 根据 user_id 获取用户
    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        for user in self._users.values():
            if user.get("user_id") == user_id:
                return user
        return None

    # xuechong 2026-06-01 获取所有用户列表（不含密码哈希）
    def list_users(self) -> List[dict]:
        result = []
        for user in self._users.values():
            item = {k: v for k, v in user.items() if k != "password_hash"}
            result.append(item)
        return result

    # xuechong 2026-06-01 删除用户
    def delete_user(self, username: str) -> bool:
        with self._lock:
            if username not in self._users:
                return False
            user = self._users.pop(username)
            self.save()
            log_info(f"[用户管理] 已删除用户: {username} (user_id={user.get('user_id')})")
            return True

    # xuechong 2026-06-01 修改用户密码
    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        with self._lock:
            user = self._users.get(username)
            if not user:
                return False
            if not verify_password(old_password, user.get("password_hash", "")):
                return False
            user["password_hash"] = hash_password(new_password)
            self.save()
            log_info(f"[用户管理] 用户 {username} 已修改密码")
            return True

    # xuechong 2026-06-01 判断是否首次使用（无任何用户）
    @property
    def is_first_run(self) -> bool:
        return len(self._users) == 0

    # xuechong 2026-06-01 迁移旧 SHA-256 格式密码到 PBKDF2
    def _migrate_passwords(self) -> None:
        """检测旧 SHA-256 纯哈希密码，标记待升级（登录时透明迁移，不重置密码）"""
        # xuechong 2026-07-21 不再暴力重置密码，verify_password 已兼容旧格式
        # 旧格式用户下次登录时 authenticate() 会自动透明升级为 PBKDF2
        legacy_count = sum(
            1 for u in self._users.values()
            if len(u.get("password_hash", "")) == 64 and '$' not in u.get("password_hash", "")
        )
        if legacy_count:
            log_info(f"[用户管理] 检测到 {legacy_count} 个旧格式密码，将在用户登录时透明升级")

    @property
    def user_count(self) -> int:
        return len(self._users)
