"""Minimal SQLite persistence for PatSight tokens and job metadata (optional)."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


def _default_db_path() -> str:
    raw = (
        os.environ.get("PATSIGHT_CLI_CLIENT_DB")
        or os.environ.get("XCLI_CLIENT_DB")
        or os.environ.get("PATSIGHT_CLIENT_DB")
        or ""
    ).strip()
    if raw:
        return os.path.expanduser(raw)
    return str(Path.home() / ".local" / "share" / "patsight-cli" / "tasks.db")


def utcnow() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


class JobStatusEnum(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass
class JobRecord:
    job_id: str
    client_type: str
    job_type: str
    input_json: str
    remote_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    notify_target: Optional[str] = None
    last_error: Optional[str] = None


class JobStore:
    """SQLite store for credentials and submitted job rows (used by PatSight client and CLI)."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self) -> None:
        with self.conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs(
                    job_id TEXT PRIMARY KEY,
                    client_type TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    remote_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    notify_target TEXT,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials(
                    client_key TEXT PRIMARY KEY,
                    token TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_client ON jobs(client_type)")

    def get_token(self, client_key: str) -> Optional[str]:
        with self.conn() as conn:
            row = conn.execute(
                "SELECT token FROM credentials WHERE client_key=?",
                (client_key,),
            ).fetchone()
        return row["token"] if row else None

    def save_token(self, client_key: str, token: str) -> None:
        now = utcnow()
        with self.conn() as conn:
            conn.execute(
                """
                INSERT INTO credentials(client_key, token, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(client_key) DO UPDATE SET
                    token=excluded.token,
                    updated_at=excluded.updated_at
                """,
                (client_key, token, now),
            )

    def create_job(
        self,
        *,
        job_id: str,
        client_type: str,
        job_type: str,
        input_json: str,
        remote_id: Optional[str] = None,
        status: str = JobStatusEnum.PENDING.value,
        notify_target: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> None:
        now = utcnow()
        with self.conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs(
                    job_id, client_type, job_type, input_json, remote_id, status,
                    created_at, updated_at, started_at, finished_at,
                    notify_target, last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    client_type=excluded.client_type,
                    job_type=excluded.job_type,
                    input_json=excluded.input_json,
                    remote_id=excluded.remote_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    notify_target=excluded.notify_target,
                    last_error=excluded.last_error
                """,
                (
                    job_id,
                    client_type,
                    job_type,
                    input_json,
                    remote_id,
                    status,
                    now,
                    now,
                    None,
                    None,
                    notify_target,
                    last_error,
                ),
            )

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self.conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return JobRecord(**dict(row)) if row else None

    def get_job_by_remote_id(
        self, remote_id: str, client_type: Optional[str] = None
    ) -> Optional[JobRecord]:
        with self.conn() as conn:
            if client_type:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE remote_id=? AND client_type=?",
                    (remote_id, client_type),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE remote_id=?",
                    (remote_id,),
                ).fetchone()
        return JobRecord(**dict(row)) if row else None
