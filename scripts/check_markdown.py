"""检查测试报告的基础 Markdown 结构。"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """参数：无 返回值：int 描述：执行简单 Markdown 结构检查。"""
    path = Path("TEST_REPORT.md")
    lines = path.read_text(encoding="utf-8").splitlines()
    errors: list[str] = []
    fence_count = sum(1 for line in lines if line.startswith("```"))
    if fence_count % 2 != 0:
        errors.append("代码块围栏数量不是偶数。")

    if not lines or not lines[0].startswith("# "):
        errors.append("首行不是一级标题。")

    previous_heading = 0
    for index, line in enumerate(lines, start=1):
        if not line.startswith("#"):
            continue
        marker = line.split(" ", 1)[0]
        if set(marker) != {"#"}:
            continue
        level = len(marker)
        if previous_heading and level > previous_heading + 1:
            errors.append(f"第 {index} 行标题跳级：{line}")
        previous_heading = level

    for index, line in enumerate(lines, start=1):
        if line.startswith("|") and index < len(lines):
            next_line = lines[index]
            if next_line.startswith("|") and "---" in next_line:
                if index == 1 or lines[index - 2].strip():
                    errors.append(f"第 {index} 行表格前缺少空行。")

    if errors:
        print("\n".join(errors))
        return 1
    print("Markdown check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
