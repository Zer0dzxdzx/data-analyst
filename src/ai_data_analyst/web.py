"""Flask web app for the AI data analyst."""

from __future__ import annotations

import os
import shutil
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from secrets import compare_digest, token_urlsafe
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, abort, current_app, redirect, render_template, request, send_from_directory, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from ai_data_analyst.config import AnalysisConfig
from ai_data_analyst.exceptions import AnalysisError
from ai_data_analyst.workflow import analyze_csv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_MIN_CATEGORIES = 1
WEB_MAX_CATEGORIES = 50
WEB_DEFAULT_CATEGORIES = 10
WEB_MAX_CATEGORIES_DIGITS = 12
DEFAULT_WEB_MAX_UPLOAD_MB = 20
DEFAULT_WEB_RETENTION_HOURS = 24
DEFAULT_WEB_RATE_LIMIT_PER_HOUR = 20
DEFAULT_WEB_ACCESS_ATTEMPT_LIMIT_PER_HOUR = 10
DEFAULT_WEB_MAX_ROWS = 100_000
DEFAULT_WEB_MAX_COLUMNS = 100
DEFAULT_WEB_MAX_CORRELATION_COLUMNS = 30
RATE_LIMIT_WINDOW_SECONDS = 60 * 60
ACCESS_SESSION_KEY = "ai_analyst_access_granted"
CSRF_SESSION_KEY = "ai_analyst_csrf"
CSRF_SIGNING_SALT = "ai-data-analyst-csrf"
CSRF_TOKEN_MAX_AGE_SECONDS = 6 * 60 * 60
ARTIFACT_TOKEN_FILE = ".artifact-token"
SAMPLE_DATASET_LABEL = "示例销售数据"
SAMPLE_DATASET_TARGET = "revenue"
SAMPLE_DATASET_FILENAME = "dashboard_test_sales.csv"
SAMPLE_DATASET_PATH = PROJECT_ROOT / "examples" / SAMPLE_DATASET_FILENAME
SAMPLE_DATASET_ROWS = 36
SAMPLE_DATASET_COLUMNS = 15


