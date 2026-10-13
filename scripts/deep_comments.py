"""Lay binh luan day du cua tung bai: mo tung bai (post_url trong file CSV bai dang moi nhat),
mo rong binh luan tren trang bai, roi xuat ra output/facebook_comments_<gio>.csv/.xlsx.

Chay tu thu muc du an:
  .\\.venv\\Scripts\\python.exe <duong dan toi file nay> --max-posts 2

Gioi han mac dinh nho, de thu truoc. Dung ngay khi gap trang dang nhap, kiem tra bao mat
hoac thong bao bi han che; script KHONG co cach vuot qua cac man hinh do."""
import argparse
import asyncio
import glob
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.getcwd())

import pandas as pd  # noqa: E402

STATE_FILE = Path("data/session/facebook_state.json")
OUTPUT_DIR = Path("output")

EXPAND_RE = re.compile(
    r"^(Xem thêm bình luận|Xem các bình luận trước|Xem thêm câu trả lời|Xem \d+ phản hồi|"
    r"Xem tất cả \d+ phản hồi|View more comments|View previous comments|View \d+ repl|"
    r"View all \d+ repl)",
    re.IGNORECASE,
)
SORT_RE = re.compile(r"^(Phù hợp nhất|Most relevant)", re.IGNORECASE)
ALL_COMMENTS_RE = re.compile(r"Tất cả bình luận|All comments", re.IGNORECASE)
BLOCK_PHRASES = (
    "tạm thời bị chặn", "bị hạn chế tạm thời", "temporarily blocked", "you're temporarily blocked",
    "bạn tạm thời không thể", "confirm your identity", "xác nhận danh tính",
)

COLLECT_JS = """
() => {
  const label = /^(Bình luận|Phản hồi|Comment|Reply)/i;
  const out = {};
  document.querySelectorAll('[role="article"]').forEach((node) => {
    const aria = node.getAttribute('aria-label') || '';
    if (!label.test(aria)) return;
    const clone = node.cloneNode(true);
    clone.querySelectorAll('[role="article"]').forEach((nested) => nested.remove());
    const text = (clone.textContent || '').replace(/\\s+/g, ' ').trim();
    const key = aria + '|' + text.slice(0, 120);
    if (!(key in out)) out[key] = clone.outerHTML;
  });
  return Object.values(out);
}
"""

DIAG_JS = """
() => {
  const arts = Array.from(document.querySelectorAll('[role="article"]'));
  const labels = {};
  arts.forEach((a) => {
    const k = (a.getAttribute('aria-label') || '-').slice(0, 10);
    labels[k] = (labels[k] || 0) + 1;
  });
  const buttons = {};
  Array.from(document.querySelectorAll('[role="button"], button')).forEach((b) => {
    const t = (b.getAttribute('aria-label') || b.textContent || '').trim();
    if (/bình luận|phản hồi|comment|repl/i.test(t)) {
      const k = t.slice(0, 14);
      buttons[k] = (buttons[k] || 0) + 1;
    }
  });
  return { articles: arts.length, labels: labels, buttons: buttons,
           video: document.querySelectorAll('video').length };
}
"""


def url_path(url):
    return url.split("?")[0].split("#")[0].rstrip("/")


PERMALINK_TOKENS = ("/posts/", "/reel/", "/videos/", "/permalink/", "story_fbid")


