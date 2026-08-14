'use strict';

// ─── Config ───────────────────────────────────────────────
const CONFIG = {
  interval:     3000,
  maxRetry:     999,
  retryDelay:   3000,
  useMockOnFail: false,   // ไม่มี mock data — แสดงข้อมูลจริงเท่านั้น
  // URL ของ backend บน Render
  cloudApiUrl:  'https://agriscan-v2.onrender.com'
};

// ─── เกณฑ์พืชรายชนิด (อ้างอิงกรมพัฒนาที่ดิน) ───────────────
// ที่มา: ศักยภาพการให้ผลผลิตพืชเศรษฐกิจของชุดดินในประเทศไทย (สำนักสำรวจและวิจัยทรัพยากรดิน, กรมพัฒนาที่ดิน)
// ตารางที่ 3 (ข้าว) และตารางที่ 4 (ข้าวโพด) — ดัดแปลงจากบัณฑิตและคำรณ (2542)
// ยางพารา: คู่มือการจำแนกความเหมาะสมของดินสำหรับพืชเศรษฐกิจ (เอกสารวิชาการ เล่ม 28, กองสำรวจและจำแนกดิน)
// โครงสร้าง: min/max = ขอบเขตยังปลูกได้ (S3) · optMin/optMax = ช่วงเหมาะสมสูงสุด (S1)
// หมายเหตุ: EC วัดเป็น µS/cm (1 dS/m = 1,000 µS/cm) · ความชื้น (%) เป็นแนวทางรดน้ำ (LDD ใช้ mm/ฤดู)
const CROP_CRITERIA = {
  rice: {
    label: 'ข้าว',
    icon:  '🌾',
    moisture: { min: 60, max: 100 },   // นาข้าว — ดินควรชื้นถึงแฉะ (แนวทางรดน้ำ)
    ph:       { min: 4.0, max: 8.4, optMin: 5.6, optMax: 7.3 },  // LDD ตาราง 3: S1 5.6–7.3, S2 5.1–5.5/7.4–7.8, S3 4.0–5.0/7.8–8.4
    ec:       { min: 0, max: 2000 },   // LDD ตาราง 3: S1 <2 dS/m, S2 2–5, S3 5–10 dS/m
    temp:     { min: 18, max: 35 },    // LDD ตาราง 3: S1 22–30, S2 31–33, S3 34–35°C
    npk: {
      nLow: 50, pLow: 10, pMid: 25, kLow: 60, kMid: 90,
      fertN: 'ปุ๋ยยูเรีย 46-0-0 หรือ 21-0-0',
      fertP: 'ปุ๋ย 0-46-0 หรือหินฟอสเฟต',
      fertK: 'ปุ๋ย 0-0-60 หรือโพแทสเซียมคลอไรด์'
    }
  },
  corn: {
    label: 'ข้าวโพด',
    icon:  '🌽',
    moisture: { min: 50, max: 80 },    // ข้าวโพด — ชื้นสม่ำเสมอ ไม่แฉะ (แนวทางรดน้ำ)
    ph:       { min: 4.0, max: 8.4, optMin: 5.1, optMax: 7.3 },  // LDD ตาราง 4: S1 5.1–7.3, S2 4.5–5.0/7.4–7.8, S3 4.0–4.4/7.9–8.4
    ec:       { min: 0, max: 2000 },   // LDD ตาราง 4: S1 <2 dS/m, S2 2–4, S3 4–8 dS/m
    temp:     { min: 16, max: 35 },    // LDD ตาราง 4: S1 24–30, S2 31–32, S3 33–35°C
    npk: {
      nLow: 60, pLow: 10, pMid: 25, kLow: 60, kMid: 90,
      fertN: 'ปุ๋ยยูเรีย 46-0-0 (ข้าวโพดต้องการ N สูง)',
      fertP: 'ปุ๋ย 0-46-0 หรือหินฟอสเฟต',
      fertK: 'ปุ๋ย 0-0-60 หรือโพแทสเซียมคลอไรด์'
    }
  },
  rubber: {
    label: 'ยางพารา',
    icon:  '🌳',
    moisture: { min: 30, max: 60 },    // ยางพารา — ต้องการดินระบายน้ำดี ไม่แฉะ (แนวทางรดน้ำ)
    ph:       { min: 4.5, max: 6.5, optMin: 5.6, optMax: 6.5 },  // เล่ม 28: S1 4.5–6.5 (เหมาะ 5.6–6.5)
    ec:       { min: 0, max: 1000 },   // <1 dS/m เหมาะสม — ยางพาราอ่อนไหวต่อความเค็มมาก
    temp:     { min: 22, max: 35 },
    npk: {
      nLow: 50, pLow: 10, pMid: 25, kLow: 60, kMid: 90,
      fertN: 'ปุ๋ย 21-0-0 (แอมโมเนียมซัลเฟต) หรือยูเรีย 46-0-0',
      fertP: 'ปุ๋ย 0-46-0 หรือหินฟอสเฟต',
      fertK: 'ปุ๋ย 0-0-60 หรือ 13-13-21'
    }
  },
  other: {
    label: 'อื่นๆ',
    icon:  '🌿',
    moisture: { min: 30, max: 80 },    // พืชทั่วไป (แนวทางรดน้ำ)
    ph:       { min: 5.5, max: 7.5, optMin: 6.0, optMax: 6.5 },  // พืชส่วนใหญ่เหมาะ pH 6.0–6.5 (LDD)
    ec:       { min: 0, max: 2000 },   // <2 dS/m เหมาะสม (เกณฑ์ความเค็มทั่วไปของ LDD)
    temp:     { min: 15, max: 35 },
    npk: {
      nLow: 50, pLow: 10, pMid: 25, kLow: 60, kMid: 90,
      fertN: 'ปุ๋ยยูเรีย 46-0-0 หรือ 21-0-0',
      fertP: 'ปุ๋ย 0-46-0 หรือหินฟอสเฟต',
      fertK: 'ปุ๋ย 0-0-60 หรือโพแทสเซียมคลอไรด์'
    }
  }
};

