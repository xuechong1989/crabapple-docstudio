# -*- coding: utf-8 -*-
# xuechong 2026-07-18 研发BUG-0009-图档扫描-用户隔离机制问题 用户数据隔离模块（重构版）
"""
按 username 隔离所有运行时数据和持久化文件。

使用方式:
    from backend.services.user_scope import get_user_scope
    scope = get_user_scope(username)
    task = scope.upload_tasks[task_id]           # 用户隔离的任务
    scope.upload_dir                              # 用户隔离的上传目录
    scope.save_download_history()                 # 持久化到用户目录

目录结构:
    users/{username}/uploads/{task_id}/
    users/{username}/outputs/{task_id}/
    users/{username}/history/download_history.json
    users/{username}/history/upload_history.json
    users/{username}/history/edit_pdf_history.json
    users/{username}/history/dual_layer_history.json
    users/{username}/tasks.json
    users/{username}/edit_pdf/{task_id}/
    users/{username}/dual_layer/
"""
import json
import os as _os_module
import re as _re_module
import shutil as _shutil_module
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.services.logging_service import log_info
from backend.services.path_service import USERS_ROOT

# xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# 绝对路径识别：Windows 盘符（D:\ / D:/）或 POSIX 根（/data/...）
_ABS_PATH_RE = _re_module.compile(r'^([A-Za-z]:[\\/]|/)')
# users 锚点段：路径中 /users/{username}/ 起的相对后缀，是重映射的唯一依据
_USERS_ANCHOR_RE = _re_module.compile(r'/users/([^/]+)/')


# xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# 单值重映射：前缀非当前数据根但含 users 锚点段 → 换前缀；候选路径必须真实存在才替换（宁漏勿错）
def _remap_legacy_path(value: str, users_root: Path) -> Optional[str]:
    if not isinstance(value, str) or not _ABS_PATH_RE.match(value):
        return None
    norm = value.replace('\\', '/')
    m = _USERS_ANCHOR_RE.search(norm)
    if not m:
        return None
    current_root = str(users_root.parent).replace('\\', '/')
    if norm.lower().startswith(current_root.lower() + '/'):
        return None  # 已是当前前缀的健康路径
    suffix = norm[m.start():].lstrip('/')
    candidate = users_root.parent / suffix
    if not candidate.exists():
        return None  # 候选路径不存在（文件真被删）→ 保留原值，绝不臆造
    return str(candidate)


# xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# 递归重映射 dict/list 中所有旧前缀绝对路径，返回 (新对象, 替换次数)；users_root 参数化便于单测注入
def _remap_legacy_paths(obj, users_root: Path = None) -> Tuple[object, int]:
    if users_root is None:
        users_root = USERS_ROOT
    count = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            nv, c = _remap_legacy_paths(v, users_root)
            if c:
                obj[k] = nv
                count += c
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            nv, c = _remap_legacy_paths(v, users_root)
            if c:
                obj[i] = nv
                count += c
    elif isinstance(obj, str):
        nv = _remap_legacy_path(obj, users_root)
        if nv is not None and nv != obj:
            return nv, 1
    return obj, count


