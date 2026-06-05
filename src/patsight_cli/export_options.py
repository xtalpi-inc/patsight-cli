from __future__ import annotations

from typing import Dict, Optional, Tuple

from patsight_cli.exceptions import ExportError

ExportType = str
FileFormat = str
JobTypeSlug = str

# export_type -> allowed file formats
_EXPORT_MATRIX: Dict[JobTypeSlug, Dict[ExportType, Tuple[FileFormat, ...]]] = {
    "structureAndActivity": {
        "bioactivity": ("csv", "xlsx", "sdf"),
        "admet": ("csv", "xlsx", "sdf"),
        "namedStructures": ("csv", "xlsx", "sdf"),
    },
    "structureAndActivityReaction": {
        "bioactivity": ("csv", "xlsx", "sdf"),
        "admet": ("csv", "xlsx", "sdf"),
        "namedStructures": ("csv", "xlsx", "sdf"),
        "reactions": ("xlsx", "json"),
    },
    "structure": {
        "structures": ("csv", "xlsx", "sdf"),
    },
    "reaction": {
        "reactions": ("xlsx", "json"),
    },
    "iupac": {
        "structures": ("csv", "xlsx", "sdf"),
    },
    "iupacAndStructure": {
        "structures": ("csv", "xlsx", "sdf"),
    },
}

_DEFAULTS: Dict[JobTypeSlug, Tuple[ExportType, FileFormat]] = {
    "structureAndActivity": ("bioactivity", "csv"),
    "structureAndActivityReaction": ("bioactivity", "csv"),
    "structure": ("structures", "csv"),
    "reaction": ("reactions", "xlsx"),
    "iupac": ("structures", "csv"),
    "iupacAndStructure": ("structures", "csv"),
}

_EXPORT_TYPE_ALIASES: Dict[str, ExportType] = {
    "bioactivity": "bioactivity",
    "activity": "bioactivity",
    "admet": "admet",
    "namedstructures": "namedStructures",
    "named_structures": "namedStructures",
    "named-structures": "namedStructures",
    "reactions": "reactions",
    "reaction": "reactions",
    "synthesis": "reactions",
    "structures": "structures",
    "structure": "structures",
    "chemicalstructures": "structures",
    "chemical_structures": "structures",
}


def normalize_export_type(value: str) -> ExportType:
    key = str(value or "").strip()
    if not key:
        raise ExportError("export_type must not be empty.")
    normalized = _EXPORT_TYPE_ALIASES.get(key) or _EXPORT_TYPE_ALIASES.get(key.lower())
    if not normalized:
        raise ExportError(f"Unknown export_type {value!r}.")
    return normalized


def normalize_file_format(value: str) -> FileFormat:
    fmt = str(value or "").strip().lower()
    if fmt not in {"csv", "xlsx", "sdf", "json"}:
        raise ExportError(f"Unknown file format {value!r}.")
    return fmt


def default_export_options(job_type: JobTypeSlug) -> Tuple[ExportType, FileFormat]:
    if job_type not in _DEFAULTS:
        raise ExportError(f"Unsupported job_type for export: {job_type!r}.")
    return _DEFAULTS[job_type]


def resolve_export_options(
    job_type: JobTypeSlug,
    export_type: Optional[str] = None,
    file_format: Optional[str] = None,
) -> Tuple[ExportType, FileFormat]:
    if job_type not in _EXPORT_MATRIX:
        raise ExportError(f"Unsupported job_type for export: {job_type!r}.")

    default_type, default_format = default_export_options(job_type)
    resolved_type = normalize_export_type(export_type) if export_type else default_type
    allowed_types = _EXPORT_MATRIX[job_type]

    if resolved_type not in allowed_types:
        allowed = ", ".join(sorted(allowed_types))
        raise ExportError(
            f"export_type {resolved_type!r} is not supported for job_type {job_type!r}. "
            f"Allowed: {allowed}"
        )

    allowed_formats = allowed_types[resolved_type]
    if file_format:
        resolved_format = normalize_file_format(file_format)
    else:
        resolved_format = default_format if resolved_type == default_type else allowed_formats[0]

    if resolved_format not in allowed_formats:
        allowed = ", ".join(allowed_formats)
        raise ExportError(
            f"format {resolved_format!r} is not supported for export_type {resolved_type!r} "
            f"on job_type {job_type!r}. Allowed: {allowed}"
        )

    return resolved_type, resolved_format


def export_type_choices_for_job(job_type: JobTypeSlug) -> tuple[str, ...]:
    return tuple(sorted(_EXPORT_MATRIX.get(job_type, {}).keys()))


def format_choices_for(job_type: JobTypeSlug, export_type: ExportType) -> tuple[str, ...]:
    return _EXPORT_MATRIX.get(job_type, {}).get(export_type, ())
