"""``python -m service`` 启动检测服务（等价于 Makefile 的 ``make run``）。"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "service.main:app",
        host=os.environ.get("LLM_GUARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("LLM_GUARD_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
