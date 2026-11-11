# Kho Công Việc TLC

Ứng dụng web lưu trữ **toàn bộ email** (Gmail `trolyceo.tlclighting@gmail.com`) và **tin nhắn các nhóm Zalo**,
tự động nhận diện các việc cần xử lý / cần anh chốt và phân loại theo phòng ban:
Kinh doanh GT · Dự án · Giải pháp công nghiệp · R&D · Mua hàng · Marketing · Nhân sự · Kế toán · Nhà máy · Chi nhánh.

## Tính năng
- **Kho tin nhắn**: lưu mọi email và tin Zalo, tìm kiếm toàn văn, lọc theo nguồn / nhóm / phòng ban. Không lưu trùng.
- **Tự tạo công việc** từ tin có “đề nghị, xin duyệt, chốt, báo cáo, hạn, gấp…”, tự đoán phòng ban, mức ưu tiên và hạn chót.
- **Quản lý công việc**: trạng thái (Mới → Đang xử lý → Chờ chốt → Hoàn thành), người phụ trách, hạn, ghi chú chỉ đạo.
- **Tổng quan**: việc cần chốt/khẩn, việc quá hạn, số việc mở theo phòng ban.
- **Xuất Excel (CSV)** danh sách công việc.
- Đăng nhập bằng mật khẩu; dữ liệu lưu trong 1 file SQLite (`data/congviec.db`) trên máy của công ty.

## Cài đặt
Yêu cầu Python 3.10+.
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env  — rồi điền thông tin
python -m congviec run           # mở http://127.0.0.1:5000
```

## Kết nối Gmail
1. Đăng nhập Gmail trợ lý → Cài đặt → *Chuyển tiếp và POP/IMAP* → **Bật IMAP**.
2. Tài khoản Google → Bảo mật → bật **Xác minh 2 bước** → tạo **Mật khẩu ứng dụng** (https://myaccount.google.com/apppasswords).
3. Điền `GMAIL_USER`, `GMAIL_APP_PASSWORD` vào `.env`.
4. Bấm **↻ Đồng bộ Gmail** trên web, hoặc chạy định kỳ:
   ```bash
   python -m congviec sync-gmail
   ```
   - Linux (cron, 15 phút/lần): `*/15 * * * * cd /duong-dan/congviec && .venv/bin/python -m congviec sync-gmail`
   - Windows: Task Scheduler → chạy `.venv\Scripts\python.exe -m congviec sync-gmail` trong thư mục ứng dụng.

Lần đầu lấy thư trong `GMAIL_SINCE_DAYS` ngày gần nhất; các lần sau chỉ lấy thư mới. Ứng dụng chỉ **đọc** thư
(không đánh dấu đã đọc, không xoá).

## Nhập tin nhắn nhóm Zalo
Zalo cá nhân **không có API chính thức** để đọc tin nhóm, vì vậy có 3 cách:

1. **Dán hội thoại** (cách nhanh nhất): Zalo PC/Web → chọn nhiều tin → Sao chép → trang **Nhập Zalo** → nhập tên nhóm → dán.
   Định dạng nhận được: `[dd/mm/yyyy hh:mm] Tên: nội dung`, `[hh:mm] Tên: nội dung`, `Tên (hh:mm): nội dung`, `hh:mm Tên: nội dung`.
2. **Tải file** `.txt / .json / .csv` (cột `sender, time, text`), hoặc dòng lệnh:
   ```bash
   python -m congviec import-zalo "TLC - Ban Giám đốc" hoithoai.txt
   ```
3. **Tự động qua webhook** — dành cho Zalo Official Account (OA) của công ty hoặc công cụ n8n/Make:
   ```
   POST /api/ingest?token=<API_TOKEN>
   {"group": "TLC - Dự án", "sender": "Nguyễn Văn A", "text": "Đề nghị anh duyệt...", "time": "11/11/2026 09:15"}
   ```
   Cũng nhận trực tiếp sự kiện Zalo OA dạng `{"event_name", "sender": {"id"}, "message": {"text"}, "timestamp"}`.
   Ứng dụng cần chạy trên địa chỉ public (HTTPS) để Zalo gọi được webhook.

> Không khuyến nghị dùng thư viện Zalo không chính thức (đăng nhập tài khoản cá nhân bằng cookie) vì có rủi ro bị khoá tài khoản.

## Tuỳ chỉnh phân loại
Danh sách từ khoá phòng ban, từ khoá nhận diện công việc và mức ưu tiên nằm trong `congviec/classify.py` — sửa trực tiếp cho sát cách
viết thực tế của các phòng ban TLC.

## Kiểm thử
```bash
pip install pytest && python -m pytest -q
```
