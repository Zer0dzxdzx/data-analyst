import unittest

import pandas as pd

from ai_data_analyst.schema import infer_column_type, profile_dataframe


class SchemaInferenceTests(unittest.TestCase):
    def test_infers_common_column_types(self):
        frame = pd.DataFrame(
            {
                "customer_id": [f"C{i}" for i in range(30)],
                "order_date": ["2025-01-01", "2025-01-02"] * 15,
                "revenue": [100.0 + i for i in range(30)],
                "region": ["North", "South", "East"] * 10,
                "returned": ["true", "false"] * 15,
                "note": [f"long text value {i}" for i in range(30)],
            }
        )

        profiles = {profile.name: profile.inferred_type for profile in profile_dataframe(frame)}

        self.assertEqual(profiles["customer_id"], "id")
        self.assertEqual(profiles["order_date"], "datetime")
        self.assertEqual(profiles["revenue"], "numeric")
        self.assertEqual(profiles["region"], "categorical")
        self.assertEqual(profiles["returned"], "boolean")
        self.assertEqual(profiles["note"], "text")

    def test_unknown_for_all_missing_column(self):
        series = pd.Series([None, None], name="empty")
        self.assertEqual(infer_column_type(series), "unknown")


if __name__ == "__main__":
    unittest.main()
