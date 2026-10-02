# Facebook Data Extractor (Playwright + pandas)

A Windows-friendly pipeline that opens a Facebook page you are authorized to view,
scrolls it, and saves the result to **CSV + XLSX + Markdown**. It supports two
extract modes: the page's **posts** (with reactions / comments / shares) or the
**commenters** (username + profile URL) of those posts.

## Features

- **Two extract modes** - `posts` (one row per post) or `commenters` (one row per comment author).
- **Current + legacy DOM** - reads `data-ad-preview="message"` posts and aria-labelled counts, with a `role="article"` fallback.
- **Session handling** - `storage_state` (cookie JSON), `cdp` (attach to your real Chrome/Edge), `persistent` (Playwright profile) or `anonymous`.
- **Interactive URL prompt** - asks for the target page on every run.
- **Access notices** - warns you when a page requires login, joining a group, pending approval, unavailable content, etc.
- **Polite scrolling** - configurable `max_scrolls` and a total time budget.
- **Comment expansion** - clicks "view more comments" and captures the page several times to collect more commenters.
- **Debug-friendly** - raw HTML + screenshot in `data/raw/`, JSON logs in `logs/pipeline.log`.
- **Two helpers** - `run.bat` (run) and `cookie.bat` (refresh the login session).
- **Tests without pytest** - `python tests\test_pipeline.py`.

## Login modes (how the tool authenticates)

Set `login_mode` in `config/config.json`:

### `anonymous` — Public pages, no session
A fresh browser context. Use for genuinely public content.

### `persistent` — Reuse a Playwright browser profile
Stores the session under `data/session/facebook`. On the first run, log in in the visible browser window; later runs reuse the profile. This was the original behaviour (`session_enabled = true`).

### `cdp` — Attach to your real Chrome (recommended for login-gated pages)
Facebook is far less likely to challenge a browser you actually use. Start Chrome once with a debug port, log in normally, then let the tool attach to it:

```powershell
# Option A: let the tool start Chrome for you
# config: "login_mode": "cdp", "cdp_autostart": true
.\.venv\Scripts\python.exe main.py

# Option B: start Chrome yourself first
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 --user-data-dir="D:\chrome-debug" `
  "https://www.facebook.com/schannel.vn"
# config: "login_mode": "cdp", "cdp_autostart": false
.\.venv\Scripts\python.exe main.py
```

The tool connects via `connect_over_cdp`, opens a dedicated tab that shares your logged-in session, and never closes your Chrome (the tab it opened is closed when the run ends). Set `save_storage_state = true` to also export the cookies to `data/session/facebook_state.json`.

### `storage_state` — Reuse saved cookies (no browser needed each run)
Reads cookies/localStorage from `storage_state_path` (default `data/session/facebook_state.json`). Produce that file by running once in `cdp` mode with `save_storage_state = true`, or by pasting cookies exported with a browser extension (Cookie-Editor format is compatible with Playwright's `storage_state`). Cookies expire periodically, so refresh when the source starts returning zero rows.

### Extra options
- `use_real_chrome: true` — use the installed Chrome (`channel="chrome"`) instead of the bundled Chromium. Combined with a few stealth tweaks (hiding `navigator.webdriver`, launched with `--disable-blink-features=AutomationControlled`) it lowers the chance of a security checkpoint.

Use these only for content your account is authorized to access. Do not use the project to bypass CAPTCHA, anti-bot controls, access restrictions, or private content.

## Setup on Windows PowerShell

```powershell
cd "D:\Downloads\facebook_data_extractor_fixed"
```

Create the environment if needed:

```powershell
py -3.13 -m venv .venv   # or: python -m venv .venv
```

If PowerShell blocks `Activate.ps1`, you do not need to activate the environment. Use the explicit interpreter:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Run:

```powershell
.\.venv\Scripts\python.exe main.py
```

## Quick start (.bat files on Windows)

Two helper batch files are provided in the project root:

- **`run.bat`** - runs the pipeline with the project's virtual environment, prints a reminder about the saved login session, and opens the `output\` folder when finished. If you see `Parsed 0 records`, the session has expired -> run `cookie.bat`.
- **`cookie.bat`** - refreshes the login session. It reads the cookie JSON from your clipboard (Cookie-Editor's **Export -> Export as JSON** copies it there) and converts it into `data/session/facebook_state.json`. If the clipboard has no JSON, it opens Notepad so you can paste manually.

Typical flow:

```text
1. Double-click run.bat
2. If it reports 0 records (session expired): double-click cookie.bat, then run.bat again
```

> The cookie JSON is sensitive (it can be used to access your account). It is converted locally and the temporary paste file is deleted afterwards. Do not share it.

## Configuration

Edit `config/config.json`:

```json
{
  "url": "https://www.facebook.com/schannel.vn",
  "extract_mode": "commenters",
  "max_scrolls": 40,
  "scroll_pause_seconds": 2,
  "max_scroll_seconds": 120,
  "expand_comments": true,
  "snapshot_every": 5,
  "prompt_for_url": true,
  "login_mode": "storage_state",
  "storage_state_path": "data/session/facebook_state.json",
  "save_storage_state": true,
  "headless": false,
  "wait_for_login": false,
  "output_prefix": "facebook_posts"
}
```

### Key settings

| Key | Meaning |
|---|---|
| `url` | Default target page (used when you press Enter at the prompt). |
| `extract_mode` | `posts` or `commenters`. |
| `max_scrolls` | Maximum scroll steps. |
| `max_scroll_seconds` | Hard time budget for scrolling (0 = unlimited). |
| `expand_comments` | Click "view more comments" to load more commenters. |
| `snapshot_every` | Capture the page every N scrolls in `commenters` mode (0 = off). |
| `prompt_for_url` | Ask for the URL on every run. |
| `login_mode` | `storage_state` / `cdp` / `persistent` / `anonymous`. |
| `headless` | Run the browser hidden (no interactive login). |

## Pipeline

```text
Facebook URL
    ↓
