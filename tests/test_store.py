"""验证 PatSight CLI 本地 SQLite 持久化行为。"""

from __future__ import annotations

from pathlib import Path

from patsight_cli.store import JobStatusEnum, JobStore


def test_job_store_saves_token_and_job_metadata(tmp_path: Path) -> None:
    """
    参数：(tmp_path: Path)
    返回值：None
    描述：验证 token 和任务元数据可写入并读取。
    """
    store = JobStore(db_path=str(tmp_path / "tasks.db"))

    store.save_token("patsight:default", "token-001")
    store.create_job(
        job_id="job-001",
        client_type="patsight",
        job_type="structureAndActivity",
        input_json='{"job_id": "job-001"}',
        remote_id="demo.pdf",
        status=JobStatusEnum.PENDING.value,
    )

    job = store.get_job("job-001")
    cached = store.get_job_by_remote_id("demo.pdf", "patsight")

    assert store.get_token("patsight:default") == "token-001"
    assert job is not None
    assert job.status == JobStatusEnum.PENDING.value
    assert cached is not None
    assert cached.job_id == "job-001"


def test_job_store_updates_existing_job(tmp_path: Path) -> None:
    """
    参数：(tmp_path: Path)
    返回值：None
    描述：验证重复 job_id 会更新已有任务记录。
    """
    store = JobStore(db_path=str(tmp_path / "tasks.db"))

    store.create_job(
        job_id="job-002",
        client_type="patsight",
        job_type="reaction",
        input_json="{}",
        remote_id="old.pdf",
        status=JobStatusEnum.PENDING.value,
    )
    store.create_job(
        job_id="job-002",
        client_type="patsight",
        job_type="reaction",
        input_json='{"updated": true}',
        remote_id="new.pdf",
        status=JobStatusEnum.DONE.value,
    )

    job = store.get_job("job-002")

    assert job is not None
    assert job.remote_id == "new.pdf"
    assert job.status == JobStatusEnum.DONE.value
