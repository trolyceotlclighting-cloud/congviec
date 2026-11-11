"""Ứng dụng web Kho Công Việc TLC."""
import csv
import hmac
import io
import os
from datetime import date
from functools import wraps

from flask import (Flask, Response, flash, g, jsonify, redirect, render_template, request, session, url_for)

from . import classify, db, gmail_sync, zalo


def load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def create_app(db_path=None):
    load_env()
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)
    app.config["DB_PATH"] = db_path or os.environ.get("CONGVIEC_DB") or db.DB_PATH
    app.config["APP_PASSWORD"] = os.environ.get("APP_PASSWORD", "")
    app.config["API_TOKEN"] = os.environ.get("API_TOKEN", "")

    def get_db():
        if "db" not in g:
            g.db = db.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def inject():
        return {"STATUSES": db.STATUSES, "PRIORITIES": db.PRIORITIES,
                "DEPARTMENTS": list(classify.DEPARTMENTS) + ["Khác"], "today": date.today().isoformat()}

    def login_required(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if app.config["APP_PASSWORD"] and not session.get("ok"):
                return redirect(url_for("login", next=request.path))
            return view(*a, **kw)
        return wrapped

    # ---------- Đăng nhập ----------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if hmac.compare_digest(request.form.get("password", ""), app.config["APP_PASSWORD"]):
                session["ok"] = True
                return redirect(request.args.get("next") or url_for("dashboard"))
            flash("Sai mật khẩu", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- Tổng quan ----------
    @app.route("/")
    @login_required
    def dashboard():
        conn = get_db()
        today = date.today().isoformat()
        by_status = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status")}
        by_dept = conn.execute(
            """SELECT department, COUNT(*) n,
                      SUM(CASE WHEN deadline != '' AND deadline < ? THEN 1 ELSE 0 END) overdue
               FROM tasks WHERE status NOT IN ('Hoàn thành','Huỷ') GROUP BY department ORDER BY n DESC""",
            (today,)).fetchall()
        overdue = conn.execute(
            """SELECT * FROM tasks WHERE status NOT IN ('Hoàn thành','Huỷ') AND deadline != '' AND deadline < ?
               ORDER BY deadline LIMIT 20""", (today,)).fetchall()
        waiting = conn.execute(
            """SELECT * FROM tasks WHERE status='Chờ chốt' OR (priority='Khẩn' AND status NOT IN ('Hoàn thành','Huỷ'))
               ORDER BY CASE priority WHEN 'Khẩn' THEN 0 WHEN 'Cao' THEN 1 ELSE 2 END, deadline LIMIT 20""").fetchall()
        recent = conn.execute("SELECT * FROM messages ORDER BY received_at DESC LIMIT 10").fetchall()
        msg_count = {r["source"]: r["n"] for r in conn.execute("SELECT source, COUNT(*) n FROM messages GROUP BY source")}
        return render_template("dashboard.html", by_status=by_status, by_dept=by_dept, overdue=overdue,
                               waiting=waiting, recent=recent, msg_count=msg_count,
                               last_sync=db.get_setting(conn, "gmail:last_sync", "chưa đồng bộ"))

    # ---------- Công việc ----------
    def _task_query(args):
        sql, params = "SELECT * FROM tasks WHERE 1=1", []
        for field in ("status", "department", "priority"):
            if args.get(field):
                sql += f" AND {field}=?"
                params.append(args[field])
        if args.get("open"):
            sql += " AND status NOT IN ('Hoàn thành','Huỷ')"
        if args.get("q"):
            sql += " AND (title LIKE ? OR description LIKE ? OR assignee LIKE ? OR note LIKE ?)"
            params += [f"%{args['q']}%"] * 4
        sql += (" ORDER BY CASE priority WHEN 'Khẩn' THEN 0 WHEN 'Cao' THEN 1 WHEN 'Bình thường' THEN 2 ELSE 3 END,"
                " CASE WHEN deadline='' THEN 1 ELSE 0 END, deadline, id DESC")
        return sql, params

    @app.route("/tasks")
    @login_required
    def tasks():
        sql, params = _task_query(request.args)
        rows = get_db().execute(sql, params).fetchall()
        return render_template("tasks.html", tasks=rows, args=request.args)

    @app.route("/tasks.csv")
    @login_required
    def tasks_csv():
        sql, params = _task_query(request.args)
        rows = get_db().execute(sql, params).fetchall()
        buf = io.StringIO()
        buf.write("﻿")  # để Excel đọc đúng tiếng Việt
        w = csv.writer(buf)
        w.writerow(["ID", "Công việc", "Phòng ban", "Trạng thái", "Ưu tiên", "Người phụ trách", "Hạn chót",
                    "Ghi chú", "Ngày tạo"])
        for r in rows:
            w.writerow([r["id"], r["title"], r["department"], r["status"], r["priority"], r["assignee"],
                        r["deadline"], r["note"], r["created_at"]])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=cong-viec.csv"})

    def _task_form():
        f = request.form
        return {k: f.get(k, "").strip() for k in
                ("title", "description", "department", "status", "priority", "assignee", "deadline", "note")}

    @app.route("/tasks/new", methods=["GET", "POST"])
    @login_required
    def task_new():
        conn = get_db()
        if request.method == "POST":
            data = _task_form()
            if not data["title"]:
                flash("Vui lòng nhập tên công việc", "error")
            else:
                mid = request.form.get("message_id") or None
                tid = db.insert_task(conn, message_id=int(mid) if mid else None, **data)
                conn.commit()
                flash("Đã tạo công việc", "ok")
                return redirect(url_for("task_detail", task_id=tid))
        msg = None
        if request.args.get("from_message"):
            msg = conn.execute("SELECT * FROM messages WHERE id=?", (request.args["from_message"],)).fetchone()
        task = {"title": classify.make_title(msg["subject"], msg["body"]) if msg else "",
                "description": msg["body"] if msg else "",
                "department": msg["department"] if msg else "Khác", "status": "Mới",
                "priority": classify.detect_priority(msg["body"]) if msg else "Bình thường",
                "assignee": "", "deadline": classify.detect_deadline(msg["body"]) if msg else "", "note": "",
                "message_id": msg["id"] if msg else ""}
        return render_template("task_form.html", task=task, msg=msg, is_new=True)

    @app.route("/tasks/<int:task_id>", methods=["GET", "POST"])
    @login_required
    def task_detail(task_id):
        conn = get_db()
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            return "Không tìm thấy công việc", 404
        if request.method == "POST":
            if request.form.get("action") == "delete":
                conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                conn.commit()
                flash("Đã xoá công việc", "ok")
                return redirect(url_for("tasks"))
            data = _task_form()
            conn.execute(
                """UPDATE tasks SET title=?, description=?, department=?, status=?, priority=?, assignee=?,
                   deadline=?, note=?, updated_at=? WHERE id=?""",
                (data["title"] or task["title"], data["description"], data["department"], data["status"],
                 data["priority"], data["assignee"], data["deadline"], data["note"], db.now(), task_id))
            conn.commit()
            flash("Đã lưu", "ok")
            return redirect(url_for("task_detail", task_id=task_id))
        msg = conn.execute("SELECT * FROM messages WHERE id=?", (task["message_id"],)).fetchone() \
            if task["message_id"] else None
        return render_template("task_form.html", task=task, msg=msg, is_new=False)

    @app.route("/tasks/<int:task_id>/status", methods=["POST"])
    @login_required
    def task_status(task_id):
        conn = get_db()
        status = request.form.get("status")
        if status in db.STATUSES:
            conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, db.now(), task_id))
            conn.commit()
        return redirect(request.referrer or url_for("tasks"))

    # ---------- Kho tin nhắn ----------
    @app.route("/messages")
    @login_required
    def messages():
        conn = get_db()
        sql, params = "SELECT * FROM messages WHERE 1=1", []
        for field in ("source", "channel", "department"):
            if request.args.get(field):
                sql += f" AND {field}=?"
                params.append(request.args[field])
        if request.args.get("q"):
            sql += " AND (subject LIKE ? OR body LIKE ? OR sender LIKE ?)"
            params += [f"%{request.args['q']}%"] * 3
        page = max(int(request.args.get("page", 1) or 1), 1)
        sql += " ORDER BY received_at DESC LIMIT 100 OFFSET ?"
        params.append((page - 1) * 100)
        rows = conn.execute(sql, params).fetchall()
        channels = [r["channel"] for r in conn.execute("SELECT DISTINCT channel FROM messages ORDER BY channel")]
        return render_template("messages.html", messages=rows, channels=channels, args=request.args, page=page)

    @app.route("/messages/<int:msg_id>")
    @login_required
    def message_detail(msg_id):
        conn = get_db()
        msg = conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
        if not msg:
            return "Không tìm thấy", 404
        linked = conn.execute("SELECT * FROM tasks WHERE message_id=?", (msg_id,)).fetchall()
        return render_template("message_detail.html", msg=msg, linked=linked)

    # ---------- Nhập dữ liệu ----------
    @app.route("/import/zalo", methods=["GET", "POST"])
    @login_required
    def import_zalo():
        if request.method == "POST":
            group = request.form.get("group", "").strip() or "Nhóm Zalo"
            auto = bool(request.form.get("auto_task"))
            file = request.files.get("file")
            try:
                if file and file.filename:
                    msgs = zalo.parse_file(file.filename, file.read().decode("utf-8-sig", errors="replace"))
                else:
                    msgs = zalo.parse_text(request.form.get("content", ""))
                st = zalo.import_messages(get_db(), group, msgs, auto_task=auto)
                flash(f"Nhóm “{group}”: đọc {st['total']} tin, lưu mới {st['new_messages']}, "
                      f"tạo {st['new_tasks']} công việc.", "ok")
            except Exception as e:  # noqa: BLE001
                flash(f"Lỗi nhập dữ liệu: {e}", "error")
            return redirect(url_for("import_zalo"))
        groups = [r["channel"] for r in get_db().execute(
            "SELECT DISTINCT channel FROM messages WHERE source='zalo' ORDER BY channel")]
        return render_template("import_zalo.html", groups=groups)

    @app.route("/sync/gmail", methods=["POST"])
    @login_required
    def sync_gmail():
        try:
            st = gmail_sync.sync(get_db())
            flash(f"Gmail: tải {st['fetched']} thư, lưu mới {st['new_messages']}, tạo {st['new_tasks']} công việc.", "ok")
        except Exception as e:  # noqa: BLE001
            flash(f"Lỗi đồng bộ Gmail: {e}", "error")
        return redirect(request.referrer or url_for("dashboard"))

    # ---------- API / Webhook ----------
    @app.route("/api/ingest", methods=["POST"])
    def api_ingest():
        token = request.args.get("token") or request.headers.get("X-Api-Token", "")
        if not app.config["API_TOKEN"] or not hmac.compare_digest(token, app.config["API_TOKEN"]):
            return jsonify(error="unauthorized"), 401
        payload = request.get_json(silent=True) or {}
        items = payload if isinstance(payload, list) else [payload]
        conn = get_db()
        total = {"new_messages": 0, "new_tasks": 0}
        for item in items:
            group, msg = zalo.from_webhook(item)
            if msg["text"]:
                st = zalo.import_messages(conn, group, [msg])
                total["new_messages"] += st["new_messages"]
                total["new_tasks"] += st["new_tasks"]
        return jsonify(ok=True, **total)

    return app
