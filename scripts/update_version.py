# -*- coding: utf-8 -*-
# xuechong 2026-06-30 版本号自动升级脚本
"""
一键更新项目中所有版本号，防止遗漏。

使用方法：
    python scripts/update_version.py 3.0.02

功能：
1. 自动扫描并更新所有包含版本号的文件
2. 更新 VersionModal.vue 中的版本条目
3. 验证更新结果
"""
import sys
import re
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 版本号匹配模式
VERSION_PATTERNS = {
    # 后端 Python
    "pyproject.toml": [
        (r'^version = "(\d+\.\d+\.\d+)"', 'version = "{new}"'),
    ],
    "backend/__init__.py": [
        (r"^__version__ = '(\d+\.\d+\.\d+)'", "__version__ = '{new}'"),
    ],
    "backend/config.py": [
        (r"^版本: (\d+\.\d+\.\d+)", "版本: {new}"),
    ],
    "backend/app.py": [
        (r'version="(\d+\.\d+\.\d+)"', 'version="{new}"'),
    ],
    "backend/routes/system.py": [
        (r'"version": "(\d+\.\d+\.\d+)"', '"version": "{new}"'),
    ],
    "backend/service_manager.py": [
        # xuechong 2026-09-01 修复版本号同步脚本 锚定窗口标题，避免误改历史注释
        (r'系统 V(\d+\.\d+\.\d+)', '系统 V{new}'),
    ],
    # 前端
    "frontend/package.json": [
        (r'"version": "(\d+\.\d+\.\d+)"', '"version": "{new}"'),
    ],
    "frontend/package-lock.json": [
        # xuechong 2026-09-01 修复版本号同步脚本 只改 root 包 2 处，避免把依赖包 version 一并替换
        # xuechong 2026-09-01 修复版本号同步脚本 \r?\n 兼容 CRLF/LF，避免换行符不匹配
        (r'("name": "DOCSTUDIO-frontend",\r?\n\s*"version": ")\d+\.\d+\.\d+(")', r'\g<1>{new}\g<2>'),
    ],
    "frontend/index.html": [
        (r'V(\d+\.\d+\.\d+)</title>', 'V{new}</title>'),
        (r'content="(\d+\.\d+\.\d+)"', 'content="{new}"'),
    ],
    "frontend/src/pages/LoginPage.vue": [
        (r'V(\d+\.\d+\.\d+)</h2>', 'V{new}</h2>'),
    ],
    "frontend/src/pages/HomePage.vue": [
        (r'>V(\d+\.\d+\.\d+)</span>', '>V{new}</span>'),
    ],
    # xuechong 2026-10-10 研发BUG-0071 三功能页顶栏新增版本徽章（>V3.3.01</span>），
    # 升版时与首页同规则同步，避免漏改
    "frontend/src/pages/ImageToPdfPage.vue": [
        (r'>V(\d+\.\d+\.\d+)</span>', '>V{new}</span>'),
    ],
    "frontend/src/pages/EditPdfPage.vue": [
        (r'>V(\d+\.\d+\.\d+)</span>', '>V{new}</span>'),
    ],
    "frontend/src/pages/DualLayerPdfPage.vue": [
        (r'>V(\d+\.\d+\.\d+)</span>', '>V{new}</span>'),
    ],
    # 文档（项目技能已迁至 .agents/skills，原 CLAUDE.md/.claude 已于 2026-08-17 删除）
    ".agents/skills/ds-project-guide/SKILL.md": [
        (r'当前版本：V(\d+\.\d+\.\d+)', '当前版本：V{new}'),
    ],
}

def update_file(file_path, patterns, new_version):
    """更新单个文件中的版本号"""
    path = PROJECT_ROOT / file_path
    if not path.exists():
        print(f"  SKIP: {file_path} (文件不存在)")
        return False

    # zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能 兼容 Python 3.11：
    # Path.read_text 的 newline 参数是 3.13 才加入的，项目 venv 为 3.11 会直接 TypeError；
    # 改用 open(newline='') 等价实现（各版本通用），语义不变：禁用换行符转换，保留原 LF/CRLF
    with open(path, 'r', encoding='utf-8', newline='') as f:
        content = f.read()
    original = content
    updated = False

    for pattern, replacement in patterns:
        new_content = re.sub(
            pattern,
            replacement.format(new=new_version),
            content,
            flags=re.MULTILINE
        )
        if new_content != content:
            content = new_content
            updated = True

    if updated:
        path.write_text(content, encoding='utf-8', newline='')
        print(f"  OK: {file_path}")
        return True
    else:
        print(f"  SKIP: {file_path} (无需更新)")
        return False

