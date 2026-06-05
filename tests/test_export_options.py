import pytest

from patsight_cli.exceptions import ExportError
from patsight_cli.export_options import (
    default_export_options,
    resolve_export_options,
)


def test_default_export_options() -> None:
    assert default_export_options("structureAndActivity") == ("bioactivity", "csv")
    assert default_export_options("reaction") == ("reactions", "xlsx")
    assert default_export_options("iupac") == ("structures", "csv")


def test_resolve_structure_and_activity_exports() -> None:
    assert resolve_export_options("structureAndActivity", "admet", "xlsx") == ("admet", "xlsx")
    assert resolve_export_options("structureAndActivity", "namedStructures", "sdf") == (
        "namedStructures",
        "sdf",
    )


def test_resolve_reaction_export_defaults() -> None:
    assert resolve_export_options("reaction") == ("reactions", "xlsx")
    assert resolve_export_options("reaction", "reactions", "json") == ("reactions", "json")


def test_reject_mismatched_export_type() -> None:
    with pytest.raises(ExportError, match="not supported for job_type 'reaction'"):
        resolve_export_options("reaction", "bioactivity", "csv")


def test_reject_mismatched_format() -> None:
    with pytest.raises(ExportError, match="format 'json' is not supported"):
        resolve_export_options("structureAndActivity", "bioactivity", "json")


def test_combined_job_supports_reactions() -> None:
    assert resolve_export_options("structureAndActivityReaction", "reactions", "xlsx") == (
        "reactions",
        "xlsx",
    )
