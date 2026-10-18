#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 DOCSTUDIO_AUTH_HASH 使用的口令哈希。

前端登录会对口令做 100000 轮 SHA-256，后端旧版兼容接口使用同一个哈希。
用法：
    python scripts/hash_password.py
    export DOCSTUDIO_AUTH_HASH=<输出的十六进制>
"""

import getpass
import hashlib


def main() -> None:
    password = getpass.getpass("Password: ")
    if not password:
        raise SystemExit("口令不能为空")
    value = password.encode("utf-8")
    for _ in range(100000):
        value = hashlib.sha256(value).digest()
    print(value.hex())


if __name__ == "__main__":
    main()
