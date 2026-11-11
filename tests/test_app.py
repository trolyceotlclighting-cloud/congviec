from datetime import date
from email.message import EmailMessage

import pytest

from congviec import classify, db, gmail_sync, zalo
from congviec.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "")
    monkeypatch.setenv("API_TOKEN", "secret")
    app = create_app(str(tmp_path / "t.db"))
    app.config["APP_PASSWORD"] = ""
    app.config["API_TOKEN"] = "secret"
    app.testing = True
    return app.test_client()


def test_classify():
    assert classify.classify_department("Đề nghị anh duyệt hồ sơ thầu dự án Vinhomes") == "Dự án"
    assert classify.classify_department("Báo cáo tuyển dụng ứng viên tháng 11") == "Nhân sự"
    assert classify.is_task("Em xin phê duyệt đơn hàng")
    assert not classify.is_task("Chúc cả nhà cuối tuần vui vẻ")
    assert classify.detect_priority("Việc gấp anh ơi") == "Khẩn"
    assert classify.detect_deadline("hạn 15/11/2026") == "2026-11-15"
    assert classify.detect_deadline("trước ngày 20/12", today=date(2026, 11, 11)) == "2026-12-20"


def test_parse_zalo_text():
    text = ("[11/11/2026 09:15] Nguyễn Văn A: Đề nghị anh duyệt báo giá\ndòng 2\n"
            "[09:20] Trần Thị B: Ok anh\n"
            "Lê C (10:00): Gửi anh báo cáo")
    msgs = zalo.parse_text(text, default_date=date(2026, 11, 11))
    assert [m["sender"] for m in msgs] == ["Nguyễn Văn A", "Trần Thị B", "Lê C"]
    assert msgs[0]["text"] == "Đề nghị anh duyệt báo giá\ndòng 2"
    assert msgs[0]["time"] == "2026-11-11 09:15:00"
    assert msgs[2]["time"] == "2026-11-11 10:00:00"


def test_import_dedup(tmp_path):
    conn = db.connect(str(tmp_path / "x.db"))
    msgs = zalo.parse_text("[09:00] A: Cần anh chốt giá nhà cung cấp linh kiện, hạn 20/11")
    s1 = zalo.import_messages(conn, "Mua hàng TLC", msgs)
    s2 = zalo.import_messages(conn, "Mua hàng TLC", msgs)
    assert s1["new_messages"] == 1 and s1["new_tasks"] == 1
    assert s2["new_messages"] == 0
    task = conn.execute("SELECT * FROM tasks").fetchone()
    assert task["department"] == "Mua hàng"
    assert task["deadline"].endswith("-11-20")


def test_parse_email():
    m = EmailMessage()
    m["From"] = "Phòng Kế toán <ketoan@tlc.vn>"
    m["Subject"] = "Đề nghị thanh toán hoá đơn NCC"
    m["Message-ID"] = "<abc@tlc>"
    m["Date"] = "Wed, 11 Nov 2026 08:00:00 +0700"
    m.set_content("Kính gửi anh, đề nghị anh duyệt thanh toán. Hạn 13/11.")
    m.add_alternative("<p>HTML</p>", subtype="html")
    p = gmail_sync.parse_message(m.as_bytes())
    assert p["subject"] == "Đề nghị thanh toán hoá đơn NCC"
    assert "duyệt thanh toán" in p["body"]
    assert p["received_at"] == "2026-11-11 08:00:00"


def test_web_flow(client):
    assert client.get("/").status_code == 200
    r = client.post("/import/zalo", data={"group": "BGĐ", "content": "[09:00] A: Đề nghị anh duyệt KPI marketing gấp",
                                          "auto_task": "1"}, follow_redirects=True)
    assert "tạo 1 công việc" in r.get_data(as_text=True)
    page = client.get("/tasks").get_data(as_text=True)
    assert "Đề nghị anh duyệt KPI marketing gấp" in page
    assert client.get("/tasks/1").status_code == 200
    client.post("/tasks/1/status", data={"status": "Hoàn thành"})
    assert "Hoàn thành" in client.get("/tasks?status=Hoàn thành").get_data(as_text=True)
    assert client.get("/messages?q=KPI").status_code == 200
    assert client.get("/messages/1").status_code == 200
    assert client.get("/tasks/new?from_message=1").status_code == 200
    assert client.get("/tasks.csv").data.startswith("﻿".encode())


def test_api_ingest(client):
    assert client.post("/api/ingest", json={"text": "x"}).status_code == 401
    r = client.post("/api/ingest?token=secret", json={"group": "Dự án", "sender": "B", "text": "Xin ý kiến anh về thầu"})
    assert r.get_json()["new_tasks"] == 1
    r = client.post("/api/ingest?token=secret",
                    json={"event_name": "user_send_text", "sender": {"id": "123"}, "timestamp": "1762822800000",
                          "message": {"text": "Chào"}})
    assert r.get_json()["new_messages"] == 1