// ─── Crop selection ──────────────────────────────────────
const CROP_KEY = 'agriscan_crop';

function getCropKey() {
  const k = localStorage.getItem(CROP_KEY);
  return CROP_CRITERIA[k] ? k : 'other';
}

function getCrop() {
  return CROP_CRITERIA[getCropKey()];
}

function changeCrop(key) {
  if (!CROP_CRITERIA[key]) key = 'other';
  localStorage.setItem(CROP_KEY, key);
  syncCropUI();
  // Re-evaluate with latest data if we have it
  if (state.data) updateUI(state.data);
}

function syncCropUI() {
  const sel = $('crop-select');
  const tag = $('crop-badge');
  if (sel) sel.value = getCropKey();
  if (tag) tag.textContent = getCrop().icon + ' ' + getCrop().label;
}

// ─── State ────────────────────────────────────────────────
let state = {
  data:         null,
  online:       false,
  isMock:       false,
  retryCount:   0,
  timer:        null,
  activeApiUrl: null
};

// ─── DOM refs ─────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ─── Fetch data (Dynamic IP resolution) ──────────────────
async function fetchData() {
  const candidates = [];
  
  // 1. Stored Custom IP
  const customIp = localStorage.getItem('esp32_custom_ip');
  if (customIp) {
    let cleanIp = customIp.trim();
    if (!cleanIp.startsWith('http')) cleanIp = 'http://' + cleanIp;
    if (!cleanIp.endsWith('/data')) cleanIp = cleanIp.replace(/\/+$/, '') + '/data';
    candidates.push(cleanIp);
  }

  // 2. Active Working URL
  if (state.activeApiUrl && !candidates.includes(state.activeApiUrl)) {
    candidates.push(state.activeApiUrl);
  }

  // 3. Current Host Origin (if served by ESP32 or server)
  if (window.location.protocol.startsWith('http')) {
    const originUrl = window.location.origin + '/data';
    if (!candidates.includes(originUrl)) candidates.push(originUrl);
  }

  // 4. Cloud backend บน Render (ค่าจริงจาก ESP32 ที่ส่งขึ้นคลาวด์)
  const cloudUrl = CONFIG.cloudApiUrl.replace(/\/+$/, '') + '/data';
  if (!candidates.includes(cloudUrl)) candidates.push(cloudUrl);

  // 5. Fallback mDNS & Default Gateways (ESP32 บนเครือข่ายท้องถิ่น)
  const fallbacks = ['http://agriscan.local/data', 'http://192.168.1.1/data', 'http://localhost:5000/data'];
  fallbacks.forEach(f => { if (!candidates.includes(f)) candidates.push(f); });

  let success = false;

  for (const url of candidates) {
    try {
      const ctrl = new AbortController();
      const timeout = setTimeout(() => ctrl.abort(), 3000);
      const res = await fetch(url, { signal: ctrl.signal });
      clearTimeout(timeout);

      if (!res.ok) continue;
      const json = await res.json();

      state.activeApiUrl = url;
      state.online = true;
      state.isMock = false;
      state.retryCount = 0;
      updateUI(json);
      setStatus('online');
      hideBanners();
      
      try {
        const host = new URL(url, window.location.href).hostname;
        $('ip-badge').textContent = (host || 'agriscan.local') + ' ⚙';
      } catch (e) {}

      success = true;
      break;
    } catch (err) {
      // try next candidate
    }
  }

  if (!success) {
    state.activeApiUrl = null;
    state.online = false;
    state.retryCount++;

    setStatus('offline');
    showBanners();
  }
}

