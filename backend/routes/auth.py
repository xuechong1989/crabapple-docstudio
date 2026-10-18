# -*- coding: utf-8 -*-
# xuechong 2026-06-01 用户认证 API（登录/注册/个人信息 + 兼容旧版口令验证）
"""登录验证 + 用户注册 + JWT 令牌签发"""
import hashlib
import hmac as _hmac
import os as _os
import secrets
import time as _time
import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional

from backend.services.logging_service import log_info
from backend.services.app_state import state
from backend.services.auth_service import get_jwt_service

router = APIRouter(tags=["auth"])


def _compute_password_hash(text: str, rounds: int = 100000) -> str:
    """计算多轮 SHA-256 哈希（兼容旧版前端密码哈希）"""
    hash_val = text.encode('utf-8')
    for _ in range(rounds):
        hash_val = hashlib.sha256(hash_val).digest()
    return hash_val.hex()


# 旧版兼容口令的 SHA-256 哈希值；开源版不提供默认口令，必须由部署方自行配置。
# 生成方式见 scripts/hash_password.py，配置到环境变量 DOCSTUDIO_AUTH_HASH。
CORRECT_PASSWORD_HASH = _os.environ.get('DOCSTUDIO_AUTH_HASH', '')

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_login_lock = threading.Lock()
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 60
_LOGIN_BLOCK_SECONDS = 10


def _check_login_rate(ip: str) -> bool:
    """检查登录速率，返回 True 表示允许尝试"""
    with _login_lock:
        now = _time.time()
        if ip not in _LOGIN_ATTEMPTS:
            _LOGIN_ATTEMPTS[ip] = []
        cutoff = now - _LOGIN_WINDOW_SECONDS
        _LOGIN_ATTEMPTS[ip] = [t for t in _LOGIN_ATTEMPTS[ip] if t > cutoff]
        if len(_LOGIN_ATTEMPTS[ip]) >= _LOGIN_MAX_ATTEMPTS:
            oldest = min(_LOGIN_ATTEMPTS[ip]) if _LOGIN_ATTEMPTS[ip] else now
            if now - oldest < _LOGIN_BLOCK_SECONDS:
                return False
            _LOGIN_ATTEMPTS[ip] = []
        _LOGIN_ATTEMPTS[ip].append(now)
        return True


# ---- Pydantic 模型 ----

class LoginRequest(BaseModel):
    password: str  # 前端已做 SHA-256 多轮哈希


# xuechong 2026-06-01 新用户登录请求
class UserLoginRequest(BaseModel):
    username: str
    password: str  # 前端已做 SHA-256 哈希的密码


# xuechong 2026-06-01 用户注册请求
class UserRegisterRequest(BaseModel):
    username: str
    password: str  # 前端已做 SHA-256 哈希的密码
    display_name: Optional[str] = None
    role: Optional[str] = "user"  # xuechong 2026-06-02 角色（仅管理员可设为admin）


# xuechong 2026-06-01 修改密码请求
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ---- 旧版兼容端点 ----

