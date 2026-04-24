from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class JobSubmission:
    job_id: str
    raw: Any = None


@dataclass
class JobStatus:
    job_id: str
    status: str
    detail: str = ""
    raw: Any = None


@dataclass
class JobResult:
    job_id: str
    result: Any = None
    output_path: Optional[str] = None
    raw: Any = None


@dataclass
class ClientContext:
    name: str = "default"
    params: Dict[str, Any] = field(default_factory=dict)
