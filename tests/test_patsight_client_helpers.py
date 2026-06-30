"""验证 PatSight 客户端无需网络的核心辅助逻辑。"""

from __future__ import annotations

import pytest

from patsight_cli.clients.patsight import (
    VIEW1_JOB_TYPES,
    coerce_job_type_slug,
    format_statistics_summary,
    normalize_status,
    safe_extract_ids_from_url,
)
from patsight_cli.exceptions import SubmitError


def test_safe_extract_ids_from_presigned_url() -> None:
    """
    参数：无
    返回值：None
    描述：验证预签名 URL 可解析任务关联 ID 和文档 ID。
    """
    job_like_id, doc_id = safe_extract_ids_from_url(
        "https://bucket.example.com/doc-only-123/demo-file.pdf?token=abc"
    )

    assert job_like_id == "doc-only-123"
    assert doc_id == "demo-file"


def test_safe_extract_ids_handles_invalid_values() -> None:
    """
    参数：无
    返回值：None
    描述：验证空值或无效路径不会抛出异常。
    """
    assert safe_extract_ids_from_url(None) == (None, None)
    assert safe_extract_ids_from_url("https://bucket.example.com/file.pdf") == (None, None)


def test_coerce_job_type_slug_rejects_unknown_value() -> None:
    """
    参数：无
    返回值：None
    描述：验证未知任务类型会给出明确错误。
    """
    with pytest.raises(SubmitError, match="Unknown job_type"):
        coerce_job_type_slug("unknown")


def test_view1_job_types_cover_iupac_family() -> None:
    """
    参数：无
    返回值：None
    描述：验证 IUPAC/结构任务会走 view=1 查询入口。
    """
    assert VIEW1_JOB_TYPES == frozenset({"iupac", "structure", "iupacAndStructure"})


def test_status_and_statistics_normalization() -> None:
    """
    参数：无
    返回值：None
    描述：验证状态和统计摘要能稳定归一化。
    """
    statistics = {
        "data": {
            "structures": {"total": 5},
            "named_structures": {"total": 3, "with_properties": 2},
            "properties": {"total": 9, "with_structures": 4},
        }
    }

    assert normalize_status(" Done ") == "done"
    assert format_statistics_summary(statistics) == (
        "structures_total=5 | named_structures=3(with_properties=2) | "
        "properties=9(with_structures=4)"
    )
