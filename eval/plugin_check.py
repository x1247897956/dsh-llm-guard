"""DSH 插件静态校验（``make plugin-check``）。

校验 ``plugin/llm-guard.mjs`` 是否仍然满足 DSH 单文件插件的契约：
- 文件存在且是 ESM（含 ``export``）
- 导出了 ``name`` / ``apply``（``defineTool`` 插件的最小契约）
- 工具名与参数名与 README / 文档一致
- ``execute`` 里有超时/取消传递（``exec.signal``）与错误处理（非 2xx 抛错）

这不是单元测试，而是防止插件与文档漂移的廉价护栏。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN = REPO_ROOT / "plugin" / "llm-guard.mjs"

CHECKS: list[tuple[str, str]] = [
    ("导出 name", r"export\s*\{[^}]*\bname\b"),
    ("导出 apply", r"export\s*\{[^}]*\bapply\b"),
    ("使用 defineTool", r"defineTool\("),
    ("工具名 llm_guard_scan", r'name:\s*"llm_guard_scan"'),
    ("参数 text", r"text:\s*\{"),
    ("输出 schema", r"schema:\s*\{"),
    ("渲染函数 render", r"render\s*\("),
    ("取消信号传递", r"exec\.signal"),
    ("非 2xx 错误处理", r"if\s*\(!resp\.ok\)"),
    ("调用 /scan", r"/scan"),
]


def main() -> int:
    if not PLUGIN.exists():
        print(f"FAIL: 插件文件不存在：{PLUGIN}")
        return 1

    source = PLUGIN.read_text(encoding="utf-8")
    failures: list[str] = []
    for label, pattern in CHECKS:
        ok = re.search(pattern, source) is not None
        print(f"{'PASS' if ok else 'FAIL'}: {label}")
        if not ok:
            failures.append(label)

    # 硬编码密钥检查（插件是公开文件，绝不能带 key）
    if re.search(r"(sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})", source):
        print("FAIL: 检测到疑似硬编码密钥")
        failures.append("hardcoded-credential")
    else:
        print("PASS: 无硬编码密钥")

    if failures:
        print(f"\n插件校验失败：{failures}")
        return 1
    print("\n插件校验通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
