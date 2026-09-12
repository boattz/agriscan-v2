"""
Agriscan — LINE Messaging API sender

ยิงแจ้งเตือนผ่าน LINE Official Account (Messaging API) ใช้stdlib ล้วน
(urllib — ไม่เพิ่ม dependency ใหม่ให้ render free plan)

ต้องตั้ง env: LINE_CHANNEL_ACCESS_TOKEN (จาก LINE Developers → Messaging API)
โหมดทดสอบ: ALERT_DRY_RUN=true → log แทนยิงจริง (ไม่เปลืองโควต้า 200/เดือน)
"""

import json
import os
import urllib.error
import urllib.request

API_BASE = "https://api.line.me/v2/bot/message"


def get_token():
    return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()


def is_dry_run():
    return os.environ.get("ALERT_DRY_RUN", "false").lower() in ("1", "true", "yes")


def is_configured():
    """มี token พร้อมยิงจริงหรือไม่ (dry-run ถือว่าไม่ configured)"""
    return bool(get_token()) and not is_dry_run()


def _post(path, payload, timeout=10):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_BASE + path,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + get_token(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return True, {"status": res.status}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        print(f"[LINE] HTTP {e.code}: {detail}")
        return False, {"status": e.code, "detail": detail}
    except Exception as e:
        print(f"[LINE] ส่งล้มเหลว: {e}")
        return False, {"error": str(e)[:300]}


def push_text(to_id, text, timeout=10):
    """ส่งหาคนเดียว/กลุ่มเดียว (ต้องมี userId/groupId)"""
    if is_dry_run():
        print(f"[LINE][DRY-RUN] push → {to_id}: {text[:200]}")
        return True, {"dry_run": True}
    if not get_token():
        print("[LINE] ยังไม่ตั้ง LINE_CHANNEL_ACCESS_TOKEN — ข้ามการส่ง")
        return False, {"error": "LINE_CHANNEL_ACCESS_TOKEN not set"}
    if not to_id:
        return False, {"error": "missing target id"}
    return _post("/push", {"to": to_id, "messages": [{"type": "text", "text": text}]},
                 timeout=timeout)


def broadcast_text(text, timeout=10):
    """ส่งหาผู้ติดตาม OA ทุกคน (ง่ายสุดสำหรับ Phase 1)"""
    if is_dry_run():
        print(f"[LINE][DRY-RUN] broadcast: {text[:200]}")
        return True, {"dry_run": True}
    if not get_token():
        print("[LINE] ยังไม่ตั้ง LINE_CHANNEL_ACCESS_TOKEN — ข้ามการส่ง")
        return False, {"error": "LINE_CHANNEL_ACCESS_TOKEN not set"}
    return _post("/broadcast", {"messages": [{"type": "text", "text": text}]},
                 timeout=timeout)


def send_text(text, mode="broadcast", target_id="", timeout=10):
    """จุดเข้าเดียว — mode: 'broadcast' หรือ 'push'"""
    if mode == "push":
        return push_text(target_id, text, timeout=timeout)
    return broadcast_text(text, timeout=timeout)
