# -*- coding: utf-8 -*-
# xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化
# REQ-001 持久化路径自愈单元测试（tmp_path 隔离，不触碰真实数据目录）
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services import user_scope


def _make_env(tmp_path, monkeypatch):
    """构造临时数据目录：new-data/users/alice/uploads/t1 真实存在；返回 (旧前缀根, 当前 users_root)"""
    users_root = tmp_path / "new-data" / "users"
    task_dir = users_root / "alice" / "uploads" / "t1"
    task_dir.mkdir(parents=True)
    monkeypatch.setattr(user_scope, "USERS_ROOT", users_root)
    return tmp_path / "old-data", users_root


def test_remap_old_prefix_to_current(tmp_path, monkeypatch):
    """旧前缀 + users 锚点 + 候选存在 → 重映射到当前数据根"""
    old_root, users_root = _make_env(tmp_path, monkeypatch)
    old_val = str(old_root) + "\\users\\alice\\uploads\\t1"
    out, n = user_scope._remap_legacy_paths({"t1": {"upload_dir": old_val}}, users_root)
    assert n == 1
    assert out["t1"]["upload_dir"] == str(users_root / "alice" / "uploads" / "t1")


def test_healthy_path_untouched(tmp_path, monkeypatch):
    """已是当前前缀的健康路径 → 零替换，字符串原样"""
    _, users_root = _make_env(tmp_path, monkeypatch)
    healthy = str(users_root / "alice" / "uploads" / "t1")
    out, n = user_scope._remap_legacy_paths({"t1": {"upload_dir": healthy}}, users_root)
    assert n == 0
    assert out["t1"]["upload_dir"] == healthy


def test_missing_candidate_untouched(tmp_path, monkeypatch):
    """候选路径不存在（文件真被删）→ 保留原值，绝不臆造"""
    old_root, users_root = _make_env(tmp_path, monkeypatch)
    old_val = str(old_root) + "\\users\\alice\\uploads\\deleted-task"
    out, n = user_scope._remap_legacy_paths({"x": {"upload_dir": old_val}}, users_root)
    assert n == 0
    assert out["x"]["upload_dir"] == old_val


def test_no_users_anchor_untouched(tmp_path, monkeypatch):
    """不含 users 锚点段的绝对路径（如外部路径）→ 不动"""
    _, users_root = _make_env(tmp_path, monkeypatch)
    out, n = user_scope._remap_legacy_paths({"p": "D:\\external\\share\\doc.pdf"}, users_root)
    assert n == 0
    assert out["p"] == "D:\\external\\share\\doc.pdf"


def test_nested_list_structure(tmp_path, monkeypatch):
    """list 嵌套 dict 中的路径同样被重映射"""
    old_root, users_root = _make_env(tmp_path, monkeypatch)
    old_val = str(old_root) + "\\users\\alice\\uploads\\t1"
    data = {"items": [{"path": old_val}, {"path": "relative/path.png"}]}
    out, n = user_scope._remap_legacy_paths(data, users_root)
    assert n == 1
    assert out["items"][0]["path"] == str(users_root / "alice" / "uploads" / "t1")
    assert out["items"][1]["path"] == "relative/path.png"


def test_load_tasks_selfheal_and_rewrite(tmp_path, monkeypatch):
    """tasks.json 含旧前缀 → UserScope 初始化后内存与磁盘均已自愈，且生成备份"""
    old_root, users_root = _make_env(tmp_path, monkeypatch)
    old_val = str(old_root) + "\\users\\alice\\uploads\\t1"
    alice_root = users_root / "alice"
    alice_root.mkdir(parents=True, exist_ok=True)
    tasks_file = alice_root / "tasks.json"
    tasks_file.write_text(json.dumps({"t1": {"upload_dir": old_val, "status": "uploaded"}}),
                          encoding="utf-8")

    scope = user_scope.UserScope("alice")
    expected = str(users_root / "alice" / "uploads" / "t1")
    assert scope.upload_tasks["t1"]["upload_dir"] == expected
    # 磁盘已回写为自愈后的内容
    assert json.loads(tasks_file.read_text(encoding="utf-8"))["t1"]["upload_dir"] == expected
    # 备份存在且保留原始旧路径
    bak = Path(str(tasks_file) + ".bak-migration")
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8"))["t1"]["upload_dir"] == old_val


def test_load_history_selfheal(tmp_path, monkeypatch):
    """history/download_history.json 含旧前缀 → 加载后自愈并回写"""
    old_root, users_root = _make_env(tmp_path, monkeypatch)
    old_val = str(old_root) + "\\users\\alice\\outputs\\t1\\out.pdf"
    out_dir = users_root / "alice" / "outputs" / "t1"
    out_dir.mkdir(parents=True)
    (out_dir / "out.pdf").write_bytes(b"%PDF-1.4")  # 候选路径必须真实存在才会被重映射
    hist_dir = users_root / "alice" / "history"
    hist_dir.mkdir(parents=True)
    (hist_dir / "download_history.json").write_text(
        json.dumps([{"task_id": "t1", "file_path": old_val}]), encoding="utf-8")

    scope = user_scope.UserScope("alice")
    assert scope.download_history[0]["file_path"] == str(users_root / "alice" / "outputs" / "t1" / "out.pdf")
    assert Path(str(hist_dir / "download_history.json") + ".bak-migration").exists()


def test_normal_env_zero_rewrite(tmp_path, monkeypatch):
    """正常环境（无旧前缀）→ 不回写不备份，文件内容逐字节不变"""
    _, users_root = _make_env(tmp_path, monkeypatch)
    alice_root = users_root / "alice"
    alice_root.mkdir(parents=True, exist_ok=True)
    healthy = str(users_root / "alice" / "uploads" / "t1")
    original = json.dumps({"t1": {"upload_dir": healthy}}, ensure_ascii=False, indent=2)
    tasks_file = alice_root / "tasks.json"
    tasks_file.write_text(original, encoding="utf-8")

    user_scope.UserScope("alice")
    assert tasks_file.read_text(encoding="utf-8") == original
    assert not Path(str(tasks_file) + ".bak-migration").exists()
