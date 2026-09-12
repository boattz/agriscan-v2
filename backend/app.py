"""
Agriscan — Backend API (ข้อมูลจริงจาก ESP32)

รับค่าเซ็นเซอร์จริงจาก ESP32 เก็บลง PostgreSQL (หรือ SQLite เมื่อรันในเครื่อง)
และเสิร์ฟ dashboard + ค่าล่าสุดให้เว็บ

Endpoints:
  POST /api/readings  ← ESP32 ส่งค่า (ต้องมี header X-API-Key)
  GET  /api/latest    → ค่าล่าสุดจากฐานข้อมูล
  GET  /data          → alias ของ /api/latest (dashboard เดิมใช้เส้นนี้)
  GET  /health        → ตรวจสถานะ service + ฐานข้อมูล
  POST /api/alerts/test   → ส่งข้อความทดสอบเข้า LINE (กันสแปมด้วย cooldown)
  GET  /api/alerts/status → สถานะระบบแจ้งเตือน + alert ล่าสุด (ให้ dashboard)
  GET  /              → เสิร์ฟหน้า dashboard
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import alerts
import line_notify

# ── Config ──────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_DIR = os.path.join(BASE_DIR, "..", "dashboard")

# API key สำหรับกันคนอื่นส่งข้อมูลปลอม — ตั้งผ่าน env บน Render
API_KEY = os.environ.get("API_KEY", "agriscan-dev-key")

# ถ้าตั้ง DATABASE_URL (บน Render) จะใช้ PostgreSQL
# ถ้าไม่ตั้ง (รันในเครื่อง) จะใช้ SQLite file อัตโนมัติ
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# เก็บข้อมูลกี่วันแล้วลบทิ้งอัตโนมัติ (กัน database เต็ม) — ตั้งผ่าน env RETAIN_DAYS
RETAIN_DAYS = int(os.environ.get("RETAIN_DAYS", "7"))

# ── LINE Alerts (Phase 1: พืชเดียวกลาง + broadcast/push) ─────
# เกณฑ์พืชที่ใช้ตัดสิน — key ตาม dashboard/crops.js (เช่น rice, corn, other)
ALERT_CROP = os.environ.get("ALERT_CROP", "other")
# ความรุนแรงขั้นต่ำที่จะส่ง: warn = เอาหมด, alert = เฉพาะวิกฤต
ALERT_MIN_SEVERITY = os.environ.get("ALERT_MIN_SEVERITY", "warn")
# กันสแปม: alert เดิมส่งซ้ำได้ทุกกี่นาที (โควต้า Messaging API ฟรี 200/เดือน)
ALERT_COOLDOWN_MIN = int(os.environ.get("ALERT_COOLDOWN_MIN", "60"))
# เป้าหมาย: broadcast = ผู้ติดตาม OA ทุกคน · push = ส่งหา LINE_TARGET_ID เดียว
LINE_TARGET_MODE = os.environ.get("LINE_TARGET_MODE", "broadcast")
LINE_TARGET_ID = os.environ.get("LINE_TARGET_ID", "")
# ลิงก์เพิ่มเพื่อน OA (เช่น https://lin.ee/xxxxxxx) + URL สาธารณะของ dashboard
LINE_ADD_FRIEND_URL = os.environ.get("LINE_ADD_FRIEND_URL", "")
DASHBOARD_PUBLIC_URL = os.environ.get(
    "DASHBOARD_PUBLIC_URL", "https://agriscan-v2.onrender.com")
# cooldown ของปุ่มส่งทดสอบ (นาที) — กันกดรัวเปลืองโควต้า
TEST_COOLDOWN_MIN = int(os.environ.get("TEST_COOLDOWN_MIN", "10"))

# ทำงาน cleanup ทุกกี่ครั้งที่รับค่า (ไม่ต้องลบทุก insert — ประหยัด resource)
CLEANUP_EVERY = 50
_cleanup_counter = 0

app = Flask(__name__)
CORS(app)

# ── Database ────────────────────────────────────────────────
if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS readings (
        id         SERIAL PRIMARY KEY,
        moisture   REAL,
        temperature REAL,
        ec         INTEGER,
        ph         REAL,
        n          INTEGER,
        p          INTEGER,
        k          INTEGER,
        valid      BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    PARAM = "%s"
else:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS readings (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        moisture   REAL,
        temperature REAL,
        ec         INTEGER,
        ph         REAL,
        n          INTEGER,
        p          INTEGER,
        k          INTEGER,
        valid      INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    PARAM = "?"


# ── Alert state (กันส่ง LINE ซ้ำ — alert key ละ 1 แถว) ────────
if DATABASE_URL:
    ALERT_STATE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS alert_state (
        alert_key    TEXT PRIMARY KEY,
        severity     TEXT DEFAULT '',
        last_sent_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
else:
    ALERT_STATE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS alert_state (
        alert_key    TEXT PRIMARY KEY,
        severity     TEXT DEFAULT '',
        last_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """


