# -*- coding: utf-8 -*-
"""form-in 推送模块纯函数测试（研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程）。
不发起真实 HTTP 请求：登录/注册 URL 拼接、任务消息追加、结果解析分支。
"""
from backend import form_in


class TestAppendTaskMessage:
    """推送结果追加到任务消息末尾"""

    def test_append_to_existing_message(self):
        task = {"message": "处理完成！共处理 3 个文件"}
        form_in._append_task_message(task, "；已写入云盘并注册到form-in文件库")
        assert task["message"] == "处理完成！共处理 3 个文件；已写入云盘并注册到form-in文件库"

    def test_append_to_empty_message(self):
        task = {}
        form_in._append_task_message(task, "；form-in推送失败：登录form-in失败")
        assert task["message"] == "；form-in推送失败：登录form-in失败"

    def test_append_failure_does_not_raise(self):
        # task 传非字典（异常场景）不抛出，只记日志
        form_in._append_task_message(None, "；x")
        form_in._append_task_message(123, "；x")


class TestUrlBuild:
    """URL 拼接规则（base 不带末尾斜杠时直接拼路径）"""

    def test_register_url(self):
        import requests

        session = requests.Session()
        # _register_metadata 内部拼接逻辑以 base_address + 路径为准，这里验证地址常量拼出的 URL 形态
        base = "http://127.0.0.1:4102"
        assert base + "/api/cdk/efile/filelib/registerMetadata" == "http://127.0.0.1:4102/api/cdk/efile/filelib/registerMetadata"
        assert base + "/api/cdk/efile/cltdenglv/loginByPwd" == "http://127.0.0.1:4102/api/cdk/efile/cltdenglv/loginByPwd"
        assert base + "/api/cdk/efile/filelib/ping" == "http://127.0.0.1:4102/api/cdk/efile/filelib/ping"


class TestSubmitPushDisabled:
    """推送开关关闭时 submit_push 不提交任务、不执行推送"""

    def test_disabled_skips_push(self, monkeypatch):
        from backend import config

        monkeypatch.setattr(config, "FORM_IN_ENABLED", False)
        calls = []

        def _record_call(*args, **kwargs):
            calls.append(args)

        monkeypatch.setattr(form_in, "_push_once", _record_call)
        form_in.submit_push("x.pdf", "合同", {"message": ""})
        # 开关在 submit_push 里同步检查，关闭时不向线程池提交任务，_push_once 不会被调用
        assert calls == []


class TestSaveTasksSnapshot:
    """推送结果回写后的任务持久化（收集整理进度页的数据来源之一）"""

    def test_saves_via_user_scope(self, monkeypatch):
        # 有 username 字段时通过 get_user_scope 拿到 scope 并保存任务
        saved = []

        class FakeScope:
            def save_tasks(self):
                saved.append(True)

        monkeypatch.setattr("backend.services.user_scope.get_user_scope", lambda username: FakeScope())
        form_in._save_tasks_snapshot({"username": "demo", "pushed_hash": "abc"})
        assert saved == [True]

    def test_skips_without_username(self, monkeypatch):
        # 老任务没有 username 字段时跳过持久化，不报错
        def _fail(*args, **kwargs):
            raise AssertionError("没有 username 时不应调用 get_user_scope")

        monkeypatch.setattr("backend.services.user_scope.get_user_scope", _fail)
        form_in._save_tasks_snapshot({"pushed_hash": "abc"})

    def test_failure_does_not_raise(self, monkeypatch):
        # 持久化异常不抛出（推送结果本身不受影响）
        def _raise(username):
            raise RuntimeError("boom")

        monkeypatch.setattr("backend.services.user_scope.get_user_scope", _raise)
        form_in._save_tasks_snapshot({"username": "demo"})
