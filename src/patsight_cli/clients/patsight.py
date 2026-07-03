"""PatSight 远程任务客户端，封装认证、提交、查询、导出与共享文件夹接口。"""

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

from patsight_cli.base import RemoteJobClient
from patsight_cli.exceptions import (
    ExportError,
    FetchResultError,
    JobNotFoundError,
    LoginError,
    QueryError,
    SubmitError,
)
from patsight_cli.export_filename import export_filename
from patsight_cli.export_ids import compound_rows_to_export_ids, structure_rows_to_export_ids
from patsight_cli.export_options import resolve_export_options
from patsight_cli.pdf_slice import resolve_pdf_slice
from patsight_cli.submit_cache import build_submit_cache_key, matches_submit_cache
from patsight_cli.models import JobResult, JobStatus as RemoteJobStatus
from patsight_cli.registry import ClientRegistry
from patsight_cli.store import JobStatusEnum

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
    raw = (
        os.environ.get("PATSIGHT_CLI_WORKDIR")
        or os.environ.get("XCLI_WORKDIR")
        or os.environ.get("PATSIGHT_WORKDIR")
        or ""
    ).strip()
    if raw:
        return os.path.expanduser(raw)
    return str(Path.home() / ".local" / "share" / "patsight-cli" / "output")


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


def resolve_job_type_from_status(
    status_payload: Dict[str, Any],
    *,
    explicit: Optional[str] = None,
) -> ResultType:
    """Resolve job_type for export/result; API task ``action`` is the source of truth."""
    if explicit is not None and str(explicit).strip():
        slug = str(explicit).strip()
        if slug not in JOB_TYPE_TO_API_ACTION:
            allowed = ", ".join(sorted(JOB_TYPE_TO_API_ACTION))
            raise ExportError(f"Unknown job_type {slug!r}. Use one of: {allowed}")
        return slug  # type: ignore[return-value]

    task = status_payload.get("task_info") or status_payload
    action = task.get("action")
    if action is not None and str(action).strip():
        return api_action_to_job_type(str(action))

    slug = status_payload.get("job_type")
    if isinstance(slug, str) and slug.strip() and slug.strip() in JOB_TYPE_TO_API_ACTION:
        return slug.strip()  # type: ignore[return-value]

    raise ExportError("Could not determine job_type from task status.")


def task_id_from_status(status_payload: Dict[str, Any], fallback: str) -> str:
    task = status_payload.get("task_info") or status_payload
    if isinstance(task, dict):
        for key in ("id", "job_id"):
            val = task.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    job_id = status_payload.get("job_id")
    if job_id is not None and str(job_id).strip():
        return str(job_id).strip()
    return str(fallback)


def task_action_from_status(status_payload: Dict[str, Any]) -> str:
    task = status_payload.get("task_info") or status_payload
    if isinstance(task, dict):
        action = task.get("action")
        if action is not None and str(action).strip():
            return str(action).strip()
    return str(status_payload.get("action") or "0")


def validate_export_job_match(
    *,
    resolved_job_type: ResultType,
    resolved_export_type: str,
    task_action: str,
) -> None:
    """Ensure CLI export intent matches backend task action (same branching as patent export API)."""
    actual_job_type = api_action_to_job_type(task_action)
    if resolved_job_type in IUPAC_EXPORT_JOB_TYPES:
        if actual_job_type not in IUPAC_EXPORT_JOB_TYPES:
            expected = ", ".join(IUPAC_EXPORT_HEADERS)
            actual = ", ".join(COMPOUND_EXPORT_HEADERS)
            raise ExportError(
                f"IUPAC export expected CSV headers ({expected}), but task action={task_action!r} "
                f"maps to job_type={actual_job_type!r} and would produce ({actual}). "
                f"Use the job_id from an IUPAC submit (action 6/26), not a structure/activity task."
            )
    if resolved_export_type == "structures" and actual_job_type in IUPAC_EXPORT_JOB_TYPES:
        return
    if resolved_job_type in IUPAC_EXPORT_JOB_TYPES and resolved_export_type != "structures":
        raise ExportError(
            f"export_type {resolved_export_type!r} is not supported for IUPAC tasks. "
            f"Omit --export-type to use structures (default)."
        )


