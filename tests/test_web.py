import os
import re
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_data_analyst.web import create_app, web_max_categories

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
        self.assertIn('name="max_categories" type="number" min="1" max="50"', response.get_data(as_text=True))

    def test_healthz_returns_ok(self):
        app = create_app()
        client = app.test_client()

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_upload_limit_uses_environment_and_returns_friendly_error(self):
        with patch.dict(os.environ, {"AI_ANALYST_MAX_UPLOAD_MB": "1"}):
            app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-large-upload"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-large-upload",
                "csv_file": (BytesIO(b"a" * (1024 * 1024 + 1)), "too_large.csv"),
            },
            headers={"Origin": "http://localhost"},
            content_type="multipart/form-data",
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 413)
        self.assertIn("CSV 文件过大", body)
        self.assertIn("最大 1MB", body)

    def test_index_cleans_expired_run_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            old_run = reports_dir / "012345abcdef"
            fresh_run = reports_dir / "abcdef012345"
            old_run.mkdir()
            fresh_run.mkdir()
            expired_time = time.time() - (25 * 60 * 60)
            os.utime(old_run, (expired_time, expired_time))

            with patch.dict(
                os.environ,
                {
                    "AI_ANALYST_WEB_REPORTS_DIR": str(reports_dir),
                    "AI_ANALYST_RETENTION_HOURS": "24",
                },
            ):
                app = create_app()
            client = app.test_client()

            response = client.get("/")

            self.assertEqual(response.status_code, 200)
            self.assertFalse(old_run.exists())
            self.assertTrue(fresh_run.exists())

    def test_cleanup_only_removes_valid_expired_run_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            old_run = reports_dir / "012345abcdef"
            old_non_run = reports_dir / "shared-cache"
            old_run.mkdir()
            old_non_run.mkdir()
            expired_time = time.time() - (25 * 60 * 60)
            os.utime(old_run, (expired_time, expired_time))
            os.utime(old_non_run, (expired_time, expired_time))

            with patch.dict(
                os.environ,
                {
                    "AI_ANALYST_WEB_REPORTS_DIR": str(reports_dir),
                    "AI_ANALYST_RETENTION_HOURS": "24",
                },
            ):
                app = create_app()
            client = app.test_client()

            response = client.get("/")

            self.assertEqual(response.status_code, 200)
            self.assertFalse(old_run.exists())
            self.assertTrue(old_non_run.exists())

    def test_public_web_mode_forces_llm_off_even_when_requested(self):
        with patch.dict(os.environ, {"AI_ANALYST_WEB_ALLOW_LLM": "0"}):
            app = create_app()
        client = app.test_client()
        captured = {}

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-public-no-llm"

        def fake_analyze_csv(csv_path, config):
            captured["use_llm"] = config.use_llm
            output_dir = Path(csv_path).parent.parent
            summary_path = output_dir / "summary.json"
            summary_path.write_text("{}", encoding="utf-8")
            report_path = output_dir / "report.md"
            report_path.write_text("# report", encoding="utf-8")
            return SimpleNamespace(
                output_dir=output_dir,
                summary_path=summary_path,
                report_paths={"markdown": report_path},
                charts=[],
                insights={"mode": "fallback", "content": "offline"},
                eda_summary={"shape": {"rows": 1, "columns": 2}},
            )

        with patch("ai_data_analyst.web.analyze_csv", side_effect=fake_analyze_csv):
            response = client.post(
                "/analyze",
                data={
                    "csrf_token": "token-public-no-llm",
                    "csv_text": "a,b\n1,2\n",
                    "report_format": "markdown",
                    "max_categories": "5",
                    "use_llm": "on",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(captured["use_llm"])
        self.assertIn("公网离线模式", body)

    def test_llm_is_disabled_by_default_for_web(self):
        app = create_app()
        client = app.test_client()
        captured = {}

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-default-no-llm"

        def fake_analyze_csv(csv_path, config):
            captured["use_llm"] = config.use_llm
            output_dir = Path(csv_path).parent.parent
            summary_path = output_dir / "summary.json"
            summary_path.write_text("{}", encoding="utf-8")
            report_path = output_dir / "report.md"
            report_path.write_text("# report", encoding="utf-8")
            return SimpleNamespace(
                output_dir=output_dir,
                summary_path=summary_path,
                report_paths={"markdown": report_path},
                charts=[],
                insights={"mode": "fallback", "content": "offline"},
                eda_summary={"shape": {"rows": 1, "columns": 2}},
            )

        with patch("ai_data_analyst.web.analyze_csv", side_effect=fake_analyze_csv):
            response = client.post(
                "/analyze",
                data={
                    "csrf_token": "token-default-no-llm",
                    "csv_text": "a,b\n1,2\n",
                    "report_format": "markdown",
                    "max_categories": "5",
                    "use_llm": "on",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(captured["use_llm"])

    def test_render_environment_values_configure_app(self):
        with patch.dict(
            os.environ,
            {
                "AI_ANALYST_WEB_REPORTS_DIR": "/tmp/ai-data-analyst-reports",
                "AI_ANALYST_MAX_UPLOAD_MB": "10",
                "AI_ANALYST_RETENTION_HOURS": "24",
                "AI_ANALYST_WEB_ALLOW_LLM": "0",
                "MPLBACKEND": "Agg",
            },
        ):
            app = create_app()

        self.assertEqual(app.config["WEB_REPORTS_DIR"], Path("/tmp/ai-data-analyst-reports").resolve())
        self.assertEqual(app.config["WEB_MAX_UPLOAD_MB"], 10)
        self.assertEqual(app.config["MAX_CONTENT_LENGTH"], 10 * 1024 * 1024)
        self.assertEqual(app.config["WEB_RETENTION_HOURS"], 24)
        self.assertFalse(app.config["WEB_ALLOW_LLM"])

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

    def test_analyze_accepts_https_origin_behind_proxy(self):
        with patch.dict(os.environ, {"AI_ANALYST_TRUST_PROXY": "1"}):
            app = create_app()
        client = app.test_client()
        captured = {}
        proxy_headers = {
            "Host": "data-analyst.onrender.com",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "data-analyst.onrender.com",
        }
        index_response = client.get("/", headers=proxy_headers)
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', index_response.get_data(as_text=True))
        self.assertIsNotNone(csrf_match)
        csrf_token = csrf_match.group(1)

        def fake_analyze_csv(csv_path, config):
            captured["called"] = True
            output_dir = Path(csv_path).parent.parent
            summary_path = output_dir / "summary.json"
            summary_path.write_text("{}", encoding="utf-8")
            report_path = output_dir / "report.md"
            report_path.write_text("# report", encoding="utf-8")
            return SimpleNamespace(
                output_dir=output_dir,
                summary_path=summary_path,
                report_paths={"markdown": report_path},
                charts=[],
                insights={"mode": "fallback", "content": "ok"},
                eda_summary={"shape": {"rows": 1, "columns": 2}},
            )

        with patch("ai_data_analyst.web.analyze_csv", side_effect=fake_analyze_csv):
            response = client.post(
                "/analyze",
                data={
                    "csrf_token": csrf_token,
                    "csv_text": "a,b\n1,2\n",
                    "report_format": "markdown",
                    "max_categories": "5",
                },
                headers={
                    **proxy_headers,
                    "Origin": "https://data-analyst.onrender.com",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(captured["called"])

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

    def test_analyze_clamps_large_max_categories_for_web_requests(self):
        app = create_app()
        client = app.test_client()
        captured = {}

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-large-max"

        def fake_analyze_csv(csv_path, config):
            captured["max_categories"] = config.max_categories
            output_dir = Path(csv_path).parent.parent
            summary_path = output_dir / "summary.json"
            summary_path.write_text("{}", encoding="utf-8")
            report_path = output_dir / "report.md"
            report_path.write_text("# report", encoding="utf-8")
            return SimpleNamespace(
                output_dir=output_dir,
                summary_path=summary_path,
                report_paths={"markdown": report_path},
                charts=[],
                insights={"mode": "fallback", "content": "ok"},
                eda_summary={"shape": {"rows": 1, "columns": 2}},
            )

        with patch("ai_data_analyst.web.analyze_csv", side_effect=fake_analyze_csv):
            response = client.post(
                "/analyze",
                data={
                    "csrf_token": "token-large-max",
                    "csv_text": "a,b\n1,2\n",
                    "report_format": "markdown",
                    "max_categories": "999999",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["max_categories"], 50)

    def test_analyze_uses_safe_max_categories_for_low_or_invalid_values(self):
        app = create_app()
        client = app.test_client()
        captured = []

        def fake_analyze_csv(csv_path, config):
            captured.append(config.max_categories)
            output_dir = Path(csv_path).parent.parent
            summary_path = output_dir / "summary.json"
            summary_path.write_text("{}", encoding="utf-8")
            report_path = output_dir / "report.md"
            report_path.write_text("# report", encoding="utf-8")
            return SimpleNamespace(
                output_dir=output_dir,
                summary_path=summary_path,
                report_paths={"markdown": report_path},
                charts=[],
                insights={"mode": "fallback", "content": "ok"},
                eda_summary={"shape": {"rows": 1, "columns": 2}},
            )

        with patch("ai_data_analyst.web.analyze_csv", side_effect=fake_analyze_csv):
            for token, value in (("token-low-max", "0"), ("token-invalid-max", "many")):
                with client.session_transaction() as session:
                    session["ai_analyst_csrf"] = token

                response = client.post(
                    "/analyze",
                    data={
                        "csrf_token": token,
                        "csv_text": "a,b\n1,2\n",
                        "report_format": "markdown",
                        "max_categories": value,
                    },
                    headers={"Origin": "http://localhost"},
                    content_type="multipart/form-data",
                )

                self.assertEqual(response.status_code, 200)

        self.assertEqual(captured, [1, 10])

    def test_web_max_categories_uses_default_for_extremely_long_numbers(self):
        self.assertEqual(web_max_categories("9" * 1000), 10)

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

    def test_artifacts_reject_invalid_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            invalid_run = Path(tmp) / "not-a-run-id"
            invalid_run.mkdir()
            (invalid_run / "summary.json").write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"AI_ANALYST_WEB_REPORTS_DIR": tmp}):
                app = create_app()
            client = app.test_client()

            self.assertEqual(client.get("/runs/not-a-run-id/summary.json").status_code, 404)
            self.assertEqual(client.get("/runs/..%2F..%2Ftmp/summary.json").status_code, 404)

    def test_artifact_allowlist_accepts_figures_png_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "012345abcdef"
            run_dir = Path(tmp) / run_id
            figures_dir = run_dir / "figures"
            figures_dir.mkdir(parents=True)
            (figures_dir / "chart.png").write_bytes(b"png")
            (figures_dir / "chart.svg").write_text("<svg></svg>", encoding="utf-8")
            nested_dir = figures_dir / "nested"
            nested_dir.mkdir()
            (nested_dir / "chart.png").write_bytes(b"png")

            with patch.dict(os.environ, {"AI_ANALYST_WEB_REPORTS_DIR": tmp}):
                app = create_app()
            client = app.test_client()

            with client.get(f"/runs/{run_id}/figures/chart.png") as artifact_response:
                self.assertEqual(artifact_response.status_code, 200)
            self.assertEqual(client.get(f"/runs/{run_id}/figures/chart.svg").status_code, 404)
            self.assertEqual(client.get(f"/runs/{run_id}/figures/nested/chart.png").status_code, 404)

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

    def test_analysis_errors_do_not_expose_server_paths(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-empty-csv"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-empty-csv",
                "csv_file": (BytesIO(b""), "empty.csv"),
            },
            headers={"Origin": "http://localhost"},
            content_type="multipart/form-data",
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("CSV file is empty.", body)
        self.assertNotIn(str(ROOT), body)
        self.assertNotIn("reports/web", body)

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
