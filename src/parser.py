from __future__ import annotations

import re
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

COLUMNS = [
    "source_url",
    "post_url",
    "post_text",
    "timestamp_text",
    "likes_text",
    "comments_text",
    "shares_text",
]

NUM = r"([\d.,]+\s?[KkMmBb]?)"
LIKE_PATTERNS = [
    NUM + r"\s+(?:likes?|reactions?|lượt thích|lượt bày tỏ cảm xúc)",
    r"(?:all reactions|tất cả cảm xúc)\s*:?\s*" + NUM,
]
COMMENT_PATTERNS = [NUM + r"\s+(?:comments?|bình luận)"]
SHARE_PATTERNS = [NUM + r"\s+(?:shares?|lượt chia sẻ|chia sẻ)"]

# --- Current Facebook DOM (2024+) ------------------------------------------
# A post body lives in a container marked data-ad-preview="message"; the
# reaction / comment / share counts are carried by aria-labels on the footer.
MESSAGE_SELECTORS = ['[data-ad-preview="message"]', '[data-ad-comet-preview="message"]']
MESSAGE_SELECTOR = ", ".join(MESSAGE_SELECTORS)
REACTIONS_SELECTOR = '[aria-label="Thích"], [aria-label="Like"]'
COMMENTS_SELECTOR = '[aria-label="Viết bình luận"], [aria-label="Comment"]'
SHARES_SELECTOR = (
    '[aria-label="Gửi nội dung này cho bạn bè hoặc đăng lên trang cá nhân của bạn."], '
    '[aria-label="Share"]'
)
ROOT_STOP_TAGS = ("body", "html")
DATE_ARIA_RE = re.compile(
    r"(?:lúc|at)\s+\d{1,2}:\d{2}"
    r"|Tháng\s+\d{1,2},?\s+\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)
RELATIVE_TIME_RE = re.compile(
    r"\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|seconds?|minutes?|hours?|days?|weeks?|months?|years?)"
    r"\s*(?:trước|ago)",
    re.IGNORECASE,
)
MESSAGE_TAIL_RE = re.compile(r"\s*(?:Ẩn bớt|Xem thêm|See more|Hide)\s*$", re.IGNORECASE)
STRONG_POST_TOKENS = ("/posts/", "/permalink/", "/reel/", "/videos/", "/watch/", "story_fbid")
TRACKING_PARAMS = {"comment_id", "__cft__[0]", "__cft__[1]", "__tn__", "ref", "refid", "mibextid", "rdid"}

# --- Legacy DOM (older Facebook layouts), used as a fallback -----------------
POST_LINK_TOKENS = (
    "/posts/", "/permalink/", "/reel/", "/videos/", "/watch/", "story_fbid", "/photo", "/stories/",
)
TIME_WORDS = (
    "ago", "yesterday", "just now", "202", "am", "pm",
    "giờ", "phút", "ngày", "tuần", "tháng", "hôm qua", "vừa xong",
)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _extract_metric(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_post_url(article, source_url: str) -> str | None:
    for link in article.find_all("a", href=True):
        href = link.get("href", "")
        if any(token in href for token in POST_LINK_TOKENS):
            return urljoin(source_url, href)
    return None


def _extract_timestamp(article) -> str | None:
    time_tag = article.find("time")
    if time_tag:
        return _clean_text(time_tag.get("datetime") or time_tag.get_text(" ", strip=True)) or None
    for node in article.find_all(attrs={"aria-label": True}):
        label = _clean_text(node.get("aria-label"))
        if label and len(label) < 60 and any(word in label.lower() for word in TIME_WORDS):
            return label
    return None


def _extract_message(article) -> str:
    for selector in MESSAGE_SELECTORS:
        node = article.select_one(selector)
        if node:
            text = _clean_text(node.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _is_nested(node) -> bool:
    """True for comments: an article that lives inside another article."""
    parent = node.parent
    while parent is not None:
        if getattr(parent, "name", None) == "article" or (
            hasattr(parent, "get") and parent.get("role") == "article"
        ):
            return True
        parent = parent.parent
    return False


def diagnose_html(html: str) -> dict:
    """Counts of useful markers; helps explain why zero records were parsed."""
    lowered = html.lower()
    return {
        "html_length": len(html),
        "article_tags": lowered.count("<article"),
        "role_article": len(re.findall(r'role="article"', html)),
        "post_links": sum(html.count(t) for t in ("/posts/", "/reel/", "/videos/")),
        "message_containers": (
            html.count('data-ad-preview="message"') + html.count('data-ad-comet-preview="message"')
        ),
        "login_form": 'name="pass"' in html or "royal_login_form" in html,
        "checkpoint": "checkpoint" in lowered,
    }


def _parse_legacy_posts(soup, source_url: str) -> list[dict]:
    """Fallback parser for older Facebook layouts (role=article story cards)."""
    candidates = soup.find_all("article") + soup.select('[role="article"]')

    seen_ids: set[int] = set()
    unique_candidates = []
    for node in candidates:
        if id(node) not in seen_ids:
            seen_ids.add(id(node))
            unique_candidates.append(node)

    records = []
    seen_keys = set()
    for article in unique_candidates:
        if _is_nested(article):  # skip comments
            continue
        full_text = _clean_text(article.get_text(" ", strip=True))
        if len(full_text) < 20:
            continue

        post_url = _extract_post_url(article, source_url)
        timestamp = _extract_timestamp(article)
        if not post_url and not timestamp:
            continue

        text = _extract_message(article) or full_text
        key = (post_url or "", text[:300])
        if key in seen_keys:
            continue
        seen_keys.add(key)

        records.append({
            "source_url": source_url,
            "post_url": post_url,
            "post_text": text,
            "timestamp_text": timestamp,
            "likes_text": _extract_metric(full_text, LIKE_PATTERNS),
            "comments_text": _extract_metric(full_text, COMMENT_PATTERNS),
            "shares_text": _extract_metric(full_text, SHARE_PATTERNS),
        })

    return records


def _find_story_root(node):
    """Largest ancestor that still wraps exactly this one post message."""
    root = node
    while getattr(root, "parent", None) is not None and root.parent.name not in ROOT_STOP_TAGS:
        parent = root.parent
        if len(parent.select(MESSAGE_SELECTOR)) > 1:
            break
        root = parent
    return root


def _strip_tracking(url: str) -> str:
    """Drop comment / click-tracking query params, keep the permalink path."""
    base, sep, query = url.partition("?")
    if not sep:
        return url
    kept = [part for part in query.split("&") if part.split("=", 1)[0] not in TRACKING_PARAMS]
    return base + ("?" + "&".join(kept) if kept else "")


def _extract_story_url(root, source_url: str) -> str | None:
    strong = date_link = photo = stories = None
    for link in root.find_all("a", href=True):
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue
        aria = _clean_text(link.get("aria-label"))
        if date_link is None and aria and DATE_ARIA_RE.search(aria):
            date_link = href
        if strong is None and any(token in href for token in STRONG_POST_TOKENS):
            strong = href
        elif photo is None and "/photo" in href:
            photo = href
        elif stories is None and "/stories/" in href:
            stories = href
    chosen = strong or date_link or photo or stories
    return urljoin(source_url, _strip_tracking(chosen)) if chosen else None


def _extract_story_timestamp(root) -> str | None:
    for node in root.find_all(attrs={"aria-label": True}):
        aria = _clean_text(node.get("aria-label"))
        if aria and DATE_ARIA_RE.search(aria):
            return aria
    match = RELATIVE_TIME_RE.search(root.get_text(" ", strip=True))
    return match.group(0) if match else None


def _extract_count(root, selector: str) -> str | None:
    for node in root.select(selector):
        value = _clean_text(node.get_text(" ", strip=True))
        if value and any(char.isdigit() for char in value):
            return value
    return None


def _parse_message_posts(soup, source_url: str) -> list[dict]:
    """Parse posts from the current Facebook DOM (data-ad-preview="message")."""
    records: list[dict] = []
    seen_roots: set[int] = set()
    seen_keys: set[tuple[str, str]] = set()

    for message in soup.select(MESSAGE_SELECTOR):
        root = _find_story_root(message)
        if id(root) in seen_roots:
            continue
        seen_roots.add(id(root))

        text = _clean_text(message.get_text(" ", strip=True))
        text = MESSAGE_TAIL_RE.sub("", text).strip()
        if len(text) < 10:
            continue

        post_url = _extract_story_url(root, source_url)
        key = (post_url or "", text[:300])
        if key in seen_keys:
            continue
        seen_keys.add(key)

        records.append({
            "source_url": source_url,
            "post_url": post_url,
            "post_text": text,
            "timestamp_text": _extract_story_timestamp(root),
            "likes_text": _extract_count(root, REACTIONS_SELECTOR),
            "comments_text": _extract_count(root, COMMENTS_SELECTOR),
            "shares_text": _extract_count(root, SHARES_SELECTOR),
        })

    return records


def parse_posts(html: str, source_url: str) -> pd.DataFrame:
    """Parse Facebook posts, preferring the current DOM and falling back to the
    legacy role="article" layout."""
    soup = BeautifulSoup(html, "lxml")
    records = _parse_message_posts(soup, source_url) or _parse_legacy_posts(soup, source_url)
    return pd.DataFrame(records, columns=COLUMNS)


ACCESS_SIGNALS = [
    ("login", (
        "đăng nhập để tiếp tục", "log in to continue", "you must log in",
    )),
    ("join_group", (
        "tham gia nhóm", "tham gia để xem", "bạn cần tham gia", "chỉ thành viên",
        "chỉ có thành viên", "join group", "join this group", "members of this group",
        "private group", "nhóm riêng tư", "nhóm kín",
    )),
    ("membership_pending", (
        "đang chờ phê duyệt", "pending approval", "request to join", "yêu cầu tham gia",
    )),
    ("unavailable", (
        "nội dung này hiện không khả dụng", "this content isn't available",
        "this content is no longer available", "nội dung này không còn",
    )),
    ("age_restricted", ("giới hạn độ tuổi", "age-restricted", "age restricted")),
    ("rate_limited", (
        "tạm thời bị chặn", "you're temporarily blocked", "temporarily blocked",
        "bị hạn chế tạm thời",
    )),
    ("guest_view", (
        "see more on facebook", "xem thêm trên facebook", "hãy đăng nhập để tiếp tục",
    )),
]


def detect_access_issues(html: str) -> list[str]:
    """Return access-restriction codes found in the rendered HTML.

    Codes: login, join_group, membership_pending, unavailable, age_restricted,
    rate_limited, guest_view.
    """
    lowered = (html or "").lower()
    return [code for code, phrases in ACCESS_SIGNALS if any(p in lowered for p in phrases)]


# --- Commenter extraction ---------------------------------------------------
COMMENT_TIME_RE = re.compile(r"\bvào\s+(.+)$", re.IGNORECASE)
COMMENT_TIME_EN_RE = re.compile(r"\bon\s+(.+)$", re.IGNORECASE)
VERIFIED_RE = re.compile(r"^(?:Tài khoản đã xác minh|Verified account)\s*")
LEADING_TIME_RE = re.compile(
    r"^[\d.,]+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|s|m|h|d|w|y)\b", re.IGNORECASE
)
LEADING_AUTHOR_RE = re.compile(r"^(?:Tác giả|Author)\b", re.IGNORECASE)
TRAILING_UI_RE = re.compile(
    r"(?:\s*(?:Thích|Like|Trả lời|Reply|Đã chỉnh sửa|Edited|\d+[.,]?\d*[KkMm]?))*\s*$"
)


def _find_comment_block(link):
    node = link
    for _ in range(15):
        node = getattr(node, "parent", None)
        if node is None:
            return None
        if getattr(node, "get", None) and node.get("role") == "article":
            return node
    return None


def _extract_comment_time(block) -> str | None:
    if block is None:
        return None
    for node in block.find_all(attrs={"aria-label": True}):
        aria = _clean_text(node.get("aria-label"))
        match = COMMENT_TIME_RE.search(aria) or COMMENT_TIME_EN_RE.search(aria)
        if match:
            return match.group(1).strip()
    text = _clean_text(block.get_text(" ", strip=True))
    match = re.search(
        r"\b\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|giờ trước)(?:\s*trước)?\b", text
    )
    return match.group(0).strip() if match else None


def _extract_comment_text(block, name: str) -> str | None:
    if block is None:
        return None
    text = _clean_text(block.get_text(" ", strip=True))
    if name and text.startswith(name):
        text = text[len(name):]
    text = text.strip(" ·•-–—")
    text = VERIFIED_RE.sub("", text).strip(" ·•-–—")
    text = LEADING_TIME_RE.sub("", text).strip(" ·•-–—")
    text = LEADING_AUTHOR_RE.sub("", text).strip(" ·•-–—")
    text = TRAILING_UI_RE.sub("", text).strip()
    return text or None


def parse_commenters(html: str, source_url: str) -> pd.DataFrame:
    """Return one row per comment author (username + profile URL) per post."""
    soup = BeautifulSoup(html, "lxml")
    records: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    seen_roots: set[int] = set()

    for message in soup.select(MESSAGE_SELECTOR):
        root = _find_story_root(message)
        if id(root) in seen_roots:
            continue
        seen_roots.add(id(root))
        post_url = _extract_story_url(root, source_url)

        for link in root.find_all("a", href=True):
            href = link.get("href", "")
            name = _clean_text(link.get_text(" ", strip=True))
            if not name or "comment_id" not in href:
                continue
            if any(token in href for token in STRONG_POST_TOKENS):
                continue
            if "/photo" in href or "/stories/" in href:
                continue
            user_url = urljoin(source_url, _strip_tracking(href))
            key = (post_url or "", user_url, name)
            if key in seen:
                continue
            seen.add(key)
            block = _find_comment_block(link)
            records.append({
                "source_url": source_url,
                "post_url": post_url,
                "user_name": name,
                "user_url": user_url,
                "comment_text": _extract_comment_text(block, name),
                "comment_time": _extract_comment_time(block),
            })

    return pd.DataFrame(records)
