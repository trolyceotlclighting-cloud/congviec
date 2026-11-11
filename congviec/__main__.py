"""Dòng lệnh:
  python -m congviec run [--host 0.0.0.0] [--port 5000]   chạy web
  python -m congviec sync-gmail                            đồng bộ Gmail (dùng cho lịch chạy định kỳ)
  python -m congviec import-zalo "Tên nhóm" file.txt       nhập file hội thoại Zalo
"""
import argparse
import os

from . import db, gmail_sync, zalo
from .app import create_app, load_env


def main():
    load_env()
    p = argparse.ArgumentParser(prog="congviec")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    r.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    sub.add_parser("sync-gmail")
    z = sub.add_parser("import-zalo")
    z.add_argument("group")
    z.add_argument("file")
    args = p.parse_args()

    if args.cmd == "run":
        create_app().run(host=args.host, port=args.port)
    elif args.cmd == "sync-gmail":
        print(gmail_sync.sync(db.connect()))
    elif args.cmd == "import-zalo":
        with open(args.file, encoding="utf-8-sig") as f:
            msgs = zalo.parse_file(args.file, f.read())
        print(zalo.import_messages(db.connect(), args.group, msgs))


if __name__ == "__main__":
    main()
