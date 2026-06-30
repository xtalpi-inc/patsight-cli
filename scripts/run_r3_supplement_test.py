"""针对三份补充专利 PDF 执行 R3 结构与活性导出矩阵测试，并保存证据。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "r3_supplement_20260610"
OUTPUT = EVIDENCE / "output"

# 若已有提交记录，可在此填入 job_id 跳过重复 submit（留空则重新提交）
RESUME_JOB_IDS: dict[str, str] = {
    "WO2010111432A1": "2064622971598807040",
    "WO2012016698A2": "2064623050174898176",
    "WO2012107708A1": "2064623110337994752",
}

PDFS = [
    ROOT / "WO2010111432A1.pdf",
    ROOT / "WO2012016698A2.pdf",
    ROOT / "WO2012107708A1.pdf",
]

def parse_cli_json(stdout: str) -> dict[str, Any] | None:
    """参数：(stdout: str) 返回值：dict[str, Any] | None 描述：从混合 stdout 中提取 JSON 对象。"""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : idx + 1])
                except json.JSONDecodeError:
                    return None
    return None


R3_MATRIX = [
    ("bioactivity", "csv"),
    ("bioactivity", "xlsx"),
    ("bioactivity", "sdf"),
    ("admet", "csv"),
    ("admet", "xlsx"),
    ("admet", "sdf"),
    ("namedStructures", "csv"),
    ("namedStructures", "xlsx"),
    ("namedStructures", "sdf"),
]


def run_cli(args: list[str], label: str) -> dict[str, Any]:
    """参数：(args: list[str], label: str) 返回值：dict[str, Any] 描述：执行 CLI 并保存 stdout/stderr。"""
    cmd = [sys.executable, "-m", "patsight_cli.cli.main", *args]
    stdout_path = EVIDENCE / f"{label}.stdout.txt"
    stderr_path = EVIDENCE / f"{label}.stderr.txt"
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")
    payload: dict[str, Any] = {
        "label": label,
        "cmd": " ".join(args),
        "exit_code": proc.returncode,
        "stdout_path": str(stdout_path.relative_to(ROOT)),
        "stderr_path": str(stderr_path.relative_to(ROOT)),
    }
    payload["json"] = parse_cli_json(proc.stdout)
    if payload["json"] is None and proc.stdout.strip():
        payload["stdout_preview"] = (proc.stdout or "")[:500]
    if proc.returncode != 0:
        payload["error_preview"] = (proc.stderr or proc.stdout or "")[:500]
    return payload


def wait_job(job_id: str, label_prefix: str, timeout_sec: int = 3600) -> dict[str, Any]:
    """参数：(job_id: str, label_prefix: str, timeout_sec: int) 返回值：dict[str, Any] 描述：轮询任务直至完成。"""
    deadline = time.time() + timeout_sec
    last: dict[str, Any] = {}
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        last = run_cli(
            ["status", "--job-id", job_id, "--job-type", "structureAndActivity"],
            f"{label_prefix}_status_{attempt:02d}",
        )
        status = str((last.get("json") or {}).get("status") or "").lower()
        if status in {"done", "completed", "success", "finished"}:
            last["final_status"] = status
            return last
        if status in {"failed", "error", "cancelled", "canceled", "timeout"}:
            last["final_status"] = status
            return last
        time.sleep(30)
    last["final_status"] = "timeout"
    return last


def probe_backend_counts(job_id: str, label_prefix: str) -> dict[str, Any]:
    """参数：(job_id: str, label_prefix: str) 返回值：dict[str, Any] 描述：探测后端 export_ids 数量。"""
    from dotenv import find_dotenv, load_dotenv

    env_path = find_dotenv()
    if env_path:
        load_dotenv(env_path)

    sys.path.insert(0, str(ROOT / "src"))
    from patsight_cli.clients.patsight import PatSightClient

    client = PatSightClient(workdir=str(OUTPUT))
    status = client.get_job_status(job_id=job_id, view=0)
    task_id = str((status.get("task_info") or {}).get("id") or status.get("job_id") or job_id)
    stats = client.get_task_statistics(task_id)
    bio_ids = client.list_compound_export_ids(task_id, bioactivity_data_type=0)
    admet_ids = client.list_compound_export_ids(task_id, bioactivity_data_type=1)
    struct_ids = client.list_structure_ids(task_id)
    result = {
        "job_id": job_id,
        "task_id": task_id,
        "statistics": stats,
        "bioactivity_export_ids": len(bio_ids),
        "admet_export_ids": len(admet_ids),
        "named_structure_ids": len(struct_ids),
        "pdf_pages": (status.get("task_info") or {}).get("pdf_pages"),
        "file_name": (status.get("task_info") or {}).get("file_name"),
    }
    probe_path = EVIDENCE / f"{label_prefix}_probe.json"
    probe_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    """参数：无 返回值：int 描述：执行三份 PDF 的 R3 补测并写入 summary。"""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "branch": subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(ROOT), text=True
        ).strip(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True
        ).strip(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "pdfs": [],
    }

    for idx, pdf in enumerate(PDFS, start=1):
        stem = pdf.stem
        prefix = f"{idx:02d}_{stem}"
        pdf_entry: dict[str, Any] = {"pdf": pdf.name, "stem": stem, "exists": pdf.exists()}
        if not pdf.exists():
            pdf_entry["error"] = "PDF not found"
            summary["pdfs"].append(pdf_entry)
            continue

        resume_job_id = RESUME_JOB_IDS.get(stem, "").strip()
        if resume_job_id:
            job_id = resume_job_id
            pdf_entry["job_id"] = job_id
            pdf_entry["submit"] = {"skipped": True, "job_id": job_id}
        else:
            submit = run_cli(
                [
                    "submit",
                    "--pdf-path",
                    str(pdf),
                    "--job-type",
                    "structureAndActivity",
                    "--workdir",
                    str(OUTPUT),
                ],
                f"{prefix}_submit",
            )
            pdf_entry["submit"] = submit
            job_id = str((submit.get("json") or {}).get("job_id") or "")
            if not job_id:
                pdf_entry["error"] = "submit failed"
                summary["pdfs"].append(pdf_entry)
                continue
            pdf_entry["job_id"] = job_id
        status_result = wait_job(job_id, prefix)
        pdf_entry["wait"] = {
            "final_status": status_result.get("final_status"),
            "last_status_json": status_result.get("json"),
        }
        if status_result.get("final_status") not in {"done", "completed", "success", "finished"}:
            pdf_entry["error"] = f"job not done: {status_result.get('final_status')}"
            summary["pdfs"].append(pdf_entry)
            continue

        pdf_entry["probe"] = probe_backend_counts(job_id, prefix)

        exports: list[dict[str, Any]] = []
        for export_type, fmt in R3_MATRIX:
            label = f"{prefix}_export_{export_type}_{fmt}"
            result = run_cli(
                [
                    "result",
                    "--job-id",
                    job_id,
                    "--job-type",
                    "structureAndActivity",
                    "--export-type",
                    export_type,
                    "--format",
                    fmt,
                    "--workdir",
                    str(OUTPUT),
                ],
                label,
            )
            ok_json = result.get("json") or {}
            output_path = ok_json.get("output_path")
            file_exists = bool(output_path and Path(output_path).exists())
            file_size = Path(output_path).stat().st_size if file_exists else 0
            exports.append(
                {
                    "export_type": export_type,
                    "format": fmt,
                    "ok": result["exit_code"] == 0 and file_exists,
                    "exit_code": result["exit_code"],
                    "output_path": output_path,
                    "file_size": file_size,
                    "error_preview": result.get("error_preview"),
                }
            )
        pdf_entry["exports"] = exports

        default_export = run_cli(
            [
                "result",
                "--job-id",
                job_id,
                "--job-type",
                "structureAndActivity",
                "--workdir",
                str(OUTPUT),
            ],
            f"{prefix}_default_export",
        )
        pdf_entry["default_export"] = {
            "ok": default_export["exit_code"] == 0,
            "json": default_export.get("json"),
            "exit_code": default_export["exit_code"],
        }
        summary["pdfs"].append(pdf_entry)

    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    summary_path = EVIDENCE / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
