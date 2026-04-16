"""HTML summary report from a PatSight `result` dict (e.g. `JobResult.result`)."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any, Dict


def generate_patsight_report(result: Dict[str, Any], output_file: str = "patsight_report.html") -> str:
    """
    Build a simple HTML report from task result fields.

    Expected keys include: job_id, filename, status, job_type, csv_output_path,
    statistics_info, pdf_pages, title, abstract, handle, credit_used, site_address.
    """

    def safe(value: Any) -> str:
        if value is None:
            return ""
        return escape(str(value))

    def status_meta(status_text: str) -> tuple[str, str, str]:
        s = (status_text or "").lower().strip()
        if s in {"done", "success", "completed"}:
            return "Completed", "success", "Job finished successfully; results are available."
        if s in {"running", "processing"}:
            return "Running", "running", "Job is still in progress."
        if s in {"queued", "queueing", "pending"}:
            return "Queued", "queued", "Job is queued and waiting to run."
        if s in {"failed", "error"}:
            return "Failed", "failed", "Job failed; see raw response details."
        return safe(status_text), "default", "Status could not be classified."

    def parse_statistics(statistics_info: Any) -> list[tuple[str, str]]:
        text = str(statistics_info or "").strip()
        if not text:
            return []
        pairs: list[tuple[str, str]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip().strip("•").strip("-").strip()
            if not line:
                continue
            m = re.match(r"^([^:：]+)\s*[:：]\s*(.+)$", line)
            if m:
                pairs.append((m.group(1).strip(), m.group(2).strip()))
            else:
                pairs.append((line, ""))
        return pairs

    def infer_summary(result_dict: Dict[str, Any], stat_pairs: list[tuple[str, str]], status_label: str) -> str:
        filename = result_dict.get("filename", "") or "this file"
        job_type = result_dict.get("job_type", "") or "PatSight job"
        title = result_dict.get("title", "") or ""
        if status_label == "Completed":
            important_stats = []
            for k, v in stat_pairs[:3]:
                if v:
                    important_stats.append(f"{k}: {v}")
            stat_text = "; ".join(important_stats)
            if stat_text:
                return (
                    f"The {job_type} job completed successfully for {filename}. "
                    f"Key statistics: {stat_text}. Outputs are ready for downstream use."
                )
            return (
                f"The {job_type} job completed successfully for {filename}. "
                "Result data is available for further analysis."
            )
        if status_label == "Running":
            return (
                f"The {job_type} job is still running ({filename}). "
                "Check back for statistics and result files when it finishes."
            )
        if status_label == "Queued":
            return (
                f"The {job_type} job is queued ({filename}) and will start when resources are available."
            )
        if status_label == "Failed":
            if title:
                return (
                    f"The {job_type} job failed; related title: {title}. "
                    "Review the raw API response and job parameters."
                )
            return (
                f"The {job_type} job failed. Check inputs, parameters, and the raw response."
            )
        return f"The {job_type} job status is {status_label} ({filename})."

    job_id = safe(result.get("job_id", ""))
    filename = safe(result.get("filename", ""))
    status_raw = str(result.get("status", "") or "")
    job_type = safe(result.get("job_type", ""))
    csv_output_path = safe(result.get("csv_output_path", ""))
    pdf_pages = safe(result.get("pdf_pages", 0))
    credit_used = safe(result.get("credit_used", 0))
    site_address_raw = str(result.get("site_address", "") or "").strip()
    site_address = safe(site_address_raw)

    status_label, _, _ = status_meta(status_raw)
    stat_pairs = parse_statistics(result.get("statistics_info", ""))
    summary_text = infer_summary(result, stat_pairs, status_label)
    summary_text_html = safe(summary_text)

    stat_cards_html = ""
    if stat_pairs:
        stat_cards = []
        for key, value in stat_pairs[:4]:
            if value:
                stat_cards.append(
                    f"""
                    <div class="metric-card">
                      <div class="metric-label">{escape(key)}</div>
                      <div class="metric-value">{escape(value)}</div>
                    </div>
                    """
                )
        stat_cards_html = "\n".join(stat_cards)

    if stat_pairs:
        full_stats_items = []
        for key, value in stat_pairs:
            if value:
                full_stats_items.append(
                    f"""
                    <div class="detail-row">
                      <div class="detail-key">{escape(key)}</div>
                      <div class="detail-value">{escape(value)}</div>
                    </div>
                    """
                )
            else:
                full_stats_items.append(
                    f"""
                    <div class="detail-row">
                      <div class="detail-key">{escape(key)}</div>
                      <div class="detail-value muted">—</div>
                    </div>
                    """
                )
        full_stats_html = "\n".join(full_stats_items)
    else:
        full_stats_html = '<div class="empty-block">No statistics provided</div>'

    csv_html = csv_output_path if csv_output_path else '<span class="muted">Not generated</span>'
    link_html = (
        f'<a href="{site_address}" target="_blank" rel="noopener noreferrer" class="link-online">View in PatSight →</a>'
        if site_address_raw
        else '<span class="muted">Not available</span>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PatSight task report</title>
<style>
body {{
  margin:0;
  background:#f5f7fb;
  font-family:"Segoe UI",system-ui,sans-serif;
}}
.container {{
  max-width:960px;
  margin:40px auto;
  background:#fff;
  border-radius:18px;
  box-shadow:0 10px 30px rgba(0,0,0,0.08);
  overflow:hidden;
}}
.header {{
  background:linear-gradient(135deg,#1e293b 0%,#2563eb 100%);
  color:#fff;
  padding:28px 32px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:20px;
}}
.header .logo {{ height:40px; width:auto; object-fit:contain; flex-shrink:0; }}
.header .title {{ flex:1; text-align:center; min-width:0; }}
.header .title h1 {{ margin:0; font-size:22px; font-weight:600; }}
.content {{ padding:28px 32px; }}
.status {{ font-size:14px; margin-bottom:18px; color:#374151; }}
.status strong {{ color:#16a34a; }}
.metrics {{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:12px;
  margin-bottom:26px;
}}
.metric-card {{
  background:#f9fafb;
  border:1px solid #e5e7eb;
  border-radius:12px;
  padding:16px;
  text-align:center;
}}
.metric-label {{ font-size:12px; color:#6b7280; }}
.metric-value {{ font-size:18px; font-weight:700; color:#111827; margin-top:6px; }}
.section {{ margin-bottom:22px; }}
.section h2 {{ font-size:15px; margin-bottom:10px; color:#111827; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.card {{
  border:1px solid #e5e7eb;
  border-radius:12px;
  padding:12px;
  background:#fafafa;
}}
.label {{ font-size:12px; color:#6b7280; }}
.value {{ font-size:14px; margin-top:4px; word-break:break-all; color:#111827; }}
.detail-row {{ display:flex; gap:12px; padding:8px 0; border-bottom:1px solid #eee; }}
.detail-key {{ flex:0 0 140px; color:#6b7280; font-size:13px; }}
.detail-value {{ flex:1; font-size:14px; color:#111827; }}
.muted {{ color:#9ca3af; }}
.footer {{
  border-top:1px solid #eee;
  padding-top:16px;
  margin-top:20px;
  text-align:right;
  font-size:12px;
  color:#9ca3af;
}}
a {{ color:#2563eb; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.summary {{
  background:#f0f9ff;
  border:1px solid #bae6fd;
  border-radius:12px;
  padding:14px 16px;
  margin-bottom:22px;
  font-size:14px;
  color:#0c4a6e;
  line-height:1.5;
}}
</style>
</head>
<body>
<div class="container">
<header class="header">
  <img class="logo" src="https://patent.xinsight-ai.com/assets/logo-x-DP4Toyt5.png" alt="XtalPi">
  <div class="title"><h1>PatSight task report</h1></div>
  <img class="logo" src="https://patent.xinsight-ai.com/assets/logo-4-DizspTVJ.png" alt="PatSight">
</header>
<div class="content">
<div class="status">Status: <strong>{status_label}</strong> — {filename}</div>
<div class="summary">{summary_text_html}</div>
<div class="metrics">{stat_cards_html}</div>
<div class="section"><h2>Statistics</h2>{full_stats_html}</div>
<div class="section">
<h2>Task details</h2>
<div class="grid">
  <div class="card"><div class="label">Job ID</div><div class="value">{job_id}</div></div>
  <div class="card"><div class="label">Job type</div><div class="value">{job_type}</div></div>
  <div class="card"><div class="label">PDF pages</div><div class="value">{pdf_pages}</div></div>
  <div class="card"><div class="label">Credits used</div><div class="value">{credit_used}</div></div>
</div>
</div>
<div class="section">
<h2>Outputs</h2>
<div class="grid">
  <div class="card"><div class="label">Result file (local path)</div><div class="value">{csv_html}</div></div>
  <div class="card"><div class="label">View online</div><div class="value">{link_html}</div></div>
</div>
</div>
<div class="footer">patsight-cli · PatSight task summary</div>
</div>
</div>
</body>
</html>
"""

    output_path = Path(output_file).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return str(output_path)
