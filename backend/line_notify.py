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


def multicast_text(user_ids, text, timeout=10):
    """ส่งหาผู้ลงทะเบียนหลายคน (chunk ละ 500 ตาม limit LINE)"""
    ids = list(dict.fromkeys([u for u in (user_ids or []) if u]))
    if not ids:
        return False, {"error": "no subscribers"}
    if is_dry_run():
        print(f"[LINE][DRY-RUN] multicast -> {len(ids)} subs: {text[:200]}")
        return True, {"dry_run": True, "count": len(ids)}
    if not get_token():
        print("[LINE] ยังไม่ตั้ง LINE_CHANNEL_ACCESS_TOKEN — ข้ามการส่ง")
        return False, {"error": "LINE_CHANNEL_ACCESS_TOKEN not set"}
    sent = 0
    for i in range(0, len(ids), 500):
        ok, info = _post(
            "/multicast",
            {"to": ids[i:i + 500],
             "messages": [{"type": "text", "text": text[:4900]}]},
            timeout=timeout,
        )
        if not ok:
            return False, info
        sent += len(ids[i:i + 500])
    return True, {"count": sent}


def reply_text(reply_token, text, timeout=10):
    """ตอบกลับในแชท (ใช้ replyToken จาก webhook — ยืนยันช่องสองทางทันที)"""
    if is_dry_run():
        print(f"[LINE][DRY-RUN] reply: {text[:200]}")
        return True, {"dry_run": True}
    if not get_token():
        return False, {"error": "LINE_CHANNEL_ACCESS_TOKEN not set"}
    if not reply_token:
        return False, {"error": "missing reply token"}
    payload = {"replyToken": reply_token,
               "messages": [{"type": "text", "text": text[:4900]}]}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_BASE + "/reply", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + get_token()},
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
        print(f"[LINE] reply HTTP {e.code}: {detail}")
        return False, {"status": e.code, "detail": detail}
    except Exception as e:
        print(f"[LINE] reply ล้มเหลว: {e}")
        return False, {"error": str(e)[:300]}


def get_profile(user_id, timeout=10):
    """ดึง display name (optional — ล้มเหลวก็คืน None)"""
    if not get_token() or not user_id:
        return None
    req = urllib.request.Request(
        f"https://api.line.me/v2/bot/profile/{user_id}",
        headers={"Authorization": "Bearer " + get_token()},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
            name = data.get("displayName")
            return str(name)[:100] if name else None
    except Exception as e:
        print(f"[LINE] profile ล้มเหลว: {e}")
        return None
