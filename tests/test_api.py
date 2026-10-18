#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xuechong 2026-06-27 后端 API 全面集成测试
覆盖认证、系统、上传/下载历史、编辑PDF、双层PDF等所有API端点。

运行方式：
  PYTHONPATH=. python3 tests/test_api.py
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)

# xuechong 2026-08-07 默认管理员口令固定为 测试口令（SHA-256 100000轮）
_DEFAULT_PWD_HASH = '103e4cce4376cf4c1a32f3c49d8a75dec4674f0b639fa3ebe308b74059d54d92'

_passed = 0
_failed = 0


def _check(condition: bool, msg: str):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS: {msg}")
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


def _login():
    resp = client.post("/api/auth/verify", json={"password": _DEFAULT_PWD_HASH})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    token = data.get("token", "")
    assert token
    return token


def test_system():
    """1) 系统公开端点"""
    print("\n===== 1. 系统公开端点 =====")

    resp = client.get("/api/health")
    _check(resp.status_code == 200, "GET /api/health -> 200")
    j = resp.json()
    _check(j.get("status") == "healthy", "health.status == healthy")
    _check("timestamp" in j, "health.timestamp present")

    resp = client.get("/api")
    _check(resp.status_code == 200, "GET /api -> 200")
    j = resp.json()
    _check("version" in j, "api.version present")
    _check("message" in j, "api.message present")
    # xuechong 2026-07-30 动态读取版本号，避免版本升级后测试硬编码失败
    _check(j["version"] == app.version, f"api.version == {app.version}")


def test_auth():
    """2) 认证端点"""
    print("\n===== 2. 认证端点 =====")

    # 2a. verify 成功
    resp = client.post("/api/auth/verify", json={"password": _DEFAULT_PWD_HASH})
    _check(resp.status_code == 200, "POST /api/auth/verify (ok) -> 200")
    j = resp.json()
    _check(j.get("success") is True, "verify.success == true")
    _check("token" in j, "verify has token")
    _check("user" in j and "username" in j["user"], "verify has user.username")
    _check("ds_token=" in resp.headers.get("set-cookie", ""),
           "verify sets ds_token cookie")

    # 2b. verify 失败
    resp = client.post("/api/auth/verify", json={"password": "bad_hash_12345"})
    _check(resp.status_code == 200, "POST /api/auth/verify (fail) -> 200")
    j = resp.json()
    _check(j.get("success") is False, "verify fail -> success == false")

    # 2c. login
    resp = client.post("/api/auth/login", json={
        "username": "admin", "password": _DEFAULT_PWD_HASH
    })
    _check(resp.status_code == 200, "POST /api/auth/login -> 200")
    j = resp.json()
    # xuechong 2026-08-07 默认管理员密码固定为 测试口令，登录应直接成功
    _check(j.get("success") is True, "login.success == true")
    _check("token" in j, "login has token")
    _check(j.get("user", {}).get("username") == "admin", "login user.username == admin")
    _check(resp.status_code == 200, "login always returns 200")

    # 2d. register
    import uuid
    _test_username = f"test_{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/auth/register", json={
        "username": _test_username, "password": _DEFAULT_PWD_HASH,
        "display_name": "Test User"
    })
    _check(resp.status_code in (200, 409, 403),
           f"POST /api/auth/register -> {resp.status_code}")
    if resp.status_code == 200:
        _check(resp.json().get("success") is True, "register success")

    # 2e. /api/auth/me (cookie)
    client.cookies.clear()
    login_token = _login()
    resp = client.get("/api/auth/me")
    _check(resp.status_code == 200, "GET /api/auth/me (cookie) -> 200")
    j = resp.json()
    _check("username" in j, "/api/auth/me has username")
    _check("role" in j, "/api/auth/me has role")
    _check("user_id" in j, "/api/auth/me has user_id")

    # /api/auth/me (Bearer header)
    client.cookies.clear()
    resp = client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {login_token}"})
    _check(resp.status_code == 200, "GET /api/auth/me (Bearer) -> 200")

    # 2f. refresh
    resp = client.post("/api/auth/refresh",
                       headers={"Authorization": f"Bearer {login_token}"})
    _check(resp.status_code == 200, "POST /api/auth/refresh -> 200")
    j = resp.json()
    _check("token" in j, "refresh returns new token")
    _check("expires_in" in j, "refresh returns expires_in")

    # 2g. logout
    client.cookies.clear()
    _login()
    resp = client.post("/api/auth/logout")
    _check(resp.status_code == 200, "POST /api/auth/logout -> 200")
    j = resp.json()
    _check(j.get("success") is True, "logout.success == true")
    _check(j.get("message") == "已登出", "logout.message == 已登出")

    # 登出后 /api/auth/me 返回 401
    client.cookies.clear()
    resp = client.get("/api/auth/me")
    _check(resp.status_code == 401, "GET /api/auth/me (after logout) -> 401")

    # 2h. 重新登录
    client.cookies.clear()
    _login()


