'use strict';

// ─── เกณฑ์พืชรายชนิด (มีแหล่งอ้างอิง + ระดับความมั่นใจ) ───────────────
// ที่มา: ศักยภาพการให้ผลผลิตพืชเศรษฐกิจของชุดดินในประเทศไทย (สำนักสำรวจและวิจัยทรัพยากรดิน, กรมพัฒนาที่ดิน)
// ตารางที่ 3 (ข้าว) ตารางที่ 4 (ข้าวโพด) ตารางที่ 5 (มันสำปะหลัง) — ดัดแปลงจากบัณฑิตและคำรณ (2542)
// ไม้ผล (ลำไย ลิ้นจี่ ทุเรียน มังคุด ส้มโอ ฝรั่ง พุทรา ยางพารา): คู่มือการจำแนกความเหมาะสมของดินสำหรับพืชเศรษฐกิจ
//   (เอกสารวิชาการ เล่ม 28, กองสำรวจและจำแนกดิน) — ครอบคลุมเฉพาะไม้ผล ใช้สำหรับผัก/มันฝรั่งได้
// EC: max = dS/m ที่ผลผลิตยังไม่ลดลง (FAO Irrigation & Drainage Paper 29, ตารางที่ 4 — ECe คอลัมน์ 0%)
//   เอกสารอ้างอิงฉบับเต็ม/URL อยู่ใน docs/crop-sources.md
// pH: min/max = ขอบเขตยังขึ้นได้ (S3) · optMin/optMax = ช่วงเหมาะสมสูงสุด (S1)
// อุณหภูมิ: min/max = ขอบเขตที่ยังขึ้นได้ · ความชื้น (%) เป็นแนวทางรดน้ำ (LDD ใช้ mm/ฤดู — ไม่ใช่ตัวเลขจากตาราง LDD)
// ทุก metric มี src = แหล่งอ้างอิง, conf = high/medium/low (ระดับความมั่นใจ) — runtime ใช้แค่ min/max/optMin/optMax
const NPK_DEFAULT = {
  nLow: 50,   // N ต่ำ (ค่าประมาณจากเซ็นเซอร์ — กรมฯ วัด N เป็น % ไม่มีเกณฑ์ mg/kg)
  pLow: 10, pMid: 25,   // P ต่ำ/ปานกลาง mg/kg (LDD ตาราง 15)
  kLow: 60, kMid: 90,   // K ต่ำ/ปานกลาง mg/kg (LDD ตาราง 15)
  fertN: 'ปุ๋ยยูเรีย 46-0-0 หรือ 21-0-0',
  fertP: 'ปุ๋ย 0-46-0 หรือหินฟอสเฟต',
  fertK: 'ปุ๋ย 0-0-60 หรือโพแทสเซียมคลอไรด์'
};

