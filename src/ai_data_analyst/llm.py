"""LLM insight generation with privacy-preserving payloads."""

from __future__ import annotations

import os
from typing import Any

import httpx

from ai_data_analyst.schema import ColumnProfile


def generate_insights(
    profiles: list[ColumnProfile],
    eda_summary: dict[str, Any],
    target_column: str | None,
    chart_meta: list[dict[str, Any]],
    use_llm: bool = True,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Generate analysis conclusions through an LLM or local fallback."""

    payload = build_privacy_payload(profiles, eda_summary, target_column, chart_meta)
    if not use_llm:
        return _fallback_insights(payload, reason="LLM disabled by --no-llm.")

    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        return _fallback_insights(payload, reason="LLM_API_KEY is not set.")

    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    endpoint = _chat_completions_endpoint(os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    prompt = _build_prompt(payload)

    try:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a senior data analyst. Use only the aggregate metadata provided. "
                            "Do not assume unseen raw rows. Respond in concise Chinese."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return {
            "mode": "llm",
            "model": model,
            "content": str(content).strip(),
            "privacy_payload": payload,
        }
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        return _fallback_insights(payload, reason=f"LLM request failed: {exc}")


def build_privacy_payload(
    profiles: list[ColumnProfile],
    eda_summary: dict[str, Any],
    target_column: str | None,
    chart_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a no-raw-rows payload for LLM prompting."""

    shape = eda_summary.get("shape", {})
    missing = eda_summary.get("missing", {})
    numeric = eda_summary.get("numeric", {})
    categorical = eda_summary.get("categorical", {})
    datetime = eda_summary.get("datetime", {})
    correlation = eda_summary.get("correlation", {})

    sanitized_categories = {
        column: {
            "top_bucket_counts": [item.get("count") for item in values],
            "top_bucket_rates": [item.get("rate") for item in values],
            "displayed_bucket_count": len(values),
        }
        for column, values in categorical.items()
    }

    return {
        "shape": shape,
        "target_column": target_column,
        "columns": [
            {
                "name": profile.name,
                "type": profile.inferred_type,
                "missing_rate": profile.missing_rate,
                "unique_count": profile.unique_count,
                "unique_rate": profile.unique_rate,
            }
            for profile in profiles
        ],
        "missing": {
            "total_missing_cells": missing.get("total_missing_cells", 0),
            "columns_with_missing": missing.get("columns_with_missing", 0),
            "highest_missing_columns": [
                {
                    "column": item.get("column"),
                    "missing_rate": item.get("missing_rate"),
                }
                for item in missing.get("by_column", [])[:5]
                if item.get("missing_count", 0) > 0
            ],
        },
        "numeric": numeric,
        "categorical": sanitized_categories,
        "datetime": datetime,
        "correlation": {
            "strong_pairs": correlation.get("strong_pairs", [])[:10],
        },
        "charts": [{"kind": item.get("kind"), "title": item.get("title")} for item in chart_meta],
        "privacy_note": "No raw rows or category labels are included in this payload.",
    }


def _fallback_insights(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    shape = payload.get("shape", {})
    columns = payload.get("columns", [])
    missing_columns = payload.get("missing", {}).get("highest_missing_columns", [])
    strong_pairs = payload.get("correlation", {}).get("strong_pairs", [])
    type_counts: dict[str, int] = {}
    for column in columns:
        column_type = str(column.get("type", "unknown"))
        type_counts[column_type] = type_counts.get(column_type, 0) + 1

    lines = [
        f"离线分析模式：{reason}",
        f"数据集包含 {shape.get('rows', 0)} 行、{shape.get('columns', 0)} 列。",
        f"字段类型分布：{type_counts}。",
    ]
    if missing_columns:
        formatted = ", ".join(f"{item['column']}({item['missing_rate']:.1%})" for item in missing_columns)
        lines.append(f"缺失值优先关注：{formatted}。")
    else:
        lines.append("未发现明显缺失值问题。")
    if strong_pairs:
        pair = strong_pairs[0]
        left, right = pair.get("columns", ["", ""])
        lines.append(f"最强相关字段对为 {left} 与 {right}，相关系数 {pair.get('correlation')}。")
    lines.append("建议结合业务口径复核目标列、异常值和高缺失字段，再进入建模或专项分析。")

    return {
        "mode": "fallback",
        "model": None,
        "content": "\n".join(lines),
        "reason": reason,
        "privacy_payload": payload,
    }


def _chat_completions_endpoint(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return f"{cleaned}/chat/completions"


def _build_prompt(payload: dict[str, Any]) -> str:
    return (
        "请基于以下 CSV 聚合画像输出数据分析结论，要求：\n"
        "1. 总结数据规模、字段结构和质量风险。\n"
        "2. 找出最值得关注的统计现象和相关关系。\n"
        "3. 如果给定目标列，说明可能影响目标列的分析方向。\n"
        "4. 给出 3-5 条下一步分析建议。\n"
        "5. 不要编造原始数据中没有出现的信息。\n\n"
        f"聚合画像：{payload}"
    )