def post_key(url):
    """Ma dinh danh bai trong link (pfbid..., ma reel/video, fbid...) de kiem tra trang da mo dung bai."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for name in ("fbid", "v", "story_fbid"):
        if query.get(name):
            return query[name][0]
    segments = [seg for seg in parsed.path.split("/") if seg]
    return segments[-1] if segments else ""


def escape_attr(value):
    return str(value or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def load_post_urls(max_posts, include_photo=False):
    """Lay (thu_tu, post_url, source_url) tu file CSV bai dang moi nhat (co cot post_text)."""
    for path in sorted(glob.glob(str(OUTPUT_DIR / "facebook_posts_*.csv")), reverse=True):
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if "post_text" in df.columns and "post_url" in df.columns:
            rows = []
            for i, row in enumerate(df.itertuples(index=False), 1):
                url = getattr(row, "post_url", None)
                usable = isinstance(url, str) and url.startswith("http") and (
                    any(t in url for t in PERMALINK_TOKENS) or (include_photo and "/photo" in url)
                )
                if usable:
                    rows.append((i, url, getattr(row, "source_url", "") or ""))
            return path, rows[:max_posts]
    return None, []


def wrap_comments(post_index, post_url, htmls):
    return [
        '<div data-fx-post="%s" data-fx-post-url="%s">%s</div>'
        % (escape_attr(post_index), escape_attr(post_url), h)
        for h in htmls
    ]


async def blocked(page):
    if "checkpoint" in page.url or "/login" in page.url:
        return "trang dang nhap / kiem tra bao mat"
    try:
        if await page.locator('input[name="pass"]').count():
            return "form dang nhap"
        body = (await page.inner_text("body"))[:20000].lower()
    except Exception:
        return None
    for phrase in BLOCK_PHRASES:
        if phrase in body:
            return "thong bao: " + phrase
    return None


async def close_dialog(page):
    try:
        button = page.locator(
            'div[role="dialog"] [aria-label="Close"], div[role="dialog"] [aria-label="Đóng"]'
        ).first
        if await button.count() and await button.is_visible():
            await button.click(timeout=2000)
    except Exception:
        pass


async def choose_all_comments(page):
    try:
        sort = page.get_by_role("button", name=SORT_RE).first
        if await sort.count():
            await sort.click(timeout=2000)
            await page.wait_for_timeout(800)
            item = page.get_by_role("menuitem", name=ALL_COMMENTS_RE).first
            if await item.count():
                await item.click(timeout=2000)
                await page.wait_for_timeout(1500)
    except Exception:
        pass


async def expand_comments(page, seconds, max_comments, pause):
    """Mo rong binh luan; tra ve cac the thu duoc KHI CON O DUNG BAI (khong lay o trang khac)."""
    start_path = url_path(page.url)
    deadline = time.monotonic() + seconds
    cards = []
    idle_rounds = 0
    for _ in range(3):  # cuon nhe de binh luan duoc tai
        await page.mouse.wheel(0, 800)
        await page.wait_for_timeout(1000)
    while time.monotonic() < deadline:
        if url_path(page.url) != start_path:
            print("  trinh duyet roi khoi bai (dang o:", url_path(page.url)[-60:], "); bo phan sau do")
            try:
                await page.go_back(wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            break
        cards = await page.evaluate(COLLECT_JS)
        if len(cards) >= max_comments:
            break
        buttons = page.get_by_role("button", name=EXPAND_RE)
        n = await buttons.count()
        clicked = 0
        for i in range(min(n, 4)):
            try:
                await buttons.nth(i).click(timeout=1500)
                clicked += 1
                await page.wait_for_timeout(int(random.uniform(*pause) * 1000))
            except Exception:
                continue
        if not clicked:
            idle_rounds += 1
            await page.mouse.wheel(0, 700)
            await page.wait_for_timeout(1500)
            if idle_rounds >= 4:
                break
        else:
            idle_rounds = 0
    else:
        if url_path(page.url) == start_path:
            cards = await page.evaluate(COLLECT_JS)
    return cards


async def print_diag(page, tag):
    try:
        d = await page.evaluate(DIAG_JS)
        print(f"  [{tag}] url={url_path(page.url)[-70:]} | role=article:{d['articles']} | "
              f"nhan:{d['labels']} | nut:{d['buttons']} | video:{d['video']}")
    except Exception as exc:
        print(f"  [{tag}] khong doc duoc cau truc: {exc}")


async def run(args):
    from playwright.async_api import async_playwright

    from src.parser import parse_commenters
    from src.cleaner import clean_commenters
    from src.exporter import export_csv, export_xlsx

    source_file, posts = load_post_urls(args.max_posts, args.include_photo)
    if not posts:
        sys.exit("Khong thay file output/facebook_posts_*.csv nao co cot post_text va post_url hop le. "
                 "Hay chay main.py o che do posts truoc.")
    if not STATE_FILE.exists():
        sys.exit("Khong thay " + str(STATE_FILE) + ". Hay chay main.py mot lan de dang nhap.")
    print("Nguon bai:", source_file, "| se mo", len(posts), "bai")

    wrapped_all = []
    source_url = posts[0][2] or "https://www.facebook.com/"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            storage_state=str(STATE_FILE), viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()
        try:
            for number, (index, url, _src) in enumerate(posts, 1):
                print(f"[{number}/{len(posts)}] bai so {index} ...")
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(4000)
                reason = await blocked(page)
                if reason:
                    print("DUNG: gap", reason, "- hay tu xu ly tren trinh duyet roi chay lai sau.")
                    break
                key = post_key(url)
                if key and key not in page.url:
                    print("  BO QUA: khong mo duoc dung bai (dang o", url_path(page.url)[-60:] + ")")
                    if number < len(posts):
                        await page.wait_for_timeout(int(random.uniform(8, 15) * 1000))
                    continue
                await close_dialog(page)
                await print_diag(page, "truoc")
                await choose_all_comments(page)
                cards = await expand_comments(page, args.seconds, args.max_comments,
                                              (args.pause_min, args.pause_max))
                await print_diag(page, "sau")
                print("  binh luan thu duoc:", len(cards))
                if args.debug:
                    Path("data/raw").mkdir(parents=True, exist_ok=True)
                    stem = Path("data/raw") / f"deep_{datetime.now().strftime('%H%M%S')}_{index}"
                    try:
                        stem.with_suffix(".html").write_text(await page.content(), encoding="utf-8")
                        await page.screenshot(path=str(stem.with_suffix(".png")))
                    except Exception:
                        pass
                wrapped_all.extend(wrap_comments(index, url, cards))
                if number < len(posts):
                    await page.wait_for_timeout(int(random.uniform(8, 15) * 1000))
        finally:
            await browser.close()

    if not wrapped_all:
        print("Khong thu duoc binh luan nao.")
        return
    html = "<html><body>" + "\n".join(wrapped_all) + "</body></html>"
    raw = parse_commenters(html, source_url)
    df = clean_commenters(raw)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = export_csv(df, OUTPUT_DIR / f"facebook_comments_{stamp}.csv")
    xlsx_path = export_xlsx(df, OUTPUT_DIR / f"facebook_comments_{stamp}.xlsx")
    print("Da luu", len(df), "binh luan:", csv_path, "|", xlsx_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--max-posts", type=int, default=3, help="so bai toi da (mac dinh 3)")
    parser.add_argument("--max-comments", type=int, default=150, help="so binh luan toi da moi bai")
    parser.add_argument("--seconds", type=int, default=90, help="thoi gian toi da moi bai (giay)")
    parser.add_argument("--pause-min", type=float, default=2.0)
    parser.add_argument("--pause-max", type=float, default=4.0)
    parser.add_argument("--include-photo", action="store_true",
                        help="cho phep ca link anh (/photo); mac dinh chi link bai /posts/ /reel/ /videos/")
    parser.add_argument("--debug", action="store_true",
                        help="luu HTML + anh chup tung bai vao data/raw (chua ten nguoi dung)")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