@router.post("/api/auth/verify")
async def verify_login(request: LoginRequest, req: Request, response: Response):
    """验证登录口令（兼容旧版，带速率限制）"""
    client_ip = req.client.host if req.client else "unknown"

    if not CORRECT_PASSWORD_HASH:
        raise HTTPException(
            status_code=503,
            detail="未配置 DOCSTUDIO_AUTH_HASH，请先运行 scripts/hash_password.py 生成口令哈希并写入环境变量",
        )

    if not _check_login_rate(client_ip):
        log_info(f"[登录验证] 速率限制触发 - IP: {client_ip}")
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请10秒后再试")

    log_info(f"[登录验证] 收到验证请求")

    if _hmac.compare_digest(request.password, CORRECT_PASSWORD_HASH):
        log_info(f"[登录验证] 验证成功")
        with _login_lock:
            _LOGIN_ATTEMPTS.pop(client_ip, None)

        # xuechong 2026-06-02 兼容模式：验证成功后始终尝试颁发 JWT token
        try:
            user_mgr = _get_user_manager()
            if user_mgr.is_first_run:
                _create_default_admin(user_mgr)
            jwt_svc = get_jwt_service()
            admin_user = user_mgr.get_user("admin")
            if admin_user:
                token = jwt_svc.create_token({
                    "user_id": admin_user["user_id"],
                    "username": admin_user["username"],
                    "role": admin_user.get("role", "admin")
                })
                # xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
                # cookie 寿命 7 天改为 1 年，与 token 有效期对齐：原来 7 天 cookie 装着 24 小时 token，
                # 过期后浏览器还一直自动带死 token，是"上传时集中 401"的帮凶
                response.set_cookie(key="ds_token", value=token, httponly=True, samesite="lax", max_age=86400*365)
                return {
                    "success": True, "message": "登录成功",
                    "token": token,
                    "user": {
                        "user_id": admin_user["user_id"],
                        "username": admin_user["username"],
                        "display_name": admin_user.get("display_name", "管理员"),
                        "role": admin_user.get("role", "admin")
                    }
                }
        except Exception as e:
            # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
            # JWT 签发失败不再返回假成功：原实现返回 success:true 但无 token/cookie，
            # 用户"登录成功"后所有后续操作 401。改为明确失败+原因+恢复方式
            log_info(f"[登录验证][错误] JWT 签发异常: {e}")
            return {"success": False, "message": f"登录验证通过，但会话签发失败，请重启服务后重试（原因：{e}）"}
    else:
        log_info(f"[登录验证] 验证失败 - 口令错误")
        return {"success": False, "message": "口令错误"}


# ---- 新版用户认证端点 ----

# xuechong 2026-06-01 获取或初始化用户管理器
def _get_user_manager():
    """懒加载用户管理器"""
    from backend.models.user import UserManager
    if not hasattr(state, '_user_manager'):
        from backend.services.path_service import STORAGE_ROOT
        state._user_manager = UserManager(STORAGE_ROOT / "users.json")
        state._user_manager.load()
    return state._user_manager


# xuechong 2026-06-01 创建默认管理员账户
def _create_default_admin(user_mgr) -> dict:
    """首次运行时创建默认管理员账户"""
    if user_mgr.is_first_run:
        # 优先使用部署方设置的口令；未设置时生成一次性随机口令，仅在首次启动日志中输出
        default_pwd = _os.environ.get("DOCSTUDIO_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        user = user_mgr.create_user(
            username="admin",
            password=_compute_password_hash(default_pwd),
            display_name="管理员",
            role="admin"
        )
        log_info(f"[认证] 首次运行，已创建默认管理员: admin / {default_pwd}")
        log_info(f"[认证] 请登录后立即修改密码")
        # 将默认密码写入 state 供启动日志显示
        state._default_admin_password = default_pwd
        return user
    return user_mgr.get_user("admin")


@router.post("/api/auth/login")
async def user_login(request: UserLoginRequest, req: Request, response: Response):
    """用户登录 — 返回 JWT token"""
    client_ip = req.client.host if req.client else "unknown"

    if not _check_login_rate(client_ip):
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请10秒后再试")

    user_mgr = _get_user_manager()

    # xuechong 2026-06-01 首次运行时自动创建管理员
    if user_mgr.is_first_run:
        _create_default_admin(user_mgr)

    # xuechong 2026-06-01 验证用户（strip 去除首尾空白）
    username = request.username.strip() if request.username else ""
    if not username:
        return {"success": False, "message": "用户名不能为空"}

    user = user_mgr.authenticate(username, request.password)
    if not user:
        log_info(f"[登录] 失败: username={username}")
        return {"success": False, "message": "用户名或密码错误"}

    # 签发 JWT
    jwt_svc = get_jwt_service()
    token = jwt_svc.create_token({
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user.get("role", "user")
    })

    with _login_lock:
        _LOGIN_ATTEMPTS.pop(client_ip, None)

    log_info(f"[登录] 成功: username={username}")
    # xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
    # cookie 寿命 7 天改为 1 年，与 token 有效期对齐（同旧版口令验证接口处说明）
    response.set_cookie(key="ds_token", value=token, httponly=True, samesite="lax", max_age=86400*365)
    return {
        "success": True,
        "message": "登录成功",
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "display_name": user.get("display_name", user["username"]),
            "role": user.get("role", "user")
        }
    }


