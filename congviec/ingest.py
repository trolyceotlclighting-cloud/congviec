"""Nhận một tin (email/Zalo) -> lưu kho -> tự tạo công việc nếu nhận diện là việc cần xử lý."""
from . import classify, db


def ingest(conn, source, source_id, channel, sender, subject, body, received_at, auto_task=True):
    text = f"{subject or ''}\n{body or ''}"
    dept = classify.classify_department(text)
    msg_id = db.insert_message(conn, source, source_id, channel, sender, subject, body, received_at, dept)
    if msg_id is None:
        return None, None  # đã có trong kho
    task_id = None
    if auto_task and classify.is_task(text):
        task_id = db.insert_task(
            conn,
            title=classify.make_title(subject, body),
            description=(body or "")[:2000],
            department=dept,
            priority=classify.detect_priority(text),
            deadline=classify.detect_deadline(text),
            assignee="",
            message_id=msg_id,
            note=f"Tự tạo từ {source} — {channel or ''} — {sender or ''}".strip(),
        )
    return msg_id, task_id