const CROP_CRITERIA = {
  rice: {
    label: 'ข้าว', icon: '🌾',
    moisture: { min: 60, max: 100, src: 'แนวทางรดน้ำ — นาข้าวชื้นถึงแฉะ (LDD ใช้ mm/ฤดู)', conf: 'low' },
    ph:       { min: 4.0, max: 8.4, optMin: 5.6, optMax: 7.3, src: 'LDD ตาราง 3: S1 5.6–7.3, S2 5.1–5.5/7.4–7.8, S3 4.0–5.0/7.9–8.4', conf: 'high' },
    ec:       { max: 3.0, src: 'FAO 29 ตาราง 4: ECe 0% ข้าวเลื้อย = 3.0 dS/m (เดิม 2 = เกณฑ์ S1 กรมฯ ไม่ใช่ความทนเค็ม)', conf: 'high' },
    temp:     { min: 18, max: 35, src: 'LDD ตาราง 3 / FAO — ช่วงผลิตข้าวนาปี', conf: 'medium' },
    npk: { ...NPK_DEFAULT }
  },
  corn: {
    label: 'ข้าวโพด', icon: '🌽',
    moisture: { min: 50, max: 80, src: 'แนวทางรดน้ำ — ชื้นสม่ำเสมอ ไม่แฉะ', conf: 'low' },
    ph:       { min: 4.0, max: 8.4, optMin: 5.1, optMax: 7.3, src: 'LDD ตาราง 4: ขอบเขตบน 8.4 ยังต้องยืนยันกับ PDF ต้นฉบับ (ข้าวโพดทนด่างน้อยกว่าข้าว)', conf: 'medium' },
    ec:       { max: 1.7, src: 'FAO 29 ตาราง 4: ECe 0% ข้าวโพด = 1.7 dS/m (เดิม 2 เกินจริง ~4% ผลผลิตหาย)', conf: 'high' },
    temp:     { min: 16, max: 35, src: 'LDD ตาราง 4 / FAO — ช่วงผลิต', conf: 'medium' },
    npk: { ...NPK_DEFAULT,
      nLow: 60,                        // ข้าวโพดต้องการ N สูงกว่าพืชอื่น
      fertN: 'ปุ๋ยยูเรีย 46-0-0 (ข้าวโพดต้องการ N สูง)' }
  },
  rubber: {
    label: 'ยางพารา', icon: '🌳',
    moisture: { min: 30, max: 60, src: 'แนวทางรดน้ำ — ระบายน้ำดี ไม่แฉะ', conf: 'low' },
    ph:       { min: 4.5, max: 6.5, optMin: 5.6, optMax: 6.5, src: 'LDD เล่ม 28 / DOAE (เหมาะ 5.5–6.5)', conf: 'medium' },
    ec:       { max: 1, src: 'อ่อนไหวมาก — ไม่มีใน FAO 29, อ้างงานเค็มยางพารา (RRISL/DOAE)', conf: 'low' },
    temp:     { min: 22, max: 35, src: 'Hevea ช่วงเจริญ ~20–35°C, เหมาะ 24–28°C', conf: 'high' },
    npk: { ...NPK_DEFAULT,
      fertN: 'ปุ๋ย 21-0-0 (แอมโมเนียมซัลเฟต) หรือยูเรีย 46-0-0',
      fertK: 'ปุ๋ย 0-0-60 หรือ 13-13-21' }
  },
  other: {
    label: 'อื่นๆ', icon: '🌿',
    moisture: { min: 30, max: 80, src: 'แนวทางรดน้ำ — พืชทั่วไป', conf: 'low' },
    ph:       { min: 5.5, max: 7.5, optMin: 6.0, optMax: 6.5, src: 'เกณฑ์ทั่วไป (LDD pH 6–7)', conf: 'medium' },
    ec:       { max: 2, src: 'เกณฑ์ความเค็มทั่วไปของ LDD (ค่า default)', conf: 'low' },
    temp:     { min: 15, max: 35, src: 'ช่วงกว้างทั่วไป', conf: 'medium' },
    npk: { ...NPK_DEFAULT }
  },
  longan: {
    label: 'ลำไย', icon: '🍇',
    moisture: { min: 30, max: 60, src: 'แนวทางรดน้ำ — รากลึก ไม่แฉะ', conf: 'low' },
    ph:       { min: 5.0, max: 6.5, optMin: 5.5, optMax: 6.3, src: 'LDD เล่ม 28 (ลำไย): S1 5.5–6.3, S2–S3 5.0–6.5', conf: 'high' },
    ec:       { max: 1, src: 'อ่อนไหว (Sapindaceae) — ไม่มีใน FAO 29', conf: 'low' },
    temp:     { min: 18, max: 35, src: 'LDD เล่ม 28 — เขตร้อน เหมาะ 21–32°C (เสียหาย <4.5°C)', conf: 'medium' },
    npk: { ...NPK_DEFAULT }
  },
  lychee: {
    label: 'ลิ้นจี่', icon: '🍒',
    moisture: { min: 40, max: 80, src: 'แนวทางรดน้ำ — ชื้นสม่ำเสมอ ระบายน้ำดี', conf: 'low' },
    ph:       { min: 4.5, max: 6.5, optMin: 5.0, optMax: 6.0, src: 'LDD เล่ม 28 (ลิ้นจี่): S1 5.0–6.0, S2–S3 4.5–6.5', conf: 'high' },
    ec:       { max: 1, src: 'อ่อนไหว — ไม่มีใน FAO 29', conf: 'low' },
    temp:     { min: 15, max: 35, src: 'LDD เล่ม 28 — ต้องการฤดูหนาวเย็นเพื่อออกดอก', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  },
  durian: {
    label: 'ทุเรียน', icon: '🟢',
    moisture: { min: 50, max: 90, src: 'แนวทางรดน้ำ — น้ำมาก แต่ห้ามแฉะ (ขีดบน 90% เผื่อปลอดภัย)', conf: 'low' },
    ph:       { min: 5.0, max: 6.5, optMin: 5.5, optMax: 6.5, src: 'LDD เล่ม 28 (ทุเรียน): S1 5.5–6.5, S2–S3 5.0–6.5', conf: 'high' },
    ec:       { max: 1, src: 'อ่อนไหวมาก — ไม่มีใน FAO 29, DOAE แนะนำ <1', conf: 'medium' },
    temp:     { min: 24, max: 33, src: 'LDD เล่ม 28 / DOAE — ร้อนชื้น 24–30°C', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  },
  cassava: {
    label: 'มันสำปะหลัง', icon: '🌱',
    moisture: { min: 30, max: 70, src: 'แนวทางรดน้ำ — ทนแล้ง ได้น้ำพอเหมาะ', conf: 'low' },
    ph:       { min: 4.5, max: 7.5, optMin: 5.5, optMax: 6.5, src: 'LDD ตาราง 5 (มันสำปะหลัง): S1 5.5–6.5, S2–S3 4.5–7.5', conf: 'high' },
    ec:       { max: 1.0, src: 'อ่อนไหว — ไม่มีใน FAO 29 (เดิม 3 = ผิด: แย่สุดทั้งไฟล์ ทั้งที่มันสำปะหลังทนเค็มต่ำ)', conf: 'low' },
    temp:     { min: 20, max: 35, src: 'FAO/DOAE — เหมาะ 20–29°C, ทนได้ 12–40°C', conf: 'medium' },
    npk: { ...NPK_DEFAULT,
      nLow: 40 }                       // มันสำปะหลังทนดินขาด N ได้ดีกว่า
  },
  potato: {
    label: 'มันฝรั่ง', icon: '🥔',
    moisture: { min: 50, max: 80, src: 'แนวทางรดน้ำ — สม่ำเสมอ ห้ามแฉะ', conf: 'low' },
    ph:       { min: 5.0, max: 7.0, optMin: 5.2, optMax: 6.0, src: 'CIP/เอกสารวิชาการ: S1 5.2–6.0, S3 5.0–7.0 (เดิมอ้าง "เล่ม 28" ผิด — เล่ม 28 ครอบคลุมแค่ไม้ผล)', conf: 'high' },
    ec:       { max: 1.7, src: 'FAO 29 ตาราง 4: ECe 0% มันฝรั่ง = 1.7 dS/m', conf: 'high' },
    temp:     { min: 15, max: 28, src: 'CIP — พืชอากาศหนาว-กลาง, เสียหาย >28–30°C', conf: 'high' },
    npk: { ...NPK_DEFAULT,
      kLow: 70 }                       // มันฝรั่งต้องการ K สูง
  },
  onion: {
    label: 'หอมหัวใหญ่', icon: '🧅',
    moisture: { min: 50, max: 85, src: 'แนวทางรดน้ำ — ชื้นสม่ำเสมอ', conf: 'low' },
    ph:       { min: 5.5, max: 7.5, optMin: 6.0, optMax: 7.0, src: 'AVRDC/เอกสารวิชาการ: เหมาะ 6.0–6.8 (เดิมอ้าง "เล่ม 28" ผิด)', conf: 'high' },
    ec:       { max: 1.2, src: 'FAO 29 ตาราง 4: ECe 0% หอม = 1.2 dS/m (เดิม 1 ต่ำไปเล็กน้อย)', conf: 'high' },
    temp:     { min: 13, max: 25, src: 'AVRDC: 13–24°C', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  },
  garlic: {
    label: 'กระเทียม', icon: '🧄',
    moisture: { min: 45, max: 80, src: 'แนวทางรดน้ำ — พอเหมาะ', conf: 'low' },
    ph:       { min: 5.5, max: 7.5, optMin: 6.0, optMax: 7.0, src: 'เอกสารวิชาการ (คล้ายหอม): เหมาะ 6.0–7.0 (เดิมอ้าง "เล่ม 28" ผิด)', conf: 'high' },
    ec:       { max: 1, src: 'ไม่มีใน FAO 29 — ช่วงเอกสาร 1.0–1.5, เลือกค่าปลอดภัย', conf: 'medium' },
    temp:     { min: 12, max: 24, src: 'FAO/AVRDC: ช่วงการเจริญ 9–28°C, bulbing 10–15°C', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  },
  mangosteen: {
    label: 'มังคุด', icon: '🟣',
    moisture: { min: 50, max: 90, src: 'แนวทางรดน้ำ — น้ำมาก สม่ำเสมอ (ห้ามแฉะ)', conf: 'low' },
    ph:       { min: 5.0, max: 6.5, optMin: 5.5, optMax: 6.5, src: 'LDD เล่ม 28 (มังคุด): S1 5.5–6.5, S2–S3 5.0–6.5', conf: 'high' },
    ec:       { max: 1, src: 'อ่อนไหวมาก — ไม่มีใน FAO 29', conf: 'medium' },
    temp:     { min: 22, max: 33, src: 'LDD เล่ม 28 / DOAE — ร้อนชื้น 22–35°C เหมาะ ~25–30°C', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  },
  jujube: {
    label: 'พุทรา', icon: '🍏',
    moisture: { min: 40, max: 70, src: 'แนวทางรดน้ำ — ทนแล้ง น้ำพอเหมาะ', conf: 'low' },
    ph:       { min: 5.0, max: 8.0, optMin: 6.0, optMax: 7.0, src: 'Winrock FACT Sheet 98-03 / ICAR: ทนด่าง, เติบโตได้ถึง pH ~9', conf: 'high' },
    ec:       { max: 2, src: 'ICAR arid-zone: ทนเค็มปานกลาง (ECe ~2–3 ที่ 0%)', conf: 'medium' },
    temp:     { min: 18, max: 45, src: 'Winrock: ทนร้อน ~50°C, เติบโตปกติ 40–45°C (เดิม 35 ทำให้ หน้าฮ้อนของผู้ใช้ถูก flag ผิด)', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  },
  watermelon: {
    label: 'แตงโม', icon: '🍉',
    moisture: { min: 50, max: 80, src: 'แนวทางรดน้ำ — ชื้นสม่ำเสมอ', conf: 'low' },
    ph:       { min: 5.0, max: 7.5, optMin: 6.0, optMax: 7.0, src: 'เอกสารวิชาการ: เหมาะ 5.7–7.2 (เดิมอ้าง "เล่ม 28" ผิด)', conf: 'high' },
    ec:       { max: 2, src: 'FAO 29 ตาราง 4/5: แตงโม ECe 0% = 2.0 dS/m (moderately sensitive)', conf: 'medium' },
    temp:     { min: 20, max: 35, src: 'เอกสารวิชาการ — ต้องการ >25°C', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  },
  pumpkin: {
    label: 'ฟักทอง', icon: '🎃',
    moisture: { min: 40, max: 75, src: 'แนวทางรดน้ำ — พอเหมาะ ไม่แฉะ', conf: 'low' },
    ph:       { min: 5.5, max: 7.5, optMin: 6.0, optMax: 7.0, src: 'เอกสารวิชาการ: เหมาะ 6.0–7.0 (เดิมอ้าง "เล่ม 28" ผิด)', conf: 'high' },
    ec:       { max: 2, src: 'FAO 29 ตาราง 5: ไม่อยู่ในตัวเลข — ตระกูลฟัก ECe ~3+ ที่ 0%, ใช้ 2 เผื่อปลอดภัย', conf: 'medium' },
    temp:     { min: 18, max: 32, src: 'เอกสารวิชาการ — อากาศอบอุ่น', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  },
  vegetables: {
    label: 'ผักสวนครัว', icon: '🥬',
    moisture: { min: 50, max: 85, src: 'แนวทางรดน้ำ — ชื้นสม่ำเสมอ', conf: 'low' },
    ph:       { min: 5.5, max: 7.5, optMin: 6.0, optMax: 7.0, src: 'เกณฑ์ทั่วไป (LDD pH 6–7): เหมาะ 6.0–7.0 (เดิมอ้าง "เล่ม 28" ผิด)', conf: 'high' },
    ec:       { max: 1, src: 'FAO 29 ตาราง 4: เฉลี่ยผักเปราะ 1.0–2.5, เลือกค่าปลอดภัยสำหรับผักที่อ่อนไหว (ผักกาด แครอท ถั่ว)', conf: 'medium' },
    temp:     { min: 15, max: 32, src: 'ช่วงกว้างทั่วไป', conf: 'medium' },
    npk: { ...NPK_DEFAULT }
  },
  pomelo: {
    label: 'ส้มโอ', icon: '🍊',
    moisture: { min: 40, max: 75, src: 'แนวทางรดน้ำ — พอเหมาะ', conf: 'low' },
    ph:       { min: 5.0, max: 6.5, optMin: 5.5, optMax: 6.5, src: 'LDD เล่ม 28 (ส้มโอ): S1 5.5–6.5, S2–S3 5.0–6.5 — ตระกูลส้ม', conf: 'high' },
    ec:       { max: 1, src: 'Citrus อ่อนไหว — FAO 29 มีแค่ orange 1.7, ส้มโอเลือก 1 เผื่อปลอดภัย', conf: 'medium' },
    temp:     { min: 20, max: 35, src: 'LDD เล่ม 28 — เขตร้อน/กึ่งร้อน', conf: 'medium' },
    npk: { ...NPK_DEFAULT }
  },
  guava: {
    label: 'ฝรั่ง', icon: '🍐',
    moisture: { min: 40, max: 75, src: 'แนวทางรดน้ำ — พอเหมาะ', conf: 'low' },
    ph:       { min: 5.0, max: 7.0, optMin: 5.5, optMax: 6.5, src: 'UF/IFAS, FAO: ทน pH กว้าง 4.5–9.4, เหมาะ 5.5–6.5', conf: 'high' },
    ec:       { max: 2, src: 'UF/IFAS: ทนเค็มปานกลาง ECe ~2 ที่ 0% (ทนได้ถึง ~5–6)', conf: 'medium' },
    temp:     { min: 20, max: 35, src: 'UF/IFAS: เหมาะ 23–28°C, ชะลอ <16°C', conf: 'high' },
    npk: { ...NPK_DEFAULT }
  }
};

// ─── มาตราสเกตบาร์ NPK (อิงช่วง ต่ำ/ปานกลาง/สูง ของ LDD ตาราง 15) ──
const NPK_BAR_MAX = { n: 200, p: 50, k: 150 };
