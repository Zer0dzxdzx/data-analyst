import unittest

import pandas as pd

from ai_data_analyst.eda import build_eda_summary
from ai_data_analyst.schema import profile_dataframe


class EdaSummaryTests(unittest.TestCase):
    def test_missing_numeric_and_correlation_summary(self):
        frame = pd.DataFrame(
            {
                "x": [1, 2, 3, 4],
                "y": [2, 4, 6, 8],
                "category": ["A", "A", "B", None],
            }
        )
        profiles = profile_dataframe(frame)
        summary = build_eda_summary(frame, profiles, max_categories=3)

        self.assertEqual(summary["shape"], {"rows": 4, "columns": 3})
        self.assertEqual(summary["missing"]["columns_with_missing"], 1)
        self.assertAlmostEqual(summary["numeric"]["x"]["mean"], 2.5)
        self.assertEqual(summary["categorical"]["category"][0]["value"], "A")
        self.assertEqual(summary["correlation"]["strong_pairs"][0]["columns"], ["x", "y"])
        self.assertEqual(summary["correlation"]["strong_pairs"][0]["correlation"], 1.0)

    def test_non_finite_values_are_json_safe(self):
        frame = pd.DataFrame({"value": [1.0, float("inf"), float("-inf")]})
        profiles = profile_dataframe(frame)
        summary = build_eda_summary(frame, profiles)

        self.assertEqual(summary["numeric"]["value"]["mean"], 1.0)
        self.assertEqual(summary["numeric"]["value"]["max"], 1.0)

    def test_all_non_finite_numeric_column_has_null_statistics(self):
        frame = pd.DataFrame({"value": [float("inf"), float("-inf")]})
        profiles = profile_dataframe(frame)
        summary = build_eda_summary(frame, profiles)

        self.assertEqual(
            summary["numeric"]["value"],
            {
                "count": 0.0,
                "mean": None,
                "std": None,
                "min": None,
                "q25": None,
                "median": None,
                "q75": None,
                "max": None,
            },
        )

    def test_empty_dataframe_with_columns_produces_stable_summary(self):
        frame = pd.DataFrame({"empty_numeric": pd.Series(dtype="float64"), "empty_text": pd.Series(dtype="object")})
        profiles = profile_dataframe(frame)
        summary = build_eda_summary(frame, profiles)

        self.assertEqual(summary["shape"], {"rows": 0, "columns": 2})
        self.assertEqual(summary["missing"]["total_missing_cells"], 0)
        self.assertEqual(summary["numeric"], {})
        self.assertEqual(summary["categorical"], {})
        self.assertEqual(summary["correlation"], {"matrix": {}, "strong_pairs": []})


if __name__ == "__main__":
    unittest.main()
