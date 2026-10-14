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


def parse_count(value):
    """'46', 46.0, '1,2K', '3 binh luan' -> so nguyen; khong doc duoc -> None."""
    import math

    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([km])?", text)
    if not m:
        return None
    raw, suffix = m.group(1), m.group(2)
    if not suffix and re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        return int(re.sub(r"[.,]", "", raw))  # 1.234 = 1234
    number = float(raw.replace(",", "."))
    return int(number * {"k": 1000, "m": 1000000}.get(suffix, 1))


def permalink_from_id(post_id, source_url):
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(source_url or "")
    if not parsed.netloc:
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    segments = [seg for seg in parsed.path.split("/") if seg]
    if segments and segments[0] != "profile.php":
        return f"{origin}/{segments[0]}/posts/{post_id}"
    page_id = parse_qs(parsed.query).get("id")
    if page_id:
        return f"{origin}/permalink.php?story_fbid={post_id}&id={page_id[0]}"
    return None


def candidate(url, source_url, include_photo=False):
    """(loai, link_de_mo) hoac None. set=pcb (bai nhieu anh) -> dung lai link bai tu ma bai."""
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    if any(t in url for t in PERMALINK_TOKENS):
        return "permalink", url
    if "/photo" in url:
        m = re.search(r"[?&]set=pcb\.(\d+)", url)
        if m:
            link = permalink_from_id(m.group(1), source_url)
            return ("pcb->posts", link) if link else None
        if re.search(r"[?&]set=a\.", url) or include_photo:
            return "photo", url
    return None


def opened_ok(requested, current, kind):
    """Trang vua tai co dung la bai can mo khong? Duong dan trong = trang chu = sai."""
    from urllib.parse import parse_qs, urlparse

    cur, req = urlparse(current), urlparse(requested)
    path = cur.path.strip("/")
    if not path:
        return False
    if kind == "photo":
        fbid = parse_qs(req.query).get("fbid")
        return "photo" in path and (not fbid or parse_qs(cur.query).get("fbid") == fbid)
    if kind == "pcb->posts":
        req_parts = [seg for seg in req.path.split("/") if seg]
        cur_parts = [seg for seg in cur.path.split("/") if seg]
        if req_parts and req_parts[0] != "permalink.php":
            same_page = bool(cur_parts) and cur_parts[0] == req_parts[0]
            return same_page and any(t in "/" + path for t in ("/posts/", "/videos/", "/reel/"))
        return "permalink" in path
    key = post_key(requested)
    return (not key) or key in current


def load_posts(args):
    """Doc file bai dang moi nhat va chon bai co the mo duoc. Tra ve (file, bai, thong_ke)."""
    chosen = None
    for path in sorted(glob.glob(str(OUTPUT_DIR / "facebook_posts_*.csv")), reverse=True):
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if "post_text" in df.columns and "post_url" in df.columns:
            chosen = (path, df)
            break
    if chosen is None:
        return None, [], {}
    path, df = chosen
    rows, stats = [], {}

    def count(name):
        stats[name] = stats.get(name, 0) + 1

    for i, row in enumerate(df.itertuples(index=False), 1):
        source = getattr(row, "source_url", "") or ""
        expected = parse_count(getattr(row, "comments_text", None))
        found = candidate(getattr(row, "post_url", None), source, args.include_photo)
        if found is None:
            count("bo qua: khong co link dung duoc")
            continue
        if (expected or 0) < args.min_comments:
            count("bo qua: it binh luan")
            continue
        kind, link = found
        count(kind)
        rows.append({"index": i, "url": link, "kind": kind, "expected": expected, "source": source})
    if args.most_commented:
        rows.sort(key=lambda r: -(r["expected"] or 0))
    return path, rows[: args.max_posts], stats


def attach_post_index(df, posts):
    """clean_commenters chi giu cot co dinh va bo post_index: gan lai theo post_url (link da mo)."""
    if "post_index" in df.columns or "post_url" not in df.columns:
        return df
    index_by_url = {p["url"]: p["index"] for p in posts}
    df = df.copy()
    df.insert(min(2, len(df.columns)), "post_index", df["post_url"].map(index_by_url))
    return df


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


