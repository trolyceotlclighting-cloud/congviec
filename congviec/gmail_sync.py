"""Đồng bộ email từ Gmail qua IMAP (dùng Mật khẩu ứng dụng của Google).

Cấu hình qua biến môi trường:
  GMAIL_USER          địa chỉ Gmail
  GMAIL_APP_PASSWORD  mật khẩu ứng dụng 16 ký tự (myaccount.google.com/apppasswords)
  GMAIL_FOLDER        thư mục cần đồng bộ (mặc định INBOX)
  GMAIL_SINCE_DAYS    lần đầu lấy thư trong N ngày gần nhất (mặc định 30)
"""
import email
import imaplib
import os
import re
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape

from . import db
from .ingest import ingest

IMAP_HOST = "imap.gmail.com"


def _dec(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _html_to_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", "", html))
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def extract_body(msg):
    plain, html = None, None
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_maintype() == "multipart" or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            content = payload.decode(charset, errors="replace")
        except LookupError:
            content = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and plain is None:
            plain = content
        elif part.get_content_type() == "text/html" and html is None:
            html = content
    if plain:
        return plain.strip()
    return _html_to_text(html) if html else ""


def parse_message(raw_bytes):
    msg = email.message_from_bytes(raw_bytes)
    name, addr = parseaddr(_dec(msg.get("From")))
    try:
        received = parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        received = db.now()
    return {
        "message_id": (msg.get("Message-ID") or "").strip(),
        "sender": f"{name} <{addr}>" if name else addr,
        "subject": _dec(msg.get("Subject")),
        "body": extract_body(msg),
        "received_at": received,
    }


def sync(conn, user=None, password=None, folder=None, since_days=None, limit=500):
    user = user or os.environ.get("GMAIL_USER")
    password = password or os.environ.get("GMAIL_APP_PASSWORD")
    folder = folder or os.environ.get("GMAIL_FOLDER", "INBOX")
    since_days = int(since_days or os.environ.get("GMAIL_SINCE_DAYS", 30))
    if not user or not password:
        raise RuntimeError("Chưa cấu hình GMAIL_USER / GMAIL_APP_PASSWORD trong file .env")

    stats = {"fetched": 0, "new_messages": 0, "new_tasks": 0}
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        imap.login(user, password)
        typ, _ = imap.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Không mở được thư mục {folder}")
        uidvalidity = imap.untagged_responses.get("UIDVALIDITY", [b"0"])[0].decode()
        key = f"gmail:{user}:{folder}"
        last_uid = int(db.get_setting(conn, key + ":uid", 0))
        if db.get_setting(conn, key + ":validity") != uidvalidity:
            last_uid = 0
        if last_uid:
            typ, data = imap.uid("SEARCH", None, f"UID {last_uid + 1}:*")
        else:
            since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
            typ, data = imap.uid("SEARCH", None, f"SINCE {since}")
        uids = [int(u) for u in data[0].split() if int(u) > last_uid][:limit]

        for uid in uids:
            typ, msg_data = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            m = parse_message(msg_data[0][1])
            stats["fetched"] += 1
            msg_id, task_id = ingest(conn, "email", m["message_id"] or f"uid-{uidvalidity}-{uid}", user,
                                     m["sender"], m["subject"], m["body"], m["received_at"])
            stats["new_messages"] += bool(msg_id)
            stats["new_tasks"] += bool(task_id)
            last_uid = max(last_uid, uid)
            db.set_setting(conn, key + ":uid", last_uid)
            conn.commit()

        db.set_setting(conn, key + ":validity", uidvalidity)
        db.set_setting(conn, "gmail:last_sync", db.now())
        conn.commit()
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return stats
