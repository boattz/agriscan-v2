"""
Agriscan — Alert Engine (ตรรกะแจ้งเตือนฝั่ง backend)

พอร์ต 1:1 จากกติกาฝั่ง dashboard เพื่อให้ LINE แจ้งได้แม้ปิดเบราว์เซอร์:
  - เกณฑ์รายพืช  ← dashboard/crops.js (CROP_CRITERIA / NPK_DEFAULT)
  - กติกาคำแนะนำ ← dashboard/script.js buildRecommendations()

ถ้าแก้เกณฑ์ที่ crops.js ต้องมาแก้ไฟล์นี้ให้ตรงกัน (ดู SYNC_NOTE ข้างล่าง)

SYNC_NOTE: ค่า threshold ใน CROPS ต้องตรงกับ dashboard/crops.js เสมอ
"""

# ── เกณฑ์พืชรายชนิด (mirror ของ dashboard/crops.js) ──────────
# moisture: % · ph: min/max = ยังขึ้นได้, optMin/optMax = เหมาะสุด
# ec: max = dS/m · temp: °C · npk: mg/kg (N เป็นค่าประมาณจากเซ็นเซอร์)
NPK_DEFAULT = {
    "nLow": 50,
    "pLow": 10, "pMid": 25,
    "kLow": 60, "kMid": 90,
    "fertN": "ปุ๋ยยูเรีย 46-0-0 หรือ 21-0-0",
    "fertP": "ปุ๋ย 0-46-0 หรือหินฟอสเฟต",
    "fertK": "ปุ๋ย 0-0-60 หรือโพแทสเซียมคลอไรด์",
}


def _crop(label, icon, moisture, ph, ec_max, temp, npk=None, fert=None):
    base = dict(NPK_DEFAULT)
    if npk:
        base.update(npk)
    if fert:
        base.update(fert)
    return {
        "label": label, "icon": icon,
        "moisture": {"min": moisture[0], "max": moisture[1]},
        "ph": {"min": ph[0], "max": ph[1], "optMin": ph[2], "optMax": ph[3]},
        "ec": {"max": ec_max},
        "temp": {"min": temp[0], "max": temp[1]},
        "npk": base,
    }


