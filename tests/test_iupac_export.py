from unittest.mock import MagicMock, patch

import pytest

from patsight_cli.clients.patsight import PatSightClient


def _make_export_client() -> PatSightClient:
    client = PatSightClient.__new__(PatSightClient)
    client.config = MagicMock()
    client.config.base_url = "https://example.com/patent/api"
    client.workdir = "/tmp/patsight-cli-test"
    client._request = MagicMock()
    client._parse_json_response = MagicMock(return_value={})
    return client


def test_export_task_iupac_uses_structures_endpoint_ids() -> None:
    client = _make_export_client()
    client.list_structure_export_ids = MagicMock(
        return_value=[{"structure_id": 101, "property_id": None}]
    )
    client.list_compound_export_ids = MagicMock()

    response = MagicMock()
    response.content = b"Index,Structure,IUPAC Name\n"
    response.encoding = "utf-8"
    response.text = "Index,Structure,IUPAC Name\n"
    client._request.return_value = response

    with patch("patsight_cli.clients.patsight.Path") as path_cls:
        path_instance = MagicMock()
        path_cls.return_value = path_instance
        path_cls.mkdir = MagicMock()
        client.export_task(
            "2036346255269044224",
            job_type="iupac",
            file_format="csv",
            file_name="patent.pdf",
            task_action="6",
        )

    client.list_structure_export_ids.assert_called_once_with("2036346255269044224")
    client.list_compound_export_ids.assert_not_called()

    call_args = client._request.call_args
    assert call_args[0][0] == "POST"
    assert call_args[0][1].endswith("/v3/extractor/task/2036346255269044224/export")
    assert call_args[1]["json"] == {
        "file_type": "csv",
        "ids": [{"structure_id": 101, "property_id": None}],
    }
    assert "bioactivity_data_type" not in call_args[1]["json"]
