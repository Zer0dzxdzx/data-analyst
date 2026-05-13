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
    use_llm: bool = False
    report_format: str = "both"
    request_timeout_seconds: float = 30.0
    min_llm_group_size: int = 5
    max_numeric_charts: int = 12
    max_categorical_charts: int = 12
    max_heatmap_columns: int = 20
    max_rows: int | None = None
    max_columns: int | None = None
    max_correlation_columns: int = 30

    def normalized(self) -> AnalysisConfig:
        output_dir = Path(self.output_dir).expanduser().resolve()
        report_format = self.report_format.lower().strip()
        if report_format not in {"markdown", "html", "both"}:
            msg = "report_format must be one of: markdown, html, both"
            raise ValueError(msg)
        if self.max_categories < 1:
            msg = "max_categories must be at least 1"
            raise ValueError(msg)
        if self.min_llm_group_size < 2:
            msg = "min_llm_group_size must be at least 2"
            raise ValueError(msg)
        if min(self.max_numeric_charts, self.max_categorical_charts, self.max_heatmap_columns) < 1:
            msg = "chart limits must be at least 1"
            raise ValueError(msg)
        if self.max_rows is not None and self.max_rows < 1:
            msg = "max_rows must be at least 1"
            raise ValueError(msg)
        if self.max_columns is not None and self.max_columns < 1:
            msg = "max_columns must be at least 1"
            raise ValueError(msg)
        if self.max_correlation_columns < 2:
            msg = "max_correlation_columns must be at least 2"
            raise ValueError(msg)
        return AnalysisConfig(
            output_dir=output_dir,
            target_column=self.target_column,
            max_categories=self.max_categories,
            use_llm=self.use_llm,
            report_format=report_format,
            request_timeout_seconds=self.request_timeout_seconds,
            min_llm_group_size=self.min_llm_group_size,
            max_numeric_charts=self.max_numeric_charts,
            max_categorical_charts=self.max_categorical_charts,
            max_heatmap_columns=self.max_heatmap_columns,
            max_rows=self.max_rows,
            max_columns=self.max_columns,
            max_correlation_columns=self.max_correlation_columns,
        )
