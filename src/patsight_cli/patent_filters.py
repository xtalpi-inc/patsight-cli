"""专利列表客户端筛选工具，复用新版 tasks 响应中的备注、创建者和文件夹元数据。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List


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


def task_matches_filters(
    task: Dict[str, Any],
    *,
    remark: str | None = None,
    creator_email: str | None = None,
    unfiled: bool = False,
    multi_folder: bool = False,
) -> bool:
    """关键参数：(task: Dict[str, Any], remark/creator_email/unfiled/multi_folder)
    返回值：bool
    描述：判断单条专利是否满足客户端筛选条件。
    """
    if remark:
        remarks = str(task.get("remarks") or "")
        if remark.casefold() not in remarks.casefold():
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
    remark: str | None = None,
    creator_email: str | None = None,
    unfiled: bool = False,
    multi_folder: bool = False,
) -> List[Dict[str, Any]]:
    """关键参数：(rows: Iterable[Dict[str, Any]], 筛选条件)
    返回值：List[Dict[str, Any]]
    描述：按备注、创建者和文件夹数量进行客户端过滤。
    """
    return [
        task
        for task in rows
        if task_matches_filters(
            task,
            remark=remark,
            creator_email=creator_email,
            unfiled=unfiled,
            multi_folder=multi_folder,
        )
    ]


def apply_patent_filters(
    response: Dict[str, Any],
    *,
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
