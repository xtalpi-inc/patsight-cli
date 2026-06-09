from patsight_cli.export_filename import export_filename, export_label


def test_export_label_structure_and_activity() -> None:
    assert export_label("structureAndActivity", "bioactivity") == "Structure and Activity"
    assert export_label("structureAndActivity", "admet") == "Structure and Activity"
    assert export_label("structureAndActivity", "namedStructures") == "Structure and Activity"
    assert export_label("structure", "structures") == "Structure and Activity"


def test_export_label_iupac() -> None:
    assert export_label("iupac", "structures") == "IUPAC"
    assert export_label("iupacAndStructure", "structures") == "IUPAC"


def test_export_label_reaction() -> None:
    assert export_label("reaction", "reactions") == "Reaction"
    assert export_label("structureAndActivityReaction", "reactions") == "Reaction"


def test_export_filename_structure_and_activity() -> None:
    assert (
        export_filename(
            job_type="structureAndActivity",
            export_type="bioactivity",
            file_format="csv",
            file_name="WO2004087707-part.pdf",
        )
        == "WO2004087707-part.pdf-Structure and Activity.csv"
    )


def test_export_filename_iupac() -> None:
    assert (
        export_filename(
            job_type="iupac",
            export_type="structures",
            file_format="sdf",
            file_name="patent.pdf",
        )
        == "patent.pdf-IUPAC.sdf"
    )


def test_export_filename_reaction() -> None:
    assert (
        export_filename(
            job_type="reaction",
            export_type="reactions",
            file_format="xlsx",
            file_name="patent.pdf",
        )
        == "patent.pdf-Reaction.xlsx"
    )


def test_export_filename_fallback_to_task_id() -> None:
    assert (
        export_filename(
            job_type="structureAndActivity",
            export_type="bioactivity",
            file_format="csv",
            task_id="task-123",
        )
        == "task-123-Structure and Activity.csv"
    )
