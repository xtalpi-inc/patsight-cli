import json
from unittest.mock import MagicMock

import pytest

from patsight_cli.clients.patsight import PatSightClient
from patsight_cli.store import JobRecord, JobStatusEnum
from patsight_cli.submit_cache import build_submit_cache_key, matches_submit_cache


def test_build_submit_cache_key_includes_job_type_and_pages() -> None:
    assert (
        build_submit_cache_key(
            file_name="WO2013190384A1_admet.pdf",
            job_type="structureAndActivity",
            pdf_slice="10-20",
            folder_id=17,
        )
        == "WO2013190384A1_admet.pdf|structureAndActivity|10-20|folder:17"
    )
    assert (
        build_submit_cache_key(
            file_name="WO2013190384A1_admet.pdf",
            job_type="iupac",
            pdf_slice="2-8",
        )
        == "WO2013190384A1_admet.pdf|iupac|2-8|folder:0"
    )


def test_matches_submit_cache_requires_all_fields() -> None:
    cached = {
        "file_name": "patent.pdf",
        "job_type": "structureAndActivity",
        "pdf_slice": "10-20",
        "folder_id": 17,
    }
    assert matches_submit_cache(
        cached,
        file_name="patent.pdf",
        job_type="structureAndActivity",
        pdf_slice="10-20",
        folder_id=17,
    )
    assert not matches_submit_cache(
        cached,
        file_name="patent.pdf",
        job_type="iupac",
        pdf_slice="10-20",
        folder_id=17,
    )
    assert not matches_submit_cache(
        cached,
        file_name="patent.pdf",
        job_type="structureAndActivity",
        pdf_slice="2-8",
        folder_id=17,
    )
    assert not matches_submit_cache(
        cached,
        file_name="patent.pdf",
        job_type="structureAndActivity",
        pdf_slice="10-20",
        folder_id=0,
    )


def _make_client_with_store(store: MagicMock) -> PatSightClient:
    client = PatSightClient.__new__(PatSightClient)
    client.client_type = "patsight"
    client.folder_id = 0
    client.job_store = store
    client.create_job = MagicMock()
    return client


def test_submit_job_cache_miss_for_different_job_type() -> None:
    store = MagicMock()
    store.get_job_by_remote_id.return_value = None
    client = _make_client_with_store(store)
    client.create_job.return_value = {
        "job_id": "new-job",
        "file_name": "patent.pdf",
        "job_type": "iupac",
        "pdf_slice": "2-8",
    }

    result = client.submit_job(
        {
            "pdf_path": "/tmp/patent.pdf",
            "job_type": "iupac",
            "pages": "2-8",
        }
    )

    store.get_job_by_remote_id.assert_called_once_with(
        "patent.pdf|iupac|2-8|folder:0",
        "patsight",
    )
    client.create_job.assert_called_once()
    assert result["job_id"] == "new-job"


def test_submit_job_cache_hit_only_for_matching_job_type_and_pages() -> None:
    store = MagicMock()
    cached_payload = {
        "job_id": "cached-job",
        "file_name": "patent.pdf",
        "job_type": "structureAndActivity",
        "pdf_slice": "10-20",
        "folder_id": 17,
        "status": "submitted",
    }
    store.get_job_by_remote_id.return_value = JobRecord(
        job_id="cached-job",
        client_type="patsight",
        job_type="structureAndActivity",
        input_json=json.dumps(cached_payload),
        remote_id="patent.pdf|structureAndActivity|10-20|folder:17",
        status=JobStatusEnum.PENDING.value,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    client = _make_client_with_store(store)

    hit = client.submit_job(
        {
            "pdf_path": "/tmp/patent.pdf",
            "job_type": "structureAndActivity",
            "pages": "10-20",
            "folder_id": 17,
        }
    )
    miss = client.submit_job(
        {
            "pdf_path": "/tmp/patent.pdf",
            "job_type": "iupac",
            "pages": "2-8",
        }
    )

    assert hit == cached_payload
    client.create_job.assert_called_once()
    assert miss["job_id"] == client.create_job.return_value["job_id"]


def test_submit_job_cache_miss_for_different_folder_id() -> None:
    store = MagicMock()
    cached_payload = {
        "job_id": "cached-personal",
        "file_name": "patent.pdf",
        "job_type": "structureAndActivity",
        "pdf_slice": "10-20",
        "folder_id": 0,
    }
    store.get_job_by_remote_id.return_value = None
    client = _make_client_with_store(store)
    client.create_job.return_value = {
        "job_id": "shared-job",
        "file_name": "patent.pdf",
        "job_type": "structureAndActivity",
        "pdf_slice": "10-20",
        "folder_id": 17,
    }

    assert not matches_submit_cache(
        cached_payload,
        file_name="patent.pdf",
        job_type="structureAndActivity",
        pdf_slice="10-20",
        folder_id=17,
    )

    result = client.submit_job(
        {
            "pdf_path": "/tmp/patent.pdf",
            "job_type": "structureAndActivity",
            "pages": "10-20",
            "folder_id": 17,
        }
    )

    store.get_job_by_remote_id.assert_called_once_with(
        "patent.pdf|structureAndActivity|10-20|folder:17",
        "patsight",
    )
    client.create_job.assert_called_once()
    assert result["folder_id"] == 17


def test_submit_job_does_not_hit_legacy_filename_only_cache_key() -> None:
    store = MagicMock()
    store.get_job_by_remote_id.return_value = None
    client = _make_client_with_store(store)
    client.create_job.return_value = {
        "job_id": "new-job",
        "file_name": "patent.pdf",
        "job_type": "iupac",
        "pdf_slice": "2-8",
    }

    result = client.submit_job(
        {
            "pdf_path": "/tmp/patent.pdf",
            "job_type": "iupac",
            "pages": "2-8",
        }
    )

    store.get_job_by_remote_id.assert_called_once_with(
        "patent.pdf|iupac|2-8|folder:0", "patsight"
    )
    client.create_job.assert_called_once()
    assert result["job_id"] == "new-job"