@router.post("/api/auth/register")
async def user_register(request: UserRegisterRequest, req: Request):
    """注册新用户（仅管理员可创建，或首次运行时开放）"""
    user_mgr = _get_user_manager()

    # xuechong 2026-06-01 首次运行允许直接注册管理员
    if user_mgr.is_first_run:
        _create_default_admin(user_mgr)
        # 如果注册的是 admin，直接返回
        if request.username == "admin":
            return {"success": True, "message": "默认管理员账户已创建"}

    # xuechong 2026-06-01 检查调用者权限（需要真实管理员身份，兼容模式 _default_admin 不允许）
    try:
        caller_user_id = req.state.user_id if hasattr(req.state, 'user_id') else None
    except Exception:
        caller_user_id = None

    # xuechong 2026-06-02 权限检查：有 token 则验证管理员，无 token 允许（兼容模式+CORS保护）
    if caller_user_id and caller_user_id != '_default_admin':
        caller = user_mgr.get_user_by_id(caller_user_id)
        if not caller or caller.get("role") != "admin":
            raise HTTPException(status_code=403, detail="仅管理员可以创建用户")

    # 验证用户名
    if not request.username or not request.username.strip():
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if len(request.username) < 2 or len(request.username) > 32:
        raise HTTPException(status_code=400, detail="用户名长度需在2-32个字符之间")
    if not request.username.replace('_', '').replace('-', '').isalnum():
        raise HTTPException(status_code=400, detail="用户名只能包含字母、数字、下划线和连字符")

    # xuechong 2026-06-02 创建用户（管理员可设置角色为admin）
    role = request.role or "user"
    if role not in ("user", "admin"):
        role = "user"
    # 只有管理员才能创建管理员用户
    if role == "admin":
        caller = user_mgr.get_user_by_id(caller_user_id)
        if not caller or caller.get("role") != "admin":
            role = "user"

    user = user_mgr.create_user(
        username=request.username.strip(),
        password=request.password,
        display_name=request.display_name or request.username.strip(),
        role=role
    )

    if not user:
        raise HTTPException(status_code=409, detail="用户名已存在")

    log_info(f"[注册] 已创建用户: {request.username}")
    return {
        "success": True,
        "message": "用户创建成功",
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "display_name": user.get("display_name", ""),
            "role": user.get("role", "user")
        }
    }


# xuechong 2026-06-02 Token 刷新端点
@router.post("/api/auth/refresh")
async def refresh_token(req: Request, response: Response):
    """刷新即将过期的 JWT token"""
    auth_header = req.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="未提供有效的token")
    token = auth_header[7:]
    jwt_svc = get_jwt_service()
    # 检查是否在黑名单中
    from backend.services.auth_service import is_token_revoked
    if is_token_revoked(token):
        raise HTTPException(status_code=401, detail="token已被撤销")
    new_token = jwt_svc.refresh_token(token)
    if not new_token:
        raise HTTPException(status_code=401, detail="token无效或已过期")
    remaining = jwt_svc.token_remaining_seconds(new_token)
    # xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
    # cookie 寿命 7 天改为 1 年，与 token 有效期对齐（同旧版口令验证接口处说明）
    response.set_cookie(key="ds_token", value=new_token, httponly=True, samesite="lax", max_age=86400*365)
    return {"success": True, "token": new_token, "expires_in": remaining}


@router.post("/api/auth/logout")
async def logout(response: Response):
    """登出 — 清除 cookie"""
    response.delete_cookie(key="ds_token")
    return {"success": True, "message": "已登出"}


