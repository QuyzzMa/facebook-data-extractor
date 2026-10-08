import os
import sys
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import resolve_target_url
from src.cleaner import clean_posts
from src.parser import detect_access_issues, parse_commenters, parse_posts
from src.scraper import STEALTH_INIT_SCRIPT, _find_chrome_executable, _resolve_login_mode


def test_parser_and_cleaner():
    html = '''
    <article role="article">
      <time datetime="2026-09-30T10:00:00Z">Sep 30</time>
      <a href="https://www.facebook.com/example/posts/123">Post</a>
      <div>Hello from a public test post with enough content.</div>
      <span>10 likes</span><span>2 comments</span>
    </article>
    '''
    df = parse_posts(html, "https://www.facebook.com/example")
    assert len(df) == 1
    cleaned = clean_posts(df)
    assert len(cleaned) == 1
    assert "scraped_at_utc" in cleaned.columns


def test_current_dom_message_post_with_aria_counts():
    html = '''
    <div>
      <a aria-label="Thứ Tư, 30 Tháng 9, 2026 lúc 21:16" href="/schannel.vn/posts/pfbid123">21 giờ trước</a>
      <div data-ad-preview="message">Bản tin buổi sáng hôm nay có nhiều thông tin hữu ích cho mọi người.</div>
      <div>
        <div aria-label="Thích"><div>3,6K</div></div>
        <div aria-label="Viết bình luận"><div>61</div></div>
        <div aria-label="Gửi nội dung này cho bạn bè hoặc đăng lên trang cá nhân của bạn."><div>3</div></div>
      </div>
    </div>
    '''
    df = parse_posts(html, "https://www.facebook.com/schannel.vn")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["post_text"].startswith("Bản tin")
    assert row["likes_text"] == "3,6K"
    assert row["comments_text"] == "61"
    assert row["shares_text"] == "3"
    assert row["timestamp_text"].endswith("21:16")
    assert row["post_url"].endswith("/posts/pfbid123")


def test_comments_are_not_parsed_as_posts():
    html = '''
    <div>
      <div data-ad-preview="message">Bài viết chính có nội dung đủ dài để được lấy ra.</div>
      <div>
        <div aria-label="Thích"><div>1,2K</div></div>
        <div aria-label="Viết bình luận"><div>35</div></div>
      </div>
      <div role="article">
        <a href="/c/posts/9?comment_id=abc" aria-label="1 giờ">1 giờ</a>
        <div>Đây là một bình luận dài hơn hai mươi ký tự và không có message.</div>
      </div>
    </div>
    '''
    df = parse_posts(html, "https://www.facebook.com/schannel.vn")
    assert len(df) == 1
    assert df.iloc[0]["post_text"].startswith("Bài viết chính")
    assert df.iloc[0]["likes_text"] == "1,2K"


def test_resolve_login_mode():
    assert _resolve_login_mode(None, True) == "persistent"
    assert _resolve_login_mode(None, False) == "anonymous"
    assert _resolve_login_mode("CDP", False) == "cdp"
    assert _resolve_login_mode("storage_state", True) == "storage_state"
    assert _resolve_login_mode("anonymous", True) == "anonymous"
    # Unknown value falls back to the session_enabled decision.
    assert _resolve_login_mode("bogus", True) == "persistent"


def test_stealth_script_hides_automation():
    assert "webdriver" in STEALTH_INIT_SCRIPT
    assert "window.chrome" in STEALTH_INIT_SCRIPT


def test_find_chrome_executable_type():
    result = _find_chrome_executable()
    assert result is None or isinstance(result, str)


def test_detect_access_issues():
    assert "join_group" in detect_access_issues("<div>Tham gia nhóm để xem nội dung</div>")
    assert "login" in detect_access_issues("<div>Log in to continue</div>")
    assert "unavailable" in detect_access_issues("This content isn't available right now")
    assert detect_access_issues("<div>Bài viết bình thường</div>") == []


