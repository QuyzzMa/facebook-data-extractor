from __future__ import annotations

import asyncio
import logging
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

LOGIN_FORM_SELECTOR = 'input[name="pass"], form[action*="login"], [data-testid="royal_login_form"]'
CLOSE_DIALOG_SELECTOR = (
    'div[role="dialog"] [aria-label="Close"], div[role="dialog"] [aria-label="Đóng"]'
)
SEE_MORE_RE = re.compile(r"^(See more|Xem thêm)$", re.IGNORECASE)
COMMENT_MORE_RE = re.compile(
    r"Xem thêm bình luận|Xem các bình luận khác|Xem thêm trả lời|Xem các câu trả lời|"
    r"View more comments|View more replies|View \d+ more",
    re.IGNORECASE,
)

CHROME_CHANNEL = "chrome"
DEFAULT_CDP_URL = "http://localhost:9222"
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


async def _has_login_form(page) -> bool:
    if any(token in page.url for token in ("/login", "checkpoint")):
        return True
    try:
        return await page.locator(LOGIN_FORM_SELECTOR).count() > 0
    except Exception:
        return False


async def _close_dialog(page) -> None:
    """Close a dismissible pop-up (e.g. 'See more on Facebook') if one is shown."""
    try:
        button = page.locator(CLOSE_DIALOG_SELECTOR).first
        if await button.count() and await button.is_visible():
            await button.click(timeout=2000)
            await page.wait_for_timeout(800)
            logger.info("Closed a pop-up dialog")
    except Exception:
        pass


async def _expand_see_more(page, limit: int = 40) -> None:
    try:
        buttons = await page.get_by_role("button", name=SEE_MORE_RE).all()
        for button in buttons[:limit]:
            try:
                await button.click(timeout=500)
            except Exception:
                continue
    except Exception:
        pass


async def _expand_comment_threads(page, rounds: int = 3, limit: int = 15) -> None:
    """Click 'view more comments/replies' controls so more commenters load."""
    for _ in range(rounds):
        clicked = 0
        try:
            buttons = page.get_by_role("button", name=COMMENT_MORE_RE)
            count = await buttons.count()
            for index in range(min(count, limit)):
                try:
                    await buttons.nth(index).click(timeout=800)
                    clicked += 1
                except Exception:
                    continue
        except Exception:
            pass
        if clicked == 0:
            break
        await page.wait_for_timeout(1200)


async def _count_articles(page) -> int:
    try:
        return await page.locator('[role="article"]').count()
    except Exception:
        return 0


def _resolve_login_mode(login_mode: str | None, session_enabled: bool) -> str:
    """Map configuration to one of: persistent | cdp | storage_state | anonymous."""
    if login_mode:
        mode = login_mode.strip().lower()
        if mode in {"persistent", "cdp", "storage_state", "anonymous"}:
            return mode
        logger.warning("Unknown login_mode %r; falling back automatically.", login_mode)
    return "persistent" if session_enabled else "anonymous"


def _find_chrome_executable() -> str | None:
    """Locate a Chromium-based browser (Chrome, Edge or Coc Coc) for CDP autostart."""
    import os

    candidates = [
        os.environ.get("BROWSER_PATH"),
        os.environ.get("CHROME_PATH"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\CocCoc\Browser\Application\browser.exe",
        r"C:\Program Files (x86)\CocCoc\Browser\Application\browser.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\Application\browser.exe"),
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        )
        value, _ = winreg.QueryValueEx(key, None)
        if value and Path(value).exists():
            return value
    except Exception:
        pass
    return None


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _cdp_reachable(cdp_url: str) -> bool:
    parsed = urlparse(cdp_url)
    return _port_open(parsed.hostname or "localhost", parsed.port or 9222)


