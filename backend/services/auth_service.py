# -*- coding: utf-8 -*-
# xuechong 2026-06-01 JWT 认证服务（内置实现，无第三方依赖）
"""JWT 令牌签发、验证、刷新 — 基于内置 hmac + hashlib + base64"""
import base64
import hashlib
import hmac as _hmac
import json
import secrets
import time
from typing import Optional, Dict, Any, Tuple

from backend.services.logging_service import log_info


# xuechong 2026-06-01 JWT 默认配置
_DEFAULT_EXPIRE_HOURS = 24
_JWT_ALGORITHM = 'HS256'


def _base64url_encode(data: bytes) -> str:
    """Base64 URL-safe 编码（无填充）"""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _base64url_decode(s: str) -> bytes:
    """Base64 URL-safe 解码（自动补填充）"""
    s += '=' * (4 - len(s) % 4) if len(s) % 4 else ''
    return base64.urlsafe_b64decode(s)


class JWTService:
    """JWT 令牌签发和验证服务"""

    def __init__(self, secret: str = None, expire_hours: int = _DEFAULT_EXPIRE_HOURS):
        # xuechong 2026-06-01 如果没有提供 secret，自动生成随机密钥
        if secret is None:
            secret = secrets.token_hex(32)
            log_info(f"[JWT] 自动生成随机密钥 (长度={len(secret)}字符)")
        self._secret = secret.encode('utf-8') if isinstance(secret, str) else secret
        self._expire_hours = expire_hours

    # xuechong 2026-06-01 签发 JWT 令牌
    def create_token(self, payload: Dict[str, Any], expire_hours: int = None) -> str:
        """签发 JWT 令牌，包含过期时间"""
        if expire_hours is None:
            expire_hours = self._expire_hours

        header = {"alg": _JWT_ALGORITHM, "typ": "JWT"}
        now = int(time.time())
        token_payload = {
            **payload,
            "iat": now,
            "exp": now + expire_hours * 3600
        }

        # 编码 header 和 payload
        header_b64 = _base64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
        payload_b64 = _base64url_encode(json.dumps(token_payload, separators=(',', ':')).encode('utf-8'))

        # 签名
        signing_input = f"{header_b64}.{payload_b64}"
        signature = _hmac.new(self._secret, signing_input.encode('utf-8'), hashlib.sha256).digest()
        signature_b64 = _base64url_encode(signature)

        return f"{signing_input}.{signature_b64}"

    # xuechong 2026-06-01 验证 JWT 令牌
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证 JWT 令牌，返回 payload 或 None"""
        # zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
        # 保持原签名与返回值不变（内部委托 verify_token_ex），refresh/剩余时长等既有调用方零影响
        payload, _reject_reason = self.verify_token_ex(token)
        return payload

    # zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
    # 新增带拒绝原因的令牌校验：区分"签名无效"（服务重启密钥轮换的信号，本次上传整体中止
    # 事故的关键判据）与"已过期"（正常超时），供鉴权中间件 401 时写入运行日志补齐零痕迹盲区
    def verify_token_ex(self, token: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """验证 JWT 令牌，返回 (payload, 拒绝原因)；有效时 reason 为 None"""
        # 处理 None/非字符串输入
        if not token or not isinstance(token, str):
            return None, "格式非法"
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None, "格式非法"

            header_b64, payload_b64, signature_b64 = parts

            # 验证签名
            signing_input = f"{header_b64}.{payload_b64}"
            expected_sig = _hmac.new(self._secret, signing_input.encode('utf-8'), hashlib.sha256).digest()
            expected_sig_b64 = _base64url_encode(expected_sig)

            if not secrets.compare_digest(signature_b64, expected_sig_b64):
                return None, "签名无效"

            # 解码 payload
            payload_bytes = _base64url_decode(payload_b64)
            payload = json.loads(payload_bytes.decode('utf-8'))

            # 检查过期时间
            exp = payload.get("exp", 0)
            if exp < time.time():
                return None, "已过期"

            return payload, None

        except Exception as e:
            log_info(f"[JWT] 令牌验证异常: {e}")
            return None, "验证异常"

    # xuechong 2026-06-02 刷新令牌（允许 1 小时过期宽限期）
    def refresh_token(self, token: str) -> Optional[str]:
        """验证令牌并签发新令牌（过期 1 小时内仍可刷新）"""
        payload = self.verify_token(token)
        if not payload:
            # xuechong 2026-06-02 过期宽限期：手动解码检查，允许过期 1 小时内刷新
            payload = self._verify_token_with_grace(token, grace_seconds=3600)
        if not payload:
            return None

        for key in ("iat", "exp"):
            payload.pop(key, None)

        return self.create_token(payload)

    # xuechong 2026-06-02 带宽限期的 token 验证（用于刷新）
    def _verify_token_with_grace(self, token: str, grace_seconds: int = 3600) -> Optional[Dict[str, Any]]:
        """验证 token 签名但不检查过期（允许 grace_seconds 秒宽限期）"""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            header_b64, payload_b64, signature_b64 = parts
            signing_input = f"{header_b64}.{payload_b64}"
            expected_sig = _hmac.new(self._secret, signing_input.encode('utf-8'), hashlib.sha256).digest()
            expected_sig_b64 = _base64url_encode(expected_sig)
            if not secrets.compare_digest(signature_b64, expected_sig_b64):
                return None
            payload_bytes = _base64url_decode(payload_b64)
            payload = json.loads(payload_bytes.decode('utf-8'))
            # 允许 grace_seconds 宽限期
            exp = payload.get("exp", 0)
            if exp + grace_seconds < time.time():
                return None
            return payload
        except Exception:
            return None

    # xuechong 2026-06-01 获取令牌剩余有效时间（秒）
    def token_remaining_seconds(self, token: str) -> int:
        """返回令牌剩余有效秒数，无效返回 0"""
        payload = self.verify_token(token)
        if not payload:
            return 0
        return max(0, payload.get("exp", 0) - int(time.time()))


# xuechong 2026-06-02 Token 黑名单（用于强制下线/修改密码后撤销旧token）
# 存储格式: {token_hash: revoked_timestamp}
import threading as _threading_blacklist
import time as _time_blacklist
_revoked_tokens: dict[str, float] = {}
_revoked_lock = _threading_blacklist.Lock()
# xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败
# 黑名单条目保留时长与 JWT 有效期保持一致（1 年）：token 寿命放到 1 年后，被撤销的 token
# 也必须在黑名单里留满 1 年，否则 24 小时后条目被清理掉，撤销的 token 会复活继续可用
_TOKEN_MAX_AGE_SECONDS = 365 * 24 * 3600


def _cleanup_expired() -> None:
    """清理过期的黑名单条目（超过 24 小时的 token 已自然过期）"""
    now = _time_blacklist.time()
    cutoff = now - _TOKEN_MAX_AGE_SECONDS
    with _revoked_lock:
        expired = [k for k, v in _revoked_tokens.items() if v < cutoff]
        for k in expired:
            del _revoked_tokens[k]
        if expired:
            log_info(f"[JWT] 黑名单清理: 移除 {len(expired)} 条过期记录, 剩余 {len(_revoked_tokens)} 条")


def revoke_token(token: str) -> None:
    """将 token 加入黑名单（修改密码/管理员踢人时调用）"""
    short = token[:80] if len(token) > 80 else token
    with _revoked_lock:
        _revoked_tokens[short] = _time_blacklist.time()
        # 每次新增时顺便清理过期项
        if len(_revoked_tokens) % 10 == 0:
            _cleanup_expired()
    log_info(f"[JWT] token 已被撤销")


def is_token_revoked(token: str) -> bool:
    """检查 token 是否在黑名单中"""
    short = token[:80] if len(token) > 80 else token
    with _revoked_lock:
        return short in _revoked_tokens


def revoke_all_user_tokens(username: str) -> int:
    """撤销某用户的所有 token（修改密码后调用）

    当前实现：由于 token 是无状态的，无法按用户名精确撤销。
    实际做法：修改密码后，用户下次登录使用新 token，旧 token 仍有效直到过期。
    如有强制下线需求，需配合 JWT 版本号机制。
    """
    log_info(f"[JWT] 用户 {username} 密码已修改，旧 token 将在过期后失效")
    return 0


# xuechong 2026-06-01 全局 JWT 服务实例（app.py 初始化时设置 secret）
_jwt_service: Optional[JWTService] = None


def get_jwt_service() -> JWTService:
    """获取全局 JWT 服务实例"""
    global _jwt_service
    if _jwt_service is None:
        _jwt_service = JWTService()
    return _jwt_service


def init_jwt_service(secret: str = None, expire_hours: int = _DEFAULT_EXPIRE_HOURS) -> JWTService:
    """初始化全局 JWT 服务"""
    global _jwt_service
    _jwt_service = JWTService(secret=secret, expire_hours=expire_hours)
    return _jwt_service
