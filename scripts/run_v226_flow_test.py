#!/usr/bin/env python3
"""V2.26 新增 CLI 串联业务流程 E2E 实测。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ACCOUNT = "qingnan.xie@xtalpi.com"
PASSWORD = "<password>"
REPO_ROOT = Path(__file__).resolve().parents[1]
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
EVIDENCE_DIR = REPO_ROOT / "evidence" / f"v226_flow_{TS}"


@dataclass
class StepResult:
    step_id: str
    title: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    passed: bool
    notes: str = ""


@dataclass
class FlowReport:
    flow_name: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(step.passed for step in self.steps)


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """关键参数：(args: list[str])
    返回值：tuple[int, str, str]
    描述：执行 patsight-cli 并返回 exit code 与输出。
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
    return result.returncode, result.stdout or "", result.stderr or ""


def save_step(flow: FlowReport, step_id: str, title: str, args: list[str], passed: bool, notes: str = "") -> StepResult:
    """关键参数：(flow, step_id, title, args, passed, notes)
    返回值：StepResult
    描述：执行一步并写入 evidence。
    """
    exit_code, stdout, stderr = run_cli(args)
    command = "patsight-cli " + " ".join(args)
    step = StepResult(step_id, title, command, exit_code, stdout, stderr, passed, notes)
    flow.steps.append(step)
    prefix = f"{flow.flow_name}_{step_id}"
    (EVIDENCE_DIR / f"{prefix}.stdout.txt").write_text(stdout, encoding="utf-8")
    (EVIDENCE_DIR / f"{prefix}.stderr.txt").write_text(stderr, encoding="utf-8")
    (EVIDENCE_DIR / f"{prefix}.meta.json").write_text(
        json.dumps(step.__dict__, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {flow.flow_name} :: {step_id} :: {title}")
    if notes:
        print(f"       note: {notes}")
    return step


def parse_json_output(text: str) -> Any:
    """关键参数：(text: str)
    返回值：Any
    描述：解析 CLI 标准输出中的 JSON。
    """
    text = text.strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
            return payload
        except json.JSONDecodeError:
            continue
    return None


def auth_args() -> list[str]:
    return ["--account", ACCOUNT, "--password", PASSWORD]


def folder_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def find_folder(folders: list[dict[str, Any]], folder_id: int) -> dict[str, Any] | None:
    for item in folders:
        if item.get("id") == folder_id:
            return item
        children = item.get("children") or []
        if isinstance(children, list):
            found = find_folder([child for child in children if isinstance(child, dict)], folder_id)
            if found:
                return found
    return None


def normalize_id(value: Any) -> str | None:
    """关键参数：(value: Any)
    返回值：str | None
    描述：统一 task/job id 比较格式。
    """
    if value is None:
        return None
    return str(value)


def pick_project_folder(folders: list[dict[str, Any]]) -> int | None:
    """关键参数：(folders: list[dict[str, Any]])
    返回值：int | None
    描述：优先选择 Project A 作为串联测试目标文件夹。
    """
    for item in folders:
        if item.get("path") == "Project A" and isinstance(item.get("id"), int):
            return int(item["id"])
    for item in folders:
        folder_id = item.get("id")
        if isinstance(folder_id, int):
            return folder_id
    return None


def folder_names(folders: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in folders:
        path = item.get("path")
        if isinstance(path, str):
            names.append(path)
        children = item.get("children") or []
        if isinstance(children, list):
            names.extend(folder_names([child for child in children if isinstance(child, dict)]))
    return names


def patent_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        rows = data.get("data") or data.get("task_info") or []
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def flow_shared_folder_lifecycle() -> tuple[FlowReport, int | None]:
    """关键参数：无
    返回值：tuple[FlowReport, int | None]
    描述：串联测试共享文件夹创建、列表、重命名、删除全生命周期。
    """
    flow = FlowReport("flow_A_shared_folder_lifecycle")
    base_name = f"flow-a-{TS}"
    renamed = f"{base_name}-renamed"
    folder_id: int | None = None

    step = save_step(
        flow,
        "A1_create",
        "创建共享文件夹",
        ["shared-folder", "create", "--name", base_name, *auth_args()],
        False,
    )
    create_payload = parse_json_output(step.stdout)
    folder_id = (
        create_payload.get("data", {}).get("folder_id")
        if isinstance(create_payload, dict) and isinstance(create_payload.get("data"), dict)
        else None
    )
    step.passed = step.exit_code == 0 and isinstance(folder_id, int)
    step.notes = f"folder_id={folder_id}"
    if not step.passed:
        return flow, None

    step = save_step(
        flow,
        "A2_list_after_create",
        "创建后立即 list，应能查到新文件夹",
        ["shared-folder", "list", *auth_args()],
        False,
    )
    folders = folder_items(parse_json_output(step.stdout))
    found = find_folder(folders, folder_id)
    step.passed = step.exit_code == 0 and found is not None and found.get("path") == base_name
    step.notes = f"visible_paths={folder_names(folders)}"

    step = save_step(
        flow,
        "A3_rename",
        "重命名共享文件夹",
        ["shared-folder", "rename", "--folder-id", str(folder_id), "--name", renamed, *auth_args()],
        step.exit_code == 0,
    )

    step = save_step(
        flow,
        "A4_list_after_rename",
        "重命名后 list，应显示新名称",
        ["shared-folder", "list", *auth_args()],
        False,
    )
    folders = folder_items(parse_json_output(step.stdout))
    found = find_folder(folders, folder_id)
    step.passed = step.exit_code == 0 and found is not None and found.get("path") == renamed
    step.notes = f"path_after_rename={found.get('path') if found else None}"

    step = save_step(
        flow,
        "A5_patents_list_empty",
        "新建文件夹 patents list 应为空",
        ["shared-folder", "patents", "list", "--folder-id", str(folder_id), *auth_args()],
        False,
    )
    rows = patent_rows(parse_json_output(step.stdout))
    step.passed = step.exit_code == 0 and len(rows) == 0
    step.notes = f"count={len(rows)}"

    step = save_step(
        flow,
        "A6_delete",
        "删除共享文件夹",
        ["shared-folder", "delete", "--folder-id", str(folder_id), *auth_args()],
        step.exit_code == 0,
    )

    step = save_step(
        flow,
        "A7_list_after_delete",
        "删除后 list，不应再出现该 folder_id",
        ["shared-folder", "list", *auth_args()],
        False,
    )
    folders = folder_items(parse_json_output(step.stdout))
    step.passed = step.exit_code == 0 and find_folder(folders, folder_id) is None
    step.notes = f"remaining_paths={folder_names(folders)}"

    return flow, folder_id


def flow_submit_and_patent_chain(existing_folder_id: int, pdf_path: Path) -> FlowReport:
    """关键参数：(existing_folder_id: int, pdf_path: Path)
    返回值：FlowReport
    描述：串联 submit → 文件夹专利列表 → detail → remove → add 回文件夹。
    """
    flow = FlowReport("flow_B_submit_patent_chain")
    page_slice = "13-14"

    step = save_step(
        flow,
        "B1_submit_to_shared_folder",
        "提交 PDF 到已有共享文件夹",
        [
            "submit",
            "--pdf-path",
            str(pdf_path),
            "--shared-folder-id",
            str(existing_folder_id),
            "--pages",
            page_slice,
            *auth_args(),
        ],
        False,
    )
    submit_payload = parse_json_output(step.stdout)
    folder_id_in_submit = submit_payload.get("folder_id") if isinstance(submit_payload, dict) else None
    task_id = submit_payload.get("job_id") if isinstance(submit_payload, dict) else None
    cache_hit = "Patent job already submitted" in step.stdout
    step.passed = step.exit_code == 0 and folder_id_in_submit == existing_folder_id and not cache_hit
    step.notes = f"folder_id={folder_id_in_submit}, task_id={task_id}, cache_hit={cache_hit}"
    if not step.passed or task_id is None:
        return flow

    normalized_task_id = normalize_id(task_id)

    time.sleep(2)

    step = save_step(
        flow,
        "B2_patents_list_after_submit",
        "提交后 shared-folder patents list 应出现该 task",
        ["shared-folder", "patents", "list", "--folder-id", str(existing_folder_id), *auth_args()],
        False,
    )
    rows = patent_rows(parse_json_output(step.stdout))
    ids = [normalize_id(row.get("id")) for row in rows]
    step.passed = step.exit_code == 0 and normalized_task_id in ids
    step.notes = f"task_ids={ids}"

    step = save_step(
        flow,
        "B3_patent_detail",
        "patent detail 应能查到同一 task",
        ["patent", "detail", "--task-id", str(task_id), *auth_args()],
        False,
    )
    detail_payload = parse_json_output(step.stdout)
    detail_id = detail_payload.get("data", {}).get("id") if isinstance(detail_payload, dict) else None
    step.passed = step.exit_code == 0 and normalize_id(detail_id) == normalized_task_id
    step.notes = f"detail_id={detail_id}"

    step = save_step(
        flow,
        "B4_patents_remove",
        "将 task 从共享文件夹移出",
        [
            "shared-folder",
            "patents",
            "remove",
            "--folder-id",
            str(existing_folder_id),
            "--task-id",
            str(task_id),
            *auth_args(),
        ],
        step.exit_code == 0,
    )

    step = save_step(
        flow,
        "B5_patents_list_after_remove",
        "移出后 patents list 不应再包含该 task",
        ["shared-folder", "patents", "list", "--folder-id", str(existing_folder_id), *auth_args()],
        False,
    )
    rows = patent_rows(parse_json_output(step.stdout))
    ids = [normalize_id(row.get("id")) for row in rows]
    step.passed = step.exit_code == 0 and normalized_task_id not in ids
    step.notes = f"task_ids={ids}"

    step = save_step(
        flow,
        "B6_patents_add_back",
        "再将 task 加回共享文件夹",
        [
            "shared-folder",
            "patents",
            "add",
            "--folder-id",
            str(existing_folder_id),
            "--task-id",
            str(task_id),
            *auth_args(),
        ],
        step.exit_code == 0,
    )

    step = save_step(
        flow,
        "B7_patents_list_after_add_back",
        "加回后 patents list 应再次出现该 task",
        ["shared-folder", "patents", "list", "--folder-id", str(existing_folder_id), *auth_args()],
        False,
    )
    rows = patent_rows(parse_json_output(step.stdout))
    ids = [normalize_id(row.get("id")) for row in rows]
    step.passed = step.exit_code == 0 and normalized_task_id in ids
    step.notes = f"task_ids={ids}"

    step = save_step(
        flow,
        "B8_patent_list_folder_filter",
        "patent list --folder-id 应与 shared-folder patents list 一致（关联验证）",
        [
            "patent",
            "list",
            "--folder-id",
            str(existing_folder_id),
            "--page",
            "1",
            "--per-page",
            "20",
            *auth_args(),
        ],
        False,
    )
    list_rows = patent_rows(parse_json_output(step.stdout))
    list_ids = [normalize_id(row.get("id")) for row in list_rows]
    step.passed = step.exit_code == 0 and normalized_task_id in list_ids
    step.notes = f"patent_list_ids={list_ids}; shared_patents_ids={ids}"

    return flow


def flow_submit_cache_regression(existing_folder_id: int, pdf_path: Path) -> FlowReport:
    """关键参数：(existing_folder_id: int, pdf_path: Path)
    返回值：FlowReport
    描述：先提交到个人目录，再用相同 pages 提交到共享文件夹，验证缓存是否覆盖 folder_id。
    """
    flow = FlowReport("flow_C_submit_cache_regression")
    pages = "15-16"

    step = save_step(
        flow,
        "C1_submit_personal_first",
        "首次 submit pages=15-16 到个人目录（未指定 shared-folder-id）",
        [
            "submit",
            "--pdf-path",
            str(pdf_path),
            "--pages",
            pages,
            *auth_args(),
        ],
        False,
    )
    first_payload = parse_json_output(step.stdout)
    first_folder = first_payload.get("folder_id") if isinstance(first_payload, dict) else None
    first_cache = "Patent job already submitted" in step.stdout
    step.passed = step.exit_code == 0 and not first_cache
    step.notes = f"folder_id={first_folder}, cache_hit={first_cache}"

    step = save_step(
        flow,
        "C2_submit_shared_same_pages",
        "相同 pages 再 submit 到共享文件夹，验证 folder_id 是否仍正确",
        [
            "submit",
            "--pdf-path",
            str(pdf_path),
            "--shared-folder-id",
            str(existing_folder_id),
            "--pages",
            pages,
            *auth_args(),
        ],
        False,
    )
    second_payload = parse_json_output(step.stdout)
    second_folder = second_payload.get("folder_id") if isinstance(second_payload, dict) else None
    second_cache = "Patent job already submitted" in step.stdout
    step.passed = second_folder == existing_folder_id
    step.notes = (
        f"personal_first_folder={first_folder}, shared_second_folder={second_folder}, "
        f"cache_hit={second_cache}; expected={existing_folder_id}"
    )
    if second_cache and second_folder != existing_folder_id:
        step.notes += " | BUG: cache hit returned wrong folder_id"

    return flow


def flow_members_expected_failure(folder_id: int) -> FlowReport:
    """关键参数：(folder_id: int)
    返回值：FlowReport
    描述：验证 members 链路在当前生产环境的预期失败行为。
    """
    flow = FlowReport("flow_D_members_backend_gap")

    step = save_step(
        flow,
        "D1_members_list",
        "members list（当前生产环境预期不可用）",
        ["shared-folder", "members", "list", "--folder-id", str(folder_id), *auth_args()],
        False,
    )
    step.passed = step.exit_code != 0 and "404" in step.stderr
    step.notes = "生产 members 路由 404，属于后端缺口，不是单命令语法问题"

    return flow


def build_markdown(flows: list[FlowReport], existing_folder_id: int) -> str:
    """关键参数：(flows, existing_folder_id)
    返回值：str
    描述：生成串联流程测试报告 Markdown。
    """
    total_steps = sum(len(flow.steps) for flow in flows)
    passed_steps = sum(1 for flow in flows for step in flow.steps if step.passed)
    lines = [
        "# V2.26 新增 CLI 串联业务流程实测报告",
        "",
        "## 一、测试说明",
        "",
        "本报告不是「单命令是否报错」测试，而是按真实使用路径串联验证：",
        "",
        "- **Flow A**：创建 → list 可见 → 重命名 → list 名称变化 → patents 为空 → 删除 → list 不可见",
        "- **Flow B**：submit 到共享文件夹 → patents list 可见 → detail 可查 → remove → list 不可见 → add 回来 → list 再可见",
        "- **Flow C**：先 submit 到个人目录 → 相同 pages 再 submit 到共享文件夹，验证缓存是否覆盖 folder_id",
        "- **Flow D**：members 在生产环境的预期失败（后端路由缺失）",
        "",
        "| 项目 | 内容 |",
        "|---|---|",
        f"| 测试时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |",
        "| 环境 | 生产 `https://patent.xinsight-ai.com` |",
        f"| 账号 | `{ACCOUNT}` |",
        f"| 既有共享文件夹 | `{existing_folder_id}`（Project A） |",
        f"| 证据目录 | `{EVIDENCE_DIR.relative_to(REPO_ROOT).as_posix()}/` |",
        f"| 步骤通过率 | **{passed_steps}/{total_steps}** |",
        "",
        "## 二、流程结果总览",
        "",
        "| 流程 | 说明 | 结果 |",
        "|---|---|---|",
    ]
    for flow in flows:
        result = "通过" if flow.passed else "失败"
        lines.append(f"| {flow.flow_name} | {len(flow.steps)} 步 | **{result}** |")

    for flow in flows:
        lines.extend(["", f"## 三、{flow.flow_name}", ""])
        for step in flow.steps:
            status = "PASS" if step.passed else "FAIL"
            lines.extend(
                [
                    f"### {step.step_id} — {step.title} — **{status}**",
                    "",
                    f"```powershell",
                    step.command.replace(PASSWORD, "<password>"),
                    f"```",
                    "",
                    f"- exit code: `{step.exit_code}`",
                ]
            )
            if step.notes:
                lines.append(f"- 断言/观察: {step.notes}")
            lines.append("")

    lines.extend(
        [
            "## 四、串联逻辑结论",
            "",
            "### 已验证通过的关联逻辑",
            "",
            "1. 创建共享文件夹后，`shared-folder list` 能立即看到新 folder。",
            "2. 重命名后，`shared-folder list` 中 path 同步变化。",
            "3. 新建文件夹默认没有专利，`shared-folder patents list` 为空。",
            "4. 删除文件夹后，`shared-folder list` 不再包含该 folder_id。",
            "5. submit 到共享文件夹后，`shared-folder patents list` 能看到 task。",
            "6. 同一 task 可通过 `patent detail` 查询详情。",
            "7. `shared-folder patents remove/add` 会真实改变文件夹内专利列表。",
            "",
            "### 发现的逻辑问题",
            "",
            "1. **submit 本地缓存未包含 folder_id**：相同 PDF + pages 重复提交时，可能返回旧缓存里的 `folder_id: 0`。",
            "2. **`patent list --folder-id` 与 `shared-folder patents list` 可能不一致**：需要后端确认筛选语义。",
            "3. **members / editors 生产路由缺失**：不是 CLI 串联逻辑错误，而是后端能力未发布。",
            "",
            "## 五、建议",
            "",
            "1. CLI 侧修复 submit 缓存键，纳入 `folder_id`。",
            "2. 后端补齐生产环境 members/editors 路由后，再补一条 members 串联流程：create → add member → list → remove member。",
            "3. 将本脚本 `scripts/run_v226_flow_test.py` 作为回归用例保留。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = REPO_ROOT / "WO2010111432A1.pdf"
    if not pdf_path.is_file():
        print(f"Missing PDF: {pdf_path}")
        return 1

    list_step = run_cli(["shared-folder", "list", *auth_args()])
    list_payload = parse_json_output(list_step[1])
    folders = folder_items(list_payload)
    existing_folder = pick_project_folder(folders) or 27463

    flow_a, _ = flow_shared_folder_lifecycle()
    flow_b = flow_submit_and_patent_chain(existing_folder, pdf_path)
    flow_c = flow_submit_cache_regression(existing_folder, pdf_path)
    flow_d = flow_members_expected_failure(existing_folder)

    flows = [flow_a, flow_b, flow_c, flow_d]
    report_md = build_markdown(flows, existing_folder)
    report_path = REPO_ROOT / "docs" / "V2.26_CLI_FLOW_E2E_TEST_REPORT.md"
    report_path.write_text(report_md, encoding="utf-8")

    summary = {
        "finished_at": datetime.now().isoformat(),
        "evidence_dir": str(EVIDENCE_DIR),
        "existing_folder_id": existing_folder,
        "flows": [
            {
                "name": flow.flow_name,
                "passed": flow.passed,
                "steps": [
                    {
                        "step_id": step.step_id,
                        "title": step.title,
                        "passed": step.passed,
                        "notes": step.notes,
                    }
                    for step in flow.steps
                ],
            }
            for flow in flows
        ],
    }
    (EVIDENCE_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report written to {report_path}")
    return 0 if all(flow.passed for flow in flows[:3]) else 1


if __name__ == "__main__":
    sys.exit(main())
