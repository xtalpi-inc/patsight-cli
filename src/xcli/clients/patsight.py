from __future__ import annotations

import base64
import json
import logging
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple
from urllib.parse import urlparse

import requests
from requests import Response, Session

from xcli.base import RemoteJobClient
from xcli.exceptions import (
    FetchResultError,
    JobNotFoundError,
    LoginError,
    QueryError,
    SubmitError,
)
from xcli.models import JobResult, JobStatus as RemoteJobStatus
from xcli.registry import ClientRegistry
from xcli.store import JobStatusEnum

logger = logging.getLogger(__name__)

_DEFAULT_PATSIGHT_ORIGIN = "https://patent.xinsight-ai.com"
_DEFAULT_OPS_ORIGIN = "https://xops.xtalpi.com"


def _origin(url: Optional[str], env_key: str, fallback: str) -> str:
    """Resolve origin: explicit arg > env > fallback; strip trailing slashes."""
    if url is not None and str(url).strip():
        return str(url).strip().rstrip("/")
    env_val = (os.environ.get(env_key) or "").strip()
    if env_val:
        return env_val.rstrip("/")
    return fallback.rstrip("/")


def patent_api_base(patsight_origin: str) -> str:
    return f"{patsight_origin.rstrip('/')}/patent/api"


def ops_token_endpoint(ops_origin: str) -> str:
    return f"{ops_origin.rstrip('/')}/api/v2/public/token"


def ops_verify_endpoint(ops_origin: str) -> str:
    return f"{ops_origin.rstrip('/')}/api/public/token/verify"


def _default_workdir() -> str:
    raw = (os.environ.get("XCLI_WORKDIR") or os.environ.get("PATSIGHT_WORKDIR") or "").strip()
    if raw:
        return os.path.expanduser(raw)
    return str(Path.home() / ".local" / "share" / "xcli" / "output")


DEFAULT_WORKDIR = _default_workdir()

RETRY_STATUS = {429, 500, 502, 503, 504}
AUTH_STATUS = {401, 403}
SUCCESS_JOB_STATUS = {"done", "completed", "success", "finished"}
FAILED_JOB_STATUS = {"failed", "error", "cancelled", "canceled", "timeout"}

ResultType = Literal[
    "structureAndActivity",
    "reaction",
    "structureAndActivityReaction",
    "iupac",
    "structure",
    "iupacAndStructure",
]

# User-facing job_type slug -> API ``action`` string (PatSight extractor).
JOB_TYPE_TO_API_ACTION: Dict[ResultType, str] = {
    "structureAndActivity": "0",
    "reaction": "1",
    "structureAndActivityReaction": "0,1",
    "iupac": "6",
    "structure": "2",
    "iupacAndStructure": "26",
}

# API responses may still use legacy action values.
_API_ACTION_ALIASES: Dict[str, str] = {
    "0,5": "0",  # legacy alias for structureAndActivity
}


def normalize_api_action_string(action: str) -> str:
    a = str(action).strip()
    return _API_ACTION_ALIASES.get(a, a)


def api_action_to_job_type(action: str) -> ResultType:
    """Map API task ``action`` field to our ``job_type`` slug."""
    a = normalize_api_action_string(action)
    for jt, api_a in JOB_TYPE_TO_API_ACTION.items():
        if api_a == a:
            return jt
    return "structureAndActivity"


def job_type_to_api_action(job_type: ResultType) -> str:
    return JOB_TYPE_TO_API_ACTION[job_type]


def coerce_job_type_slug(value: Any) -> ResultType:
    s = str(value).strip()
    if s not in JOB_TYPE_TO_API_ACTION:
        allowed = ", ".join(sorted(JOB_TYPE_TO_API_ACTION.keys()))
        raise SubmitError(f"Unknown job_type {s!r}. Use one of: {allowed}")
    return s  # type: ignore[return-value]


CLI_JOB_TYPE_CHOICES: tuple[str, ...] = tuple(sorted(JOB_TYPE_TO_API_ACTION.keys()))

