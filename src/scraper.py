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

# --- Virtualisation-proof story capture -------------------------------------
# Facebook removes stories from the DOM once they scroll far out of view, so the
# HTML read at the end of a run is missing most of what was seen. These settings
# drive small scroll steps that re-collect every top-level story card, keyed by
# the opening text of the card, and merge the unique cards before parsing.
ARTICLE_SELECTOR = '[role="article"]'
STORY_DEDUPE_PREFIX_CHARS = 200
SCROLL_STEP_PIXELS = 1000

COLLECT_STORIES_JS = """
() => {
  const prefixLength = %d;
  const normalise = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const articles = Array.from(document.querySelectorAll('[role="article"]'));
  const topLevel = articles.filter((node) => {
    const parent = node.parentElement;
    return !parent || !parent.closest('[role="article"]');
  });
  return topLevel.map((node) => {
    const clone = node.cloneNode(true);
    // Nested cards are the comment threads; their text must not leak into the
    // key of the post that contains them.
    clone.querySelectorAll('[role="article"]').forEach((nested) => nested.remove());
    const ownText = normalise(clone.textContent);
    const permalink = node.querySelector(
      'a[href*="/posts/"], a[href*="/reel/"], a[href*="/videos/"]'
    );
    const html = node.outerHTML;
    const key = (ownText.slice(0, prefixLength) || (permalink ? permalink.href : '')
      || normalise(html).slice(0, prefixLength)).toLowerCase();
    return { key: key, html: html, text_length: ownText.length };
  });
}
""" % STORY_DEDUPE_PREFIX_CHARS

MERGE_HEAD = (
    "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n</head>\n<body>\n"
)
MERGE_TAIL = "\n</body>\n</html>\n"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _merge_stories_html(stories: dict[str, dict]) -> str:
    """Join the captured story cards into one document for the parser."""
    parts = [story["html"] for story in stories.values() if story.get("html")]
    return MERGE_HEAD + "\n".join(parts) + MERGE_TAIL


async def _collect_stories(page) -> list[dict]:
    """Return the top-level story cards currently rendered in the page."""
    try:
        stories = await page.evaluate(COLLECT_STORIES_JS)
    except Exception:
        logger.debug("Could not collect story cards", exc_info=True)
        return []
    if not isinstance(stories, list):
        return []
    return [
        story
        for story in stories
        if isinstance(story, dict) and story.get("key") and story.get("html")
    ]


def _merge_into(collected: dict[str, dict], stories: list[dict]) -> int:
    """Store stories by key, keeping the newest copy of each. Returns new keys."""
    added = 0
    for story in stories:
        key = story["key"]
        if key not in collected:
            added += 1
        # Overwrite on purpose: a later capture of the same card usually carries
        # more expanded comments than the first one.
        collected[key] = story
    return added


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
        return await page.locator(ARTICLE_SELECTOR).count()
    except Exception:
        return 0


PROFILE_INDICATORS = (
    '[aria-label="Profile"]',
    '[aria-label="Tài khoản"]',
    '[data-testid="profile-popover"]',
    '[data-testid="fb://profile"]',
)
LOGIN_URL_TOKENS = ("/login", "checkpoint", "recover")
FEED_CONTENT_SELECTOR = '[data-ad-preview="message"], [role="article"]'

WAIT_FOR_LOGIN_JS = """
() => {
  const profileSelectors = %s;
  const url = window.location.href;
  const blocked = url.includes('/login') || url.includes('checkpoint') || url.includes('recover');
  for (const selector of profileSelectors) {
    if (document.querySelector(selector) && !blocked) {
      return true;
    }
  }
  return document.querySelectorAll('%s').length > 0;
}
""" % (
    "[" + ", ".join("'%s'" % selector for selector in PROFILE_INDICATORS) + "]",
    FEED_CONTENT_SELECTOR,
)