@router.get("/api/auth/me")
async def get_current_user(req: Request):
    """获取当前登录用户信息"""
    user_id = getattr(req.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    # xuechong 2026-06-01 兼容模式下的默认管理员
    if user_id == '_default_admin':
        return {
            "user_id": "_default_admin",
            "username": "admin",
            "display_name": "管理员（兼容模式）",
            "role": "admin"
        }

    user_mgr = _get_user_manager()
    user = user_mgr.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "display_name": user.get("display_name", ""),
        "role": user.get("role", "user"),
        "created_at": user.get("created_at", ""),
        "last_login": user.get("last_login", "")
    }


@router.get("/api/auth/users")
async def list_users(req: Request):
    """获取所有用户列表（仅管理员）"""
    user_id = getattr(req.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    user_mgr = _get_user_manager()

    # xuechong 2026-06-02 权限检查：有token验证admin，无token允许（兼容模式）
    if user_id and user_id != '_default_admin':
        caller = user_mgr.get_user_by_id(user_id)
        if not caller or caller.get("role") != "admin":
            raise HTTPException(status_code=403, detail="仅管理员可查看用户列表")

    return {"users": user_mgr.list_users(), "total": user_mgr.user_count}


@router.delete("/api/auth/users/{username}")
async def delete_user(username: str, req: Request):
    """删除用户（仅管理员，不能删除自己）"""
    user_id = getattr(req.state, 'user_id', None)

    user_mgr = _get_user_manager()

    if user_id and user_id != '_default_admin':
        caller = user_mgr.get_user_by_id(user_id)
        if not caller or caller.get("role") != "admin":
            raise HTTPException(status_code=403, detail="仅管理员可删除用户")
        if caller.get("username") == username:
            raise HTTPException(status_code=400, detail="不能删除自己的账户")

    if not user_mgr.delete_user(username):
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"success": True, "message": f"用户 {username} 已删除"}


# xuechong 2026-06-02 管理员重置用户密码
class ResetPasswordRequest(BaseModel):
    new_password: Optional[str] = None  # 不传则自动生成随机密码


@router.post("/api/auth/users/{username}/reset-password")
async def reset_user_password(username: str, body: ResetPasswordRequest, req: Request):
    """管理员重置指定用户的密码"""
    user_id = getattr(req.state, 'user_id', None)
    if not user_id or user_id == '_default_admin':
        raise HTTPException(status_code=403, detail="兼容模式下不支持此操作，请使用管理员账户登录")

    user_mgr = _get_user_manager()
    caller = user_mgr.get_user_by_id(user_id)
    if not caller or caller.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可重置密码")
    if caller.get("username") == username:
        raise HTTPException(status_code=400, detail="请使用修改密码功能来修改自己的密码")

    target = user_mgr.get_user(username)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 生成或使用指定的新密码
    import secrets as _secrets_pwd
    new_pwd = body.new_password if body.new_password else _secrets_pwd.token_hex(6)
    hashed = _compute_password_hash(new_pwd)
    user_mgr._users[username]["password_hash"] = hashed
    user_mgr.save()

    log_info(f"[用户管理] 管理员 {caller['username']} 重置了用户 {username} 的密码")
    return {"success": True, "message": f"用户 {username} 的密码已重置", "new_password": new_pwd}


@router.post("/api/auth/change-password")
async def change_password(request: ChangePasswordRequest, req: Request):
    """修改当前用户密码"""
    user_id = getattr(req.state, 'user_id', None)
    if not user_id or user_id == '_default_admin':
        raise HTTPException(status_code=400, detail="兼容模式下不支持修改密码，请使用用户登录")

    user_mgr = _get_user_manager()
    user = user_mgr.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not user_mgr.change_password(user["username"], request.old_password, request.new_password):
        raise HTTPException(status_code=400, detail="旧密码错误")

    return {"success": True, "message": "密码修改成功"}
