"""Flask web app for the AI data analyst."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from secrets import token_urlsafe
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, abort, render_template, request, send_from_directory, session, url_for

from ai_data_analyst.config import AnalysisConfig
from ai_data_analyst.exceptions import AnalysisError
from ai_data_analyst.workflow import analyze_csv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_MIN_CATEGORIES = 1
WEB_MAX_CATEGORIES = 50
WEB_DEFAULT_CATEGORIES = 10
WEB_MAX_CATEGORIES_DIGITS = 12


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
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.config["SECRET_KEY"] = os.getenv("AI_ANALYST_SECRET_KEY", "dev-only-secret")
    app.config["WEB_REPORTS_DIR"] = Path(
        os.getenv("AI_ANALYST_WEB_REPORTS_DIR", PROJECT_ROOT / "reports" / "web")
    ).expanduser().resolve()

    @app.get("/")
    def index() -> str:
        return _render_index()

    @app.post("/analyze")
    def analyze() -> str:
        if not _check_csrf():
            return _render_index(error="Invalid request origin or CSRF token."), 400

        uploaded = request.files.get("csv_file")
        form = _parse_analyze_form()

        if form.csv_text and uploaded and uploaded.filename:
            return _render_index(error="Please provide either a CSV file or pasted CSV text, not both."), 400

        if not form.csv_text and (not uploaded or not uploaded.filename):
            return _render_index(error="Please choose a CSV file or paste CSV text."), 400

        run_id = uuid.uuid4().hex[:12]
        run_dir = _run_dir(app, run_id)
        input_dir = run_dir / "_inputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        if form.csv_text:
            csv_path = input_dir / "pasted.csv"
            csv_path.write_text(form.csv_text, encoding="utf-8")
        else:
            csv_path = input_dir / _safe_filename(uploaded.filename or "")
            uploaded.save(csv_path)

        try:
            result = analyze_csv(
                csv_path,
                AnalysisConfig(
                    output_dir=run_dir,
                    target_column=form.target or None,
                    max_categories=form.max_categories,
                    use_llm=form.use_llm,
                    report_format=form.report_format,
                ),
            )
        except AnalysisError as exc:
            return _analysis_error_response(exc)
        except ValueError as exc:
            return _analysis_error_response(exc)

        preview = _build_preview(app, run_id, result)
        return _render_index(
            result=preview,
            defaults={
                **_defaults(),
                "last_target": form.target,
                "last_report_format": form.report_format,
                "last_use_llm": form.use_llm,
            },
        )

    @app.get("/runs/<run_id>/<path:filename>")
    def artifact(run_id: str, filename: str) -> Any:
        run_dir = _run_dir(app, run_id)
        if not run_dir.exists() or not _is_allowed_artifact(filename):
            abort(404)
        return send_from_directory(run_dir, filename, as_attachment=False)

    return app


def main() -> int:
    app = create_app()
    port = int(os.getenv("AI_ANALYST_PORT", "8000"))
    debug = os.getenv("AI_ANALYST_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=port, debug=debug)
    return 0


def _build_preview(app: Flask, run_id: str, result) -> dict[str, Any]:
    report_paths = {
        name: _artifact_url(app, run_id, result.output_dir, path)
        for name, path in result.report_paths.items()
    }
    summary_url = _artifact_url(app, run_id, result.output_dir, result.summary_path)
    charts = []
    for chart in result.charts:
        url = None
        if chart.get("rendered", True) and chart.get("path"):
            url = _artifact_url(app, run_id, result.output_dir, Path(chart["path"]))
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
    )


def _parse_analyze_form() -> AnalyzeForm:
    return AnalyzeForm(
        target=_clean_text(request.form.get("target")),
        use_llm=request.form.get("use_llm") == "on",
        report_format=_clean_text(request.form.get("report_format")) or "both",
        max_categories=web_max_categories(request.form.get("max_categories")),
        csv_text=_clean_text(request.form.get("csv_text")),
    )


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


def _artifact_url(app: Flask, run_id: str, output_dir: Path, path: Path) -> str:
    relative = Path(path).resolve().relative_to(output_dir.resolve()).as_posix()
    if not _is_allowed_artifact(relative):
        raise ValueError(f"Artifact is not web-accessible: {relative}")
    return url_for("artifact", run_id=run_id, filename=relative)


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


def _csrf_token() -> str:
    token = session.get("ai_analyst_csrf")
    if not token:
        token = token_urlsafe(24)
        session["ai_analyst_csrf"] = token
    return token


def _check_csrf() -> bool:
    origin = request.headers.get("Origin", "")
    referer = request.headers.get("Referer", "")
    host = request.host_url.rstrip("/")
    if origin and not _same_origin(origin, host):
        return False
    if referer and not _same_origin(referer, host):
        return False
    form_token = request.form.get("csrf_token", "")
    session_token = session.get("ai_analyst_csrf", "")
    if not session_token or not form_token:
        return False
    return session_token == form_token


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