# PatSight task list: view=1 for IUPAC/structure family; view=0 for structure/reaction/combined
VIEW1_JOB_TYPES: frozenset[str] = frozenset({"iupac", "structure", "iupacAndStructure"})


class PatSightError(RuntimeError):
    pass


class PatSightAuthError(PatSightError):
    pass


class PatSightJobNotFoundError(PatSightError):
    pass


class PatSightJobNotFinishedError(PatSightError):
    pass


class PatSightTimeoutError(PatSightError):
    pass


@dataclass(frozen=True)
class PatSightConfig:
    """API and UI origins: patent API is ``{patsight_origin}/patent/api``; OPS paths under ``ops_origin``."""

    patsight_origin: str
    base_url: str
    ops_token_url: str
    verify_url: str
    default_folder_id: int = 0
    timeout_connect: float = 10.0
    timeout_read: float = 180.0
    max_retries: int = 5
    backoff_base: float = 1.2
    user_agent: str = "xcli/0.1 (patsight)"
    create_job_poll_interval: float = 3.0
    create_job_poll_attempts: int = 15
    list_tasks_per_page: int = 50
    list_tasks_max_pages: int = 500


def encode_credential_from_password(password: str) -> str:
    return base64.b64encode(password.encode("utf-8")).decode("utf-8")


