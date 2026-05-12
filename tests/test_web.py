import unittest
from io import BytesIO
from pathlib import Path
import re

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
        self.assertIn("分析结论", body)
        self.assertIn("报告下载", body)
        self.assertIn("图表预览", body)
        self.assertIn("/runs/", body)
        self.assertIn("summary.json", body)
        self.assertNotIn(str(ROOT), body)

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
        self.assertIn("分析结论", body)
        self.assertIn("报告下载", body)
        self.assertIn("summary.json", body)
        self.assertNotIn(str(ROOT), body)

    def test_artifacts_do_not_expose_raw_pasted_csv(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-artifact-1"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-artifact-1",
                "csv_text": "a,b\n1,2\n3,4\n",
                "report_format": "both",
                "max_categories": "5",
            },
            headers={"Origin": "http://localhost"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        run_id = self._extract_run_id(response.get_data(as_text=True))
        with client.get(f"/runs/{run_id}/summary.json") as artifact_response:
            self.assertEqual(artifact_response.status_code, 200)
        self.assertEqual(client.get(f"/runs/{run_id}/_inputs/pasted.csv").status_code, 404)
        self.assertEqual(client.get(f"/runs/{run_id}/pasted.csv").status_code, 404)

    def test_artifacts_do_not_expose_raw_uploaded_csv(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-artifact-2"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-artifact-2",
                "csv_file": (BytesIO(b"a,b\n1,2\n3,4\n"), "private_sales.csv"),
                "report_format": "html",
                "max_categories": "5",
            },
            headers={"Origin": "http://localhost"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        run_id = self._extract_run_id(response.get_data(as_text=True))
        with client.get(f"/runs/{run_id}/summary.json") as artifact_response:
            self.assertEqual(artifact_response.status_code, 200)
        self.assertEqual(client.get(f"/runs/{run_id}/_inputs/private_sales.csv").status_code, 404)
        self.assertEqual(client.get(f"/runs/{run_id}/private_sales.csv").status_code, 404)

    def test_analyze_rejects_missing_csrf_token(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-missing-csrf"

        response = client.post(
            "/analyze",
            data={
                "csv_text": "a,b\n1,2\n",
            },
            headers={"Origin": "http://localhost"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request origin or CSRF token", response.get_data(as_text=True))

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

    def test_analyze_rejects_origin_prefix_bypass(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-prefix-origin"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-prefix-origin",
                "csv_text": "a,b\n1,2\n",
            },
            headers={"Origin": "http://localhost.evil.example"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request origin or CSRF token", response.get_data(as_text=True))

    def test_analyze_rejects_bad_referer(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-5"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-5",
                "csv_text": "a,b\n1,2\n",
            },
            headers={"Referer": "http://evil.example/form"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request origin or CSRF token", response.get_data(as_text=True))

    def test_analyze_rejects_referer_prefix_bypass(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-prefix-referer"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-prefix-referer",
                "csv_text": "a,b\n1,2\n",
            },
            headers={"Referer": "http://localhost.evil.example/form"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request origin or CSRF token", response.get_data(as_text=True))

    def _extract_run_id(self, body: str) -> str:
        match = re.search(r"/runs/([0-9a-f]{12})/summary\.json", body)
        self.assertIsNotNone(match)
        return match.group(1)


if __name__ == "__main__":
    unittest.main()
