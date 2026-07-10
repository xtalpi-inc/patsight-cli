"""验证 patent export --zip 本地批量打包逻辑。"""

from __future__ import annotations

import importlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from patsight_cli.export.batch_zip import export_patents_to_zip
from patsight_cli.export_filename import export_filename

cli_main = importlib.import_module("patsight_cli.cli.main")


class FakeExportClient:
    """关键参数：(workdir: Path)
    返回值：FakeExportClient
    描述：模拟 PatSight client 的列表、导出和 editors 能力。
    """

    def __init__(self, workdir: Path) -> None:
        self.workdir = str(workdir)
        self.config = SimpleNamespace(list_tasks_max_pages=10)
        self.list_calls: list[dict[str, Any]] = []
        self.export_calls: list[tuple[Any, ...]] = []

    def list_accessible_patents(self, **kwargs: Any) -> dict[str, Any]:
        """关键参数：(**kwargs: Any)
        返回值：dict[str, Any]
        描述：返回一条完成任务和一条未完成任务。
        """
        self.list_calls.append(kwargs)
        return {
            "code": 1,
            "data": {
                "count": 2,
                "task_info": [
                    {
                        "id": 101,
                        "action": "0",
                        "status": "done",
                        "file_name": "WO2022233302 - 生物活性",
                        "creator": "owner@example.com",
                        "remarks": "Priority",
                        "folders": [{"id": 17, "path": "Project A"}],
                    },
                    {
                        "id": 102,
                        "action": "0",
                        "status": "Queueing",
                        "file_name": "pending-patent",
                        "creator": "owner@example.com",
                        "remarks": "",
                        "folders": [],
                    },
                ],
            },
        }

    def list_patent_editors(self, task_id: int) -> dict[str, Any]:
        """关键参数：(task_id: int)
        返回值：dict[str, Any]
        描述：返回固定 editors 数据。
        """
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
        }

    def export_task(self, *args: Any, **kwargs: Any) -> str:
        """关键参数：(*args: Any, **kwargs: Any)
        返回值：str
        描述：按生产命名规则创建含中文的假导出文件并返回路径。
        """
        self.export_calls.append((args, kwargs))
        file_name = str(kwargs.get("file_name") or f"{args[0]}")
        out_name = export_filename(
            export_type=str(kwargs.get("export_type") or "bioactivity"),
            file_format=str(kwargs.get("file_format") or "csv"),
            file_name=file_name,
        )
        path = Path(self.workdir) / out_name
        path.write_text("id,value\n1,ok\n", encoding="utf-8")
        return str(path)


def test_export_patents_to_zip_writes_manifest_and_exports_done_tasks(tmp_path: Path) -> None:
    """关键参数：(tmp_path: Path)
    返回值：None
    描述：验证 zip 包含 manifest、metadata 和完成任务导出文件。
    """
    client = FakeExportClient(tmp_path)
    result = export_patents_to_zip(
        client,
        output_path=str(tmp_path / "batch.zip"),
        export_type="bioactivity",
        list_kwargs={"folder_id": 17, "per_page": 10},
        filter_kwargs={"creator_email": "owner@example.com"},
    )

    assert result["ok"] is True
    assert result["task_count"] == 2
    assert result["exported_count"] == 1
    assert result["skipped_count"] == 1
    assert client.list_calls == [
        {
            "page": 1,
            "per_page": 10,
            "sort_by": None,
            "sort_dir": None,
            "status": None,
            "is_collection": None,
            "folder_id": 17,
            "name": None,
            "name_field": None,
            "searched_smiles": None,
            "view": None,
            "exclude_action": None,
            "last_operator": None,
            "last_operated_after": None,
            "last_operated_before": None,
        }
    ]

    with zipfile.ZipFile(result["zip_path"]) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "metadata.json" in names
        assert "exports/101-bioactivity.csv" in names
        assert all(name.isascii() for name in names if name.startswith("exports/"))
        assert not any("生物活性" in name for name in names)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["exported_count"] == 1
        assert manifest["skipped_count"] == 1
        assert manifest["tasks"][0]["metadata"]["remarks"] == "Priority"
        assert manifest["tasks"][0]["metadata"]["file_name"] == "WO2022233302 - 生物活性"
        assert manifest["tasks"][0]["exported_file"] == "exports/101-bioactivity.csv"
        assert manifest["tasks"][1]["reason"] == "status=Queueing"
        assert archive.read("exports/101-bioactivity.csv").decode("utf-8").replace("\r\n", "\n") == "id,value\n1,ok\n"


