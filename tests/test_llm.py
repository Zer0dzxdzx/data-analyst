import os
import unittest

from ai_data_analyst.llm import build_privacy_payload, generate_insights
from ai_data_analyst.schema import ColumnProfile


class LlmFallbackTests(unittest.TestCase):
    def test_fallback_without_api_key_and_payload_omits_category_labels(self):
        previous = os.environ.pop("LLM_API_KEY", None)
        try:
            profiles = [
                ColumnProfile("region", "object", "categorical", 0, 0.0, 2, 0.5),
                ColumnProfile("revenue", "int64", "numeric", 0, 0.0, 4, 1.0),
            ]
            eda_summary = {
                "shape": {"rows": 4, "columns": 2},
                "missing": {"total_missing_cells": 0, "columns_with_missing": 0, "by_column": []},
                "numeric": {"revenue": {"mean": 20.0}},
                "categorical": {
                    "region": [
                        {"value": "SensitiveRegionA", "count": 3, "rate": 0.75},
                        {"value": "SensitiveRegionB", "count": 1, "rate": 0.25},
                    ]
                },
                "datetime": {},
                "correlation": {"strong_pairs": []},
            }

            insights = generate_insights(profiles, eda_summary, "revenue", [], use_llm=True)
            payload = insights["privacy_payload"]

            self.assertEqual(insights["mode"], "fallback")
            self.assertNotIn("SensitiveRegionA", str(payload))
            self.assertEqual(payload["categorical"]["region"]["top_bucket_counts"], [3, 1])
        finally:
            if previous is not None:
                os.environ["LLM_API_KEY"] = previous

    def test_privacy_payload_includes_chart_titles_only(self):
        profile = ColumnProfile("revenue", "int64", "numeric", 0, 0.0, 3, 1.0)
        payload = build_privacy_payload(
            [profile],
            {
                "shape": {"rows": 3, "columns": 1},
                "missing": {"by_column": [], "columns_with_missing": 0, "total_missing_cells": 0},
                "numeric": {},
                "categorical": {},
                "datetime": {},
                "correlation": {"strong_pairs": []},
            },
            None,
            [{"kind": "numeric_distribution", "title": "Distribution of revenue", "path": "/tmp/secret.png"}],
        )

        self.assertEqual(payload["charts"][0]["title"], "Distribution of revenue")
        self.assertNotIn("/tmp/secret.png", str(payload))


if __name__ == "__main__":
    unittest.main()
