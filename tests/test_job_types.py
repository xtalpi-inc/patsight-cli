import xcli  # noqa: F401
from xcli.clients.patsight import (
    JOB_TYPE_TO_API_ACTION,
    api_action_to_job_type,
    job_type_to_api_action,
    normalize_api_action_string,
)


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
