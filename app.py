"""接收 HC Webhook 推送的 Health Connect 数据，落 SQLite，供 hermes 拉取。"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))
DB_PATH = Path(CONFIG["data_dir"]) / "health.db"

ENVELOPE_KEYS = {"timestamp", "app_version"}
TIME_FIELDS = ("time", "start_time", "session_end_time")

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    ts          TEXT NOT NULL,
    payload     TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE(type, ts, payload)
);
CREATE INDEX IF NOT EXISTS idx_type_ts ON records(type, ts);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def record_time(record):
    for field in TIME_FIELDS:
        if field in record:
            return record[field]
    return None


def store(body):
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    stored = 0
    for type_, records in body.items():
        if type_ in ENVELOPE_KEYS:
            continue
        for record in records:
            cur = conn.execute(
                "INSERT OR IGNORE INTO records(type, ts, payload, received_at) VALUES (?, ?, ?, ?)",
                (
                    type_,
                    record_time(record),
                    json.dumps(record, sort_keys=True, separators=(",", ":")),
                    now,
                ),
            )
            stored += cur.rowcount
    conn.commit()
    conn.close()
    return stored


def export(days):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = connect()
    rows = conn.execute(
        "SELECT type, payload FROM records WHERE ts >= ? ORDER BY ts", (since,)
    ).fetchall()
    conn.close()
    grouped = {}
    for type_, payload in rows:
        grouped.setdefault(type_, []).append(json.loads(payload))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "records": grouped,
    }


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        return self.headers.get("x-api-key") == CONFIG["ingest_key"]

    def do_POST(self):
        if urlparse(self.path).path != "/ingest":
            self.send_error(404)
            return
        if not self.authorized():
            self.send_error(401)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.reply(200, {"ok": True, "stored": store(body)})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/ping":
            self.reply(200, {"ok": True})
            return
        if not self.authorized():
            self.send_error(401)
            return
        if parsed.path == "/export":
            self.reply(200, export(int(parse_qs(parsed.query)["days"][0])))
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    host, port = CONFIG["listen"].rsplit(":", 1)
    HTTPServer((host, int(port)), Handler).serve_forever()
