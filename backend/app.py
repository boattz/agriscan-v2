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
  POST /api/line/webhook  ← รับ event จาก LINE OA (เก็บ userId + ตอบยืนยัน)
  GET  /api/line/subscribers → ดู userId ที่ลงทะเบียน (ต้องมี X-API-Key)
  GET  /api/alerts/crops  → รายชื่อพืชทั้งหมด (ให้ dropdown)
  GET/POST /api/alerts/crop → ดู/เปลี่ยนพืชที่ใช้ตัดสิน alert
  GET  /              → เสิร์ฟหน้า dashboard
"""

import base64
import hashlib
import hmac
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

# ── LINE Alerts (พืชเดียวกลาง + ส่งหาผู้ลงทะเบียน) ───────────
# เกณฑ์พืชที่ใช้ตัดสิน — key ตาม dashboard/crops.js (เช่น rice, corn, other)
ALERT_CROP = os.environ.get("ALERT_CROP", "other")
# ความรุนแรงขั้นต่ำที่จะส่ง: alert = เฉพาะเรื่องสำคัญ (default)
# อยากได้เตือนละเอียดด้วยตั้ง warn (รวมดินชื้นเกิน/pH เบี่ยง/N-P-K ปานกลาง)
ALERT_MIN_SEVERITY = os.environ.get("ALERT_MIN_SEVERITY", "alert")
# กันเตือนรัว: cooldown เป็นแค่ตาข่ายกัน flapping (หายแล้วเป็นใหม่ถี่ๆ)
# ปกติส่งครั้งเดียวตอนอาการเกิดใหม่เท่านั้น ไม่ส่งซ้ำทุกชั่วโมง
ALERT_COOLDOWN_MIN = int(os.environ.get("ALERT_COOLDOWN_MIN", "60"))
# ส่งให้ใคร: ผู้ลงทะเบียนในตาราง line_subscribers ทุกคน (multicast)
# ลงทะเบียนโดยแอด OA แล้วทักแชท 1 ครั้ง (webhook เก็บ userId ให้เอง)
# Channel secret (Developers Console -> Messaging API) - ใช้ตรวจ webhook signature
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
# ลิงก์เพิ่มเพื่อน OA (เช่น https://lin.ee/xxxxxxx) + URL สาธารณะของ dashboard
LINE_ADD_FRIEND_URL = os.environ.get("LINE_ADD_FRIEND_URL", "")
DASHBOARD_PUBLIC_URL = os.environ.get(
    "DASHBOARD_PUBLIC_URL", "https://agriscan-v2.onrender.com")
# cooldown ของปุ่มส่งทดสอบ (นาที) — กันกดรัวเปลืองโควต้า
TEST_COOLDOWN_MIN = int(os.environ.get("TEST_COOLDOWN_MIN", "10"))

# ทำงาน cleanup ทุกกี่ครั้งที่รับค่า (ไม่ต้องลบทุก insert — ประหยัด resource)
CLEANUP_EVERY = 50
_cleanup_counter = 0

# ── Validation (mirror ขอบเขตใน agriscan.ino — แก้ที่ใดที่หนึ่งต้องแก้อีกที่) ──
# bad = หลุดโลก → reject 422 ไม่เก็บ · suspect = แปลกแต่เป็นไปได้ → เก็บพร้อม flag
VALID_RANGES = {
    "moisture":    (0.0, 100.0),
    "temperature": (-10.0, 60.0),
    "ec":          (0, 20000),
    "ph":          (0.0, 14.0),
    "n":           (0, 1999),
    "p":           (0, 1999),
    "k":           (0, 1999),
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_reading(row):
    """ตรวจ 1 reading → (decision, quality, reasons)

    decision: 'reject' | 'accept' · quality: 'good' | 'suspect' | 'bad'
    ESP32 ส่ง quality/reason มาด้วยก็ไม่ไว้ใจทั้งหมด — ตรวจซ้ำฝั่ง server เสมอ
    """
    reasons = []
    for f, (lo, hi) in VALID_RANGES.items():
        v = _num(row.get(f))
        if v is None:
            if f == "moisture":
                reasons.append("missing:moisture")
            continue
        if v < lo or v > hi:
            reasons.append(f"out_of_range:{f}")
    if reasons:
        return "reject", "bad", reasons

    suspect = []
    t, ec, ph = _num(row.get("temperature")), _num(row.get("ec")), _num(row.get("ph"))
    if t is not None and t > 50.0:
        suspect.append("suspect:temp_high")
    if ec is not None and ec > 5000:
        suspect.append("suspect:ec_high")
    if ph is not None and (ph < 3.0 or ph > 10.0):
        suspect.append("suspect:ph_extreme")
    # เคารพ flag จาก ESP32 (เช่น suspect:unstable จาก median spread)
    fw_reason = str(row.get("reason") or "")
    if fw_reason.startswith("suspect:") and fw_reason not in suspect:
        suspect.append(fw_reason)
    if suspect:
        return "accept", "suspect", suspect
    return "accept", "good", ["ok"]

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
        quality    TEXT DEFAULT 'good',
        reason     TEXT DEFAULT 'ok',
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
        quality    TEXT DEFAULT 'good',
        reason     TEXT DEFAULT 'ok',
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
    LINE_SUBSCRIBERS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS line_subscribers (
        line_user_id VARCHAR(50) PRIMARY KEY,
        display_name VARCHAR(100),
        active       BOOLEAN DEFAULT TRUE,
        subscribed_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    SETTINGS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
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
    LINE_SUBSCRIBERS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS line_subscribers (
        line_user_id TEXT PRIMARY KEY,
        display_name TEXT,
        active       INTEGER DEFAULT 1,
        subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    SETTINGS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
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
            conn.execute(LINE_SUBSCRIBERS_SCHEMA)
            conn.execute(SETTINGS_SCHEMA)
            # migration ตารางเก่าที่ไม่มี quality/reason (กัน QueryError หลังอัปเดต)
            for col in ("quality TEXT DEFAULT 'good'", "reason TEXT DEFAULT 'ok'"):
                try:
                    if DATABASE_URL:
                        conn.execute(
                            "ALTER TABLE readings ADD COLUMN IF NOT EXISTS %s"
                            % col)
                    else:
                        conn.execute("ALTER TABLE readings ADD COLUMN %s" % col)
                except Exception:
                    pass  # SQLite: มีคอลัมน์แล้ว → duplicate column, ข้ามได้
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
    keys = row.keys() if hasattr(row, "keys") else []
    return {
        "moisture":    float(row["moisture"]) if row["moisture"] is not None else None,
        "temperature": float(row["temperature"]) if row["temperature"] is not None else None,
        "ec":          row["ec"],
        "ph":          float(row["ph"]) if row["ph"] is not None else None,
        "n":           row["n"],
        "p":           row["p"],
        "k":           row["k"],
        "valid":       bool(row["valid"]),
        "quality":     row["quality"] if "quality" in keys and row["quality"] else "good",
        "reason":      row["reason"] if "reason" in keys and row["reason"] else "ok",
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


def _get_alert_states():
    """สถานะทุก key: {key: (severity, last_sent_at)} — severity 'clear' = หายแล้ว"""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT alert_key, severity, last_sent_at FROM alert_state")
            return {r["alert_key"]: (r["severity"] or "",
                                     _parse_ts(r["last_sent_at"]))
                    for r in cur.fetchall()}
    except Exception as e:
        print("[Alert] อ่าน alert_state ล้มเหลว:", e)
        return {}


def _cooldown_ok(last_sent, cooldown_min):
    if last_sent is None:
        return True
    age_min = (datetime.now(timezone.utc) - last_sent).total_seconds() / 60
    return age_min >= cooldown_min


def _cooldown_expired(alert_key, cooldown_min):
    """ปุ่มทดสอบใช้ — ดูแค่เวลา (True = ส่งได้)"""
    states = _get_alert_states()
    _, last_sent = states.get(alert_key, ("", None))
    return _cooldown_ok(last_sent, cooldown_min)


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


def _get_active_subscriber_ids():
    """userId ผู้รับ alert (active) — ไม่มีใคร = ยังไม่ส่ง"""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT line_user_id FROM line_subscribers WHERE active = "
                + ("TRUE" if DATABASE_URL else "1")
            )
            return [r["line_user_id"] for r in cur.fetchall()
                    if r["line_user_id"]]
    except Exception as e:
        print("[Alert] อ่าน subscribers ล้มเหลว:", e)
        return []


def evaluate_and_notify(reading):
    """ประเมิน 1 reading แล้วส่ง LINE (รันใน background thread — ห้ามบล็อก API)

    ไม่เตือนรัว: ส่งครั้งเดียวตอนอาการ 'เกิดใหม่' เท่านั้น
    - ยังเป็นอยู่ (เคยส่งแล้ว) → เงียบ
    - หายแล้วกลับมาเป็นอีก → เตือนซ้ำได้ (กัน flapping ด้วย cooldown)
    """
    # ค่าไม่น่าเชื่อถือ (valid=false / quality=bad) → ไม่ประเมิน ไม่ส่ง LINE
    if not reading.get("valid", True) or reading.get("quality") == "bad":
        return {"sent": False, "reason": "invalid reading — skipped"}
    crop_key = _effective_crop()
    items = alerts.filter_by_severity(
        alerts.evaluate(reading, crop_key), ALERT_MIN_SEVERITY)
    now_active = {i["key"]: i for i in items}
    states = _get_alert_states()

    # key ที่เคย active แต่ตอนนี้หายแล้ว → ตั้งเป็น clear (เงียบ ไม่ส่ง)
    for key, (sev, _) in states.items():
        if key == "manual_test":
            continue
        if key not in now_active and sev in ("alert", "warn"):
            _mark_sent(key, "clear")
            print(f"[Alert] {key} กลับสู่เกณฑ์แล้ว — รอบหน้าเป็นอีกค่อยเตือน")

    # ส่งเฉพาะ key ที่เพิ่งเกิดใหม่ (ไม่เคย active) + พ้น cooldown กัน flapping
    fresh = [i for key, i in now_active.items()
             if states.get(key, ("", None))[0] not in ("alert", "warn")
             and _cooldown_ok(states.get(key, ("", None))[1],
                             ALERT_COOLDOWN_MIN)]
    if not fresh:
        return {"sent": False, "reason": "no new alerts"}

    user_ids = _get_active_subscriber_ids()
    if not user_ids:
        print("[Alert] มี alert แต่ยังไม่มีผู้ลงทะเบียน — ข้ามการส่ง "
              "(แอด OA แล้วทักแชท 1 ครั้งเพื่อลงทะเบียน)")
        return {"sent": False, "reason": "no subscribers",
                "keys": [i["key"] for i in fresh]}

    crop = alerts.get_crop(crop_key)
    now_str = datetime.now().strftime("%H:%M:%S")
    card = alerts.format_flex_alert(
        crop["label"], crop["icon"], fresh,
        dashboard_url=DASHBOARD_PUBLIC_URL, time_str=now_str)

    ok, info = line_notify.multicast_msg(user_ids, card)
    if ok:
        for i in fresh:
            _mark_sent(i["key"], i["severity"])
        print(f"[Alert] ส่ง LINE แล้ว {len(fresh)} รายการ "
              f"-> {info.get('count', 0)} คน")
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

    # ตรวจซ้ำฝั่ง server (ไม่ไว้ใจ firmware อย่างเดียว)
    # bad → 422 ทิ้ง ไม่เก็บ ไม่ยิง LINE · suspect → เก็บพร้อม flag
    decision, quality, reasons = validate_reading({**row, **data})
    if decision == "reject":
        print(f"⚠ Reject reading หลุดโลก: {reasons} <- {row}")
        return jsonify({"error": "ค่าหลุดช่วงที่เป็นไปได้",
                        "reasons": reasons}), 422

    valid = bool(data.get("valid", True))
    if not valid:
        quality = "bad"
        reasons = [str(data.get("reason") or "firmware invalid")]
    reason_str = ",".join(reasons[:3])
    placeholders = ", ".join([PARAM] * (len(fields) + 3))
    sql = (
        "INSERT INTO readings (moisture, temperature, ec, ph, n, p, k, valid, "
        "quality, reason) "
        f"VALUES ({placeholders})"
    )

    try:
        with get_conn() as conn:
            conn.execute(sql, (*[row[f] for f in fields], valid, quality,
                                reason_str))
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
    # ข้ามเมื่อ suspect/bad ที่เป็น sensor-error? — suspect ยังเตือนได้ (ค่าจริงแต่แปลก),
    # bad ไม่ถึงจุดนี้แล้ว (reject ข้างบน) ยกเว้น firmware valid=false ที่ผ่านมาแบบ quality=bad
    if quality != "bad":
        _notify_async({**row, "valid": valid, "quality": quality})

    return jsonify({"success": True, "quality": quality,
                    "reasons": reasons}), 201


@app.route("/api/latest", methods=["GET"])
def latest():
    """ค่าล่าสุดจากฐานข้อมูล (ข้อมูลจริงจาก ESP32)"""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT moisture, temperature, ec, ph, n, p, k, valid, "
                "quality, reason, created_at "
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
                    "quality, reason, created_at FROM readings "
                    "ORDER BY id DESC LIMIT 1"
                )
                latest_row = cur.fetchone()
        except Exception as e:
            return jsonify({"error": "database unavailable"}), 503
        if latest_row is None:
            return jsonify({"error": "ยังไม่มีข้อมูล — รอ ESP32 ส่งค่ามาก่อน"}), 404
        reading = {f: latest_row[f] for f in
                   ["moisture", "temperature", "ec", "ph", "n", "p", "k"]}

    crop_key = _effective_crop()
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

    user_ids = _get_active_subscriber_ids()
    if not user_ids:
        return jsonify({"sent": False, "preview": text,
                        "reason": "ยังไม่มีผู้ลงทะเบียน — "
                                  "แอด OA แล้วทักแชท 1 ครั้งก่อน"}), 400

    card = alerts.format_flex_alert(
        crop["label"], crop["icon"], items,
        dashboard_url=DASHBOARD_PUBLIC_URL)
    ok, info = line_notify.multicast_msg(
        user_ids,
        [{"type": "text", "text": "ทดสอบระบบแจ้งเตือน Agriscan"}, card])
    if ok:
        _mark_sent("manual_test", "warn")
    return jsonify({"sent": ok, "preview": text, "info": info})


@app.route("/api/alerts/status", methods=["GET"])
def alerts_status():
    """สถานะระบบแจ้งเตือนให้ dashboard (ไม่เปิดเผย token)"""
    crop_key = _effective_crop()
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
        "target": "subscribers",
        "crop": crop_key,
        "crop_label": f"{crop['icon']} {crop['label']}",
        "min_severity": ALERT_MIN_SEVERITY,
        "cooldown_min": ALERT_COOLDOWN_MIN,
        "add_friend_url": LINE_ADD_FRIEND_URL,
        "subscribers": _count_subscribers(),
        "active_alerts": sorted(
            k for k, (sev, _) in _get_alert_states().items()
            if k != "manual_test" and sev in ("alert", "warn")),
        "last_alerts": last_alerts,
        "latest_age_s": latest_age_s,
        "stale": stale,
    })


# ── LINE webhook: เก็บ userId ผู้ติดตาม (แบบ Agriflow) ───────
def _verify_line_signature(raw, signature):
    """ตรวจ X-LINE-Signature — ไม่ตั้ง secret ถือว่าผ่าน (dev)"""
    if not LINE_CHANNEL_SECRET:
        return True
    if not signature or not raw:
        return False
    mac = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), raw,
                   hashlib.sha256).digest()
    try:
        return hmac.compare_digest(
            base64.b64encode(mac).decode(),
            signature,
        )
    except Exception:
        return False


def _save_subscriber(user_id, active=True):
    try:
        with get_conn() as conn:
            if DATABASE_URL:
                conn.execute(
                    "INSERT INTO line_subscribers (line_user_id, active, "
                    "subscribed_at) VALUES (%s, %s, NOW()) "
                    "ON CONFLICT (line_user_id) DO UPDATE SET active = "
                    "EXCLUDED.active",
                    (user_id, active),
                )
            else:
                conn.execute(
                    "INSERT INTO line_subscribers (line_user_id, active, "
                    "subscribed_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (line_user_id) DO UPDATE SET active = "
                    "excluded.active",
                    (user_id, 1 if active else 0),
                )
            conn.commit()
    except Exception as e:
        print("[Alert] บันทึก subscriber ล้มเหลว:", e)


def _set_subscriber_name(user_id, name):
    if not name:
        return
    try:
        with get_conn() as conn:
            conn.execute(
                f"UPDATE line_subscribers SET display_name = {PARAM} "
                f"WHERE line_user_id = {PARAM}",
                (name, user_id),
            )
            conn.commit()
    except Exception as e:
        print("[Alert] บันทึกชื่อ subscriber ล้มเหลว:", e)


def _count_subscribers():
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM line_subscribers WHERE active = "
                + ("TRUE" if DATABASE_URL else "1")
            )
            row = cur.fetchone()
            return int(row["c"]) if row else 0
    except Exception:
        return 0


def _get_setting(key, default=""):
    try:
        with get_conn() as conn:
            cur = conn.execute(
                f'SELECT "value" FROM settings WHERE "key" = {PARAM}', (key,))
            row = cur.fetchone()
            if row is None:
                return default
            return row["value"] if row["value"] != "" else default
    except Exception:
        return default


def _set_setting(key, value):
    try:
        with get_conn() as conn:
            if DATABASE_URL:
                conn.execute(
                    'INSERT INTO settings ("key", "value") VALUES (%s, %s) '
                    'ON CONFLICT ("key") DO UPDATE SET "value" = '
                    "EXCLUDED.value",
                    (key, value),
                )
            else:
                conn.execute(
                    'INSERT INTO settings ("key", "value") VALUES (?, ?) '
                    'ON CONFLICT ("key") DO UPDATE SET "value" = '
                    "excluded.value",
                    (key, value),
                )
            conn.commit()
            return True
    except Exception as e:
        print("[Alert] บันทึก setting ล้มเหลว:", e)
        return False


def _effective_crop():
    """พืชที่ใช้ตัดสิน alert — ค่าที่เลือกผ่าน dashboard มาก่อน, env เป็น default"""
    return alerts.get_crop_key(_get_setting("alert_crop", ALERT_CROP))


def _latest_reading():
    """ค่าล่าสุดจาก DB (ให้บอทตอบ 'สถานะ')"""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT moisture, temperature, ec, ph, n, p, k, valid, "
                "quality, reason, created_at FROM readings "
                "ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row is None:
                return None
            keys = row.keys() if hasattr(row, "keys") else []
            out = {f: row[f] for f in
                   ["moisture", "temperature", "ec", "ph", "n", "p", "k"]}
            out["quality"] = row["quality"] if "quality" in keys else "good"
            out["reason"] = row["reason"] if "reason" in keys else "ok"
            try:
                out["valid"] = bool(row["valid"])
            except Exception:
                out["valid"] = True
            return out
    except Exception:
        return None


HOWTO_TEXT = (
    "วิธีใช้ Agriscan\n"
    "- คุณได้ลงทะเบียนรับแจ้งเตือนแล้ว บอทจะส่งการ์ดมาเองเมื่อดินผิดปกติ\n"
    "- พิมพ์ 'สถานะ' ดูค่าดินล่าสุด\n"
    "- เปิด Dashboard ดูกราฟ/เกณฑ์ละเอียดได้ตลอด"
)


def _handle_chat(user_id, reply_token, text):
    """ตอบแชทตามคำสั่ง (สถานะ / เมนู / วิธีใช้)"""
    t = (text or "").strip()
    low = t.lower()

    if t in ("สถานะ", "status"):
        reading = _latest_reading()
        if reading is None:
            return line_notify.reply_text(
                reply_token, "ยังไม่มีข้อมูลเซ็นเซอร์ รอ ESP32 ส่งรอบแรก")
        if not reading.get("valid", True) or reading.get("quality") == "bad":
            return line_notify.reply_text(
                reply_token,
                f"⚠️ เซ็นเซอร์ผิดปกติ ({reading.get('reason', '?')}) — "
                "ตรวจสอบสาย RS485/ไฟเลี้ยง/การจุ่ม probe แล้วดูบน Dashboard อีกครั้ง")
        crop = alerts.get_crop(_effective_crop())
        return line_notify.reply_msg(
            reply_token,
            alerts.format_flex_status(
                reading, f"{crop['icon']} {crop['label']}",
                dashboard_url=DASHBOARD_PUBLIC_URL,
                time_str=datetime.now().strftime("%H:%M:%S")))

    if t in ("เมนู", "menu", "help"):
        return line_notify.reply_msg(reply_token, alerts.format_flex_menu())

    if t in ("วิธีใช้", "วิธีใช"):
        return line_notify.reply_text(reply_token, HOWTO_TEXT)

    return line_notify.reply_text(
        reply_token,
        f"รับทราบ (ลงทะเบียนแล้ว)\n"
        f"พิมพ์ 'สถานะ' ดูค่าดิน หรือ 'เมนู' ดูคำสั่ง")


@app.route("/api/line/webhook", methods=["POST"])
def line_webhook():
    """รับ event จาก LINE OA → เก็บ userId + ตอบยืนยัน (ตอบ 200 เสมอ กัน retry-storm)"""
    raw = request.get_data()
    if not _verify_line_signature(raw, request.headers.get("X-Line-Signature")):
        return jsonify({"error": "invalid signature"}), 403

    data = request.get_json(silent=True) or {}
    for ev in data.get("events", []):
        src = ev.get("source", {}) or {}
        user_id = src.get("userId") or src.get("groupId") or src.get("roomId")
        if not user_id:
            continue
        etype = ev.get("type")

        if etype in ("follow", "join"):
            _save_subscriber(user_id, True)
            _set_subscriber_name(user_id, line_notify.get_profile(user_id))
            line_notify.reply_msg(
                ev.get("replyToken"),
                [{"type": "text",
                  "text": "ลงทะเบียนรับแจ้งเตือน Agriscan สำเร็จ\n"
                          "บอทจะส่งการ์ดมาเองเมื่อดินผิดปกติ"},
                 alerts.format_flex_menu()],
            )
        elif etype in ("unfollow", "leave"):
            _save_subscriber(user_id, False)
        elif etype == "message":
            msg = (ev.get("message") or {})
            if msg.get("type") == "text":
                _save_subscriber(user_id, True)
                _set_subscriber_name(user_id, line_notify.get_profile(user_id))
                _handle_chat(user_id, ev.get("replyToken"),
                             msg.get("text") or "")
    return jsonify({"ok": True})


@app.route("/api/line/subscribers", methods=["GET"])
def line_subscribers():
    """ดู userId ที่ลงทะเบียนไว้ (ต้องมี X-API-Key — กันคนนอก)"""
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "unauthorized — X-API-Key ไม่ถูกต้อง"}), 401
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT line_user_id, display_name, active, subscribed_at "
                "FROM line_subscribers ORDER BY subscribed_at DESC LIMIT 100"
            )
            subs = [
                {"user_id": r["line_user_id"], "name": r["display_name"],
                 "active": bool(r["active"]),
                 "at": (r["subscribed_at"].isoformat()
                        if isinstance(r["subscribed_at"], datetime)
                        else r["subscribed_at"])}
                for r in cur.fetchall()
            ]
    except Exception:
        return jsonify({"error": "database unavailable"}), 503
    return jsonify({"count": len(subs), "subscribers": subs})


@app.route("/api/alerts/crops", methods=["GET"])
def alerts_crops():
    """รายชื่อพืชทั้งหมดให้ dropdown เลือกพืชที่จะใช้เตือน"""
    return jsonify({"current": _effective_crop(),
                    "crops": alerts.list_crops()})


@app.route("/api/alerts/crop", methods=["GET", "POST"])
def alerts_crop():
    """ดู/เปลี่ยนพืชที่ใช้ตัดสิน alert (เก็บใน DB — restart ไม่หาย)"""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        key = alerts.get_crop_key(body.get("crop", ""))
        if body.get("crop", "") not in alerts.CROPS:
            return jsonify({"error": "unknown crop",
                            "crops": alerts.list_crops()}), 400
        _set_setting("alert_crop", key)
        # เปลี่ยนพืช = เกณฑ์เปลี่ยน → ล้างสถานะ active เก่า กันค้างเตือนผิดเกณฑ์
        try:
            with get_conn() as conn:
                conn.execute("DELETE FROM alert_state "
                             "WHERE alert_key != 'manual_test'")
                conn.commit()
        except Exception:
            pass
    key = _effective_crop()
    crop = alerts.get_crop(key)
    return jsonify({"crop": key,
                    "crop_label": f"{crop['icon']} {crop['label']}"})


init_db()
cleanup_old_readings()  # ลบทิ้งข้อมูลเก่าครั้งแรกตอน service เริ่ม

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