CROPS = {
    "rice":       _crop("ข้าว", "🌾", (60, 100), (4.0, 8.4, 5.6, 7.3), 2,   (18, 35)),
    "corn":       _crop("ข้าวโพด", "🌽", (50, 80), (4.0, 7.8, 5.1, 7.3), 2, (16, 35),
                        {"nLow": 70, "pLow": 15, "pMid": 30, "kLow": 90, "kMid": 120},
                        {"fertN": "ปุ๋ยยูเรีย 46-0-0 (ข้าวโพดต้องการ N สูง)"}),
    "rubber":     _crop("ยางพารา", "🌳", (30, 60), (4.5, 6.5, 5.5, 6.5), 1, (22, 35),
                        {"nLow": 40, "pLow": 10, "pMid": 25, "kLow": 70, "kMid": 100},
                        {"fertN": "ปุ๋ย 21-0-0 (แอมโมเนียมซัลเฟต) หรือยูเรีย 46-0-0",
                         "fertK": "ปุ๋ย 0-0-60 หรือ 13-13-21"}),
    "longan":     _crop("ลำไย", "🍇", (30, 60), (5.0, 6.5, 5.5, 6.3), 1,   (18, 35),
                        {"nLow": 40, "pLow": 10, "pMid": 25, "kLow": 70, "kMid": 100}),
    "lychee":     _crop("ลิ้นจี่", "🍒", (40, 80), (4.5, 6.5, 5.0, 6.0), 1, (15, 35),
                        {"nLow": 40, "pLow": 10, "pMid": 25, "kLow": 70, "kMid": 100}),
    "durian":     _crop("ทุเรียน", "🟢", (50, 90), (5.0, 6.5, 5.5, 6.5), 1, (24, 33),
                        {"nLow": 50, "pLow": 12, "pMid": 30, "kLow": 90, "kMid": 130}),
    "cassava":    _crop("มันสำปะหลัง", "🌱", (30, 70), (4.5, 7.5, 5.5, 6.5), 1.0, (20, 35),
                        {"nLow": 35, "pLow": 12, "pMid": 30, "kLow": 90, "kMid": 130}),
    "potato":     _crop("มันฝรั่ง", "🥔", (50, 80), (5.0, 7.0, 5.2, 6.0), 2, (15, 28),
                        {"nLow": 55, "pLow": 15, "pMid": 35, "kLow": 90, "kMid": 130}),
    "onion":      _crop("หอมหัวใหญ่", "🧅", (50, 85), (5.5, 7.5, 6.0, 6.8), 1, (13, 25),
                        {"nLow": 60, "pLow": 15, "pMid": 30, "kLow": 80, "kMid": 120}),
    "garlic":     _crop("กระเทียม", "🧄", (45, 80), (5.5, 7.5, 6.0, 7.0), 1, (12, 24),
                        {"nLow": 60, "pLow": 15, "pMid": 30, "kLow": 80, "kMid": 120}),
    "mangosteen": _crop("มังคุด", "🟣", (50, 90), (5.0, 6.5, 5.5, 6.5), 1, (22, 33),
                        {"nLow": 45, "pLow": 12, "pMid": 30, "kLow": 80, "kMid": 120}),
    "jujube":     _crop("พุทรา", "🍏", (40, 70), (5.0, 8.5, 6.0, 7.0), 2,   (18, 45),
                        {"nLow": 40, "pLow": 10, "pMid": 25, "kLow": 70, "kMid": 100}),
    "watermelon": _crop("แตงโม", "🍉", (50, 80), (5.0, 7.5, 5.7, 7.2), 2,   (20, 35),
                        {"nLow": 50, "pLow": 15, "pMid": 30, "kLow": 80, "kMid": 120}),
    "pumpkin":    _crop("ฟักทอง", "🎃", (40, 75), (5.5, 7.5, 6.0, 7.0), 2,  (18, 32),
                        {"nLow": 50, "pLow": 12, "pMid": 28, "kLow": 80, "kMid": 120}),
    "vegetables": _crop("ผักสวนครัว", "🥬", (50, 85), (5.5, 7.5, 6.0, 7.0), 1, (15, 32),
                        {"nLow": 60, "pLow": 15, "pMid": 30, "kLow": 80, "kMid": 120}),
    "pomelo":     _crop("ส้มโอ", "🍊", (40, 75), (5.0, 6.5, 5.5, 6.5), 1,   (20, 35),
                        {"nLow": 45, "pLow": 12, "pMid": 30, "kLow": 70, "kMid": 100}),
    "guava":      _crop("ฝรั่ง", "🍐", (40, 75), (4.5, 8.5, 5.5, 6.5), 2,   (20, 35),
                        {"nLow": 45, "pLow": 10, "pMid": 25, "kLow": 70, "kMid": 100}),
    "other":      _crop("อื่นๆ", "🌿", (30, 80), (5.5, 7.5, 6.0, 6.5), 2,   (15, 35)),
}

SEVERITY_ORDER = {"ok": 0, "warn": 1, "alert": 2}


def get_crop(crop_key):
    """คืนเกณฑ์พืช — key ไม่รู้จักตกกลับเป็น 'other' (เหมือน frontend)"""
    return CROPS.get(crop_key) or CROPS["other"]


def get_crop_key(crop_key):
    return crop_key if crop_key in CROPS else "other"


