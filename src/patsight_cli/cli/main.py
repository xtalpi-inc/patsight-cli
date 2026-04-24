from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv

import patsight_cli.clients  # noqa: F401 — register built-in clients
from patsight_cli.base import RemoteJobClient
from patsight_cli.clients.patsight import CLI_JOB_TYPE_CHOICES, PatSightClient
from patsight_cli.config import load_yaml_config, merge_client_kwargs, resolve_profile
from patsight_cli.exceptions import ClientError
from patsight_cli.logging_utils import setup_logging
from patsight_cli.registry import ClientRegistry
from patsight_cli.reporting.html import generate_patsight_report
from patsight_cli.store import JobStore

_env = find_dotenv()
if _env and os.path.isfile(_env):
    load_dotenv(_env)


def parse_json_or_text(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def load_payload(args: argparse.Namespace) -> Any:
    if getattr(args, "payload_file", None):
        content = Path(args.payload_file).read_text(encoding="utf-8")
        return parse_json_or_text(content)
    if getattr(args, "payload", None):
        return parse_json_or_text(args.payload)
    if getattr(args, "pdf_path", None):
        payload: dict[str, Any] = {"pdf_path": args.pdf_path}
        if getattr(args, "action", None):
            payload["action"] = args.action
        else:
            payload["job_type"] = getattr(args, "job_type", None) or "structureAndActivity"
        if getattr(args, "folder_id", None) is not None:
            payload["folder_id"] = args.folder_id
        return payload
    return {}


def build_common_client_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "name": getattr(args, "name", None),
        "workdir": getattr(args, "workdir", None),
        "account": getattr(args, "account", None),
        "token": getattr(args, "token", None),
        "folder_id": getattr(args, "folder_id", None),
        "patsight_url": getattr(args, "patsight_url", None),
        "ops_url": getattr(args, "ops_url", None),
        "base_url": getattr(args, "base_url", None),
        "ops_token_url": getattr(args, "ops_token_url", None),
        "verify_url": getattr(args, "verify_url", None),
        "password": getattr(args, "password", None),
    }


def create_client_from_args(args: argparse.Namespace) -> RemoteJobClient:
    config = load_yaml_config(getattr(args, "config", None))
    profile_data = resolve_profile(config, args.profile) if getattr(args, "profile", None) else {}

    client_type = args.client or profile_data.get("client_type")
    if not client_type:
        client_type = "patsight"

    cli_kwargs = build_common_client_kwargs(args)
    merged = merge_client_kwargs(cli_kwargs, profile_data.get("params", {}))
    merged.setdefault("job_store", JobStore())
    return RemoteJobClient.create(client_type=client_type, **merged)


