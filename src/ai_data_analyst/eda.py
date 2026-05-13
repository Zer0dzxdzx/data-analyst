"""Exploratory data analysis summaries."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ai_data_analyst.schema import ColumnProfile, coerce_numeric, profiles_by_name


def build_eda_summary(
    frame: pd.DataFrame,
    profiles: list[ColumnProfile],
    max_categories: int = 10,
    max_correlation_columns: int = 30,
) -> dict[str, Any]:
    """Build serializable EDA statistics for reporting."""

    profile_map = profiles_by_name(profiles)
    numeric_columns = [p.name for p in profiles if p.inferred_type == "numeric"]
    categorical_columns = [p.name for p in profiles if p.inferred_type in {"categorical", "boolean"}]
    datetime_columns = [p.name for p in profiles if p.inferred_type == "datetime"]

    summary: dict[str, Any] = {
        "shape": {"rows": int(frame.shape[0]), "columns": int(frame.shape[1])},
        "missing": _missing_summary(frame),
        "numeric": _numeric_summary(frame, numeric_columns),
        "categorical": _categorical_summary(frame, categorical_columns, max_categories),
        "datetime": _datetime_summary(frame, datetime_columns),
        "correlation": _correlation_summary(frame, numeric_columns, max_correlation_columns),
        "column_type_counts": _column_type_counts(profiles),
    }

    for column, profile in profile_map.items():
        if profile.inferred_type == "id":
            summary.setdefault("id_columns", []).append(column)
    return summary


def _missing_summary(frame: pd.DataFrame) -> dict[str, Any]:
    rows = len(frame)
    by_column = []
    for column in frame.columns:
        missing = int(frame[column].isna().sum())
        by_column.append(
            {
                "column": str(column),
                "missing_count": missing,
                "missing_rate": round(missing / max(rows, 1), 4),
            }
        )
    by_column.sort(key=lambda item: item["missing_rate"], reverse=True)
    return {
        "total_missing_cells": int(frame.isna().sum().sum()),
        "columns_with_missing": int(sum(1 for item in by_column if item["missing_count"] > 0)),
        "by_column": by_column,
    }


def _numeric_summary(frame: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    if not columns:
        return {}
    numeric_frame = frame[columns].apply(coerce_numeric).replace([np.inf, -np.inf], np.nan)
    described = numeric_frame.describe().transpose()
    result: dict[str, Any] = {}
    for column, row in described.iterrows():
        result[str(column)] = {
            "count": _safe_float(row.get("count")),
            "mean": _safe_float(row.get("mean")),
            "std": _safe_float(row.get("std")),
            "min": _safe_float(row.get("min")),
            "q25": _safe_float(row.get("25%")),
            "median": _safe_float(row.get("50%")),
            "q75": _safe_float(row.get("75%")),
            "max": _safe_float(row.get("max")),
        }
    return result


def _categorical_summary(
    frame: pd.DataFrame,
    columns: list[str],
    max_categories: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in columns:
        counts = frame[column].value_counts(dropna=True).head(max_categories)
        total = max(int(frame[column].notna().sum()), 1)
        result[str(column)] = [
            {
                "value": _json_value(value),
                "count": int(count),
                "rate": round(int(count) / total, 4),
            }
            for value, count in counts.items()
        ]
    return result


def _datetime_summary(frame: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in columns:
        parsed = pd.to_datetime(frame[column], errors="coerce", format="mixed")
        valid = parsed.dropna()
        if valid.empty:
            continue
        result[str(column)] = {
            "valid_count": int(valid.shape[0]),
            "min": valid.min().isoformat(),
            "max": valid.max().isoformat(),
        }
    return result


def _correlation_summary(frame: pd.DataFrame, columns: list[str], max_columns: int) -> dict[str, Any]:
    if len(columns) < 2:
        return {"matrix": {}, "strong_pairs": []}
    included_columns = columns[:max_columns]
    numeric_frame = frame[included_columns].apply(coerce_numeric).replace([np.inf, -np.inf], np.nan)
    corr = numeric_frame.corr(numeric_only=True)
    matrix = {
        str(index): {str(column): _safe_float(value) for column, value in row.items()}
        for index, row in corr.iterrows()
    }
    pairs = []
    for left_index, left in enumerate(corr.columns):
        for right in corr.columns[left_index + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value) and abs(float(value)) >= 0.5:
                pairs.append({"columns": [str(left), str(right)], "correlation": round(float(value), 4)})
    pairs.sort(key=lambda item: abs(item["correlation"]), reverse=True)
    return {
        "matrix": matrix,
        "strong_pairs": pairs,
        "truncated": len(columns) > len(included_columns),
        "total_numeric_columns": len(columns),
        "included_columns": [str(column) for column in included_columns],
    }


def _column_type_counts(profiles: list[ColumnProfile]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for profile in profiles:
        counts[profile.inferred_type] = counts.get(profile.inferred_type, 0) + 1
    return counts


def _safe_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    converted = float(value)
    if not math.isfinite(converted):
        return None
    return round(converted, 6)


def _json_value(value: Any) -> str | int | float | bool:
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)