def test_export_patents_to_zip_exports_all_types_by_default(tmp_path: Path) -> None:
    """关键参数：(tmp_path: Path)
    返回值：None
    描述：验证未指定 export_type 时会导出任务支持的全部类型。
    """
    client = FakeExportClient(tmp_path)
    result = export_patents_to_zip(
        client,
        output_path=str(tmp_path / "all-types.zip"),
        filter_kwargs={"creator_email": "owner@example.com"},
    )

    assert result["task_count"] == 2
    assert result["exported_count"] == 3
    assert result["skipped_count"] == 1
    assert [call[1]["export_type"] for call in client.export_calls] == [
        "admet",
        "bioactivity",
        "namedStructures",
    ]

    with zipfile.ZipFile(result["zip_path"]) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        exported_files = manifest["tasks"][0]["exported_files"]
        assert [item["export_type"] for item in exported_files] == [
            "admet",
            "bioactivity",
            "namedStructures",
        ]


def test_export_patents_to_zip_filters_by_last_operator(tmp_path: Path) -> None:
    """关键参数：(tmp_path: Path)
    返回值：None
    描述：验证 zip 导出会按最后操作人过滤任务。
    """
    client = FakeExportClient(tmp_path)
    result = export_patents_to_zip(
        client,
        output_path=str(tmp_path / "last-operator.zip"),
        export_type="bioactivity",
        fetch_all=True,
        filter_kwargs={"last_operator": "owner@example.com"},
    )

    assert result["task_count"] == 1
    assert result["exported_count"] == 1
    assert client.export_calls[0][0][0] == "101"


def test_export_patents_to_zip_uses_ascii_arcnames_for_chinese_file_name(tmp_path: Path) -> None:
    """关键参数：(tmp_path: Path)
    返回值：None
    描述：验证中文专利名只保留在 metadata，zip 条目使用 ASCII 稳定名。
    """
    client = FakeExportClient(tmp_path)
    result = export_patents_to_zip(
        client,
        output_path=str(tmp_path / "chinese-name.zip"),
        export_type="bioactivity",
        filter_kwargs={"creator_email": "owner@example.com"},
    )

    with zipfile.ZipFile(result["zip_path"]) as archive:
        export_names = [name for name in archive.namelist() if name.startswith("exports/")]
        assert export_names == ["exports/101-bioactivity.csv"]
        assert all(name.isascii() for name in export_names)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["tasks"][0]["metadata"]["file_name"] == "WO2022233302 - 生物活性"
        metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
        assert metadata[0]["file_name"] == "WO2022233302 - 生物活性"


def test_patent_export_parser_accepts_zip_flags() -> None:
    """关键参数：无
    返回值：None
    描述：验证 patent export --zip 参数可解析。
    """
    args = cli_main.build_parser().parse_args(
        [
            "patent",
            "export",
            "--zip",
            "--folder-id",
            "17",
            "--remark",
            "Priority",
            "--creator-email",
            "owner@example.com",
            "--last-operator",
            "owner@example.com",
            "--last-operated-after",
            "2026-06-01",
            "--last-operated-before",
            "2026-07-01",
            "--fetch-all",
            "--format",
            "csv",
            "-o",
            "out.zip",
        ]
    )

    assert args.func is cli_main.cmd_patent_export_zip
    assert args.zip is True
    assert args.folder_id == 17
    assert args.remark == "Priority"
    assert args.creator_email == "owner@example.com"
    assert args.last_operator == "owner@example.com"
    assert args.last_operated_after == "2026-06-01"
    assert args.last_operated_before == "2026-07-01"
    assert args.fetch_all is True
    assert args.format == "csv"
    assert args.output == "out.zip"
