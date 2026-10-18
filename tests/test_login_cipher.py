# -*- coding: utf-8 -*-
"""form-in 登录密码加密模块测试（研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程）。
参考向量由 JDK8 调 crabapple 的 SkaUtil/MD5Util 生成；湮没算法带随机数无法逐字节比对，
其正确性以「Java 端 SubmergeUtil.decrypt 能还原 Python 加密结果」验证（开发期已实测三个密码全部还原成功）。
"""
import re

import pytest

from backend.login_cipher import (
    _caesar_encrypt,
    _md5,
    _ska_public_encrypt,
    encrypt_login_password,
)

# JDK8 + crabapple 生成的参考向量
JAVA_MD5_TEST123 = "cc03e747a6afbbcbf8be7668acfebee5"
JAVA_MD53_REAL_PWD = "0f6c19e6d31d0e080ec958ca288747b8"  # "WLT@sjsxny#2025!" 的 md5 三次值
JAVA_SKA_VECTORS = [
    ("abcXYZ019-#", "djlIHG527.-"),
    ("a", "d"),
    ("0123456789", "5231609487"),
]


class TestMd5:
    """MD5 与 JDK8 MD5Util.getHash 一致"""

    def test_md5_vector(self):
        assert _md5("test123") == JAVA_MD5_TEST123

    def test_md5_three_times(self):
        value = "WLT@sjsxny#2025!"
        for _ in range(3):
            value = _md5(value)
        assert value == JAVA_MD53_REAL_PWD


class TestSkaPublicEncrypt:
    """Ska 公开本加密与 JDK8 SkaUtil.encrypt(ENCRYPT_PUBLIC, x, 10) 逐字节一致"""

    @pytest.mark.parametrize("plaintext,expect", JAVA_SKA_VECTORS)
    def test_ska_vector(self, plaintext, expect):
        assert _ska_public_encrypt(plaintext, 10) == expect


class TestCaesar:
    """凯撒移位规则（字母+10 mod 26、数字+10 mod 10、其他原样）"""

    def test_letter_wrap(self):
        # 'w'+10 超过 'z' 回绕到 'g'
        assert _caesar_encrypt("wxyz", 10) == "ghij"

    def test_digit_wrap(self):
        # '5'+10 超过 '9' 回绕到 '5'（mod 10）
        assert _caesar_encrypt("0123456789", 10) == "0123456789"

    def test_other_chars_untouched(self):
        assert _caesar_encrypt("-#@_", 10) == "-#@_"


class TestEncryptLoginPassword:
    """登录密码参数整体结构"""

    def test_output_is_printable_ascii(self):
        cipher = encrypt_login_password("test123")
        # 密文字符全部为可打印 ascii（密码本与凯撒的输出域）
        assert all(33 <= ord(ch) <= 126 for ch in cipher)

    def test_output_differs_each_call(self):
        # 湮没算法含随机串与时间戳，两次加密结果不同（服务端按规则解密，不比对密文）
        assert encrypt_login_password("test123") != encrypt_login_password("test123")

    def test_output_length_reasonable(self):
        cipher = encrypt_login_password("test123")
        # 明文md53为32字符，密文必然远长于明文（随机串128+13位起）
        assert len(cipher) > 100
