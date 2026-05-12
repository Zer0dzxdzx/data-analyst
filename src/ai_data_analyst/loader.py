"""CSV loading with practical encoding fallbacks."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ai_data_analyst.exceptions import DataLoadError

DEFAULT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "latin1")


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a CSV with common encoding fallbacks and validation."""

    csv_path = Path(path).expanduser()
    if not csv_path.exists():
        raise DataLoadError(f"CSV file does not exist: {csv_path}")
    if not csv_path.is_file():
        raise DataLoadError(f"CSV path is not a file: {csv_path}")
    if csv_path.stat().st_size == 0:
        raise DataLoadError(f"CSV file is empty: {csv_path}")

    errors: list[str] = []
    for encoding in DEFAULT_ENCODINGS:
        try:
            frame = pd.read_csv(csv_path, encoding=encoding, sep=None, engine="python")
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        except pd.errors.EmptyDataError as exc:
            raise DataLoadError(f"CSV has no columns: {csv_path}") from exc
        except pd.errors.ParserError as exc:
            raise DataLoadError(f"CSV parser error in {csv_path}: {exc}") from exc
        except OSError as exc:
            raise DataLoadError(f"Could not read CSV {csv_path}: {exc}") from exc

        if frame.columns.empty:
            raise DataLoadError(f"CSV has no columns: {csv_path}")
        if frame.empty:
            raise DataLoadError(f"CSV has columns but no data rows: {csv_path}")
        return frame

    joined = "; ".join(errors)
    raise DataLoadError(f"Could not decode CSV {csv_path}. Tried {DEFAULT_ENCODINGS}. {joined}")
