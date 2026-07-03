"""验证 V2.26 二期专利备注 CLI 与 client 契约。"""

from __future__ import annotations

import argparse
import importlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from patsight_cli.clients.patsight import PatSightClient
from patsight_cli.exceptions import ClientError

cli_main = importlib.import_module("patsight_cli.cli.main")


class FakeJsonResponse:
    """关键参数：(payload: dict[str, Any])
    返回值：FakeJsonResponse
    描述：提供最小 JSON 响应对象用于 client 契约测试。
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        """关键参数：无
        返回值：dict[str, Any]
        描述：返回预置 JSON 响应。
        """
        return self.payload


class FakePatSightClient:
    """关键参数：无
    返回值：FakePatSightClient
    描述：模拟 PatSight client 以验证 CLI handler 串联逻辑。
    """

    client_type = "patsight"

    def __init__(self) -> None:
        self.logged_in = False
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def login(self) -> None:
        """关键参数：无
        返回值：None
        描述：模拟登录。
        """
        self.logged_in = True

    def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        """关键参数：(payload: dict[str, Any])
        返回值：dict[str, Any]
        描述：记录提交 payload 并返回固定任务。
        """
        self.calls.append(("submit_job", (payload,), {}))
        return {"job_id": "101", "file_name": "demo.pdf", "folder_id": payload.get("folder_id", 0)}

    def set_patent_remark(self, task_id: int, remarks: str | None = None) -> dict[str, Any]:
        """关键参数：(task_id: int, remarks: str | None)
        返回值：dict[str, Any]
        描述：记录备注写入请求。
        """
        self.calls.append(("set_patent_remark", (task_id, remarks), {}))
        return {"code": 1, "data": {}, "message": "task remarks process success!"}


def test_client_set_patent_remark_uses_swagger_contract() -> None:
    """关键参数：无
    返回值：None
    描述：验证 remarks 接口 method、path 和 body。
    """
    captured: list[dict[str, Any]] = []
    client = PatSightClient.__new__(PatSightClient)
    client.config = SimpleNamespace(base_url="https://example.test/patent/api")

    def fake_request(method: str, url: str, **kwargs: Any) -> FakeJsonResponse:
        captured.append({"method": method, "url": url, **kwargs})
        return FakeJsonResponse({"code": 1, "data": {}, "message": "ok"})

    client._request = fake_request  # type: ignore[method-assign]
    client._parse_json_response = lambda resp: resp.json()  # type: ignore[method-assign]

    assert client.set_patent_remark(101, "Priority review")["code"] == 1
    assert client.set_patent_remark(101, "")["code"] == 1

    assert captured == [
        {
            "method": "POST",
            "url": "https://example.test/patent/api/v2/extractor/task/remarks",
            "json": {"task_id": 101, "remarks": "Priority review"},
        },
        {
            "method": "POST",
            "url": "https://example.test/patent/api/v2/extractor/task/remarks",
            "json": {"task_id": 101, "remarks": ""},
        },
    ]


def test_submit_remark_sets_remark_after_submit(monkeypatch: Any, capsys: Any) -> None:
    """关键参数：(monkeypatch: Any, capsys: Any)
    返回值：None
    描述：验证 submit --remark 在提交成功后写入同一 task 备注。
    """
    fake_client = FakePatSightClient()
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", FakePatSightClient)
    args = argparse.Namespace(
        payload_file=None,
        payload=None,
        pdf_path="demo.pdf",
        action=None,
        job_type="structureAndActivity",
        shared_folder_id=17,
        folder_id=None,
        pages=None,
        remark="Priority review",
    )

    cli_main.cmd_submit(args)

    output = json.loads(capsys.readouterr().out)
    assert fake_client.logged_in is True
    assert fake_client.calls == [
        (
            "submit_job",
            (
                {
                    "pdf_path": "demo.pdf",
                    "job_type": "structureAndActivity",
                    "folder_id": 17,
                },
            ),
            {},
        ),
        ("set_patent_remark", (101, "Priority review"), {}),
    ]
    assert output["remark"]["ok"] is True


def test_submit_remark_failure_raises_client_error(monkeypatch: Any) -> None:
    """关键参数：(monkeypatch: Any)
    返回值：None
    描述：验证 submit 成功但备注更新失败时命令会失败。
    """
    fake_client = FakePatSightClient()

    def fail_set_patent_remark(task_id: int, remarks: str | None = None) -> dict[str, Any]:
        raise RuntimeError("remark api unavailable")

    fake_client.set_patent_remark = fail_set_patent_remark  # type: ignore[method-assign]
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", FakePatSightClient)
    args = argparse.Namespace(
        payload_file=None,
        payload=None,
        pdf_path="demo.pdf",
        action=None,
        job_type="structureAndActivity",
        shared_folder_id=17,
        folder_id=None,
        pages=None,
        remark="Priority review",
    )

    with pytest.raises(ClientError, match="remark update failed"):
        cli_main.cmd_submit(args)


def test_patent_remark_set_handler(monkeypatch: Any, capsys: Any) -> None:
    """关键参数：(monkeypatch: Any, capsys: Any)
    返回值：None
    描述：验证 patent remark set 会调用备注接口。
    """
    fake_client = FakePatSightClient()
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", FakePatSightClient)
    args = argparse.Namespace(task_id=101, remark="done")

    cli_main.cmd_patent_remark_set(args)

    assert fake_client.logged_in is True
    assert fake_client.calls == [("set_patent_remark", (101, "done"), {})]
    assert json.loads(capsys.readouterr().out)["code"] == 1


def test_remark_length_validation() -> None:
    """关键参数：无
    返回值：None
    描述：验证备注长度限制与 Swagger 保持一致。
    """
    with pytest.raises(ClientError, match="at most 139"):
        cli_main._validate_remark("x" * 140)


def test_parser_accepts_submit_and_patent_remark() -> None:
    """关键参数：无
    返回值：None
    描述：验证新增备注命令参数可解析。
    """
    submit_args = cli_main.build_parser().parse_args(
        ["submit", "--pdf-path", "demo.pdf", "--remark", "Priority"]
    )
    assert submit_args.func is cli_main.cmd_submit
    assert submit_args.remark == "Priority"

    remark_args = cli_main.build_parser().parse_args(
        ["patent", "remark", "set", "--task-id", "101", "--remark", "Priority"]
    )
    assert remark_args.func is cli_main.cmd_patent_remark_set
    assert remark_args.task_id == 101
    assert remark_args.remark == "Priority"
