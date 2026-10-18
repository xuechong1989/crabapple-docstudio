# -*- coding: utf-8 -*-
# xuechong 2026-09-22 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# form-in 登录密码加密模块：form-in 的登录接口 loginByPwd 不收明文密码，
# 要求 password 参数为「明文 MD5 三次 → 湮没算法加密 → Ska加密（凯撒+公开密码本）」的结果。
# 三段算法与 crabapple 的 xc.crabapple.core.cipher.submerge.SubmergeUtil / ska.SkaUtil 逐行为对齐，
# 正确性由 tests/test_login_cipher.java 端参考向量与「Java SubmergeUtil.decrypt 能还原」双向验证
"""
加密链（与 LoginServiceImpl.checkMd53Password 对偶）：
1. md5 三次：md53 = md5(md5(md5(明文)))
2. 湮没算法 SubmergeUtil.encrypt(公钥常量, md53)：
   随机串+毫秒时间戳 → 从首个数字起按“每偶数迭代插一个倒序明文字符”混入 →
   按公钥各字符 ascii（删字符0后）的数值逐个做首尾轮转 → 尾部追加 "XC"+明文长度
3. Ska 加密 SkaUtil.encrypt(公开本, 10)：先凯撒移位（字母+10 mod 26、数字+10 mod 10），再查公开密码本映射
"""

import hashlib
import random
import string
import time

# 湮没算法公钥（与 AppSecurityUtil.SUBMERGE_PUBLIC_KEY_PWD 一致）
SUBMERGE_KEY = "09wlyot2ceoevk3ysvn72ywwfqwj4smqozlvgi0iuugccu2kysacwsqpuf0hcziwbx6a5pbvn8ojlovpzlk07trmtvepwdefm35hjduhfwhnfyiqdakzxr2fhkrfspjm"

# Ska 公开密码本（与 SkaUtil.p_ascPubMap 一致，键值均为 ascii 码）
ASC_PUB_MAP = {
    48: 53, 49: 50, 50: 51, 51: 49, 52: 54, 53: 48, 54: 57, 55: 52, 56: 56, 57: 55,
    65: 80, 66: 66, 67: 85, 68: 89, 69: 87, 70: 68, 71: 74, 72: 73, 73: 72, 74: 71,
    75: 69, 76: 78, 77: 76, 78: 65, 79: 70, 80: 79, 81: 84, 82: 75, 83: 81, 84: 83,
    85: 67, 86: 82, 87: 88, 88: 90, 89: 86, 90: 77,
    97: 122, 98: 117, 99: 110, 100: 101, 101: 121, 102: 115, 103: 118, 104: 104,
    105: 102, 106: 97, 107: 100, 108: 106, 109: 108, 110: 120, 111: 116, 112: 103,
    113: 111, 114: 98, 115: 112, 116: 105, 117: 114, 118: 113, 119: 99, 120: 109,
    121: 119, 122: 107,
    33: 44, 34: 47, 35: 45, 36: 43, 37: 42, 38: 38, 39: 33, 40: 41, 41: 35, 42: 34,
    43: 37, 44: 39, 45: 46, 46: 36, 47: 40,
    58: 61, 59: 62, 60: 58, 61: 60, 62: 59, 63: 64, 64: 63,
    91: 95, 92: 94, 93: 96, 94: 93, 95: 91, 96: 92,
    123: 124, 124: 125, 125: 126, 126: 123,
}


def _md5(text: str) -> str:
    """标准 MD5 十六进制（与 MD5Util.getHash 一致）"""
    md5 = hashlib.md5()
    md5.update(text.encode("utf-8"))
    return md5.hexdigest()


def _caesar_encrypt(plaintext: str, offset: int) -> str:
    """凯撒移位（与 CaesarUtil.encrypt 一致）：字母 +offset mod 26、数字 +offset mod 10、其他字符原样"""
    chars = []
    for ch in plaintext:
        code = ord(ch)
        if "a" <= ch <= "z":
            code = code + offset % 26
            if code > ord("z"):
                code = code - 26
            chars.append(chr(code))
            continue
        if "A" <= ch <= "Z":
            code = code + offset % 26
            if code > ord("Z"):
                code = code - 26
            chars.append(chr(code))
            continue
        if "0" <= ch <= "9":
            code = code + offset % 10
            if code > ord("9"):
                code = code - 10
            chars.append(chr(code))
            continue
        chars.append(ch)
    return "".join(chars)


def _ska_public_encrypt(plaintext: str, offset: int) -> str:
    """Ska 公开本加密（与 SkaUtil.encrypt(ENCRYPT_PUBLIC, x, offset) 一致）：先凯撒后查公开密码本"""
    shifted = _caesar_encrypt(plaintext, offset)
    chars = []
    for ch in shifted:
        mapped = ASC_PUB_MAP.get(ord(ch))
        if mapped is None:
            # 密码本外的字符（如中文）凯撒后原样保留，与 Java 端 p_ascPubMap.get 返回 null 时行为对齐由参考向量保证
            chars.append(ch)
            continue
        chars.append(chr(mapped))
    return "".join(chars)


def _rotate_cipher(cipher: str) -> str:
    """湮没算法的单次轮转（与 SubmergeUtil.encrypt 的 key 混淆一致）：
    新串 = 最后1字符 + [3, 长度-1) 段 + 前3字符
    """
    return cipher[-1] + cipher[3:-1] + cipher[:3]


def _submerge_encrypt(plaintext: str) -> str:
    """湮没算法加密（与 SubmergeUtil.encrypt(SUBMERGE_KEY, plaintext) 一致）"""
    random_str = "".join(random.choices(string.ascii_letters + string.digits, k=len(SUBMERGE_KEY)))
    random_full = random_str + str(int(time.time() * 1000))
    # 前缀：从左起直到第一个数字字符（含该数字）
    prefix_len = len(random_full)
    for i, ch in enumerate(random_full):
        prefix_len = i + 1
        if ch.isdigit():
            break
    mixed = list(random_full[:prefix_len])
    # 从前缀之后按“每偶数迭代插一个倒序明文字符+随机字符”混入
    plaintext_index = len(plaintext) - 1
    count = -1
    for i in range(prefix_len, len(random_full)):
        count = count + 1
        ch = random_full[i]
        if count % 2 == 0 and plaintext_index >= 0:
            mixed.append(plaintext[plaintext_index])
            mixed.append(ch)
            plaintext_index = plaintext_index - 1
            continue
        mixed.append(ch)
    # 随机串用尽后剩余明文倒序补在末尾
    while plaintext_index >= 0:
        mixed.append(plaintext[plaintext_index])
        plaintext_index = plaintext_index - 1
    cipher = "".join(mixed)
    # key 混淆：公钥各字符 ascii 码串删掉字符"0"后按逗号拆分，逐值做该值次轮转
    ascii_str = ",".join(str(ord(ch)) for ch in SUBMERGE_KEY).replace("0", "")
    for piece in ascii_str.split(","):
        if piece == "":
            continue
        times = int(piece)
        for _ in range(times):
            cipher = _rotate_cipher(cipher)
    # 尾部追加密文标记与明文长度
    cipher = cipher + "XC" + str(len(plaintext))
    return _ska_public_encrypt(cipher, 10)


def encrypt_login_password(plaintext: str) -> str:
    """登录密码参数生成入口：明文 MD5 三次后走湮没算法加密（loginByPwd 接口的 password 参数）"""
    md53 = plaintext
    for _ in range(3):
        md53 = _md5(md53)
    return _submerge_encrypt(md53)
