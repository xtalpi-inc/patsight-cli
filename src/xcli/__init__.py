"""
xcli: multi-service CLI and Python library with a pluggable remote-job client registry.

The PatSight patent extraction backend lives under ``xcli.clients.patsight`` and registers as client type ``patsight``.
"""

from __future__ import annotations

import xcli.clients  # noqa: F401 — register built-ins

from xcli.base import RemoteJobClient
from xcli.clients.patsight import (
    JOB_TYPE_TO_API_ACTION,
    PatSightClient,
    PatSightConfig,
    job_type_to_api_action,
)
from xcli.models import JobResult, JobStatus, JobSubmission
from xcli.registry import ClientRegistry
from xcli.reporting import generate_patsight_report

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "ClientRegistry",
    "RemoteJobClient",
    "PatSightClient",
    "PatSightConfig",
    "JOB_TYPE_TO_API_ACTION",
    "job_type_to_api_action",
    "JobSubmission",
    "JobStatus",
    "JobResult",
    "generate_patsight_report",
]
