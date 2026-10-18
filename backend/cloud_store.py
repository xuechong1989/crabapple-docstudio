# -*- coding: utf-8 -*-
# xuechong 2026-09-22 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# 云盘存储直写模块：scanner 把生成的 PDF 直接写入 form-in 的云盘存储，两个系统之间不再传文件字节
# xuechong 2026-09-24 研发BUG-0066-某项目-21-4.2.00-上传文件新增MD5回读校验彻底解决文件缺失或损坏的问题
# 同步 form-in 存储层 的强制回读校验语义：读回校验未通过自动强制重写一次（主记录 writedSize
# 置 0 后从头逐块覆盖重写，对应 writeByUrlForce/p_forceRewrite），重写后仍校验不过才判失败
"""
存储格式与 form-in 存储层 完全一致（字段清单见各写入函数）：
- 库内三个系列的集合：info（容量统计）、file（文件元数据，以文件 MD5 为 hash 主键）、chunk0/chunk1/...（分块内容，每集合累计 100GB 轮换）
- 文件按 2MB 一块，每块 AES-256/ECB/PKCS7Padding 加密后再 Base64 编码，存入 chunk 文档的 content 字段（BSON Binary）
- 加密密钥由部署方通过环境变量 DOCSTUDIO_MONGODB_KEY 配置，派生方式为 Java SHA1PRNG（种子=密钥串 UTF-8 字节，取前 32 字节）
- 同 hash 已存在且 writedSize==size 视为已完整，跳过写入（秒传）；writedSize<size 从已写位置续写；writedSize>size 视为元数据损坏
写入完成后必须把全部块读回来解密拼接，校验 MD5 与原文件一致，校验通过才算写入成功；
读回校验未通过（含秒传命中的既有坏对象、损坏到解不开的块）自动强制重写一次再核，仍不通过才判失败（与 form-in 存储层 强制回读校验同语义）；
同一 hash 的写入全程持 per-md5 线程锁串行执行（对应 form-in 存储层.FILE_LOCKS），强制重写是同位置覆盖不新增存储占用，info 容量统计不因重写重复累计；
调用方（backend/form_in.py）只有在校验通过后才允许调 form-in 的元数据注册接口。
STORE_MODE=localdisk 时走 Windows 本地磁盘模式：把 PDF 以 MD5 命名复制到 bddata 目录（与 form-in 本地开发环境共用同一目录）。
"""

import base64
import os
import hashlib
import shutil
import threading
from pathlib import Path

# 分块大小 2MB，与 form-in 存储层.CHUNK_SIZE 一致
CHUNK_SIZE = 2 * 1024 * 1024
# 单个 chunk 集合容量上限 100GB，与 form-in 存储层.COLL_MAXSIZE 一致
COLL_MAXSIZE = 100 * 1024 * 1024 * 1024
# form-in 云盘加密密钥，由部署方配置；未配置时相关功能不可用
MONGODB_KEY = os.environ.get("DOCSTUDIO_MONGODB_KEY", "")


def _signed(byte_value: int) -> int:
    """把 0..255 的字节值转成 Java byte 的带符号值（-128..127）"""
    if byte_value >= 128:
        return byte_value - 256
    return byte_value


def _update_state(state: bytes, output: bytes) -> bytes:
    """复刻 sun.security.provider.SecureRandom.updateState：
    state = (state + output + 1) mod 2^160，从第 0 字节起逐字节进位。
    注意 Java 的 (int)byte 是带符号提升、进位 v>>8 是算术右移，必须按带符号语义算，无符号模拟会算错进位
    """
    last = 1
    new_state = bytearray(20)
    for i in range(20):
        v = _signed(state[i]) + _signed(output[i]) + last
        new_state[i] = v & 0xFF
        last = v >> 8
    return bytes(new_state)


