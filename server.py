import os
import sqlite3
from datetime import datetime, timezone

from flask import Flask, jsonify, request, render_template, send_from_directory

app = Flask(__name__, static_folder="static", template_folder="templates")
DB_PATH = os.getenv("DB_PATH", "xyntrix.db")
SCRIPT_FILE = os.getenv("SCRIPT_FILE", "script.lua")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            key TEXT PRIMARY KEY,
            discord_id TEXT NOT NULL,
            username TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            hwid TEXT,
            created_at TEXT NOT NULL,
            last_used TEXT,
            uses INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_license(key):
    if not key:
        return None
    conn = db()
    row = conn.execute("SELECT * FROM licenses WHERE key=?", (key.strip().upper(),)).fetchone()
    conn.close()
    return row

def valid_license(key):
    row = get_license(key)
    return row is not None and row["active"] == 1

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/script")
def script_page():
    return render_template("script.html")

@app.route("/reset")
def reset_page():
    return render_template("reset.html")

@app.route("/stats")
def stats_page():
    conn = db()
    total = conn.execute("SELECT COUNT(*) c FROM licenses").fetchone()["c"]
    active = conn.execute("SELECT COUNT(*) c FROM licenses WHERE active=1").fetchone()["c"]
    uses = conn.execute("SELECT COALESCE(SUM(uses),0) c FROM licenses").fetchone()["c"]
    conn.close()
    return render_template("stats.html", total=total, active=active, uses=uses)

@app.post("/api/redeem")
def redeem():
    data = request.get_json(silent=True) or {}
    key = str(data.get("key", "")).strip().upper()
    row = get_license(key)

    if not row or not row["active"]:
        return jsonify(ok=False, error="Invalid or revoked key."), 400

    return jsonify(ok=True, message="Key is valid.", discord_id=row["discord_id"])

@app.get("/api/status")
def status():
    key = request.args.get("key", "")
    row = get_license(key)
    if not row:
        return jsonify(ok=False, error="Key not found."), 404

    return jsonify(
        ok=True,
        active=bool(row["active"]),
        uses=row["uses"],
        created_at=row["created_at"],
        last_used=row["last_used"]
    )

@app.get("/api/script")
def protected_script():
    key = request.args.get("key", "")
    row = get_license(key)

    if not row or not row["active"]:
        return "-- XYNTRIX: invalid or revoked license\n", 403

    now = datetime.now(timezone.utc).isoformat()
    conn = db()
    conn.execute(
        "UPDATE licenses SET uses=uses+1, last_used=? WHERE key=?",
        (now, key.strip().upper())
    )
    conn.commit()
    conn.close()

    if not os.path.exists(SCRIPT_FILE):
        return "-- XYNTRIX: script.lua is not installed yet\n", 503

    with open(SCRIPT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    return app.response_class(content, mimetype="text/plain")

@app.get("/health")
def health():
    return jsonify(status="ok", project="XYNTRIXREDEEMER")

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