def get_conn():
    """คืน connection — PostgreSQL เมื่อมี DATABASE_URL, ไม่เช่นนั้น SQLite"""
    if DATABASE_URL:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    conn = sqlite3.connect(os.path.join(BASE_DIR, "agriscan.db"))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    try:
        with get_conn() as conn:
            conn.execute(SCHEMA)
            conn.execute(ALERT_STATE_SCHEMA)
            conn.commit()
        print("[OK] Database พร้อมใช้งาน" + (" (PostgreSQL)" if DATABASE_URL else " (SQLite local)"))
    except Exception as e:
        print("[WARN] Database init ล้มเหลว:", e)


def cleanup_old_readings():
    """ลบข้อมูลที่เก่ากว่า RETAIN_DAYS วันออก — กัน database เต็ม"""
    try:
        with get_conn() as conn:
            if DATABASE_URL:
                conn.execute(
                    "DELETE FROM readings WHERE created_at < NOW() - INTERVAL '%s days'"
                    % RETAIN_DAYS
                )
            else:
                conn.execute(
                    "DELETE FROM readings WHERE created_at < datetime('now', '-%d days')"
                    % RETAIN_DAYS
                )
            conn.commit()
        print(f"[OK] Cleanup: ลบข้อมูลเก่ากว่า {RETAIN_DAYS} วันแล้ว")
    except Exception as e:
        print("[WARN] Cleanup ล้มเหลว:", e)


def row_to_json(row):
    ts = row["created_at"]
    return {
        "moisture":    float(row["moisture"]) if row["moisture"] is not None else None,
        "temperature": float(row["temperature"]) if row["temperature"] is not None else None,
        "ec":          row["ec"],
        "ph":          float(row["ph"]) if row["ph"] is not None else None,
        "n":           row["n"],
        "p":           row["p"],
        "k":           row["k"],
        "valid":       bool(row["valid"]),
        # PostgreSQL คืน datetime ส่วน SQLite คืน string
        "timestamp":   ts.isoformat() if isinstance(ts, datetime) else ts,
    }


# ── LINE Alert worker ───────────────────────────────────────
def _parse_ts(value):
    """parse created_at/last_sent_at ที่อาจเป็น datetime หรือ string"""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _cooldown_expired(alert_key, cooldown_min):
    """alert นี้พ้น cooldown แล้วหรือยัง (True = ส่งได้)"""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                f"SELECT last_sent_at FROM alert_state WHERE alert_key = {PARAM}",
                (alert_key,),
            )
            row = cur.fetchone()
    except Exception as e:
        print("[Alert] อ่าน alert_state ล้มเหลว (ยอมให้ส่ง):", e)
        return True
    if row is None:
        return True
    ts = _parse_ts(row["last_sent_at"])
    if ts is None:
        return True
    age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
    return age_min >= cooldown_min


def _mark_sent(alert_key, severity):
    try:
        with get_conn() as conn:
            if DATABASE_URL:
                conn.execute(
                    "INSERT INTO alert_state (alert_key, severity, last_sent_at) "
                    "VALUES (%s, %s, NOW()) "
                    "ON CONFLICT (alert_key) DO UPDATE SET "
                    "severity = EXCLUDED.severity, last_sent_at = NOW()",
                    (alert_key, severity),
                )
            else:
                conn.execute(
                    "INSERT INTO alert_state (alert_key, severity, last_sent_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (alert_key) DO UPDATE SET "
                    "severity = excluded.severity, "
                    "last_sent_at = CURRENT_TIMESTAMP",
                    (alert_key, severity),
                )
            conn.commit()
    except Exception as e:
        print("[Alert] บันทึก alert_state ล้มเหลว:", e)