// ─── Change IP/Host Manually ──────────────────────────────
function changeIp() {
  const current = localStorage.getItem('esp32_custom_ip') || '';
  const input = prompt('ระบุ IP Address หรือ Host ของ ESP32 (เช่น 192.168.137.100 หรือ agriscan.local):', current);
  if (input !== null) {
    const val = input.trim();
    if (val) {
      localStorage.setItem('esp32_custom_ip', val);
    } else {
      localStorage.removeItem('esp32_custom_ip');
    }
    state.activeApiUrl = null;
    fetchData();
  }
}

// ─── Update UI ────────────────────────────────────────────
function updateUI(d) {
  state.data = d;
  const crop = getCrop();
  const c = crop; // shorthand

  // Moisture
  const m = clamp(d.moisture, 0, 100);
  setValue('val-moisture', m.toFixed(1));
  animateBar('bar-moisture', m, 100);
  const barEl = $('bar-moisture');
  if (m < c.moisture.min) {
    barEl.style.setProperty('--bar-color', '#f87171');
    barEl.style.background = 'linear-gradient(90deg,#ef4444,#f87171)';
    barEl.style.boxShadow  = '0 0 8px rgba(239,68,68,0.5)';
    setChip('status-moisture', 'alert', `⚠ ดินแห้งเกินไป — ควรรดน้ำ (เกณฑ์ ${c.label}: ≥${c.moisture.min}%)`);
  } else if (m > c.moisture.max) {
    barEl.style.background = 'linear-gradient(90deg,#3b82f6,#60a5fa)';
    barEl.style.boxShadow  = '0 0 8px rgba(59,130,246,0.5)';
    setChip('status-moisture', 'warn', `💧 ชื้นเกินไป — ระวังรากเน่า (เกณฑ์ ${c.label}: ≤${c.moisture.max}%)`);
  } else {
    barEl.style.background = 'linear-gradient(90deg,#22c55e,#4ade80)';
    barEl.style.boxShadow  = '0 0 8px rgba(34,197,94,0.5)';
    setChip('status-moisture', 'ok', `✓ ปกติ (เกณฑ์ ${c.label}: ${c.moisture.min}–${c.moisture.max}%)`);
  }

  // Temperature
  setValue('val-temperature', (+d.temperature).toFixed(1));
  if (d.temperature > c.temp.max)      setChip('status-temperature', 'alert', `🌡 ร้อนเกินไป (เกณฑ์ ${c.label}: ≤${c.temp.max}°C)`);
  else if (d.temperature < c.temp.min) setChip('status-temperature', 'warn', `❄ เย็นเกินไป (เกณฑ์ ${c.label}: ≥${c.temp.min}°C)`);
  else                                 setChip('status-temperature', 'ok', '✓ ปกติ');

  // EC — เกณฑ์กรมพัฒนาที่ดิน (1 dS/m = 1,000 µS/cm)
  setValue('val-ec', Math.round(d.ec));
  if (d.ec > c.ec.max)       setChip('status-ec', 'alert', `⚠ เกลือสูงเกินไป — ${c.label} เหมาะกับ EC ≤${c.ec.max/1000} dS/m`);
  else if (d.ec < c.ec.min)  setChip('status-ec', 'warn', '↓ EC ต่ำ');
  else                       setChip('status-ec', 'ok', `✓ ปกติ (เกณฑ์ ${c.label}: ≤${c.ec.max/1000} dS/m)`);

  // pH — เกณฑ์กรมพัฒนาที่ดิน
  setValue('val-ph', (+d.ph).toFixed(1));
  if (d.ph < c.ph.min)            setChip('status-ph', 'alert', `⚠ กรดเกินไป (เกณฑ์ ${c.label}: pH ≥${c.ph.min})`);
  else if (d.ph > c.ph.max)       setChip('status-ph', 'warn', `⚠ ด่างเกินไป (เกณฑ์ ${c.label}: pH ≤${c.ph.max})`);
  else if (d.ph < c.ph.optMin || d.ph > c.ph.optMax) setChip('status-ph', 'warn', `ℹ พอใช้ได้ (เหมาะสุด pH ${c.ph.optMin}–${c.ph.optMax})`);
  else                            setChip('status-ph', 'ok', `✓ ปกติ (เกณฑ์ ${c.label}: pH ${c.ph.min}–${c.ph.max})`);

  // NPK — เกณฑ์กรมพัฒนาที่ดิน (ตารางที่ 15, กองสำรวจดิน 2523)
  // P: ต่ำ <10, ปานกลาง 10–25, สูง >25 mg/kg · K: ต่ำ <60, ปานกลาง 60–90, สูง >90 mg/kg
  // N: กรมฯ ไม่มีเกณฑ์ mg/kg — เป็นค่าประมาณจากเซ็นเซอร์ (ใช้ 50 เป็นค่าบ่งชี้)
  const nMax = 200, pMax = 50, kMax = 150;
  setValue('val-n', Math.round(d.n) + ' <small>mg/kg</small>');
  setValue('val-p', Math.round(d.p) + ' <small>mg/kg</small>');
  setValue('val-k', Math.round(d.k) + ' <small>mg/kg</small>');
  animateBar('bar-n', d.n, nMax);
  animateBar('bar-p', d.p, pMax);
  animateBar('bar-k', d.k, kMax);

  const npkAlerts = [], npkWarns = [];
  if (d.n < c.npk.nLow)  npkAlerts.push('N ต่ำ');
  if (d.p < c.npk.pLow)  npkAlerts.push('P ต่ำ');
  else if (d.p < c.npk.pMid) npkWarns.push('P ปานกลาง');
  if (d.k < c.npk.kLow)  npkAlerts.push('K ต่ำ');
  else if (d.k < c.npk.kMid) npkWarns.push('K ปานกลาง');
  if (npkAlerts.length > 0)
    setChip('status-npk', 'warn', '⚠ ' + npkAlerts.join(' / '));
  else if (npkWarns.length > 0)
    setChip('status-npk', 'warn', 'ℹ ' + npkWarns.join(' / '));
  else
    setChip('status-npk', 'ok', '✓ ปกติ');

  // Recommendations
  buildRecommendations(d);

  // Timestamp — แสดงเวลาที่เซ็นเซอร์ส่งค่า (จากคลาวด์) ถ้า API ให้มา
  const ts = d.timestamp ? new Date(d.timestamp) : new Date();
  $('last-update').textContent = ts.toLocaleTimeString('th-TH');
}

