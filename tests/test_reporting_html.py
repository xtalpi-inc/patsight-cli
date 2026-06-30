"""验证 PatSight 离线 HTML 报告生成能力。"""

from __future__ import annotations

from pathlib import Path

from patsight_cli.reporting.html import generate_patsight_report


def test_generate_report_parses_summary_statistics(tmp_path: Path) -> None:
    """
    参数：(tmp_path: Path)
    返回值：None
    描述：验证接口统计摘要能被拆分为报告指标卡片。
    """
    output_file = tmp_path / "report.html"
    result = {
        "job_id": "job-001",
        "filename": "demo.pdf",
        "status": "done",
        "job_type": "structureAndActivity",
        "statistics_info": "structures_total=3 | named_structures=2(with_properties=1)",
        "csv_output_path": str(tmp_path / "job-001_sar_input.csv"),
        "pdf_pages": 8,
        "credit_used": 10,
        "site_address": "https://patent.xinsight-ai.com/patsight?fileId=job-001",
    }

    report_path = generate_patsight_report(result, str(output_file))
    html = Path(report_path).read_text(encoding="utf-8")

    assert Path(report_path) == output_file.resolve()
    assert "structures_total" in html
    assert "named_structures" in html
    assert "structureAndActivity job completed successfully" in html


def test_generate_report_escapes_user_supplied_content(tmp_path: Path) -> None:
    """
    参数：(tmp_path: Path)
    返回值：None
    描述：验证报告会转义任务字段，避免 HTML 注入。
    """
    output_file = tmp_path / "safe.html"
    result = {
        "job_id": "job-002",
        "filename": "<script>alert(1)</script>.pdf",
        "status": "failed",
        "job_type": "iupac",
        "title": "<b>unsafe</b>",
    }

    report_path = generate_patsight_report(result, str(output_file))
    html = Path(report_path).read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;.pdf" in html
    assert "&lt;b&gt;unsafe&lt;/b&gt;" in html
