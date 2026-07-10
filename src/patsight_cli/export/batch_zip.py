"""按专利列表筛选结果执行本地 zip 批量导出。"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from patsight_cli.clients.patsight import api_action_to_job_type, normalize_api_action_string
from patsight_cli.exceptions import ExportError
from patsight_cli.export_options import export_type_choices_for_job
from patsight_cli.patent_filters import (
    filter_patent_rows,
    has_last_operation_filters,
    patent_rows_from_response,
    task_matches_last_operation_filters,
    validate_last_operation_date_filters,
)

FINISHED_STATUS = {"done", "completed", "success", "finished"}


def is_finished_status(status: Any) -> bool:
    """关键参数：(status: Any)
    返回值：bool
    描述：判断任务状态是否允许导出。
    """
    return str(status or "").strip().lower() in FINISHED_STATUS


def task_id_from_row(row: Dict[str, Any]) -> str:
    """关键参数：(row: Dict[str, Any])
    返回值：str
    描述：从专利列表行中提取后端导出使用的 task id。
    """
    raw_id = row.get("id") or row.get("task_id")
    if raw_id is None:
        raise ExportError(f"patent row has no id/task_id: {row}")
    return str(raw_id)


def job_type_from_row(row: Dict[str, Any]) -> str:
    """关键参数：(row: Dict[str, Any])
    返回值：str
    描述：根据任务 action 推导导出 job_type。
    """
    action = row.get("action") if row.get("action") is not None else row.get("action_type")
    normalized = normalize_api_action_string(str(action or "0"))
    return api_action_to_job_type(normalized)


def export_types_for_row(row: Dict[str, Any], requested_export_type: str | None) -> tuple[str, ...]:
    """关键参数：(row: Dict[str, Any], requested_export_type: str | None)
    返回值：tuple[str, ...]
    描述：确定单条任务需要导出的数据类型，未指定时导出该任务支持的全部类型。
    """
    if requested_export_type:
        return (requested_export_type,)
    job_type = job_type_from_row(row)
    export_types = export_type_choices_for_job(job_type)
    if not export_types:
        raise ExportError(f"Unsupported job_type for export: {job_type!r}.")
    return export_types


def collect_patents(
    client: Any,
    *,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
    status: Optional[str] = None,
    is_collection: Optional[bool] = None,
    folder_id: Optional[int] = None,
    name: Optional[str] = None,
    name_field: Optional[str] = None,
    searched_smiles: Optional[str] = None,
    view: Optional[int] = None,
    exclude_action: Optional[str] = None,
    fetch_all: bool = False,
    remark: Optional[str] = None,
    creator_email: Optional[str] = None,
    unfiled: bool = False,
    multi_folder: bool = False,
    last_operator: Optional[str] = None,
    last_operated_after: Optional[str] = None,
    last_operated_before: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """关键参数：(client: Any, list/filter 参数)
    返回值：List[Dict[str, Any]]
    描述：分页收集专利列表并应用客户端过滤。
    """
    validate_last_operation_date_filters(
        last_operated_after=last_operated_after,
        last_operated_before=last_operated_before,
    )
    per_page_value = per_page or (100 if fetch_all else None)
    start_page = page or 1
    max_pages = getattr(getattr(client, "config", None), "list_tasks_max_pages", 500)
    rows: list[dict[str, Any]] = []

    for index in range(max_pages if fetch_all else 1):
        current_page = start_page + index
        response = client.list_accessible_patents(
            page=current_page,
            per_page=per_page_value,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status=status,
            is_collection=is_collection,
            folder_id=folder_id,
            name=name,
            name_field=name_field,
            searched_smiles=searched_smiles,
            view=view,
            exclude_action=exclude_action,
            last_operator=last_operator,
            last_operated_after=last_operated_after,
            last_operated_before=last_operated_before,
        )
        page_rows = patent_rows_from_response(response)
        rows.extend(page_rows)
        data = response.get("data") if isinstance(response, dict) else None
        total = data.get("count") if isinstance(data, dict) else None
        if not fetch_all or not page_rows:
            break
        if isinstance(total, int) and len(rows) >= total:
            break

    filtered_rows = filter_patent_rows(
        rows,
        remark=remark,
        creator_email=creator_email,
        unfiled=unfiled,
        multi_folder=multi_folder,
    )
    if not has_last_operation_filters(
        last_operator=last_operator,
        last_operated_after=last_operated_after,
        last_operated_before=last_operated_before,
    ):
        return filtered_rows

    operation_filtered_rows: list[dict[str, Any]] = []
    for row in filtered_rows:
        editors_payload = client.list_patent_editors(int(task_id_from_row(row)))
        if task_matches_last_operation_filters(
            editors_payload,
            last_operator=last_operator,
            last_operated_after=last_operated_after,
            last_operated_before=last_operated_before,
        ):
            operation_filtered_rows.append(row)
    return operation_filtered_rows


def metadata_for_row(row: Dict[str, Any], editors: Any = None) -> Dict[str, Any]:
    """关键参数：(row: Dict[str, Any], editors: Any)
    返回值：Dict[str, Any]
    描述：构建 zip manifest 中的专利元数据。
    """
    return {
        "id": row.get("id"),
        "task_id": row.get("task_id"),
        "file_name": row.get("file_name"),
        "status": row.get("status"),
        "creator": row.get("creator"),
        "remarks": row.get("remarks"),
        "folders": row.get("folders") or [],
        "added_by": row.get("added_by"),
        "copy_from_user_email": row.get("copy_from_user_email"),
        "copy_time": row.get("copy_time"),
        "created_time": row.get("created_time"),
        "updated_time": row.get("updated_time"),
        "finished_time": row.get("finished_time"),
        "editors": editors,
    }


def safe_arcname(path: Path, used_names: set[str]) -> str:
    """关键参数：(path: Path, used_names: set[str])
    返回值：str
    描述：按本地文件名生成 zip 内唯一条目名（测试/扩展用）。
    """
    base_name = path.name
    candidate = base_name
    index = 2
    while candidate in used_names:
        candidate = f"{path.stem}-{index}{path.suffix}"
        index += 1
    used_names.add(candidate)
    return f"exports/{candidate}"


def stable_export_arcname(
    *,
    task_id: str,
    export_type: str,
    file_suffix: str,
    used_names: set[str],
) -> str:
    """关键参数：(task_id/export_type/file_suffix/used_names)
    返回值：str
    描述：生成纯 ASCII 的 zip 导出条目名，避免中文文件名在解压工具中乱码。
    """
    suffix = file_suffix if file_suffix.startswith(".") or not file_suffix else f".{file_suffix}"
    candidate = f"{task_id}-{export_type}{suffix}"
    index = 2
    while candidate in used_names:
        candidate = f"{task_id}-{export_type}-{index}{suffix}"
        index += 1
    used_names.add(candidate)
    return f"exports/{candidate}"


def export_patents_to_zip(
    client: Any,
    *,
    output_path: str | None = None,
    export_type: str | None = None,
    file_format: str | None = None,
    fetch_all: bool = False,
    include_editors: bool = True,
    list_kwargs: Optional[Dict[str, Any]] = None,
    filter_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """关键参数：(client: Any, output_path/export_type/file_format/fetch_all 等)
    返回值：Dict[str, Any]
    描述：按专利列表结果导出完成任务并打包为 zip。
    """
    list_kwargs = list_kwargs or {}
    filter_kwargs = filter_kwargs or {}
    rows = collect_patents(client, fetch_all=fetch_all, **list_kwargs, **filter_kwargs)

    workdir = Path(getattr(client, "workdir", "."))
    workdir.mkdir(parents=True, exist_ok=True)
    if output_path:
        zip_path = Path(output_path)
    else:
        zip_path = workdir / f"patsight_patent_export_{int(time.time())}.zip"
    if not zip_path.is_absolute():
        zip_path = workdir / zip_path
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "task_count": len(rows),
        "exported_count": 0,
        "skipped_count": 0,
        "warnings": [],
        "tasks": [],
    }
    used_names: set[str] = set()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for row in rows:
            task_id = task_id_from_row(row)
            task_meta = metadata_for_row(row)
            export_record: dict[str, Any] = {"task_id": task_id, "metadata": task_meta}

            if include_editors:
                try:
                    task_meta["editors"] = client.list_patent_editors(int(task_id))
                except Exception as exc:  # noqa: BLE001
                    warning = f"editors unavailable for task_id={task_id}: {exc}"
                    manifest["warnings"].append(warning)
                    task_meta["editors"] = None

            if not is_finished_status(row.get("status")):
                export_record["skipped"] = True
                export_record["reason"] = f"status={row.get('status')}"
                manifest["skipped_count"] += 1
                manifest["tasks"].append(export_record)
                continue

            job_type = job_type_from_row(row)
            export_record["exported_files"] = []
            export_record["export_errors"] = []
            for target_export_type in export_types_for_row(row, export_type):
                try:
                    exported_path = Path(
                        client.export_task(
                            task_id,
                            job_type=job_type,
                            export_type=target_export_type,
                            file_format=file_format,
                            file_name=str(row.get("file_name") or ""),
                            task_action=str(row.get("action") or row.get("action_type") or "0"),
                        )
                    )
                    if exported_path.is_file():
                        arcname = stable_export_arcname(
                            task_id=task_id,
                            export_type=target_export_type,
                            file_suffix=exported_path.suffix,
                            used_names=used_names,
                        )
                        zip_file.write(exported_path, arcname)
                        export_record["exported_files"].append(
                            {"export_type": target_export_type, "file": arcname}
                        )
                        manifest["exported_count"] += 1
                    else:
                        raise ExportError(f"exported file does not exist: {exported_path}")
                except Exception as exc:  # noqa: BLE001
                    warning = f"export failed for task_id={task_id} export_type={target_export_type}: {exc}"
                    export_record["export_errors"].append(str(exc))
                    manifest["warnings"].append(warning)

            if export_record.get("exported_files"):
                if len(export_record["exported_files"]) == 1:
                    export_record["exported_file"] = export_record["exported_files"][0]["file"]
            else:
                export_record["skipped"] = True
                export_record["reason"] = "; ".join(export_record["export_errors"]) or "no files exported"
                manifest["skipped_count"] += 1

            manifest["tasks"].append(export_record)

        zip_file.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zip_file.writestr(
            "metadata.json",
            json.dumps([task["metadata"] for task in manifest["tasks"]], ensure_ascii=False, indent=2),
        )

    return {
        "ok": True,
        "zip_path": str(zip_path),
        "task_count": manifest["task_count"],
        "exported_count": manifest["exported_count"],
        "skipped_count": manifest["skipped_count"],
        "warnings": manifest["warnings"],
    }


def copy_into_zip(zip_file: zipfile.ZipFile, paths: Iterable[Path], used_names: set[str]) -> None:
    """关键参数：(zip_file: ZipFile, paths: Iterable[Path], used_names: set[str])
    返回值：None
    描述：保留给测试/扩展使用的批量复制工具。
    """
    for path in paths:
        if path.is_file():
            zip_file.write(path, safe_arcname(path, used_names))