def job_type_to_api_action(job_type: ResultType) -> str:
    return JOB_TYPE_TO_API_ACTION[job_type]


def coerce_job_type_slug(value: Any) -> ResultType:
    s = str(value).strip()
    if s not in JOB_TYPE_TO_API_ACTION:
        allowed = ", ".join(sorted(JOB_TYPE_TO_API_ACTION.keys()))
        raise SubmitError(f"Unknown job_type {s!r}. Use one of: {allowed}")
    return s  # type: ignore[return-value]


def shared_folder_role_to_api(value: Any) -> int:
    """关键参数：(value: Any)
    返回值：int
    描述：将 CLI 成员角色归一化为后端约定的 0=admin、1=member。
    """
    if isinstance(value, int):
        if value in {0, 1}:
            return value
        raise PatSightError("shared folder role must be 0/admin or 1/member.")
    role = str(value).strip().lower()
    if role in {"0", "admin"}:
        return 0
    if role in {"1", "member"}:
        return 1
    raise PatSightError("shared folder role must be 0/admin or 1/member.")


CLI_JOB_TYPE_CHOICES: tuple[str, ...] = tuple(sorted(JOB_TYPE_TO_API_ACTION.keys()))

# PatSight task list: view=1 for IUPAC/structure family; view=0 for structure/reaction/combined
VIEW1_JOB_TYPES: frozenset[str] = frozenset({"iupac", "structure", "iupacAndStructure"})

