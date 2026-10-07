from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.scraper import get_html_sync
from src.parser import parse_posts, parse_commenters, diagnose_html, detect_access_issues
from src.cleaner import clean_posts, clean_commenters
from src.exporter import export_csv, export_xlsx
from src.reporter import generate_markdown_report

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "config.json"
LOG_DIR = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "output"


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8"),
        ],
    )


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_target_url(config: dict) -> str:
    """Prompt for a URL on every run; pressing Enter keeps the configured default."""
    default = (config.get("url") or "").strip()
    if not config.get("prompt_for_url", True):
        return default
    print()
    print("=" * 64)
    print("  NHAP URL TRANG FACEBOOK CAN LAY DU LIEU")
    if default:
        print(f"  (Nhan Enter de dung mac dinh: {default})")
    print("=" * 64)
    try:
        entered = input("URL: ").strip()
    except (EOFError, KeyboardInterrupt):
        entered = ""
        print()
    if not entered:
        entered = default
    if entered and not entered.lower().startswith(("http://", "https://")):
        entered = "https://" + entered
    return entered


ACCESS_NOTICE_MESSAGES = {
    "login": "Trang yeu cau DANG NHAP. Neu phien da het han, chay cookie.bat de dan cookie moi.",
    "join_group": "Trang yeu cau THAM GIA NHOM de xem noi dung. Hay tham gia nhom bang tai khoan cua ban roi chay lai.",
    "membership_pending": "Tu cach thanh vien dang CHO PHE DUYET. Hay doi duoc duyet roi chay lai.",
    "unavailable": "Noi dung HIEN KHONG KHA DUNG (co the da bi xoa hoac bi gioi han).",
    "age_restricted": "Noi dung bi GIOI HAN DO TUOI hoac theo khu vuc.",
    "rate_limited": "Tai khoan co the dang TAM BI HAN CHE. Hay thu lai sau.",
    "guest_view": "Facebook dang hien thi che do KHACH - can dang nhap de xem day du.",
}


def report_access_notices(html: str, logger: logging.Logger) -> list[str]:
    """Detect access restrictions and both log and print them for the user."""
    codes = detect_access_issues(html)
    messages = [ACCESS_NOTICE_MESSAGES.get(code, code) for code in codes]
    if messages:
        logger.warning("PHAT HIEN YEU CAU TRUY CAP:")
        for message in messages:
            logger.warning("  - %s", message)
        print()
        print("*** THONG BAO ***")
        for message in messages:
            print(f"  - {message}")
    return messages


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    config = load_config()

    url = resolve_target_url(config)
    if not url:
        raise RuntimeError("Chua co URL. Hay nhap URL hoac dat 'url' trong config/config.json.")
    extract_mode = config.get("extract_mode", "posts")
    logger.info("Starting Facebook extraction pipeline")
    logger.info("Opening URL: %s", url)

    htmls = get_html_sync(
        url=url,
        max_scrolls=config.get("max_scrolls", 40),
        scroll_pause_seconds=config.get("scroll_pause_seconds", 2),
        max_scroll_seconds=config.get("max_scroll_seconds", 0),
        expand_comments=config.get("expand_comments", config.get("extract_mode") == "commenters"),
        snapshot_every=config.get("snapshot_every", 0) if extract_mode == "commenters" else 0,
        headless=config.get("headless", False),
        timeout_ms=config.get("timeout_ms", 30_000),
        session_enabled=config.get("session_enabled", False),
        session_dir=str(BASE_DIR / config.get("session_dir", "data/session/facebook")),
        raw_dir=str(BASE_DIR / "data" / "raw"),
        save_raw_html=config.get("save_raw_html", True),
        save_screenshot_on_error=config.get("save_screenshot_on_error", True),
        wait_for_login=config.get("wait_for_login", True),
        login_mode=config.get("login_mode"),
        cdp_url=config.get("cdp_url", "http://localhost:9222"),
        cdp_autostart=config.get("cdp_autostart", False),
        chrome_profile_dir=str(BASE_DIR / config.get("chrome_profile_dir", "data/chrome-profile")),
        storage_state_path=str(
            BASE_DIR / config.get("storage_state_path", "data/session/facebook_state.json")
        ),
        save_storage_state=config.get("save_storage_state", False),
        use_real_chrome=config.get("use_real_chrome", False),
        browser_executable=config.get("browser_executable", ""),
    )

    final_html = htmls[-1] if htmls else ""
    if extract_mode == "commenters":
        frames = [parse_commenters(page_html, url) for page_html in htmls]
        raw_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    else:
        raw_df = parse_posts(final_html, url)
    logger.info("Extract mode: %s | parsed %s records", extract_mode, len(raw_df))

    notices = report_access_notices(final_html, logger)

    if raw_df.empty:
        logger.warning("No records were parsed. Inspect data/raw/*.html before changing selectors.")
        logger.warning("HTML diagnostics: %s", diagnose_html(final_html))
        if config.get("fail_on_zero_records", False):
            raise RuntimeError("Zero records parsed. See data/raw for the rendered HTML snapshot.")

    df = clean_commenters(raw_df) if extract_mode == "commenters" else clean_posts(raw_df)
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

    logger.info("CSV  : %s", csv_path)
    logger.info("XLSX : %s", xlsx_path)
    logger.info("MD   : %s", report_path)
    logger.info("Finished.")


if __name__ == "__main__":
    main()
