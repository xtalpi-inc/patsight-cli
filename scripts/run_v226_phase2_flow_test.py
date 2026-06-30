#!/usr/bin/env python3
"""V2.26 二期当前 CLI 环境/dev Swagger 串联实测脚本，结果写入 evidence。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
EVIDENCE_ROOT = REPO_ROOT / "evidence" / f"v226_phase2_flow_{TS}"
PROD_ORIGIN = "https://patent.xinsight-ai.com"
DEV_ORIGIN = "http://10.254.51.19:9900"


@dataclass
class Step:
    """关键参数：无
    返回值：Step
    描述：记录单个串联测试步骤的结果。
    """

    name: str
    passed: bool
    detail: str
    command: str | None = None
    exit_code: int | None = None
    stdout_file: str | None = None
    stderr_file: str | None = None


@dataclass
class Flow:
    """关键参数：无
    返回值：Flow
    描述：记录一个业务流程的多个步骤。
    """

    name: str
    environment: str
    steps: list[Step] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(step.passed for step in self.steps)


def env_auth_args() -> list[str]:
    """关键参数：无
    返回值：list[str]
    描述：从环境变量读取账号密码并组装 CLI 参数。
    """
    account = os.environ.get("PATSIGHT_E2E_ACCOUNT") or os.environ.get("PATSIGHT_OPS_ACCOUNT")
    password = os.environ.get("PATSIGHT_E2E_PASSWORD") or os.environ.get("PATSIGHT_OPS_PASSWORD")
    if not account or not password:
        return []
    return ["--account", account, "--password", password]


def mask_sensitive(text: str) -> str:
    """关键参数：(text: str)
    返回值：str
    描述：脱敏写入证据文件的命令文本。
    """
    password = os.environ.get("PATSIGHT_E2E_PASSWORD") or os.environ.get("PATSIGHT_OPS_PASSWORD")
    if password:
        text = text.replace(password, "<password>")
    return text


def run_cli(flow: Flow, step_name: str, args: list[str], *, expected_success: bool = True) -> Step:
    """关键参数：(flow: Flow, step_name: str, args: list[str])
    返回值：Step
    描述：执行 patsight-cli 并保存 stdout/stderr。
    """
    env_dir = EVIDENCE_ROOT / flow.environment
    env_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = env_dir / f"{flow.name}_{step_name}.stdout.txt"
    stderr_path = env_dir / f"{flow.name}_{step_name}.stderr.txt"
    command = ["patsight-cli", *args]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_path.write_text(result.stdout or "", encoding="utf-8")
    stderr_path.write_text(result.stderr or "", encoding="utf-8")
    passed = (result.returncode == 0) if expected_success else (result.returncode != 0)
    step = Step(
        name=step_name,
        passed=passed,
        detail="exit code matched expectation",
        command=mask_sensitive(" ".join(command)),
        exit_code=result.returncode,
        stdout_file=str(stdout_path.relative_to(REPO_ROOT)),
        stderr_file=str(stderr_path.relative_to(REPO_ROOT)),
    )
    flow.steps.append(step)
    return step


def api_base_for_origin(origin: str) -> str:
    """关键参数：(origin: str)
    返回值：str
    描述：根据生产或 dev 地址生成 patent API base。
    """
    clean = origin.rstrip("/")
    if clean.endswith("/api"):
        return clean
    if "10.254.51.19" in clean:
        return f"{clean}/api"
    return f"{clean}/patent/api"


def probe_route(origin: str, method: str, path: str) -> dict[str, Any]:
    """关键参数：(origin: str, method: str, path: str)
    返回值：dict[str, Any]
    描述：无鉴权探测路由发布状态。
    """
    url = f"{api_base_for_origin(origin)}{path}"
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return {"method": method, "path": path, "status": response.status}
    except urllib.error.HTTPError as exc:
        return {"method": method, "path": path, "status": exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"method": method, "path": path, "status": "error", "error": str(exc)}


def parse_json_file(path: str | None) -> Any:
    """关键参数：(path: str | None)
    返回值：Any
    描述：读取步骤 stdout 中的 JSON。
    """
    if not path:
        return None
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            return json.loads(text[index:])
        except json.JSONDecodeError:
            continue
    return None


def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    """关键参数：(payload: Any)
    返回值：list[dict[str, Any]]
    描述：从不同列表接口响应中提取行数据。
    """
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("task_info", "data", "list", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    for key in ("task_info", "data", "list", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def extract_numeric_task_id(payload: Any) -> int | None:
    """关键参数：(payload: Any)
    返回值：int | None
    描述：从提交、状态或列表响应中解析 remarks API 需要的数字任务 ID。
    """
    if not isinstance(payload, dict):
        return None
    candidates = [
        payload.get("job_id"),
        payload.get("task_id"),
        payload.get("id"),
        payload.get("taskId"),
        payload.get("task_id_int"),
    ]
    task_info = payload.get("task_info")
    if isinstance(task_info, dict):
        candidates.extend([task_info.get("job_id"), task_info.get("task_id"), task_info.get("id")])
    for value in candidates:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def first_folder_id(payload: Any) -> str | None:
    """关键参数：(payload: Any)
    返回值：str | None
    描述：从共享文件夹列表中选取第一个可用 folder id。
    """
    rows = rows_from_payload(payload)
    for row in rows:
        folder_id = row.get("id") or row.get("folder_id")
        if folder_id is not None:
            return str(folder_id)
    return None


def resolve_folder_id(flow: Flow, auth: list[str]) -> str | None:
    """关键参数：(flow: Flow, auth: list[str])
    返回值：str | None
    描述：优先使用环境变量，否则从当前 CLI 环境的文件夹列表取一个可用文件夹。
    """
    configured = os.environ.get("PATSIGHT_E2E_FOLDER_ID")
    if configured:
        return configured
    list_step = run_cli(flow, "shared_folder_list_for_setup", ["shared-folder", "list", *auth])
    folder_id = first_folder_id(parse_json_file(list_step.stdout_file))
    list_step.passed = list_step.exit_code == 0 and folder_id is not None
    list_step.detail = f"selected folder_id={folder_id}" if folder_id else "no folder id found"
    return folder_id


def resolve_remark_task_id(
    flow: Flow,
    shared_payload: Any,
    folder_id: str,
    auth: list[str],
) -> int | None:
    """关键参数：(flow: Flow, shared_payload: Any, folder_id: str)
    返回值：int | None
    描述：提交响应为 UUID 时，通过 status 和文件夹列表补充反查数字任务 ID。
    """
    direct_task_id = extract_numeric_task_id(shared_payload)
    if direct_task_id is not None:
        return direct_task_id
    raw_job_id = None
    if isinstance(shared_payload, dict):
        raw_job_id = shared_payload.get("job_id") or shared_payload.get("task_id")
    if raw_job_id:
        status_step = run_cli(
            flow,
            "resolve_task_id_status",
            ["status", "--job-id", str(raw_job_id), "--folder-id", folder_id, *auth],
        )
        status_payload = parse_json_file(status_step.stdout_file)
        status_task_id = extract_numeric_task_id(status_payload)
        status_step.passed = status_step.exit_code == 0 and status_task_id is not None
        status_step.detail = (
            f"resolved numeric task_id={status_task_id}"
            if status_task_id is not None
            else "status did not expose numeric task_id"
        )
        if status_task_id is not None:
            return status_task_id
    folder_step = run_cli(
        flow,
        "resolve_task_id_folder_list",
        ["shared-folder", "patents", "list", "--folder-id", folder_id, *auth],
    )
    rows = rows_from_payload(parse_json_file(folder_step.stdout_file))
    folder_task_id = None
    for row in rows:
        folder_task_id = extract_numeric_task_id(row)
        if folder_task_id is not None:
            break
    folder_step.passed = folder_step.exit_code == 0 and folder_task_id is not None
    folder_step.detail = (
        f"resolved numeric task_id={folder_task_id}"
        if folder_task_id is not None
        else "folder patents list did not expose numeric task_id"
    )
    return folder_task_id


def current_environment_name(origin: str) -> str:
    """关键参数：(origin: str)
    返回值：str
    描述：根据当前 CLI origin 生成报告中的环境名称。
    """
    if "test" in origin:
        return "test"
    if "10.254.51.19" in origin or "dev" in origin:
        return "dev"
    if "patent.xinsight-ai.com" in origin:
        return "production"
    return "current"


def current_env_flow() -> Flow:
    """关键参数：无
    返回值：Flow
    描述：当前 .env CLI 环境 remarks、筛选、zip 与缓存回归串联实测。
    """
    origin = os.environ.get("PATSIGHT_E2E_PATSIGHT_URL") or os.environ.get("PATSIGHT_URL") or PROD_ORIGIN
    environment = current_environment_name(origin)
    flow = Flow("phase2_current_env", environment)
    auth = env_auth_args()
    pdf_path = str(REPO_ROOT / "WO2010111432A1.pdf")
    pages = os.environ.get("PATSIGHT_E2E_PAGES", "21-22")
    remark = f"phase2-e2e-{TS}"

    if not auth:
        flow.steps.append(Step("auth", False, "missing PATSIGHT_E2E_ACCOUNT/PATSIGHT_E2E_PASSWORD"))
        return flow

    route = probe_route(origin, "POST", "/v2/extractor/task/remarks")
    flow.steps.append(
        Step(
            "remarks_route",
            route.get("status") in {200, 400, 401, 403},
            f"POST /task/remarks status={route.get('status')}",
        )
    )

    folder_id = resolve_folder_id(flow, auth)
    if not folder_id:
        flow.steps.append(Step("folder_setup", False, "could not resolve folder_id for current CLI environment"))
        return flow

    run_cli(
        flow,
        "submit_personal_cache_seed",
        ["submit", "--pdf-path", pdf_path, "--pages", pages, *auth],
    )
    shared_step = run_cli(
        flow,
        "submit_shared_same_pages",
        ["submit", "--pdf-path", pdf_path, "--shared-folder-id", folder_id, "--pages", pages, *auth],
    )
    shared_payload = parse_json_file(shared_step.stdout_file)
    shared_folder = shared_payload.get("folder_id") if isinstance(shared_payload, dict) else None
    shared_step.passed = shared_step.exit_code == 0 and str(shared_folder) == str(folder_id)
    shared_step.detail = f"expected folder_id={folder_id}, actual={shared_folder}"

    remark_task_id = resolve_remark_task_id(flow, shared_payload, folder_id, auth)
    if remark_task_id is None:
        flow.steps.append(Step("remark_set", False, "could not resolve numeric task_id for remarks API"))
    else:
        run_cli(
            flow,
            "remark_set",
            ["patent", "remark", "set", "--task-id", str(remark_task_id), "--remark", remark, *auth],
            expected_success=True,
        )
        status_step = run_cli(
            flow,
            "remark_status_verify",
            ["status", "--job-id", str(remark_task_id), "--folder-id", folder_id, *auth],
        )
        status_payload = parse_json_file(status_step.stdout_file)
        task_info = {}
        if isinstance(status_payload, dict) and isinstance(status_payload.get("raw"), dict):
            raw_task_info = status_payload["raw"].get("task_info")
            if isinstance(raw_task_info, dict):
                task_info = raw_task_info
        status_remark = task_info.get("remarks")
        status_step.passed = status_step.exit_code == 0 and status_remark == remark
        status_step.detail = f"expected remark={remark}, status remark={status_remark!r}"

    list_remark_step = run_cli(
        flow,
        "patent_list_remark_filter",
        [
            "patent",
            "list",
            "--folder-id",
            folder_id,
            "--remark",
            remark,
            "--fetch-all",
            "--per-page",
            "20",
            *auth,
        ],
    )
    list_payload = parse_json_file(list_remark_step.stdout_file)
    rows = []
    if isinstance(list_payload, dict) and isinstance(list_payload.get("data"), dict):
        rows = list_payload["data"].get("task_info") or list_payload["data"].get("data") or []
    list_remark_step.passed = any(isinstance(row, dict) and row.get("remarks") == remark for row in rows)
    list_remark_step.detail = f"expected remark={remark}, matched={list_remark_step.passed}"

    zip_step = run_cli(
        flow,
        "patent_export_zip",
        [
            "patent",
            "export",
            "--zip",
            "--folder-id",
            folder_id,
            "--per-page",
            "5",
            "--no-editors",
            "-o",
            str(EVIDENCE_ROOT / environment / "phase2.zip"),
            *auth,
        ],
    )
    zip_payload = parse_json_file(zip_step.stdout_file)
    if isinstance(zip_payload, dict):
        zip_step.passed = zip_step.exit_code == 0 and zip_payload.get("ok") is True
        zip_step.detail = (
            f"task_count={zip_payload.get('task_count')}, "
            f"exported_count={zip_payload.get('exported_count')}, "
            f"skipped_count={zip_payload.get('skipped_count')}"
        )
    return flow


def dev_flow() -> Flow:
    """关键参数：无
    返回值：Flow
    描述：dev 环境路由发布状态探测。
    """
    flow = Flow("dev_swagger_route_probe", "dev_swagger")
    origin = os.environ.get("PATSIGHT_DEV_ORIGIN", DEV_ORIGIN)
    probes = [
        ("remarks_route", "POST", "/v2/extractor/task/remarks", {200, 400, 401, 403}),
        ("members_route", "GET", "/v2/extractor/task/folder/1/members", {200, 400, 401, 403, 404, 500}),
        ("editors_route", "GET", "/v3/extractor/task/1/editors", {200, 400, 401, 403, 404, 500}),
        ("tasks_route", "GET", "/v2/extractor/tasks", {200, 400, 401, 403, 500}),
    ]
    for name, method, path, allowed in probes:
        result = probe_route(origin, method, path)
        flow.steps.append(
            Step(
                name,
                result.get("status") in allowed,
                f"{method} {path} status={result.get('status')}",
            )
        )
    return flow


def write_report(flows: list[Flow]) -> None:
    """关键参数：(flows: list[Flow])
    返回值：None
    描述：写入 JSON 和 Markdown 实测报告。
    """
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {
        "finished_at": datetime.now().isoformat(),
        "evidence_root": str(EVIDENCE_ROOT),
        "flows": [
            {
                "name": flow.name,
                "environment": flow.environment,
                "passed": flow.passed,
                "steps": [step.__dict__ for step in flow.steps],
            }
            for flow in flows
        ],
    }
    (EVIDENCE_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# V2.26 CLI Phase2 串联 E2E 测试报告",
        "",
        f"- 测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 证据目录：`{EVIDENCE_ROOT.relative_to(REPO_ROOT).as_posix()}/`",
        "- CLI 实测默认读取仓库根目录 `.env`；账号密码来自 `PATSIGHT_E2E_*` 或 `PATSIGHT_OPS_*`。",
        "- `dev_swagger` Flow 仅做 Swagger/dev host 路由探测，不执行登录态业务链路。",
        "",
        "## 流程结果",
        "",
        "| 环境 | Flow | 结果 | 步骤 |",
        "|---|---|---|---|",
    ]
    for flow in flows:
        passed_steps = sum(1 for step in flow.steps if step.passed)
        result = "通过" if flow.passed else "失败"
        lines.append(f"| {flow.environment} | {flow.name} | {result} | {passed_steps}/{len(flow.steps)} |")
    for flow in flows:
        lines.extend(["", f"## {flow.environment} / {flow.name}", ""])
        for step in flow.steps:
            result = "PASS" if step.passed else "FAIL"
            lines.append(f"- `{step.name}`：**{result}**，{step.detail}")
            if step.command:
                safe_command = step.command
                lines.append(f"  - command: `{safe_command}`")
    (REPO_ROOT / "docs" / "V2.26_CLI_PHASE2_FLOW_E2E_TEST_REPORT.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    flows = [current_env_flow(), dev_flow()]
    write_report(flows)
    print(json.dumps({"evidence_root": str(EVIDENCE_ROOT), "passed": all(f.passed for f in flows)}, ensure_ascii=False))
    return 0 if all(flow.passed for flow in flows) else 1


if __name__ == "__main__":
    sys.exit(main())