def test_unauthorized():
    """3) 认证保护"""
    print("\n===== 3. 未认证访问检查 =====")
    client.cookies.clear()

    for method, path in [
        ("GET", "/api/download-history"),
        ("GET", "/api/upload-history"),
        ("GET", "/api/edit-pdf/history"),
        ("GET", "/api/dual-layer/history"),
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"),
    ]:
        resp = client.request(method, path)
        _check(resp.status_code == 401,
               f"{method} {path} -> 401 (got {resp.status_code})")
        if resp.status_code == 401:
            _check("detail" in resp.json(), f"{path} 401 body has detail")

    client.cookies.clear()
    _login()


def test_download_history():
    """4) 下载历史"""
    print("\n===== 4. 下载历史 =====")
    resp = client.get("/api/download-history")
    _check(resp.status_code == 200, "GET /api/download-history -> 200")
    j = resp.json()
    _check("history" in j, "response has history list")
    _check("total" in j, "response has total count")
    _check(isinstance(j["history"], list), "history is a list")
    _check(isinstance(j["total"], int), "total is an int")

    for entry in j["history"]:
        _check("username" in entry, "history entry has username")
        break

    _check("no-cache" in resp.headers.get("cache-control", ""),
           "response has no-cache header")

    resp = client.delete("/api/download-history-item/0")
    _check(resp.status_code in (200, 404),
           "DELETE /api/download-history-item/0 responds")
    if resp.status_code == 200:
        _check(resp.json().get("success") is True, "delete success")
    elif resp.status_code == 404:
        _check("detail" in resp.json(), "delete 404 has detail")


def test_upload_history():
    """5) 上传历史"""
    print("\n===== 5. 上传历史 =====")
    resp = client.get("/api/upload-history")
    _check(resp.status_code == 200, "GET /api/upload-history -> 200")
    j = resp.json()
    _check("history" in j, "response has history list")
    _check("total" in j, "response has total count")
    _check(isinstance(j["history"], list), "history is a list")


def test_edit_pdf_history():
    """6) 编辑PDF历史"""
    print("\n===== 6. 编辑PDF历史 =====")
    resp = client.get("/api/edit-pdf/history")
    _check(resp.status_code == 200, "GET /api/edit-pdf/history -> 200")
    j = resp.json()
    _check("history" in j, "response has history list")
    for entry in j["history"]:
        _check("username" in entry, "edit-pdf entry has username")
        break


def test_dual_layer_history():
    """7) 双层PDF历史"""
    print("\n===== 7. 双层PDF历史 =====")
    resp = client.get("/api/dual-layer/history")
    _check(resp.status_code == 200, "GET /api/dual-layer/history -> 200")
    j = resp.json()
    _check("history" in j, "response has history list")


def test_response_format():
    """8) Content-Type 验证"""
    print("\n===== 8. 响应格式 =====")
    for method, path in [("GET", "/api/health"), ("GET", "/api")]:
        resp = client.request(method, path)
        _check("application/json" in resp.headers.get("content-type", ""),
               f"{path} Content-Type is JSON")

    client.cookies.clear()
    _login()
    for method, path in [
        ("GET", "/api/download-history"),
        ("GET", "/api/upload-history"),
        ("GET", "/api/edit-pdf/history"),
        ("GET", "/api/dual-layer/history"),
    ]:
        resp = client.request(method, path)
        _check("application/json" in resp.headers.get("content-type", ""),
               f"{path} Content-Type is JSON")


def main() -> int:
    print("=" * 60)
    print("  后端 API 全面集成测试")
    print(f"  项目: {_PROJECT_ROOT}")
    print("=" * 60)

    test_system()
    test_auth()
    test_unauthorized()
    test_download_history()
    test_upload_history()
    test_edit_pdf_history()
    test_dual_layer_history()
    test_response_format()

    total = _passed + _failed
    print("\n" + "=" * 60)
    print(f"  汇总: 通过 {_passed} / 失败 {_failed} / 总计 {total}")
    if _failed == 0:
        print("  结论: 全部通过!")
    else:
        print(f"  结论: 存在 {_failed} 个失败项")
    print("=" * 60)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