def evaluate(reading, crop_key="other"):
    """ประเมินค่าเซ็นเซอร์ 1 ชุด → ลิสต์ alert/warn (mirror buildRecommendations)

    reading: dict มี moisture, temperature, ec (µS/cm), ph, n, p, k
    คืน: [{key, severity, icon, title, short}] — เฉพาะ warn/alert (ok ไม่ส่ง LINE)
    """
    c = get_crop(crop_key)
    npk = c["npk"]
    items = []

    m = float(reading.get("moisture") or 0)
    t = reading.get("temperature")
    ec = reading.get("ec")
    ph = reading.get("ph")
    n = reading.get("n")
    p = reading.get("p")
    k = reading.get("k")

    def num(v, default=None):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    t, ec, ph, n, p, k = num(t), num(ec), num(ph), num(n), num(p), num(k)

    # ── ความชื้น (mirror script.js:253-259) ──
    if m < c["moisture"]["min"]:
        items.append({"key": "moisture_low", "severity": "alert", "icon": "💧",
                      "title": "ดินแห้ง — ควรรดน้ำ",
                      "short": f"ความชื้น {m:.1f}% ต่ำกว่าเกณฑ์ {c['label']} (≥{c['moisture']['min']}%)"})
    elif m > c["moisture"]["max"]:
        items.append({"key": "moisture_high", "severity": "warn", "icon": "🌊",
                      "title": "ดินชื้นเกินไป",
                      "short": f"ความชื้น {m:.1f}% สูงกว่าเกณฑ์ (≤{c['moisture']['max']}%) ระวังรากเน่า"})

    # ── pH (mirror script.js:262-270) ──
    if ph is not None:
        if ph < c["ph"]["min"]:
            items.append({"key": "ph_acid", "severity": "alert", "icon": "🪨",
                          "title": "ดินเป็นกรดเกินไป",
                          "short": f"pH {ph:.1f} ต่ำกว่าเกณฑ์ (≥{c['ph']['min']}) ควรใส่ปูนขาว/โดโลไมท์"})
        elif ph > c["ph"]["max"]:
            items.append({"key": "ph_alkaline", "severity": "warn", "icon": "⚗️",
                          "title": "ดินเป็นด่างเกินไป",
                          "short": f"pH {ph:.1f} สูงกว่าเกณฑ์ (≤{c['ph']['max']}) ควรใส่กำมะถัน/ปุ๋ยอินทรีย์"})
        elif ph < c["ph"]["optMin"] or ph > c["ph"]["optMax"]:
            items.append({"key": "ph_subopt", "severity": "warn", "icon": "ℹ️",
                          "title": "pH พอใช้ได้แต่ไม่เหมาะที่สุด",
                          "short": f"pH {ph:.1f} ช่วงเหมาะสุด {c['ph']['optMin']}–{c['ph']['optMax']}"})

    # ── N/P/K (mirror script.js:273-287) ──
    if n is not None and n < npk["nLow"]:
        items.append({"key": "n_low", "severity": "warn", "icon": "🌿",
                      "title": "ไนโตรเจน (N) ค่อนข้างต่ำ",
                      "short": f"N = {n:.0f} mg/kg (ค่าประมาณ) ควรใส่ {npk['fertN']}"})
    if p is not None:
        if p < npk["pLow"]:
            items.append({"key": "p_low", "severity": "alert", "icon": "🌱",
                          "title": "ฟอสฟอรัส (P) ต่ำ",
                          "short": f"P = {p:.0f} mg/kg (<{npk['pLow']}) ควรใส่ {npk['fertP']}"})
        elif p < npk["pMid"]:
            items.append({"key": "p_mid", "severity": "warn", "icon": "🌱",
                          "title": "ฟอสฟอรัส (P) ปานกลาง",
                          "short": f"P = {p:.0f} mg/kg ระดับปานกลาง — ยังไม่ต้องใส่ปุ๋ย"})
    if k is not None:
        if k < npk["kLow"]:
            items.append({"key": "k_low", "severity": "alert", "icon": "🍂",
                          "title": "โพแทสเซียม (K) ต่ำ",
                          "short": f"K = {k:.0f} mg/kg (<{npk['kLow']}) ควรใส่ {npk['fertK']}"})
        elif k < npk["kMid"]:
            items.append({"key": "k_mid", "severity": "warn", "icon": "🍂",
                          "title": "โพแทสเซียม (K) ปานกลาง",
                          "short": f"K = {k:.0f} mg/kg ระดับปานกลาง — ยังไม่ต้องใส่ปุ๋ย"})

    # ── EC (mirror script.js:290-292) — เซ็นเซอร์อ่าน µS/cm, เกณฑ์เป็น dS/m ──
    if ec is not None and ec > c["ec"]["max"] * 1000:
        items.append({"key": "ec_high", "severity": "alert", "icon": "⚡",
                      "title": f"ดินเค็มเกินไปสำหรับ {c['label']}",
                      "short": f"EC = {ec / 1000:.1f} dS/m เกินเกณฑ์ (≤{c['ec']['max']}) งดปุ๋ยเคมี"})

    # ── อุณหภูมิ (mirror script.js:294-296 — เฉพาะร้อนเกิน) ──
    if t is not None and t > c["temp"]["max"]:
        items.append({"key": "temp_high", "severity": "alert", "icon": "🌡",
                      "title": "อุณหภูมิดินสูงเกินไป",
                      "short": f"{t:.1f}°C สูงกว่าเกณฑ์ (≤{c['temp']['max']}°C) ควรคลุมดิน"})

    return items