async def _is_logged_in(page) -> bool:
    """Check whether the current page shows a logged-in Facebook session."""
    try:
        if any(token in page.url for token in LOGIN_URL_TOKENS):
            return False
        for selector in PROFILE_INDICATORS:
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        try:
            return await page.locator(FEED_CONTENT_SELECTOR).count() > 0
        except Exception:
            return False
    except Exception:
        return False


async def _load_existing_context(browser, storage_state_path: str):
    """Load a browser context from an existing storage-state file, if any."""
    state_file = Path(storage_state_path)
    if not state_file.exists():
        return None
    try:
        context = await browser.new_context(storage_state=str(state_file))
        logger.info("Loaded existing session state from %s", state_file)
        return context
    except Exception as exc:
        logger.warning("Could not load session state from %s: %s", storage_state_path, exc)
        return None


def _resolve_login_mode(login_mode: str | None, session_enabled: bool) -> str:
    """Map configuration to one of: persistent | cdp | storage_state | anonymous."""
    if login_mode:
        mode = login_mode.strip().lower()
        if mode in {"persistent", "cdp", "storage_state", "anonymous"}:
            return mode
        logger.warning("Unknown login_mode %r; falling back automatically.", login_mode)
    return "persistent" if session_enabled else "anonymous"


async def _prompt_for_manual_login(browser, url: str) -> object:
    """Open a visible browser, let the user log in, and return that context.

    Credentials are never read, typed or stored by this code.
    """
    context = await browser.new_context()
    try:
        logger.info("Opening a browser window for manual Facebook login...")
        page = await context.new_page()
        await page.goto("https://www.facebook.com", wait_until="domcontentloaded")
        if await _is_logged_in(page):
            logger.info("Already logged in; reusing this session.")
            await page.close()
            return context
        if "login" not in page.url:
            await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
        logger.info("Complete the Facebook login in the browser window.")
        logger.info("The scraper continues automatically once the login is detected.")
        await page.wait_for_function(WAIT_FOR_LOGIN_JS, timeout=MANUAL_LOGIN_TIMEOUT_MS)
        logger.info("Facebook login detected; continuing.")
        await page.close()
        return context
    except Exception as exc:
        logger.error("Timed out waiting for the manual login: %s", exc)
        await context.close()
        raise RuntimeError("Manual login did not complete in time. Please run again.") from exc


