import pytest

from patsight_cli.exceptions import SubmitError
from patsight_cli.pdf_slice import (
    normalize_pdf_slice,
    resolve_pdf_slice,
    validate_pdf_slice,
)


def test_normalize_pdf_slice() -> None:
    assert normalize_pdf_slice(" 1-3 , 5 ") == "1-3,5"
    assert normalize_pdf_slice("1，3") == "1,3"


def test_validate_single_action() -> None:
    assert validate_pdf_slice("1-5,7,9-12", "0") == "1-5,7,9-12"
    assert validate_pdf_slice("", "0") == ""


def test_validate_composite_action() -> None:
    assert validate_pdf_slice("1-3;4-6", "0,1") == "1-3;4-6"


def test_validate_rejects_invalid_range() -> None:
    with pytest.raises(SubmitError, match="Invalid page range"):
        validate_pdf_slice("5-3", "0")


def test_validate_rejects_too_many_composite_parts() -> None:
    with pytest.raises(SubmitError, match="at most two parts"):
        validate_pdf_slice("1-3;4-6;7-9", "0,1")


def test_resolve_pdf_slice_prefers_pdf_slice_key() -> None:
    payload = {"pdf_slice": "1-3", "pages": "4-6"}
    assert resolve_pdf_slice(payload, api_action="0") == "1-3"


def test_resolve_pdf_slice_accepts_pages_alias() -> None:
    payload = {"pages": "1-3"}
    assert resolve_pdf_slice(payload, api_action="2") == "1-3"
