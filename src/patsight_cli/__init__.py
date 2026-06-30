"""
patsight-cli: multi-service CLI and Python library with a pluggable remote-job client registry.

The PatSight patent extraction backend lives under ``patsight_cli.clients.patsight`` and registers as client type ``patsight``.
"""

from __future__ import annotations

import patsight_cli.clients  # noqa: F401 — register built-ins

from patsight_cli.base import RemoteJobClient
from patsight_cli.clients.patsight import (
    JOB_TYPE_TO_API_ACTION,
    PatSightClient,
    PatSightConfig,
    job_type_to_api_action,
)
from patsight_cli.models import JobResult, JobStatus, JobSubmission
from patsight_cli.registry import ClientRegistry
from patsight_cli.reporting import generate_patsight_report

__version__ = "0.1.1"

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
