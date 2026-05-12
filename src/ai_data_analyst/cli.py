"""Command line interface for the AI data analyst."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_data_analyst.config import AnalysisConfig
from ai_data_analyst.exceptions import AnalysisError
from ai_data_analyst.workflow import analyze_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-data-analyst", description="Analyze CSV files with EDA and LLM insights.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze a CSV file and generate report artifacts.")
    analyze.add_argument("csv_path", help="Path to the CSV file to analyze.")
    analyze.add_argument("--out", required=True, help="Output directory for report artifacts.")
    analyze.add_argument("--target", help="Optional target column for focused insights.")
    analyze.add_argument("--max-categories", type=int, default=10, help="Maximum top categories to display per column.")
    llm_group = analyze.add_mutually_exclusive_group()
    llm_group.add_argument("--llm", action="store_true", help="Enable OpenAI-compatible LLM API calls.")
    llm_group.add_argument("--no-llm", action="store_true", help="Keep offline template insights. This is the default.")
    analyze.add_argument(
        "--format",
        choices=("markdown", "html", "both"),
        default="both",
        help="Report format to write.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        config = AnalysisConfig(
            output_dir=Path(args.out),
            target_column=args.target,
            max_categories=args.max_categories,
            use_llm=args.llm,
            report_format=args.format,
        )
        try:
            result = analyze_csv(args.csv_path, config)
        except (AnalysisError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

        print(f"Analysis complete: {result.output_dir}")
        print(f"Summary JSON: {result.summary_path}")
        for label, path in result.report_paths.items():
            print(f"{label.title()} report: {path}")
        rendered_charts = sum(1 for chart in result.charts if chart.get("rendered", True))
        print(f"Charts generated: {rendered_charts}")
        return 0

    parser.print_help()
    return 1
