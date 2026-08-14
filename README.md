# 🌱 Agriscan

ระบบ IoT สำหรับตรวจสอบค่าดินแบบ Real-time อ่านค่าจากเซ็นเซอร์ 7-in-1 (RS485 Modbus) ผ่าน ESP32 และแสดงผลบนแดชบอร์ดเว็บ — **ESP32 ส่งค่าจริงขึ้นคลาวด์ (Render.com) เก็บลง PostgreSQL** ดูได้จากทุกที่ ไม่มี mock data

## ค่าที่วัดได้

แดชบอร์ดให้เลือก**ชนิดพืช** (ข้าว 🌾 / ข้าวโพด 🌽 / ยางพารา 🌳 / อื่นๆ 🌿) — ระบบใช้เกณฑ์เฉพาะของพืชนั้นๆ ในการประเมินและแนะนำ (จำตัวเลือกไว้ใน localStorage):

| เกณฑ์ (กรมพัฒนาที่ดิน) | ข้าว 🌾 | ข้าวโพด 🌽 | ยางพารา 🌳 | อื่นๆ 🌿 |
|-----------------------|---------|-----------|------------|---------|
| pH — เหมาะสูง (S1) | 5.6–7.3 | 5.1–7.3 | 5.6–6.5 | 6.0–6.5 |
| pH — ยังปลูกได้ (S2–S3) | 4.0–8.4 | 4.0–8.4 | 4.5–6.5 | 5.5–7.5 |
| EC — เหมาะสูง (S1) | < 2 dS/m (S2: 2–5, S3: 5–10) | < 2 dS/m (S2: 2–4, S3: 4–8) | < 1 dS/m (อ่อนไหวมาก) | < 2 dS/m |
| อุณหภูมิ — เหมาะสูง (S1) | 22–30°C | 24–30°C | 22–35°C | 15–35°C |
| ความชื้น (แนวทางรดน้ำ) | 60–100% (นาขังน้ำ) | 50–80% | 30–60% (ระบายน้ำดี) | 30–80% |
| N (ค่าบ่งชี้) | ≥ 50 mg/kg | ≥ 60 mg/kg | ≥ 50 mg/kg | ≥ 50 mg/kg |
| P (ตารางที่ 15) | ต่ำ <10 · ปานกลาง 10–25 · สูง >25 mg/kg (ทุกพืช) |
| K (ตารางที่ 15) | ต่ำ <60 · ปานกลาง 60–90 · สูง >90 mg/kg (ทุกพืช) |

**แหล่งอ้างอิง:** กรมพัฒนาที่ดิน — *ศักยภาพการให้ผลผลิตพืชเศรษฐกิจของชุดดินในประเทศไทย* (สำนักสำรวจและวิจัยทรัพยากรดิน): ตารางที่ 3 ข้าว / ตารางที่ 4 ข้าวโพด (ดัดแปลงจากบัณฑิตและคำรณ, 2542) · ยางพารา: *คู่มือการจำแนกความเหมาะสมของดินสำหรับพืชเศรษฐกิจ* (เอกสารวิชาการ เล่ม 28) · P/K/N: *คู่มือการวิเคราะห์ดินทางเคมี*, ตารางที่ 15 (กองสำรวจดิน, 2523): https://e-library.ldd.go.th/library/flip/bib10134f/files/basic-html/page83.html

## สถาปัตยกรรม

```
esp32/agriscan/
  agriscan.ino            ← firmware (RS485 + WiFi + WebServer + ส่งข้อมูลขึ้นคลาวด์)
  dashboard.h             ← dashboard ฝังใน C++ raw string literal

dashboard/
  index.html              ← dashboard สำหรับเปิดในเบราว์เซอร์
  script.js               ← logic ดึงข้อมูล, fallback chain, คำแนะนำ
  style.css               ← ธีม dark green glassmorphism

backend/
  app.py                  ← Flask API จริง (รับค่า + เก็บ DB + เสิร์ฟ dashboard)
  requirements.txt        ← Python dependencies
```

**Data flow (ข้อมูลจริง ไม่มี mock):**

```
เซ็นเซอร์ 7-in-1 → RS485 Modbus → ESP32 → POST /api/readings (HTTPS, ทุก 3 วินาที)
                                          ↓
                              PostgreSQL (Render)
                                          ↓
              Dashboard บนเว็บ ← GET /api/latest (poll ทุก 3 วินาที)
```

## วิธี Deploy (Render.com) — ดูบนเว็บได้จริง

