"""执行 PatSight CLI 真实链路测试，并保存脱敏证据。"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


REDACT_KEYS = (
    "PATSIGHT_OPS_ACCOUNT",
    "PATSIGHT_OPS_PASSWORD",
    "PATSIGHT_PASSWORD",
    "PATSIGHT_TOKEN",
    "HOROLOGIUM_API_KEY",
)

SAMPLE_PATENT_URLS = (
    "https://patentimages.storage.googleapis.com/pdfs/US7654321.pdf",
    "https://patentimages.storage.googleapis.com/pdfs/US20100219964A1.pdf",
    "https://patentimages.storage.googleapis.com/pdfs/US10000000.pdf",
)


def redact_text(value: str) -> str:
    """
    参数：(value: str)
    返回值：str
    描述：脱敏日志中的账号、密码和令牌内容。
    """
    masked = value
    for key in REDACT_KEYS:
        secret = os.environ.get(key, "")
        if secret:
            masked = masked.replace(secret, f"<redacted:{key}>")
    masked = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer <redacted>", masked)
    masked = re.sub(r'"token"\s*:\s*"[^"]+"', '"token": "<redacted>"', masked)
    masked = re.sub(
        r"(https://patent-prod-s3\.xinsight-ai\.com/[^\"?\s]+)\?[^\"\s]+",
        r"\1?<redacted-presigned-query>",
        masked,
    )
    masked = re.sub(r"X-Amz-(Credential|Signature)=[^&\"\s]+", r"X-Amz-\1=<redacted>", masked)
    return masked


def write_text(path: Path, content: str) -> None:
    """
    参数：(path: Path, content: str)
    返回值：None
    描述：写入 UTF-8 文本证据文件。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact_text(content), encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    """
    参数：(path: Path, data: Any)
    返回值：None
    描述：写入脱敏 JSON 证据文件。
    """
    text = json.dumps(data, ensure_ascii=False, indent=2)
    write_text(path, text)


def run_command(args: list[str], evidence_dir: Path, name: str, env: dict[str, str]) -> dict[str, Any]:
    """
    参数：(args: list[str], evidence_dir: Path, name: str, env: dict[str, str])
    返回值：dict[str, Any]
    描述：执行 CLI 命令并保存 stdout、stderr 和元数据。
    """
    started_at = datetime.now().isoformat(timespec="seconds")
    completed = subprocess.run(args, capture_output=True, text=True, env=env)
    result = {
        "name": name,
        "started_at": started_at,
        "returncode": completed.returncode,
        "command": " ".join(args),
        "stdout_file": f"{name}.stdout.txt",
        "stderr_file": f"{name}.stderr.txt",
    }
    write_text(evidence_dir / f"{name}.stdout.txt", completed.stdout)
    write_text(evidence_dir / f"{name}.stderr.txt", completed.stderr)
    write_json(evidence_dir / f"{name}.meta.json", result)
    print(f"[{name}] returncode={completed.returncode}", flush=True)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "meta": result,
    }


def ensure_sample_pdf(evidence_dir: Path) -> Path:
    """
    参数：(evidence_dir: Path)
    返回值：Path
    描述：下载公开专利 PDF 样例，供真实提交测试使用。
    """
    pdf_path = evidence_dir / "sample_patent.pdf"
    for url in SAMPLE_PATENT_URLS:
        try:
            response = requests.get(url, timeout=(10, 60))
            if response.status_code == 200 and response.content.startswith(b"%PDF"):
                pdf_path.write_bytes(response.content)
                write_json(
                    evidence_dir / "sample_pdf.meta.json",
                    {"source_url": url, "size_bytes": len(response.content)},
                )
                print(f"[sample_pdf] downloaded size={len(response.content)}", flush=True)
                return pdf_path
        except requests.RequestException as exc:
            write_text(evidence_dir / "sample_pdf.download.log", f"{url}\n{exc}\n")
    raise RuntimeError("No sample patent PDF could be downloaded.")


def parse_json_stdout(raw_stdout: str) -> dict[str, Any]:
    """
    参数：(raw_stdout: str)
    返回值：dict[str, Any]
    描述：解析 CLI stdout 中的 JSON 对象。
    """
    text = raw_stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise
        return json.loads(text[start : end + 1])


def run_model_probe(evidence_dir: Path) -> dict[str, Any]:
    """
    参数：(evidence_dir: Path)
    返回值：dict[str, Any]
    描述：验证 Horologium 模型配置可用性并保存脱敏响应。
    """
    base_url = os.environ["HOROLOGIUM_BASE_URL"].rstrip("/")
    api_key = os.environ["HOROLOGIUM_API_KEY"]
    model = os.environ["HOROLOGIUM_MODEL"]
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": "请用一句中文回复：PatSight CLI 真实测试连通性正常。"}],
        },
        timeout=(10, 120),
    )
    payload: dict[str, Any]
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text}
    result = {"status_code": response.status_code, "model": model, "response": payload}
    write_json(evidence_dir / "model_probe.json", result)
    print(f"[model_probe] status_code={response.status_code}", flush=True)
    return result


