"""Nhập tin nhắn nhóm Zalo.

Zalo cá nhân không có API chính thức để đọc tin nhóm, nên ứng dụng hỗ trợ 3 đường:
  1. Dán (copy/paste) đoạn hội thoại từ Zalo PC/Web vào trang "Nhập Zalo".
  2. Tải lên file .txt / .json / .csv đã xuất.
  3. Webhook /api/ingest — nhận sự kiện từ Zalo Official Account hoặc công cụ tự động (n8n, Make, bot...).
"""
import csv
import hashlib
import io
import json
import re
from datetime import datetime

from . import db
from .ingest import ingest

# Các mẫu dòng mở đầu một tin nhắn
_LINE_PATTERNS = [
    # [11/11/2026 09:15] Nguyễn Văn A: nội dung    |   [09:15] Nguyễn Văn A: nội dung
    re.compile(r"^\[(?P<time>[\d/\-. :]+)\]\s*(?P<sender>[^:]{1,60}):\s?(?P<text>.*)$"),
    # 11/11/2026 09:15 - Nguyễn Văn A: nội dung
    re.compile(r"^(?P<time>\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2})\s*[-–]\s*(?P<sender>[^:]{1,60}):\s?(?P<text>.*)$"),
    # Nguyễn Văn A (09:15): nội dung    |   Nguyễn Văn A [09:15]: nội dung
    re.compile(r"^(?P<sender>[^:(\[]{1,60}?)\s*[(\[](?P<time>[\d/\-. :]+)[)\]]\s*:\s?(?P<text>.*)$"),
    # 09:15 Nguyễn Văn A: nội dung
    re.compile(r"^(?P<time>\d{1,2}:\d{2})\s+(?P<sender>[^:]{1,60}):\s?(?P<text>.*)$"),
]


def parse_time(raw, default_date=None):
    raw = (raw or "").strip().replace(",", "")
    default_date = default_date or datetime.now().date()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%y %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
                "%H:%M %d/%m/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if m:
        return datetime.combine(default_date, datetime.min.time()).replace(
            hour=int(m.group(1)) % 24, minute=int(m.group(2))).strftime("%Y-%m-%d %H:%M:%S")
    return db.now()


def parse_text(text, default_date=None):
    """Tách đoạn hội thoại dán vào thành danh sách {sender, time, text}."""
    messages = []
    for line in (text or "").splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        for pat in _LINE_PATTERNS:
            m = pat.match(line.strip())
            if m:
                messages.append({"sender": m.group("sender").strip(),
                                 "time": parse_time(m.group("time"), default_date),
                                 "text": m.group("text").strip()})
                break
        else:
            if messages:  # dòng tiếp theo của tin trước
                messages[-1]["text"] += "\n" + line.strip()
            else:
                messages.append({"sender": "", "time": db.now(), "text": line.strip()})
    if len(messages) == 1 and not messages[0]["sender"]:
        # Không nhận diện được định dạng -> mỗi đoạn (cách bằng dòng trống) là một tin
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
        messages = [{"sender": "", "time": db.now(), "text": b} for b in blocks]
    return messages


def parse_file(filename, content):
    name = (filename or "").lower()
    if name.endswith(".json"):
        data = json.loads(content)
        data = data.get("messages", data) if isinstance(data, dict) else data
        return [{"sender": str(d.get("sender") or d.get("from") or d.get("name") or ""),
                 "time": parse_time(str(d.get("time") or d.get("date") or d.get("timestamp") or "")),
                 "text": str(d.get("text") or d.get("message") or d.get("content") or "")} for d in data]
    if name.endswith(".csv"):
        rows = csv.DictReader(io.StringIO(content))
        return [{"sender": r.get("sender") or r.get("Người gửi") or "",
                 "time": parse_time(r.get("time") or r.get("Thời gian") or ""),
                 "text": r.get("text") or r.get("Nội dung") or ""} for r in rows]
    return parse_text(content)


def _source_id(group, msg):
    key = f"{group}|{msg['sender']}|{msg['time']}|{msg['text']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def import_messages(conn, group, messages, auto_task=True):
    stats = {"total": 0, "new_messages": 0, "new_tasks": 0}
    for m in messages:
        if not m.get("text", "").strip():
            continue
        stats["total"] += 1
        msg_id, task_id = ingest(conn, "zalo", _source_id(group, m), group, m["sender"], "", m["text"],
                                 m["time"], auto_task=auto_task)
        stats["new_messages"] += bool(msg_id)
        stats["new_tasks"] += bool(task_id)
    conn.commit()
    return stats


def from_webhook(payload):
    """Chuẩn hoá payload webhook về (group, message).

    Hỗ trợ: định dạng đơn giản {"group","sender","text","time"} và sự kiện Zalo OA
    ({"event_name","sender":{"id"},"message":{"text"},"timestamp"}).
    """
    if "message" in payload and isinstance(payload["message"], dict):
        ts = payload.get("timestamp")
        time = datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts else db.now()
        group = (payload.get("recipient") or {}).get("id") or payload.get("group_id") or payload.get("oa_id") or "Zalo OA"
        sender = (payload.get("sender") or {}).get("id", "")
        return str(group), {"sender": str(sender), "time": time, "text": payload["message"].get("text", "")}
    return (str(payload.get("group") or payload.get("channel") or "Zalo"),
            {"sender": str(payload.get("sender", "")), "time": parse_time(str(payload.get("time", ""))),
             "text": str(payload.get("text", ""))})