1. **Push โค้ดนี้ขึ้น GitHub** แล้วนำเข้าใน [Render.com](https://render.com) (New → Blueprint)
2. Render จะอ่าน `render.yaml` อัตโนมัติ สร้างให้ครบ: **Web Service + PostgreSQL (free tier)** + สุ่มค่า `API_KEY`
3. เปิด URL ที่ได้ เช่น `https://agriscan-xynf.onrender.com/` — จะเห็นหน้า dashboard
4. คัดลอกค่า **API_KEY** จาก Render Dashboard → Environment

### ตั้งค่า ESP32 ให้ส่งค่าขึ้นคลาวด์

เปิด `esp32/agriscan/agriscan.ino` แล้วแก้:

```cpp
const char* CLOUD_URL = "https://agriscan-xynf.onrender.com/api/readings";
const char* API_KEY   = "<ค่า API_KEY จาก Render — ดูที่ Environment>";
```

- ESP32 จะ POST ค่าจริงขึ้นคลาวด์ทุก 3 วินาที (`POST_INTERVAL_MS`)
- Backend ลบข้อมูลเก่ากว่า 7 วันอัตโนมัติ (ตั้งได้ผ่าน env `RETAIN_DAYS`) — กัน database เต็ม
- ยังเสิร์ฟ dashboard ให้เครือข่ายท้องถิ่นผ่าน `http://agriscan.local` ตามเดิม

## วิธีใช้งาน

### Backend (รันในเครื่อง — ใช้ SQLite อัตโนมัติ)

```bash
pip install -r backend/requirements.txt
cd backend && python app.py          # http://localhost:5000
```

- ไม่ต้องตั้งค่าใด ๆ — ไม่มี `DATABASE_URL` จะใช้ไฟล์ `backend/agriscan.db` (SQLite)
- ทดสอบส่งค่าเหมือน ESP32:
  ```bash
  curl -X POST http://localhost:5000/api/readings \
       -H "Content-Type: application/json" \
       -H "X-API-Key: agriscan-dev-key" \
       -d '{"moisture":45.2,"temperature":28.5,"ec":320,"ph":6.8,"n":45,"p":32,"k":89}'
  ```

### Dashboard (เบราว์เซอร์)

- เปิด `dashboard/index.html` ตรงๆ หรือเข้าผ่าน URL ของ Render
- Fallback chain: IP ตั้งเอง (localStorage) → URL ที่ใช้ได้ล่าสุด → page origin → **คลาวด์ Render** → agriscan.local → 192.168.1.1 → localhost:5000

### ESP32 (ของจริง)

1. เปิดไฟล์ `esp32/agriscan/agriscan.ino` ใน Arduino IDE
2. ติดตั้งไลบรารี ModbusMaster
3. แก้ไข SSID/PASSWORD และ CLOUD_URL/API_KEY
4. Flash ไปยัง ESP32

## API Endpoints

| เส้นทาง | วิธี | คำอธิบาย |
|---------|------|-----------|
| `POST /api/readings` | ESP32 | รับค่าจากเซ็นเซอร์ (ต้องมี header `X-API-Key`) |
| `GET /api/latest` | Dashboard | ค่าล่าสุดจากฐานข้อมูล |
| `GET /data` | Dashboard | alias ของ `/api/latest` |
| `GET /health` | — | ตรวจสถานะ service + ฐานข้อมูล |
| `GET /` | — | เสิร์ฟหน้า dashboard |

## เอกสารประกอบ

- `agriscan-presentation.html` — เอกสารนำเสนอโปรเจกต์ฉบับสมบูรณ์ (เปิดในเบราว์เซอร์)
- `agriscan-code-guide.html` — คู่มืออธิบายโค้ดทุกส่วน: ภาษา, สแตก, workflow, อธิบายทีละไฟล์ (เปิดในเบราว์เซอร์)

## หมายเหตุ

- **ไม่มี mock data แล้ว** — ถ้ายังไม่มีข้อมูล หน้าเว็บจะแสดงสถานะ offline จนกว่า ESP32 จะส่งค่ามา
- บน Render free tier พื้นที่ Postgres มีจำกัด (ส่งทุก 3 วินาที ≈ 28,800 แถว/วัน + ลบข้อมูลเก่าอัตโนมัติ) เหมาะสำหรับการสาธิต
- HTTPS ของ ESP32 ใช้ `setInsecure()` — เพียงพอสำหรับการพัฒนา ถ้าต้องการความปลอดภัยสูงขึ้นควรใช้ certificate pinning
