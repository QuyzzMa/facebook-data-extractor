# Hướng dẫn Deploy miễn phí (kèm tên miền)

Thư mục `web/` là trang **tĩnh** (HTML/CSS/JS, không cần server) nên bạn deploy **miễn phí**
lên nhiều nền tảng và có ngay **tên miền miễn phí** dạng:

```
<ten>.github.io      → GitHub Pages
<ten>.netlify.app    → Netlify
<ten>.vercel.app     → Vercel
<ten>.pages.dev      → Cloudflare Pages
<ten>.surge.sh       → Surge.sh
```

> ⚠️ **Hai điều cần biết trước:**
> 1. **Hosting thì miễn phí, tên miền gốc tùy chỉnh thì phải trả tiền.**
>    Tên miền kiểu `tencuatoi.com` **không còn miễn phí** (dịch vụ domain free như Freenom
>    đã ngừng). Hosting (chỗ chứa website) miễn phí là được, còn tên miền phải mua
>    khoảng 5–15$/năm — hoặc dùng các **subdomain miễn phí** ở trên.
> 2. **Trang tĩnh chỉ hiển thị DEMO.** Tính năng **"Chạy dữ liệu thật"** cần `server.py`
>    + trình duyệt + phiên đăng nhập Facebook, nên phải chạy **trên máy bạn** (xem mục cuối).

---

## 1) GitHub Pages (khuyên dùng, có luôn GitHub)

1. Push thư mục dự án lên GitHub (hoặc tạo repo mới, upload `web/`).
2. Vào repo → **Settings → Pages**.
3. Mục **Build and deployment → Source**: chọn **Deploy from a branch**.
4. Chọn **Branch = `main`** (hoặc nhánh bạn dùng), **Folder = `/web`** → **Save**.
5. Đợi 1–2 phút → site chạy tại `https://<username>.github.io/<repo>/`.

**Tùy biến tên miền tùy chỉnh** (nếu bạn có domain):
- Settings → Pages → **Custom domain** → nhập `tencuatoi.com`.
- Tạo file `web/CNAME` chứa `tencuatoi.com`.
- Trỏ DNS: `CNAME tencuatoi.com → <username>.github.io`
  (hoặc `A` → `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`).

## 2) Netlify (kéo-thả, không cần Git)

1. Vào <https://app.netlify.com/drop> (đăng nhập miễn phí).
2. **Kéo nguyên thư mục `web/`** vào khung → tự deploy.
3. Nhận URL `https://<ten>.netlify.app` (đổi tên tại **Site settings → Change site name**).

Gắn tên miền: **Domain management → Add custom domain** → nhập tên miền → đổi DNS tương ứng (Netlify hướng dẫn từng bước).

## 3) Vercel (nhanh, có CLI)

Cách kéo-thả tại <https://vercel.com/new> → chọn **Project** → import thư mục `web/`,
hoặc dùng CLI:

```powershell
npm i -g vercel
cd web
vercel --prod          # lần đầu đăng nhập bằng email
```

Nhận URL `https://<ten>.vercel.app`. Gắn tên miền: **Project → Settings → Domains**.

## 4) Cloudflare Pages

1. Vào <https://dash.cloudflare.com> → **Workers & Pages → Create → Pages**.
2. Hoặc kéo-thả thư mục `web/` tại trang tạo Pages.
3. Nhận URL `https://<ten>.pages.dev`. Miễn phí luôn cả DNS (đặt tên miền sau này).

## 5) Surge.sh (tối giản, dòng lệnh)

```powershell
npm i -g surge
surge web tencuatoi.surge.sh
```

---

## Tên miền miễn phí vs tên miền trả phí — tóm tắt

| Loại | Chi phí | Ví dụ |
|---|---|---|
| Subdomain của nền tảng (GitHub/Netlify/Vercel/…). | **Miễn phí** | `ten.github.io`, `ten.netlify.app` |
| Tên miền gốc bạn tự đăng ký | ~5–15$/năm | `tencuatoi.com`, `tencuatoi.net` |
| Dịch vụ cấp domain 100% miễn phí | ❌ không còn | Freenom đã ngừng |

Nơi mua tên miền giá rẻ (có ghi danh): **Cloudflare Registrar**, **Namecheap**, **Porkbun**.
DNS miễn phí: **Cloudflare**.

---

## ⚙️ Tính năng "Chạy dữ liệu thật" thì sao khi deploy?

- **Trang tĩnh (deploy miễn phí như trên):** chỉ xem demo. Bấm "Chạy dữ liệu thật" sẽ báo
  cần server cục bộ — chuẩn, vì cào Facebook cần trình duyệt + phiên đăng nhập của bạn.
- **Chạy thật trên máy bạn:**
  ```powershell
  .\.venv\Scripts\python.exe server.py   # → mở http://127.0.0.1:8000
  ```
- **Deploy cả backend lên cloud (tùy chọn, KHÔNG khuyến nghị cho Facebook):**
  Render/Railway miễn phí có thể chạy `server.py` + cài Playwright/Chromium. Nhưng rủi ro:
  IP của cloud thường bị Facebook chặn, không có phiên đăng nhập cục bộ, dễ vi phạm điều khoản.

## Kiểm tra sau deploy

1. Mở URL → thấy đúng giao diện demo, đổi được **theme sáng/tối**, scroll có hiệu ứng.
2. Vào mục **"Chạy dữ liệu thật"** → bấm Chạy → thấy thông báo cần `python server.py`
   (đó là hành vi đúng của bản tĩnh).
3. Nếu muốn xem dữ liệu thật: chạy server cục bộ như hướng dẫn ở trên.