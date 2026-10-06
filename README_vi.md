# Trình trích xuất dữ liệu Facebook (Playwright + pandas)

Một pipeline thân thiện với Windows mở trang Facebook mà bạn được ủy quyền xem, lướt qua trang và lưu kết quả dưới CSV + XLSX + Markdown. Nó hỗ trợ hai chế độ trích: **posts** (mỗi dòng là một bài đăng) hoặc **commenters** (mỗi dòng là một người bình luận).

## Features
- **Hai chế độ trích** – `posts` (mỗi dòng là một bài đăng) hoặc `commenters` (mỗi dòng là một người bình luận).
- **Đọc DOM hiện tại và cũ** – đọc các bài đăng có `data-ad-preview="message"` và đếm số lượng phản hồi / bình luận / chia sẻ, với fallback `role="article"`.
- **Quản lý phiên** – `storage_state` (JSON cookie), `cdp` (liên kết với Chrome/Edge thật), `persistent` (profil Playwright) hoặc `anonymous`.
- **Cung cấp URL tương tác** – hỏi URL mục tiêu mỗi khi chạy.
- **Thông báo truy cập** – cảnh báo khi trang yêu cầu đăng nhập, tham gia nhóm, chưa được phê duyệt, nội dung không sẵn sàng, v.v.
- **Lướt scroll có đạo đức** – cấu hình `max_scrolls` và ngưỡng thời gian tổng cộng.
- **Mở rộng bình luận** – nhấp vào "xem thêm bình luận" và thu thập nhiều lần để lấy nhiều người bình luận.
- **Debug dễ dàng** – HTML thô + ảnh chụp màn hình trong `data/raw/`, nhật ký JSON trong `logs/pipeline.log`.
- **Hai công cụ trợ giúp** – `run.bat` (chạy pipeline) và `cookie.bat` (làm mới phiên thủ công - phương án dự phòng, vì chế độ `storage_state` đã tự động mở trình duyệt để đăng nhập khi cần).
- **Thử nghiệm mà không cần pytest** – `python tests\test_pipeline.py`.