def sha1prng_key_bytes(seed: bytes, length: int = 32) -> bytes:
    """复刻 Java SHA1PRNG 的输出流（与 sun.security.provider.SecureRandom 逐字节一致，
    算法已用 JDK8 实际输出流验证 5 个 20 字节块全部匹配）：
    state = SHA1(seed)；每轮输出 20 字节 = SHA1(state)；随后 state = state + output + 1（模 2^160）。
    KeyGenerator("AES").init(256, 该随机源) 取前 32 字节即 AES 密钥。
    正确性由 tests/test_cloud_store.py 内 Java 端预生成的加密参考向量保证（逐字节比对）。
    """
    state = hashlib.sha1(seed).digest()
    out = b""
    while len(out) < length:
        block = hashlib.sha1(state).digest()
        out += block
        state = _update_state(state, block)
    return out[:length]


def _get_cipher():
    """惰性初始化 AES 加解密器（pycryptodome），密钥按 SHA1PRNG 派生"""
    if not MONGODB_KEY:
        raise RuntimeError("未配置 DOCSTUDIO_MONGODB_KEY，form-in 云盘存储不可用")
    from Crypto.Cipher import AES
    key = sha1prng_key_bytes(MONGODB_KEY.encode("utf-8"), 32)
    return AES.new(key, AES.MODE_ECB)


def encrypt_chunk(plain: bytes) -> bytes:
    """单块加密：AES-256/ECB/PKCS7Padding 加密后 Base64 编码，返回 Base64 文本字节（与 p_encryptByAes 输出一致）"""
    cipher = _get_cipher()
    pad_len = 16 - (len(plain) % 16)
    padded = plain + bytes([pad_len]) * pad_len
    cipher_bytes = cipher.encrypt(padded)
    return base64.b64encode(cipher_bytes)


def decrypt_chunk(content: bytes) -> bytes:
    """单块解密：Base64 解码后 AES-256/ECB/PKCS7Padding 解密并去填充"""
    from Crypto.Util.Padding import unpad
    cipher = _get_cipher()
    cipher_bytes = base64.b64decode(content)
    plain_padded = cipher.decrypt(cipher_bytes)
    return unpad(plain_padded, 16)


def compute_file_md5(file_path) -> tuple:
    """计算文件 MD5 与字节数，返回 (32位小写MD5, 字节数)"""
    md5 = hashlib.md5()
    total = 0
    with open(file_path, "rb") as f:
        while True:
            block = f.read(8 * 1024 * 1024)
            if not block:
                break
            md5.update(block)
            total += len(block)
    return md5.hexdigest(), total


