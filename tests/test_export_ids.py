from patsight_cli.export_ids import compound_rows_to_export_ids


def test_compound_rows_to_export_ids() -> None:
    rows = [
        {"id": 10, "property_id": 20},
        {"id": 11, "property_id": None},
        {"id": None, "property_id": 22},
        {"id": None, "property_id": None},
    ]
    assert compound_rows_to_export_ids(rows) == [
        {"property_id": 20, "structure_id": 10},
        {"structure_id": 11},
        {"property_id": 22},
    ]
