import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_data_analyst.cli import main
from ai_data_analyst.config import AnalysisConfig
from ai_data_analyst.exceptions import DataLoadError
from ai_data_analyst.loader import load_csv
from ai_data_analyst.workflow import analyze_csv

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sales_sample.csv"


class WorkflowCliTests(unittest.TestCase):
    def test_analyze_csv_writes_expected_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze_csv(
                SAMPLE,
                AnalysisConfig(output_dir=Path(tmpdir), target_column="revenue", use_llm=False),
            )

            self.assertTrue(result.summary_path.exists())
            self.assertTrue(result.report_paths["markdown"].exists())
            self.assertTrue(result.report_paths["html"].exists())
            self.assertGreaterEqual(len(result.charts), 3)

            payload = json.loads(result.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["eda"]["shape"]["rows"], 24)
            self.assertEqual(payload["insights"]["mode"], "fallback")

    def test_cli_analyze_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = main(["analyze", str(SAMPLE), "--out", tmpdir, "--target", "revenue"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((Path(tmpdir) / "report.md").exists())
            self.assertTrue((Path(tmpdir) / "summary.json").exists())

    def test_cli_defaults_offline_even_when_api_key_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"LLM_API_KEY": "test-key"}):
                with patch("ai_data_analyst.llm.httpx.post", side_effect=AssertionError("network called")):
                    exit_code = main(["analyze", str(SAMPLE), "--out", tmpdir, "--target", "revenue"])

            payload = json.loads((Path(tmpdir) / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["insights"]["mode"], "fallback")

    def test_wide_dataset_records_skipped_charts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "wide.csv"
            columns = [f"n{i}" for i in range(25)]
            rows = [",".join(columns)]
            for row_index in range(10):
                rows.append(",".join(str(row_index + offset) for offset in range(25)))
            csv_path.write_text("\n".join(rows), encoding="utf-8")

            result = analyze_csv(csv_path, AnalysisConfig(output_dir=Path(tmpdir) / "out"))

            skipped = [chart for chart in result.charts if not chart.get("rendered", True)]
            self.assertTrue(skipped)
            self.assertTrue(any(chart["kind"] == "correlation" for chart in skipped))

    def test_analyze_csv_rejects_row_limit_excess(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "rows.csv"
            csv_path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

            with self.assertRaises(DataLoadError):
                analyze_csv(csv_path, AnalysisConfig(output_dir=Path(tmpdir) / "out", max_rows=1))

    def test_analyze_csv_rejects_column_limit_excess(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "columns.csv"
            csv_path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

            with self.assertRaises(DataLoadError):
                analyze_csv(csv_path, AnalysisConfig(output_dir=Path(tmpdir) / "out", max_columns=2))

    def test_summary_json_is_strict_json_and_markdown_escapes_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "odd.csv"
            csv_path.write_text("bad|name,normal\n1,2\n3,4\n", encoding="utf-8")

            result = analyze_csv(csv_path, AnalysisConfig(output_dir=Path(tmpdir) / "out"))
            summary_text = result.summary_path.read_text(encoding="utf-8")
            markdown = result.report_paths["markdown"].read_text(encoding="utf-8")

            json.loads(summary_text)
            self.assertNotIn("Infinity", summary_text)
            self.assertIn(r"bad\|name", markdown)

    def test_load_csv_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            empty = Path(tmpdir) / "empty.csv"
            empty.write_text("", encoding="utf-8")

            with self.assertRaises(DataLoadError):
                load_csv(empty)

    def test_cli_rejects_missing_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = main(["analyze", str(SAMPLE), "--out", tmpdir, "--target", "does_not_exist"])

            self.assertEqual(exit_code, 2)

    def test_load_csv_detects_semicolon_delimiter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "semicolon.csv"
            csv_path.write_text("a;b\n1;2\n3;4\n", encoding="utf-8")

            frame = load_csv(csv_path)

            self.assertEqual(list(frame.columns), ["a", "b"])
            self.assertEqual(frame.shape, (2, 2))

    def test_load_csv_can_reject_before_reading_past_row_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "limited.csv"
            csv_path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

            with self.assertRaises(DataLoadError):
                load_csv(csv_path, max_rows=1)

    def test_load_csv_can_reject_column_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "limited_columns.csv"
            csv_path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

            with self.assertRaises(DataLoadError):
                load_csv(csv_path, max_columns=2)


if __name__ == "__main__":
    unittest.main()