IUPAC_EXPORT_JOB_TYPES: frozenset[str] = frozenset({"iupac", "iupacAndStructure"})
IUPAC_EXPORT_HEADERS = ("Index", "Structure", "IUPAC Name", "Data Source", "Confidence")
COMPOUND_EXPORT_HEADERS = ("compound_number", "duplicate_number", "quality", "smiles")


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
    user_agent: str = "patsight-cli/0.1 (patsight)"
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
        pdf_slice = resolve_pdf_slice(payload, api_action=api_action)

        file_name = Path(pdf_path).name
        cache_key = build_submit_cache_key(
            file_name=file_name,
            job_type=job_type,
            pdf_slice=pdf_slice,
            folder_id=folder_id,
        )
        if getattr(self, "job_store", None):
            existing = self.job_store.get_job_by_remote_id(cache_key, self.client_type)
            if existing and existing.input_json:
                try:
                    cached = json.loads(existing.input_json)
                    if isinstance(cached, dict) and matches_submit_cache(
                        cached,
                        file_name=file_name,
                        job_type=job_type,
                        pdf_slice=pdf_slice,
                        folder_id=folder_id,
                    ):
                        pages_hint = pdf_slice or "all"
                        print(
                            "Patent job already submitted "
                            f"(file={file_name}, type={job_type}, pages={pages_hint})."
                        )
                        return cached
                except Exception:
                    print(
                        f"Patent job cache for {cache_key!r} has invalid input_json, submitting again"
                    )

        print(
            f"Patent job not submitted (file={file_name}, type={job_type}, "
            f"pages={pdf_slice or 'all'}). Creating new job..."
        )
        try:
            result = self.create_job(
                file_path=pdf_path,
                job_type=job_type,
                folder_id=folder_id,
                pdf_slice=pdf_slice,
            )
            if getattr(self, "job_store", None):
                try:
                    self.job_store.create_job(
                        job_id=result["job_id"],
                        client_type=self.client_type,
                        job_type=job_type,
                        input_json=json.dumps(result, ensure_ascii=False),
                        remote_id=cache_key,
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
        export_type: Optional[str] = None,
        file_format: Optional[str] = None,
        **kwargs: Any,
    ) -> JobResult:
        try:
            return self.get_job_result(
                job_id=job_id,
                folder_id=self.folder_id,
                data_type=job_type,
                export_type=export_type,
                file_format=file_format,
            )
        except PatSightJobNotFoundError as exc:
            raise JobNotFoundError(str(exc)) from exc
        except ExportError:
            raise
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

    def create_task(
        self,
        pdf_url: str,
        action: str = "0",
        folder_id: int = 0,
        pdf_slice: str = "",
    ) -> Dict[str, Any]:
        payload = {
            "data": [{"action": action, "pdf_slice": pdf_slice, "pdf_url": pdf_url}],
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

    def list_shared_folders(self, view: Optional[int] = None) -> Dict[str, Any]:
        """关键参数：(view: Optional[int])
        返回值：Dict[str, Any]
        描述：列出当前用户可访问的一级共享文件夹及子文件夹树。
        """
        params = {"view": int(view)} if view is not None else None
        url = f"{self.config.base_url}/v2/extractor/task/folder/full"
        resp = self._request("GET", url, params=params)
        return self._parse_json_response(resp)

    def create_shared_folder(
        self,
        name: str,
        parent_id: Optional[int] = None,
        view: int = 0,
    ) -> Dict[str, Any]:
        """关键参数：(name: str, parent_id: Optional[int], view: int)
        返回值：Dict[str, Any]
        描述：创建一级共享文件夹或继承权限的子文件夹。
        """
        folder_name = str(name).strip()
        if not folder_name:
            raise PatSightError("shared folder name is required.")
        body: Dict[str, Any] = {"path": folder_name, "view": int(view)}
        if parent_id is not None:
            body["parent_id"] = int(parent_id)
        url = f"{self.config.base_url}/v2/extractor/task/folder"
        resp = self._request("POST", url, json=body)
        return self._parse_json_response(resp)

    def rename_shared_folder(self, folder_id: int, name: str) -> Dict[str, Any]:
        """关键参数：(folder_id: int, name: str)
        返回值：Dict[str, Any]
        描述：重命名共享文件夹或其子文件夹。
        """
        folder_name = str(name).strip()
        if not folder_name:
            raise PatSightError("shared folder name is required.")
        url = f"{self.config.base_url}/v2/extractor/task/folder/name"
        resp = self._request("PUT", url, json={"folder_id": int(folder_id), "new_path": folder_name})
        return self._parse_json_response(resp)

    def delete_shared_folder(self, folder_id: int) -> Dict[str, Any]:
        """关键参数：(folder_id: int)
        返回值：Dict[str, Any]
        描述：软删除指定共享文件夹及其子文件夹。
        """
        url = f"{self.config.base_url}/v2/extractor/task/folder"
        resp = self._request("DELETE", url, json={"folder_id": int(folder_id)})
        return self._parse_json_response(resp)

    def list_shared_folder_members(self, folder_id: int) -> Dict[str, Any]:
        """关键参数：(folder_id: int)
        返回值：Dict[str, Any]
        描述：查询一级共享文件夹成员列表。
        """
        url = f"{self.config.base_url}/v2/extractor/task/folder/{int(folder_id)}/members"
        resp = self._request("GET", url)
        return self._parse_json_response(resp)

    def add_shared_folder_member(
        self,
        folder_id: int,
        email: str,
        role: Any = "member",
    ) -> Dict[str, Any]:
        """关键参数：(folder_id: int, email: str, role: Any)
        返回值：Dict[str, Any]
        描述：向一级共享文件夹添加 admin 或 member 成员。
        """
        member_email = str(email).strip()
        if not member_email:
            raise PatSightError("email is required for adding shared folder member.")
        url = f"{self.config.base_url}/v2/extractor/task/folder/{int(folder_id)}/members"
        resp = self._request(
            "POST",
            url,
            json={"email": member_email, "role": shared_folder_role_to_api(role)},
        )
        return self._parse_json_response(resp)

    def remove_shared_folder_member(self, folder_id: int, user_email: str) -> Dict[str, Any]:
        """关键参数：(folder_id: int, user_email: str)
        返回值：Dict[str, Any]
        描述：调用共享文件夹成员删除接口移除指定邮箱成员。
        """
        email = str(user_email).strip()
        if not email:
            raise PatSightError("user_email is required for removing shared folder member.")
        url = f"{self.config.base_url}/v2/extractor/task/folder/{int(folder_id)}/members"
        resp = self._request("DELETE", url, json={"user_email": email})
        return self._parse_json_response(resp)

    def update_shared_folder_member_role(
        self,
        folder_id: int,
        user_email: str,
        role: Any,
    ) -> Dict[str, Any]:
        """关键参数：(folder_id: int, user_email: str, role: Any)
        返回值：Dict[str, Any]
        描述：修改一级共享文件夹成员角色。
        """
        email = str(user_email).strip()
        if not email:
            raise PatSightError("user_email is required for updating shared folder member role.")
        url = f"{self.config.base_url}/v2/extractor/task/folder/{int(folder_id)}/members/role"
        resp = self._request(
            "PATCH",
            url,
            json={"user_email": email, "role": shared_folder_role_to_api(role)},
        )
        return self._parse_json_response(resp)

    def list_shared_folder_patents(self, folder_id: int) -> Dict[str, Any]:
        """关键参数：(folder_id: int)
        返回值：Dict[str, Any]
        描述：查询指定共享文件夹下的专利列表。
        """
        url = f"{self.config.base_url}/v2/extractor/task/folder/task/get"
        resp = self._request("POST", url, json={"folder_id": int(folder_id)})
        return self._parse_json_response(resp)

    def add_shared_folder_patents(self, folder_id: int, task_ids: list[int]) -> Dict[str, Any]:
        """关键参数：(folder_id: int, task_ids: list[int])
        返回值：Dict[str, Any]
        描述：将一组专利加入指定共享文件夹。
        """
        ids = [int(task_id) for task_id in task_ids]
        if not ids:
            raise PatSightError("task_ids is required for adding patents to shared folder.")
        url = f"{self.config.base_url}/v2/extractor/task/folder/task/favorite"
        resp = self._request("POST", url, json={"folder_id": int(folder_id), "task_ids": ids})
        return self._parse_json_response(resp)

    def remove_shared_folder_patents(self, folder_id: int, task_ids: list[int]) -> Dict[str, Any]:
        """关键参数：(folder_id: int, task_ids: list[int])
        返回值：Dict[str, Any]
        描述：将一组专利从指定共享文件夹移出。
        """
        ids = [int(task_id) for task_id in task_ids]
        if not ids:
            raise PatSightError("task_ids is required for removing patents from shared folder.")
        url = f"{self.config.base_url}/v2/extractor/task/folder/task/unfavorite"
        resp = self._request("POST", url, json={"folder_id": int(folder_id), "task_ids": ids})
        return self._parse_json_response(resp)

    def list_accessible_patents(
        self,
        *,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_dir: Optional[str] = None,
        status: Optional[str] = None,
        is_collection: Optional[bool] = None,
        folder_id: Optional[int] = None,
        name: Optional[str] = None,
        name_field: Optional[str] = None,
        searched_smiles: Optional[str] = None,
        view: Optional[int] = None,
        exclude_action: Optional[str] = None,
        last_operator: Optional[str] = None,
        last_operated_after: Optional[str] = None,
        last_operated_before: Optional[str] = None,
    ) -> Dict[str, Any]:
        """关键参数：(page/per_page/folder_id/name/status/最后操作等筛选参数)
        返回值：Dict[str, Any]
        描述：分页查询当前用户可访问的全部专利或指定共享文件夹专利。
        """
        params: Dict[str, Any] = {}
        optional_values: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "status": status,
            "is_collection": is_collection,
            "folder_id": folder_id,
            "name": name,
            "name_field": name_field,
            "searched_smiles": searched_smiles,
            "view": view,
            "exclude_action": exclude_action,
            "last_operator": last_operator,
            "last_operated_after": last_operated_after,
            "last_operated_before": last_operated_before,
        }
        for key, value in optional_values.items():
            if value is not None and value != "":
                params[key] = value
        resp = self._request("GET", self.tasks_url, params=params)
        return self._parse_json_response(resp)

    def get_patent_detail(self, task_id: int) -> Dict[str, Any]:
        """关键参数：(task_id: int)
        返回值：Dict[str, Any]
        描述：查询当前用户可访问的单篇专利详情。
        """
        url = f"{self.config.base_url}/v2/extractor/task/{int(task_id)}"
        resp = self._request("GET", url)
        return self._parse_json_response(resp)

    def list_patent_editors(self, task_id: int) -> Dict[str, Any]:
        """关键参数：(task_id: int)
        返回值：Dict[str, Any]
        描述：查询修改过专利的用户及其最后一次操作时间。
        """
        url = f"{self.config.base_url}/v3/extractor/task/{int(task_id)}/editors"
        resp = self._request("GET", url)
        return self._parse_json_response(resp)

    def set_patent_remark(self, task_id: int, remarks: Optional[str] = None) -> Dict[str, Any]:
        """关键参数：(task_id: int, remarks: Optional[str])
        返回值：Dict[str, Any]
        描述：为指定专利设置或清除用户备注。
        """
        remark_text = "" if remarks is None else str(remarks)
        if len(remark_text) > 139:
            raise PatSightError("remark must be at most 139 characters.")
        url = f"{self.config.base_url}/v2/extractor/task/remarks"
        resp = self._request("POST", url, json={"task_id": int(task_id), "remarks": remark_text})
        return self._parse_json_response(resp)

    def get_task_statistics(self, task_id: str) -> Dict[str, Any]:
        url = f"{self.config.base_url}/v3/extractor/task/{task_id}/statistics"
        resp = self._request("GET", url, params={"request_id": int(time.time() * 1000)})
        return self._parse_json_response(resp)

    def list_structure_ids(self, task_id: str) -> list[int]:
        url = f"{self.config.base_url}/v3/extractor/task/{task_id}/structures"
        resp = self._request("GET", url)
        data = self._parse_json_response(resp)
        structures = (data.get("data") or {}).get("structures") or []
        ids: list[int] = []
        for item in structures:
            raw_id = item.get("id")
            if raw_id is None:
                continue
            ids.append(int(raw_id))
        return ids

    def list_compound_export_ids(
        self,
        task_id: str,
        *,
        bioactivity_data_type: int,
        mode: Optional[str] = "properties",
    ) -> list[Dict[str, Optional[int]]]:
        """Fetch compound rows from backend and convert to export ``ids`` payload."""
        url = f"{self.config.base_url}/v3/extractor/task/{task_id}/compounds"
        params: Dict[str, Any] = {"bioactivity_data_type": bioactivity_data_type}
        if mode:
            params["mode"] = mode
        resp = self._request("GET", url, params=params)
        data = self._parse_json_response(resp)
        compounds = (data.get("data") or {}).get("compounds") or []
        return compound_rows_to_export_ids(compounds)

    def list_structure_export_ids(self, task_id: str) -> list[Dict[str, Optional[int]]]:
        """Fetch structure rows for IUPAC/structure export via ``/export``."""
        url = f"{self.config.base_url}/v3/extractor/task/{task_id}/structures"
        resp = self._request("GET", url)
        data = self._parse_json_response(resp)
        structures = (data.get("data") or {}).get("structures") or []
        return structure_rows_to_export_ids(structures)

    def export_task(
        self,
        task_id: str,
        *,
        job_type: ResultType,
        export_type: Optional[str] = None,
        file_format: Optional[str] = None,
        file_name: Optional[str] = None,
        task_action: Optional[str] = None,
    ) -> str:
        resolved_type, resolved_format = resolve_export_options(
            job_type,
            export_type=export_type,
            file_format=file_format,
        )
        if task_action is not None:
            validate_export_job_match(
                resolved_job_type=job_type,
                resolved_export_type=resolved_type,
                task_action=task_action,
            )

        if resolved_type == "reactions":
            url = f"{self.config.base_url}/v3/extractor/task/{task_id}/reactions/export"
            body = {"file_type": resolved_format, "reaction_ids": []}
        elif resolved_type == "namedStructures":
            export_ids = self.list_compound_export_ids(
                task_id,
                bioactivity_data_type=0,
                mode="namedStructures",
            )
            if not export_ids:
                raise ExportError(
                    f"No named structures found for task_id={task_id}; cannot export namedStructures."
                )
            url = f"{self.config.base_url}/v3/extractor/task/{task_id}/export"
            body = {"ids": export_ids, "file_type": resolved_format}
        else:
            if resolved_type == "admet":
                export_ids = self.list_compound_export_ids(
                    task_id,
                    bioactivity_data_type=1,
                    mode="properties",
                )
            elif resolved_type == "bioactivity":
                export_ids = self.list_compound_export_ids(
                    task_id,
                    bioactivity_data_type=0,
                    mode="properties",
                )
            elif resolved_type == "structures":
                export_ids = self.list_structure_export_ids(task_id)
            else:
                raise ExportError(f"Unsupported export_type for compound export: {resolved_type!r}")

            if not export_ids:
                raise ExportError(
                    f"No {resolved_type} records found for task_id={task_id}; cannot export."
                )

            url = f"{self.config.base_url}/v3/extractor/task/{task_id}/export"
            body = {"file_type": resolved_format, "ids": export_ids}
            if resolved_type in {"bioactivity", "admet"}:
                body["bioactivity_data_type"] = 1 if resolved_type == "admet" else 0

        params = {"request_id": int(time.time() * 1000)}
        resp = self._request("POST", url, params=params, json=body)
        Path(self.workdir).mkdir(parents=True, exist_ok=True)
        out_name = export_filename(
            export_type=resolved_type,
            file_format=resolved_format,
            file_name=file_name or "",
        )
        out_path = Path(self.workdir) / out_name
        if resolved_format in {"xlsx", "sdf"}:
            out_path.write_bytes(resp.content)
        else:
            resp.encoding = resp.encoding or "utf-8"
            out_path.write_text(resp.text, encoding="utf-8")
        return str(out_path)

    def create_job(
        self,
        file_path: str,
        job_type: ResultType,
        folder_id: int = 0,
        pdf_slice: str = "",
    ) -> Dict[str, Any]:
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

        create_payload = self.create_task(
            pdf_url=pdf_url,
            action=api_action,
            folder_id=folder_id,
            pdf_slice=pdf_slice,
        )
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
            "pdf_slice": pdf_slice,
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
        export_type: Optional[str] = None,
        file_format: Optional[str] = None,
    ) -> JobResult:
        target_folder_id = self.folder_id if folder_id is None else folder_id
        status_payload = self.get_job_status_for_job_id(
            job_id=job_id, folder_id=target_folder_id
        )
        status = normalize_status(status_payload.get("status"))
        if not status:
            raise PatSightJobNotFoundError(f"Job not found: job_id={job_id}")
        if status not in SUCCESS_JOB_STATUS:
            raise PatSightJobNotFinishedError(f"Job not finished: job_id={job_id}, status={status}")
        task = status_payload.get("task_info") or status_payload
        task_id = task_id_from_status(status_payload, job_id)
        if not task_id:
            raise PatSightError(f"Missing task_id in task payload: {status_payload}")

        resolved_type = resolve_job_type_from_status(status_payload, explicit=data_type)
        task_action = task_action_from_status(status_payload)

        statistics_info = self.get_task_statistics(str(task_id))
        output_path = self.export_task(
            str(task_id),
            job_type=resolved_type,
            export_type=export_type,
            file_format=file_format,
            file_name=task.get("file_name", ""),
            task_action=task_action,
        )
        resolved_export_type, resolved_file_format = resolve_export_options(
            resolved_type,
            export_type=export_type,
            file_format=file_format,
        )
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
            "export_type": resolved_export_type,
            "file_format": resolved_file_format,
            "output_path": output_path,
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
            output_path=output_path,
            raw=status_payload,
        )