class UserScope:
    """单个用户的隔离数据容器"""

    # xuechong 2026-07-18 初始化用户 scope
    def __init__(self, username: str) -> None:
        self.username: str = username
        # xuechong 2026-07-18 用户根目录
        self.user_root: Path = USERS_ROOT / username

        # xuechong 2026-07-18 用户隔离的目录
        self.upload_dir: Path = self.user_root / "uploads"
        self.output_dir: Path = self.user_root / "outputs"
        self.source_dir: Path = self.user_root / "original"
        self.target_dir: Path = self.user_root / "target"
        self.history_dir: Path = self.user_root / "history"
        self.edit_pdf_dir: Path = self.user_root / "edit_pdf"  # 预留：工作文件暂存 TEMP_DIR/edit_pdf/
        self.dual_layer_dir: Path = self.user_root / "dual_layer"
        self.tasks_file: Path = self.user_root / "tasks.json"

        # xuechong 2026-07-18 确保目录存在
        for d in [self.upload_dir, self.output_dir, self.source_dir,
                  self.target_dir, self.history_dir, self.edit_pdf_dir,
                  self.dual_layer_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # xuechong 2026-07-18 用户隔离的任务字典和取消标志
        self.upload_tasks: dict = {}
        self.edit_pdf_tasks: dict = {}
        # xuechong 2026-07-20 研发BUG-0009 BUG3: 批量转换任务迁移到 scope（用户隔离）
        self.batch_tasks: dict = {}
        self.tasks_cancel_flags: dict = {}
        self._lock: threading.Lock = threading.Lock()

        # xuechong 2026-07-18 双层PDF处理状态（per-user）
        self._dual_layer_processing: set = set()
        self._dual_layer_lock: threading.Lock = threading.Lock()
        self.dual_layer_progress: dict = {}
        self.dual_layer_progress_lock: threading.Lock = threading.Lock()

        # xuechong 2026-07-18 从文件加载历史记录
        self.download_history: List[dict] = self._load_json("download_history.json")
        self.upload_history: List[dict] = self._load_json("upload_history.json")
        self.edit_pdf_history: List[dict] = self._load_json("edit_pdf_history.json")
        self.dual_layer_history: List[dict] = self._load_json("dual_layer_history.json")

        # xuechong 2026-07-18 从文件加载任务状态
        self.load_tasks()

        log_info(f"[用户隔离] user={username} 已初始化 "
                 f"(下载:{len(self.download_history)} 上传:{len(self.upload_history)} "
                 f"编辑:{len(self.edit_pdf_history)} 双层:{len(self.dual_layer_history)} "
                 f"任务:{len(self.upload_tasks)})")

    # ---- JSON 文件读写 ----

    # xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
    # 加载后自愈：重映射旧前缀绝对路径并回写（回写前备份 .bak-migration，已存在则保留最早原始备份）
    def _remap_and_rewrite(self, fp: Path, data, label: str):
        new_data, n = _remap_legacy_paths(data)
        if n > 0:
            bak = Path(str(fp) + '.bak-migration')
            if not bak.exists() and fp.exists():
                _shutil_module.copy2(fp, bak)
            try:
                with open(fp, 'w', encoding='utf-8') as f:
                    json.dump(new_data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    _os_module.fsync(f.fileno())
            except Exception as e:
                log_info(f"[路径自愈] {label} 回写失败: {e}")
                return new_data  # 内存态已修复，落盘失败不影响本次运行
            log_info(f"[路径自愈] {label} 重映射 {n} 处旧前缀路径，已备份并回写")
        return new_data

    # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
    # 数据文件损坏时立即备份原文件再继续，防止后续保存覆盖导致原数据彻底丢失；
    # 备份命名 {原文件名}.corrupt-{时间戳}，用户可手工恢复
    def _backup_corrupt(self, fp: Path, filename: str, reason: str) -> None:
        try:
            from datetime import datetime as _dt
            bak = fp.with_name(fp.name + ".corrupt-" + _dt.now().strftime("%Y%m%d-%H%M%S"))
            _shutil_module.copy2(fp, bak)
            log_info(f"[用户隔离][错误] 数据文件损坏：{fp}")
            log_info(f"[用户隔离][错误] 原因：{reason}")
            log_info(f"[用户隔离][错误] 后果：{filename} 相关记录本次将以空白状态启动（不会自动清空，仅本次不显示）")
            log_info(f"[用户隔离][错误] 原文件已备份至：{bak}，如需找回历史数据请检查该文件（JSON格式，可手工修复后还原）")
        except Exception as backup_e:
            log_info(f"[用户隔离][错误] 数据文件 {filename} 损坏且备份失败：{backup_e}，请人工检查 {fp}")

    # xuechong 2026-07-18 从 history 目录加载 JSON 文件
    def _load_json(self, filename: str) -> list:
        fp: Path = self.history_dir / filename
        if fp.exists():
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
                # 数据目录改名/迁移后，历史记录里的旧前缀绝对路径在加载时自愈
                return self._remap_and_rewrite(fp, data, filename)
            except Exception as e:
                # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
                # 损坏先备份再降级为空列表，日志醒目化（原实现仅一行日志，用户历史"消失"无感知）
                self._backup_corrupt(fp, filename, str(e))
        return []

    # xuechong 2026-07-18 保存 JSON 文件到 history 目录
    def _save_json(self, filename: str, data: list) -> None:
        fp: Path = self.history_dir / filename
        try:
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                _os_module.fsync(f.fileno())
        except Exception as e:
            # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
            # 保存失败醒目化：明确告知数据未落盘的后果与排查方向（磁盘空间/目录权限）
            log_info(f"[用户隔离][错误] 保存 {filename} 失败：{e}")
            log_info(f"[用户隔离][错误] 后果：本次新增的该类历史记录重启服务后将丢失，请检查磁盘空间与目录写权限：{self.history_dir}")

    # ---- 持久化方法 ----

    # xuechong 2026-07-18 保存下载历史
    def save_download_history(self) -> None:
        self._save_json("download_history.json", self.download_history)

    # xuechong 2026-07-18 保存上传历史
    def save_upload_history(self) -> None:
        self._save_json("upload_history.json", self.upload_history)

    # xuechong 2026-07-18 保存编辑PDF历史
    def save_edit_pdf_history(self) -> None:
        self._save_json("edit_pdf_history.json", self.edit_pdf_history)

    # xuechong 2026-07-18 保存双层PDF历史
    def save_dual_layer_history(self) -> None:
        self._save_json("dual_layer_history.json", self.dual_layer_history)

    # xuechong 2026-10-06 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程
    # 补历史记录缺失的 source 字段（form-in 演示链标记）：上传/下载历史在 2026-10-06 前落盘的
    # 记录没有 source 字段，嵌入页会话过滤会把这些演示链记录误滤成空——读取列表时按 task_id
    # 回查任务的 source 补齐并落盘一次；任务已删除的记录补空串（维持"嵌入无历史数据"口径）
    def heal_history_sources(self) -> None:
        healed_download = False
        for record in self.download_history:
            if record.get("source") is None:
                task = self.upload_tasks.get(record.get("task_id"))
                record["source"] = (task.get("source") or "") if task else ""
                healed_download = True
        healed_upload = False
        for record in self.upload_history:
            if record.get("source") is None:
                task = self.upload_tasks.get(record.get("task_id"))
                record["source"] = (task.get("source") or "") if task else ""
                healed_upload = True
        if healed_download:
            self.save_download_history()
        if healed_upload:
            self.save_upload_history()

    # ---- 任务持久化 ----

    # xuechong 2026-07-18 保存任务状态到 users/{username}/tasks.json
    def save_tasks(self) -> None:
        try:
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                json.dump(self.upload_tasks, f, ensure_ascii=False, indent=2)
                f.flush()
                _os_module.fsync(f.fileno())
        except Exception as e:
            log_info(f"[用户隔离] 保存任务状态失败: {e}")

    # xuechong 2026-07-18 从 users/{username}/tasks.json 加载任务状态
    def load_tasks(self) -> None:
        if self.tasks_file.exists():
            try:
                with open(self.tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    log_info(f"[用户隔离] 任务文件格式错误，期望 dict，得到 {type(data).__name__}")
                    return
                # xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
                # 数据目录改名/迁移后，任务里的旧前缀绝对路径（upload_dir 等）在加载时自愈
                data = self._remap_and_rewrite(self.tasks_file, data, "tasks.json")
                for task_id, task in data.items():
                    # xuechong 2026-07-18 标记中断的任务
                    if task.get("status") == "processing":
                        task["status"] = "interrupted"
                        task["message"] = "服务重启，任务被中断"
                    # xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
                    # 修图状态同步降级：持久化的 clean_status=processing 只可能属于已死进程
                    # （服务刚启动不可能有修图在跑），降级为 interrupted 供断点续跑判定
                    if task.get("clean_status") == "processing":
                        task["clean_status"] = "interrupted"
                        task["clean_message"] = "服务重启，修图被中断（可断点续跑）"
                    self.upload_tasks[task_id] = task
                log_info(f"[用户隔离] 已恢复 {len(data)} 个任务")
            except Exception as e:
                # xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性整改
                # 任务文件损坏：备份+醒目日志（断点续跑状态静默丢失用户无感知）
                self._backup_corrupt(self.tasks_file, "tasks.json", str(e))

    # ---- 任务操作方法 ----

    # xuechong 2026-07-18 获取任务
    def get_task(self, task_id: str) -> Optional[dict]:
        return self.upload_tasks.get(task_id)

    # xuechong 2026-07-18 取消任务
    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self.upload_tasks.get(task_id)
            if task and task.get("status") in ("processing", "uploaded"):
                self.tasks_cancel_flags[task_id] = True
                task["message"] = "正在取消..."
                return True
        return False

    # xuechong 2026-07-18 检查任务是否已取消
    def is_cancelled(self, task_id: str) -> bool:
        return self.tasks_cancel_flags.get(task_id, False)

    # xuechong 2026-07-18 清除取消标志
    def clear_cancel_flag(self, task_id: str) -> None:
        self.tasks_cancel_flags.pop(task_id, None)

    # ---- 双层PDF进度操作 ----

    # xuechong 2026-07-18 设置双层PDF转换进度
    def set_dual_layer_progress(self, key: str, progress: dict) -> None:
        with self.dual_layer_progress_lock:
            self.dual_layer_progress[key] = progress

    # xuechong 2026-07-18 获取双层PDF转换进度
    def get_dual_layer_progress(self, key: str) -> Optional[dict]:
        with self.dual_layer_progress_lock:
            return self.dual_layer_progress.get(key)

    # xuechong 2026-07-18 检查双层PDF是否正在处理
    def is_dual_layer_processing(self, key: str) -> bool:
        with self._dual_layer_lock:
            return key in self._dual_layer_processing

    # xuechong 2026-07-18 设置双层PDF处理状态
    def set_dual_layer_processing(self, key: str, value: bool) -> None:
        with self._dual_layer_lock:
            if value:
                self._dual_layer_processing.add(key)
            else:
                self._dual_layer_processing.discard(key)


# xuechong 2026-07-18 全局用户作用域缓存
_user_scopes: Dict[str, UserScope] = {}
_scopes_lock: threading.Lock = threading.Lock()


# xuechong 2026-07-18 获取或创建用户的隔离数据容器
def get_user_scope(username: str) -> UserScope:
    with _scopes_lock:
        if username not in _user_scopes:
            _user_scopes[username] = UserScope(username)
        return _user_scopes[username]


# xuechong 2026-07-18 获取所有活跃用户名
def get_all_usernames() -> List[str]:
    with _scopes_lock:
        return list(_user_scopes.keys())


# xuechong 2026-07-18 移除用户作用域
def remove_user_scope(username: str) -> None:
    with _scopes_lock:
        _user_scopes.pop(username, None)
