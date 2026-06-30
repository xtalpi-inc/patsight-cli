"""验证 patsight-cli 文档承诺的离线 CLI 行为。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from patsight_cli.cli.main import load_payload, parse_json_or_text


def test_parse_json_or_text_keeps_plain_text() -> None:
    """
    参数：无
    返回值：None
    描述：验证 CLI 能区分 JSON 字符串和普通文本参数。
    """
    assert parse_json_or_text('{"job_id": "123"}') == {"job_id": "123"}
    assert parse_json_or_text("plain-value") == "plain-value"
    assert parse_json_or_text(None) is None


def test_load_payload_builds_default_submit_payload() -> None:
    """
    参数：无
    返回值：None
    描述：验证 PDF 提交参数默认生成 structureAndActivity 任务类型。
    """
    args = argparse.Namespace(
        payload=None,
        payload_file=None,
        pdf_path="C:/PatSight/examples/demo.pdf",
        action=None,
        job_type=None,
        folder_id=12,
    )

    assert load_payload(args) == {
        "pdf_path": "C:/PatSight/examples/demo.pdf",
        "job_type": "structureAndActivity",
        "folder_id": 12,
    }


def test_load_payload_action_overrides_job_type() -> None:
    """
    参数：无
    返回值：None
    描述：验证兼容参数 action 会覆盖 job_type。
    """
    args = argparse.Namespace(
        payload=None,
        payload_file=None,
        pdf_path="demo.pdf",
        action="1",
        job_type="structureAndActivity",
        folder_id=None,
    )

    assert load_payload(args) == {"pdf_path": "demo.pdf", "action": "1"}


def test_cli_clients_lists_patsight_backend() -> None:
    """
    参数：无
    返回值：None
    描述：验证 clients 命令可离线列出 patsight 后端。
    """
    completed = subprocess.run(
        [sys.executable, "-m", "patsight_cli.cli.main", "clients"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {"clients": ["patsight"]}


def test_cli_report_from_json_generates_html(tmp_path: Path) -> None:
    """
    参数：(tmp_path: Path)
    返回值：None
    描述：验证 report --from-json 能从本地结果文件生成 HTML。
    """
    source_file = tmp_path / "result.json"
    output_file = tmp_path / "report.html"
    source_file.write_text(
        json.dumps(
            {
                "result": {
                    "job_id": "job-003",
                    "filename": "demo.pdf",
                    "status": "done",
                    "job_type": "reaction",
                    "statistics_info": "products: 4",
                }
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "patsight_cli.cli.main",
            "report",
            "--from-json",
            str(source_file),
            "-o",
            str(output_file),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout)["ok"] is True
    assert "reaction job completed successfully" in output_file.read_text(encoding="utf-8")