def _launch_debug_chrome(
    cdp_url: str, profile_dir: str, url: str, executable: str | None = None
) -> None:
    """Start a real Chromium browser with a debugging port + a dedicated profile.

    Log in once in that window; the profile keeps the session for later runs.
    """
    parsed = urlparse(cdp_url)
    port = parsed.port or 9222
    chrome = executable or _find_chrome_executable()
    if not chrome:
        raise RuntimeError(
            "No browser was found. Install Chrome or Edge, set browser_executable, or "
            f"start your browser yourself with --remote-debugging-port={port}."
        )
    profile = Path(profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        url,
    ]
    logger.info("Launching browser for CDP on port %s (profile: %s)", port, profile)
    subprocess.Popen(args)


async def _connect_cdp(p, cdp_url: str, timeout_ms: int):
    """Connect to a running Chrome, retrying until the debug port is ready."""
    deadline = time.monotonic() + max(timeout_ms / 1000, 30)
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return await p.chromium.connect_over_cdp(cdp_url, timeout=5000)
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError(
        f"Could not connect to Chrome at {cdp_url}. Start Chrome with "
        f"--remote-debugging-port=9222 or set cdp_autostart=true. Last error: {last_error}"
    )


async def _apply_stealth(context) -> None:
    """Reduce common automation fingerprints for the given browser context."""
    try:
        await context.add_init_script(STEALTH_INIT_SCRIPT)
    except Exception:
        logger.debug("Could not apply stealth init script", exc_info=True)


