import pytest

from patsight_cli.exceptions import ExportError
from patsight_cli.export_filename import export_filename


def test_export_filename_uses_file_name_and_export_type() -> None:
    assert (
        export_filename(
            export_type="bioactivity",
            file_format="csv",
            file_name="WO2004087707-part.pdf",
        )
        == "WO2004087707-part.pdf-bioactivity.csv"
    )


def test_export_filename_named_structures() -> None:
    assert (
        export_filename(
            export_type="namedStructures",
            file_format="xlsx",
            file_name="WO2024102924A1",
        )
        == "WO2024102924A1-namedStructures.xlsx"
    )


def test_export_filename_sanitizes_path_separators() -> None:
    assert (
        export_filename(
            export_type="reactions",
            file_format="json",
            file_name="folder/patent.pdf",
        )
        == "folder_patent.pdf-reactions.json"
    )


def test_export_filename_requires_file_name() -> None:
    with pytest.raises(ExportError, match="file_name is required"):
        export_filename(export_type="bioactivity", file_format="csv", file_name="")
