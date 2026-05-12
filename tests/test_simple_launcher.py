import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("simple_launcher", ROOT / "analyze.py")
launcher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(launcher)


class SimpleLauncherTests(unittest.TestCase):
    def test_resolves_project_relative_sample_when_called_elsewhere(self):
        path = launcher._resolve_csv_path("examples/sales_sample.csv")

        self.assertEqual(path, ROOT / "examples" / "sales_sample.csv")

    def test_default_output_dir_is_collision_resistant(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_csv = Path(first) / "sales.csv"
            second_csv = Path(second) / "sales.csv"
            first_csv.write_text("a\n1\n", encoding="utf-8")
            second_csv.write_text("a\n2\n", encoding="utf-8")

            first_out = launcher._resolve_output_dir(first_csv, None)
            second_out = launcher._resolve_output_dir(second_csv, None)

            self.assertNotEqual(first_out, second_out)
            self.assertTrue(first_out.name.startswith("sales-"))
            self.assertTrue(second_out.name.startswith("sales-"))

    def test_explicit_output_dir_is_preserved(self):
        self.assertEqual(launcher._resolve_output_dir(Path("data.csv"), "reports/custom"), Path("reports/custom"))


if __name__ == "__main__":
    unittest.main()
