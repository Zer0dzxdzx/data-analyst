"""Markdown, HTML, and JSON report writers."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from ai_data_analyst.schema import ColumnProfile, profiles_to_dicts


def write_summary_json(
    output_dir: Path,
    profiles: list[ColumnProfile],
    eda_summary: dict[str, Any],
    chart_meta: list[dict[str, Any]],
    insights: dict[str, Any],
) -> Path:
    path = output_dir / "summary.json"
    payload = {
        "columns": profiles_to_dicts(profiles),
        "eda": eda_summary,
        "charts": _relative_chart_meta(output_dir, chart_meta),
        "insights": {
            key: value
            for key, value in insights.items()
            if key != "privacy_payload"
        },
        "privacy_payload_sent_to_llm": insights.get("privacy_payload"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_reports(
    output_dir: Path,
    source_name: str,
    profiles: list[ColumnProfile],
    eda_summary: dict[str, Any],
    chart_meta: list[dict[str, Any]],
    insights: dict[str, Any],
    report_format: str,
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    markdown = _build_markdown(source_name, profiles, eda_summary, chart_meta, insights, output_dir)
    if report_format in {"markdown", "both"}:
        path = output_dir / "report.md"
        path.write_text(markdown, encoding="utf-8")
        paths["markdown"] = path
    if report_format in {"html", "both"}:
        path = output_dir / "report.html"
        path.write_text(_build_html(source_name, markdown), encoding="utf-8")
        paths["html"] = path
    return paths


def _build_markdown(
    source_name: str,
    profiles: list[ColumnProfile],
    eda_summary: dict[str, Any],
    chart_meta: list[dict[str, Any]],
    insights: dict[str, Any],
    output_dir: Path,
) -> str:
    shape = eda_summary.get("shape", {})
    missing = eda_summary.get("missing", {})
    strong_pairs = eda_summary.get("correlation", {}).get("strong_pairs", [])
    lines = [
        f"# AI Data Analysis Report: {source_name}",
        "",
        "## Overview",
        "",
        f"- Rows: {shape.get('rows', 0)}",
        f"- Columns: {shape.get('columns', 0)}",
        f"- Columns with missing values: {missing.get('columns_with_missing', 0)}",
        f"- Insight mode: {insights.get('mode')}",
        "",
        "## Column Profiles",
        "",
        "| Column | Type | Pandas dtype | Missing rate | Unique count |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for profile in profiles:
        lines.append(
            f"| {profile.name} | {profile.inferred_type} | {profile.pandas_dtype} | "
            f"{profile.missing_rate:.2%} | {profile.unique_count} |"
        )

    lines.extend(["", "## Numeric Summary", ""])
    numeric = eda_summary.get("numeric", {})
    if numeric:
        lines.extend(
            [
                "| Column | Mean | Median | Min | Max | Std |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for column, values in numeric.items():
            lines.append(
                f"| {column} | {_fmt(values.get('mean'))} | {_fmt(values.get('median'))} | "
                f"{_fmt(values.get('min'))} | {_fmt(values.get('max'))} | {_fmt(values.get('std'))} |"
            )
    else:
        lines.append("No numeric columns detected.")

    lines.extend(["", "## Data Quality", ""])
    missing_by_column = missing.get("by_column", [])
    missing_with_values = [item for item in missing_by_column if item.get("missing_count", 0) > 0]
    if missing_with_values:
        lines.extend(["| Column | Missing count | Missing rate |", "| --- | ---: | ---: |"])
        for item in missing_with_values[:10]:
            lines.append(
                f"| {item['column']} | {item['missing_count']} | {float(item['missing_rate']):.2%} |"
            )
    else:
        lines.append("No missing values detected.")

    lines.extend(["", "## Correlation Signals", ""])
    if strong_pairs:
        for pair in strong_pairs[:10]:
            left, right = pair["columns"]
            lines.append(f"- {left} vs {right}: {pair['correlation']}")
    else:
        lines.append("No strong numeric correlations detected.")

    lines.extend(["", "## Visualizations", ""])
    if chart_meta:
        for item in _relative_chart_meta(output_dir, chart_meta):
            lines.append(f"![{item['title']}]({item['path']})")
            lines.append("")
    else:
        lines.append("No charts were generated for this dataset.")

    lines.extend(["", "## AI Insights", "", str(insights.get("content", "")).strip(), ""])
    lines.extend(
        [
            "## Privacy Note",
            "",
            "The LLM payload contains schema and aggregate statistics only. Raw rows are not sent.",
            "",
        ]
    )
    return "\n".join(lines)


def _build_html(source_name: str, markdown: str) -> str:
    body = _markdown_to_html(markdown)
    title = html.escape(f"AI Data Analysis Report: {source_name}")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 40px; color: #1f2933; }}
    main {{ max-width: 1080px; margin: 0 auto; }}
    h1, h2 {{ color: #102a43; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0 24px; font-size: 14px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px 10px; text-align: left; }}
    th {{ background: #f0f4f8; }}
    img {{ max-width: 100%; height: auto; margin: 12px 0 28px; border: 1px solid #d9e2ec; }}
    code {{ background: #f0f4f8; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    in_table = False
    next_table_row_is_header = False
    in_list = False
    for line in lines:
        if line.startswith("| ") and line.endswith(" |"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(set(cell.replace(" ", "")) <= {"-", ":"} for cell in cells):
                next_table_row_is_header = False
                continue
            if not in_table:
                html_lines.append("<table>")
                in_table = True
                next_table_row_is_header = True
            tag = "th" if next_table_row_is_header else "td"
            html_lines.append("<tr>" + "".join(f"<{tag}>{html.escape(cell)}</{tag}>" for cell in cells) + "</tr>")
            next_table_row_is_header = False
            continue
        if in_table:
            html_lines.append("</table>")
            in_table = False
            next_table_row_is_header = False

        if line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        if in_list:
            html_lines.append("</ul>")
            in_list = False

        if line.startswith("# "):
            html_lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("![") and "](" in line and line.endswith(")"):
            alt = line[2 : line.index("]")]
            src = line[line.index("(") + 1 : -1]
            html_lines.append(f'<img src="{html.escape(src)}" alt="{html.escape(alt)}">')
        elif line.strip():
            html_lines.append(f"<p>{html.escape(line)}</p>")
        else:
            html_lines.append("")

    if in_table:
        html_lines.append("</table>")
    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def _relative_chart_meta(output_dir: Path, chart_meta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relative = []
    for item in chart_meta:
        copied = dict(item)
        copied["path"] = str(Path(item["path"]).resolve().relative_to(output_dir.resolve()))
        relative.append(copied)
    return relative


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