def evaluate_and_notify(reading):
    """ประเมิน 1 reading แล้วส่ง LINE (รันใน background thread — ห้ามบล็อก API)

    กติกันสแปม: ส่งเฉพาะ alert ที่พ้น cooldown แล้ว รวมเป็นข้อความเดียว
    """
    crop_key = alerts.get_crop_key(ALERT_CROP)
    items = alerts.filter_by_severity(
        alerts.evaluate(reading, crop_key), ALERT_MIN_SEVERITY)
    if not items:
        return {"sent": False, "reason": "no alerts"}

    fresh = [i for i in items if _cooldown_expired(i["key"], ALERT_COOLDOWN_MIN)]
    if not fresh:
        return {"sent": False, "reason": "cooldown",
                "suppressed": [i["key"] for i in items]}

    crop = alerts.get_crop(crop_key)
    now_str = datetime.now().strftime("%H:%M:%S")
    text = alerts.format_line_message(
        crop["label"], crop["icon"], fresh,
        dashboard_url=DASHBOARD_PUBLIC_URL, time_str=now_str)

    ok, info = line_notify.send_text(
        text, mode=LINE_TARGET_MODE, target_id=LINE_TARGET_ID)
    if ok:
        for i in fresh:
            _mark_sent(i["key"], i["severity"])
        print(f"[Alert] ส่ง LINE แล้ว {len(fresh)} รายการ ({LINE_TARGET_MODE})")
    return {"sent": ok, "count": len(fresh),
            "keys": [i["key"] for i in fresh], "info": info}


def _notify_async(reading):
    t = threading.Thread(target=evaluate_and_notify, args=(reading,), daemon=True)
    t.start()


# ── Routes ──────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    # เสิร์ฟ dashboard (poll /data บน origin เดียวกัน)
    return send_from_directory(DASHBOARD_DIR, "index.html")


@app.route("/<path:path>", methods=["GET"])
def static_files(path):
    # assets: style.css, script.js ฯลฯ
    return send_from_directory(DASHBOARD_DIR, path)


@app.route("/health", methods=["GET"])
def health():
    db_ok = False
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass
    return jsonify({"status": "healthy", "db": "connected" if db_ok else "unavailable"})


@app.route("/api/readings", methods=["POST"])
def add_reading():
    """ESP32 ส่งค่าเซ็นเซอร์จริงมาบันทึกลงฐานข้อมูล"""
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "unauthorized — X-API-Key ไม่ถูกต้อง"}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "ต้องส่ง JSON body"}), 400

    fields = ["moisture", "temperature", "ec", "ph", "n", "p", "k"]
    row = {f: data.get(f) for f in fields}

    # ตรวจสอบขั้นต่ำ — ต้องมี moisture เสมอ
    if row["moisture"] is None:
        return jsonify({"error": "missing required field: moisture"}), 400

    valid = bool(data.get("valid", True))
    placeholders = ", ".join([PARAM] * (len(fields) + 1))
    sql = (
        "INSERT INTO readings (moisture, temperature, ec, ph, n, p, k, valid) "
        f"VALUES ({placeholders})"
    )

    try:
        with get_conn() as conn:
            conn.execute(sql, (*[row[f] for f in fields], valid))
            conn.commit()
    except Exception as e:
        print("⚠ Insert ล้มเหลว:", e)
        return jsonify({"error": "database error"}), 500

    # ลบข้อมูลเก่าเป็นระยะ ๆ (ทุก CLEANUP_EVERY ครั้งที่รับค่า) — กัน DB เต็ม
    global _cleanup_counter
    _cleanup_counter += 1
    if _cleanup_counter % CLEANUP_EVERY == 0:
        cleanup_old_readings()

    # ประเมิน alert + ส่ง LINE แบบ async (ไม่บล็อก response 201)
    _notify_async({**row, "valid": valid})

    return jsonify({"success": True}), 201


@app.route("/api/latest", methods=["GET"])
def latest():
    """ค่าล่าสุดจากฐานข้อมูล (ข้อมูลจริงจาก ESP32)"""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT moisture, temperature, ec, ph, n, p, k, valid, created_at "
                "FROM readings ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
    except Exception as e:
        print("⚠ Query ล้มเหลว:", e)
        return jsonify({"error": "database unavailable"}), 503

    if row is None:
        return jsonify({"error": "ยังไม่มีข้อมูล — รอ ESP32 ส่งค่ามาก่อน"}), 404

    return jsonify(row_to_json(row))


@app.route("/data", methods=["GET"])
def data():
    """alias ของ /api/latest — ใช้กับ dashboard เดิมที่ไม่ต้องแก้เส้นทาง"""
    return latest()


