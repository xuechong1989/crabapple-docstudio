# -*- coding: utf-8 -*-
# xuechong 2026-09-22 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# form-in 文件库推送模块：图片转PDF成功后送进form-in文件库，两个系统之间只传元数据、不传文件字节
"""
推送顺序（强制）：
1. 先调 cloud_store 把 PDF 直接写入云盘存储（MongoDB 或 Windows 本地磁盘模式），读回校验 MD5 一致才算成功；
2. 校验通过后才调 form-in 的元数据注册接口 registerMetadata（登录拿会话 Cookie 后 POST hash/fileName/totalBytes/sourceFolder）；
3. 注册结果追加到任务消息末尾（任务列表现有的 task.message 展示位，scanner 前端零改动）。
推送在专用单线程池后台执行，任何异常记日志并追加到任务消息，不影响本地 PDF 生成与任务状态。
"""

from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor

from backend.services.logging_service import log_info

# 推送专用单线程池：推送串行执行，不占用图片处理线程资源
_push_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="form_in_push")

# HTTP 超时（秒）：登录与注册都是小请求；探活用短超时快速失败
_LOGIN_TIMEOUT = 30
_REGISTER_TIMEOUT = 60
_PING_TIMEOUT = 5


def submit_push(pdf_path: str, source_folder: str, task: dict) -> None:
    """提交推送任务到后台单线程池执行；开关关闭时直接返回（不提交任务）。
    入口自身不抛任何异常：推送失败绝不影响任务主流程
    """
    try:
        from backend import config
        if not config.FORM_IN_ENABLED:
            return
        def _run():
            try:
                _push_once(pdf_path, source_folder, task)
            except Exception as e:
                log_info("[form-in推送] 推送执行异常（不影响本地PDF）: " + str(e))
                _append_task_message(task, "；form-in推送异常：" + str(e))
        _push_executor.submit(_run)
    except Exception as submit_err:
        log_info("[form-in推送] 推送任务提交失败（不影响本地PDF）: " + str(submit_err))
        _append_task_message(task, "；form-in推送异常：" + str(submit_err))


def _push_once(pdf_path: str, source_folder: str, task: dict) -> None:
    """一次完整推送：云盘写入并读回校验 → 探活 → 登录 → 注册 → 结果追加任务消息"""
    from backend import config
    from backend import cloud_store

    file_path = Path(pdf_path)
    if not file_path.exists():
        log_info("[form-in推送] PDF文件不存在，跳过推送: " + str(file_path))
        return
    log_info("[form-in推送] 开始推送: " + str(file_path) + "，来源文件夹=" + source_folder)
    # 第一步：写入云盘存储并读回校验（校验不通过绝不调注册接口）
    write_result = cloud_store.write_file(str(file_path))
    if not write_result.get("ok"):
        reason = "云盘写入失败（" + str(write_result.get("message")) + "）"
        _append_task_message(task, "；form-in推送失败：" + reason)
        log_info("[form-in推送] " + reason)
        return
    file_hash = write_result["hash"]
    file_size = write_result["size"]
    log_info("[form-in推送] " + str(write_result.get("message")) + "，hash=" + file_hash)
    # 第二步：探活 form-in 服务
    session = requests.Session()
    base_address = config.FORM_IN_ADDRESS
    ping_ok = _ping(session, base_address)
    if not ping_ok:
        _append_task_message(task, "；form-in推送失败：form-in服务不可达（" + base_address + "）")
        log_info("[form-in推送] form-in服务不可达: " + base_address)
        return
    # 第三步：登录拿会话
    login_ok = _login(session, base_address)
    if not login_ok:
        _append_task_message(task, "；form-in推送失败：登录form-in失败（检查推送账号配置）")
        log_info("[form-in推送] 登录form-in失败")
        return
    # 第四步：注册元数据（文件本体已在云盘，只传 hash/文件名/字节数/来源文件夹名）
    register_ok, register_message, file_id = _register_metadata(session, base_address, file_hash, file_path.name, file_size, source_folder)
    if not register_ok:
        _append_task_message(task, "；form-in推送失败：form-in注册失败（" + register_message + "）")
        log_info("[form-in推送] form-in注册失败: " + register_message)
        return
    _append_task_message(task, "；已写入云盘并注册到form-in文件库")
    log_info("[form-in推送] 注册成功，fileId=" + str(file_id))
    # xuechong 2026-09-26 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 推送结果回写任务对象并持久化：收集整理进度页用 hash 精确对应 form-in 文件库里的记录
    task["pushed_file"] = file_path.name
    task["pushed_hash"] = file_hash
    _save_tasks_snapshot(task)


