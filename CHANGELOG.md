# Changelog — Agriscan

เวอร์ชันทั้งหมดของ Agriscan (IoT soil monitoring) — อัปเดตตามที่ edit โค้ดจริง

รูปแบบเวอร์ชัน: `MAJOR.MINOR.PATCH`
- **MAJOR** — เปลี่ยนโครงสร้าง/สถาปัตยกรรมสำคัญ
- **MINOR** — เพิ่ม feature ความสามารถใหม่
- **PATCH** — แก้บั๊ก/ปรับปรุงเล็กน้อย

---

## [Unreleased]
- (งานที่ค้างยังไม่ release — ดู git log)

## [2.1.0] — 2026-08-15
### Changed
- **EC กลับไปใช้เกณฑ์ความเค็ม S1 ของกรมพัฒนาที่ดิน (LDD)** เป็นเกณฑ์หลัก (ข้าว/ข้าวโพด <2, ไม้ผล/ผัก <1 dS/m) — เลิกใช้ FAO 29 เป็นเกณฑ์หลัก (คงเป็นเพียงเอกสารอ้างอิงประกอบ)
- แก้ `src`/`conf` metadata เดิมออก; ใช้หมายเหตุระบุที่มาใน `crops.js`
- ปรับ `agriscan-presentation.html` + `docs/crop-sources.md` ให้สอดคล้อง (FAO 29 = เอกสารประกอบ)

### Fixed
- **มันสำปะหลัง EC 3 → 1.0 dS/m** — ค่าเดิมสูงสุดทั้งไฟล์ ทั้งที่จริงทนเค็มต่ำ (ผิดพลาดที่สุด)
- **พุทรา `temp.max` 35 → 45°C** — เป็นไม้ผลทนร้อนสุดขั้ว (~50°C)
- คอมเมนต์อ้าง "เล่ม 28" ผิด 6 จุด (มันฝรั่ง/หอม/กระเทียม/แตงโม/ฟักทอง/ผัก) — เล่ม 28 ครอบคลุมเฉพาะไม้ผล → เปลี่ยนอ้างเอกสารวิชาการจริง

### Added
- ฉลากเวอร์ชัน Ⓥ 2.1.0 ที่ header ของ dashboard (ทั้ง index.html และฝังใน dashboard.h)
- ไฟล์ CHANGELOG.md (เริ่มบันทึกจากเวอร์ชันนี้)

## [2.0.0] — 2026-08-15
### Added
- เพิ่มชนิดพืชอีก 14 ชนิด → รวม 18 ชนิด (ลำไย ลิ้นจี่ ทุเรียน มันสำปะหลัง มันฝรั่ง หอม กระเทียม มังคุด พุทรา แตงโม ฟักทอง ผักสวนครัว ส้มโอ ฝรั่ง)
- แยกเกณฑ์แต่ละพืชเป็น `dashboard/crops.js` (จากเดิมรวมใน script.js) — มี NPK_DEFAULT, CROP_CRITERIA, NPK_BAR_MAX
- crop selector + ระบบคำแนะนำอัตโนมัติตามชนิดพืช

### Changed
- หน่วย EC แสดงเป็น **dS/m** (จากเดิม µS/cm) ทั้งใน index.html และฝังใน dashboard.h
- Refactor script.js เพื่อความอ่านง่าย (helper npkLevels, setValue early-return ฯลฯ)

## [1.0.0] — รุ่นแรกเริ่ม (ก่อน feature อื่น)
### Initial
- ระบบ Agriscan พื้นฐาน: ESP32 อ่านเซ็นเซอร์ 7-ค่า ผ่าน RS485 Modbus + WebServer
- dashboard เดี่ยว (index.html) + Flask mock backend (app.py)
- เกณฑ์พื้นฐาน 4 ชนิด (ข้าว / ข้าวโพด / ยางพารา / อื่นๆ) อ้างอิงกรมพัฒนาที่ดิน

---

## อ้างอิงงานค้าง
- `dashboard/script.js` ยังมี diff ค้างไม่ commit (งานก่อนหน้า)
- branch `agents/plant-criteria-research-thai` + worktree `agriscan-v2.worktrees/` — งานวิจัยเกณฑ์พืชที่ยังค้าง
