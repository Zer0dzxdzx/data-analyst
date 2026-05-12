"""Flask web app for the AI data analyst."""

from __future__ import annotations

import os
import uuid
from secrets import token_urlsafe
from pathlib import Path
from typing import Any

from flask import Flask, abort, render_template, request, send_from_directory, session, url_for

from ai_data_analyst.config import AnalysisConfig
from ai_data_analyst.exceptions import AnalysisError
from ai_data_analyst.workflow import analyze_csv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        return render_template("index.html", result=None, error=None, defaults=_defaults(), csrf_token=_csrf_token())

    @app.post("/analyze")
    def analyze() -> str:
        if not _check_csrf():
            return render_template(
                "index.html",
                result=None,
                error="Invalid request origin or CSRF token.",
                defaults=_defaults(),
                csrf_token=_csrf_token(),
            ), 400

        uploaded = request.files.get("csv_file")
        target = _clean_text(request.form.get("target"))
        use_llm = request.form.get("use_llm") == "on"
        report_format = request.form.get("report_format", "both")
        max_categories = _int_or_default(request.form.get("max_categories"), 10)
        csv_text = _clean_text(request.form.get("csv_text"))

        if csv_text and uploaded and uploaded.filename:
            return render_template(
                "index.html",
                result=None,
                error="Please provide either a CSV file or pasted CSV text, not both.",
                defaults=_defaults(),
                csrf_token=_csrf_token(),
            ), 400

        if not csv_text and (not uploaded or not uploaded.filename):
            return render_template(
                "index.html",
                result=None,
                error="Please choose a CSV file or paste CSV text.",
                defaults=_defaults(),
                csrf_token=_csrf_token(),
            ), 400

        run_id = uuid.uuid4().hex[:12]
        run_dir = _run_dir(app, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        if csv_text:
            csv_path = run_dir / "pasted.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
        else:
            csv_path = run_dir / _safe_filename(uploaded.filename or "")
            uploaded.save(csv_path)

        try:
            result = analyze_csv(
                csv_path,
                AnalysisConfig(
                    output_dir=run_dir,
                    target_column=target or None,
                    max_categories=max_categories,
                    use_llm=use_llm,
                    report_format=report_format,
                ),
            )
        except AnalysisError as exc:
            return render_template("index.html", result=None, error=str(exc), defaults=_defaults(), csrf_token=_csrf_token()), 400
        except ValueError as exc:
            return render_template("index.html", result=None, error=str(exc), defaults=_defaults(), csrf_token=_csrf_token()), 400

        preview = _build_preview(app, run_id, result)
        return render_template(
            "index.html",
            result=preview,
            error=None,
            defaults={
                **_defaults(),
                "last_target": target,
                "last_report_format": report_format,
                "last_use_llm": use_llm,
            },
            csrf_token=_csrf_token(),
        )

    @app.get("/runs/<run_id>/<path:filename>")
    def artifact(run_id: str, filename: str) -> Any:
        run_dir = _run_dir(app, run_id)
        if not run_dir.exists():
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
    charts = [
        {
            "title": chart.get("title"),
            "url": _artifact_url(app, run_id, result.output_dir, Path(chart["path"])),
            "rendered": chart.get("rendered", True),
        }
        for chart in result.charts
    ]
    return {
        "run_id": run_id,
        "output_dir": str(result.output_dir),
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


def _run_dir(app: Flask, run_id: str) -> Path:
    return Path(app.config["WEB_REPORTS_DIR"]) / run_id


def _artifact_url(app: Flask, run_id: str, output_dir: Path, path: Path) -> str:
    relative = Path(path).resolve().relative_to(output_dir.resolve()).as_posix()
    return url_for("artifact", run_id=run_id, filename=relative)


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
    if origin and not origin.startswith(host):
        return False
    if referer and not referer.startswith(host):
        return False
    form_token = request.form.get("csrf_token", "")
    session_token = session.get("ai_analyst_csrf", "")
    if not session_token or not form_token:
        return False
    return session_token == form_token


if __name__ == "__main__":
    raise SystemExit(main())