@dataclass(slots=True)
class AnalyzeForm:
    target: str
    use_llm: bool
    report_format: str
    max_categories: int
    csv_text: str


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
    )
    max_upload_mb = _env_int("AI_ANALYST_MAX_UPLOAD_MB", DEFAULT_WEB_MAX_UPLOAD_MB, minimum=1)
    retention_hours = _env_int("AI_ANALYST_RETENTION_HOURS", DEFAULT_WEB_RETENTION_HOURS, minimum=0)
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024
    configured_secret_key = os.getenv("AI_ANALYST_SECRET_KEY", "").strip()
    app.config["SECRET_KEY"] = configured_secret_key or token_urlsafe(32)
    app.config["WEB_SECRET_KEY_EPHEMERAL"] = not configured_secret_key
    app.config["WEB_REPORTS_DIR"] = Path(
        os.getenv("AI_ANALYST_WEB_REPORTS_DIR", PROJECT_ROOT / "reports" / "web")
    ).expanduser().resolve()
    app.config["WEB_MAX_UPLOAD_MB"] = max_upload_mb
    app.config["WEB_RETENTION_HOURS"] = retention_hours
    app.config["WEB_ALLOW_LLM"] = _env_bool("AI_ANALYST_WEB_ALLOW_LLM", default=False)
    app.config["WEB_ACCESS_CODE"] = os.getenv("AI_ANALYST_ACCESS_CODE", "").strip()
    trust_proxy = _env_bool("AI_ANALYST_TRUST_PROXY", default=False)
    app.config["WEB_TRUST_PROXY"] = trust_proxy
    app.config["WEB_REQUIRE_ACCESS_CODE"] = _env_bool("AI_ANALYST_REQUIRE_ACCESS_CODE", default=trust_proxy)
    app.config["WEB_RATE_LIMIT_PER_HOUR"] = _env_int(
        "AI_ANALYST_RATE_LIMIT_PER_HOUR",
        DEFAULT_WEB_RATE_LIMIT_PER_HOUR,
        minimum=0,
    )
    app.config["WEB_ACCESS_ATTEMPT_LIMIT_PER_HOUR"] = _env_int(
        "AI_ANALYST_ACCESS_ATTEMPT_LIMIT_PER_HOUR",
        DEFAULT_WEB_ACCESS_ATTEMPT_LIMIT_PER_HOUR,
        minimum=0,
    )
    app.config["WEB_RATE_LIMIT_STATE"] = {}
    app.config["WEB_MAX_ROWS"] = _env_int("AI_ANALYST_MAX_ROWS", DEFAULT_WEB_MAX_ROWS, minimum=1)
    app.config["WEB_MAX_COLUMNS"] = _env_int("AI_ANALYST_MAX_COLUMNS", DEFAULT_WEB_MAX_COLUMNS, minimum=1)
    app.config["WEB_MAX_CORRELATION_COLUMNS"] = _env_int(
        "AI_ANALYST_MAX_CORRELATION_COLUMNS",
        DEFAULT_WEB_MAX_CORRELATION_COLUMNS,
        minimum=2,
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _env_bool("AI_ANALYST_SESSION_COOKIE_SECURE", default=trust_proxy)
    if trust_proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.after_request
    def add_security_headers(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.before_request
    def cleanup_expired_runs() -> None:
        if request.endpoint == "healthz":
            return
        _cleanup_expired_runs(app)

    @app.get("/healthz")
    def healthz():
        if _service_misconfigured(app):
            return {"status": "misconfigured"}, 503
        return {"status": "ok"}

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_exc: RequestEntityTooLarge):
        limit = app.config["WEB_MAX_UPLOAD_MB"]
        return _render_index(error=f"CSV 文件过大。最大 {limit}MB。"), 413

    @app.get("/")
    def index():
        if _service_misconfigured(app):
            return _render_index(error=_service_configuration_error(app)), 503
        return _render_index()

    @app.post("/")
    def unlock_access():
        if _service_misconfigured(app):
            return _render_index(error=_service_configuration_error(app)), 503
        if not _access_required(app):
            return redirect(url_for("index"))
        if not _check_csrf():
            return _render_index(error="Invalid request origin or CSRF token."), 400
        if not _check_rate_limit(app, bucket="access", limit_config="WEB_ACCESS_ATTEMPT_LIMIT_PER_HOUR"):
            return _render_index(error="访问码尝试太频繁，请稍后再试。"), 429
        if _access_code_matches(app, request.form.get("access_code", "")):
            session[ACCESS_SESSION_KEY] = True
            return redirect(url_for("index"))
        return _render_index(error="访问码不正确，请重新输入。"), 403

    @app.post("/analyze")
    def analyze() -> str:
        if not _check_csrf():
            return _render_index(error="Invalid request origin or CSRF token."), 400
        if _service_misconfigured(app):
            return _render_index(error=_service_configuration_error(app)), 503
        if not _has_access(app):
            return _render_index(error="请输入访问码后再上传分析。"), 403
        if not _check_rate_limit(app, bucket="analysis", limit_config="WEB_RATE_LIMIT_PER_HOUR"):
            return _render_index(error="请求太频繁，请稍后再试。"), 429

        uploaded = request.files.get("csv_file")
        form = _parse_analyze_form(app)
        if _csv_text_too_large(app, form.csv_text):
            limit = app.config["WEB_MAX_UPLOAD_MB"]
            return _render_index(error=f"CSV 文本过大。最大 {limit}MB。"), 413

        has_upload = bool(uploaded and uploaded.filename)
        if form.csv_text and has_upload:
            return _render_index(error="Please provide either a CSV file or pasted CSV text, not both."), 400

        if not form.csv_text and not has_upload:
            return _render_index(error="请选择上传文件、粘贴 CSV，或点击一键体验示例分析。"), 400

        run_id = uuid.uuid4().hex[:12]
        run_dir = _run_dir(app, run_id)
        input_dir = run_dir / "_inputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        source_label = "上传文件"
        if form.csv_text:
            csv_path = input_dir / "pasted.csv"
            csv_path.write_text(form.csv_text, encoding="utf-8")
            source_label = "粘贴 CSV"
        else:
            csv_path = input_dir / _safe_filename(uploaded.filename or "")
            uploaded.save(csv_path)
        target_column = form.target or None

        try:
            result = analyze_csv(
                csv_path,
                AnalysisConfig(
                    output_dir=run_dir,
                    target_column=target_column,
                    max_categories=form.max_categories,
                    use_llm=form.use_llm,
                    report_format=form.report_format,
                    max_rows=app.config["WEB_MAX_ROWS"],
                    max_columns=app.config["WEB_MAX_COLUMNS"],
                    max_correlation_columns=app.config["WEB_MAX_CORRELATION_COLUMNS"],
                ),
            )
        except AnalysisError as exc:
            shutil.rmtree(run_dir, ignore_errors=True)
            return _analysis_error_response(exc)
        except ValueError as exc:
            shutil.rmtree(run_dir, ignore_errors=True)
            return _analysis_error_response(exc)
        except Exception:
            app.logger.exception("Unexpected analysis failure for run %s", run_id)
            shutil.rmtree(run_dir, ignore_errors=True)
            return _render_index(error="分析失败。请检查 CSV 后重试；如果问题持续出现，请稍后再试。"), 500

        artifact_token = token_urlsafe(18)
        _write_artifact_token(run_dir, artifact_token)
        preview = _build_preview(app, run_id, result, artifact_token, source_label)
        return _render_index(
            result=preview,
            defaults={
                **_defaults(),
                "last_target": target_column or "",
                "last_report_format": form.report_format,
                "last_use_llm": form.use_llm,
            },
        )

    @app.get("/demo")
    def demo() -> str:
        if _service_misconfigured(app):
            return _render_index(error=_service_configuration_error(app)), 503
        if not _has_access(app):
            return _render_index(error="请输入访问码后再查看示例分析。"), 403
        if not _check_rate_limit(app, bucket="analysis", limit_config="WEB_RATE_LIMIT_PER_HOUR"):
            return _render_index(error="请求太频繁，请稍后再试。"), 429
        return _run_sample_analysis(app)

    @app.get("/runs/<run_id>/<token>/<path:filename>")
    def artifact(run_id: str, token: str, filename: str) -> Any:
        if _service_misconfigured(app):
            abort(404)
        if not _has_access(app):
            abort(404)
        if not _is_valid_run_id(run_id):
            abort(404)
        run_dir = _run_dir(app, run_id)
        if not run_dir.exists() or not _is_allowed_artifact(filename) or not _artifact_token_matches(run_dir, token):
            abort(404)
        return send_from_directory(run_dir, filename, as_attachment=False)

    @app.get("/runs/<run_id>/<path:filename>")
    def legacy_artifact(run_id: str, filename: str) -> Any:
        abort(404)

    return app


def _run_sample_analysis(app: Flask) -> str:
    if not SAMPLE_DATASET_PATH.exists():
        return _render_index(error="示例数据暂不可用，请上传 CSV 或稍后再试。"), 500

    run_id = uuid.uuid4().hex[:12]
    run_dir = _run_dir(app, run_id)
    input_dir = run_dir / "_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    csv_path = input_dir / SAMPLE_DATASET_FILENAME
    shutil.copyfile(SAMPLE_DATASET_PATH, csv_path)

    try:
        result = analyze_csv(
            csv_path,
            AnalysisConfig(
                output_dir=run_dir,
                target_column=SAMPLE_DATASET_TARGET,
                max_categories=WEB_DEFAULT_CATEGORIES,
                use_llm=False,
                report_format="both",
                max_rows=app.config["WEB_MAX_ROWS"],
                max_columns=app.config["WEB_MAX_COLUMNS"],
                max_correlation_columns=app.config["WEB_MAX_CORRELATION_COLUMNS"],
            ),
        )
    except AnalysisError as exc:
        shutil.rmtree(run_dir, ignore_errors=True)
        return _analysis_error_response(exc)
    except ValueError as exc:
        shutil.rmtree(run_dir, ignore_errors=True)
        return _analysis_error_response(exc)
    except Exception:
        app.logger.exception("Unexpected sample analysis failure for run %s", run_id)
        shutil.rmtree(run_dir, ignore_errors=True)
        return _render_index(error="示例分析失败。请稍后再试，或改用上传 CSV。"), 500

    artifact_token = token_urlsafe(18)
    _write_artifact_token(run_dir, artifact_token)
    preview = _build_preview(app, run_id, result, artifact_token, SAMPLE_DATASET_LABEL)
    return _render_index(
        result=preview,
        defaults={
            **_defaults(),
            "last_target": SAMPLE_DATASET_TARGET,
            "last_report_format": "both",
            "last_use_llm": False,
        },
    )


def main() -> int:
    app = create_app()
    port = int(os.getenv("AI_ANALYST_PORT", "8000"))
    debug = os.getenv("AI_ANALYST_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=port, debug=debug)
    return 0


def _build_preview(app: Flask, run_id: str, result, artifact_token: str, source_label: str) -> dict[str, Any]:
    report_paths = {
        name: _artifact_url(app, run_id, artifact_token, result.output_dir, path)
        for name, path in result.report_paths.items()
    }
    summary_url = _artifact_url(app, run_id, artifact_token, result.output_dir, result.summary_path)
    charts = []
    for chart in result.charts:
        url = None
        if chart.get("rendered", True) and chart.get("path"):
            url = _artifact_url(app, run_id, artifact_token, result.output_dir, Path(chart["path"]))
        charts.append(
            {
                "title": chart.get("title"),
                "url": url,
                "rendered": chart.get("rendered", True),
            }
        )
    return {
        "run_id": run_id,
        "output_label": f"runs/{run_id}",
        "source_label": source_label,
        "summary_url": summary_url,
        "report_urls": report_paths,
        "insights": result.insights,
        "eda_summary": result.eda_summary,
        "charts": charts,
    }


def _defaults() -> dict[str, Any]:
    return {
        "last_target": "",
        "last_report_format": "both",
        "last_use_llm": False,
    }


def _render_index(
    result: dict[str, Any] | None = None,
    error: str | None = None,
    defaults: dict[str, Any] | None = None,
) -> str:
    return render_template(
        "index.html",
        result=result,
        error=error,
        defaults=defaults or _defaults(),
        csrf_token=_csrf_token(),
        settings=_web_settings(),
    )


def _parse_analyze_form(app: Flask) -> AnalyzeForm:
    requested_llm = request.form.get("use_llm") == "on"
    return AnalyzeForm(
        target=_clean_text(request.form.get("target")),
        use_llm=requested_llm and bool(app.config["WEB_ALLOW_LLM"]),
        report_format=_clean_text(request.form.get("report_format")) or "both",
        max_categories=web_max_categories(request.form.get("max_categories")),
        csv_text=_clean_text(request.form.get("csv_text")),
    )


def _web_settings() -> dict[str, Any]:
    from flask import current_app

    retention_hours = int(current_app.config.get("WEB_RETENTION_HOURS", DEFAULT_WEB_RETENTION_HOURS))
    access_enabled = _access_required(current_app)
    return {
        "allow_llm": bool(current_app.config.get("WEB_ALLOW_LLM", True)),
        "max_upload_mb": int(current_app.config.get("WEB_MAX_UPLOAD_MB", DEFAULT_WEB_MAX_UPLOAD_MB)),
        "retention_hours": retention_hours,
        "retention_label": _retention_label(retention_hours),
        "access_enabled": access_enabled,
        "access_required": access_enabled and not _has_access(current_app),
        "max_rows": int(current_app.config.get("WEB_MAX_ROWS", DEFAULT_WEB_MAX_ROWS)),
        "max_columns": int(current_app.config.get("WEB_MAX_COLUMNS", DEFAULT_WEB_MAX_COLUMNS)),
        "rate_limit_per_hour": int(
            current_app.config.get("WEB_RATE_LIMIT_PER_HOUR", DEFAULT_WEB_RATE_LIMIT_PER_HOUR)
        ),
        "sample_dataset": {
            "label": SAMPLE_DATASET_LABEL,
            "target": SAMPLE_DATASET_TARGET,
            "rows": SAMPLE_DATASET_ROWS,
            "columns": SAMPLE_DATASET_COLUMNS,
        },
    }


def _analysis_error_response(exc: Exception):
    return _render_index(error=_public_error_message(exc)), 400


def _public_error_message(exc: Exception) -> str:
    message = str(exc)
    if "Target column not found" in message:
        return message
    if "empty" in message.lower():
        return "CSV file is empty."
    if "parser error" in message.lower():
        return "CSV parser error. Please check the file format."
    if "could not decode" in message.lower():
        return "Could not decode CSV. Please save it as UTF-8 or UTF-8-SIG and try again."
    if "no columns" in message.lower():
        return "CSV has no columns."
    if "no data rows" in message.lower():
        return "CSV has columns but no data rows."
    if "too many rows" in message.lower() or "too many columns" in message.lower():
        return message
    return "Could not analyze the CSV. Please check the file and try again."


def _safe_filename(name: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {".", "_", "-"} else "_" for char in name)
    return cleaned or "upload.csv"


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _int_or_default(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    value = _int_or_default(os.getenv(name), default)
    if minimum is not None:
        value = max(value, minimum)
    return value


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _retention_label(hours: int) -> str:
    if hours <= 0:
        return "本地报告不自动清理"
    if hours % 24 == 0:
        days = hours // 24
        if days == 1:
            return "报告临时保留 24 小时"
        return f"报告临时保留 {days} 天"
    return f"报告临时保留 {hours} 小时"


def web_max_categories(value: str | None) -> int:
    cleaned = _clean_text(value)
    if cleaned.startswith("-"):
        numeric_text = cleaned[1:]
    else:
        numeric_text = cleaned
    if len(numeric_text) > WEB_MAX_CATEGORIES_DIGITS or not numeric_text.isdecimal():
        parsed = WEB_DEFAULT_CATEGORIES
    else:
        parsed = _int_or_default(cleaned, WEB_DEFAULT_CATEGORIES)
    return min(max(parsed, WEB_MIN_CATEGORIES), WEB_MAX_CATEGORIES)


def _run_dir(app: Flask, run_id: str) -> Path:
    return Path(app.config["WEB_REPORTS_DIR"]) / run_id


def _is_valid_run_id(run_id: str) -> bool:
    return len(run_id) == 12 and all(char in "0123456789abcdef" for char in run_id)


def _cleanup_expired_runs(app: Flask) -> None:
    retention_hours = int(app.config.get("WEB_RETENTION_HOURS", DEFAULT_WEB_RETENTION_HOURS))
    if retention_hours <= 0:
        return
    reports_dir = Path(app.config["WEB_REPORTS_DIR"])
    if not reports_dir.exists():
        return

    cutoff = time.time() - (retention_hours * 60 * 60)
    for child in reports_dir.iterdir():
        try:
            if child.is_symlink() or not child.is_dir() or not _is_valid_run_id(child.name):
                continue
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child)
        except OSError:
            continue


def _artifact_url(app: Flask, run_id: str, token: str, output_dir: Path, path: Path) -> str:
    relative = Path(path).resolve().relative_to(output_dir.resolve()).as_posix()
    if not _is_allowed_artifact(relative):
        raise ValueError(f"Artifact is not web-accessible: {relative}")
    return url_for("artifact", run_id=run_id, token=token, filename=relative)


def _is_allowed_artifact(filename: str) -> bool:
    path = PurePosixPath(filename)
    if path.is_absolute() or not path.parts:
        return False
    if any(part in {"", ".", ".."} for part in path.parts):
        return False
    if len(path.parts) == 1:
        return path.name in {"summary.json", "report.md", "report.html"}
    if len(path.parts) == 2 and path.parts[0] == "figures":
        return path.suffix.lower() == ".png"
    return False


def _write_artifact_token(run_dir: Path, token: str) -> None:
    (run_dir / ARTIFACT_TOKEN_FILE).write_text(token, encoding="utf-8")


def _artifact_token_matches(run_dir: Path, submitted: str) -> bool:
    try:
        expected = (run_dir / ARTIFACT_TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(submitted and expected and compare_digest(expected, submitted))


def _access_required(app: Flask) -> bool:
    return bool(app.config.get("WEB_REQUIRE_ACCESS_CODE")) or bool(str(app.config.get("WEB_ACCESS_CODE", "")).strip())


def _access_misconfigured(app: Flask) -> bool:
    return bool(app.config.get("WEB_REQUIRE_ACCESS_CODE")) and not str(app.config.get("WEB_ACCESS_CODE", "")).strip()


def _secret_key_misconfigured(app: Flask) -> bool:
    return bool(app.config.get("WEB_TRUST_PROXY")) and bool(app.config.get("WEB_SECRET_KEY_EPHEMERAL"))


def _service_misconfigured(app: Flask) -> bool:
    return _access_misconfigured(app) or _secret_key_misconfigured(app)


def _service_configuration_error(app: Flask) -> str:
    if _access_misconfigured(app):
        return "服务未配置访问码。请设置 AI_ANALYST_ACCESS_CODE 后再开放公网访问。"
    return "服务未配置稳定密钥。请设置 AI_ANALYST_SECRET_KEY 后再开放公网访问。"


def _has_access(app: Flask) -> bool:
    if not _access_required(app):
        return True
    return bool(session.get(ACCESS_SESSION_KEY))


def _access_code_matches(app: Flask, submitted: str) -> bool:
    expected = str(app.config.get("WEB_ACCESS_CODE", "")).strip()
    return bool(submitted and expected and compare_digest(expected, submitted.strip()))


def _csv_text_too_large(app: Flask, csv_text: str) -> bool:
    if not csv_text:
        return False
    max_bytes = int(app.config["WEB_MAX_UPLOAD_MB"]) * 1024 * 1024
    return len(csv_text.encode("utf-8")) > max_bytes


def _check_rate_limit(app: Flask, bucket: str, limit_config: str) -> bool:
    limit = int(app.config.get(limit_config, DEFAULT_WEB_RATE_LIMIT_PER_HOUR))
    if limit <= 0:
        return True
    state: dict[str, list[float]] = app.config["WEB_RATE_LIMIT_STATE"]
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    client = f"{bucket}:{_client_key()}"
    attempts = [stamp for stamp in state.get(client, []) if stamp >= cutoff]
    if len(attempts) >= limit:
        state[client] = attempts
        return False
    attempts.append(now)
    state[client] = attempts
    return True


def _client_key() -> str:
    return request.remote_addr or "local"


def _csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = token_urlsafe(24)
        session[CSRF_SESSION_KEY] = token
    return _signed_csrf_token()


def _check_csrf() -> bool:
    origin = request.headers.get("Origin", "")
    referer = request.headers.get("Referer", "")
    host = request.host_url.rstrip("/")
    if origin and not _same_origin(origin, host):
        return False
    if referer and not _same_origin(referer, host):
        return False
    if not (origin or referer):
        return False
    form_token = request.form.get("csrf_token", "")
    if not form_token:
        return False
    session_token = session.get(CSRF_SESSION_KEY, "")
    if session_token and compare_digest(str(session_token), str(form_token)):
        return True
    return _signed_csrf_token_matches(str(form_token))


def _signed_csrf_token() -> str:
    payload = {
        "nonce": token_urlsafe(16),
        "client": _csrf_client_fingerprint(),
        "v": 1,
    }
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=CSRF_SIGNING_SALT).dumps(payload)


def _signed_csrf_token_matches(token: str) -> bool:
    try:
        payload = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=CSRF_SIGNING_SALT).loads(
            token,
            max_age=CSRF_TOKEN_MAX_AGE_SECONDS,
        )
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("v") != 1:
        return False
    submitted_fingerprint = str(payload.get("client", ""))
    return bool(submitted_fingerprint) and compare_digest(submitted_fingerprint, _csrf_client_fingerprint())


def _csrf_client_fingerprint() -> str:
    user_agent = request.headers.get("User-Agent", "")
    return sha256(user_agent.encode("utf-8")).hexdigest()[:32]


def _same_origin(candidate: str, expected: str) -> bool:
    try:
        candidate_parts = urlsplit(candidate)
        expected_parts = urlsplit(expected)
    except ValueError:
        return False
    if not candidate_parts.scheme or not candidate_parts.netloc:
        return False
    try:
        return (
            candidate_parts.scheme.lower(),
            candidate_parts.hostname.lower() if candidate_parts.hostname else "",
            _normalized_port(candidate_parts),
        ) == (
            expected_parts.scheme.lower(),
            expected_parts.hostname.lower() if expected_parts.hostname else "",
            _normalized_port(expected_parts),
        )
    except ValueError:
        return False


def _normalized_port(parts) -> int | None:
    if parts.port is not None:
        return parts.port
    if parts.scheme.lower() == "http":
        return 80
    if parts.scheme.lower() == "https":
        return 443
    return None


if __name__ == "__main__":
    raise SystemExit(main())