async def _validate_session_state(context, url: str) -> bool:
    """Check that a saved session is still accepted by Facebook."""
    try:
        page = await context.new_page()
        target = url if url.startswith("https://www.facebook.com") else "https://www.facebook.com"
        await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
        await _close_dialog(page)
        is_logged_in = await _is_logged_in(page)
        await page.close()
        return is_logged_in
    except Exception as exc:
        logger.warning("Session validation failed: %s", exc)
        return False


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
    """Start a real Chromium browser with a debugging port and a dedicated profile.

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
    """Reduce the most common automation fingerprints in the given context."""
    try:
        await context.add_init_script(STEALTH_INIT_SCRIPT)
    except Exception:
        logger.debug("Could not apply the stealth init script", exc_info=True)


# --- Run tuning -------------------------------------------------------------
VIEWPORT = {"width": 1440, "height": 900}
INITIAL_SETTLE_MS = 4000
CLOSE_DIALOG_EVERY = 5
EXPAND_COMMENTS_EVERY = 4
SCROLL_MOUSE_X = 720
SCROLL_MOUSE_Y = 500
ARTICLE_WAIT_MS = 10_000
MANUAL_LOGIN_TIMEOUT_MS = 300_000


async def _open_owned_context(
    p,
    mode: str,
    headless: bool,
    channel: str | None,
    state_file: Path | None,
    session_path: Path,
    url: str,
):
    """Launch a browser owned by this run and return ``(browser, context, page)``.

    ``persistent`` returns ``browser=None`` because Playwright owns it through the
    persistent context. For ``storage_state`` the saved cookies are validated
    first: an expired or missing session triggers a visible re-login and the
    refreshed cookies are written back to ``state_file``.
    """
    storage_state = None
    if mode == "storage_state" and state_file is not None and state_file.exists():
        storage_state = str(state_file)
        logger.info("Reusing saved session state: %s", state_file)

    if mode == "persistent":
        logger.info("Using persistent browser session: %s", session_path)
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(session_path.resolve()),
            headless=headless,
            channel=channel,
            args=LAUNCH_ARGS,
            viewport=VIEWPORT,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        return None, context, page

    browser = await p.chromium.launch(headless=headless, channel=channel, args=LAUNCH_ARGS)
    context = await browser.new_context(viewport=VIEWPORT, storage_state=storage_state)
    page = context.pages[0] if context.pages else await context.new_page()

    if mode != "storage_state":
        return browser, context, page

    has_state = state_file is not None and state_file.exists()
    if has_state and await _validate_session_state(context, url):
        logger.info("Saved session state is valid.")
        return browser, context, page

    if headless:
        raise RuntimeError(
            "The saved session is missing or expired and headless=true cannot log in. "
            "Run again with headless=false, or refresh the session with cookie.bat."
        )

    logger.warning("The saved session is missing or expired; a manual login is required.")
    await context.close()
    await browser.close()

    browser = await p.chromium.launch(headless=False, channel=channel, args=LAUNCH_ARGS)
    context = await _prompt_for_manual_login(browser, url)
    if state_file is not None:
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(state_file))
            logger.info("Saved the refreshed session state: %s", state_file)
        except Exception:
            logger.exception("Could not save the refreshed session state")
    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


def _on_target(current: str, target: str) -> bool:
    """True neu trinh duyet van o trang dich (hoac mot bai viet cua trang do)."""
    from urllib.parse import urlparse

    cur, tgt = urlparse(current), urlparse(target)
    tpath = tgt.path.rstrip("/")
    if not tpath:
        return True
    cpath = cur.path.rstrip("/")
    return cur.netloc == tgt.netloc and (cpath == tpath or cpath.startswith(tpath + "/"))


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
    """Open a Facebook URL and return the captured HTML documents.

    Login strategies (``login_mode``):

    * ``persistent``    - reuse a Playwright profile under ``session_dir``.
    * ``cdp``           - attach to a real Chrome you already use (``cdp_url``);
      optionally auto-start Chrome via ``cdp_autostart`` + ``chrome_profile_dir``.
    * ``storage_state`` - import cookies/localStorage from ``storage_state_path``.
    * ``anonymous``     - a fresh context with no saved session.

    Facebook removes story cards from the DOM once they leave the viewport
    (virtualisation), so the page is sampled in small steps of
    :data:`SCROLL_STEP_PIXELS` and every top-level ``[role="article"]`` card is
    captured, de-duplicated by the opening :data:`STORY_DEDUPE_PREFIX_CHARS`
    characters of that card's own text, and merged. The merged document is the
    **last** element of the returned list, so the parser sees every story that was
    on screen at any point during the run.

    Credentials are never read, typed or stored by this code.
    """
    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    session_path = Path(session_dir)
    session_path.mkdir(parents=True, exist_ok=True)
    pause_ms = max(int(scroll_pause_seconds * 1000), 0)

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
                context = (
                    browser.contexts[0] if browser.contexts else await browser.new_context()
                )
                # A dedicated tab that shares the existing logged-in cookies.
                page = await context.new_page()
                owns_page = True
            else:
                browser, context, page = await _open_owned_context(
                    p, mode, headless, channel, state_file, session_path, url
                )
                owns_browser = True

            await _apply_stealth(context)
            page.set_default_timeout(timeout_ms)

            logger.info("Opening URL: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(INITIAL_SETTLE_MS)

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
                    await page.wait_for_timeout(INITIAL_SETTLE_MS)
                else:
                    logger.warning(
                        "Facebook is showing a login form; posts are probably not available. "
                        "Run with headless=false and wait_for_login=true to log in once."
                    )

            await _close_dialog(page)
            try:
                await page.wait_for_selector(ARTICLE_SELECTOR, timeout=ARTICLE_WAIT_MS)
            except Exception:
                logger.warning(
                    "No [role=article] elements appeared within %ss (%s found).",
                    ARTICLE_WAIT_MS // 1000,
                    await _count_articles(page),
                )

            snapshots: list[str] = []
            collected: dict[str, dict] = {}
            await page.mouse.move(SCROLL_MOUSE_X, SCROLL_MOUSE_Y)
            started = time.monotonic()
            for index in range(max_scrolls):
                await page.mouse.wheel(0, SCROLL_STEP_PIXELS)
                await page.wait_for_timeout(pause_ms)
                if index % CLOSE_DIALOG_EVERY == 0:
                    await _close_dialog(page)
                if expand_comments and index % EXPAND_COMMENTS_EVERY == 0:
                    await _expand_comment_threads(page, rounds=1, limit=6)

                if not _on_target(page.url, url):
                    logger.warning(
                        "Trinh duyet roi khoi trang dich (dang o %s); quay lai va bo qua luot nay.",
                        page.url[:90],
                    )
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                        await page.wait_for_timeout(INITIAL_SETTLE_MS)
                    except Exception:
                        logger.exception("Khong quay lai duoc trang dich")
                    continue
                stories = await _collect_stories(page)
                added = _merge_into(collected, stories)
                logger.info(
                    "Scroll %s/%s | cards on page: %s | unique stories collected: %s (+%s)",
                    index + 1,
                    max_scrolls,
                    len(stories),
                    len(collected),
                    added,
                )
                try:
                    diag = await page.evaluate(
                        "() => ({y: Math.round(window.scrollY), "
                        "h: document.documentElement.scrollHeight, "
                        "d: document.querySelectorAll('[role=\"dialog\"]').length})"
                    )
                    logger.info(
                        "  diag | scrollY=%s scrollHeight=%s dialogs=%s url=%s",
                        diag["y"], diag["h"], diag["d"], page.url[:90],
                    )
                except Exception:
                    pass

                if snapshot_every and (index + 1) % snapshot_every == 0:
                    snapshots.append(await page.content())
                if max_scroll_seconds and (time.monotonic() - started) >= max_scroll_seconds:
                    logger.info("Scroll time budget of %ss reached; stopping.", max_scroll_seconds)
                    break

            if expand_comments:
                await _expand_comment_threads(page)
            await _expand_see_more(page)
            added = _merge_into(collected, await _collect_stories(page))
            logger.info("Final sweep | unique stories collected: %s (+%s)", len(collected), added)

            html = await page.content()
            snapshots.append(html)
            if collected:
                snapshots.append(_merge_stories_html(collected))

            if save_raw_html:
                stamp = _timestamp()
                raw_file = raw_path / f"facebook_page_{stamp}.html"
                raw_file.write_text(html, encoding="utf-8")
                logger.info("Saved raw HTML: %s", raw_file)
                if collected:
                    stories_file = raw_path / f"facebook_stories_{stamp}.html"
                    stories_file.write_text(_merge_stories_html(collected), encoding="utf-8")
                    logger.info(
                        "Saved %s merged story cards: %s", len(collected), stories_file
                    )
                try:
                    shot = raw_path / f"facebook_page_{stamp}.png"
                    await page.screenshot(path=str(shot), full_page=False)
                    logger.info("Saved screenshot: %s", shot)
                except Exception:
                    logger.exception("Could not save the screenshot")

            if save_storage_state and state_file is not None:
                try:
                    state_file.parent.mkdir(parents=True, exist_ok=True)
                    await context.storage_state(path=str(state_file))
                    logger.info("Saved session state: %s", state_file)
                except Exception:
                    logger.exception("Could not save the session state")

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
                    logger.exception("Could not save the error screenshot")
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