async def fetch_rendered_html(
    url: str,
    max_scrolls: int = 40,
    scroll_pause_seconds: float = 2,
    max_scroll_seconds: int = 0,
    expand_comments: bool = True,
    snapshot_every: int = 0,
    headless: bool = False,
    timeout_ms: int = 30_000,
    session_enabled: bool = False,
    session_dir: str = "data/session/facebook",
    raw_dir: str = "data/raw",
    save_raw_html: bool = True,
    save_screenshot_on_error: bool = True,
    wait_for_login: bool = True,
    login_mode: str | None = None,
    cdp_url: str = DEFAULT_CDP_URL,
    cdp_autostart: bool = False,
    chrome_profile_dir: str = "data/chrome-profile",
    storage_state_path: str | None = None,
    save_storage_state: bool = False,
    use_real_chrome: bool = False,
    browser_executable: str = "",
) -> list[str]:
    """Open a Facebook URL and return the rendered HTML.

    Login strategies (``login_mode``):

    * ``persistent``    - reuse a Playwright profile under ``session_dir``.
    * ``cdp``           - attach to a real Chrome you already use (``cdp_url``);
      optionally auto-start Chrome via ``cdp_autostart`` + ``chrome_profile_dir``.
    * ``storage_state`` - import cookies/localStorage from ``storage_state_path``.
    * ``anonymous``     - a fresh context with no saved session.

    If a login form is detected and the browser is visible, the script pauses so
    you can log in yourself. Credentials are never read or stored by this code.
    """
    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    session_path = Path(session_dir)
    session_path.mkdir(parents=True, exist_ok=True)

    mode = _resolve_login_mode(login_mode, session_enabled)
    channel = CHROME_CHANNEL if use_real_chrome else None
    state_file = Path(storage_state_path) if storage_state_path else None
    logger.info("Login mode: %s | channel: %s", mode, channel or "bundled chromium")

    async with async_playwright() as p:
        browser = None
        context = None
        page = None
        owns_browser = False
        owns_page = False
        try:
            if mode == "cdp":
                if cdp_autostart and not _cdp_reachable(cdp_url):
                    _launch_debug_chrome(
                        cdp_url, chrome_profile_dir, url, browser_executable or None
                    )
                logger.info("Connecting to Chrome over CDP: %s", cdp_url)
                browser = await _connect_cdp(p, cdp_url, timeout_ms)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                # Open a dedicated tab that shares the existing login cookies.
                page = await context.new_page()
                owns_page = True
            else:
                storage_state = None
                if mode == "storage_state" and state_file and state_file.exists():
                    storage_state = str(state_file)
                    logger.info("Reusing saved session state: %s", state_file)
                if mode == "persistent":
                    logger.info("Using persistent browser session: %s", session_path)
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=str(session_path.resolve()),
                        headless=headless,
                        channel=channel,
                        args=LAUNCH_ARGS,
                        viewport={"width": 1440, "height": 900},
                    )
                else:
                    browser = await p.chromium.launch(
                        headless=headless, channel=channel, args=LAUNCH_ARGS
                    )
                    context = await browser.new_context(
                        viewport={"width": 1440, "height": 900},
                        storage_state=storage_state,
                    )
                owns_browser = True
                page = context.pages[0] if context.pages else await context.new_page()

            await _apply_stealth(context)
            page.set_default_timeout(timeout_ms)

            logger.info("Opening URL: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(4000)

            if await _has_login_form(page):
                if wait_for_login and not headless:
                    logger.warning("Facebook is showing a login form.")
                    print(
                        "\n>>> Log in to Facebook in the browser window (your own account).\n"
                        ">>> When you can see the page's posts, come back here and press Enter.\n"
                        ">>> (Press Enter without logging in to continue anonymously.)\n",
                        flush=True,
                    )
                    await asyncio.to_thread(input, "Press Enter to continue... ")
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await page.wait_for_timeout(4000)
                else:
                    logger.warning(
                        "Facebook is showing a login form; posts are probably not available. "
                        "Run with headless=false and session_enabled=true to log in once."
                    )

            await _close_dialog(page)

            try:
                await page.wait_for_selector('[role="article"]', timeout=10_000)
            except Exception:
                logger.warning("No [role=article] elements appeared after 10 seconds")

            snapshots: list[str] = []
            await page.mouse.move(720, 500)
            started = time.monotonic()
            for index in range(max_scrolls):
                await page.keyboard.press("End")
                await page.mouse.wheel(0, 6000)
                await page.wait_for_timeout(int(scroll_pause_seconds * 1000))
                if index % 5 == 0:
                    await _close_dialog(page)
                logger.info("Scroll %s/%s", index + 1, max_scrolls)
                if expand_comments and index % 4 == 0:
                    await _expand_comment_threads(page, rounds=1, limit=6)
                if snapshot_every and (index + 1) % snapshot_every == 0:
                    snapshots.append(await page.content())
                if max_scroll_seconds and (time.monotonic() - started) >= max_scroll_seconds:
                    logger.info("Scroll time budget of %ss reached; stopping.", max_scroll_seconds)
                    break

            if expand_comments:
                await _expand_comment_threads(page)
            await _expand_see_more(page)
            html = await page.content()
            snapshots.append(html)

            if save_raw_html:
                stamp = _timestamp()
                raw_file = raw_path / f"facebook_page_{stamp}.html"
                raw_file.write_text(html, encoding="utf-8")
                logger.info("Saved raw HTML: %s", raw_file)
                try:
                    shot = raw_path / f"facebook_page_{stamp}.png"
                    await page.screenshot(path=str(shot), full_page=False)
                    logger.info("Saved screenshot: %s", shot)
                except Exception:
                    logger.exception("Could not save screenshot")

            if save_storage_state and state_file is not None:
                try:
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    await context.storage_state(path=str(state_file))
                    logger.info("Saved session state: %s", state_file)
                except Exception:
                    logger.exception("Could not save session state")

            return snapshots
        except Exception:
            if save_screenshot_on_error and context is not None:
                try:
                    pages = context.pages
                    if pages:
                        screenshot = raw_path / f"facebook_error_{_timestamp()}.png"
                        await pages[0].screenshot(path=str(screenshot), full_page=False)
                        logger.info("Saved error screenshot: %s", screenshot)
                except Exception:
                    logger.exception("Could not save error screenshot")
            raise
        finally:
            if owns_browser:
                if context is not None:
                    await context.close()
                if browser is not None:
                    await browser.close()
            elif owns_page and page is not None:
                try:
                    await page.close()
                except Exception:
                    pass


def get_html_sync(**kwargs) -> list[str]:
    return asyncio.run(fetch_rendered_html(**kwargs))
