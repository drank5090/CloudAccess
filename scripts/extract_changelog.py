"""从 CHANGELOG.md 提取指定版本的更新说明（供 CI Release 使用）。

用法：python scripts/extract_changelog.py vX.Y.Z
"""

from __future__ import annotations

import re
import sys


def extract(changelog: str, tag: str) -> str:
    version = tag.removeprefix("v")
    pattern = re.compile(rf"^## \[{re.escape(version)}\]( - \d{{4}}-\d{{2}}-\d{{2}})?\s*$", re.M)
    match = pattern.search(changelog)
    if match is None:
        raise SystemExit(f"CHANGELOG.md 中找不到版本 {version} 的段落，请在发布前补全")
    start = match.end()
    nxt = re.search(r"^## ", changelog[start:], re.M)
    section = changelog[start : start + nxt.start()] if nxt else changelog[start:]
    lines = [
        line
        for line in section.strip().splitlines()
        if not re.match(r"^\[[^\]]+\]:\s*\S+", line)  # 去掉文末链接引用定义
    ]
    return "\n".join(lines).strip()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    tag = sys.argv[1]
    with open("CHANGELOG.md", encoding="utf-8") as f:
        changelog = f.read()
    print(extract(changelog, tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