def build_env(evidence_dir: Path) -> dict[str, str]:
    """
    参数：(evidence_dir: Path)
    返回值：dict[str, str]
    描述：构造隔离的 CLI 运行环境，避免污染用户默认缓存。
    """
    env = os.environ.copy()
    env["PATSIGHT_CLI_CLIENT_DB"] = str(evidence_dir / "tasks.db")
    env["PATSIGHT_CLI_WORKDIR"] = str(evidence_dir / "output")
    return env


def main() -> int:
    """
    参数：无
    返回值：int
    描述：执行真实测试主流程。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--poll-seconds", type=int, default=900)
    parser.add_argument("--poll-interval", type=int, default=30)
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    env = build_env(evidence_dir)
    summary: dict[str, Any] = {"started_at": datetime.now().isoformat(timespec="seconds"), "steps": []}

    sample_pdf = ensure_sample_pdf(evidence_dir)
    summary["sample_pdf"] = str(sample_pdf)

    model_probe = run_model_probe(evidence_dir)
    summary["steps"].append({"name": "model_probe", "status_code": model_probe["status_code"]})

    for name, command in (
        ("cli_clients", [sys.executable, "-m", "patsight_cli.cli.main", "clients"]),
        ("cli_login", [sys.executable, "-m", "patsight_cli.cli.main", "login", "--client", "patsight"]),
    ):
        result = run_command(command, evidence_dir, name, env)
        summary["steps"].append({"name": name, "returncode": result["returncode"]})
        if result["returncode"] != 0:
            write_json(evidence_dir / "summary.json", summary)
            return result["returncode"]

    if args.job_id:
        job_id = str(args.job_id)
    else:
        submit_command = [
            sys.executable,
            "-m",
            "patsight_cli.cli.main",
            "submit",
            "--client",
            "patsight",
            "--pdf-path",
            str(sample_pdf),
            "--job-type",
            "structureAndActivity",
        ]
        submit_result = run_command(submit_command, evidence_dir, "cli_submit", env)
        summary["steps"].append({"name": "cli_submit", "returncode": submit_result["returncode"]})
        if submit_result["returncode"] != 0:
            write_json(evidence_dir / "summary.json", summary)
            return submit_result["returncode"]

        submit_payload = parse_json_stdout(submit_result["stdout"])
        job_id = str(submit_payload["job_id"])
    summary["job_id"] = job_id
    print(f"[cli_submit] job_id={job_id}", flush=True)

    deadline = time.time() + args.poll_seconds
    final_status: dict[str, Any] = {}
    status_index = 0
    while time.time() < deadline:
        status_index += 1
        status_result = run_command(
            [
                sys.executable,
                "-m",
                "patsight_cli.cli.main",
                "status",
                "--client",
                "patsight",
                "--job-id",
                job_id,
            ],
            evidence_dir,
            f"cli_status_{status_index:02d}",
            env,
        )
        summary["steps"].append({"name": f"cli_status_{status_index:02d}", "returncode": status_result["returncode"]})
        if status_result["returncode"] != 0:
            break
        final_status = parse_json_stdout(status_result["stdout"])
        normalized_status = str(final_status.get("status", "")).lower()
        print(f"[cli_status_{status_index:02d}] status={normalized_status}", flush=True)
        if normalized_status in {"done", "completed", "success", "finished", "failed", "error", "cancelled", "canceled", "timeout"}:
            break
        time.sleep(args.poll_interval)

    summary["final_status"] = final_status
    if str(final_status.get("status", "")).lower() in {"done", "completed", "success", "finished"}:
        result_step = run_command(
            [
                sys.executable,
                "-m",
                "patsight_cli.cli.main",
                "result",
                "--client",
                "patsight",
                "--job-id",
                job_id,
            ],
            evidence_dir,
            "cli_result",
            env,
        )
        summary["steps"].append({"name": "cli_result", "returncode": result_step["returncode"]})
        if result_step["returncode"] == 0:
            result_file = evidence_dir / "cli_result.stdout.txt"
            report_step = run_command(
                [
                    sys.executable,
                    "-m",
                    "patsight_cli.cli.main",
                    "report",
                    "--from-json",
                    str(result_file),
                    "-o",
                    str(evidence_dir / "patsight_report.html"),
                ],
                evidence_dir,
                "cli_report_from_real_result",
                env,
            )
            summary["steps"].append({"name": "cli_report_from_real_result", "returncode": report_step["returncode"]})

    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(evidence_dir / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
