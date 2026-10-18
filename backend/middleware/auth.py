# -*- coding: utf-8 -*-
# xuechong 2026-06-01 JWT 认证中间件
"""FastAPI 中间件 — Cookie 优先，其次 Authorization header"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.services.auth_service import get_jwt_service, is_token_revoked
from backend.services.logging_service import log_info

TOKEN_COOKIE = "ds_token"

_PUBLIC_PATHS = {
    '/api/auth/login', '/api/auth/register', '/api/auth/verify', '/api/auth/refresh',
    '/api/health', '/api', '/api/system/version', '/', '/index.html', '/favicon.ico',
    # zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
    # 免鉴权精确路径：要抓的 401 死循环场景下带无效凭证的请求到不了业务层，诊断上报通道必须放行
    '/api/upload-diagnostic',
}
_PUBLIC_PREFIXES = ('/assets/', '/ws/')


class AuthMiddleware(BaseHTTPMiddleware):

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # xuechong 2026-07-21 研发BUG-0009 仅拦截 /api/ 路径；
        # 前端路由（/login、/img-to-pdf 等）与静态资源直接放行，认证由 SPA 路由守卫 + API 401 兜底
        if not path.startswith('/api/'):
            return await call_next(request)
        if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        # xuechong 2026-09-30 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
        # 嵌入模式免登录直通（演示环境口径：嵌入=form-in页签iframe内，入口由form-in控制，
        # 免登录且直接拥有管理员最高权限）：请求头 X-Embed-Mode: 1（前端axios请求统一附加）
        # 或 URL embed=1 参数（预览/下载等浏览器直链）时按嵌入管理员（admin，与form-in
        # scanner.api.username 配置一致、共用同一用户数据目录）放行，不校验token——
        # 彻底消除"页面残留过期登录态/ token过期"场景下嵌入页接口401"未登录"的问题
        if request.headers.get('X-Embed-Mode', '') == '1' or request.query_params.get('embed', '') == '1':
            request.state.user_id = 'admin'
            request.state.username = 'admin'
            request.state.role = 'admin'
            return await call_next(request)

        # xuechong 2026-06-27 cookie 优先，header 兜底
        token = request.cookies.get(TOKEN_COOKIE)
        if not token:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
        # xuechong 2026-09-28 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
        # 第三兜底：URL query 参数 token——嵌入模式（form-in页签iframe嵌本系统，跨域第三方
        # 上下文种cookie被浏览器拦、浏览器直链请求又带不上Authorization头）由前端在
        # 预览/下载等直链URL上拼token；query token 走与 cookie/header 完全相同的校验链
        # （签名/过期/撤销逐项校验，无效即401），普通直连模式URL不带token参数行为不变
        if not token:
            token = request.query_params.get('token', '')

        # zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
        # 401 拒绝分支补运行日志（此前零痕迹）：token 来源（cookie/header/query）+ 具体原因，
        # "签名无效"即服务重启密钥轮换的信号——本次上传整体中止事故排查的关键证据
        _token_from = 'cookie' if request.cookies.get(TOKEN_COOKIE) else ('header' if request.headers.get('Authorization') else 'query')

        if not token:
            log_info(f"[认证拦截] {path} token来源=无 原因=未携带token")
            return JSONResponse(status_code=401, content={"detail": "未登录", "code": "UNAUTHORIZED"})

        if is_token_revoked(token):
            log_info(f"[认证拦截] {path} token来源={_token_from} 原因=token已被撤销")
            return JSONResponse(status_code=401, content={"detail": "登录已撤销", "code": "TOKEN_REVOKED"})

        jwt_svc = get_jwt_service()
        payload, _reject_reason = jwt_svc.verify_token_ex(token)
        if not payload:
            log_info(f"[认证拦截] {path} token来源={_token_from} 原因={_reject_reason}")
            return JSONResponse(status_code=401, content={"detail": "登录已过期", "code": "UNAUTHORIZED"})

        request.state.user_id = payload.get('user_id')
        request.state.username = payload.get('username', 'unknown')
        # xuechong 2026-07-21 研发BUG-0009 提取角色信息供管理员端点校验
        request.state.role = payload.get('role', 'user')
        return await call_next(request)
