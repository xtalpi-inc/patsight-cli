"""验证专利列表客户端筛选逻辑。"""

from __future__ import annotations

from patsight_cli.patent_filters import (
    apply_patent_filters,
    filter_patent_rows,
    patent_rows_from_response,
    task_matches_last_operation_filters,
    validate_last_operation_date_filters,
)
from patsight_cli.exceptions import ClientError

import pytest


def sample_response() -> dict:
    """关键参数：无
    返回值：dict
    描述：构造包含备注、创建者和文件夹元数据的专利列表响应。
    """
    return {
        "code": 1,
        "data": {
            "count": 3,
            "task_info": [
                {
                    "id": 1,
                    "remarks": "Priority review",
                    "creator": "owner@example.com",
                    "folders": [{"id": 10, "path": "A"}],
                },
                {
                    "id": 2,
                    "remarks": "backup",
                    "creator": "other@example.com",
                    "folders": [],
                },
                {
                    "id": 3,
                    "remarks": "",
                    "creator": "owner@example.com",
                    "folders": [{"id": 10, "path": "A"}, {"id": 11, "path": "B"}],
                },
            ],
        },
        "error": "",
        "message": "",
    }


def test_patent_rows_from_response_extracts_task_info() -> None:
    """关键参数：无
    返回值：None
    描述：验证能从标准 tasks 响应中读取专利行。
    """
    assert [row["id"] for row in patent_rows_from_response(sample_response())] == [1, 2, 3]


def test_filter_patent_rows_by_remark_and_creator() -> None:
    """关键参数：无
    返回值：None
    描述：验证备注和创建者邮箱客户端筛选。
    """
    rows = patent_rows_from_response(sample_response())
    assert [row["id"] for row in filter_patent_rows(rows, remark="priority")] == [1]
    assert [row["id"] for row in filter_patent_rows(rows, creator_email="owner@example.com")] == [
        1,
        3,
    ]


def test_filter_patent_rows_by_folder_count() -> None:
    """关键参数：无
    返回值：None
    描述：验证未归档和多文件夹客户端筛选。
    """
    rows = patent_rows_from_response(sample_response())
    assert [row["id"] for row in filter_patent_rows(rows, unfiled=True)] == [2]
    assert [row["id"] for row in filter_patent_rows(rows, multi_folder=True)] == [3]


def test_apply_patent_filters_updates_count_without_mutating_original() -> None:
    """关键参数：无
    返回值：None
    描述：验证过滤响应会同步 count 且不修改原对象。
    """
    original = sample_response()
    filtered = apply_patent_filters(original, creator_email="owner@example.com", multi_folder=True)

    assert filtered["data"]["count"] == 1
    assert [row["id"] for row in filtered["data"]["task_info"]] == [3]
    assert original["data"]["count"] == 3


def test_task_matches_last_operation_filters() -> None:
    """关键参数：无
    返回值：None
    描述：验证最后操作人和最后操作时间筛选。
    """
    editors_payload = {
        "code": 1,
        "data": {
            "editors": [
                {
                    "user_email": "first@example.com",
                    "last_operation_time": "Thu, 25 Jun 2026 05:34:41 GMT",
                },
                {
                    "user_email": "last@example.com",
                    "last_operation_time": "Thu, 25 Jun 2026 06:34:41 GMT",
                },
            ]
        },
    }

    assert task_matches_last_operation_filters(
        editors_payload,
        last_operator="last@example.com",
        last_operated_after="2026-06-25",
        last_operated_before="2026-06-25",
    )
    assert not task_matches_last_operation_filters(editors_payload, last_operator="first@example.com")
    assert not task_matches_last_operation_filters(
        editors_payload,
        last_operated_after="2026-06-26",
    )


@pytest.mark.parametrize("value", ["2026-6-17", "2026-06-17T00:00:00Z", "20026-06-17"])
def test_validate_last_operation_date_filters_rejects_invalid_formats(value: str) -> None:
    """关键参数：(value: str)
    返回值：None
    描述：验证最后操作日期只接受 YYYY-MM-DD 格式。
    """
    with pytest.raises(ClientError, match="YYYY-MM-DD"):
        validate_last_operation_date_filters(last_operated_after=value)