// ─── Build recommendations ────────────────────────────────
function buildRecommendations(d) {
  const recs = [];
  const c = getCrop();
  const ph = (+d.ph).toFixed(1);

  // Moisture ตามเกณฑ์พืชที่เลือก
  if (d.moisture < c.moisture.min) {
    recs.push({ type:'alert', icon:'💧', title:'ดินแห้ง — ควรรดน้ำ', desc:`ความชื้น ${d.moisture.toFixed(1)}% ต่ำกว่าเกณฑ์ ${c.label} (≥${c.moisture.min}%) ควรเปิดระบบรดน้ำทันที` });
  } else if (d.moisture > c.moisture.max) {
    recs.push({ type:'warn', icon:'🌊', title:'ดินชื้นเกินไป', desc:`ความชื้น ${d.moisture.toFixed(1)}% สูงกว่าเกณฑ์ ${c.label} (≤${c.moisture.max}%) อาจทำให้รากเน่าได้ ควรหยุดรดน้ำและปรับปรุงการระบายน้ำ` });
  } else {
    recs.push({ type:'ok', icon:'✅', title:'ความชื้นอยู่ในเกณฑ์ปกติ', desc:`ความชื้น ${d.moisture.toFixed(1)}% อยู่ในช่วงเหมาะสมของ ${c.label} (${c.moisture.min}–${c.moisture.max}%)` });
  }

  // pH ตามเกณฑ์กรมพัฒนาที่ดินของพืช
  if (d.ph < c.ph.min) {
    recs.push({ type:'alert', icon:'🪨', title:'ดินเป็นกรดเกินไป', desc:`pH ${ph} ต่ำกว่าเกณฑ์ ${c.label} (pH ≥${c.ph.min}) ควรใส่ปูนขาว (Lime) หรือโดโลไมท์เพื่อปรับสภาพดิน` });
  } else if (d.ph > c.ph.max) {
    recs.push({ type:'warn', icon:'⚗️', title:'ดินเป็นด่างเกินไป', desc:`pH ${ph} สูงกว่าเกณฑ์ ${c.label} (pH ≤${c.ph.max}) ควรใส่กำมะถัน (Sulfur) หรือปุ๋ยอินทรีย์เพื่อลด pH` });
  } else if (d.ph < c.ph.optMin || d.ph > c.ph.optMax) {
    recs.push({ type:'warn', icon:'ℹ️', title:'pH พอใช้ได้แต่ไม่เหมาะที่สุด', desc:`pH ${ph} ยังอยู่ในช่วงที่ ${c.label} ขึ้นได้ แต่ช่วงเหมาะที่สุดคือ ${c.ph.optMin}–${c.ph.optMax}` });
  } else {
    recs.push({ type:'ok', icon:'✅', title:'pH อยู่ในเกณฑ์เหมาะสม', desc:`pH ${ph} อยู่ในช่วงเหมาะที่สุดของ ${c.label} (${c.ph.optMin}–${c.ph.optMax})` });
  }

  // เกณฑ์ P, K อ้างอิงกรมพัฒนาที่ดิน (ตารางที่ 15) · N เป็นค่าประมาณจากเซ็นเซอร์
  if (d.n < c.npk.nLow) {
    recs.push({ type:'warn', icon:'🌿', title:'ไนโตรเจน (N) ค่อนข้างต่ำ', desc:`N = ${Math.round(d.n)} mg/kg (ค่าประมาณจากเซ็นเซอร์ — กรมฯ วัด N เป็น %) ควรใส่ ${c.npk.fertN}` });
  }

  if (d.p < c.npk.pLow) {
    recs.push({ type:'alert', icon:'🌱', title:'ฟอสฟอรัส (P) ต่ำ', desc:`P = ${Math.round(d.p)} mg/kg ต่ำกว่าเกณฑ์กรมพัฒนาที่ดิน (<${c.npk.pLow}) ควรใส่ ${c.npk.fertP}` });
  } else if (d.p < c.npk.pMid) {
    recs.push({ type:'warn', icon:'🌱', title:'ฟอสฟอรัส (P) ปานกลาง', desc:`P = ${Math.round(d.p)} mg/kg ระดับปานกลาง (${c.npk.pLow}–${c.npk.pMid}) ตามเกณฑ์กรมพัฒนาที่ดิน — ยังไม่ต้องใส่ปุ๋ย` });
  }

  if (d.k < c.npk.kLow) {
    recs.push({ type:'alert', icon:'🍂', title:'โพแทสเซียม (K) ต่ำ', desc:`K = ${Math.round(d.k)} mg/kg ต่ำกว่าเกณฑ์กรมพัฒนาที่ดิน (<${c.npk.kLow}) ควรใส่ ${c.npk.fertK}` });
  } else if (d.k < c.npk.kMid) {
    recs.push({ type:'warn', icon:'🍂', title:'โพแทสเซียม (K) ปานกลาง', desc:`K = ${Math.round(d.k)} mg/kg ระดับปานกลาง (${c.npk.kLow}–${c.npk.kMid}) ตามเกณฑ์กรมพัฒนาที่ดิน — ยังไม่ต้องใส่ปุ๋ย` });
  }

  // EC ตามความทนเค็มของพืช
  if (d.ec > c.ec.max) {
    recs.push({ type:'alert', icon:'⚡', title:'ดินเค็มเกินไปสำหรับ ' + c.label, desc:`EC = ${Math.round(d.ec)} µS/cm เกินเกณฑ์ ${c.label} (≤${c.ec.max/1000} dS/m) ตามกรมพัฒนาที่ดิน ควรงดใส่ปุ๋ยเคมี ล้างเกลือด้วยน้ำ หรือเลือกพันธุ์ทนเค็ม` });
  }

  if (d.temperature > c.temp.max) {
    recs.push({ type:'alert', icon:'🌡', title:'อุณหภูมิดินสูงเกินไป', desc:`${(+d.temperature).toFixed(1)}°C สูงกว่าเกณฑ์ ${c.label} (≤${c.temp.max}°C) อาจส่งผลต่อการดูดซึมของราก ควรคลุมดินเพื่อลดความร้อน` });
  }

  const grid = $('rec-grid');
  grid.innerHTML = recs.map(r => `
    <div class="rec-item ${r.type}">
      <span class="rec-icon">${r.icon}</span>
      <div class="rec-content">
        <div class="rec-title">${r.title}</div>
        <div class="rec-desc">${r.desc}</div>
      </div>
    </div>
  `).join('');
}

