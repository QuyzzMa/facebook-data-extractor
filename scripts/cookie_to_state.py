"""Convert a Cookie-Editor (or EditThisCookie) JSON export into a Playwright
storage_state file that this project can load via ``login_mode = storage_state``.

Usage:
    python scripts/cookie_to_state.py [cookie_paste.json] [data/session/facebook_state.json]
"""
from __future__ import annotations