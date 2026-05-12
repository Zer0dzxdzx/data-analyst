"""Top-level CSV analysis workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_data_analyst.charts import generate_charts
from ai_data_analyst.config import AnalysisConfig
from ai_data_analyst.eda import build_eda_summary
from ai_data_analyst.exceptions import ConfigurationError
from ai_data_analyst.llm import generate_insights
from ai_data_analyst.loader import load_csv
from ai_data_analyst.report import write_reports, write_summary_json
from ai_data_analyst.schema import ColumnProfile, profile_dataframe


@dataclass(slots=True)
class AnalysisResult:
    csv_path: Path
    output_dir: Path
    profiles: list[ColumnProfile]
    eda_summary: dict[str, Any]
    charts: list[dict[str, Any]]
    insights: dict[str, Any]
    summary_path: Path
    report_paths: dict[str, Path]


def analyze_csv(path: str | Path, config: AnalysisConfig) -> AnalysisResult:
    """Analyze one CSV and write all configured artifacts."""

    normalized = config.normalized()
    csv_path = Path(path).expanduser().resolve()
    frame = load_csv(csv_path)

    if normalized.target_column and normalized.target_column not in frame.columns:
        raise ConfigurationError(f"Target column not found: {normalized.target_column}")

    normalized.output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = normalized.output_dir / "figures"

    profiles = profile_dataframe(frame)
    eda_summary = build_eda_summary(frame, profiles, normalized.max_categories)
    charts = generate_charts(frame, profiles, figures_dir, normalized.max_categories)
    insights = generate_insights(
        profiles=profiles,
        eda_summary=eda_summary,
        target_column=normalized.target_column,
        chart_meta=charts,
        use_llm=normalized.use_llm,
        timeout_seconds=normalized.request_timeout_seconds,
    )
    summary_path = write_summary_json(normalized.output_dir, profiles, eda_summary, charts, insights)
    report_paths = write_reports(
        output_dir=normalized.output_dir,
        source_name=csv_path.name,
        profiles=profiles,
        eda_summary=eda_summary,
        chart_meta=charts,
        insights=insights,
        report_format=normalized.report_format,
    )

    return AnalysisResult(
        csv_path=csv_path,
        output_dir=normalized.output_dir,
        profiles=profiles,
        eda_summary=eda_summary,
        charts=charts,
        insights=insights,
        summary_path=summary_path,
        report_paths=report_paths,
    )
