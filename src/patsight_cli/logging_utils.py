"""配置 CLI 日志输出，并保证 stdout 以 UTF-8 写出机器可读结果。"""

import logging
import sys


def configure_stdout_utf8() -> None:
    """描述：将 stdout 重配置为 UTF-8，避免 Windows 控制台默认编码破坏 JSON。"""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")


def setup_logging(verbose: bool = False) -> None:
    """关键参数：(verbose: bool)
    返回值：None
    描述：根据 verbose 开关配置日志级别，并将日志写入 stderr。
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,
    )
