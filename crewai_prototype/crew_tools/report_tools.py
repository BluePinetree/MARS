"""Report writing tool for CrewAI WriterAgent."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class _WriteReportInput(BaseModel):
    output_path: str = Field(description="Absolute path where the report file should be saved (e.g. /runs/abc/report.md)")
    content: str = Field(description="Full report content in Markdown format")
    format: Literal["markdown"] = Field(default="markdown", description="Report format (currently only 'markdown')")


class WriteReportTool(BaseTool):
    name: str = "WriteReportTool"
    description: str = (
        "Write the final research report to disk. "
        "Creates parent directories automatically. "
        "Content should be a complete Markdown document."
    )
    args_schema: Type[BaseModel] = _WriteReportInput

    def _run(self, output_path: str, content: str, format: str = "markdown") -> str:
        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            lines = content.count("\n") + 1
            return f"OK: report saved to {output_path} ({lines} lines)"
        except Exception as exc:
            return f"ERROR: {exc}"