def _append_task_message(task: dict, suffix: str) -> None:
    """把推送结果追加到任务消息末尾（任务列表的 task.message 展示位）"""
    try:
        current = task.get("message", "")
        task["message"] = current + suffix
    except Exception as e:
        log_info("[form-in推送] 追加任务消息失败: " + str(e))


# xuechong 2026-09-26 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# 推送线程改了任务字段后补一次任务持久化（主流程 finally 已落过盘，这里保存回写的 pushed_file/pushed_hash）；
# 找不到任务所属用户（老任务无 username 字段）时跳过，不影响推送结果
def _save_tasks_snapshot(task: dict) -> None:
    try:
        from backend.services.user_scope import get_user_scope
        username = task.get("username")
        if not username:
            return
        scope = get_user_scope(username)
        scope.save_tasks()
    except Exception as e:
        log_info("[form-in推送] 任务状态持久化失败: " + str(e))


def _ping(session: requests.Session, base_address: str) -> bool:
    """探测 form-in 文件库服务可用性（POST /api/cdk/efile/filelib/ping）"""
    url = base_address + "/api/cdk/efile/filelib/ping"
    try:
        resp = session.post(url, timeout=_PING_TIMEOUT)
        if resp.status_code == 200:
            return True
        log_info("[form-in推送] ping返回状态码=" + str(resp.status_code))
        return False
    except Exception as e:
        log_info("[form-in推送] ping异常: " + str(e))
        return False


def _login(session: requests.Session, base_address: str) -> bool:
    """登录 form-in 建立会话（POST /api/cdk/efile/cltdenglv/loginByPwd，参数 account/password）。
    该接口不收明文密码：password 必须按「明文MD5三次→湮没算法→Ska」加密后传参
    （加密实现见 backend/login_cipher.py，已用 Java 端 SubmergeUtil.decrypt 逐条验证可还原）
    """
    from backend import config
    from backend.login_cipher import encrypt_login_password
    url = base_address + "/api/cdk/efile/cltdenglv/loginByPwd"
    encrypted_password = encrypt_login_password(config.FORM_IN_PASSWORD)
    data = {"account": config.FORM_IN_USERNAME, "password": encrypted_password}
    try:
        resp = session.post(url, data=data, timeout=_LOGIN_TIMEOUT)
        if resp.status_code != 200:
            log_info("[form-in推送] 登录返回状态码=" + str(resp.status_code))
            return False
        body = resp.json()
        if body.get("success"):
            return True
        log_info("[form-in推送] 登录返回失败: " + str(body.get("message")))
        return False
    except Exception as e:
        log_info("[form-in推送] 登录异常: " + str(e))
        return False


def _register_metadata(session: requests.Session, base_address: str, file_hash: str, file_name: str, file_size: int, source_folder: str) -> tuple:
    """调用 form-in 元数据注册接口（POST /api/cdk/efile/filelib/registerMetadata）。
    返回 (是否成功, 说明, fileId)
    """
    url = base_address + "/api/cdk/efile/filelib/registerMetadata"
    data = {
        "hash": file_hash,
        "fileName": file_name,
        "totalBytes": str(file_size),
        "sourceFolder": source_folder,
        "autoAnalyze": "true",
    }
    try:
        resp = session.post(url, data=data, timeout=_REGISTER_TIMEOUT)
        if resp.status_code != 200:
            return False, "HTTP状态码" + str(resp.status_code), ""
        body = resp.json()
        if body.get("success"):
            file_id = ""
            data_body = body.get("data")
            if isinstance(data_body, dict):
                file_id = str(data_body.get("fileId", ""))
            return True, "注册成功", file_id
        return False, str(body.get("message")), ""
    except Exception as e:
        return False, "请求异常：" + str(e), ""
