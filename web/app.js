// Static demo logic for the Facebook Data Extractor page.
// Works from file:// too (data is embedded via data.sample.js, no fetch).

const COLUMNS = {
  posts: [
    { key: "post_text", label: "Nội dung" },
    { key: "timestamp_text", label: "Thời gian" },
    { key: "likes_text", label: "Thích" },
    { key: "comments_text", label: "Bình luận" },
    { key: "shares_text", label: "Chia sẻ" },
    { key: "post_url", label: "Link bài" },
  ],
  commenters: [
    { key: "user_name", label: "Người bình luận" },
    { key: "user_url", label: "Trang cá nhân" },
    { key: "comment_text", label: "Nội dung" },
    { key: "comment_time", label: "Thời gian" },
    { key: "post_url", label: "Bài viết" },
  ],
};

const DATA = window.SAMPLE_DATA || { posts: [], commenters: [] };
let currentTab = "posts";

const thead = document.querySelector("#data-table thead");
const tbody = document.querySelector("#data-table tbody");
const countEl = document.getElementById("count");
const searchEl = document.getElementById("search");
const toggle = document.getElementById("theme-toggle");

/* ---------- Theme ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  if (toggle) toggle.textContent = theme === "dark" ? "☀️" : "🌙";
  try { localStorage.setItem("fbe-theme", theme); } catch (e) { /* ignore */ }
}
(function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("fbe-theme"); } catch (e) { /* ignore */ }
  if (!saved) {
    const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
    saved = prefersLight ? "light" : "dark";
  }
  applyTheme(saved);
})();
if (toggle) {
  toggle.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
  });
}

/* ---------- Table ---------- */
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}
function isUrl(value) {
  return typeof value === "string" && /^https?:\/\//i.test(value);
}
function render() {
  const columns = COLUMNS[currentTab];
  const query = (searchEl.value || "").trim().toLowerCase();
  const rows = (DATA[currentTab] || []).filter((row) => {
    if (!query) return true;
    return columns.some((c) => String(row[c.key] ?? "").toLowerCase().includes(query));
  });

  thead.innerHTML = "<tr>" + columns.map((c) => `<th>${escapeHtml(c.label)}</th>`).join("") + "</tr>";

  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="${columns.length}">Không có dữ liệu.</td></tr>`;
  } else {
    tbody.innerHTML = rows.map((row) =>
      "<tr>" + columns.map((c) => {
        const value = row[c.key] ?? "";
        const cell = isUrl(value)
          ? `<a href="${escapeHtml(value)}" target="_blank" rel="noopener">${escapeHtml(value)}</a>`
          : escapeHtml(value);
        return `<td>${cell}</td>`;
      }).join("") + "</tr>"
    ).join("");
  }
  countEl.textContent = String(rows.length);
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    currentTab = button.dataset.tab;
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === button));
    render();
  });
});
searchEl.addEventListener("input", render);

/* ---------- Reveal on scroll ---------- */
function setupReveal() {
  const items = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) {
    items.forEach((el) => el.classList.add("in"));
    return;
  }
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("in");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  items.forEach((el, index) => {
    el.style.transitionDelay = Math.min((index % 8) * 45, 270) + "ms";
    observer.observe(el);
  });
}

/* ---------- Animated counters ---------- */
function runCounters() {
  document.querySelectorAll(".stat-num").forEach((el) => {
    const target = Number(el.dataset.count || "0");
    if (!target) { el.textContent = "0"; return; }
    let current = 0;
    const step = Math.max(1, Math.round(target / 22));
    const tick = () => {
      current += step;
      if (current >= target) { el.textContent = String(target); return; }
      el.textContent = String(current);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

/* ---------- Init ---------- */
render();
setupReveal();
runCounters();

/* ---------- Live run (needs the local server: python server.py) ---------- */
const runForm = document.getElementById("run-form");

if (runForm) {
  const runUrl = document.getElementById("run-url");
  const runMode = document.getElementById("run-mode");
  const runBtn = document.getElementById("run-btn");
  const runAlert = document.getElementById("run-alert");
  const runState = document.getElementById("run-state");
  const runLog = document.getElementById("run-log");
  const runResults = document.getElementById("run-results");
  const liveTable = document.getElementById("live-table");

  const showAlert = (text, kind) => {
    runAlert.hidden = false;
    runAlert.className = "alert" + (kind ? " " + kind : "");
    runAlert.textContent = text;
  };

  const renderLive = (result) => {
    const cols = result.columns || [];
    liveTable.querySelector("thead").innerHTML =
      "<tr>" + cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("") + "</tr>";
    const rows = result.rows || [];
    liveTable.querySelector("tbody").innerHTML = rows.length
      ? rows.map((row) => "<tr>" + cols.map((c) => {
          const value = row[c] ?? "";
          const cell = isUrl(value)
            ? `<a href="${escapeHtml(value)}" target="_blank" rel="noopener">${escapeHtml(value)}</a>`
            : escapeHtml(value);
          return `<td>${cell}</td>`;
        }).join("") + "</tr>").join("")
      : `<tr><td class="empty" colspan="${cols.length}">Không có dữ liệu.</td></tr>`;
    runResults.hidden = false;
  };

  const poll = async (jobId) => {
    for (;;) {
      const res = await fetch("/api/status/" + encodeURIComponent(jobId));
      const data = await res.json();
      runLog.textContent = (data.logs || []).join("\n");
      runLog.scrollTop = runLog.scrollHeight;
      if (data.state === "done") return data.result;
      if (data.state === "error") throw new Error(data.error || "Job lỗi");
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  };

  runForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    runAlert.hidden = true;
    runResults.hidden = true;
    runLog.hidden = false;
    runLog.textContent = "";
    runState.hidden = false;
    runState.innerHTML = '<span class="spin"></span> Đang chạy… (thường 1–3 phút)';
    runBtn.disabled = true;
    runBtn.textContent = "Đang chạy…";
    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: runUrl.value.trim(), extract_mode: runMode.value }),
      });
      const started = await res.json().catch(() => ({}));
      if (!res.ok || !started.ok) throw new Error(started.error || ("HTTP " + res.status));
      const result = await poll(started.job_id);
      renderLive(result);
      runState.textContent = `Xong: ${result.count} dòng (${result.mode}). File CSV: ${(result.files || {}).csv || ""}`;
      if (result.notices && result.notices.length) showAlert(result.notices.join("  •  "), "ok");
    } catch (err) {
      showAlert(
        "Không chạy được: " + err.message +
        " — Nếu bạn đang mở trang tĩnh (không có server), hãy chạy: python server.py " +
        "rồi mở http://127.0.0.1:8000",
        "error"
      );
      runState.hidden = true;
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "Chạy";
    }
  });
}