def filter_by_severity(items, min_severity="warn"):
    """กรองตามความรุนแรงขั้นต่ำ (warn = เอา warn+alert, alert = เอาเฉพาะ alert)"""
    threshold = SEVERITY_ORDER.get(min_severity, 1)
    return [i for i in items if SEVERITY_ORDER.get(i["severity"], 0) >= threshold]


def format_line_message(crop_label, crop_icon, items, dashboard_url=None,
                        time_str=None, prefix="🌱 Agriscan แจ้งเตือน", max_items=8):
    """รวมหลาย alert เป็นข้อความ LINE ก้อนเดียว (กันเปลืองโควต้า 200/เดือน)"""
    lines = [f"{prefix} ({crop_icon} {crop_label})"]
    for it in items[:max_items]:
        sev = "🔴" if it["severity"] == "alert" else "🟡"
        lines.append(f"{sev} {it['icon']} {it['title']}: {it['short']}")
    if len(items) > max_items:
        lines.append(f"…และอีก {len(items) - max_items} รายการ ดูทั้งหมดบน dashboard")
    lines.append("ค่า N เป็นค่าประมาณจากเซ็นเซอร์ (กรมฯ วัด N เป็น %)")
    footer = []
    if time_str:
        footer.append(f"🕒 {time_str}")
    if dashboard_url:
        footer.append(f"📊 {dashboard_url}")
    if footer:
        lines.append(" · ".join(footer))
    text = "\n".join(lines)
    return text[:4900]  # กันเกิน limit 5000 ตัวอักษรของ LINE


# ── Flex UI (การ์ดสวยในแชท LINE) ────────────────────────────
def _flex_row(label, value, value_color="#111111"):
    return {
        "type": "box", "layout": "baseline", "spacing": "sm",
        "contents": [
            {"type": "text", "text": str(label), "size": "sm",
             "color": "#8b9bb4", "flex": 0},
            {"type": "text", "text": str(value), "size": "sm",
             "color": value_color, "weight": "bold", "align": "end",
             "wrap": True},
        ],
    }


def _dashboard_button(dashboard_url):
    if not dashboard_url:
        return None
    return {
        "type": "button", "style": "primary", "height": "sm",
        "action": {"type": "uri", "label": "เปิด Dashboard",
                   "uri": dashboard_url},
    }


def format_flex_alert(crop_label, crop_icon, items, dashboard_url=None,
                      time_str=None, max_items=8):
    """การ์ดแจ้งเตือน (แดง = วิกฤต, เหลือง = เฝ้าระวัง, เขียว = ปกติ)"""
    items = items[:max_items]
    if not items:
        accent, title = "#16a34a", "ค่าปกติ"
        alt = f"Agriscan: {crop_label} ค่าปกติ"
    elif any(i["severity"] == "alert" for i in items):
        accent, title = "#ef4444", f"{crop_icon} {crop_label} ผิดปกติ"
        alt = f"Agriscan แจ้งเตือน {crop_label}: " + ", ".join(
            i["title"] for i in items)[:350]
    else:
        accent, title = "#f59e0b", f"{crop_icon} {crop_label} เฝ้าระวัง"
        alt = f"Agriscan เฝ้าระวัง {crop_label}: " + ", ".join(
            i["title"] for i in items)[:350]

    body = []
    if not items:
        body.append({"type": "text", "text": "ทุกค่าอยู่ในเกณฑ์",
                     "size": "md", "weight": "bold", "color": "#16a34a",
                     "align": "center"})
    for it in items:
        dot = "#ef4444" if it["severity"] == "alert" else "#f59e0b"
        body.append({
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                {"type": "text", "text": "●", "size": "sm",
                 "color": dot, "flex": 0},
                {"type": "box", "layout": "vertical", "flex": 1,
                 "contents": [
                     {"type": "text", "text": f"{it['icon']} {it['title']}",
                      "weight": "bold", "size": "sm", "wrap": True},
                     {"type": "text", "text": it["short"], "size": "xs",
                      "color": "#8b9bb4", "wrap": True},
                 ]},
            ],
        })
    body.append({"type": "separator", "margin": "md"})
    body.append({"type": "text",
                 "text": "ค่า N เป็นค่าประมาณจากเซ็นเซอร์ (กรมฯ วัด N เป็น %)",
                 "size": "xs", "color": "#8b9bb4", "wrap": True,
                 "margin": "md"})
    if time_str:
        body.append({"type": "text", "text": f"เวลา {time_str}", "size": "xs",
                     "color": "#8b9bb4", "align": "end", "margin": "xs"})

    bubble = {
        "type": "bubble",
        "header": {
            "type": "box", "layout": "vertical", "paddingAll": "12px",
            "backgroundColor": accent,
            "contents": [{"type": "text", "text": title, "weight": "bold",
                          "size": "md", "color": "#ffffff"}],
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "sm",
                 "paddingAll": "16px", "contents": body},
    }
    btn = _dashboard_button(dashboard_url)
    if btn:
        bubble["footer"] = {"type": "box", "layout": "vertical",
                            "paddingAll": "12px", "contents": [btn]}
    return {"type": "flex", "altText": alt, "contents": bubble}


