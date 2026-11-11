"""安全卫生检查：源码与测试不得出现疑似真实云密钥的字面量。"""

from pathlib import Path

# 常见云厂商 AccessKeyId 前缀；任何出现都视为泄漏
SUSPICIOUS_PREFIXES = ("LTAI", "AKID", "AKLT", "ASIA", "AKTP")


def test_no_realistic_key_literals():
    root = Path(__file__).resolve().parent.parent
    self_path = Path(__file__).resolve()
    offenders: list[str] = []
    for base in (root / "src", root / "tests"):
        for path in sorted(base.rglob("*.py")):
            if path == self_path:
                continue  # 跳过本文件（前缀常量定义在此）
            text = path.read_text(encoding="utf-8")
            for prefix in SUSPICIOUS_PREFIXES:
                if prefix in text:
                    offenders.append(f"{path.name}:{prefix}")
    assert not offenders, f"疑似真实密钥字面量，请改用 demo-ak-**** 占位：{offenders}"
