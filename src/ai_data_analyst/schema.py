"""Column profiling and field type inference."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd
from pandas.api import types as pdt


@dataclass(slots=True)
class ColumnProfile:
    name: str
    pandas_dtype: str
    inferred_type: str
    missing_count: int
    missing_rate: float
    unique_count: int
    unique_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_column_type(series: pd.Series) -> str:
    """Infer a pragmatic analytics type for one column."""

    non_null = series.dropna()
    if non_null.empty:
        return "unknown"

    name = str(series.name or "").lower()
    unique_count = int(non_null.nunique(dropna=True))
    unique_rate = unique_count / max(len(non_null), 1)

    if _is_boolean_like(non_null):
        return "boolean"
    if _is_datetime_like(non_null):
        return "datetime"
    if _is_id_like(name, non_null, unique_rate):
        return "id"
    if pdt.is_numeric_dtype(non_null):
        return "numeric"
    if _can_parse_numeric(non_null) and unique_rate > 0.2:
        return "numeric"
    if unique_count <= min(30, max(2, int(len(non_null) * 0.5))):
        return "categorical"
    return "text"


def profile_dataframe(frame: pd.DataFrame) -> list[ColumnProfile]:
    row_count = len(frame)
    profiles: list[ColumnProfile] = []
    for column in frame.columns:
        series = frame[column]
        missing_count = int(series.isna().sum())
        unique_count = int(series.nunique(dropna=True))
        profiles.append(
            ColumnProfile(
                name=str(column),
                pandas_dtype=str(series.dtype),
                inferred_type=infer_column_type(series),
                missing_count=missing_count,
                missing_rate=round(missing_count / max(row_count, 1), 4),
                unique_count=unique_count,
                unique_rate=round(unique_count / max(row_count, 1), 4),
            )
        )
    return profiles


def profiles_to_dicts(profiles: list[ColumnProfile]) -> list[dict[str, Any]]:
    return [profile.to_dict() for profile in profiles]


def profiles_by_name(profiles: list[ColumnProfile]) -> dict[str, ColumnProfile]:
    return {profile.name: profile for profile in profiles}


def coerce_numeric(series: pd.Series) -> pd.Series:
    """Convert common numeric text formats without mutating the source series."""

    if pdt.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = (
        series.astype("string")
        .str.strip()
        .str.replace(r"[$¥€£]", "", regex=True)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _is_boolean_like(series: pd.Series) -> bool:
    if pdt.is_bool_dtype(series):
        return True
    values = {str(value).strip().lower() for value in series.unique()}
    if len(values) > 2:
        return False
    bool_values = {"true", "false", "yes", "no", "y", "n", "1", "0"}
    return bool(values) and values.issubset(bool_values)


def _is_datetime_like(series: pd.Series) -> bool:
    if pdt.is_datetime64_any_dtype(series):
        return True
    if pdt.is_numeric_dtype(series):
        return False
    sample = series.astype("string").dropna().head(100)
    if sample.empty:
        return False
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return float(parsed.notna().mean()) >= 0.8


def _is_id_like(name: str, series: pd.Series, unique_rate: float) -> bool:
    id_name = name == "id" or name.endswith("_id") or name.endswith("id") or "identifier" in name
    if id_name and unique_rate >= 0.8:
        return True
    if unique_rate >= 0.95 and len(series) >= 20 and not pdt.is_float_dtype(series) and _looks_like_identifier(series):
        return True
    return False


def _can_parse_numeric(series: pd.Series) -> bool:
    if pdt.is_numeric_dtype(series):
        return True
    parsed = coerce_numeric(series)
    return float(parsed.notna().mean()) >= 0.9


def _looks_like_identifier(series: pd.Series) -> bool:
    sample = series.astype("string").dropna().head(50)
    if sample.empty:
        return False
    compact_rate = sample.str.contains(r"\s", regex=True).map(lambda value: not bool(value)).mean()
    avg_length = sample.str.len().mean()
    return float(compact_rate) >= 0.95 and float(avg_length) <= 32