// ─── Helpers ──────────────────────────────────────────────
function setValue(id, val) {
  const el = $(id);
  if (!el) return;
  const old = el.innerHTML;
  el.innerHTML = String(val);
  if (old !== String(val) && old !== '--') {
    el.classList.remove('flash');
    void el.offsetWidth; // reflow
    el.classList.add('flash');
  }
}

function animateBar(id, val, max) {
  const el = $(id);
  if (!el) return;
  const pct = clamp((val / max) * 100, 0, 100);
  el.style.width = pct + '%';
}

function setChip(id, type, text) {
  const el = $(id);
  if (!el) return;
  el.className = `card-status ${type}`;
  el.textContent = text;
}

function setStatus(mode) {
  const badge = $('status-badge');
  const text  = $('status-text');
  badge.className = `status-badge ${mode}`;
  if (mode === 'online') {
    text.textContent = 'ออนไลน์';
  } else if (mode === 'offline') {
    text.textContent = state.isMock ? 'ออฟไลน์ (Mock)' : 'ออฟไลน์';
  } else {
    text.textContent = 'กำลังเชื่อมต่อ...';
  }
}

function showBanners() {
  $('connecting-banner').classList.add('visible');
  $('retry-count').textContent = `Retry ครั้งที่ ${state.retryCount} · ทุก ${CONFIG.retryDelay/1000} วินาที`;
  if (state.isMock) $('mock-banner').classList.add('visible');
}

function hideBanners() {
  $('connecting-banner').classList.remove('visible');
  $('mock-banner').classList.remove('visible');
}

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

// ─── Manual refresh ───────────────────────────────────────
async function manualRefresh() {
  const btn = $('btn-refresh');
  btn.classList.add('spinning');
  btn.disabled = true;
  await fetchData();
  setTimeout(() => {
    btn.classList.remove('spinning');
    btn.disabled = false;
  }, 600);
}

// ─── Auto-polling ─────────────────────────────────────────
function startPolling() {
  fetchData();
  state.timer = setInterval(fetchData, CONFIG.interval);
}

// ─── Init ─────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  syncCropUI();
  startPolling();
});

// Reconnect when tab becomes visible
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && !state.online) fetchData();
});
