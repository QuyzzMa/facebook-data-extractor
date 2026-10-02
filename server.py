"""Local web server.

Serves the static UI in ``web/`` and runs the extractor for a user-supplied URL.
The static site works on its own as a demo; this server adds the "run real data"
feature (needs a browser + a saved session, so it must run locally).

Run:   .\\.venv\\Scripts\\python.exe server.py
Open:  http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory

from main import ACCESS_NOTICE_MESSAGES
from src.cleaner import clean_commenters, clean_posts
from src.exporter import export_csv, export_xlsx
from src.parser import detect_access_issues, diagnose_html, parse_commenters, parse_posts
from src.reporter import generate_markdown_report
from src.scraper import get_html_sync

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
CONFIG_PATH = BASE_DIR / "config" / "config.json"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"

app = Flask(__name__, static_folder=None)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


class _JobHandler(logging.Handler):
    """Keeps the last log lines of a job so the UI can show live progress."""

    def __init__(self, job: dict) -> None:
        super().__init__()
        self._job = job

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._job["logs"].append(self.format(record))
            if len(self._job["logs"]) > 400:
                del self._job["logs"][:100]
        except Exception:
            pass


def _records_to_json(df: pd.DataFrame) -> tuple[list[str], list[dict]]:
    columns = [column for column in df.columns if column != "scraped_at_utc"]
    rows: list[dict] = []
    for _, row in df.iterrows():
        item = {}
        for column in columns:
            value = row[column]
            item[column] = "" if pd.isna(value) else str(value)
        rows.append(item)
    return columns, rows
def run_job(job_id: str, options: dict) -> None:
    job = JOBS[job_id]
    logger = logging.getLogger(__name__)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = _JobHandler(job)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
    root.addHandler(handler)
    try:
        config = load_config()
        url = options["url"]
        mode = options["extract_mode"]
        logger.info("Bắt đầu: %s (chế độ=%s)", url, mode)

        htmls = get_html_sync(
            url=url,
            max_scrolls=options["max_scrolls"],
            scroll_pause_seconds=config.get("scroll_pause_seconds", 2),
            max_scroll_seconds=options["max_scroll_seconds"],
            expand_comments=config.get("expand_comments", True),
            snapshot_every=config.get("snapshot_every", 0) if mode == "commenters" else 0,
            headless=config.get("headless", False),
            timeout_ms=config.get("timeout_ms", 30_000),
            session_enabled=config.get("session_enabled", True),
            session_dir=str(BASE_DIR / config.get("session_dir", "data/session/facebook")),
            raw_dir=str(BASE_DIR / "data" / "raw"),
            save_raw_html=config.get("save_raw_html", True),
            save_screenshot_on_error=config.get("save_screenshot_on_error", True),
            wait_for_login=False,
            login_mode=config.get("login_mode", "storage_state"),
            cdp_url=config.get("cdp_url", "http://localhost:9222"),
            cdp_autostart=config.get("cdp_autostart", False),
            chrome_profile_dir=str(BASE_DIR / config.get("chrome_profile_dir", "data/chrome-profile")),
            storage_state_path=str(
                BASE_DIR / config.get("storage_state_path", "data/session/facebook_state.json")
            ),
            save_storage_state=config.get("save_storage_state", True),
            use_real_chrome=config.get("use_real_chrome", False),
            browser_executable=config.get("browser_executable", ""),
        )

        final_html = htmls[-1] if htmls else ""
        if mode == "commenters":
            frames = [parse_commenters(page_html, url) for page_html in htmls]
            raw_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        else:
            raw_df = parse_posts(final_html, url)
        logger.info("Đã bóc tách %s bản ghi", len(raw_df))

        notices = [
            ACCESS_NOTICE_MESSAGES.get(code, code) for code in detect_access_issues(final_html)
        ]
        for notice in notices:
            logger.warning(notice)

        df = clean_commenters(raw_df) if mode == "commenters" else clean_posts(raw_df)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = config.get("output_prefix", "facebook_posts")
        csv_path = export_csv(df, OUTPUT_DIR / f"{prefix}_{stamp}.csv")
        xlsx_path = export_xlsx(df, OUTPUT_DIR / f"{prefix}_{stamp}.xlsx")
        report_path = generate_markdown_report(
            df,
            OUTPUT_DIR / f"{prefix}_{stamp}.md",
            source_url=url,
            csv_path=csv_path,
            xlsx_path=xlsx_path,
            notices=notices,
        )

        columns, rows = _records_to_json(df)
        job["result"] = {
            "mode": mode,
            "count": len(rows),
            "columns": columns,
            "rows": rows,
            "notices": notices,
            "diagnostics": diagnose_html(final_html),
            "files": {"csv": str(csv_path), "xlsx": str(xlsx_path), "md": str(report_path)},
        }
        job["state"] = "done"
        logger.info("Hoàn tất: %s dòng", len(rows))
    except Exception as exc:  # noqa: BLE001 - surface the error to the UI
        logger.exception("Lỗi khi chạy")
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["state"] = "error"
    finally:
        root.removeHandler(handler)
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:filename>")
def static_files(filename: str):
    return send_from_directory(WEB_DIR, filename)


@app.get("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "service": "facebook-data-extractor",
        "time": datetime.now(timezone.utc).isoformat(),
    })


@app.post("/api/run")
def api_run():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Thiếu URL."}), 400
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    mode = data.get("extract_mode") or "commenters"
    if mode not in {"posts", "commenters"}:
        mode = "commenters"
    try:
        max_scrolls = max(1, min(int(data.get("max_scrolls") or 40), 500))
        max_scroll_seconds = max(0, min(int(data.get("max_scroll_seconds") or 120), 1800))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Tham số cuộn không hợp lệ."}), 400

    options = {
        "url": url,
        "extract_mode": mode,
        "max_scrolls": max_scrolls,
        "max_scroll_seconds": max_scroll_seconds,
    }
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "state": "running",
            "logs": [],
            "result": None,
            "error": None,
            "created": datetime.now(timezone.utc).isoformat(),
        }
    threading.Thread(target=run_job, args=(job_id, options), daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/status/<job_id>")
def api_status(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"ok": False, "error": "Không tìm thấy job."}), 404
    return jsonify({
        "ok": True,
        "state": job["state"],
        "logs": job["logs"],
        "result": job["result"],
        "error": job["error"],
    })


if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Facebook Data Extractor - local server")
    print("  Mo: http://127.0.0.1:8000")
    app.run(host="127.0.0.1", port=8000, debug=False)
