"""专利列表客户端筛选工具，复用新版 tasks 响应中的备注、创建者和文件夹元数据。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import re
from typing import Any, Dict, Iterable, List

from patsight_cli.exceptions import ClientError

OPERATION_DATE_FORMAT_HINT = "YYYY-MM-DD, for example 2026-06-17"


def patent_rows_from_response(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """关键参数：(response: Dict[str, Any])
    返回值：List[Dict[str, Any]]
    描述：从专利列表响应中提取 task_info 行。
    """
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    rows = data.get("task_info")
    if rows is None:
        rows = data.get("data")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def with_patent_rows(response: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """关键参数：(response: Dict[str, Any], rows: Iterable[Dict[str, Any]])
    返回值：Dict[str, Any]
    描述：返回替换 task_info 后的新响应对象，并同步 count。
    """
    copied = deepcopy(response)
    data = copied.setdefault("data", {})
    if not isinstance(data, dict):
        copied["data"] = data = {}
    row_list = list(rows)
    target_key = "task_info" if "task_info" in data or "data" not in data else "data"
    data[target_key] = row_list
    data["count"] = len(row_list)
    return copied


def task_folder_ids(task: Dict[str, Any]) -> set[int]:
    """关键参数：(task: Dict[str, Any])
    返回值：set[int]
    描述：从专利行 folders 字段提取文件夹 id 集合。
    """
    folders = task.get("folders")
    if not isinstance(folders, list):
        return set()
    folder_ids: set[int] = set()
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        raw_id = folder.get("id")
        if raw_id is None:
            continue
        try:
            folder_ids.add(int(raw_id))
        except (TypeError, ValueError):
            continue
    return folder_ids


def task_matches_filters(
    task: Dict[str, Any],
    *,
    folder_id: int | None = None,
    remark: str | None = None,
    creator_email: str | None = None,
    unfiled: bool = False,
    multi_folder: bool = False,
) -> bool:
    """关键参数：(task: Dict[str, Any], folder_id/remark/creator_email/unfiled/multi_folder)
    返回值：bool
    描述：判断单条专利是否满足客户端筛选条件。
    """
    if folder_id is not None and folder_id not in task_folder_ids(task):
        return False

    if remark is not None:
        remarks = str(task.get("remarks") or "").strip()
        if remarks.casefold() != remark.strip().casefold():
            return False

    if creator_email:
        creator = str(task.get("creator") or "")
        expected = creator_email.casefold()
        if creator.casefold() != expected and not creator.casefold().startswith(expected):
            return False

    folders = task.get("folders")
    folder_count = len(folders) if isinstance(folders, list) else 0
    if unfiled and folder_count != 0:
        return False
    if multi_folder and folder_count <= 1:
        return False

    return True


def filter_patent_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    folder_id: int | None = None,
    remark: str | None = None,
    creator_email: str | None = None,
    unfiled: bool = False,
    multi_folder: bool = False,
) -> List[Dict[str, Any]]:
    """关键参数：(rows: Iterable[Dict[str, Any]], 筛选条件)
    返回值：List[Dict[str, Any]]
    描述：按文件夹归属、备注、创建者和文件夹数量进行客户端过滤。
    """
    return [
        task
        for task in rows
        if task_matches_filters(
            task,
            folder_id=folder_id,
            remark=remark,
            creator_email=creator_email,
            unfiled=unfiled,
            multi_folder=multi_folder,
        )
    ]


def apply_patent_filters(
    response: Dict[str, Any],
    *,
    folder_id: int | None = None,
    remark: str | None = None,
    creator_email: str | None = None,
    unfiled: bool = False,
    multi_folder: bool = False,
) -> Dict[str, Any]:
    """关键参数：(response: Dict[str, Any], 筛选条件)
    返回值：Dict[str, Any]
    描述：对专利列表响应应用客户端过滤并返回新响应。
    """
    rows = patent_rows_from_response(response)
    filtered = filter_patent_rows(
        rows,
        folder_id=folder_id,
        remark=remark,
        creator_email=creator_email,
        unfiled=unfiled,
        multi_folder=multi_folder,
    )
    return with_patent_rows(response, filtered)


def has_client_filters(
    *,
    remark: str | None = None,
    creator_email: str | None = None,
    unfiled: bool = False,
    multi_folder: bool = False,
) -> bool:
    """关键参数：(remark/creator_email/unfiled/multi_folder)
    返回值：bool
    描述：判断是否启用了客户端过滤参数。
    """
    return bool(remark or creator_email or unfiled or multi_folder)


def parse_operation_datetime(value: str | None) -> datetime | None:
    """关键参数：(value: str | None)
    返回值：datetime | None
    描述：解析后端返回的最后操作时间，统一转换为 UTC。
    """
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_operation_filter_date(value: str | None, flag_name: str) -> date | None:
    """关键参数：(value: str | None, flag_name: str)
    返回值：date | None
    描述：解析用户输入的最后操作日期，只允许 YYYY-MM-DD 格式。
    """
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ClientError(f"{flag_name} must use date format {OPERATION_DATE_FORMAT_HINT}.")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ClientError(f"{flag_name} must use a valid date in format {OPERATION_DATE_FORMAT_HINT}.") from exc


def validate_last_operation_date_filters(
    *,
    last_operated_after: str | None = None,
    last_operated_before: str | None = None,
) -> None:
    """关键参数：(last_operated_after/last_operated_before)
    返回值：None
    描述：校验最后操作日期筛选参数，失败时给出用户可读错误。
    """
    parse_operation_filter_date(last_operated_after, "--last-operated-after")
    parse_operation_filter_date(last_operated_before, "--last-operated-before")


def latest_editor_record(editors_payload: Dict[str, Any]) -> tuple[Dict[str, Any] | None, datetime | None]:
    """关键参数：(editors_payload: Dict[str, Any])
    返回值：tuple[Dict[str, Any] | None, datetime | None]
    描述：从 editors 响应中选出最后一次操作记录。
    """
    data = editors_payload.get("data") if isinstance(editors_payload, dict) else None
    editors = data.get("editors") if isinstance(data, dict) else None
    if not isinstance(editors, list):
        return None, None

    latest_record: Dict[str, Any] | None = None
    latest_time: datetime | None = None
    for editor in editors:
        if not isinstance(editor, dict):
            continue
        operation_time = parse_operation_datetime(editor.get("last_operation_time"))
        if operation_time is None:
            continue
        if latest_time is None or operation_time > latest_time:
            latest_record = editor
            latest_time = operation_time
    return latest_record, latest_time


def task_matches_last_operation_filters(
    editors_payload: Dict[str, Any],
    *,
    last_operator: str | None = None,
    last_operated_after: str | None = None,
    last_operated_before: str | None = None,
) -> bool:
    """关键参数：(editors_payload: Dict[str, Any], last_operator/last_operated_after/last_operated_before)
    返回值：bool
    描述：根据最后操作人和最后操作时间范围判断任务是否匹配。
    """
    latest_record, latest_time = latest_editor_record(editors_payload)
    if latest_record is None or latest_time is None:
        return False

    if last_operator:
        operator_email = str(latest_record.get("user_email") or "")
        expected_operator = last_operator.casefold()
        if operator_email.casefold() != expected_operator and not operator_email.casefold().startswith(
            expected_operator
        ):
            return False

    after_date = parse_operation_filter_date(last_operated_after, "--last-operated-after")
    latest_date = latest_time.date()
    if after_date is not None and latest_date < after_date:
        return False

    before_date = parse_operation_filter_date(last_operated_before, "--last-operated-before")
    if before_date is not None and latest_date > before_date:
        return False

    return True


def has_last_operation_filters(
    *,
    last_operator: str | None = None,
    last_operated_after: str | None = None,
    last_operated_before: str | None = None,
) -> bool:
    """关键参数：(last_operator/last_operated_after/last_operated_before)
    返回值：bool
    描述：判断是否启用了最后操作相关筛选。
    """
    return bool(last_operator or last_operated_after or last_operated_before)