def test_resolve_target_url():
    assert resolve_target_url({"url": "https://x.com", "prompt_for_url": False}) == "https://x.com"
    with mock.patch("builtins.input", return_value="facebook.com/abc"):
        assert resolve_target_url({"url": "https://d", "prompt_for_url": True}) == "https://facebook.com/abc"
    with mock.patch("builtins.input", return_value=""):
        assert resolve_target_url({"url": "https://d", "prompt_for_url": True}) == "https://d"


def test_parse_commenters():
    html = '''
    <div>
      <div data-ad-preview="message">Bài viết chính của trang đủ dài để lấy.</div>
      <div role="article">
        <a href="https://www.facebook.com/cherry.trang.600859?comment_id=abc"
           aria-label="Bình luận dưới tên Cherry Trang vào 15 giờ trước">Cherry Trang</a>
        <div>15 giờ</div>
        <div>Biết rồi ngáo hết rồi luôn</div>
      </div>
    </div>
    '''
    df = parse_commenters(html, "https://www.facebook.com/schannel.vn")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["user_name"] == "Cherry Trang"
    assert row["user_url"] == "https://www.facebook.com/cherry.trang.600859"
    assert "Biết rồi" in str(row["comment_text"])
    assert row["comment_time"] == "15 giờ trước"


def test_on_target():
    from src.scraper import _on_target

    target = "https://www.facebook.com/schannel.vn"
    assert _on_target(target, target)
    assert _on_target(target + "/", target)
    assert _on_target(target + "/posts/pfbid1", target)
    assert not _on_target("https://www.facebook.com/", target)
    assert not _on_target("https://www.facebook.com/groups/x/posts/1", target)
    assert not _on_target(target + "2", target)  # tien to giong nhau nhung khac trang
    profile = "https://www.facebook.com/profile.php?id=5"
    assert _on_target(profile, profile)


def _fixed_now():
    from datetime import datetime

    from src.dates import VN_TZ

    return datetime(2026, 10, 7, 14, 0, tzinfo=VN_TZ)


def test_parse_fb_datetime_absolute():
    from src.dates import parse_fb_datetime

    now = _fixed_now()
    got = parse_fb_datetime("Thứ Tư, 7 Tháng 10, 2026 lúc 13:20", now)
    assert (got.year, got.month, got.day, got.hour, got.minute) == (2026, 10, 7, 13, 20)
    got = parse_fb_datetime("October 7, 2026 at 1:20 PM", now)
    assert (got.year, got.month, got.day, got.hour, got.minute) == (2026, 10, 7, 13, 20)


def test_parse_fb_datetime_relative():
    from src.dates import parse_fb_datetime

    now = _fixed_now()
    assert parse_fb_datetime("3 giờ", now).hour == 11
    assert parse_fb_datetime("2 ngày", now).day == 5
    got = parse_fb_datetime("Hôm qua lúc 10:00", now)
    assert (got.day, got.hour, got.minute) == (6, 10, 0)
    assert parse_fb_datetime("abc", now) is None


def test_filter_by_date():
    import pandas as pd

    from src.dates import filter_by_date

    now = _fixed_now()
    df = pd.DataFrame({"timestamp_text": [
        "Thứ Tư, 7 Tháng 10, 2026 lúc 13:20",
        "Thứ Hai, 1 Tháng 9, 2026 lúc 09:00",
        "Thứ Sáu, 30 Tháng 10, 2026 lúc 09:00",
        "abc",
    ]})
    out, stats = filter_by_date(df, "timestamp_text", "2026-10-01", "2026-10-15", now, keep_undated=True)
    assert stats == {"total": 4, "kept": 2, "dropped_out_of_range": 2, "undated": 1}
    assert set(out["date_status"]) == {"ok", "undated"}
    out, stats = filter_by_date(df, "timestamp_text", "2026-10-01", "2026-10-15", now, keep_undated=False)
    assert stats["kept"] == 1 and stats["undated"] == 1


if __name__ == "__main__":
    import traceback

    _tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    _failed = 0
    for _test in _tests:
        try:
            _test()
            print("PASS", _test.__name__)
        except Exception:
            _failed += 1
            print("FAIL", _test.__name__)
            traceback.print_exc()
    print(f"{len(_tests) - _failed}/{len(_tests)} passed")
    sys.exit(1 if _failed else 0)