def _now_str() -> str:
    """当前时间字符串，格式与 TimerUtil.FORMATTYPE1 一致（yyyy-MM-dd HH:mm:ss）"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pick_chunk_collection_name(db, file_size: int) -> str:
    """复刻 form-in 存储层.getCollectionChunk 的集合选择规则：
    info 文档数为 count、最新一篇 info 的 size 累计值 s；count 为 0 用 chunk0；
    否则序号 i=count-1，若 s+本文件大小超过 100GB 则 i+1（轮换新集合）
    """
    count = db["info"].estimated_document_count()
    if count == 0:
        return "chunk0"
    latest = db["info"].find_one(sort=[("_id", -1)])
    if latest is None:
        return "chunk0"
    size_value = latest.get("size", 0)
    try:
        accumulated = int(size_value)
    except (TypeError, ValueError):
        accumulated = 0
    index = count - 1
    if accumulated + file_size > COLL_MAXSIZE:
        index = index + 1
    return "chunk" + str(index)


def _get_mongo_db():
    """按 url.conf 配置连接 MongoDB，返回 (client, db)；调用方用完必须 client.close() 释放连接"""
    from backend import config
    from pymongo import MongoClient
    host_port = config.MONGO_HOST
    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_port
        port = 27017
    client = MongoClient(
        host=host,
        port=port,
        username=config.MONGO_USERNAME,
        password=config.MONGO_PASSWORD,
        authSource=config.MONGO_DBNAME,
        authMechanism="SCRAM-SHA-1",
        serverSelectionTimeoutMS=10000,
        connectTimeoutMS=10000,
    )
    return client, client[config.MONGO_DBNAME]


# 同 hash 写入串行化锁表（对应 form-in 存储层.FILE_LOCKS）：并发的探测/写入/置0互相读到中间状态由它排除
_md5_locks = {}
_md5_locks_guard = threading.Lock()


def _get_md5_lock(md5: str):
    """取该 hash 专属的写入锁，不存在则创建；调用方用完在释放的同时从锁表移除（防锁表无限增长）"""
    with _md5_locks_guard:
        lock = _md5_locks.get(md5)
        if lock is None:
            lock = threading.Lock()
            _md5_locks[md5] = lock
        return lock


def _read_back_and_verify(db, file_doc, expect_md5: str, expect_size: int) -> tuple:
    """读回校验：按块序号读出该文件全部 chunk，解密拼接后校验总字节数与 MD5。
    返回 (是否通过, 说明)
    """
    chunk_coll = db[file_doc["chunkname"]]
    fid = file_doc["_id"]
    md5 = hashlib.md5()
    total = 0
    chunk_count = 0
    for chunk in chunk_coll.find({"fid": fid}).sort("n", 1):
        content = chunk.get("content")
        if content is None:
            return False, "存在没有内容的块（序号=" + str(chunk.get("n")) + "）"
        # 损坏到解不开的块（非法 Base64、密文长度非16倍数、填充位错误）一律按校验不过处理，交给上层强制重写修复
        # （对应 Java p_verifyWritten 整体 catch Throwable 返回 false），不允许异常冒泡中断推送链路
        try:
            plain = decrypt_chunk(bytes(content))
        except Exception as e:
            return False, "块内容解密失败（序号=" + str(chunk.get("n")) + "，" + str(e) + "）"
        md5.update(plain)
        total += len(plain)
        chunk_count = chunk_count + 1
    if total != expect_size:
        return False, "读回字节数不一致（期望 " + str(expect_size) + "，实际 " + str(total) + "）"
    actual_md5 = md5.hexdigest()
    if actual_md5 != expect_md5:
        return False, "读回MD5不一致（期望 " + expect_md5 + "，实际 " + actual_md5 + "）"
    return True, "读回校验通过（" + str(chunk_count) + " 块，" + str(total) + " 字节）"


def _reset_writed_size(md5: str) -> bool:
    """强制重写前置动作（与 form-in 存储层.writeByUrlForce 同语义）：把该 hash 主记录的 writedSize 置 0，
    让后续写入探测不再命中秒传/续写，从头逐块覆盖重写（分块写入是 upsert 覆盖语义，纯覆盖不删除已有数据）
    """
    client, db = _get_mongo_db()
    try:
        result = db["file"].update_one({"hash": md5}, {"$set": {"writedSize": 0}})
        # 按"记录存在"（matched_count）而非"值被修改"（modified_count）判定：writedSize 已是 0 时
        # 置0不修改任何字段但仍算成功，与 Java writeByUrlForce 不检查置0结果、只看操作是否抛错的行为对齐
        return result.matched_count == 1
    finally:
        client.close()


def write_file_to_mongodb(local_path) -> dict:
    """把本地文件按云盘存储格式写入 MongoDB（同一 hash 全程持锁串行执行，对应 form-in 存储层.FILE_LOCKS）。
    读回校验未通过（含秒传命中的既有坏对象、解不开的坏块）时强制重写一次再核，仍不通过判失败——对应 form-in 存储层
    writeByUrl 写完即回读校验、校验不过置 0 强制重写且只重写一次的语义。
    返回 {ok: bool, hash: str, size: int, message: str, fast: bool}
    """
    from backend.services.logging_service import log_info

    file_path = Path(local_path)
    if not file_path.exists():
        return {"ok": False, "hash": "", "size": 0, "message": "本地文件不存在: " + str(file_path), "fast": False}
    if not file_path.is_file():
        # 与 form-in 存储层.writeByUrl 前置校验同款：非普通文件直接拒收
        return {"ok": False, "hash": "", "size": 0, "message": "本地文件不是普通文件: " + str(file_path), "fast": False}
    if file_path.stat().st_size <= 0:
        # 与 form-in 存储层.writeByUrl 前置校验同款：大小为 0 直接拒收，不留无 chunk 的空记录与 info 统计副作用
        return {"ok": False, "hash": "", "size": 0, "message": "文件大小为0", "fast": False}
    md5, file_size = compute_file_md5(file_path)
    md5_lock = _get_md5_lock(md5)
    md5_lock.acquire()
    try:
        result = _write_mongodb_once(file_path, md5, file_size)
        # xuechong 2026-09-24 研发BUG-0066-某项目-21-4.2.00-上传文件新增MD5回读校验彻底解决文件缺失或损坏的问题
        # 读回校验未通过自动强制重写一次：主记录置 0 后重走完整写入（覆盖语义，坏对象由此被重传修复），重写后仍不过直接判失败
        if (not result["ok"]) and result.get("verify_fail"):
            log_info("[云盘写入] 读回校验未通过，强制置0重写一次: " + md5 + "（" + result["message"] + "）")
            if not _reset_writed_size(md5):
                result["message"] = "读回校验失败且主记录writedSize置0失败，无法强制重写（" + result["message"] + "）"
                return result
            retry = _write_mongodb_once(file_path, md5, file_size, is_force_rewrite=True)
            if retry["ok"]:
                retry["message"] = "强制重写修复成功，" + retry["message"]
            elif retry.get("verify_fail"):
                retry["message"] = "云盘强制重写后读回校验仍失败，判定失败（" + retry["message"] + "）"
            return retry
        return result
    finally:
        with _md5_locks_guard:
            _md5_locks.pop(md5, None)
        md5_lock.release()


def _write_mongodb_once(file_path, md5: str, file_size: int, is_force_rewrite: bool = False) -> dict:
    """单次完整写入：连接 → 探测（秒传/续写/元数据损坏）→ 分块写入 → 读回校验。
    读回校验未通过的返回带 verify_fail 标记，由 write_file_to_mongodb 决定是否强制重写；
    is_force_rewrite=True 表示本次是置0后的强制重写：覆盖既有 chunk 与 file 文档、不新增存储占用，跳过 info 容量累计
    """
    from bson.objectid import ObjectId

    client, db = _get_mongo_db()
    try:
        file_coll = db["file"]
        existing = file_coll.find_one({"hash": md5})
        # 已存在记录的三种情况：完整（秒传）/未完整（续写）/元数据损坏（报错结束）
        if existing is not None:
            writed = int(existing.get("writedSize", 0))
            size = int(existing.get("size", 0))
            if writed > size:
                return {"ok": False, "hash": md5, "size": file_size, "message": "云盘已有该hash的元数据损坏记录（writedSize>size），请人工处理", "fast": False}
            if writed == size and size == file_size:
                verify_ok, verify_msg = _read_back_and_verify(db, existing, md5, file_size)
                if not verify_ok:
                    # 秒传命中的既有对象校验不过也走强制重写（对应 form-in 存储层 秒传命中回读核对不过即置0重写）
                    return {"ok": False, "hash": md5, "size": file_size, "message": "秒传文件读回校验失败：" + verify_msg, "fast": True, "verify_fail": True}
                return {"ok": True, "hash": md5, "size": file_size, "message": "云盘已存在同hash完整文件，跳过写入（秒传），" + verify_msg, "fast": True}
        # 分块写入（新文件从 0 开始，未完整的历史记录从 writedSize 位置续写）
        offset = 0
        fid = None
        if existing is not None:
            # 续写必须沿用已存记录的 chunkname：chunk 集合可能已轮换，重新选择会把新块写进新集合、丢掉旧集合里的块
            fid = existing["_id"]
            offset = int(existing.get("writedSize", 0))
            chunk_name = existing["chunkname"]
        else:
            chunk_name = _pick_chunk_collection_name(db, file_size)
        chunk_coll = db[chunk_name]
        with open(file_path, "rb") as f:
            if offset > 0:
                f.seek(offset)
            while offset < file_size:
                write_will = min(CHUNK_SIZE, file_size - offset)
                plain = f.read(write_will)
                if len(plain) != write_will:
                    return {"ok": False, "hash": md5, "size": file_size, "message": "本地文件读取不完整（期望 " + str(write_will) + " 字节，实际 " + str(len(plain)) + " 字节）", "fast": False}
                chunk_index = offset // CHUNK_SIZE
                encrypted = encrypt_chunk(plain)
                if fid is None:
                    fid = ObjectId()
                chunk_coll.update_one(
                    {"fid": fid, "n": chunk_index},
                    {
                        "$setOnInsert": {"_id": ObjectId(), "fid": fid, "n": chunk_index},
                        "$set": {"content": encrypted},
                    },
                    upsert=True,
                )
                offset = offset + write_will
                new_writed = offset
                # 与 Java 端写入顺序一致：第一块写完后插入 file 文档，后续块递增 writedSize 后整篇替换
                file_doc = {
                    "_id": fid,
                    "hash": md5,
                    "size": file_size,
                    "writedSize": new_writed,
                    "chunkname": chunk_name,
                    "updatetime": _now_str(),
                }
                file_coll.replace_one({"_id": fid}, file_doc, upsert=True)
        # 最后一块写完更新 info 集合容量统计（与 form-in 存储层.p_updateSize 同语义：最新 info 的 size 累加，没有则新建）；
        # 强制重写是同位置覆盖、不新增存储占用，不重复累计（Java 端重写会再累计一次，属保守方向的既有偏差，此处按只计一次处理）
        if not is_force_rewrite:
            latest_info = db["info"].find_one(sort=[("_id", -1)])
            if latest_info is None:
                db["info"].insert_one({"_id": ObjectId(), "size": file_size})
            else:
                db["info"].update_one({"_id": latest_info["_id"]}, {"$inc": {"size": file_size}})
        # 读回校验（强制顺序：校验通过调用方才允许调 form-in 注册接口）
        final_doc = file_coll.find_one({"hash": md5})
        if final_doc is None:
            return {"ok": False, "hash": md5, "size": file_size, "message": "写入后查不到文件元数据记录", "fast": False}
        verify_ok, verify_msg = _read_back_and_verify(db, final_doc, md5, file_size)
        if not verify_ok:
            return {"ok": False, "hash": md5, "size": file_size, "message": "云盘写入读回校验失败：" + verify_msg, "fast": False, "verify_fail": True}
        return {"ok": True, "hash": md5, "size": file_size, "message": "云盘写入成功，" + verify_msg, "fast": False}
    finally:
        client.close()


def write_file_to_localdisk(local_path) -> dict:
    """Windows 本地磁盘模式：把 PDF 复制到 bddata 目录并以 MD5 命名（与 form-in 本地开发环境的云盘模拟目录共用）"""
    from backend import config
    file_path = Path(local_path)
    if not file_path.exists():
        return {"ok": False, "hash": "", "size": 0, "message": "本地文件不存在: " + str(file_path), "fast": False}
    md5, file_size = compute_file_md5(file_path)
    target_dir = Path(config.LOCAL_DISK_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / md5
    shutil.copyfile(str(file_path), str(target))
    # 读回校验
    read_back_md5, read_back_size = compute_file_md5(target)
    if read_back_md5 != md5 or read_back_size != file_size:
        return {"ok": False, "hash": md5, "size": file_size, "message": "本地磁盘写入读回校验失败", "fast": False}
    return {"ok": True, "hash": md5, "size": file_size, "message": "本地磁盘写入成功，读回校验通过", "fast": False}


def write_file(local_path) -> dict:
    """存储写入统一入口：按 STORE_MODE 分发（mongodb=直写 MongoDB，localdisk=Windows 本地磁盘）"""
    from backend import config
    if config.STORE_MODE == "localdisk":
        return write_file_to_localdisk(local_path)
    return write_file_to_mongodb(local_path)