## Login modes (cách xác thực)
### anonymous — Trang công khai, không cần phiên. Tạo trình duyệt mới mỗi lần chạy. Dùng cho nội dung thực sự công khai.
### persistent — tái sử dụng profil trình duyệt Playwright. Lưu phiên trong `data/session/facebook`. Trong lần chạy đầu tiên, đăng nhập trong cửa sổ trình duyệt hiện có; các lần chạy tiếp theo sẽ tái sử dụng profil. Đây là hành vi ban đầu của dự án (khi dùng `session_enabled = true`).
### cdp — Kết nối với Chrome thật (đề nghị cho trang yêu cầu đăng nhập). Khởi chạy Chrome một lần với cổng debug, đăng nhập bình thường, sau đó cho công cụ gắn vào nó:
```powershell
# Phương án A: để công cụ khởi động Chrome tự động
# cấu hình: "login_mode": "cdp", "cdp_autostart": true
.\\.\venv\Scripts\python.exe main.py

# Phương án B: khởi động Chrome thủ công trước
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `--remote-debugging-port=9222` `--user-data-dir="C:\chrome-debug"` `https://www.facebook.com/example.page`
# cấu hình: "login_mode": "cdp", "cdp_autostart": false
.\\.\venv\Scripts\python.exe main.py
```
Công cụ kết nối qua `connect_over_cdp`, mở một tab riêng chia sẻ phiên đăng nhập của bạn và không bao giờ đóng Chrome (tab nó mở sẽ được đóng khi chạy kết thúc). Đặt `save_storage_state = true` để xuất cookies thành `data/session/facebook_state.json`.
### storage_state — **Cookie lưu trong file (login_mode MẶC ĐỊNH, khuyến nghị).** Tái sử dụng cookies lưu trữ, không cần mở trình duyệt mỗi lần chạy. Đọc cookies/localStorage từ `storage_state_path` (mặc định `data/session/facebook_state.json`). 
- **Lần đầu chạy** (hoặc file phiên thiếu/lỗi): công cụ mở cửa sổ trình duyệt HIỂN THỊ (cần `headless: false`) để bạn tự đăng nhập Facebook - công cụ không tự điền mật khẩu, không vượt CAPTCHA/checkpoint. Sau khi đăng nhập xong, phiên được lưu tự động vào `storage_state_path` (khi `save_storage_state: true`).
- **Các lần chạy sau**: phiên lưu sẵn được tái sử dụng. Nếu hết hạn, công cụ phát hiện trang đăng nhập, mở trình duyệt để bạn đăng nhập lại và tự động cập nhật phiên.
- `cookie.bat` (hoặc `scripts/cookie_to_state.py`) vẫn là cách thủ công dự phòng: dán JSON export từ Cookie-Editor vào file phiên.
### Extra options
- `use_real_chrome: true` — sử dụng Chrome đã cài đặt (`channel="chrome"`) thay vì Chromium đi kèm (bundled). Kết hợp với một số kỹ thuật che giấu (`hiding navigator.webdriver`, khởi chạy với `--disable-blink-features=AutomationControlled`) sẽ giảm khả năng bị kiểm tra an ninh.
### Troubleshooting

| Triệu chứng | Nguyên nhân / cách khắc phục |
|---|---|
| `Parsed 0 records` | Phiên đăng nhập hết hạn hoặc trang yêu cầu đăng nhập. Hệ thống sẽ tự động mở trình duyệt để bạn đăng nhập lại (nếu chạy với headless=false). Nếu chạy với headless=true, hãy dừng và chạy lại với headless=false để đăng nhập. |
| Chỉ có vài người bình luận | Facebook chỉ hiển thị một số bình luận ban đầu. Công cụ nhấp vào "xem thêm bình luận", nhưng để hiển thị đầy đủ mọi bình luận cần mở từng bài đăng. Giảm `max_scrolls` để các bài đăng còn nhiều hơn, hoặc tăng `snapshot_every`. |
| Thời gian chạy rất lâu | Giảm `max_scrolls` và/hoặc `max_scroll_seconds`. Trang lớn sẽ cứ tải thêm nội dung khi cuộn. |
| Lướt scroll cảm giác chậm | Feed trực tiếp trở nên quá lớn. Giảm `max_scrolls`, giữ `max_scroll_seconds` nhỏ, hoặc set `headless: true`. |
| Một khối `*** THONG BAO ***` xuất hiện | Facebook hiển thị form đăng nhập / nhóm chờ / giới hạn tuổi; thông báo sẽ nói bạn cần làm gì. |
| Trình duyệt không mở | Chạy `.\\\.\.venv\Scripts\python.exe -m playwright install chromium`. |

## FAQ
- **Có thể tự động đăng nhập không?** Công cụ tự động QUẢN LÝ phiên: lần đầu chạy (hoặc khi phiên hết hạn) sẽ mở cửa sổ trình duyệt để bạn tự đăng nhập, rồi lưu và tái sử dụng phiên ở các lần sau. Công cụ không tự điền mật khẩu, không vượt CAPTCHA/checkpoint; cách thủ công dự phòng là `cookie.bat`.
- **Kết quả nằm ở đâu?** Ở `output\` dưới dạng `.csv`, `.xlsx` và `.md`.
- **Nơi raw data để gỡ lỗi?** `data\raw\` (HTML đã render + ảnh chụp màn hình).
- **File cookie có an toàn không?** `data/session/facebook_state.json` có thể truy cập tài khoản của bạn - giữ nó riêng tư và không bao giờ commit file này lên repo.

## Chạy dữ liệu thật (trên máy tính địa phương)
Trang tĩnh chỉ là demo. Để trích **dữ liệu thật từ URL mà bạn cung cấp**, chạy máy chủ Flask đính kèm (cần trình duyệt + phiên đăng nhập, vì vậy chạy địa phương):
```powershell
.\\.\.venv\Scripts\python.exe server.py
# mở http://127.0.0.1:8000
```
Trên trang sử dụng mục **"Chạy dữ liệu thật"**: nhập URL Facebook, chọn chế độ (`commenters` / `posts`) và nhấn **Chạy**. UI sẽ hiển thị tiến độ trực tiếp và bảng kết quả; kết quả được ghi vào `output\`.

## Lướt scroll và thu thập bài đăng tránh mất do virtualization

Facebook sẽ xóa các bài đăng khỏi DOM khi chúng cuộn ra khỏi màn hình quá xa. Để chắc chắn thu thập được tất cả bài đăng mà công cụ đã thấy trong quá trình chạy, trình duyệt sẽ được cuộn từng bước nhỏ **1.000 pixel**. Tại mỗi bước, mọi thẻ `[role="article"]` cấp cao nhất (bài đăng chính) được:

1. Trích xuất
2. Loại trùng lặp bằng **200 ký tự đầu** của nội dung bài (không tính luồng bình luận lồng nhau)
3. Gộp lại thành một tài liệu HTML duy nhất

Tài liệu HTML đã gộp là phần tử **cuối cùng** trong danh sách trả về, vì vậy parser sẽ thấy mọi bài đăng từng xuất hiện trên màn hình trong suốt quá trình chạy. Mặc định, `max_scrolls` được đặt là **40** (tương đương 40.000 pixel cuộn) và `snapshot_every` là **5** (chụp lại trang mỗi 5 lần cuộn). Bạn có thể giảm `max_scrolls` (và giữ `max_scroll_seconds` nhỏ) nếu cảm thấy cuộn chậm hoặc lag.

## Sử dụng có trách nhiệm
- Thu thập chỉ nội dung bạn được ủy quyền truy cập.
- Ưu tiên API chính thức nếu họ đáp ứng yêu cầu dự án.
- Không thu thập thông tin cá nhân không cần thiết.
- Không cài đặt mật khẩu, token truy cập hoặc cookie cứng.
- Không bỏ qua CAPTCHA, kiểm soát chống bot, ràng buộc truy cập hoặc kiểm soát riêng tư.
- Kiểm tra điều kiện áp dụng và luật địa phương trước khi triển khai trình trích.
- Giữ thư mục phiên trình duyệt liên tục riêng tư. Không bao giờ công khai hoặc đăng lên.

## Kiểm tra sau triển khai
1. Mở URL → thấy đúng giao diện demo, có thể đổi **theme sáng/tối**, lướt có hiệu ứng.
2. Vào mục **"Chạy dữ liệu thật"** → nhấn **Chạy** → thấy thông báo cần `python server.py` (đó là hành vi đúng của bản tĩnh).
3. Nếu muốn xem dữ liệu thật: chạy server địa phương như hướng dẫn ở trên.