# PROJECT PROMPT — Facebook Data Extractor (Playwright + pandas)

> A complete, from-scratch specification. Hand this to a developer (or an AI coding
> agent) to build the whole project. It does not assume any existing code.

## 0) Goal in one line

Build a Windows-friendly Python pipeline that, given a Facebook **Page URL** the user is
authorized to view, opens it with a saved login session, scrolls the feed, and extracts
either the page's **posts** (with reactions / comments / shares) or the **usernames and
profile URLs of the people who commented**, then exports the result to **CSV + XLSX +
Markdown** while keeping the raw HTML for debugging.

## 1) Scope

**In scope**
- Scrape a single Facebook page/timeline URL per run (chosen at runtime).
- Two extract modes: `posts`, `commenters`.
- Session reuse via saved cookies (no password storage).
- Polite, bounded scrolling.
- Export to CSV / XLSX / Markdown.
- Clear notices when a page is gated (login, join-group, pending, age, rate-limit).
- Debug artifacts (raw HTML + screenshot) and JSON logs.

**Out of scope / non-goals**
- Bypassing CAPTCHA, anti-bot controls, checkpoints, or access restrictions.
- Accessing private content or accounts you are not authorized to view.
- Storing passwords, tokens, or secrets in source.
- Real-time streaming, databases, scheduling (optional future work).

## 2) Target environment

- Windows 10/11, PowerShell.
- Python 3.11+ inside a local `.venv`.
- Browsers: bundled Playwright Chromium, and optionally the real Chrome/Edge/Coc Coc.

## 3) Tech stack (dependencies)

`playwright`, `pandas`, `openpyxl`, `beautifulsoup4`, `lxml`, `tabulate`.

## 4) Architecture

```
main.py                     # orchestration: config -> scrape -> parse -> clean -> export -> report
src/scraper.py              # Playwright: login, scroll, expand comments, snapshots, raw HTML
src/parser.py               # BeautifulSoup: posts + commenters + access-issue detection
src/cleaner.py              # pandas: normalise, drop empties, de-duplicate
src/exporter.py             # CSV (utf-8-sig) + XLSX (auto width, tz-aware dates)
src/reporter.py             # Markdown report (schema, samples, notices)
scripts/cookie_to_state.py  # Cookie-Editor JSON -> Playwright storage_state
config/config.json          # all settings
run.bat / cookie.bat        # Windows helpers
tests/test_pipeline.py      # unit tests (runnable without pytest)
```

Data flow:

```
URL -> Playwright (login + scroll + expand) -> rendered HTML (list of snapshots)
    -> parser (posts | commenters) -> cleaner -> CSV + XLSX + Markdown
raw HTML + screenshot -> data/raw/   |   log -> logs/pipeline.log
```

## 5) Data model

`posts` (one row per post):
`source_url, post_url, post_text, timestamp_text, likes_text, comments_text, shares_text, scraped_at_utc`

`commenters` (one row per comment author):
`source_url, post_url, user_name, user_url, comment_text, comment_time, scraped_at_utc`

## 6) Functional requirements

**FR1 - Login modes** (`login_mode`)
- `storage_state`: load cookies/localStorage from a JSON file (default). Primary mode.
- `cdp`: attach to a real Chrome/Edge started with `--remote-debugging-port=9222` (`connect_over_cdp`); optionally auto-start the browser (`cdp_autostart`, `browser_executable`).
- `persistent`: reuse a Playwright browser profile directory.
- `anonymous`: fresh context, no session.
- Apply light stealth: hide `navigator.webdriver`, launch with `--disable-blink-features=AutomationControlled`, optional `channel="chrome"`.

**FR2 - Interactive URL prompt**
- On every run, ask for the target URL; pressing Enter keeps the configured default.
- Prepend `https://` if the scheme is missing. Disable with `prompt_for_url: false`.

**FR3 - Scrolling**
- `max_scrolls` steps, `scroll_pause_seconds` between steps.
- `max_scroll_seconds`: hard time budget (0 = unlimited); stop when reached.
- `expand_comments`: click "view more comments / replies" controls to load more commenters.
- `snapshot_every`: capture the rendered page every N scrolls so virtualised posts keep their comments.
- Keep each loop iteration light: avoid expensive whole-page queries every step; close pop-ups only occasionally.

**FR4 - Post parsing (current + legacy DOM)**
- Current DOM: a post body is `[data-ad-preview="message"]` (`data-ad-comet-preview` too). The post "root" is the largest ancestor containing only that one message.
- Counts from footer aria-labels: `Thích`/`Like` -> reactions, `Viết bình luận`/`Comment` -> comments, `Gửi nội dung này...`/`Share` -> shares.
- Post URL: prefer a `/posts/`, `/reel/`, `/videos/` permalink (strip `comment_id` / `__cft__` / `__tn__`), then the timestamp link, then a photo link.
- Timestamp: a date-like aria-label (e.g. "lúc 21:16"), else relative "N giờ trước".
- Fallback: if no message containers exist, parse older `role="article"` story cards.

**FR5 - Commenter extraction**
- Within each post root, find `<a>` links whose `href` contains `comment_id`, whose text is a name, and that are not post permalinks (`/posts/`, `/reel/`, ...) or media links.
- `user_name` = link text; `user_url` = href with tracking params stripped; `comment_text` / `comment_time` from the enclosing comment block (`role="article"` ancestor).

**FR6 - Cleaning**
- Force the column order; fill missing columns; whitespace-normalise; drop rows missing required fields; de-duplicate.

