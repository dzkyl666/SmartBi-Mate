"""Tool for saving reports to files."""

import datetime
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from smartbi_mate import config
from smartbi_mate.utils import log


class SaveReportInput(BaseModel):
    content: str = Field(description="The content of the report to save")
    title: str = Field(description="The title of the report (will be used in filename)")
    file_format: str = Field(
        description="The file format/extension, only support 'md', 'csv', 'txt', 'json', 'html', 'xml'"
    )


@tool("save_report", args_schema=SaveReportInput, return_direct=False, infer_schema=True)
def save_report(content: str, title: str, file_format: str = "md") -> str:
    """把分析结果保存成一份可下载的报告文件。

    当用户提出「分析/总结/出报告/整理成文档」类需求，或要把一次查询结论
    保存下来供后续查看时，调用此工具。content 用 Markdown 组织，包含结论、
    关键数据、SQL 结果摘要。保存后返回下载链接。

    Args:
        content: 要保存的报告正文（建议 Markdown 格式）
        title: 报告标题（会用于文件名，请用中文简短标题）
        file_format: 文件格式，只支持 'md', 'csv', 'txt', 'json', 'html', 'xml'

    Returns:
        str: 成功消息（含下载链接）或错误消息
    """
    allowed_formats = {"md", "csv", "txt", "json", "html", "xml"}
    if file_format not in allowed_formats:
        raise ValueError(f"Unsupported file format: {file_format}")

    try:
        # Get report directory from config
        report_dir = config.get().report_directory

        # Create directory if it doesn't exist
        Path(report_dir).mkdir(parents=True, exist_ok=True)

        # Generate timestamp for filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Clean title for filename (remove invalid characters)
        clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "-")).rstrip()
        clean_title = clean_title.replace(" ", "_")

        # Create filename
        filename = f"{timestamp}_{clean_title}.{file_format}"
        file_path = Path(report_dir) / filename

        # Write content to file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        log(f"Report saved: {file_path}")

        # Return success message with download link
        download_url = f"/api/download/report/{filename}"
        return f"Report saved successfully! Download link: {download_url}"

    except Exception as e:
        error_msg = f"Failed to save report: {str(e)}"
        log(error_msg)
        return error_msg
