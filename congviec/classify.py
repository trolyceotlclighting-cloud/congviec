"""Phân loại tin nhắn theo phòng ban, nhận diện việc cần xử lý, độ ưu tiên và hạn chót.

Dựa trên từ khoá tiếng Việt — có thể chỉnh danh sách bên dưới cho sát thực tế TLC.
"""
import re
import unicodedata
from datetime import date, timedelta

DEPARTMENTS = {
    "Kinh doanh GT": ["kinh doanh", "đại lý", "nhà phân phối", "npp", "doanh số", "đơn hàng", "báo giá",
                      "khách hàng", "công nợ khách", "kênh gt", "showroom", "chiết khấu"],
    "Dự án": ["dự án", "công trình", "chủ đầu tư", "thầu", "hồ sơ thầu", "nghiệm thu", "thi công", "tư vấn thiết kế"],
    "Giải pháp công nghiệp": ["công nghiệp", "nhà xưởng", "kho bãi", "highbay", "đèn đường", "chiếu sáng công nghiệp",
                              "giải pháp", "smart lighting", "chiếu sáng thông minh"],
    "R&D": ["r&d", "nghiên cứu", "phát triển sản phẩm", "mẫu thử", "thiết kế sản phẩm", "driver", "chip led",
            "quang thông", "thử nghiệm", "lab", "bản vẽ"],
    "Mua hàng": ["mua hàng", "nhà cung cấp", "ncc", "nhập khẩu", "po ", "purchase", "linh kiện", "vật tư", "đặt hàng ncc"],
    "Marketing": ["marketing", "quảng cáo", "truyền thông", "fanpage", "website", "sự kiện", "catalogue", "catalog",
                  "hội chợ", "triển lãm", "brand", "thương hiệu", "seo"],
    "Nhân sự": ["nhân sự", "tuyển dụng", "ứng viên", "phỏng vấn", "lương", "bảo hiểm", "nghỉ phép", "hợp đồng lao động",
                "đào tạo", "kpi nhân viên", "thôi việc", "chấm công"],
    "Kế toán": ["kế toán", "hoá đơn", "hóa đơn", "thanh toán", "công nợ", "thuế", "quyết toán", "ngân hàng",
                "dòng tiền", "chi phí", "tạm ứng", "báo cáo tài chính", "vat"],
    "Nhà máy": ["nhà máy", "sản xuất", "dây chuyền", "qc", "kiểm tra chất lượng", "tồn kho", "xuất kho", "lắp ráp",
                "công suất", "lỗi sản phẩm", "bảo hành"],
    "Chi nhánh": ["chi nhánh", "cn hcm", "cn hà nội", "cn đà nẵng", "văn phòng đại diện", "miền nam", "miền trung", "miền bắc"],
}

# Cụm từ cho thấy đây là việc cần anh xử lý / chốt.
TASK_PATTERNS = [
    r"đề nghị", r"đề xuất", r"xin (ý kiến|phê duyệt|duyệt|chỉ đạo)", r"phê duyệt", r"trình (ký|duyệt|anh)",
    r"cần (anh|chốt|xử lý|gấp|duyệt)", r"nhờ anh", r"anh (xem|duyệt|chốt|cho ý kiến|ký)", r"chốt", r"deadline",
    r"hạn (chót|nộp|cuối)", r"trước ngày", r"báo cáo", r"kế hoạch", r"giao (việc|cho)", r"yêu cầu", r"\btodo\b",
    r"việc cần", r"xử lý", r"ký (hợp đồng|duyệt)", r"@ceo", r"@anh",
]

URGENT = [r"\bgấp\b", r"khẩn", r"urgent", r"asap", r"ngay hôm nay", r"trong hôm nay", r"hỏa tốc", r"hoả tốc"]
HIGH = [r"quan trọng", r"ưu tiên", r"important", r"sớm nhất"]


def _norm(text):
    return unicodedata.normalize("NFC", (text or "")).lower()


def classify_department(text):
    t = _norm(text)
    best, score = "Khác", 0
    for dept, kws in DEPARTMENTS.items():
        s = sum(t.count(k) for k in kws)
        if s > score:
            best, score = dept, s
    return best


def is_task(text):
    t = _norm(text)
    return any(re.search(p, t) for p in TASK_PATTERNS)


def detect_priority(text):
    t = _norm(text)
    if any(re.search(p, t) for p in URGENT):
        return "Khẩn"
    if any(re.search(p, t) for p in HIGH):
        return "Cao"
    return "Bình thường"


def detect_deadline(text, today=None):
    """Tìm hạn chót dạng 'dd/mm', 'dd/mm/yyyy', 'hôm nay', 'ngày mai', 'tuần này'. Trả về 'YYYY-MM-DD' hoặc ''."""
    today = today or date.today()
    t = _norm(text)
    m = re.search(r"(?:hạn|deadline|trước ngày|trước|ngày|chậm nhất)\s*:?\s*(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        year = int(y) + (2000 if y and len(y) == 2 else 0) if y else today.year
        try:
            return date(year, mo, d).isoformat()
        except ValueError:
            pass
    if re.search(r"hôm nay|trong ngày", t):
        return today.isoformat()
    if re.search(r"ngày mai", t):
        return (today + timedelta(days=1)).isoformat()
    if re.search(r"tuần này", t):
        return (today + timedelta(days=6 - today.weekday())).isoformat()
    return ""


def make_title(subject, body, limit=120):
    base = (subject or "").strip() or (body or "").strip().split("\n")[0]
    base = re.sub(r"^(re|fw|fwd)\s*:\s*", "", base, flags=re.I).strip()
    return (base[:limit] + "…") if len(base) > limit else (base or "(không tiêu đề)")
