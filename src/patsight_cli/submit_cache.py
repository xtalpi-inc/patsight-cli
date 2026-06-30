from __future__ import annotations

from typing import Any, Dict


def build_submit_cache_key(
    *,
    file_name: str,
    job_type: str,
    pdf_slice: str = "",
    folder_id: int = 0,
) -> str:
    """Composite cache key: same patent + type + pages + folder = same submission."""
    return f"{file_name}|{job_type}|{pdf_slice or ''}|folder:{int(folder_id)}"


def matches_submit_cache(
    cached_input: Dict[str, Any],
    *,
    file_name: str,
    job_type: str,
    pdf_slice: str = "",
    folder_id: int = 0,
) -> bool:
    return (
        cached_input.get("file_name") == file_name
        and cached_input.get("job_type") == job_type
        and (cached_input.get("pdf_slice") or "") == (pdf_slice or "")
        and int(cached_input.get("folder_id") or 0) == int(folder_id)
    )
