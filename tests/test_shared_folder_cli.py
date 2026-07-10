"""验证 V2.26 共享文件夹与专利查询 CLI 的离线契约。"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import logging
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from patsight_cli.clients.patsight import PatSightClient, shared_folder_role_to_api
from patsight_cli.exceptions import ClientError

cli_main = importlib.import_module("patsight_cli.cli.main")


class FakeJsonResponse:
    """关键参数：(payload: dict[str, Any])
    返回值：FakeJsonResponse
    描述：提供最小 JSON 响应对象以验证 client 请求契约。
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        """关键参数：无
        返回值：dict[str, Any]
        描述：返回预置 JSON 响应内容。
        """
        return self.payload


class FakePatSightClient:
    """关键参数：无
    返回值：FakePatSightClient
    描述：记录 CLI 调用以验证命令参数传递。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.logged_in = False

    def login(self) -> None:
        """关键参数：无
        返回值：None
        描述：模拟登录并记录登录状态。
        """
        self.logged_in = True

    def record(self, method_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """关键参数：(method_name: str, *args: Any, **kwargs: Any)
        返回值：dict[str, Any]
        描述：记录被调用的 client 方法并返回固定响应。
        """
        self.calls.append((method_name, args, kwargs))
        return {"code": 1, "data": {"method": method_name}, "error": "", "message": "ok"}

    def list_shared_folders(self, view: int | None = None) -> dict[str, Any]:
        """关键参数：(view: int | None)
        返回值：dict[str, Any]
        描述：记录共享文件夹列表查询调用。
        """
        return self.record("list_shared_folders", view=view)

    def create_shared_folder(
        self, name: str, parent_id: int | None = None, view: int = 0
    ) -> dict[str, Any]:
        """关键参数：(name: str, parent_id: int | None, view: int)
        返回值：dict[str, Any]
        描述：记录共享文件夹创建调用。
        """
        return self.record("create_shared_folder", name, parent_id=parent_id, view=view)

    def rename_shared_folder(self, folder_id: int, name: str) -> dict[str, Any]:
        """关键参数：(folder_id: int, name: str)
        返回值：dict[str, Any]
        描述：记录共享文件夹重命名调用。
        """
        return self.record("rename_shared_folder", folder_id, name)

    def delete_shared_folder(self, folder_id: int) -> dict[str, Any]:
        """关键参数：(folder_id: int)
        返回值：dict[str, Any]
        描述：记录共享文件夹删除调用。
        """
        return self.record("delete_shared_folder", folder_id)

    def list_shared_folder_members(self, folder_id: int) -> dict[str, Any]:
        """关键参数：(folder_id: int)
        返回值：dict[str, Any]
        描述：记录共享文件夹成员列表调用。
        """
        return self.record("list_shared_folder_members", folder_id)

    def add_shared_folder_member(
        self, folder_id: int, email: str, role: str = "member"
    ) -> dict[str, Any]:
        """关键参数：(folder_id: int, email: str, role: str)
        返回值：dict[str, Any]
        描述：记录共享文件夹成员添加调用。
        """
        return self.record("add_shared_folder_member", folder_id, email, role=role)

    def remove_shared_folder_member(self, folder_id: int, user_email: str) -> dict[str, Any]:
        """关键参数：(folder_id: int, user_email: str)
        返回值：dict[str, Any]
        描述：记录共享文件夹成员删除请求并返回固定结果。
        """
        return self.record("remove_shared_folder_member", folder_id, user_email)

    def update_shared_folder_member_role(
        self, folder_id: int, user_email: str, role: str
    ) -> dict[str, Any]:
        """关键参数：(folder_id: int, user_email: str, role: str)
        返回值：dict[str, Any]
        描述：记录共享文件夹成员角色修改调用。
        """
        return self.record("update_shared_folder_member_role", folder_id, user_email, role)

    def list_shared_folder_patents(self, folder_id: int) -> dict[str, Any]:
        """关键参数：(folder_id: int)
        返回值：dict[str, Any]
        描述：记录共享文件夹专利列表调用。
        """
        return self.record("list_shared_folder_patents", folder_id)

    def add_shared_folder_patents(self, folder_id: int, task_ids: list[int]) -> dict[str, Any]:
        """关键参数：(folder_id: int, task_ids: list[int])
        返回值：dict[str, Any]
        描述：记录共享文件夹专利加入调用。
        """
        return self.record("add_shared_folder_patents", folder_id, task_ids)

    def remove_shared_folder_patents(self, folder_id: int, task_ids: list[int]) -> dict[str, Any]:
        """关键参数：(folder_id: int, task_ids: list[int])
        返回值：dict[str, Any]
        描述：记录共享文件夹专利移出调用。
        """
        return self.record("remove_shared_folder_patents", folder_id, task_ids)

    def list_accessible_patents(self, **kwargs: Any) -> dict[str, Any]:
        """关键参数：(**kwargs: Any)
        返回值：dict[str, Any]
        描述：记录专利列表查询调用。
        """
        return self.record("list_accessible_patents", **kwargs)

    def get_patent_detail(self, task_id: int) -> dict[str, Any]:
        """关键参数：(task_id: int)
        返回值：dict[str, Any]
        描述：记录专利详情查询调用。
        """
        return self.record("get_patent_detail", task_id)

    def list_patent_editors(self, task_id: int) -> dict[str, Any]:
        """关键参数：(task_id: int)
        返回值：dict[str, Any]
        描述：记录专利编辑者查询调用。
        """
        return self.record("list_patent_editors", task_id)


class FakeLastOperationClient(FakePatSightClient):
    """关键参数：无
    返回值：FakeLastOperationClient
    描述：模拟可按最后操作记录筛选的专利列表客户端。
    """

    def list_accessible_patents(self, **kwargs: Any) -> dict[str, Any]:
        """关键参数：(**kwargs: Any)
        返回值：dict[str, Any]
        描述：返回两条完成任务以验证最后操作筛选。
        """
        self.calls.append(("list_accessible_patents", (), kwargs))
        return {
            "code": 1,
            "data": {
                "count": 2,
                "task_info": [
                    {"id": 101, "status": "Done", "file_name": "A"},
                    {"id": 102, "status": "Done", "file_name": "B"},
                ],
            },
            "error": "",
            "message": "ok",
        }

    def list_patent_editors(self, task_id: int) -> dict[str, Any]:
        """关键参数：(task_id: int)
        返回值：dict[str, Any]
        描述：返回不同最后操作人用于筛选。
        """
        self.calls.append(("list_patent_editors", (task_id,), {}))
        email = "owner@example.com" if task_id == 101 else "other@example.com"
        return {
            "code": 1,
            "data": {
                "editors": [
                    {
                        "user_email": email,
                        "last_operation_time": "Thu, 25 Jun 2026 05:34:41 GMT",
                    }
                ]
            },
            "error": "",
            "message": "ok",
        }


class EdgeCasePatentListClient(FakePatSightClient):
    """关键参数：(task_row: dict[str, Any])
    返回值：EdgeCasePatentListClient
    描述：返回包含特殊字符的专利列表数据以验证 stdout JSON 契约。
    """

    def __init__(self, task_row: dict[str, Any]) -> None:
        super().__init__()
        self.task_row = task_row

    def list_accessible_patents(self, **kwargs: Any) -> dict[str, Any]:
        """关键参数：(**kwargs: Any)
        返回值：dict[str, Any]
        描述：记录查询参数并返回特殊字符专利列表。
        """
        logging.getLogger("patsight_cli.tests").warning("diagnostic log should stay off stdout")
        self.calls.append(("list_accessible_patents", (), kwargs))
        return {
            "code": 1,
            "data": {"count": 1, "task_info": [self.task_row]},
            "error": "",
            "message": "ok",
        }


def build_uninitialized_client() -> tuple[PatSightClient, list[dict[str, Any]]]:
    """关键参数：无
    返回值：tuple[PatSightClient, list[dict[str, Any]]]
    描述：构造不触发登录的 PatSight client 并捕获请求参数。
    """
    client = PatSightClient.__new__(PatSightClient)
    client.config = SimpleNamespace(base_url="https://example.test/patent/api")
    client.tasks_url = "https://example.test/patent/api/v2/extractor/tasks"
    captured_requests: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> FakeJsonResponse:
        captured_requests.append({"method": method, "url": url, **kwargs})
        return FakeJsonResponse({"code": 1, "data": {}, "error": "", "message": "ok"})

    client._request = fake_request  # type: ignore[method-assign]
    return client, captured_requests


def test_shared_folder_role_to_api_accepts_public_values() -> None:
    """关键参数：无
    返回值：None
    描述：验证成员角色参数会转换为后端 0/1 约定。
    """
    assert shared_folder_role_to_api("admin") == 0
    assert shared_folder_role_to_api("member") == 1
    assert shared_folder_role_to_api("0") == 0
    assert shared_folder_role_to_api(1) == 1


def test_client_v226_required_methods_use_openapi_contracts() -> None:
    """关键参数：无
    返回值：None
    描述：验证 V2.26 必需接口封装的 method、path、query 和 body 契约。
    """
    client, captured_requests = build_uninitialized_client()

    client.list_shared_folders(view=1)
    client.create_shared_folder("Root", parent_id=9, view=0)
    client.rename_shared_folder(17, "New Root")
    client.delete_shared_folder(17)
    client.list_shared_folder_members(17)
    client.add_shared_folder_member(17, "member@example.com", role="admin")
    client.remove_shared_folder_member(17, "member@example.com")
    client.update_shared_folder_member_role(17, "member@example.com", "member")
    client.list_shared_folder_patents(17)
    client.add_shared_folder_patents(17, [101, 102])
    client.remove_shared_folder_patents(17, [101, 102])
    client.list_accessible_patents(
        page=2,
        per_page=10,
        status="done",
        folder_id=17,
        name="demo",
        name_field="title",
        view=0,
        last_operator="owner@example.com",
        last_operated_after="2026-06-01",
        last_operated_before="2026-07-01",
    )
    client.get_patent_detail(101)
    client.list_patent_editors(101)

    assert captured_requests == [
        {
            "method": "GET",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/full",
            "params": {"view": 1},
        },
        {
            "method": "POST",
            "url": "https://example.test/patent/api/v2/extractor/task/folder",
            "json": {"path": "Root", "view": 0, "parent_id": 9},
        },
        {
            "method": "PUT",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/name",
            "json": {"folder_id": 17, "new_path": "New Root"},
        },
        {
            "method": "DELETE",
            "url": "https://example.test/patent/api/v2/extractor/task/folder",
            "json": {"folder_id": 17},
        },
        {
            "method": "GET",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/17/members",
        },
        {
            "method": "POST",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/17/members",
            "json": {"email": "member@example.com", "role": 0},
        },
        {
            "method": "DELETE",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/17/members",
            "json": {"user_email": "member@example.com"},
        },
        {
            "method": "PATCH",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/17/members/role",
            "json": {"user_email": "member@example.com", "role": 1},
        },
        {
            "method": "POST",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/task/get",
            "json": {"folder_id": 17},
        },
        {
            "method": "POST",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/task/favorite",
            "json": {"folder_id": 17, "task_ids": [101, 102]},
        },
        {
            "method": "POST",
            "url": "https://example.test/patent/api/v2/extractor/task/folder/task/unfavorite",
            "json": {"folder_id": 17, "task_ids": [101, 102]},
        },
        {
            "method": "GET",
            "url": "https://example.test/patent/api/v2/extractor/tasks",
            "params": {
                "page": 2,
                "per_page": 10,
                "status": "done",
                "folder_id": 17,
                "name": "demo",
                "name_field": "title",
                "view": 0,
                "last_operator": "owner@example.com",
                "last_operated_after": "2026-06-01",
                "last_operated_before": "2026-07-01",
            },
        },
        {
            "method": "GET",
            "url": "https://example.test/patent/api/v2/extractor/task/101",
        },
        {
            "method": "GET",
            "url": "https://example.test/patent/api/v3/extractor/task/101/editors",
        },
    ]


@pytest.mark.parametrize(
    ("handler_name", "args", "expected_call"),
    [
        (
            "cmd_shared_folder_list",
            argparse.Namespace(view=1),
            ("list_shared_folders", (), {"view": 1}),
        ),
        (
            "cmd_shared_folder_create",
            argparse.Namespace(name="Root", parent_id=9, view=0),
            ("create_shared_folder", ("Root",), {"parent_id": 9, "view": 0}),
        ),
        (
            "cmd_shared_folder_rename",
            argparse.Namespace(folder_id=17, name="New Root"),
            ("rename_shared_folder", (17, "New Root"), {}),
        ),
        (
            "cmd_shared_folder_delete",
            argparse.Namespace(folder_id=17),
            ("delete_shared_folder", (17,), {}),
        ),
        (
            "cmd_shared_folder_members_list",
            argparse.Namespace(folder_id=17),
            ("list_shared_folder_members", (17,), {}),
        ),
        (
            "cmd_shared_folder_members_add",
            argparse.Namespace(folder_id=17, email="member@example.com", role="admin"),
            ("add_shared_folder_member", (17, "member@example.com"), {"role": "admin"}),
        ),
        (
            "cmd_shared_folder_members_remove",
            argparse.Namespace(folder_id=17, email="member@example.com"),
            ("remove_shared_folder_member", (17, "member@example.com"), {}),
        ),
        (
            "cmd_shared_folder_members_role",
            argparse.Namespace(folder_id=17, email="member@example.com", role="member"),
            ("update_shared_folder_member_role", (17, "member@example.com", "member"), {}),
        ),
        (
            "cmd_shared_folder_patents_list",
            argparse.Namespace(folder_id=17),
            ("list_shared_folder_patents", (17,), {}),
        ),
        (
            "cmd_shared_folder_patents_add",
            argparse.Namespace(folder_id=17, task_id=[101, 102]),
            ("add_shared_folder_patents", (17, [101, 102]), {}),
        ),
        (
            "cmd_shared_folder_patents_remove",
            argparse.Namespace(folder_id=17, task_id=[101, 102]),
            ("remove_shared_folder_patents", (17, [101, 102]), {}),
        ),
        (
            "cmd_patent_detail",
            argparse.Namespace(task_id=101),
            ("get_patent_detail", (101,), {}),
        ),
        (
            "cmd_patent_editors",
            argparse.Namespace(task_id=101),
            ("list_patent_editors", (101,), {}),
        ),
    ],
)
def test_cli_handlers_call_expected_client_method(
    monkeypatch: Any,
    capsys: Any,
    handler_name: str,
    args: argparse.Namespace,
    expected_call: tuple[str, tuple[Any, ...], dict[str, Any]],
) -> None:
    """关键参数：(monkeypatch: Any, capsys: Any)
    返回值：None
    描述：验证 CLI handler 会登录并调用对应 PatSight client 方法。
    """
    fake_client = FakePatSightClient()
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", FakePatSightClient)

    getattr(cli_main, handler_name)(args)

    assert fake_client.logged_in is True
    assert fake_client.calls == [expected_call]
    assert json.loads(capsys.readouterr().out)["code"] == 1


def test_cli_patent_list_handler_passes_supported_filters(monkeypatch: Any, capsys: Any) -> None:
    """关键参数：(monkeypatch: Any, capsys: Any)
    返回值：None
    描述：验证 patent list handler 会传递 Swagger 支持的筛选参数。
    """
    fake_client = FakePatSightClient()
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", FakePatSightClient)
    args = argparse.Namespace(
        page=2,
        per_page=10,
        sort_by="id",
        sort_dir="desc",
        status="done",
        is_collection=None,
        folder_id=17,
        name="demo",
        name_field="title",
        searched_smiles=None,
        view=0,
        exclude_action=None,
        last_operator=None,
        last_operated_after=None,
        last_operated_before=None,
        remark=None,
        creator_email=None,
        unfiled=False,
        multi_folder=False,
        fetch_all=False,
    )

    cli_main.cmd_patent_list(args)

    assert fake_client.logged_in is True
    assert fake_client.calls == [
        (
            "list_accessible_patents",
            (),
            {
                "page": 2,
                "per_page": 10,
                "sort_by": "id",
                "sort_dir": "desc",
                "status": "done",
                "is_collection": None,
                "folder_id": 17,
                "name": "demo",
                "name_field": "title",
                "searched_smiles": None,
                "view": 0,
                "exclude_action": None,
                "last_operator": None,
                "last_operated_after": None,
                "last_operated_before": None,
            },
        )
    ]
    assert json.loads(capsys.readouterr().out)["code"] == 1


def test_patent_list_parser_separates_client_name_from_keyword_filter() -> None:
    """关键参数：无
    返回值：None
    描述：验证 patent list 未传 --name 时不会把 client_name 默认值误当作筛选关键字。
    """
    parser = cli_main.build_parser()

    default_args = parser.parse_args(["patent", "list", "--fetch-all"])
    assert default_args.client_name == "default"
    assert default_args.name is None

    filtered_args = parser.parse_args(["patent", "list", "--name", "demo", "--client-name", "ProjectA"])
    assert filtered_args.client_name == "ProjectA"
    assert filtered_args.name == "demo"


def test_patent_list_parser_accepts_last_operation_filters() -> None:
    """关键参数：无
    返回值：None
    描述：验证 patent list 支持最后操作时间和操作人筛选参数。
    """
    parser = cli_main.build_parser()

    args = parser.parse_args(
        [
            "patent",
            "list",
            "--last-operator",
            "owner@example.com",
            "--last-operated-after",
            "2026-06-01",
            "--last-operated-before",
            "2026-07-01",
            "--fetch-all",
        ]
    )

    assert args.last_operator == "owner@example.com"
    assert args.last_operated_after == "2026-06-01"
    assert args.last_operated_before == "2026-07-01"


def test_patent_list_without_name_filter_omits_name_param(monkeypatch: Any, capsys: Any) -> None:
    """关键参数：(monkeypatch: Any, capsys: Any)
    返回值：None
    描述：验证 patent list 默认不会向后端传递 name=default。
    """
    fake_client = FakePatSightClient()
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", FakePatSightClient)
    args = cli_main.build_parser().parse_args(["patent", "list", "--fetch-all", "--per-page", "100"])

    cli_main.cmd_patent_list(args)

    assert fake_client.calls
    _, _, kwargs = fake_client.calls[0]
    assert kwargs.get("name") is None
    assert kwargs["page"] == 1
    assert kwargs["per_page"] == 100


def test_patent_list_stdout_is_valid_json_with_unicode_and_escapes(
    monkeypatch: Any, capsys: Any
) -> None:
    """关键参数：(monkeypatch: Any, capsys: Any)
    返回值：None
    描述：验证 patent list 在 verbose 和特殊字符字段下仍只向 stdout 输出合法 JSON。
    """
    special_remark = '中文备注 "quoted"\nsecond line\twith tab\x08backspace'
    long_abstract = "长文本段落-" + "稳定序列化" * 40
    task_row = {
        "id": 2071532118869155840,
        "title": "含中文标题与引号 \"CN patent\"",
        "abstract": long_abstract,
        "remarks": special_remark,
        "error_msg": "backend message with comma, colon: ok",
    }
    fake_client = EdgeCasePatentListClient(task_row)
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "handlers", [])
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", EdgeCasePatentListClient)
    monkeypatch.setattr(
        sys,
        "argv",
        ["patsight-cli", "--verbose", "patent", "list", "--fetch-all"],
    )

    cli_main.main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    output_row = output["data"]["task_info"][0]
    assert output_row["title"] == task_row["title"]
    assert output_row["abstract"] == long_abstract
    assert output_row["remarks"] == special_remark
    assert "中文备注" in captured.out
    assert "\\u4e2d" not in captured.out
    assert '\\"quoted\\"' in captured.out
    assert "\\nsecond line\\twith tab\\bbackspace" in captured.out
    assert "diagnostic log should stay off stdout" not in captured.out


def test_patent_list_stdout_bytes_are_utf8_under_cp936_console(monkeypatch: Any) -> None:
    """关键参数：(monkeypatch: Any)
    返回值：None
    描述：模拟 CP936 控制台时，patent list 仍以 UTF-8 字节写出可解析 JSON。
    """
    special_remark = "中文备注与标题"
    task_row = {
        "id": 2071532118869155840,
        "title": "含中文标题",
        "remarks": special_remark,
    }
    fake_client = EdgeCasePatentListClient(task_row)
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", EdgeCasePatentListClient)
    monkeypatch.setattr(
        sys,
        "argv",
        ["patsight-cli", "patent", "list", "--fetch-all"],
    )

    raw_buffer = io.BytesIO()
    cp936_stdout = io.TextIOWrapper(raw_buffer, encoding="cp936", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", cp936_stdout)

    cli_main.main()
    cp936_stdout.flush()

    assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
    raw_bytes = raw_buffer.getvalue()
    decoded = raw_bytes.decode("utf-8")
    output = json.loads(decoded)
    assert output["data"]["task_info"][0]["remarks"] == special_remark
    assert "中文备注".encode("utf-8") in raw_bytes
    assert "中文备注".encode("cp936") not in raw_bytes

def test_patent_list_filters_by_last_operator(monkeypatch: Any, capsys: Any) -> None:
    """关键参数：(monkeypatch: Any, capsys: Any)
    返回值：None
    描述：验证最后操作人筛选会调用 editors 并同步列表 count。
    """
    fake_client = FakeLastOperationClient()
    monkeypatch.setattr(cli_main, "create_client_from_args", lambda args: fake_client)
    monkeypatch.setattr(cli_main, "PatSightClient", FakeLastOperationClient)
    args = cli_main.build_parser().parse_args(
        [
            "patent",
            "list",
            "--last-operator",
            "owner@example.com",
            "--fetch-all",
        ]
    )

    cli_main.cmd_patent_list(args)

    output = json.loads(capsys.readouterr().out)
    assert output["data"]["count"] == 1
    assert output["data"]["task_info"][0]["id"] == 101
    assert [call[0] for call in fake_client.calls] == [
        "list_accessible_patents",
        "list_patent_editors",
        "list_patent_editors",
    ]


def test_patent_list_client_filters_require_fetch_all() -> None:
    """关键参数：无
    返回值：None
    描述：验证客户端筛选必须显式抓取完整分页数据。
    """
    args = argparse.Namespace(
        fetch_all=False,
        remark="Priority",
        creator_email=None,
        unfiled=False,
        multi_folder=False,
        last_operator=None,
        last_operated_after=None,
        last_operated_before=None,
    )

    with pytest.raises(ClientError, match="--fetch-all"):
        cli_main.cmd_patent_list(args)


def test_patent_export_client_filters_require_fetch_all() -> None:
    """关键参数：无
    返回值：None
    描述：验证批量导出使用客户端筛选时必须显式抓取完整分页数据。
    """
    args = argparse.Namespace(
        zip=True,
        fetch_all=False,
        remark=None,
        creator_email="owner@example.com",
        unfiled=False,
        multi_folder=False,
        last_operator=None,
        last_operated_after=None,
        last_operated_before=None,
    )

    with pytest.raises(ClientError, match="--fetch-all"):
        cli_main.cmd_patent_export_zip(args)


def test_patent_last_operation_filters_require_fetch_all() -> None:
    """关键参数：无
    返回值：None
    描述：验证最后操作筛选必须显式抓取完整分页数据。
    """
    args = argparse.Namespace(
        fetch_all=False,
        remark=None,
        creator_email=None,
        unfiled=False,
        multi_folder=False,
        last_operator="owner@example.com",
        last_operated_after=None,
        last_operated_before=None,
    )

    with pytest.raises(ClientError, match="--fetch-all"):
        cli_main.cmd_patent_list(args)


@pytest.mark.parametrize(
    ("argv", "expected_func", "expected_attrs"),
    [
        (["shared-folder", "list", "--view", "1"], "cmd_shared_folder_list", {"view": 1}),
        (
            ["shared-folder", "create", "--name", "Root", "--parent-id", "9", "--view", "0"],
            "cmd_shared_folder_create",
            {"name": "Root", "parent_id": 9, "view": 0},
        ),
        (
            ["shared-folder", "rename", "--folder-id", "17", "--name", "New Root"],
            "cmd_shared_folder_rename",
            {"folder_id": 17, "name": "New Root"},
        ),
        (
            ["shared-folder", "delete", "--folder-id", "17"],
            "cmd_shared_folder_delete",
            {"folder_id": 17},
        ),
        (
            ["shared-folder", "members", "list", "--folder-id", "17"],
            "cmd_shared_folder_members_list",
            {"folder_id": 17},
        ),
        (
            ["shared-folder", "members", "add", "--folder-id", "17", "--email", "a@b.com", "--role", "admin"],
            "cmd_shared_folder_members_add",
            {"folder_id": 17, "email": "a@b.com", "role": "admin"},
        ),
        (
            ["shared-folder", "members", "remove", "--folder-id", "17", "--email", "a@b.com"],
            "cmd_shared_folder_members_remove",
            {"folder_id": 17, "email": "a@b.com"},
        ),
        (
            ["shared-folder", "members", "role", "--folder-id", "17", "--email", "a@b.com", "--role", "member"],
            "cmd_shared_folder_members_role",
            {"folder_id": 17, "email": "a@b.com", "role": "member"},
        ),
        (
            ["shared-folder", "patents", "list", "--folder-id", "17"],
            "cmd_shared_folder_patents_list",
            {"folder_id": 17},
        ),
        (
            ["shared-folder", "patents", "add", "--folder-id", "17", "--task-id", "101", "102"],
            "cmd_shared_folder_patents_add",
            {"folder_id": 17, "task_id": [101, 102]},
        ),
        (
            ["shared-folder", "patents", "remove", "--folder-id", "17", "--task-id", "101", "102"],
            "cmd_shared_folder_patents_remove",
            {"folder_id": 17, "task_id": [101, 102]},
        ),
        (
            ["patent", "list", "--folder-id", "17", "--name", "demo", "--status", "done"],
            "cmd_patent_list",
            {"folder_id": 17, "name": "demo", "status": "done"},
        ),
        (
            ["patent", "detail", "--task-id", "101"],
            "cmd_patent_detail",
            {"task_id": 101},
        ),
        (
            ["patent", "editors", "--task-id", "101"],
            "cmd_patent_editors",
            {"task_id": 101},
        ),
    ],
)
def test_v226_required_parser_contracts(
    argv: list[str],
    expected_func: str,
    expected_attrs: dict[str, Any],
) -> None:
    """关键参数：无
    返回值：None
    描述：验证 V2.26 必需命令的公开参数形态。
    """
    parser = cli_main.build_parser()
    args = parser.parse_args(argv)

    assert args.func is getattr(cli_main, expected_func)
    for attr_name, expected_value in expected_attrs.items():
        assert getattr(args, attr_name) == expected_value


def test_load_payload_uses_shared_folder_id_for_submit() -> None:
    """关键参数：无
    返回值：None
    描述：验证 submit --shared-folder-id 会映射到后端 folder_id 字段。
    """
    args = argparse.Namespace(
        payload=None,
        payload_file=None,
        pdf_path="demo.pdf",
        action=None,
        job_type="structureAndActivity",
        folder_id=None,
        shared_folder_id=17,
        pages=None,
    )

    assert cli_main.load_payload(args) == {
        "pdf_path": "demo.pdf",
        "job_type": "structureAndActivity",
        "folder_id": 17,
    }


def test_load_payload_rejects_folder_id_and_shared_folder_id_conflict() -> None:
    """关键参数：无
    返回值：None
    描述：验证提交时个人文件夹和共享文件夹参数不能混用。
    """
    args = argparse.Namespace(
        payload=None,
        payload_file=None,
        pdf_path="demo.pdf",
        action=None,
        job_type="structureAndActivity",
        folder_id=12,
        shared_folder_id=17,
        pages=None,
    )

    with pytest.raises(ClientError, match="--shared-folder-id"):
        cli_main.load_payload(args)


def test_load_payload_rejects_payload_mode_submit_flag_conflicts() -> None:
    """关键参数：无
    返回值：None
    描述：验证 payload 模式不会静默忽略结构化 submit 参数。
    """
    args = argparse.Namespace(
        payload='{"pdf_path": "demo.pdf"}',
        payload_file=None,
        pdf_path=None,
        action=None,
        job_type="reaction",
        folder_id=None,
        shared_folder_id=None,
        pages=None,
    )

    with pytest.raises(ClientError, match="--job-type"):
        cli_main.load_payload(args)