async def expand_comments(page, seconds, max_comments, pause, ok_fn):
    """Mo rong binh luan; chi lay the khi trang dang mo DUNG la bai can mo (ok_fn kiem tra moi vong)."""
    deadline = time.monotonic() + seconds
    cards = []
    idle_rounds = 0
    for _ in range(3):  # cuon nhe de binh luan duoc tai
        await page.mouse.wheel(0, 800)
        await page.wait_for_timeout(1000)
    while time.monotonic() < deadline:
        if not ok_fn():
            print("  trang khong con la bai can mo (dang o:", url_path(page.url)[-60:] + ") -",
                  "giu phan thu duoc truoc do" if cards else "khong thu thap gi")
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
        if ok_fn():
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

    source_file, posts, stats = load_posts(args)
    if source_file is None:
        sys.exit("Khong thay file output/facebook_posts_*.csv nao co cot post_text va post_url. "
                 "Hay chay main.py o che do posts truoc.")
    print("Nguon bai:", source_file)
    print("Phan loai:", stats)
    if not posts:
        sys.exit("Khong co bai nao mo duoc theo bo loc hien tai (xem 'Phan loai' o tren; "
                 "thu --min-comments 0 hoac --include-photo).")
    if not STATE_FILE.exists():
        sys.exit("Khong thay " + str(STATE_FILE) + ". Hay chay main.py mot lan de dang nhap.")
    print("Se mo", len(posts), "bai")

    wrapped_all = []
    source_url = posts[0]["source"] or "https://www.facebook.com/"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            storage_state=str(STATE_FILE), viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()
        pcb_broken = False
        try:
            for number, post in enumerate(posts, 1):
                index, url, kind, expected = post["index"], post["url"], post["kind"], post["expected"]
                print(f"[{number}/{len(posts)}] bai so {index} ({kind}; file bai ghi "
                      f"{expected if expected is not None else '?'} binh luan) ...")
                if kind == "pcb->posts" and pcb_broken:
                    print("  BO QUA: link pcb->posts khong mo duoc bai o lan truoc")
                    continue
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(4000)
                reason = await blocked(page)
                if reason:
                    print("DUNG: gap", reason, "- hay tu xu ly tren trinh duyet roi chay lai sau.")
                    break
                if not opened_ok(url, page.url, kind):
                    print("  BO QUA: khong mo duoc dung bai (dang o", url_path(page.url)[-60:] + ")")
                    if kind == "pcb->posts":
                        pcb_broken = True
                    if number < len(posts):
                        await page.wait_for_timeout(int(random.uniform(8, 15) * 1000))
                    continue
                await close_dialog(page)
                await print_diag(page, "truoc")
                await choose_all_comments(page)
                ok_fn = lambda: opened_ok(url, page.url, kind)  # noqa: E731
                cards = await expand_comments(page, args.seconds, args.max_comments,
                                              (args.pause_min, args.pause_max), ok_fn)
                await print_diag(page, "sau")
                if not cards and not ok_fn():
                    print("  BO QUA: trang bi chuyen di (dang o", url_path(page.url)[-60:] + "); khong thu thap gi")
                    if kind == "pcb->posts":
                        pcb_broken = True
                    if number < len(posts):
                        await page.wait_for_timeout(int(random.uniform(8, 15) * 1000))
                    continue
                print("  binh luan thu duoc:", len(cards))
                if not cards and expected:
                    print(f"  CANH BAO: file bai ghi {expected} binh luan nhung thu duoc 0 "
                          "(link nay co the khong hien binh luan cua bai)")
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
    df = attach_post_index(df, posts)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = export_csv(df, OUTPUT_DIR / f"facebook_comments_{stamp}.csv")
    xlsx_path = export_xlsx(df, OUTPUT_DIR / f"facebook_comments_{stamp}.xlsx")
    print("Da luu", len(df), "binh luan:", csv_path, "|", xlsx_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--max-posts", type=int, default=3, help="so bai toi da (mac dinh 3)")
    parser.add_argument("--min-comments", type=int, default=1,
                        help="bo qua bai co it hon N binh luan theo file bai dang (mac dinh 1; 0 = lay tat ca)")
    parser.add_argument("--most-commented", action="store_true",
                        help="mo cac bai nhieu binh luan nhat truoc (mac dinh: theo thu tu trong file)")
    parser.add_argument("--max-comments", type=int, default=150, help="so binh luan toi da moi bai")
    parser.add_argument("--seconds", type=int, default=90, help="thoi gian toi da moi bai (giay)")
    parser.add_argument("--pause-min", type=float, default=2.0)
    parser.add_argument("--pause-max", type=float, default=4.0)
    parser.add_argument("--include-photo", action="store_true",
                        help="cho phep ca link anh khong thuoc loai set=a (mac dinh bo qua)")
    parser.add_argument("--debug", action="store_true",
                        help="luu HTML + anh chup tung bai vao data/raw (chua ten nguoi dung)")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
