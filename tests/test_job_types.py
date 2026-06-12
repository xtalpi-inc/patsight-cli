import pytest

import patsight_cli  # noqa: F401
from patsight_cli.clients.patsight import (
    JOB_TYPE_TO_API_ACTION,
    api_action_to_job_type,
    job_type_to_api_action,
    normalize_api_action_string,
    resolve_job_type_from_status,
    validate_export_job_match,
)
from patsight_cli.exceptions import ExportError
from patsight_cli.export_options import default_export_options


def test_job_type_to_api_action_table() -> None:
    assert job_type_to_api_action("structureAndActivity") == "0"
    assert job_type_to_api_action("reaction") == "1"
    assert job_type_to_api_action("structureAndActivityReaction") == "0,1"
    assert job_type_to_api_action("iupac") == "6"
    assert job_type_to_api_action("structure") == "2"
    assert job_type_to_api_action("iupacAndStructure") == "26"
    assert len(JOB_TYPE_TO_API_ACTION) == 6


def test_api_action_roundtrip() -> None:
    for jt in JOB_TYPE_TO_API_ACTION:
        a = job_type_to_api_action(jt)
        assert api_action_to_job_type(a) == jt


def test_legacy_action_alias() -> None:
    assert normalize_api_action_string("0,5") == "0"
    assert api_action_to_job_type("0,5") == "structureAndActivity"


def test_resolve_job_type_from_status_prefers_task_action() -> None:
    status = {
        "job_type": "structureAndActivity",
        "task_info": {"action": "6"},
    }
    assert resolve_job_type_from_status(status) == "iupac"


def test_resolve_job_type_from_status_honors_explicit_override() -> None:
    status = {"job_type": "iupac", "task_info": {"action": "6"}}
    assert resolve_job_type_from_status(status, explicit="structure") == "structure"


def test_iupac_default_export_type_is_structures() -> None:
    assert default_export_options("iupac") == ("structures", "csv")


def test_resolve_job_type_from_status_requires_action_or_slug() -> None:
    with pytest.raises(ExportError, match="Could not determine job_type"):
        resolve_job_type_from_status({"job_type": "", "task_info": {}})


def test_validate_export_job_match_rejects_iupac_export_on_compound_task() -> None:
    with pytest.raises(ExportError, match="IUPAC export expected CSV headers"):
        validate_export_job_match(
            resolved_job_type="iupac",
            resolved_export_type="structures",
            task_action="0",
        )


def test_validate_export_job_match_allows_iupac_task() -> None:
    validate_export_job_match(
        resolved_job_type="iupac",
        resolved_export_type="structures",
        task_action="6",
    )