def update_version_modal(new_version):
    """更新 VersionModal.vue 中的版本条目"""
    path = PROJECT_ROOT / "frontend/src/components/VersionModal.vue"
    if not path.exists():
        print(f"  SKIP: VersionModal.vue (文件不存在)")
        return

    # zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能 兼容 Python 3.11
    # （read_text 的 newline 参数 3.13 才有，改用 open(newline='')，保留原换行符语义不变）
    with open(path, 'r', encoding='utf-8', newline='') as f:
        content = f.read()

    # xuechong 2026-09-01 修复版本号同步脚本 幂等：先判重，避免重复运行丢失"当前版本"标记
    if f'<!-- V{new_version} -->' in content:
        print(f"  INFO: V{new_version} 条目已存在，跳过更新")
        return

    # 移除旧版本的 current 标记
    content = re.sub(
        r'<span class="version-tag current">V\d+\.\d+\.\d+</span>',
        lambda m: m.group(0).replace(' current', ''),
        content
    )

    # 移除旧版本的"当前版本"徽标
    content = re.sub(
        r'\s*<span class="version-badge">当前版本</span>',
        '',
        content
    )

    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    # 在版本列表开头添加新版本条目
    new_version_entry = f'''          <!-- V{new_version} -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag current">V{new_version}</span>
              <span class="version-date">{today}</span>
              <span class="version-badge">当前版本</span>
            </div>
            <ul class="version-changes">
              <li>【版本升级】更新至 V{new_version}</li>
            </ul>
          </div>

          '''

    # 在 version-list 开头插入新版本
    content = content.replace(
        '<div class="version-list">\n',
        f'<div class="version-list">\n{new_version_entry}'
    )

    path.write_text(content, encoding='utf-8', newline='')
    print(f"  OK: VersionModal.vue (已添加新版本条目，更新日志需手工补充)")

def verify_version(new_version):
    """验证所有文件的版本号是否已更新"""
    print("\n=== 验证版本号 ===")
    errors = []

    # 检查关键文件（与 self_check.py 的版本一致性清单对齐）
    checks = [
        ("pyproject.toml", f'version = "{new_version}"'),
        ("backend/__init__.py", f"__version__ = '{new_version}'"),
        ("backend/config.py", f"版本: {new_version}"),
        ("backend/app.py", f'version="{new_version}"'),
        ("backend/routes/system.py", f'"version": "{new_version}"'),
        ("backend/service_manager.py", f'V{new_version}'),
        ("frontend/package.json", f'"version": "{new_version}"'),
        ("frontend/index.html", f'V{new_version}'),
        ("frontend/src/pages/LoginPage.vue", f'V{new_version}'),
        ("frontend/src/pages/HomePage.vue", f'V{new_version}'),
        ("tests/test_api.py", 'j["version"] == app.version'),
    ]

    for file_path, expected in checks:
        path = PROJECT_ROOT / file_path
        if not path.exists():
            errors.append(f"{file_path}: 文件不存在")
            continue
        content = path.read_text(encoding='utf-8')
        if expected not in content:
            errors.append(f"{file_path}: 未找到 '{expected}'")
        else:
            print(f"  OK: {file_path}")

    # xuechong 2026-09-01 修复版本号同步脚本 校验 package-lock 仅 root 包为新版本，防止依赖包被污染
    lock_file = PROJECT_ROOT / 'frontend' / 'package-lock.json'
    if lock_file.exists():
        lock_content = lock_file.read_text(encoding='utf-8')
        root_versions = re.findall(
            r'"name": "DOCSTUDIO-frontend",\r?\n\s*"version": "([^"]+)"',
            lock_content
        )
        if len(root_versions) >= 2 and all(v == new_version for v in root_versions):
            print(f"  OK: frontend/package-lock.json (root 包 {len(root_versions)} 处)")
        else:
            errors.append(
                f"frontend/package-lock.json: root 包版本应为 {new_version}，实际 {root_versions}"
            )

    if errors:
        print("\n验证失败:")
        for e in errors:
            print(f"  ERROR: {e}")
        return False

    print("\n验证通过!")
    return True

def main():
    if len(sys.argv) < 2:
        print("使用方法: python scripts/update_version.py <新版本号>")
        print("示例: python scripts/update_version.py 3.0.02")
        sys.exit(1)

    new_version = sys.argv[1]

    # 验证版本号格式
    if not re.match(r'^\d+\.\d+\.\d+$', new_version):
        print(f"错误: 版本号格式不正确 '{new_version}'，应为 X.Y.Z")
        sys.exit(1)

    print(f"=== 更新版本号到 {new_version} ===\n")

    # 更新所有文件
    updated_count = 0
    for file_path, patterns in VERSION_PATTERNS.items():
        if update_file(file_path, patterns, new_version):
            updated_count += 1

    # 更新 VersionModal.vue
    update_version_modal(new_version)

    print(f"\n=== 更新完成: {updated_count} 个文件已更新 ===")

    # 验证
    if not verify_version(new_version):
        sys.exit(1)

    print("\n请执行以下命令构建前端:")
    print("  cd frontend && npm run build")
    print("\n请手工补充以下人工内容:")
    print("  1. backend/config.py 的更新日期与版本说明条目")
    print("  2. frontend/src/components/VersionModal.vue 的实际更新日志")
    print("  3. AGENTS.md 与 docs/生产-某项目-*.md 中的版本记录")

if __name__ == "__main__":
    main()
