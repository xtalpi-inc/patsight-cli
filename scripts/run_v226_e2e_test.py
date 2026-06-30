#!/usr/bin/env python3
"""V2.26 新增 CLI 命令生产环境 E2E 实测，输出 evidence 与汇总 JSON。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ACCOUNT = "qingnan.xie@xtalpi.com"
PASSWORD = "<password>"
REPO_ROOT = Path(__file__).resolve().parents[1]
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
EVIDENCE_DIR = REPO_ROOT / "evidence" / f"v226_e2e_{TS}"


def run_case(name: str, args: list[str]) -> dict:
    """关键参数：(name: str, args: list[str])
    返回值：dict
    描述：执行单条 patsight-cli 命令并保存 stdout/stderr。
    """
    cmd = ["patsight-cli", *args]
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_path = EVIDENCE_DIR / f"{name}.stdout.txt"
    stderr_path = EVIDENCE_DIR / f"{name}.stderr.txt"
    stdout_path.write_text(result.stdout or "", encoding="utf-8")
    stderr_path.write_text(result.stderr or "", encoding="utf-8")
    payload = {
        "name": name,
        "command": " ".join(cmd),
        "exit_code": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }
    (EVIDENCE_DIR / f"{name}.meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[{result.returncode}] {name}")
    return payload


def parse_json_text(text: str) -> dict | list | None:
    """关键参数：(text: str)
    返回值：dict | list | None
    描述：从 CLI 输出中提取 JSON 对象。
    """
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{[\s\S]*\})", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
    return None


def first_int_from_json(data: object, *keys: str) -> int | None:
    """关键参数：(data: object, *keys: str)
    返回值：int | None
    描述：递归查找 JSON 中第一个整型 id 字段。
    """
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, int):
                return value
        for value in data.values():
            found = first_int_from_json(value, *keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = first_int_from_json(item, *keys)
            if found is not None:
                return found
    return None


def probe_route(method: str, path: str) -> dict:
    """关键参数：(method: str, path: str)
    返回值：dict
    描述：无鉴权探测生产环境路由是否存在。
    """
    import urllib.error
    import urllib.request

    url = f"https://patent.xinsight-ai.com/patent/api{path}"
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return {"method": method, "path": path, "status": response.status}
    except urllib.error.HTTPError as exc:
        return {"method": method, "path": path, "status": exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"method": method, "path": path, "status": "error", "error": str(exc)}


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    auth = ["--account", ACCOUNT, "--password", PASSWORD]
    results: list[dict] = []
    folder_id: int | None = None
    task_id: int | None = None
    test_folder_name = f"cli-e2e-{TS}"

    cases: list[tuple[str, list[str]]] = [
        ("01_help_root", ["--help"]),
        ("02_help_shared_folder", ["shared-folder", "--help"]),
        ("03_help_patent", ["patent", "--help"]),
        ("10_shared_folder_list_view0", ["shared-folder", "list", "--view", "0", *auth]),
        ("11_shared_folder_list_view1", ["shared-folder", "list", "--view", "1", *auth]),
        ("20_shared_folder_create", ["shared-folder", "create", "--name", test_folder_name, *auth]),
    ]

    for name, args in cases:
        results.append(run_case(name, args))

    create_data = parse_json_text(results[-1]["stdout"])
    folder_id = first_int_from_json(create_data, "folder_id", "id")

    if folder_id is not None:
        results.append(run_case("21_shared_folder_list_after_create", ["shared-folder", "list", *auth]))
        results.append(
            run_case(
                "22_shared_folder_rename",
                ["shared-folder", "rename", "--folder-id", str(folder_id), "--name", f"{test_folder_name}-renamed", *auth],
            )
        )
        results.append(
            run_case(
                "23_shared_folder_members_list",
                ["shared-folder", "members", "list", "--folder-id", str(folder_id), *auth],
            )
        )
        results.append(
            run_case(
                "24_shared_folder_members_add",
                [
                    "shared-folder",
                    "members",
                    "add",
                    "--folder-id",
                    str(folder_id),
                    "--email",
                    ACCOUNT,
                    "--role",
                    "admin",
                    *auth,
                ],
            )
        )
        results.append(
            run_case(
                "25_shared_folder_patents_list",
                ["shared-folder", "patents", "list", "--folder-id", str(folder_id), *auth],
            )
        )

    results.append(run_case("30_patent_list_default", ["patent", "list", "--page", "1", "--per-page", "5", *auth]))
    results.append(
        run_case(
            "31_patent_list_status_done",
            ["patent", "list", "--page", "1", "--per-page", "5", "--status", "done", *auth],
        )
    )

    patent_data = parse_json_text(results[-2]["stdout"])
    task_id = first_int_from_json(patent_data, "id", "task_id")

    if task_id is not None:
        results.append(run_case("32_patent_detail", ["patent", "detail", "--task-id", str(task_id), *auth]))
        results.append(run_case("33_patent_editors", ["patent", "editors", "--task-id", str(task_id), *auth]))
        if folder_id is not None:
            results.append(
                run_case(
                    "34_shared_folder_patents_add",
                    ["shared-folder", "patents", "add", "--folder-id", str(folder_id), "--task-id", str(task_id), *auth],
                )
            )
            results.append(
                run_case(
                    "35_shared_folder_patents_list_after_add",
                    ["shared-folder", "patents", "list", "--folder-id", str(folder_id), *auth],
                )
            )
            results.append(
                run_case(
                    "36_shared_folder_patents_remove",
                    ["shared-folder", "patents", "remove", "--folder-id", str(folder_id), "--task-id", str(task_id), *auth],
                )
            )

    results.append(
        run_case(
            "40_submit_conflict",
            [
                "submit",
                "--pdf-path",
                str(REPO_ROOT / "WO2010111432A1.pdf"),
                "--folder-id",
                "0",
                "--shared-folder-id",
                "27463",
                *auth,
            ],
        )
    )

    pdf_path = REPO_ROOT / "WO2010111432A1.pdf"
    if folder_id is not None and pdf_path.is_file():
        results.append(
            run_case(
                "41_submit_shared_folder",
                [
                    "submit",
                    "--pdf-path",
                    str(pdf_path),
                    "--shared-folder-id",
                    str(folder_id),
                    "--pages",
                    "1-2",
                    *auth,
                ],
            )
        )

    if folder_id is not None:
        results.append(
            run_case(
                "90_shared_folder_delete",
                ["shared-folder", "delete", "--folder-id", str(folder_id), *auth],
            )
        )

    route_probes = [
        probe_route("GET", "/v2/extractor/task/folder/full"),
        probe_route("GET", "/v2/extractor/task/folder/1/members"),
        probe_route("POST", "/v2/extractor/task/folder/task/get"),
        probe_route("POST", "/v2/extractor/task/folder/task/favorite"),
        probe_route("GET", "/v2/extractor/tasks"),
        probe_route("GET", "/v2/extractor/task/1"),
        probe_route("GET", "/v3/extractor/task/1/editors"),
    ]

    summary = {
        "finished_at": datetime.now().isoformat(),
        "environment": "https://patent.xinsight-ai.com",
        "account": ACCOUNT,
        "evidence_dir": str(EVIDENCE_DIR),
        "test_folder_name": test_folder_name,
        "folder_id": folder_id,
        "task_id": task_id,
        "results": [
            {
                "name": item["name"],
                "exit_code": item["exit_code"],
                "command": item["command"],
            }
            for item in results
        ],
        "route_probes": route_probes,
    }
    summary_path = EVIDENCE_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
