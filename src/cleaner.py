from __future__ import annotations

import re
import pandas as pd

COLUMNS = [
    "source_url",
    "post_url",
    "post_text",
    "timestamp_text",
    "likes_text",
    "comments_text",
    "shares_text",
]


def clean_posts(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for column in COLUMNS:
        if column not in result.columns:
            result[column] = None
    result = result[COLUMNS].copy()

    result["post_text"] = result["post_text"].fillna("").map(lambda x: re.sub(r"\s+", " ", str(x)).strip())
    result = result[result["post_text"].str.len() > 0].copy()
    result = result.drop_duplicates(subset=["post_url", "post_text"], keep="first")
    result["scraped_at_utc"] = pd.Timestamp.now(tz="UTC")
    return result.reset_index(drop=True)


COMMENTER_COLUMNS = [
    "source_url",
    "post_url",
    "user_name",
    "user_url",
    "comment_text",
    "comment_time",
]


def clean_commenters(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for column in COMMENTER_COLUMNS:
        if column not in result.columns:
            result[column] = None
    result = result[COMMENTER_COLUMNS].copy()

    result["user_name"] = result["user_name"].fillna("").map(lambda x: re.sub(r"\s+", " ", str(x)).strip())
    result = result[result["user_name"].str.len() > 0].copy()
    result = result.drop_duplicates(subset=["post_url", "user_url", "comment_text"], keep="first")
    result["scraped_at_utc"] = pd.Timestamp.now(tz="UTC")
    return result.reset_index(drop=True)
