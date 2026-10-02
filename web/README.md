# Web page (static demo)

A polished, dependency-free static site (light/dark theme, animated reveal, interactive
data table with tabs + search) that documents the project and shows a demo table fed by
**Synthetic** data (`data.sample.js`). No build step, no server required.

## Run real data

Run `python server.py` from the project root: it serves this folder **and** enables the
**"Chạy dữ liệu thật"** section (`POST /api/run`). Hosted statically (GitHub Pages,
Netlify, Vercel), that section simply asks you to start the local server instead.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check. |
| POST | `/api/run` | Start a job for `{url, extract_mode}`. |
| GET | `/api/status/<job_id>` | Poll progress + result. |

| File | Purpose |
|---|---|
| `index.html` | The page (hero, features, demo table, usage). |
| `styles.css` | Styles (dark, responsive, no framework). |
| `app.js` | Tab switching, search, table rendering. |
| `data.sample.js` | Fictional sample data (`window.SAMPLE_DATA`). |
| `.nojekyll` | Tells GitHub Pages to serve files as-is. |

## Preview locally

- **No server:** double-click `index.html` (works because the sample data is a JS file, not a `fetch`).
- **HTTP server:**
  ```powershell
  cd web
  python -m http.server 8000
  # open http://localhost:8000
  ```

## Deploy

**GitHub Pages**
1. Push the repository to GitHub.
2. Settings -> Pages -> Source: *Deploy from a branch* -> Branch `main`, Folder `/web`.
3. Save. The site is served at `https://<user>.github.io/<repo>/`.

**Netlify**
- Drag-and-drop the `web/` folder at <https://app.netlify.com/drop>, or run `npx netlify deploy --dir=web --prod`.

**Vercel**
- `npx vercel --prod web` (or set the project root to `web`).

**Cloudflare Pages / Surge / any static host**
- Publish the `web/` folder as the site root.

## Using your own data

Replace `data.sample.js` with your own:
```js
window.SAMPLE_DATA = { posts: [ ... ], commenters: [ ... ] };
```
Generate it from the tool's exported CSV/JSON. **Never publish real user data** - keep the
demo synthetic or anonymised.
