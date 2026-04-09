from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from xcli.models import JobResult, JobStatus, JobSubmission
from xcli.registry import ClientRegistry


class RemoteJobClient(ABC):
    """Abstract remote job client. Subclass and register with `ClientRegistry`."""

    client_type: str = "base"

    def __init__(
        self,
        name: str = "default",
        workdir: str = "",
        job_store: Any = None,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.workdir = workdir
        self.job_store = job_store
        Path(self.workdir).mkdir(parents=True, exist_ok=True)
        self.config = kwargs

    @classmethod
    def create(cls, client_type: str, **kwargs: Any) -> RemoteJobClient:
        return ClientRegistry.create(client_type, **kwargs)

    @abstractmethod
    def login(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def submit_job(self, payload: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def query_status(self, job_id: str, job_type: str = "") -> JobStatus:
        raise NotImplementedError

    @abstractmethod
    def fetch_result(self, job_id: str, **kwargs: Any) -> JobResult:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, client_type={self.client_type!r})"
