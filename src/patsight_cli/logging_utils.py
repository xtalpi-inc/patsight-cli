"""配置 CLI 日志输出，保持 stdout 仅用于机器可读结果。"""

import logging
import sys


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
