import json
import tempfile
import unittest
from pathlib import Path

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
            exit_code = main(["analyze", str(SAMPLE), "--out", tmpdir, "--target", "revenue", "--no-llm"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((Path(tmpdir) / "report.md").exists())
            self.assertTrue((Path(tmpdir) / "summary.json").exists())

    def test_load_csv_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            empty = Path(tmpdir) / "empty.csv"
            empty.write_text("", encoding="utf-8")

            with self.assertRaises(DataLoadError):
                load_csv(empty)

    def test_cli_rejects_missing_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = main(["analyze", str(SAMPLE), "--out", tmpdir, "--target", "does_not_exist", "--no-llm"])

            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
