"""Lớp lưu trữ SQLite: tin nhắn gốc (email/Zalo) và công việc."""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("CONGVIEC_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "congviec.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,              -- email | zalo | manual
    source_id    TEXT NOT NULL,              -- Message-ID email / hash tin Zalo
    channel      TEXT,                       -- hộp thư / tên nhóm Zalo
    sender       TEXT,
    subject      TEXT,
    body         TEXT,
    received_at  TEXT,
    department   TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE(source, source_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT,
    department   TEXT,
    status       TEXT NOT NULL DEFAULT 'Mới',
    priority     TEXT NOT NULL DEFAULT 'Bình thường',
    assignee     TEXT,
    deadline     TEXT,
    message_id   INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    note         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_dept ON tasks(department);
CREATE INDEX IF NOT EXISTS idx_msg_received ON messages(received_at);
"""

STATUSES = ["Mới", "Đang xử lý", "Chờ chốt", "Hoàn thành", "Huỷ"]
PRIORITIES = ["Khẩn", "Cao", "Bình thường", "Thấp"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def insert_message(conn, source, source_id, channel, sender, subject, body, received_at, department):
    """Lưu tin nhắn; trả về id mới, hoặc None nếu đã tồn tại (chống trùng)."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO messages
           (source, source_id, channel, sender, subject, body, received_at, department, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (source, source_id, channel, sender, subject, body, received_at, department, now()),
    )
    return cur.lastrowid if cur.rowcount else None


def insert_task(conn, title, description="", department="Khác", status="Mới", priority="Bình thường",
                assignee="", deadline="", message_id=None, note=""):
    ts = now()
    cur = conn.execute(
        """INSERT INTO tasks (title, description, department, status, priority, assignee, deadline,
                              message_id, note, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (title[:300], description, department, status, priority, assignee, deadline, message_id, note, ts, ts),
    )
    return cur.lastrowid
