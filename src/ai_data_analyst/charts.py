"""Chart generation for analysis reports."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path.cwd() / ".cache" / "matplotlib"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from ai_data_analyst.schema import ColumnProfile


def generate_charts(
    frame: pd.DataFrame,
    profiles: list[ColumnProfile],
    figures_dir: Path,
    max_categories: int = 10,
) -> list[dict[str, Any]]:
    """Generate report charts and return their metadata."""

    figures_dir.mkdir(parents=True, exist_ok=True)
    chart_meta: list[dict[str, Any]] = []
    chart_meta.extend(_missing_chart(frame, figures_dir))
    chart_meta.extend(_numeric_histograms(frame, profiles, figures_dir))
    chart_meta.extend(_categorical_bars(frame, profiles, figures_dir, max_categories))
    chart_meta.extend(_correlation_heatmap(frame, profiles, figures_dir))
    chart_meta.extend(_time_trend(frame, profiles, figures_dir))
    return chart_meta


def _missing_chart(frame: pd.DataFrame, figures_dir: Path) -> list[dict[str, Any]]:
    missing_rates = frame.isna().mean().sort_values(ascending=False)
    if missing_rates.empty or float(missing_rates.max()) == 0:
        return []
    fig, ax = plt.subplots(figsize=(10, 5))
    missing_rates.plot(kind="bar", ax=ax, color="#4C78A8")
    ax.set_title("Missing Value Rate by Column")
    ax.set_ylabel("Missing rate")
    ax.set_ylim(0, 1)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    path = figures_dir / "missing_values.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return [{"kind": "missing", "title": "Missing Value Rate by Column", "path": str(path)}]


def _numeric_histograms(
    frame: pd.DataFrame,
    profiles: list[ColumnProfile],
    figures_dir: Path,
) -> list[dict[str, Any]]:
    charts = []
    for profile in profiles:
        if profile.inferred_type != "numeric":
            continue
        values = pd.to_numeric(frame[profile.name], errors="coerce").dropna()
        if values.empty:
            continue
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.hist(values, bins=min(30, max(5, int(values.nunique()))), color="#59A14F", edgecolor="white")
        ax.set_title(f"Distribution of {profile.name}")
        ax.set_xlabel(profile.name)
        ax.set_ylabel("Count")
        fig.tight_layout()
        filename = f"hist_{_safe_filename(profile.name)}.png"
        path = figures_dir / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        charts.append({"kind": "numeric_distribution", "title": f"Distribution of {profile.name}", "path": str(path)})
    return charts


def _categorical_bars(
    frame: pd.DataFrame,
    profiles: list[ColumnProfile],
    figures_dir: Path,
    max_categories: int,
) -> list[dict[str, Any]]:
    charts = []
    for profile in profiles:
        if profile.inferred_type not in {"categorical", "boolean"}:
            continue
        counts = frame[profile.name].value_counts(dropna=True).head(max_categories)
        if counts.empty:
            continue
        fig, ax = plt.subplots(figsize=(9, 5))
        counts.sort_values().plot(kind="barh", ax=ax, color="#F28E2B")
        ax.set_title(f"Top {len(counts)} Categories of {profile.name}")
        ax.set_xlabel("Count")
        fig.tight_layout()
        filename = f"bar_{_safe_filename(profile.name)}.png"
        path = figures_dir / filename
        fig.savefig(path, dpi=150)
        plt.close(fig)
        charts.append({"kind": "categorical_top", "title": f"Top Categories of {profile.name}", "path": str(path)})
    return charts


def _correlation_heatmap(
    frame: pd.DataFrame,
    profiles: list[ColumnProfile],
    figures_dir: Path,
) -> list[dict[str, Any]]:
    numeric_columns = [profile.name for profile in profiles if profile.inferred_type == "numeric"]
    if len(numeric_columns) < 2:
        return []
    corr = frame[numeric_columns].apply(pd.to_numeric, errors="coerce").corr(numeric_only=True)
    fig, ax = plt.subplots(figsize=(max(6, len(numeric_columns)), max(5, len(numeric_columns) * 0.75)))
    image = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_title("Numeric Correlation Heatmap")
    ax.set_xticks(range(len(corr.columns)), corr.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(corr.index)), corr.index)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    path = figures_dir / "correlation_heatmap.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return [{"kind": "correlation", "title": "Numeric Correlation Heatmap", "path": str(path)}]


def _time_trend(
    frame: pd.DataFrame,
    profiles: list[ColumnProfile],
    figures_dir: Path,
) -> list[dict[str, Any]]:
    datetime_columns = [profile.name for profile in profiles if profile.inferred_type == "datetime"]
    numeric_columns = [profile.name for profile in profiles if profile.inferred_type == "numeric"]
    if not datetime_columns or not numeric_columns:
        return []

    date_col = datetime_columns[0]
    numeric_col = numeric_columns[0]
    working = frame[[date_col, numeric_col]].copy()
    working[date_col] = pd.to_datetime(working[date_col], errors="coerce", format="mixed")
    working[numeric_col] = pd.to_numeric(working[numeric_col], errors="coerce")
    working = working.dropna().sort_values(date_col)
    if working.empty:
        return []
    grouped = working.set_index(date_col)[numeric_col].resample("ME").mean().dropna()
    if grouped.shape[0] < 2:
        return []
    fig, ax = plt.subplots(figsize=(10, 5))
    grouped.plot(ax=ax, color="#E15759", marker="o")
    ax.set_title(f"Monthly Average {numeric_col} by {date_col}")
    ax.set_xlabel(date_col)
    ax.set_ylabel(numeric_col)
    fig.tight_layout()
    path = figures_dir / f"trend_{_safe_filename(date_col)}_{_safe_filename(numeric_col)}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return [{"kind": "time_trend", "title": f"Monthly Average {numeric_col} by {date_col}", "path": str(path)}]


def _safe_filename(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in str(value))
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "column"