Playwright
    ↓
Rendered HTML
    ↓
Raw HTML snapshot
    ↓
Parser
    ↓
Cleaner / validation
    ↓
CSV + XLSX + Markdown report
```

## Project structure

```text
facebook_data_extractor_fixed/
├── run.bat                 # run the pipeline
├── cookie.bat              # refresh the login session
├── main.py                 # orchestrates the pipeline
├── requirements.txt
├── README.md
├── PROJECT_PROMPT.md       # full from-scratch project spec
├── config/
│   └── config.json         # all settings
├── scripts/
│   └── cookie_to_state.py  # cookie JSON -> storage_state
├── src/
│   ├── scraper.py          # Playwright: scroll, login, snapshots
│   ├── parser.py           # BeautifulSoup: posts + commenters
│   ├── cleaner.py          # pandas: cleanup + dedupe
│   ├── exporter.py         # CSV / XLSX
│   └── reporter.py         # Markdown report
├── tests/
│   └── test_pipeline.py
├── data/
│   ├── raw/                # rendered HTML + screenshots
│   └── session/            # browser profile + facebook_state.json
├── docs/
├── logs/pipeline.log
├── output/                 # CSV / XLSX / MD results
└── web/                    # static demo site (deployable)
```

## Interactive URL & access notices

- Each run asks for the target URL. Press **Enter** to use the default `url` from `config/config.json`. Set `"prompt_for_url": false` to skip the prompt and always use the configured URL.
- If Facebook blocks the page (login, join-group, pending membership, unavailable content, age gate, rate limit, guest view), the tool prints a **notice** in the console, records it in `logs/pipeline.log`, and lists it under **Access Notices** in the Markdown report.

## Extract modes

Set `extract_mode` in `config/config.json`:

- **`posts`** - one row per post: `source_url, post_url, post_text, timestamp_text, likes_text, comments_text, shares_text`.
- **`commenters`** - one row per comment author: `source_url, post_url, user_name, user_url, comment_text, comment_time`. Use this to build a list of the users who interacted.

Scrolling is controlled by `max_scrolls` (default 40) and `max_scroll_seconds` (a hard time budget, default 120). In `commenters` mode the tool also clicks "view more comments" controls and captures the page several times so it collects more commenters.

## Parser

`src/parser.py` supports the current Facebook DOM and older layouts:

- **Current DOM (2024+):** a post body is a `[data-ad-preview="message"]` element. The parser takes the wrapping "story" (the largest ancestor that holds only that one message), so it captures the real posts and skips comment blocks (`role="article"`).
- **Counts** are read from footer aria-labels: `Thích`/`Like` -> reactions, `Viết bình luận`/`Comment` -> comments, `Gửi nội dung này...`/`Share` -> shares.
- **Post URL** prefers a `/posts/`, `/reel/`, `/videos/` permalink (comment and click-tracking query params are stripped), then the timestamp link, then a photo link.
- **Fallback:** if no message containers exist, the older `role="article"` parser is used.

Facebook changes its DOM regularly, so selectors may need maintenance. A zero-record result is not proof the source has no posts - inspect the newest file in `data/raw/`.

## Debugging zero records

If the log says `Parsed 0 records`, do not immediately change selectors. First inspect the newest file in `data/raw/`. It is the exact rendered HTML returned by Playwright. The report will also record that zero rows were parsed.

Facebook's DOM is dynamic and can change. A parser that works today may need maintenance later.


## Login pause

If Facebook shows a login form and `headless` is false, the script pauses and asks you to log in in the browser window, then press Enter in the terminal. The login is saved in `data/session/facebook` and reused next time. A screenshot is saved next to each raw HTML file in `data/raw/`.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Parsed 0 records` | The session expired or the page needs login. Run `cookie.bat`, then `run.bat`. Read the notice printed in the console. |
| Only a few commenters | Facebook renders only a handful of comments per post. The tool clicks "view more comments", but fully loading every comment requires opening each post. Lower `max_scrolls` so more posts stay rendered, or raise `snapshot_every`. |
| Run takes very long | Lower `max_scrolls` and/or `max_scroll_seconds`. Big pages keep loading. |
| Scrolling feels laggy | The live feed becomes huge. Lower `max_scrolls`, keep `max_scroll_seconds` small, or set `headless: true`. |
| A `*** THONG BAO ***` block appears | Facebook shows a login / join-group / age wall; the message tells you what to do. |
| Browser does not open | Run `.\.venv\Scripts\python.exe -m playwright install chromium`. |