def to_output_payload(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    payload: dict[str, Any] = {}
    for key in ("job_id", "status", "detail", "result", "output_path", "raw"):
        if hasattr(obj, key):
            payload[key] = getattr(obj, key)
    if not payload:
        payload = {"value": repr(obj)}
    return payload


def _print_patsight_submit_hint(submission: dict[str, Any]) -> None:
    job_id = submission.get("job_id")
    if not job_id:
        return
    file_name = submission.get("file_name") or submission.get("file_path", "")
    job_type = submission.get("job_type", "")
    status = submission.get("status", "submitted")
    site = submission.get("site_address", "")
    lines = [
        "",
        "━━━ PatSight job submitted ━━━",
        f"  job_id: {job_id}",
        f"  file: {file_name or '-'}",
        f"  type: {job_type or '-'}",
        f"  status: {status}",
    ]
    if site:
        lines.append(f"  view: {site}")
    lines.append("")
    print("\n".join(lines), file=sys.stderr)


def cmd_clients(_: argparse.Namespace) -> None:
    print(json.dumps({"clients": ClientRegistry.list_clients()}, ensure_ascii=False, indent=2))


def cmd_login(args: argparse.Namespace) -> None:
    client = create_client_from_args(args)
    client.login()
    print(json.dumps({"ok": True, "client": repr(client)}, ensure_ascii=False, indent=2))


def cmd_submit(args: argparse.Namespace) -> None:
    client = create_client_from_args(args)
    client.login()
    submission = client.submit_job(load_payload(args))
    payload = to_output_payload(submission)
    if getattr(client, "client_type", None) == "patsight":
        _print_patsight_submit_hint(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    client = create_client_from_args(args)
    client.login()
    jt = getattr(args, "job_type", None)
    jt_str = jt if isinstance(jt, str) and jt.strip() else ""
    status = client.query_status(args.job_id, job_type=jt_str)
    print(json.dumps(to_output_payload(status), ensure_ascii=False, indent=2))


def cmd_result(args: argparse.Namespace) -> None:
    client = create_client_from_args(args)
    client.login()

    if isinstance(client, PatSightClient):
        jt = getattr(args, "job_type", None)
        result = client.fetch_result(args.job_id, job_type=jt)
    else:
        result = client.fetch_result(args.job_id)

    print(json.dumps(to_output_payload(result), ensure_ascii=False, indent=2))


def cmd_report(args: argparse.Namespace) -> None:
    if getattr(args, "from_json", None):
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        inner = data.get("result") if isinstance(data.get("result"), dict) else data
    elif args.job_id:
        client = create_client_from_args(args)
        client.login()
        if not isinstance(client, PatSightClient):
            raise ClientError("report currently supports PatSight client only")
        jr = client.fetch_result(args.job_id, job_type=getattr(args, "job_type", None))
        inner = jr.result if isinstance(jr.result, dict) else {}
    else:
        raise ClientError("report requires --job-id (live fetch) or --from-json")

    out = args.output or "patsight_report.html"
    path = generate_patsight_report(inner, out)
    print(json.dumps({"ok": True, "html_path": path}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patsight-cli",
        description="patsight-cli: unified CLI for registered remote-job clients (built-in: patsight — PatSight patent extraction).",
    )
    parser.add_argument("--config", help="YAML config with profiles (optional)")
    parser.add_argument("--profile", help="Profile name inside config")
    parser.add_argument("--verbose", action="store_true", help="debug logging")

    sub = parser.add_subparsers(dest="command_name", required=True)

    def add_client_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--client",
            default="patsight",
            help="Registered client type (default: patsight). Register more via ClientRegistry.",
        )
        p.add_argument("--name", default="default", help="Client instance name (token key suffix)")
        p.add_argument("--workdir", help="Output directory for downloads (default: env or ~/.local/share/...)")
        p.add_argument("--account", help="OPS / PatSight account")
        p.add_argument("--password", help="OPS / PatSight password")
        p.add_argument("--token", help="Existing OPS token")
        p.add_argument("--folder-id", type=int, help="PatSight folder id")
        p.add_argument(
            "--patsight-url",
            help="PatSight site origin; patent API is {origin}/patent/api (env: PATSIGHT_URL)",
        )
        p.add_argument(
            "--ops-url",
            help="OPS origin; token/verify paths are derived under /api/... (env: OPS_URL)",
        )
        p.add_argument(
            "--base-url",
            help="Override patent API base (default: PATSIGHT_URL + /patent/api)",
        )
        p.add_argument("--ops-token-url", help="Override OPS token URL (default: OPS_URL + /api/v2/public/token)")
        p.add_argument(
            "--verify-url",
            help="Override OPS verify URL (default: OPS_URL + /api/public/token/verify)",
        )

    p_c = sub.add_parser("clients", help="List registered client types")
    p_c.set_defaults(func=cmd_clients)

    p_login = sub.add_parser("login", help="Verify credentials and cache token")
    add_client_flags(p_login)
    p_login.set_defaults(func=cmd_login)

    p_sub = sub.add_parser("submit", help="Submit extraction job (PatSight: PDF path + --job-type)")
    add_client_flags(p_sub)
    p_sub.add_argument("--payload", help="JSON payload string")
    p_sub.add_argument("--payload-file", help="JSON payload file")
    p_sub.add_argument("--pdf-path", help="Path to patent PDF")
    p_sub.add_argument(
        "--job-type",
        default="structureAndActivity",
        choices=list(CLI_JOB_TYPE_CHOICES),
        help="Task kind (mapped to PatSight API action codes)",
    )
    p_sub.add_argument(
        "--action",
        default=None,
        help="Deprecated: raw API action string; when set, overrides --job-type",
    )
    p_sub.set_defaults(func=cmd_submit)

    p_st = sub.add_parser("status", help="Query job status")
    add_client_flags(p_st)
    p_st.add_argument("--job-id", required=True)
    p_st.add_argument(
        "--job-type",
        default=None,
        choices=list(CLI_JOB_TYPE_CHOICES),
        help="Optional: pin list view (default: try view=0 then view=1)",
    )
    p_st.set_defaults(func=cmd_status)

    p_res = sub.add_parser("result", help="Fetch finished job result (exports CSV under workdir)")
    add_client_flags(p_res)
    p_res.add_argument("--job-id", required=True)
    p_res.add_argument(
        "--job-type",
        default=None,
        choices=list(CLI_JOB_TYPE_CHOICES),
        help="Optional: skip auto view scan; result links use this type if set",
    )
    p_res.set_defaults(func=cmd_result)

    p_rep = sub.add_parser("report", help="Generate HTML summary (from API or JSON)")
    add_client_flags(p_rep)
    p_rep.add_argument("--job-id", help="PatSight job id (with live fetch)")
    p_rep.add_argument(
        "--job-type",
        default=None,
        choices=list(CLI_JOB_TYPE_CHOICES),
        help="Optional: same as result",
    )
    p_rep.add_argument(
        "--from-json",
        metavar="PATH",
        help="Build report from saved `result` JSON (object or full CLI output)",
    )
    p_rep.add_argument("-o", "--output", help="Output HTML path (default: patsight_report.html)")
    p_rep.set_defaults(func=cmd_report)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
    try:
        args.func(args)
    except ClientError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(
            json.dumps({"ok": False, "error": f"unexpected error: {e}"}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        sys.exit(3)


if __name__ == "__main__":
    main()
