import unittest
from pathlib import Path

from ai_data_analyst.web import create_app


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sales_sample.csv"


class WebAppTests(unittest.TestCase):
    def test_index_loads(self):
        app = create_app()
        client = app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI 数据分析助手", response.get_data(as_text=True))
        self.assertIn('name="csrf_token"', response.get_data(as_text=True))

    def test_analyze_upload_returns_result_page(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-1"

        with SAMPLE.open("rb") as handle:
            response = client.post(
                "/analyze",
                data={
                    "csrf_token": "token-1",
                    "csv_file": (handle, "sales_sample.csv"),
                    "target": "revenue",
                    "report_format": "markdown",
                    "max_categories": "5",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("分析结果", body)
        self.assertIn("结论", body)
        self.assertIn("/runs/", body)
        self.assertIn("summary.json", body)

    def test_analyze_pasted_csv_returns_result_page(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-2"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-2",
                "csv_text": "a,b\n1,2\n3,4\n",
                "target": "",
                "report_format": "html",
                "max_categories": "5",
            },
            headers={"Origin": "http://localhost"},
            content_type="multipart/form-data",
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("分析结果", body)
        self.assertIn("summary.json", body)

    def test_analyze_rejects_both_file_and_text(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-3"

        with SAMPLE.open("rb") as handle:
            response = client.post(
                "/analyze",
                data={
                    "csrf_token": "token-3",
                    "csv_file": (handle, "sales_sample.csv"),
                    "csv_text": "a,b\n1,2\n",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("either a CSV file or pasted CSV text", response.get_data(as_text=True))

    def test_analyze_rejects_bad_origin(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-4"

        with SAMPLE.open("rb") as handle:
            response = client.post(
                "/analyze",
                data={
                    "csrf_token": "token-4",
                    "csv_file": (handle, "sales_sample.csv"),
                },
                headers={"Origin": "http://evil.example"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request origin or CSRF token", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
