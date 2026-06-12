from __future__ import annotations

from typing import Optional

JobTypeSlug = str
ExportType = str
FileFormat = str


def export_label(job_type: JobTypeSlug, export_type: ExportType) -> str:
    """Human-readable export label aligned with xinsight-patent-front."""
    if export_type == "reactions":
        return "Reaction"
    if job_type in {"iupac", "iupacAndStructure"}:
        return "IUPAC"
    return "Structure and Activity"


def _sanitize_base_name(value: str) -> str:
    name = value.strip()
    if not name:
        return ""
    return name.replace("/", "_").replace("\\", "_")


def export_filename(
    *,
    job_type: JobTypeSlug,
    export_type: ExportType,
    file_format: FileFormat,
    file_name: Optional[str] = None,
    task_id: Optional[str] = None,
) -> str:
    """Build export filename matching xinsight-patent-front download naming."""
    base = _sanitize_base_name(file_name or "")
    if not base:
        base = _sanitize_base_name(task_id or "") or "export"
    label = export_label(job_type, export_type)
    return f"{base}-{label}.{file_format}"
