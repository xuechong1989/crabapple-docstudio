# -*- coding: utf-8 -*-
# xuechong 2026-09-22 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
# form-in 接口一键自检脚本：验证 scanner 与 form-in 之间的上传下载、元数据传参接口。
# 在 crabapple-docstudio 工程根目录运行（依赖本工程的 backend 包读取 url.conf 与登录加密实现）：
#   python scripts/formin_api_selfcheck.py --address http://127.0.0.1:6062 --account user@example.com --password 口令 --source-folder 合同
# 依次执行五步并输出 PASS/FAIL：
#   1. ping 探活 form-in 文件库服务
#   2. 登录（密码按系统要求加密传参）
#   3. 生成一个测试 PDF 写入云盘（MongoDB 或 localdisk，读回校验 MD5）
#   4. 调元数据注册接口 registerMetadata（映射解析、存储复核、拉回工作副本、建记录）
#   5. 调下载接口 download，下载内容与写入内容 MD5 比对
# 测试会在云盘与文件库里留下一条记录（文件名为 selfcheck-时间戳.pdf，页面可见可删）。
import argparse
import sys
import time

sys.path.insert(0, ".")


def main():
    parser = argparse.ArgumentParser(description="form-in 接口一键自检")
    parser.add_argument("--address", required=True, help="form-in 服务地址，如 http://127.0.0.1:6062（ROOT部署，不带应用名前缀）")
    parser.add_argument("--account", required=True, help="推送账号（用户管理里该用户的邮箱）")
    parser.add_argument("--password", required=True, help="推送账号口令")
    parser.add_argument("--source-folder", default="合同", help="来源文件夹名，需已在 filelib.source.folder.map 配置映射（默认：合同）")
    parser.add_argument("--auto-analyze", action="store_true", help="注册后触发 AI 归类与分析（默认不触发，验证归类链路时加此参数）")
    args = parser.parse_args()

    import requests

    from backend import cloud_store
    from backend.login_cipher import encrypt_login_password

    results = []

    def step(name, ok, detail):
        results.append((name, ok, detail))
        print(("[PASS] " if ok else "[FAIL] ") + name + ("  " + detail if detail else ""), flush=True)

    # 第1步：探活
    base = args.address.rstrip("/")
    session = requests.Session()
    try:
        resp = session.post(base + "/api/cdk/efile/filelib/ping", timeout=10)
        step("1 探活ping", resp.status_code == 200, "HTTP " + str(resp.status_code))
    except Exception as e:
        step("1 探活ping", False, str(e))
        print("form-in 不可达，后续步骤终止")
        return

    # 第2步：登录
    login_ok = False
    try:
        cipher = encrypt_login_password(args.password)
        resp = session.post(base + "/api/cdk/efile/cltdenglv/loginByPwd", data={"account": args.account, "password": cipher}, timeout=30)
        body = resp.json()
        login_ok = bool(body.get("success"))
        step("2 登录loginByPwd", login_ok, str(body.get("message")))
    except Exception as e:
        step("2 登录loginByPwd", False, str(e))
    if not login_ok:
        print("登录失败（检查账号是否填邮箱、口令是否正确），后续步骤终止")
        return

    # 第3步：测试PDF写入云盘（复用推送模块的同一套存储写入与读回校验）
    pdf_path = None
    try:
        stamp = time.strftime("%Y%m%d%H%M%S")
        import os
        import tempfile
        pdf_path = os.path.join(tempfile.gettempdir(), "selfcheck-" + stamp + ".pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.7\nselfcheck " + stamp.encode("ascii") + b"\n" + b"x" * 300)
        write_result = cloud_store.write_file(pdf_path)
        step("3 写入云盘并读回校验", bool(write_result.get("ok")), str(write_result.get("message")))
    except Exception as e:
        step("3 写入云盘并读回校验", False, str(e))
    if pdf_path is None or not write_result.get("ok"):
        print("云盘写入失败（检查 url.conf 的 STORE_MODE/MONGO_* 配置与网络），后续步骤终止")
        return

    # 第4步：元数据注册
    import hashlib

    with open(pdf_path, "rb") as f:
        content = f.read()
    local_md5 = hashlib.md5(content).hexdigest()
    register_ok = False
    file_id = ""
    try:
        resp = session.post(base + "/api/cdk/efile/filelib/registerMetadata", data={
            "hash": write_result["hash"],
            "fileName": "selfcheck-" + stamp + ".pdf",
            "totalBytes": str(write_result["size"]),
            "sourceFolder": args.source_folder,
            "autoAnalyze": "true" if args.auto_analyze else "false",
        }, timeout=60)
        body = resp.json()
        register_ok = bool(body.get("success"))
        data_body = body.get("data")
        if isinstance(data_body, dict):
            file_id = str(data_body.get("fileId", ""))
        step("4 元数据注册registerMetadata", register_ok, str(body.get("message")) + " fileId=" + file_id)
    except Exception as e:
        step("4 元数据注册registerMetadata", False, str(e))
    if not register_ok:
        print("注册失败（检查 filelib.source.folder.map 是否配了来源文件夹 " + args.source_folder + "）")
        return

    # 第5步：下载比对
    try:
        resp = session.post(base + "/api/cdk/efile/filelib/download", data={"fileId": file_id}, timeout=60)
        download_md5 = hashlib.md5(resp.content).hexdigest()
        same = resp.status_code == 200 and download_md5 == local_md5
        step("5 下载download并MD5比对", same, "下载" + str(len(resp.content)) + "字节 MD5=" + download_md5 + ("（与写入一致）" if same else "（与写入不一致：" + local_md5 + "）"))
    except Exception as e:
        step("5 下载download并MD5比对", False, str(e))

    # 汇总
    passed = sum(1 for _, ok, _ in results if ok)
    print("=== 自检结果：" + str(passed) + "/" + str(len(results)) + " 步通过 ===", flush=True)
    print("测试记录：云盘 hash=" + write_result["hash"] + "，文件库记录 fileId=" + file_id + "（文件名 selfcheck-...，可在文件库页面删除）", flush=True)


if __name__ == "__main__":
    main()
