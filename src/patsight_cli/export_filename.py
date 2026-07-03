"""导出文件本地命名：{file_name}-{export_type}.{format}。"""

from __future__ import annotations

from patsight_cli.exceptions import ExportError

ExportType = str
FileFormat = str


def export_filename(
    *,
    export_type: ExportType,
    file_format: FileFormat,
    file_name: str,
) -> str:
    """关键参数：(export_type: ExportType, file_format: FileFormat, file_name: str)
    返回值：str
    描述：按专利 file_name 与 export_type 生成本地导出文件名。
    """
    base = file_name.strip().replace("/", "_").replace("\\", "_")
    if not base:
        raise ExportError("file_name is required for export filename.")
    return f"{base}-{export_type}.{file_format}"
