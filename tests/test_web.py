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
DEMO_SAMPLE = ROOT / "examples" / "dashboard_test_sales.csv"


class WebAppTests(unittest.TestCase):
    def test_index_loads(self):
        app = create_app()
        client = app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI 数据分析助手", response.get_data(as_text=True))
        self.assertIn('name="csrf_token"', response.get_data(as_text=True))
        self.assertIn('name="max_categories" type="number" min="1" max="50"', response.get_data(as_text=True))
        self.assertIn('href="/demo"', response.get_data(as_text=True))
        self.assertIn("一键体验示例分析", response.get_data(as_text=True))
        self.assertIn("示例销售数据", response.get_data(as_text=True))

    def test_access_code_gate_hides_analysis_form_until_unlocked(self):
        with patch.dict(os.environ, {"AI_ANALYST_ACCESS_CODE": "let-me-in"}):
            app = create_app()
        client = app.test_client()

        response = client.get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("访问码", body)
        self.assertNotIn('id="analysis-form"', body)

    def test_required_access_code_without_code_fails_closed(self):
        with patch.dict(os.environ, {"AI_ANALYST_REQUIRE_ACCESS_CODE": "1"}, clear=False):
            with patch.dict(os.environ, {"AI_ANALYST_ACCESS_CODE": ""}, clear=False):
                app = create_app()
        client = app.test_client()

        response = client.get("/")
        health = client.get("/healthz")

        self.assertEqual(response.status_code, 503)
        self.assertIn("服务未配置访问码", response.get_data(as_text=True))
        self.assertEqual(health.status_code, 503)
        self.assertEqual(health.get_json(), {"status": "misconfigured"})

    def test_proxy_mode_without_access_code_fails_closed_by_default(self):
        with patch.dict(os.environ, {"AI_ANALYST_TRUST_PROXY": "1"}, clear=False):
            with patch.dict(os.environ, {"AI_ANALYST_ACCESS_CODE": ""}, clear=False):
                app = create_app()
        client = app.test_client()

        response = client.get(
            "/",
            headers={
                "Host": "data-analyst.onrender.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "data-analyst.onrender.com",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("服务未配置访问码", response.get_data(as_text=True))

    def test_proxy_mode_without_stable_secret_fails_closed(self):
        with patch.dict(
            os.environ,
            {
                "AI_ANALYST_TRUST_PROXY": "1",
                "AI_ANALYST_REQUIRE_ACCESS_CODE": "0",
                "AI_ANALYST_ACCESS_CODE": "",
                "AI_ANALYST_SECRET_KEY": "",
            },
            clear=False,
        ):
            app = create_app()
        client = app.test_client()

        response = client.get(
            "/",
            headers={
                "Host": "data-analyst.onrender.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "data-analyst.onrender.com",
            },
        )
        health = client.get("/healthz")

        self.assertEqual(response.status_code, 503)
        self.assertIn("服务未配置稳定密钥", response.get_data(as_text=True))
        self.assertEqual(health.status_code, 503)
        self.assertEqual(health.get_json(), {"status": "misconfigured"})

    def test_access_code_unlock_allows_index(self):
        with patch.dict(os.environ, {"AI_ANALYST_ACCESS_CODE": "let-me-in"}):
            app = create_app()
        client = app.test_client()
        index_response = client.get("/")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', index_response.get_data(as_text=True))
        self.assertIsNotNone(csrf_match)

        response = client.post(
            "/",
            data={"csrf_token": csrf_match.group(1), "access_code": "let-me-in"},
            headers={"Origin": "http://localhost"},
            follow_redirects=True,
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="analysis-form"', body)

    def test_access_code_required_for_analyze(self):
        with patch.dict(os.environ, {"AI_ANALYST_ACCESS_CODE": "let-me-in"}):
            app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-access-required"

        response = client.post(
            "/analyze",
            data={"csrf_token": "token-access-required", "csv_text": "a,b\n1,2\n"},
            headers={"Origin": "http://localhost"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("请输入访问码", response.get_data(as_text=True))

    def test_public_analyze_accepts_signed_csrf_without_session_cookie(self):
        app = create_app()
        issuing_client = app.test_client()
        stateless_client = app.test_client()
        index_response = issuing_client.get("/")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', index_response.get_data(as_text=True))
        self.assertIsNotNone(csrf_match)

        def fake_analyze_csv(csv_path, config):
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
            response = stateless_client.post(
                "/analyze",
                data={
                    "csrf_token": csrf_match.group(1),
                    "csv_text": "a,b\n1,2\n",
                    "report_format": "markdown",
                    "max_categories": "5",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("分析结论", response.get_data(as_text=True))

    def test_signed_csrf_rejects_different_client_fingerprint(self):
        app = create_app()
        issuing_client = app.test_client()
        stateless_client = app.test_client()
        index_response = issuing_client.get("/", headers={"User-Agent": "Browser A"})
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', index_response.get_data(as_text=True))
        self.assertIsNotNone(csrf_match)

        response = stateless_client.post(
            "/analyze",
            data={
                "csrf_token": csrf_match.group(1),
                "csv_text": "a,b\n1,2\n",
                "report_format": "markdown",
                "max_categories": "5",
            },
            headers={"Origin": "http://localhost", "User-Agent": "Browser B"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request origin or CSRF token.", response.get_data(as_text=True))

    def test_signed_csrf_accepts_same_origin_referer_without_origin(self):
        app = create_app()
        issuing_client = app.test_client()
        stateless_client = app.test_client()
        index_response = issuing_client.get("/")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', index_response.get_data(as_text=True))
        self.assertIsNotNone(csrf_match)

        def fake_analyze_csv(csv_path, config):
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
            response = stateless_client.post(
                "/analyze",
                data={
                    "csrf_token": csrf_match.group(1),
                    "csv_text": "a,b\n1,2\n",
                    "report_format": "markdown",
                    "max_categories": "5",
                },
                headers={"Referer": "http://localhost/"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("分析结论", response.get_data(as_text=True))

    def test_session_csrf_requires_same_origin_signal(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-session-no-origin"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-session-no-origin",
                "csv_text": "a,b\n1,2\n",
                "report_format": "markdown",
                "max_categories": "5",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request origin or CSRF token.", response.get_data(as_text=True))

    def test_public_analyze_rejects_null_origin(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-null-origin"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-null-origin",
                "report_format": "markdown",
                "max_categories": "5",
            },
            headers={"Origin": "null"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request origin or CSRF token.", response.get_data(as_text=True))

    def test_access_code_attempts_are_rate_limited(self):
        with patch.dict(
            os.environ,
            {
                "AI_ANALYST_ACCESS_CODE": "let-me-in",
                "AI_ANALYST_ACCESS_ATTEMPT_LIMIT_PER_HOUR": "1",
            },
        ):
            app = create_app()
        client = app.test_client()
        index_response = client.get("/")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', index_response.get_data(as_text=True))
        self.assertIsNotNone(csrf_match)

        first = client.post(
            "/",
            data={"csrf_token": csrf_match.group(1), "access_code": "wrong"},
            headers={"Origin": "http://localhost"},
        )
        second = client.post(
            "/",
            data={"csrf_token": csrf_match.group(1), "access_code": "wrong-again"},
            headers={"Origin": "http://localhost"},
        )

        self.assertEqual(first.status_code, 403)
        self.assertEqual(second.status_code, 429)
        self.assertIn("访问码尝试太频繁", second.get_data(as_text=True))

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

    def test_web_resource_limits_are_passed_to_analysis_config(self):
        with patch.dict(
            os.environ,
            {
                "AI_ANALYST_MAX_ROWS": "250",
                "AI_ANALYST_MAX_COLUMNS": "30",
                "AI_ANALYST_MAX_CORRELATION_COLUMNS": "12",
            },
        ):
            app = create_app()
        client = app.test_client()
        captured = {}

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-resource-limits"

        def fake_analyze_csv(csv_path, config):
            captured["max_rows"] = config.max_rows
            captured["max_columns"] = config.max_columns
            captured["max_correlation_columns"] = config.max_correlation_columns
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
                    "csrf_token": "token-resource-limits",
                    "csv_text": "a,b\n1,2\n",
                    "report_format": "markdown",
                    "max_categories": "5",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured, {"max_rows": 250, "max_columns": 30, "max_correlation_columns": 12})

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

    def test_proxy_mode_uses_forwarded_for_and_secure_cookie(self):
        with patch.dict(
            os.environ,
            {
                "AI_ANALYST_TRUST_PROXY": "1",
                "AI_ANALYST_ACCESS_CODE": "let-me-in",
                "AI_ANALYST_SECRET_KEY": "stable-test-secret",
            },
        ):
            app = create_app()
        client = app.test_client()

        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        response = client.get(
            "/",
            headers={
                "Host": "data-analyst.onrender.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "data-analyst.onrender.com",
                "X-Forwarded-For": "203.0.113.7",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers.get("Set-Cookie", ""))

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
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(response.headers.get("Referrer-Policy"), "same-origin")

    def test_demo_dataset_returns_result_page_without_csrf(self):
        app = create_app()
        client = app.test_client()
        captured = {}

        def fake_analyze_csv(csv_path, config):
            captured["path"] = Path(csv_path)
            captured["target_column"] = config.target_column
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
                insights={"mode": "fallback", "content": "ok"},
                eda_summary={"shape": {"rows": 36, "columns": 15}},
            )

        with patch("ai_data_analyst.web.analyze_csv", side_effect=fake_analyze_csv):
            response = client.get("/demo")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["path"].name, DEMO_SAMPLE.name)
        self.assertTrue(captured["path"].read_text(encoding="utf-8").startswith("order_id,order_date"))
        self.assertEqual(captured["target_column"], "revenue")
        self.assertFalse(captured["use_llm"])
        self.assertIn("示例销售数据", body)
        self.assertIn("报告下载", body)
        self.assertNotIn(str(ROOT), body)

    def test_demo_requires_access_code_when_enabled(self):
        with patch.dict(os.environ, {"AI_ANALYST_ACCESS_CODE": "let-me-in"}):
            app = create_app()
        client = app.test_client()

        response = client.get("/demo")

        self.assertEqual(response.status_code, 403)
        self.assertIn("请输入访问码", response.get_data(as_text=True))

    def test_demo_uses_analysis_rate_limit(self):
        with patch.dict(os.environ, {"AI_ANALYST_RATE_LIMIT_PER_HOUR": "1"}):
            app = create_app()
        client = app.test_client()

        def fake_analyze_csv(csv_path, config):
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
                eda_summary={"shape": {"rows": 36, "columns": 15}},
            )

        with patch("ai_data_analyst.web.analyze_csv", side_effect=fake_analyze_csv):
            first = client.get("/demo")
            second = client.get("/demo")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("请求太频繁", second.get_data(as_text=True))

    def test_analyze_accepts_https_origin_behind_proxy(self):
        with patch.dict(
            os.environ,
            {
                "AI_ANALYST_TRUST_PROXY": "1",
                "AI_ANALYST_ACCESS_CODE": "let-me-in",
                "AI_ANALYST_SECRET_KEY": "stable-test-secret",
            },
        ):
            app = create_app()
        client = app.test_client()
        captured = {}
        proxy_headers = {
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "data-analyst.onrender.com",
        }
        index_response = client.get("/", base_url="https://data-analyst.onrender.com", headers=proxy_headers)
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', index_response.get_data(as_text=True))
        self.assertIsNotNone(csrf_match)
        unlock_response = client.post(
            "/",
            base_url="https://data-analyst.onrender.com",
            data={"csrf_token": csrf_match.group(1), "access_code": "let-me-in"},
            headers={**proxy_headers, "Origin": "https://data-analyst.onrender.com"},
            follow_redirects=True,
        )
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', unlock_response.get_data(as_text=True))
        self.assertIsNotNone(csrf_match)

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
                base_url="https://data-analyst.onrender.com",
                data={
                    "csrf_token": csrf_match.group(1),
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

    def test_rate_limit_rejects_repeated_analysis_requests(self):
        with patch.dict(os.environ, {"AI_ANALYST_RATE_LIMIT_PER_HOUR": "1"}):
            app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-rate-limit"

        def fake_analyze_csv(csv_path, config):
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

        payload = {
            "csrf_token": "token-rate-limit",
            "csv_text": "a,b\n1,2\n",
            "report_format": "markdown",
            "max_categories": "5",
        }
        with patch("ai_data_analyst.web.analyze_csv", side_effect=fake_analyze_csv):
            first = client.post(
                "/analyze",
                data=payload,
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )
            second = client.post(
                "/analyze",
                data=payload,
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("请求太频繁", second.get_data(as_text=True))

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
        run_id, token = self._extract_run_link_parts(response.get_data(as_text=True))
        with client.get(f"/runs/{run_id}/{token}/summary.json") as artifact_response:
            self.assertEqual(artifact_response.status_code, 200)
            self.assertIn("no-store", artifact_response.headers.get("Cache-Control", ""))
            self.assertEqual(artifact_response.headers.get("Referrer-Policy"), "same-origin")
        self.assertEqual(client.get(f"/runs/{run_id}/summary.json").status_code, 404)
        self.assertEqual(client.get(f"/runs/{run_id}/wrong-token/summary.json").status_code, 404)
        self.assertEqual(client.get(f"/runs/{run_id}/_inputs/pasted.csv").status_code, 404)
        self.assertEqual(client.get(f"/runs/{run_id}/{token}/_inputs/pasted.csv").status_code, 404)
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
        run_id, token = self._extract_run_link_parts(response.get_data(as_text=True))
        with client.get(f"/runs/{run_id}/{token}/summary.json") as artifact_response:
            self.assertEqual(artifact_response.status_code, 200)
        self.assertEqual(client.get(f"/runs/{run_id}/_inputs/private_sales.csv").status_code, 404)
        self.assertEqual(client.get(f"/runs/{run_id}/{token}/_inputs/private_sales.csv").status_code, 404)
        self.assertEqual(client.get(f"/runs/{run_id}/private_sales.csv").status_code, 404)

    def test_artifacts_reject_invalid_run_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            invalid_run = Path(tmp) / "not-a-run-id"
            invalid_run.mkdir()
            (invalid_run / "summary.json").write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"AI_ANALYST_WEB_REPORTS_DIR": tmp}):
                app = create_app()
            client = app.test_client()

            self.assertEqual(client.get("/runs/not-a-run-id/token/summary.json").status_code, 404)
            self.assertEqual(client.get("/runs/..%2F..%2Ftmp/token/summary.json").status_code, 404)
            self.assertEqual(client.get("/runs/not-a-run-id/summary.json").status_code, 404)

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
            token = "artifact-token"
            (run_dir / ".artifact-token").write_text(token, encoding="utf-8")

            with client.get(f"/runs/{run_id}/{token}/figures/chart.png") as artifact_response:
                self.assertEqual(artifact_response.status_code, 200)
            self.assertEqual(client.get(f"/runs/{run_id}/{token}/figures/chart.svg").status_code, 404)
            self.assertEqual(client.get(f"/runs/{run_id}/{token}/figures/nested/chart.png").status_code, 404)

    def test_artifacts_fail_closed_when_access_code_is_required_but_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "012345abcdef"
            token = "artifact-token"
            run_dir = Path(tmp) / run_id
            run_dir.mkdir()
            (run_dir / ".artifact-token").write_text(token, encoding="utf-8")
            (run_dir / "summary.json").write_text("{}", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "AI_ANALYST_WEB_REPORTS_DIR": tmp,
                    "AI_ANALYST_TRUST_PROXY": "1",
                    "AI_ANALYST_ACCESS_CODE": "",
                },
                clear=False,
            ):
                app = create_app()
            client = app.test_client()

            with client.session_transaction() as session:
                session["ai_analyst_access_granted"] = True

            response = client.get(f"/runs/{run_id}/{token}/summary.json")

            self.assertEqual(response.status_code, 404)

    def test_unexpected_analysis_errors_return_friendly_message(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-runtime-error"

        with patch("ai_data_analyst.web.analyze_csv", side_effect=RuntimeError("disk failed /private/path")):
            response = client.post(
                "/analyze",
                data={
                    "csrf_token": "token-runtime-error",
                    "csv_text": "a,b\n1,2\n",
                    "report_format": "markdown",
                    "max_categories": "5",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 500)
        self.assertIn("分析失败", body)
        self.assertNotIn("/private/path", body)

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

    def test_analyze_ignores_stale_sample_flag_and_rejects_missing_user_input(self):
        app = create_app()
        client = app.test_client()

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-sample-conflict"

        response = client.post(
            "/analyze",
            data={
                "csrf_token": "token-sample-conflict",
                "sample_dataset": "sales",
                "report_format": "markdown",
            },
            headers={"Origin": "http://localhost"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("一键体验示例分析", response.get_data(as_text=True))

    def test_analyze_treats_upload_as_user_input_when_stale_sample_flag_is_present(self):
        app = create_app()
        client = app.test_client()
        captured = {}

        with client.session_transaction() as session:
            session["ai_analyst_csrf"] = "token-sample-upload-conflict"

        def fake_analyze_csv(csv_path, config):
            captured["path"] = Path(csv_path)
            captured["target_column"] = config.target_column
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
                    "csrf_token": "token-sample-upload-conflict",
                    "sample_dataset": "sales",
                    "csv_file": (BytesIO(b"a,b\n1,2\n"), "uploaded.csv"),
                    "report_format": "markdown",
                },
                headers={"Origin": "http://localhost"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["path"].name, "uploaded.csv")
        self.assertIsNone(captured["target_column"])

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

    def _extract_run_link_parts(self, body: str) -> tuple[str, str]:
        match = re.search(r"/runs/([0-9a-f]{12})/([^/]+)/summary\.json", body)
        self.assertIsNotNone(match)
        return match.group(1), match.group(2)


if __name__ == "__main__":
    unittest.main()
