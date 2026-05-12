"""Configuration objects for the analysis workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AnalysisConfig:
    """Runtime options for analyzing one CSV file."""

    output_dir: Path
    target_column: str | None = None
    max_categories: int = 10
    use_llm: bool = True
    report_format: str = "both"
    request_timeout_seconds: float = 30.0

    def normalized(self) -> "AnalysisConfig":
        output_dir = Path(self.output_dir).expanduser().resolve()
        report_format = self.report_format.lower().strip()
        if report_format not in {"markdown", "html", "both"}:
            msg = "report_format must be one of: markdown, html, both"
            raise ValueError(msg)
        if self.max_categories < 1:
            msg = "max_categories must be at least 1"
            raise ValueError(msg)
        return AnalysisConfig(
            output_dir=output_dir,
            target_column=self.target_column,
            max_categories=self.max_categories,
            use_llm=self.use_llm,
            report_format=report_format,
            request_timeout_seconds=self.request_timeout_seconds,
        )
