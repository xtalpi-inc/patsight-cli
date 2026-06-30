"""PatSight CLI 入口，负责参数解析并调度远程任务与共享文件夹命令。"""

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
from patsight_cli.exceptions import ClientError, ExportError
from patsight_cli.export.batch_zip import export_patents_to_zip
from patsight_cli.patent_filters import apply_patent_filters, has_client_filters, patent_rows_from_response
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


def _reject_payload_submit_flag_conflicts(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：阻止 payload 模式下静默忽略结构化 submit 参数。
    """
    if not (getattr(args, "payload_file", None) or getattr(args, "payload", None)):
        return
    conflict_flags = {
        "--pdf-path": getattr(args, "pdf_path", None),
        "--action": getattr(args, "action", None),
        "--job-type": getattr(args, "job_type", None),
        "--folder-id": getattr(args, "folder_id", None),
        "--shared-folder-id": getattr(args, "shared_folder_id", None),
        "--pages": getattr(args, "pages", None),
    }
    used_flags = [flag_name for flag_name, value in conflict_flags.items() if value is not None]
    if used_flags:
        raise ClientError(
            "--payload/--payload-file cannot be combined with submit flags: "
            + ", ".join(used_flags)
        )


def load_payload(args: argparse.Namespace) -> Any:
    _reject_payload_submit_flag_conflicts(args)
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
        shared_folder_id = getattr(args, "shared_folder_id", None)
        if shared_folder_id is not None and getattr(args, "folder_id", None) is not None:
            raise ClientError("--shared-folder-id cannot be used together with --folder-id.")
        if shared_folder_id is not None:
            payload["folder_id"] = shared_folder_id
        elif getattr(args, "folder_id", None) is not None:
            payload["folder_id"] = args.folder_id
        if getattr(args, "pages", None):
            payload["pages"] = args.pages
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
    pdf_slice = submission.get("pdf_slice", "")
    lines = [
        "",
        "━━━ PatSight job submitted ━━━",
        f"  job_id: {job_id}",
        f"  file: {file_name or '-'}",
        f"  type: {job_type or '-'}",
        f"  status: {status}",
    ]
    if pdf_slice:
        lines.append(f"  pages: {pdf_slice}")
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


def _validate_remark(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > 139:
        raise ClientError("--remark must be at most 139 characters.")
    return value


def _task_id_for_remark(payload: dict[str, Any]) -> int:
    raw_task_id = payload.get("job_id") or payload.get("id")
    if raw_task_id is None:
        raise ClientError("submit succeeded but response did not include a numeric task id for remark.")
    try:
        return int(raw_task_id)
    except (TypeError, ValueError) as exc:
        raise ClientError(f"submit response task id is not numeric: {raw_task_id!r}") from exc


def cmd_submit(args: argparse.Namespace) -> None:
    client = create_client_from_args(args)
    client.login()
    submission = client.submit_job(load_payload(args))
    payload = to_output_payload(submission)
    remark = _validate_remark(getattr(args, "remark", None))
    if remark is not None:
        if not isinstance(client, PatSightClient):
            raise ClientError("submit --remark currently supports PatSight client only")
        remark_task_id = _task_id_for_remark(payload)
        try:
            remark_response = client.set_patent_remark(remark_task_id, remark)
            payload["remark"] = {"ok": True, "response": remark_response}
        except Exception as exc:  # noqa: BLE001
            raise ClientError(
                f"submit succeeded but remark update failed for task_id={remark_task_id}: {exc}"
            ) from exc
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


def _explicit_job_type_from_args(args: argparse.Namespace) -> str | None:
    jt = getattr(args, "job_type", None)
    if isinstance(jt, str) and jt.strip():
        return jt.strip()
    return None


def _resolve_result_job_type(
    client: PatSightClient,
    args: argparse.Namespace,
    status: dict[str, Any] | None = None,
) -> str:
    from patsight_cli.clients.patsight import resolve_job_type_from_status

    payload = status
    if payload is None:
        payload = client.get_job_status_for_job_id(job_id=args.job_id, folder_id=client.folder_id)
    return resolve_job_type_from_status(payload, explicit=_explicit_job_type_from_args(args))


def cmd_result(args: argparse.Namespace) -> None:
    client = create_client_from_args(args)
    client.login()

    if isinstance(client, PatSightClient):
        result = client.fetch_result(
            args.job_id,
            job_type=_explicit_job_type_from_args(args),
            export_type=getattr(args, "export_type", None),
            file_format=getattr(args, "format", None),
        )
    else:
        result = client.fetch_result(args.job_id)

    print(json.dumps(to_output_payload(result), ensure_ascii=False, indent=2))


def cmd_export(args: argparse.Namespace) -> None:
    client = create_client_from_args(args)
    client.login()
    if not isinstance(client, PatSightClient):
        raise ClientError("export currently supports PatSight client only")

    status = client.get_job_status_for_job_id(job_id=args.job_id, folder_id=client.folder_id)
    try:
        jt = _resolve_result_job_type(client, args, status=status)
    except ExportError as exc:
        raise ExportError(
            f"{exc} Pass --job-type explicitly for export validation."
        ) from exc
    task_status = str(status.get("status") or "").strip().lower()
    if task_status not in {"done", "completed", "success", "finished"}:
        raise ExportError(f"Job is not finished: job_id={args.job_id}, status={status.get('status')}")

    task_info = status.get("task_info") or status
    from patsight_cli.clients.patsight import task_action_from_status, task_id_from_status

    task_id = task_id_from_status(status, args.job_id)
    output_path = client.export_task(
        task_id,
        job_type=jt,  # type: ignore[arg-type]
        export_type=getattr(args, "export_type", None),
        file_format=getattr(args, "format", None),
        file_name=task_info.get("file_name", ""),
        task_action=task_action_from_status(status),
    )
    from patsight_cli.export_options import resolve_export_options

    export_type, file_format = resolve_export_options(
        jt,
        export_type=getattr(args, "export_type", None),
        file_format=getattr(args, "format", None),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "job_id": args.job_id,
                "task_id": task_id,
                "job_type": jt,
                "export_type": export_type,
                "file_format": file_format,
                "output_path": output_path,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_report(args: argparse.Namespace) -> None:
    if getattr(args, "from_json", None):
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        inner = data.get("result") if isinstance(data.get("result"), dict) else data
    elif args.job_id:
        client = create_client_from_args(args)
        client.login()
        if not isinstance(client, PatSightClient):
            raise ClientError("report currently supports PatSight client only")
        jr = client.fetch_result(
            args.job_id,
            job_type=_explicit_job_type_from_args(args),
            export_type=getattr(args, "export_type", None),
            file_format=getattr(args, "format", None),
        )
        inner = jr.result if isinstance(jr.result, dict) else {}
    else:
        raise ClientError("report requires --job-id (live fetch) or --from-json")

    out = args.output or "patsight_report.html"
    path = generate_patsight_report(inner, out)
    print(json.dumps({"ok": True, "html_path": path}, ensure_ascii=False, indent=2))


def create_patsight_client_for_command(args: argparse.Namespace, command_name: str) -> PatSightClient:
    """关键参数：(args: argparse.Namespace, command_name: str)
    返回值：PatSightClient
    描述：为 PatSight 专属命令创建并登录客户端。
    """
    client = create_client_from_args(args)
    client.login()
    if not isinstance(client, PatSightClient):
        raise ClientError(f"{command_name} currently supports PatSight client only")
    return client


def cmd_shared_folder_list(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：列出当前用户可访问的共享文件夹树并输出 JSON。
    """
    client = create_patsight_client_for_command(args, "shared-folder")
    response = client.list_shared_folders(view=args.view)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_create(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：创建共享文件夹或其子文件夹并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder")
    response = client.create_shared_folder(args.name, parent_id=args.parent_id, view=args.view)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_rename(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：重命名共享文件夹并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder")
    response = client.rename_shared_folder(args.folder_id, args.name)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_delete(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：删除共享文件夹并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder")
    response = client.delete_shared_folder(args.folder_id)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_members_list(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：列出一级共享文件夹成员并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder members")
    response = client.list_shared_folder_members(args.folder_id)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_members_add(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：向一级共享文件夹添加成员并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder members")
    response = client.add_shared_folder_member(args.folder_id, args.email, role=args.role)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_members_remove(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：删除一级共享文件夹中的指定邮箱成员并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder members")
    response = client.remove_shared_folder_member(args.folder_id, args.email)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_members_role(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：修改一级共享文件夹成员角色并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder members")
    response = client.update_shared_folder_member_role(args.folder_id, args.email, args.role)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_patents_list(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：列出共享文件夹内专利并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder patents")
    response = client.list_shared_folder_patents(args.folder_id)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_patents_add(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：将专利加入共享文件夹并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder patents")
    response = client.add_shared_folder_patents(args.folder_id, args.task_id)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_shared_folder_patents_remove(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：将专利从共享文件夹移出并输出后端响应。
    """
    client = create_patsight_client_for_command(args, "shared-folder patents")
    response = client.remove_shared_folder_patents(args.folder_id, args.task_id)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_patent_list(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：分页查询当前用户可访问的专利并输出 JSON。
    """
    _require_fetch_all_for_client_filters(args, "patent list")
    client = create_patsight_client_for_command(args, "patent")
    response = _list_patents_for_args(client, args)
    if has_client_filters(
        remark=args.remark,
        creator_email=args.creator_email,
        unfiled=args.unfiled,
        multi_folder=args.multi_folder,
    ):
        response = apply_patent_filters(
            response,
            remark=args.remark,
            creator_email=args.creator_email,
            unfiled=args.unfiled,
            multi_folder=args.multi_folder,
        )
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def _require_fetch_all_for_client_filters(args: argparse.Namespace, command_name: str) -> None:
    """关键参数：(args: argparse.Namespace, command_name: str)
    返回值：None
    描述：要求客户端筛选在完整分页数据上执行，避免单页误报。
    """
    if getattr(args, "fetch_all", False):
        return
    if has_client_filters(
        remark=getattr(args, "remark", None),
        creator_email=getattr(args, "creator_email", None),
        unfiled=getattr(args, "unfiled", False),
        multi_folder=getattr(args, "multi_folder", False),
    ):
        raise ClientError(f"{command_name} client-side filters require --fetch-all.")


def _patent_list_kwargs(args: argparse.Namespace, *, page: int | None = None) -> dict[str, Any]:
    return {
        "page": page if page is not None else args.page,
        "per_page": args.per_page,
        "sort_by": args.sort_by,
        "sort_dir": args.sort_dir,
        "status": args.status,
        "is_collection": args.is_collection,
        "folder_id": args.folder_id,
        "name": args.name,
        "name_field": args.name_field,
        "searched_smiles": args.searched_smiles,
        "view": args.view,
        "exclude_action": args.exclude_action,
    }


def _list_patents_for_args(client: PatSightClient, args: argparse.Namespace) -> dict[str, Any]:
    if not args.fetch_all:
        return client.list_accessible_patents(**_patent_list_kwargs(args))

    per_page = args.per_page or 100
    start_page = args.page or 1
    max_pages = getattr(getattr(client, "config", None), "list_tasks_max_pages", 500)
    merged: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []
    total_count: int | None = None

    for index in range(max_pages):
        page = start_page + index
        kwargs = _patent_list_kwargs(args, page=page)
        kwargs["per_page"] = per_page
        response = client.list_accessible_patents(**kwargs)
        if merged is None:
            merged = response
        data = response.get("data") if isinstance(response, dict) else None
        if isinstance(data, dict) and isinstance(data.get("count"), int):
            total_count = data["count"]
        page_rows = patent_rows_from_response(response)
        rows.extend(page_rows)
        if not page_rows:
            break
        if total_count is not None and len(rows) >= total_count:
            break

    if merged is None:
        merged = {"code": 1, "data": {"count": 0, "task_info": []}, "error": "", "message": ""}
    data = merged.setdefault("data", {})
    if isinstance(data, dict):
        data["task_info"] = rows
        data["count"] = len(rows)
        data["fetched_all"] = True
    return merged


def cmd_patent_detail(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：查询单篇专利详情并输出 JSON。
    """
    client = create_patsight_client_for_command(args, "patent")
    response = client.get_patent_detail(args.task_id)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_patent_editors(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：查询专利最后编辑用户和时间并输出 JSON。
    """
    client = create_patsight_client_for_command(args, "patent")
    response = client.list_patent_editors(args.task_id)
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_patent_remark_set(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：设置或清除指定专利的用户备注。
    """
    client = create_patsight_client_for_command(args, "patent remark")
    response = client.set_patent_remark(args.task_id, _validate_remark(args.remark))
    print(json.dumps(to_output_payload(response), ensure_ascii=False, indent=2))


def cmd_patent_export_zip(args: argparse.Namespace) -> None:
    """关键参数：(args: argparse.Namespace)
    返回值：None
    描述：按专利列表筛选结果本地打包导出 zip。
    """
    if not args.zip:
        raise ClientError("patent export currently requires --zip.")
    _require_fetch_all_for_client_filters(args, "patent export --zip")
    client = create_patsight_client_for_command(args, "patent export")
    result = export_patents_to_zip(
        client,
        output_path=args.output,
        export_type=args.export_type,
        file_format=args.format,
        fetch_all=args.fetch_all,
        include_editors=not args.no_editors,
        list_kwargs=_patent_list_kwargs(args),
        filter_kwargs={
            "remark": args.remark,
            "creator_email": args.creator_email,
            "unfiled": args.unfiled,
            "multi_folder": args.multi_folder,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _add_export_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--export-type",
        default=None,
        help=(
            "Export data category. structureAndActivity: bioactivity (default), admet, namedStructures; "
            "reaction: reactions (default); iupac: structures (default). "
            "Mismatched job_type/export_type combinations raise an error."
        ),
    )
    p.add_argument(
        "--format",
        default=None,
        dest="format",
        help=(
            "Export file format. Defaults: csv for structure/activity and iupac, xlsx for reaction. "
            "Allowed formats depend on export-type and job-type."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patsight-cli",
        description="patsight-cli: unified CLI for registered remote-job clients (built-in: patsight — PatSight patent extraction).",
    )
    parser.add_argument("--config", help="YAML config with profiles (optional)")
    parser.add_argument("--profile", help="Profile name inside config")
    parser.add_argument("--verbose", action="store_true", help="debug logging")

    sub = parser.add_subparsers(dest="command_name", required=True)

    def add_client_flags(
        p: argparse.ArgumentParser,
        *,
        folder_id_required: bool = False,
        folder_id_help: str = "PatSight folder id",
        client_name_flag: str = "--name",
    ) -> None:
        p.add_argument(
            "--client",
            default="patsight",
            help="Registered client type (default: patsight). Register more via ClientRegistry.",
        )
        p.add_argument(client_name_flag, dest="name", default="default", help="Client instance name (token key suffix)")
        p.add_argument("--workdir", help="Output directory for downloads (default: env or ~/.local/share/...)")
        p.add_argument("--account", help="OPS / PatSight account")
        p.add_argument("--password", help="OPS / PatSight password")
        p.add_argument("--token", help="Existing OPS token")
        p.add_argument("--folder-id", type=int, required=folder_id_required, help=folder_id_help)
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
        default=None,
        choices=list(CLI_JOB_TYPE_CHOICES),
        help="Task kind (mapped to PatSight API action codes)",
    )
    p_sub.add_argument(
        "--action",
        default=None,
        help="Deprecated: raw API action string; when set, overrides --job-type",
    )
    p_sub.add_argument(
        "--pages",
        default=None,
        metavar="RANGE",
        help=(
            "Optional page ranges for extraction (maps to API pdf_slice). "
            "Single-action jobs: comma-separated ranges like '1-5,7,9-12'. "
            "Composite jobs (e.g. structureAndActivityReaction): semicolon-separated "
            "parts like '1-5,7;9-12,15'. Omit to process all pages."
        ),
    )
    p_sub.add_argument(
        "--shared-folder-id",
        type=int,
        help="Top-level shared folder id for submitting directly into a shared folder",
    )
    p_sub.add_argument(
        "--remark",
        default=None,
        help="Optional user remark saved to the created patent task (max 139 characters)",
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

    p_res = sub.add_parser("result", help="Fetch finished job result and export file under workdir")
    add_client_flags(p_res)
    p_res.add_argument("--job-id", required=True)
    p_res.add_argument(
        "--job-type",
        default=None,
        choices=list(CLI_JOB_TYPE_CHOICES),
        help="Optional: pin list view; also used for export validation when set",
    )
    _add_export_flags(p_res)
    p_res.set_defaults(func=cmd_result)

    p_exp = sub.add_parser("export", help="Export finished job result file only (no statistics/report)")
    add_client_flags(p_exp)
    p_exp.add_argument("--job-id", required=True)
    p_exp.add_argument(
        "--job-type",
        default=None,
        choices=list(CLI_JOB_TYPE_CHOICES),
        help="Required when job_type cannot be inferred from task list",
    )
    _add_export_flags(p_exp)
    p_exp.set_defaults(func=cmd_export)

    p_rep = sub.add_parser("report", help="Generate HTML summary (from API or JSON)")
    add_client_flags(p_rep)
    p_rep.add_argument("--job-id", help="PatSight job id (with live fetch)")
    p_rep.add_argument(
        "--job-type",
        default=None,
        choices=list(CLI_JOB_TYPE_CHOICES),
        help="Optional: same as result",
    )
    _add_export_flags(p_rep)
    p_rep.add_argument(
        "--from-json",
        metavar="PATH",
        help="Build report from saved `result` JSON (object or full CLI output)",
    )
    p_rep.add_argument("-o", "--output", help="Output HTML path (default: patsight_report.html)")
    p_rep.set_defaults(func=cmd_report)

    p_shared = sub.add_parser("shared-folder", help="Manage PatSight shared folders")
    shared_sub = p_shared.add_subparsers(dest="shared_folder_command", required=True)

    p_shared_list = shared_sub.add_parser("list", help="List accessible shared folders")
    add_client_flags(p_shared_list, client_name_flag="--client-name")
    p_shared_list.add_argument("--view", type=int, default=None, help="Optional environment view: 0=main, 1=IUPAC")
    p_shared_list.set_defaults(func=cmd_shared_folder_list)

    p_shared_create = shared_sub.add_parser("create", help="Create a shared folder or sub-folder")
    add_client_flags(p_shared_create, client_name_flag="--client-name")
    p_shared_create.add_argument("--name", required=True, help="Shared folder name")
    p_shared_create.add_argument("--parent-id", type=int, default=None, help="Optional parent folder id")
    p_shared_create.add_argument("--view", type=int, default=0, help="Environment view: 0=main, 1=IUPAC")
    p_shared_create.set_defaults(func=cmd_shared_folder_create)

    p_shared_rename = shared_sub.add_parser("rename", help="Rename a shared folder")
    add_client_flags(
        p_shared_rename,
        folder_id_required=True,
        folder_id_help="Shared folder id",
        client_name_flag="--client-name",
    )
    p_shared_rename.add_argument("--name", required=True, help="New shared folder name")
    p_shared_rename.set_defaults(func=cmd_shared_folder_rename)

    p_shared_delete = shared_sub.add_parser("delete", help="Delete a shared folder")
    add_client_flags(
        p_shared_delete,
        folder_id_required=True,
        folder_id_help="Shared folder id",
        client_name_flag="--client-name",
    )
    p_shared_delete.set_defaults(func=cmd_shared_folder_delete)

    p_members = shared_sub.add_parser("members", help="Manage top-level shared folder members")
    members_sub = p_members.add_subparsers(dest="shared_folder_members_command", required=True)

    p_members_list = members_sub.add_parser("list", help="List shared folder members")
    add_client_flags(
        p_members_list,
        folder_id_required=True,
        folder_id_help="Top-level shared folder id",
        client_name_flag="--client-name",
    )
    p_members_list.set_defaults(func=cmd_shared_folder_members_list)

    p_members_add = members_sub.add_parser("add", help="Add a member to a shared folder")
    add_client_flags(
        p_members_add,
        folder_id_required=True,
        folder_id_help="Top-level shared folder id",
        client_name_flag="--client-name",
    )
    p_members_add.add_argument("--email", required=True, help="Member email to add")
    p_members_add.add_argument(
        "--role",
        default="member",
        choices=["admin", "member", "0", "1"],
        help="Member role: admin/0 or member/1",
    )
    p_members_add.set_defaults(func=cmd_shared_folder_members_add)

    p_members_remove = members_sub.add_parser("remove", help="Remove a member from a shared folder")
    add_client_flags(
        p_members_remove,
        folder_id_required=True,
        folder_id_help="Top-level shared folder id",
        client_name_flag="--client-name",
    )
    p_members_remove.add_argument("--email", required=True, help="Member email to remove")
    p_members_remove.set_defaults(func=cmd_shared_folder_members_remove)

    p_members_role = members_sub.add_parser("role", help="Update a shared folder member role")
    add_client_flags(
        p_members_role,
        folder_id_required=True,
        folder_id_help="Top-level shared folder id",
        client_name_flag="--client-name",
    )
    p_members_role.add_argument("--email", required=True, help="Member email to update")
    p_members_role.add_argument(
        "--role",
        required=True,
        choices=["admin", "member", "0", "1"],
        help="New member role: admin/0 or member/1",
    )
    p_members_role.set_defaults(func=cmd_shared_folder_members_role)

    p_patents = shared_sub.add_parser("patents", help="Manage patents in a shared folder")
    patents_sub = p_patents.add_subparsers(dest="shared_folder_patents_command", required=True)

    p_patents_list = patents_sub.add_parser("list", help="List patents in a shared folder")
    add_client_flags(
        p_patents_list,
        folder_id_required=True,
        folder_id_help="Shared folder id",
        client_name_flag="--client-name",
    )
    p_patents_list.set_defaults(func=cmd_shared_folder_patents_list)

    p_patents_add = patents_sub.add_parser("add", help="Add patents to a shared folder")
    add_client_flags(
        p_patents_add,
        folder_id_required=True,
        folder_id_help="Shared folder id",
        client_name_flag="--client-name",
    )
    p_patents_add.add_argument("--task-id", type=int, nargs="+", required=True, help="Patent task id(s) to add")
    p_patents_add.set_defaults(func=cmd_shared_folder_patents_add)

    p_patents_remove = patents_sub.add_parser("remove", help="Remove patents from a shared folder")
    add_client_flags(
        p_patents_remove,
        folder_id_required=True,
        folder_id_help="Shared folder id",
        client_name_flag="--client-name",
    )
    p_patents_remove.add_argument("--task-id", type=int, nargs="+", required=True, help="Patent task id(s) to remove")
    p_patents_remove.set_defaults(func=cmd_shared_folder_patents_remove)

    p_patent = sub.add_parser("patent", help="Query accessible patents")
    patent_sub = p_patent.add_subparsers(dest="patent_command", required=True)

    p_patent_list = patent_sub.add_parser("list", help="List accessible patents")
    add_client_flags(p_patent_list, client_name_flag="--client-name")
    p_patent_list.add_argument("--page", type=int, default=None, help="Page number")
    p_patent_list.add_argument("--per-page", type=int, default=None, help="Items per page")
    p_patent_list.add_argument("--sort-by", default=None, help="Sort field")
    p_patent_list.add_argument("--sort-dir", default=None, choices=["asc", "desc"], help="Sort direction")
    p_patent_list.add_argument("--status", default=None, help="Patent task status")
    p_patent_list.add_argument("--is-collection", action="store_true", default=None, help="Filter collected patents")
    p_patent_list.add_argument("--name", default=None, help="Keyword filter")
    p_patent_list.add_argument("--name-field", default=None, help="Keyword field supported by backend")
    p_patent_list.add_argument("--searched-smiles", default=None, help="SMILES search filter")
    p_patent_list.add_argument("--view", type=int, default=None, help="Optional environment view")
    p_patent_list.add_argument("--exclude-action", default=None, help="Backend exclude_action filter")
    p_patent_list.add_argument(
        "--remark",
        default=None,
        help="Client-side filter: remark text contains this keyword",
    )
    p_patent_list.add_argument(
        "--creator-email",
        default=None,
        help="Client-side filter: patent owner email",
    )
    p_patent_list.add_argument(
        "--unfiled",
        action="store_true",
        help="Client-side filter: patents with no visible folders",
    )
    p_patent_list.add_argument(
        "--multi-folder",
        action="store_true",
        help="Client-side filter: patents visible in more than one folder",
    )
    p_patent_list.add_argument(
        "--fetch-all",
        action="store_true",
        help="Fetch all pages before applying client-side filters",
    )
    p_patent_list.set_defaults(func=cmd_patent_list)

    p_patent_detail = patent_sub.add_parser("detail", help="Get patent detail")
    add_client_flags(p_patent_detail, client_name_flag="--client-name")
    p_patent_detail.add_argument("--task-id", type=int, required=True, help="Patent task id")
    p_patent_detail.set_defaults(func=cmd_patent_detail)

    p_patent_editors = patent_sub.add_parser("editors", help="List patent editors and last operation time")
    add_client_flags(p_patent_editors, client_name_flag="--client-name")
    p_patent_editors.add_argument("--task-id", type=int, required=True, help="Patent task id")
    p_patent_editors.set_defaults(func=cmd_patent_editors)

    p_patent_export = patent_sub.add_parser("export", help="Export filtered patents as a local zip")
    add_client_flags(p_patent_export, client_name_flag="--client-name")
    p_patent_export.add_argument("--zip", action="store_true", help="Create a local zip archive")
    p_patent_export.add_argument("-o", "--output", default=None, help="Output zip path")
    p_patent_export.add_argument("--page", type=int, default=None, help="Page number")
    p_patent_export.add_argument("--per-page", type=int, default=None, help="Items per page")
    p_patent_export.add_argument("--sort-by", default=None, help="Sort field")
    p_patent_export.add_argument("--sort-dir", default=None, choices=["asc", "desc"], help="Sort direction")
    p_patent_export.add_argument("--status", default=None, help="Patent task status")
    p_patent_export.add_argument("--is-collection", action="store_true", default=None, help="Filter collected patents")
    p_patent_export.add_argument("--name", default=None, help="Keyword filter")
    p_patent_export.add_argument("--name-field", default=None, help="Keyword field supported by backend")
    p_patent_export.add_argument("--searched-smiles", default=None, help="SMILES search filter")
    p_patent_export.add_argument("--view", type=int, default=None, help="Optional environment view")
    p_patent_export.add_argument("--exclude-action", default=None, help="Backend exclude_action filter")
    p_patent_export.add_argument("--remark", default=None, help="Client-side filter: remark contains keyword")
    p_patent_export.add_argument("--creator-email", default=None, help="Client-side filter: patent owner email")
    p_patent_export.add_argument("--unfiled", action="store_true", help="Client-side filter: no folders")
    p_patent_export.add_argument("--multi-folder", action="store_true", help="Client-side filter: more than one folder")
    p_patent_export.add_argument("--fetch-all", action="store_true", help="Fetch all pages before export")
    p_patent_export.add_argument(
        "--no-editors",
        action="store_true",
        help="Do not call editors API when building zip metadata",
    )
    _add_export_flags(p_patent_export)
    p_patent_export.set_defaults(func=cmd_patent_export_zip)

    p_patent_remark = patent_sub.add_parser("remark", help="Set or clear patent remark")
    remark_sub = p_patent_remark.add_subparsers(dest="patent_remark_command", required=True)

    p_patent_remark_set = remark_sub.add_parser("set", help="Set or clear a patent remark")
    add_client_flags(p_patent_remark_set, client_name_flag="--client-name")
    p_patent_remark_set.add_argument("--task-id", type=int, required=True, help="Patent task id")
    p_patent_remark_set.add_argument(
        "--remark",
        default="",
        help="Remark text to save; empty or omitted clears the existing remark",
    )
    p_patent_remark_set.set_defaults(func=cmd_patent_remark_set)

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
    except ExportError as e:
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