def format_flex_status(reading, crop_label="Agriscan", dashboard_url=None,
                       time_str=None):
    """การ์ดสถานะดินปัจจุบัน (ตอบเมื่อพิมพ์ 'สถานะ')"""
    def f(v, digits=1, suffix=""):
        try:
            return f"{float(v):.{digits}f}{suffix}"
        except (TypeError, ValueError):
            return "-"

    m = f(reading.get("moisture"), 1, "%")
    t = f(reading.get("temperature"), 1, "°C")
    try:
        ec = f"{float(reading.get('ec')) / 1000:.1f} dS/m"
    except (TypeError, ValueError):
        ec = "-"
    ph = f(reading.get("ph"))
    n = f(reading.get("n"), 0)
    p = f(reading.get("p"), 0)
    k = f(reading.get("k"), 0)

    body = [
        {"type": "text", "text": m, "size": "xxl", "weight": "bold",
         "color": "#16a34a", "align": "center"},
        {"type": "text", "text": "ความชื้นดิน", "size": "sm",
         "color": "#8b9bb4", "align": "center", "margin": "xs"},
        {"type": "separator", "margin": "md"},
        {"type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
         "contents": [
             _flex_row("อุณหภูมิ", t),
             _flex_row("EC", ec),
             _flex_row("pH", ph),
             _flex_row("N / P / K", f"{n} / {p} / {k} mg/kg"),
             _flex_row("พืช", crop_label),
         ]},
    ]
    if time_str:
        body.append({"type": "text", "text": f"ข้อมูลเวลา {time_str}",
                     "size": "xs", "color": "#8b9bb4", "align": "end",
                     "margin": "md"})

    bubble = {
        "type": "bubble",
        "header": {
            "type": "box", "layout": "vertical", "paddingAll": "12px",
            "backgroundColor": "#16a34a",
            "contents": [{"type": "text", "text": "สถานะดิน Agriscan",
                          "weight": "bold", "size": "md",
                          "color": "#ffffff"}],
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "sm",
                 "paddingAll": "16px", "contents": body},
    }
    btn = _dashboard_button(dashboard_url)
    if btn:
        bubble["footer"] = {"type": "box", "layout": "vertical",
                            "paddingAll": "12px", "contents": [btn]}
    return {"type": "flex",
            "altText": f"สถานะดิน: ชื้น {m} pH {ph} EC {ec}",
            "contents": bubble}


def format_flex_menu():
    """การ์ดเมนูคำสั่ง (ตอบเมื่อพิมพ์ 'เมนู')"""
    bubble = {
        "type": "bubble",
        "header": {
            "type": "box", "layout": "vertical", "paddingAll": "12px",
            "backgroundColor": "#16a34a",
            "contents": [{"type": "text", "text": "เมนู Agriscan",
                          "weight": "bold", "size": "md",
                          "color": "#ffffff"}],
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "แตะปุ่มหรือพิมพ์สั่งได้เลย",
                 "size": "sm", "color": "#8b9bb4", "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "box", "layout": "vertical", "margin": "md",
                 "spacing": "sm",
                 "contents": [
                     _flex_row("ดูค่าดิน", "พิมพ์ 'สถานะ'"),
                     _flex_row("วิธีใช้", "พิมพ์ 'วิธีใช้'"),
                 ]},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                {"type": "button", "style": "primary", "height": "sm",
                 "action": {"type": "message", "label": "ดูสถานะดิน",
                            "text": "สถานะ"}},
                {"type": "button", "style": "link", "height": "sm",
                 "action": {"type": "message", "label": "วิธีใช้",
                            "text": "วิธีใช้"}},
            ],
        },
    }
    return {"type": "flex", "altText": "เมนู Agriscan: สถานะ วิธีใช้",
            "contents": bubble}