@app.route("/api/alerts/test", methods=["POST"])
def alerts_test():
    """ส่งข้อความทดสอบเข้า LINE — กันกดรัวด้วย cooldown (default 10 นาที)

    body (optional): ค่าเซ็นเซอร์จำลอง {"moisture":..,"temperature":..,"ec":..,
                     "ph":..,"n":..,"p":..,"k":..}
    ?dry=1 → ส่งแค่ preview ไม่ยิงจริง
    """
    if not _cooldown_expired("manual_test", TEST_COOLDOWN_MIN):
        return jsonify({"sent": False,
                        "reason": f"cooldown — กดได้ทุก {TEST_COOLDOWN_MIN} นาที"}), 429

    body = request.get_json(silent=True) or {}
    reading = {f: body.get(f) for f in
               ["moisture", "temperature", "ec", "ph", "n", "p", "k"]}

    # ไม่มี body → ใช้ค่าล่าสุดจาก DB มาประเมิน
    if all(v is None for v in reading.values()):
        try:
            with get_conn() as conn:
                cur = conn.execute(
                    "SELECT moisture, temperature, ec, ph, n, p, k, valid, "
                    "created_at FROM readings ORDER BY id DESC LIMIT 1"
                )
                latest_row = cur.fetchone()
        except Exception as e:
            return jsonify({"error": "database unavailable"}), 503
        if latest_row is None:
            return jsonify({"error": "ยังไม่มีข้อมูล — รอ ESP32 ส่งค่ามาก่อน"}), 404
        reading = {f: latest_row[f] for f in
                   ["moisture", "temperature", "ec", "ph", "n", "p", "k"]}

    crop_key = alerts.get_crop_key(ALERT_CROP)
    items = alerts.filter_by_severity(
        alerts.evaluate(reading, crop_key), ALERT_MIN_SEVERITY)
    crop = alerts.get_crop(crop_key)
    text = alerts.format_line_message(
        crop["label"], crop["icon"],
        items or [{"key": "ok", "severity": "warn", "icon": "✅",
                   "title": "ค่าปกติ", "short": "ทุกค่าอยู่ในเกณฑ์ — ระบบพร้อมแจ้งเตือน"}],
        dashboard_url=DASHBOARD_PUBLIC_URL, prefix="🔔 Agriscan ทดสอบ")

    if request.args.get("dry") == "1":
        return jsonify({"sent": False, "dry": True, "preview": text})

    ok, info = line_notify.send_text(
        text, mode=LINE_TARGET_MODE, target_id=LINE_TARGET_ID)
    if ok:
        _mark_sent("manual_test", "warn")
    return jsonify({"sent": ok, "preview": text, "info": info})


@app.route("/api/alerts/status", methods=["GET"])
def alerts_status():
    """สถานะระบบแจ้งเตือนให้ dashboard (ไม่เปิดเผย token)"""
    crop_key = alerts.get_crop_key(ALERT_CROP)
    crop = alerts.get_crop(crop_key)

    latest_age_s, stale = None, None
    row = None
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT created_at FROM readings ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            cur = conn.execute(
                "SELECT alert_key, severity, last_sent_at FROM alert_state "
                "WHERE alert_key != 'manual_test' "
                "ORDER BY last_sent_at DESC LIMIT 5")
            last_alerts = [
                {"key": r["alert_key"], "severity": r["severity"],
                 "at": (r["last_sent_at"].isoformat()
                        if isinstance(r["last_sent_at"], datetime)
                        else r["last_sent_at"])}
                for r in cur.fetchall()
            ]
    except Exception:
        last_alerts = []
    if row is not None:
        ts = _parse_ts(row["created_at"])
        if ts is not None:
            latest_age_s = int((datetime.now(timezone.utc) - ts).total_seconds())
            stale = latest_age_s > 600  # เงียบเกิน 10 นาที = น่าสงสัย

    return jsonify({
        "line_configured": line_notify.is_configured(),
        "dry_run": line_notify.is_dry_run(),
        "target_mode": LINE_TARGET_MODE,
        "crop": crop_key,
        "crop_label": f"{crop['icon']} {crop['label']}",
        "min_severity": ALERT_MIN_SEVERITY,
        "cooldown_min": ALERT_COOLDOWN_MIN,
        "add_friend_url": LINE_ADD_FRIEND_URL,
        "last_alerts": last_alerts,
        "latest_age_s": latest_age_s,
        "stale": stale,
    })


init_db()
cleanup_old_readings()  # ลบทิ้งข้อมูลเก่าครั้งแรกตอน service เริ่ม

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