def safe_extract_ids_from_url(url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not url:
        return None, None
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            return None, None
        file_name = parts[-1]
        doc_id = os.path.splitext(file_name)[0] if file_name else None
        job_like_id = parts[-2]
        return job_like_id, doc_id
    except Exception:
        logger.exception("Failed to extract ids from url: %s", url)
        return None, None


def normalize_status(status: Optional[str]) -> str:
    return str(status or "").strip().lower()


def format_statistics_summary(statistics_info: Dict[str, Any]) -> str:
    if not isinstance(statistics_info, dict):
        return "No statistics"
    data = statistics_info.get("data") or statistics_info
    if not data:
        return "No statistics"
    parts = []
    structures = data.get("structures") or {}
    total_s = structures.get("total")
    if total_s is not None:
        parts.append(f"structures_total={total_s}")
    named = data.get("named_structures") or {}
    total_n = named.get("total")
    if total_n is not None:
        with_p = named.get("with_properties")
        parts.append(
            f"named_structures={total_n}"
            + (f"(with_properties={with_p})" if with_p is not None else "")
        )
    props = data.get("properties") or {}
    total_p = props.get("total")
    if total_p is not None:
        with_s = props.get("with_structures")
        parts.append(
            f"properties={total_p}" + (f"(with_structures={with_s})" if with_s is not None else "")
        )
    return " | ".join(parts) if parts else "No key figures"


@ClientRegistry.register("patsight")
class PatSightClient(RemoteJobClient):
    def __init__(
        self,
        name: str = "patsight",
        account: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        folder_id: Optional[int] = None,
        patsight_url: Optional[str] = None,
        ops_url: Optional[str] = None,
        base_url: Optional[str] = None,
        ops_token_url: Optional[str] = None,
        verify_url: Optional[str] = None,
        session: Optional[Session] = None,
        workdir: str = DEFAULT_WORKDIR,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, workdir=workdir, **kwargs)

        patsight_origin = _origin(patsight_url, "PATSIGHT_URL", _DEFAULT_PATSIGHT_ORIGIN)
        ops_origin = _origin(ops_url, "OPS_URL", _DEFAULT_OPS_ORIGIN)
        resolved_base = base_url or patent_api_base(patsight_origin)
        resolved_ops_token = ops_token_url or ops_token_endpoint(ops_origin)
        resolved_verify = verify_url or ops_verify_endpoint(ops_origin)

        self.config = PatSightConfig(
            patsight_origin=patsight_origin,
            base_url=resolved_base,
            ops_token_url=resolved_ops_token,
            verify_url=resolved_verify,
            default_folder_id=int(folder_id or 0),
        )
        self.account = (
            account
            or os.environ.get("PATSIGHT_OPS_ACCOUNT")
            or os.environ.get("PATSIGHT_ACCOUNT")
        )
        self.password = (
            password
            or os.environ.get("PATSIGHT_OPS_PASSWORD")
            or os.environ.get("PATSIGHT_PASSWORD")
        )
        self.token = (
            token
            or os.environ.get("PATSIGHT_TOKEN")
            or (
                self.job_store.get_token(f"patsight:{self.name}")
                if getattr(self, "job_store", None)
                else None
            )
        )
        self.folder_id = self.config.default_folder_id

        self.presigned_url = f"{self.config.base_url}/v1/u/presigned_url"
        self.create_url = f"{self.config.base_url}/v3/extractor/tasks/batch_create"
        self.tasks_url = f"{self.config.base_url}/v2/extractor/tasks"
        self.sess = session or requests.Session()
        self.sess.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": self.config.user_agent,
            }
        )
        self.login()

    def login(self) -> None:
        if self.token:
            try:
                verify_payload = self.verify_ops_token(self.token)
                if verify_payload.get("code") == 0:
                    self.sess.headers["Authorization"] = self.token
                    return
                logger.warning("Existing token invalid, refreshing.")
            except Exception as exc:
                logger.warning("Token verification failed, refreshing token: %s", exc)

        if not self.account or not self.password:
            raise LoginError("Missing PatSight account or password.")
        logger.info("Logging in to PatSight with account: %s", self.account)
        token_payload = self.get_ops_token(account=self.account, password=self.password)
        token_val = (token_payload.get("data") or {}).get("token")
        if not token_val:
            raise LoginError(f"Token not found in OPS response: {token_payload}")

        self.token = token_val
        self.sess.headers["Authorization"] = token_val
        os.environ["PATSIGHT_TOKEN"] = token_val
        if getattr(self, "job_store", None):
            self.job_store.save_token(f"patsight:{self.name}", token_val)

    def refresh_token(self) -> None:
        self.token = None
        self.sess.headers.pop("Authorization", None)
        self.login()

    def submit_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        pdf_path = payload.get("pdf_path")
        if not pdf_path:
            raise SubmitError("submit_job payload must contain 'pdf_path'.")

        folder_id = int(payload.get("folder_id", self.folder_id))
        raw_jt = payload.get("job_type")
        legacy_action = payload.get("action")
        if raw_jt is not None and str(raw_jt).strip():
            job_type = coerce_job_type_slug(raw_jt)
        elif legacy_action is not None and str(legacy_action).strip():
            normalized = normalize_api_action_string(str(legacy_action).strip())
            job_type = api_action_to_job_type(normalized)
        else:
            job_type = "structureAndActivity"
        api_action = job_type_to_api_action(job_type)

        remote_id = Path(pdf_path).name
        if getattr(self, "job_store", None):
            existing = self.job_store.get_job_by_remote_id(remote_id, self.client_type)
            if existing and existing.input_json:
                try:
                    cached = json.loads(existing.input_json)
                    if isinstance(cached, dict):
                        print(
                            f"Patent id {remote_id} in PatSight job already submitted. The task_info is: "
                        )
                        return asdict(existing)
                except Exception:
                    print(
                        f"Patent id {remote_id} in PatSight job store but input_json invalid, submitting again"
                    )

        print(f"Patent id {remote_id} in PatSight job not submitted. Creating new job...")
        try:
            result = self.create_job(file_path=pdf_path, job_type=job_type, folder_id=folder_id)
            if getattr(self, "job_store", None):
                try:
                    self.job_store.create_job(
                        job_id=result["job_id"],
                        client_type=self.client_type,
                        job_type=job_type,
                        input_json=json.dumps(result, ensure_ascii=False),
                        remote_id=result.get("file_name"),
                        status=JobStatusEnum.PENDING.value,
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to persist job to store, job_id=%s: %s", result.get("job_id"), e
                    )
            return result
        except Exception as exc:
            if isinstance(exc, SubmitError):
                raise
            raise SubmitError(f"submit_job failed: {exc}") from exc

    def query_status(self, job_id: str, job_type: str = "") -> RemoteJobStatus:
        try:
            if job_type and str(job_type).strip():
                view = 1 if job_type in VIEW1_JOB_TYPES else 0
                payload = self.get_job_status(job_id=job_id, folder_id=self.folder_id, view=view)
            else:
                payload = self.get_job_status_for_job_id(job_id=job_id, folder_id=self.folder_id)
            raw_status = payload.get("status")
            status_str = normalize_status(raw_status) if raw_status is not None else "unknown"
            task_info = payload.get("task_info") or {}
            detail = str(task_info.get("error_message") or task_info.get("message") or "")
            return RemoteJobStatus(
                job_id=payload.get("job_id") or job_id,
                status=status_str,
                detail=detail,
                raw=payload,
            )
        except Exception as exc:
            raise QueryError(f"query_status failed for job_id={job_id}: {exc}") from exc

    def fetch_result(
        self,
        job_id: str,
        *,
        job_type: Optional[ResultType] = None,
        **kwargs: Any,
    ) -> JobResult:
        try:
            return self.get_job_result(
                job_id=job_id,
                folder_id=self.folder_id,
                data_type=job_type,
            )
        except PatSightJobNotFoundError as exc:
            raise JobNotFoundError(str(exc)) from exc
        except Exception as exc:
            raise FetchResultError(f"fetch_result failed for job_id={job_id}: {exc}") from exc

    def _sleep_backoff(self, attempt: int) -> None:
        delay = (self.config.backoff_base**attempt) + random.random() * 0.3
        time.sleep(delay)

    def _request(self, method: str, url: str, **kwargs: Any) -> Response:
        kwargs.setdefault("timeout", (self.config.timeout_connect, self.config.timeout_read))

        if "Authorization" not in self.sess.headers:
            self.login()

        auth_retried = False
        last_exc: Optional[Exception] = None

        for attempt in range(self.config.max_retries + 1):
            try:
                resp = self.sess.request(method, url, **kwargs)

                if resp.status_code in AUTH_STATUS and not auth_retried:
                    logger.warning("Authorization expired, refreshing token once.")
                    self.refresh_token()
                    auth_retried = True
                    continue

                if resp.status_code in RETRY_STATUS and attempt < self.config.max_retries:
                    logger.warning(
                        "Retryable status=%s for %s %s, retry=%s",
                        resp.status_code,
                        method,
                        url,
                        attempt + 1,
                    )
                    self._sleep_backoff(attempt)
                    continue

                resp.raise_for_status()
                return resp

            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.config.max_retries:
                    logger.warning(
                        "Request failed for %s %s, retry=%s, error=%s",
                        method,
                        url,
                        attempt + 1,
                        exc,
                    )
                    self._sleep_backoff(attempt)
                    continue
                raise PatSightError(f"Request failed: {method} {url}; last_error={exc}") from exc

        raise PatSightError(f"Unexpected retry loop end: {method} {url}; last_error={last_exc}")

    @staticmethod
    def _parse_json_response(resp: Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except ValueError as exc:
            raise PatSightError(f"Response is not valid JSON: {resp.text[:500]}") from exc

    def get_ops_token(
        self,
        account: Optional[str] = None,
        password: Optional[str] = None,
        credential: Optional[str] = None,
    ) -> Dict[str, Any]:
        account = account or self.account
        password = password or self.password

        if not credential and password:
            credential = encode_credential_from_password(password)

        if not account or not credential:
            raise PatSightAuthError("Missing OPS account or credential.")

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": self.config.user_agent,
        }
        payload = {"account": account, "credential": credential}

        try:
            resp = requests.post(
                self.config.ops_token_url,
                json=payload,
                headers=headers,
                timeout=(self.config.timeout_connect, self.config.timeout_read),
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise PatSightAuthError(f"Failed to get OPS token: {exc}") from exc

    def verify_ops_token(
        self,
        token: str,
        from_value: str = "login",
        already_base64: bool = False,
    ) -> Dict[str, Any]:
        if not token:
            raise PatSightAuthError("Empty token cannot be verified.")

        body_token = token if already_base64 else base64.b64encode(token.encode("utf-8")).decode("utf-8")

        try:
            resp = requests.post(
                self.config.verify_url,
                json={"token": body_token, "from": from_value},
                headers={"Content-Type": "application/json"},
                timeout=(self.config.timeout_connect, self.config.timeout_read),
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise PatSightAuthError(f"Failed to verify OPS token: {exc}") from exc

    def get_presigned(self, file_name: str) -> Tuple[str, str]:
        resp = self._request("POST", self.presigned_url, json={"file_name": file_name})
        data = self._parse_json_response(resp)
        url = (data.get("data") or {}).get("url")
        if not url:
            raise PatSightError(f"Presigned URL missing in response: {data}")
        pdf_url = url.split("?", 1)[0]
        return url, pdf_url

    def upload_pdf(self, presigned_url: str, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        if not path.is_file():
            raise ValueError(f"PDF path is not a file: {file_path}")

        try:
            with path.open("rb") as f:
                resp = requests.put(
                    presigned_url,
                    data=f,
                    headers={"Content-Type": "application/pdf"},
                    timeout=(self.config.timeout_connect, self.config.timeout_read),
                )
                resp.raise_for_status()
        except requests.RequestException as exc:
            raise PatSightError(f"Failed to upload PDF: {file_path}; error={exc}") from exc

    def create_task(self, pdf_url: str, action: str = "0", folder_id: int = 0) -> Dict[str, Any]:
        payload = {
            "data": [{"action": action, "pdf_slice": "", "pdf_url": pdf_url}],
            "email_notify": False,
            "folder_id": folder_id,
        }
        resp = self._request("POST", self.create_url, json=payload)
        return self._parse_json_response(resp)

    def list_tasks(
        self, folder_id: int, per_page: Optional[int] = None, page: int = 1, view: int = 1
    ) -> Dict[str, Any]:
        per = per_page or self.config.list_tasks_per_page
        if view == 1:
            params = {"folder_id": folder_id, "per_page": per, "page": page, "view": 1}
        else:
            params = {"folder_id": folder_id, "per_page": per, "page": page}
        resp = self._request("GET", self.tasks_url, params=params)
        return self._parse_json_response(resp)

    def get_task_statistics(self, task_id: str) -> Dict[str, Any]:
        url = f"{self.config.base_url}/v3/extractor/task/{task_id}/statistics"
        resp = self._request("GET", url, params={"request_id": int(time.time() * 1000)})
        return self._parse_json_response(resp)

    def export_task(
        self,
        task_id: str,
        file_type: str = "csv",
        export_to_molvalley: bool = True,
    ) -> str:
        url = f"{self.config.base_url}/v3/extractor/task/{task_id}/export"
        params = {"request_id": int(time.time() * 1000)}
        body = {"file_type": file_type, "export_to_molvalley": export_to_molvalley}
        resp = self._request("POST", url, params=params, json=body)
        resp.encoding = resp.encoding or "utf-8"
        csv_content = resp.text
        Path(self.workdir).mkdir(parents=True, exist_ok=True)
        out_path = Path(self.workdir) / f"{task_id}_sar_input.csv"
        out_path.write_text(csv_content, encoding="utf-8")
        return str(out_path)

    def create_job(self, file_path: str, job_type: ResultType, folder_id: int = 0) -> Dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")
        if path.suffix.lower() != ".pdf":
            logger.warning("Submitting non-.pdf file to PatSight: %s", file_path)

        api_action = job_type_to_api_action(job_type)

        presigned_url, pdf_url = self.get_presigned(file_name=path.name)
        self.upload_pdf(presigned_url=presigned_url, file_path=str(path))

        doc_only_id, doc_id = safe_extract_ids_from_url(presigned_url)
        if not doc_only_id:
            raise PatSightError(f"Failed to infer doc_only_id from presigned url: {presigned_url}")

        create_payload = self.create_task(pdf_url=pdf_url, action=api_action, folder_id=folder_id)
        task_id = (create_payload.get("data") or {}).get("task_id", "")
        if not task_id:
            raise PatSightError(f"create_task returned no task_id: {create_payload}")

        initial_status: Dict[str, Any] = {}
        poll_view = 1 if job_type in VIEW1_JOB_TYPES else 0
        for _ in range(self.config.create_job_poll_attempts):
            time.sleep(self.config.create_job_poll_interval)
            initial_status = self.get_job_status(
                doc_only_id=doc_only_id, folder_id=folder_id, view=poll_view
            )

            if initial_status.get("job_id"):
                break

        if job_type == "iupacAndStructure":
            site_address = f"{self.config.patsight_origin}/iupac?iupac=%2Fiupac%3FactiveMenu%3Dall%26isNode%3D0"
        else:
            site_address = f"{self.config.patsight_origin}/patsight?patsight-app/patent-list/activeMenu/all"

        job_id = initial_status.get("job_id", "") or task_id
        if not job_id:
            raise PatSightError(
                f"Unable to resolve job_id after task creation. task_id={task_id}, "
                f"doc_only_id={doc_only_id}, last_status={initial_status}"
            )
        return {
            "job_id": str(job_id),
            "task_id": str(task_id),
            "doc_only_id": doc_only_id,
            "doc_id": doc_id,
            "file_name": path.name,
            "file_path": str(path.resolve()),
            "job_type": job_type,
            "api_action": api_action,
            "folder_id": folder_id,
            "status": initial_status.get("status", "submitted"),
            "site_address": site_address,
        }

    def get_job_status(
        self, doc_only_id: str = "", job_id: str = "", folder_id: int = 0, view: int = 0
    ) -> Dict[str, Any]:
        page = 1
        per_page = self.config.list_tasks_per_page
        task_infos: list = []
        while page <= self.config.list_tasks_max_pages:
            time.sleep(1)
            for _ in range(2):
                data = self.list_tasks(folder_id=folder_id, per_page=per_page, page=page, view=view)
                task_infos = (data.get("data") or {}).get("task_info") or []
                if not task_infos:
                    break
                for task in task_infos:
                    extracted_doc_only_id, _ = safe_extract_ids_from_url(task.get("pdf_url"))
                    task_job_id = str(task.get("id", ""))
                    task_uuid = str(task.get("task_id", ""))
                    if (doc_only_id and str(extracted_doc_only_id) == str(doc_only_id)) or (
                        job_id and (task_job_id == str(job_id) or task_uuid == str(job_id))
                    ):
                        jt = api_action_to_job_type(str(task.get("action", "0")))
                        if jt == "iupacAndStructure":
                            site_address = f"{self.config.patsight_origin}/iupac?iupac=%2Fiupac%3FactiveMenu%3Dall%26isNode%3D0"
                        else:
                            site_address = f"{self.config.patsight_origin}/patsight?patsight-app/patent-list/activeMenu/all"
                        return {
                            "job_id": task_job_id or task_uuid or str(job_id),
                            "doc_only_id": doc_only_id,
                            "doc_id": task.get("doc_id", ""),
                            "file_name": task.get("file_name", ""),
                            "job_handle": task.get("job_handle", ""),
                            "job_type": jt,
                            "folder_id": folder_id,
                            "status": task.get("status", "submitted"),
                            "site_address": site_address,
                            "credit": task.get("credit", 0),
                            "task_info": task,
                        }

            if len(task_infos) < per_page:
                break
            page += 1

        return {
            "job_id": str(job_id or ""),
            "doc_only_id": str(doc_only_id or ""),
            "doc_id": "",
            "file_name": "",
            "job_handle": "",
            "job_type": "",
            "folder_id": folder_id,
            "status": None,
            "site_address": "",
        }

    def get_job_status_for_job_id(
        self, job_id: str, folder_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Try ``view=0`` then ``view=1`` until a row is found (by ``status`` set)."""
        fid = self.folder_id if folder_id is None else folder_id
        last: Dict[str, Any] = {}
        for view in (0, 1):
            payload = self.get_job_status(job_id=job_id, folder_id=fid, view=view)
            last = payload
            if payload.get("status") is not None:
                return payload
        return last

    def wait_for_job(
        self,
        job_id: str,
        folder_id: Optional[int] = None,
        poll_interval: int = 20,
        timeout_seconds: int = 1200,
    ) -> Dict[str, Any]:
        target_folder_id = self.folder_id if folder_id is None else folder_id
        deadline = time.time() + timeout_seconds
        last_status_payload: Optional[Dict[str, Any]] = None

        while time.time() < deadline:
            status_payload = self.get_job_status_for_job_id(job_id=job_id, folder_id=target_folder_id)
            last_status_payload = status_payload
            status = normalize_status(status_payload.get("status"))

            if status in SUCCESS_JOB_STATUS:
                return status_payload
            if status in FAILED_JOB_STATUS:
                raise PatSightError(f"Job entered failed status: {status_payload}")

            time.sleep(poll_interval)

        raise PatSightTimeoutError(
            f"Timeout after {timeout_seconds}s waiting for job_id={job_id}, last_status={last_status_payload}"
        )

    def get_job_result(
        self,
        job_id: str,
        folder_id: Optional[int] = None,
        data_type: Optional[ResultType] = None,
    ) -> JobResult:
        target_folder_id = self.folder_id if folder_id is None else folder_id
        if data_type is not None:
            view = 1 if data_type in VIEW1_JOB_TYPES else 0
            status_payload = self.get_job_status(job_id=job_id, folder_id=target_folder_id, view=view)
        else:
            status_payload = self.get_job_status_for_job_id(
                job_id=job_id, folder_id=target_folder_id
            )
        status = normalize_status(status_payload.get("status"))
        if not status:
            raise PatSightJobNotFoundError(f"Job not found: job_id={job_id}")
        if status not in SUCCESS_JOB_STATUS:
            raise PatSightJobNotFinishedError(f"Job not finished: job_id={job_id}, status={status}")
        task = status_payload.get("task_info") or status_payload
        task_id = task.get("job_id") or status_payload.get("job_id") or job_id
        if not task_id:
            raise PatSightError(f"Missing task_id in task payload: {status_payload}")

        resolved_type: ResultType
        if data_type is not None:
            resolved_type = data_type
        else:
            jt_slug = status_payload.get("job_type")
            if isinstance(jt_slug, str) and jt_slug in JOB_TYPE_TO_API_ACTION:
                resolved_type = jt_slug  # type: ignore[assignment]
            else:
                resolved_type = api_action_to_job_type(str(task.get("action", "0")))

        statistics_info = self.get_task_statistics(str(task_id))
        csv_output_path = self.export_task(str(task_id), file_type="csv", export_to_molvalley=True)
        data_type_map = {
            "structureAndActivity": "patsight?patsight-app=/view-results/overview?",
            "structureAndActivityReaction": "patsight?patsight-app=/view-results/overview?",
            "reaction": "patsight?patsight-app=/reaction-results/overview?",
            "iupac": "iupac?iupac=/patent-result/overview?",
            "iupacAndStructure": "iupac?iupac=/patent-result/overview?",
            "structure": "patsight?patsight-app=/view-results/overview?",
        }
        path_suffix = data_type_map.get(resolved_type, data_type_map["structureAndActivity"])
        result = {
            "job_id": str(job_id),
            "filename": task.get("file_name", ""),
            "status": status,
            "action": task.get("action", "0"),
            "job_type": resolved_type,
            "csv_output_path": csv_output_path,
            "statistics_info": format_statistics_summary(statistics_info),
            "pdf_pages": task.get("pdf_pages", 0),
            "title": task.get("title", ""),
            "abstract": task.get("abstract", ""),
            "handle": task.get("job_handle", ""),
            "credit_used": task.get("credit", 0),
            "site_address": (f"{self.config.patsight_origin}/{path_suffix}fileId={job_id}"),
        }
        return JobResult(
            job_id=str(job_id),
            result=result,
            output_path=csv_output_path,
            raw=status_payload,
        )
