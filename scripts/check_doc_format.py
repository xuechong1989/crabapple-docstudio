# -*- coding: utf-8 -*-
# xuechong 2026-10-13 研发需求-0179-图档扫描-3.4.00-发行版安装包文件安全与系统权限注册机制
# Markdown 文档格式断言工具：按项目 Markdown 文档规范逐条检查（H1唯一+元信息块、
# ## N 编号连续、H2 间 --- 分隔、表头分隔行、连续空行、末尾空行），0 问题退出码 0。
# 用法：python scripts/check_doc_format.py <文件1.md> <文件2.md> ...
# 交付前必须把本次任务产出的全部 .md（含随手写的 README/说明）都扫一遍
import re
import sys
from pathlib import Path


# xuechong 2026-10-13 研发需求-0179-图档扫描-3.4.00-发行版安装包文件安全与系统权限注册机制
# 检查单个文档，返回问题列表（空列表=合规）
def check_doc(path: Path) -> list:
    problems = []
    lines = path.read_text(encoding="utf-8").split("\n")
    name = path.name

    # 规则类文件（SKILL frontmatter 式、AGENTS.md 条款式）自有格式体系，整体豁免格式断言
    if name.endswith("SKILL.md") or name == "AGENTS.md":
        return problems

    # 1. H1 唯一
    h1 = [i for i, l in enumerate(lines) if l.startswith("# ")]
    if len(h1) != 1:
        problems.append(f"{name}: H1 数量 {len(h1)}（应为1）")
        return problems

    # 2. 元信息块：H1 后紧跟 > 引用块
    j = h1[0] + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j >= len(lines) or not lines[j].startswith(">"):
        problems.append(f"{name}: H1 后缺元信息引用块")

    # 3. H2 阿拉拉数字编号连续（运维须知等模板的"附录 A/B"为法定章节名，豁免）
    h2_nums = []
    for l in lines:
        m = re.match(r"^## (\d+) ", l)
        if m:
            h2_nums.append(int(m.group(1)))
        elif l.startswith("## ") and not l.startswith("## 附录"):
            problems.append(f"{name}: H2 缺阿拉伯编号: {l[:30]}")
    if h2_nums and h2_nums != list(range(1, len(h2_nums) + 1)):
        problems.append(f"{name}: H2 编号不连续: {h2_nums}")

    # 4. H2 之间 --- 分隔（每个 H2 前最近非空行应为 ---）
    for i, l in enumerate(lines):
        if l.startswith("## "):
            j = i - 1
            while j >= 0 and lines[j].strip() == "":
                j -= 1
            if j < 0 or lines[j].strip() != "---":
                problems.append(f"{name}: 第{i+1}行 H2 前缺 --- 分隔: {l[:26]}")

    # 5. 表头分隔行：每组连续 | 行的第一行后必须是 |--- 分隔行
    in_table = False
    for i, l in enumerate(lines):
        row = l.strip().startswith("|")
        if row and not in_table and (i + 1 >= len(lines) or "---" not in lines[i + 1]):
            problems.append(f"{name}: 第{i+1}行表头后缺分隔行")
        in_table = row

    # 6. 连续空行 > 1 与文件末尾多余空行
    blank = 0
    for i, l in enumerate(lines):
        blank = blank + 1 if l.strip() == "" else 0
        if blank > 1:
            problems.append(f"{name}: 第{i+1}行连续空行超过1")
    if len(lines) >= 2 and lines[-1] == "" and lines[-2] == "":
        problems.append(f"{name}: 文件末尾多余空行")

    return problems


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/check_doc_format.py <文件1.md> <文件2.md> ...")
        print("把本次任务产出的全部 .md 传进来（含 README、说明文件），禁止只查主文档")
        return 2
    total = 0
    for arg in sys.argv[1:]:
        problems = check_doc(Path(arg))
        for p in problems:
            print(" -", p)
            total += 1
    print(f"检查文档 {len(sys.argv) - 1} 份，发现问题 {total} 条")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
