"""验证 patent export --zip 本地批量打包逻辑。"""

from __future__ import annotations

import importlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from patsight_cli.export.batch_zip import export_patents_to_zip

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
                        "file_name": "done-patent",
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
        return {"code": 1, "data": {"editors": [{"user_email": f"user-{task_id}@example.com"}]}}

    def export_task(self, *args: Any, **kwargs: Any) -> str:
        """关键参数：(*args: Any, **kwargs: Any)
        返回值：str
        描述：创建一个假导出文件并返回路径。
        """
        self.export_calls.append((args, kwargs))
        path = Path(self.workdir) / f"{args[0]}-export.csv"
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
        }
    ]

    with zipfile.ZipFile(result["zip_path"]) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "metadata.json" in names
        assert "exports/101-export.csv" in names
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["exported_count"] == 1
        assert manifest["skipped_count"] == 1
        assert manifest["tasks"][0]["metadata"]["remarks"] == "Priority"
        assert manifest["tasks"][1]["reason"] == "status=Queueing"


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
    assert args.fetch_all is True
    assert args.format == "csv"
    assert args.output == "out.zip"