**FR7 - Export**
- CSV with `utf-8-sig` (so Excel reads Vietnamese correctly).
- XLSX via openpyxl with auto-sized columns; convert timezone-aware datetimes to text.
- Markdown report: source URL, run time, row/column counts, schema table, sample rows, output paths, access notices, data-quality notes.

**FR8 - Access notices**
- Detect login / join-group / pending membership / unavailable / age-gate / rate-limit / guest-view markers in the rendered HTML.
- Print a `*** THONG BAO ***` banner, log them, and list them under "Access Notices" in the report.

**FR9 - Logging & debug artifacts**
- Formatted log to console + `logs/pipeline.log`.
- Save rendered HTML and a screenshot to `data/raw/`; save an error screenshot on failure.

**FR10 - Cookie refresh helper**
- `scripts/cookie_to_state.py` converts a Cookie-Editor JSON export to Playwright `storage_state`.
- `cookie.bat` reads the JSON from the clipboard (or opens Notepad), runs the converter, then deletes the temporary paste file.

**FR11 - Local web server (optional)**
- `server.py` (Flask) serves the static site in `web/` and exposes `GET /api/health`,
  `POST /api/run` (start a job for a user-supplied URL), `GET /api/status/<job_id>` (poll).
- Jobs run in a background thread; progress is captured by attaching a logging handler to
  the root logger. Bind to `127.0.0.1` only.

## 7) Configuration reference (`config/config.json`)

| Key | Default | Meaning |
|---|---|---|
| `url` | page URL | Default target (used when Enter is pressed). |
| `extract_mode` | `posts` | `posts` or `commenters`. |
| `max_scrolls` | 40 | Maximum scroll steps. |
| `scroll_pause_seconds` | 2 | Wait between scrolls. |
| `max_scroll_seconds` | 120 | Hard scroll time budget (0 = unlimited). |
| `expand_comments` | true | Click "view more comments" to load more commenters. |
| `snapshot_every` | 5 | Capture the page every N scrolls (commenters). |
| `prompt_for_url` | true | Ask for the URL each run. |
| `login_mode` | storage_state | storage_state / cdp / persistent / anonymous. |
| `storage_state_path` | data/session/facebook_state.json | Saved cookies. |
| `save_storage_state` | true | Re-save cookies after each run. |
| `headless` | false | Run the browser hidden. |
| `timeout_ms` | 30000 | Default element timeout. |
| `output_prefix` | facebook_posts | Output file prefix. |
| `save_raw_html` | true | Save rendered HTML + screenshot. |
| `cdp_url` / `cdp_autostart` / `browser_executable` | - | CDP options. |

## 8) CLI / usage

```powershell
# one-time setup
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

# run (asks for the URL; Enter keeps the default)
.\.venv\Scripts\python.exe main.py

# refresh the saved session when it expires
cookie.bat            # then run.bat again
```

Windows helpers: `run.bat` (prints a reminder, runs the pipeline, opens `output\`);
`cookie.bat` (import cookies). Batch files use ASCII-only text for safe display in `cmd`.

## 9) Folder layout

```
project/
  run.bat  cookie.bat  main.py  requirements.txt  README.md  PROJECT_PROMPT.md
  config/config.json
  scripts/cookie_to_state.py
  src/{scraper,parser,cleaner,exporter,reporter}.py
  tests/test_pipeline.py
  data/raw/  data/session/
  docs/  logs/  output/
  web/            # optional static site (see section 13)
```

## 10) Testing

- Plain functions named `test_*`, runnable directly: `python tests\test_pipeline.py`
  (and also under pytest if installed).
- Cover: post parsing (current DOM + aria counts), legacy fallback, commenter parsing,
  access-issue detection, URL-prompt normalisation, login-mode resolution, stealth script.

## 11) Security & responsible use

- Collect only content you are authorized to access; prefer official APIs where they fit.
- Do not bypass CAPTCHA, anti-bot controls, access restrictions, or privacy controls.
- Never store passwords/secrets in source; the session file (`data/session/*.json`)
  contains live cookies - keep it private and out of version control (`.gitignore`).
- Provide a `docs/RESPONSIBLE_USE.md`.

## 12) Performance notes

- Virtualised feeds grow huge; keep iterations light and cap the run with
  `max_scrolls` + `max_scroll_seconds`.
- Measuring page height for auto-stop is unreliable on Facebook - prefer the time budget.
- Commenters on old posts are lost once scrolled past, so capture snapshots periodically.

## 13) Optional deliverable - static web page

- A single-page static site in `web/` (no build step): hero + features + a live demo table
  fed by `web/data.sample.json` (use **synthetic** data, never real user data) + usage steps.
- Deployable to GitHub Pages / Netlify / Vercel by publishing the `web/` folder.
- Include `web/README.md` with deploy instructions and a `.nojekyll` file for Pages.

## 14) Acceptance criteria

1. `python main.py` with a valid saved session returns rows for a public page.
2. `extract_mode: posts` yields one row per post with text, timestamp, and counts.
3. `extract_mode: commenters` yields names + profile URLs (many more than the default 1-2 comments).
4. `Parsed 0 records` + a login notice appears when the session is missing/expired.
5. Output files appear in `output\` (CSV, XLSX, MD); raw HTML + screenshot in `data\raw\`.
6. `python tests\test_pipeline.py` reports all tests passing.
7. `cookie.bat` updates `data/session/facebook_state.json` from clipboard/Notepad input.
8. The static site in `web/` works offline and can be deployed as-is.
