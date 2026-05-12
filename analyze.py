#!/usr/bin/env python3
"""Simple launcher for the AI data analyst.

Run the bundled demo:
    python3 analyze.py

Analyze your own CSV:
    python3 analyze.py path/to/data.csv --target revenue
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simple CSV analysis launcher. Defaults to the bundled sales sample.",
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=str(PROJECT_ROOT / "examples" / "sales_sample.csv"),
        help="CSV file to analyze. Defaults to examples/sales_sample.csv.",
    )
    parser.add_argument("--out", help="Output directory. Defaults to reports/<csv-file-name>-<path-hash>.")
    parser.add_argument("--target", help="Optional target column for focused insights.")
    parser.add_argument("--llm", action="store_true", help="Enable LLM API calls. Offline mode is the default.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    csv_path = _resolve_csv_path(args.csv_path)
    output_dir = _resolve_output_dir(csv_path, args.out)

    cli_args = ["analyze", str(csv_path), "--out", str(output_dir)]
    if args.target:
        cli_args.extend(["--target", args.target])
    if args.llm:
        cli_args.append("--llm")

    try:
        from ai_data_analyst.cli import main as cli_main
    except ModuleNotFoundError as exc:
        missing = exc.name or "a dependency"
        print(
            f"Missing dependency: {missing}. Run `python3 -m pip install -e .` once, then retry.",
            file=sys.stderr,
        )
        return 2

    return cli_main(cli_args)


def _resolve_csv_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate.resolve()
    if candidate.is_absolute():
        return candidate
    project_relative = PROJECT_ROOT / candidate
    if project_relative.exists():
        return project_relative.resolve()
    return candidate


def _resolve_output_dir(csv_path: Path, out: str | None) -> Path:
    if out:
        return Path(out).expanduser()
    resolved = csv_path.resolve() if csv_path.exists() else csv_path
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
    return PROJECT_ROOT / "reports" / f"{csv_path.stem}-{digest}"


if __name__ == "__main__":
    raise SystemExit(main())