## FAQ

- **Can it auto-login?** No. Facebook blocks automation logins; you refresh the session with `cookie.bat` (browser extension export).
- **Where are the results?** In `output\` as `.csv`, `.xlsx` and `.md`.
- **Where is the raw data for debugging?** `data\raw\` (rendered HTML + screenshot).
- **Is the cookie file safe?** `data/session/facebook_state.json` can access your account - keep it private and never commit it.

## Run real data (local web server)

The static site is a demo only. To extract **real data from a URL you provide**, run the
bundled Flask server (it needs a browser + your saved session, so it runs locally):

```powershell
.\.venv\Scripts\python.exe server.py
# open http://127.0.0.1:8000
```

On the page use the **"Chạy dữ liệu thật"** section: type a Facebook URL, pick the mode
(`commenters` / `posts`) and press **Chạy**. The UI shows live progress and the result
table; files are written to `output\`.

API (for scripting):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check. |
| POST | `/api/run` | Body `{url, extract_mode, max_scrolls?, max_scroll_seconds?}` → `{job_id}`. |
| GET | `/api/status/<job_id>` | `{state, logs, result, error}` — poll until `done`. |

The server binds to `127.0.0.1` only.

## Web demo (static site)

A polished static site lives in `web/` (hero, feature cards, an interactive data table with
search + tabs, workflow, and usage). No build step and no external service required.

- Preview: open `web/index.html`, or run `cd web; python -m http.server 8000` and visit `http://localhost:8000`.
- Deploy: publish the `web/` folder to GitHub Pages / Netlify / Vercel / Cloudflare Pages / Surge.sh (see deployment guide in `docs/DEPLOY.md`).
- The demo uses **synthetic** data in `web/data.sample.js` - never publish real user data.
- Includes a light/dark theme toggle, scroll-reveal animations and animated counters.

## Responsible use

Collect only content you are authorized to access, prefer official APIs where they fit, and do not bypass CAPTCHA, anti-bot controls, access restrictions or privacy controls. See `docs/RESPONSIBLE_USE.md`.
