from __future__ import annotations

from patsight_cli.exceptions import SubmitError


def normalize_pdf_slice(value: str) -> str:
    """Normalize user input to API ``pdf_slice`` format."""
    return value.replace("，", ",").replace(" ", "").strip()


def _action_count(api_action: str) -> int:
    return len([part for part in str(api_action).split(",") if part.strip()])


def _validate_page_range(part: str) -> None:
    for item in part.split(","):
        token = item.strip()
        if not token:
            raise SubmitError("Invalid page range: empty segment in pdf_slice")
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            try:
                start = int(start_text)
                end = int(end_text)
            except ValueError as exc:
                raise SubmitError(f"Invalid page range format: {token}") from exc
            if start <= 0 or end <= 0:
                raise SubmitError(f"Page numbers must be positive: {token}")
            if start > end:
                raise SubmitError(f"Invalid page range: {token}")
        else:
            try:
                page = int(token)
            except ValueError as exc:
                raise SubmitError(f"Invalid page number: {token}") from exc
            if page <= 0:
                raise SubmitError(f"Page numbers must be positive: {token}")


def validate_pdf_slice(pdf_slice: str, api_action: str) -> str:
    """Validate and normalize ``pdf_slice`` for the given API action string."""
    normalized = normalize_pdf_slice(pdf_slice)
    if not normalized:
        return ""

    if _action_count(api_action) > 1:
        parts = normalized.split(";")
        if len(parts) > 2:
            raise SubmitError(
                "For composite job types, pdf_slice should have at most two parts "
                "separated by semicolon (e.g. '1-5,7;9-12,15')."
            )
        for part in parts:
            if part.strip():
                _validate_page_range(part.strip())
    else:
        _validate_page_range(normalized)

    return normalized


def resolve_pdf_slice(payload: dict, *, api_action: str) -> str:
    """Read ``pdf_slice`` / ``pages`` from a submit payload and validate it."""
    raw = payload.get("pdf_slice")
    if raw is None:
        raw = payload.get("pages")
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise SubmitError("pdf_slice/pages must be a string.")
    return validate_pdf_slice(raw, api_action)
