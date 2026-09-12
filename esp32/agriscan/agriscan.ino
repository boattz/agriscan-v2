/**
 * Agriscan v2 — RS485 Soil Sensor 7-in-1 + WiFi + WebServer
 * GET /data  →  JSON สำหรับแดชบอร์ด
 */

#include <ModbusMaster.h>
#include <WiFi.h>
#include <WebServer.h>      // ← เพิ่ม
#include <ESPmDNS.h>        // ← เพิ่ม mDNS
#include <HTTPClient.h>     // ← ส่งข้อมูลขึ้นคลาวด์
#include <WiFiClientSecure.h>
#include "dashboard.h"      // ← หน้าเว็บ HTML
#include "secrets.h"        // ← WiFi + API key (ไฟล์นี้ไม่ขึ้น Git)

// ── WiFi ──────────────────────────────────────────────────
// SSID/รหัส WiFi อยู่ใน secrets.h (ไฟล์นี้ไม่ขึ้น Git — กันข้อมูลหลุด)
// ถ้าต้องการแก้ WiFi ให้แก้ที่ secrets.h แล้ว re-flash

// ── Cloud Upload ───────────────────────────────────────────
// URL ของ backend บน Render
const char* CLOUD_URL = "https://agriscan-v2.onrender.com/api/readings";
// API key อยู่ใน secrets.h (ดูจาก Render Dashboard → Environment → API_KEY)
// ความถี่ส่งข้อมูลขึ้นคลาวด์ (มิลลิวินาที) — 3,000 = ทุก 3 วินาที
#define POST_INTERVAL_MS  3000

// ── Calibration offsets (ชดเชยเซ็นเซอร์หลังเทียบกับ buffer/เครื่องมืออ้างอิง) ──
// วิธีใช้: เทียบกับสารละลายมาตรฐานแล้วใส่ส่วนต่าง เช่น อ่าน pH ได้ 6.7 แต่ buffer
// คือ 7.0 → ตั้ง CAL_PH 0.3 แล้ว re-flash (ทศนิยม 1 ตำแหน่งก็พอ)
#define CAL_MOISTURE     0.0
#define CAL_TEMPERATURE  0.0
#define CAL_EC           0
#define CAL_PH           0.0
#define CAL_N            0
#define CAL_P            0
#define CAL_K            0

// ── ช่วงที่เป็นไปได้ทางฟิสิกส์ (หลุด = เซ็นเซอร์เพี้ยน/สายหลุด → valid=false) ──
#define LIM_MOIST_MIN  0.0
#define LIM_MOIST_MAX  100.0
#define LIM_TEMP_MIN   -10.0
#define LIM_TEMP_MAX   60.0
#define LIM_EC_MIN     0
#define LIM_EC_MAX     20000
#define LIM_PH_MIN     0.0
#define LIM_PH_MAX     14.0
#define LIM_NPK_MIN    0
#define LIM_NPK_MAX    1999

// ── ช่วงน่าสงสัย (เป็นไปได้แต่แปลก → valid=true แต่ quality=suspect) ──
#define SUS_TEMP_MAX   50.0
#define SUS_EC_MAX     5000
#define SUS_PH_LO      3.0
#define SUS_PH_HI      10.0

// ── Median filter: อ่านกี่ครั้งต่อรอบ (คั่น 80ms) ──
#define NUM_SAMPLES    5

// ── RS485 ─────────────────────────────────────────────────
#define RXD2        16
#define TXD2        17
#define DE_RE_PIN   4       // pin ต่อ DE+RE รวมกันของ MAX485 (ไม่มีพินนี้ลบได้)
#define BAUD_RATE   4800
#define MODBUS_ID   1

ModbusMaster node;
WebServer server(80);       // ← Web Server port 80

// ── Register map ──────────────────────────────────────────
#define REG_MOISTURE     0x0000
#define REG_TEMPERATURE  0x0001
#define REG_EC           0x0002
#define REG_PH           0x0003
#define REG_NITROGEN     0x0004
#define REG_PHOSPHORUS   0x0005
#define REG_POTASSIUM    0x0006
#define REG_COUNT        7

// ── Struct ────────────────────────────────────────────────
// quality: 0=good 1=suspect 2=bad · reason: รหัสสั้นให้ cloud/dashboard แปลเป็นไทย
struct SoilData {
  float moisture;
  float temperature;
  int   ec;
  float ph;
  int   nitrogen;
  int   phosphorus;
  int   potassium;
  bool  valid;
  uint8_t quality;
  char  reason[32];
};

SoilData lastData = {0, 0, 0, 0, 0, 0, 0, false, 2, "init"};

// ── WiFi Connect ──────────────────────────────────────────
void connectWiFi() {
  Serial.printf("กำลังเชื่อมต่อ WiFi: %s ", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  uint8_t retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < 20) {
    delay(500);
    Serial.print(".");
    retry++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.printf("✅ WiFi เชื่อมต่อสำเร็จ! IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println();
    Serial.println("⚠ WiFi เชื่อมต่อไม่ได้ — ทำงานต่อแบบ offline");
  }
}

// ── Read Sensor (median NUM_SAMPLES + calibration + range check) ──
// คืน valid=false พร้อม reason เมื่อ Modbus ล้มเหลวหรือค่าหลุดโลก —
// ผู้เรียกต้องอัปเดต lastData เสมอ (อย่าเงียบใช้ค่าเก่า) ให้ dashboard โชว์ sensor-error
static float medianOf5(float *a) {
  // bubble sort 5 ตัว (เล็กพอ ไม่ต้องไลบรารี)
  for (uint8_t i = 0; i < 4; i++)
    for (uint8_t j = i + 1; j < 5; j++)
      if (a[j] < a[i]) { float t = a[i]; a[i] = a[j]; a[j] = t; }
  return a[2];
}
static int medianInt5(float *a) { return (int)(medianOf5(a) + 0.5f); }

SoilData readSensor() {
  SoilData d = {0, 0, 0, 0, 0, 0, 0, false, 2, "modbus_timeout"};
  float mArr[NUM_SAMPLES], tArr[NUM_SAMPLES], ecArr[NUM_SAMPLES],
        phArr[NUM_SAMPLES], nArr[NUM_SAMPLES], pArr[NUM_SAMPLES], kArr[NUM_SAMPLES];
  uint8_t ok = 0;

  for (uint8_t i = 0; i < NUM_SAMPLES; i++) {
    uint8_t result = node.readHoldingRegisters(REG_MOISTURE, REG_COUNT);
    if (result == node.ku8MBSuccess) {
      mArr[ok]  = node.getResponseBuffer(0) / 10.0;
      tArr[ok]  = (int16_t)node.getResponseBuffer(1) / 10.0;
      ecArr[ok] = node.getResponseBuffer(2);
      phArr[ok] = node.getResponseBuffer(3) / 10.0;
      nArr[ok]  = node.getResponseBuffer(4);
      pArr[ok]  = node.getResponseBuffer(5);
      kArr[ok]  = node.getResponseBuffer(6);
      ok++;
    } else {
      Serial.printf("[Modbus] sample %d fail (%d)\n", i, result);
    }
    if (i + 1 < NUM_SAMPLES) delay(80);
  }
  Serial.printf("[Modbus] ok=%d/%d\n", ok, NUM_SAMPLES);

  if (ok < 3) return d;  // ล้มเหลวเกินครึ่ง → valid=false reason=modbus_timeout

  // median + calibration
  d.moisture    = medianOf5(mArr)    + CAL_MOISTURE;
  d.temperature = medianOf5(tArr)    + CAL_TEMPERATURE;
  d.ec          = medianInt5(ecArr)  + CAL_EC;
  d.ph          = medianOf5(phArr)   + CAL_PH;
  d.nitrogen    = medianInt5(nArr)   + CAL_N;
  d.phosphorus  = medianInt5(pArr)   + CAL_P;
  d.potassium   = medianInt5(kArr)   + CAL_K;

  // จับเซ็นเซอร์แกว่ง (max-min) จากตัวอย่างที่อ่านสำเร็จ
  float mSpread = 0, tSpread = 0, phSpread = 0;
  { float mn = mArr[0], mx = mArr[0];
    for (uint8_t i = 1; i < ok; i++) { if (mArr[i] < mn) mn = mArr[i]; if (mArr[i] > mx) mx = mArr[i]; }
    mSpread = mx - mn; }
  { float mn = tArr[0], mx = tArr[0];
    for (uint8_t i = 1; i < ok; i++) { if (tArr[i] < mn) mn = tArr[i]; if (tArr[i] > mx) mx = tArr[i]; }
    tSpread = mx - mn; }
  { float mn = phArr[0], mx = phArr[0];
    for (uint8_t i = 1; i < ok; i++) { if (phArr[i] < mn) mn = phArr[i]; if (phArr[i] > mx) mx = phArr[i]; }
    phSpread = mx - mn; }

  // 1) ตรวจหลุดโลก → bad
  const char *badField = NULL;
  if      (d.moisture < LIM_MOIST_MIN || d.moisture > LIM_MOIST_MAX) badField = "moisture";
  else if (d.temperature < LIM_TEMP_MIN || d.temperature > LIM_TEMP_MAX) badField = "temperature";
  else if (d.ec < LIM_EC_MIN || d.ec > LIM_EC_MAX)   badField = "ec";
  else if (d.ph < LIM_PH_MIN || d.ph > LIM_PH_MAX)   badField = "ph";
  else if (d.nitrogen < LIM_NPK_MIN || d.nitrogen > LIM_NPK_MAX
        || d.phosphorus < LIM_NPK_MIN || d.phosphorus > LIM_NPK_MAX
        || d.potassium < LIM_NPK_MIN || d.potassium > LIM_NPK_MAX) badField = "npk";
  if (badField) {
    d.valid = false; d.quality = 2;
    snprintf(d.reason, sizeof(d.reason), "out_of_range:%s", badField);
    return d;
  }

  // 2) ตรวจน่าสงสัย → suspect แต่ยัง valid
  const char *sus = NULL;
  if      (d.temperature > SUS_TEMP_MAX)           sus = "suspect:temp_high";
  else if (d.ec > SUS_EC_MAX)                      sus = "suspect:ec_high";
  else if (d.ph < SUS_PH_LO || d.ph > SUS_PH_HI)   sus = "suspect:ph_extreme";
  else if (mSpread > 10.0 || tSpread > 5.0 || phSpread > 1.0) sus = "suspect:unstable";
  if (sus) {
    d.valid = true; d.quality = 1;
    snprintf(d.reason, sizeof(d.reason), "%s", sus);
    return d;
  }

  d.valid = true; d.quality = 0;
  snprintf(d.reason, sizeof(d.reason), "ok");
  return d;
}

static const char* qualityStr(uint8_t q) {
  return q == 0 ? "good" : (q == 1 ? "suspect" : "bad");
}

// ── Upload to Cloud (POST /api/readings) ──────────────────
void uploadReading() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[Cloud] WiFi ไม่เชื่อมต่อ — ข้ามการส่ง");
    return;
  }
  if (!lastData.valid) {
    Serial.printf("[Cloud] ค่าไม่ valid (%s) — ยังส่งพร้อม flag เพื่อให้ backend ปฏิเสธ/บันทึกอย่างถูกต้อง\n", lastData.reason);
    // ไม่ return — ส่ง valid=false ขึ้นไปให้ backend ตอบ 422 (กัน dashboard เข้าใจผิดว่าค่าสด)
  }

  WiFiClientSecure client;
  client.setInsecure();   // ไม่ตรวจ certificate (เพียงพอสำหรับการทดลอง/พัฒนา)

  HTTPClient http;
  if (!http.begin(client, CLOUD_URL)) {
    Serial.println("[Cloud] เริ่ม HTTP ไม่สำเร็จ");
    return;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);

  String body = "{";
  body += "\"moisture\":"    + String(lastData.moisture, 1)    + ",";
  body += "\"temperature\":" + String(lastData.temperature, 1) + ",";
  body += "\"ec\":"          + String(lastData.ec)             + ",";
  body += "\"ph\":"          + String(lastData.ph, 1)          + ",";
  body += "\"n\":"           + String(lastData.nitrogen)       + ",";
  body += "\"p\":"           + String(lastData.phosphorus)     + ",";
  body += "\"k\":"           + String(lastData.potassium)      + ",";
  body += "\"valid\":"       + String(lastData.valid ? "true" : "false") + ",";
  body += "\"quality\":\""  + String(qualityStr(lastData.quality)) + "\",";
  body += "\"reason\":\""   + String(lastData.reason) + "\"";
  body += "}";

  int code = http.POST(body);
  if (code > 0) {
    Serial.printf("[Cloud] POST %d → %s\n", code, http.getString().c_str());
  } else {
    Serial.printf("[Cloud] ส่งล้มเหลว (%d)\n", code);
  }
  http.end();
}

// ── HTTP Handler: GET /data ───────────────────────────────
void handleData() {
  // CORS headers — สำคัญมาก ให้เบราว์เซอร์ดึงได้
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");

  String json = "{";
  json += "\"moisture\":"    + String(lastData.moisture, 1)    + ",";
  json += "\"temperature\":" + String(lastData.temperature, 1) + ",";
  json += "\"ec\":"          + String(lastData.ec)             + ",";
  json += "\"ph\":"          + String(lastData.ph, 1)          + ",";
  json += "\"n\":"           + String(lastData.nitrogen)       + ",";
  json += "\"p\":"           + String(lastData.phosphorus)     + ",";
  json += "\"k\":"           + String(lastData.potassium)      + ",";
  json += "\"valid\":"       + String(lastData.valid ? "true" : "false") + ",";
  json += "\"quality\":\""   + String(qualityStr(lastData.quality)) + "\",";
  json += "\"reason\":\""    + String(lastData.reason) + "\"";
  json += "}";

  server.send(200, "application/json", json);
  Serial.println("[HTTP] GET /data → ส่ง JSON สำเร็จ");
}

// ── HTTP Handler: OPTIONS (preflight) ────────────────────
void handleOptions() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  server.send(204);
}

// ── Print to Serial ───────────────────────────────────────
void printSerial(const SoilData& d) {
  Serial.println("┌────────────────────────────────┐");
  Serial.printf( "│ ความชื้น    : %6.1f %%\n", d.moisture);
  Serial.printf( "│ อุณหภูมิ    : %6.1f °C\n", d.temperature);
  Serial.printf( "│ EC          : %6d µS/cm\n", d.ec);
  Serial.printf( "│ pH          : %6.1f\n", d.ph);
  Serial.printf( "│ N           : %6d mg/kg\n", d.nitrogen);
  Serial.printf( "│ P           : %6d mg/kg\n", d.phosphorus);
  Serial.printf( "│ K           : %6d mg/kg\n", d.potassium);
  Serial.printf( "│ WiFi        : %s\n",
    WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "ไม่ได้เชื่อมต่อ");
  Serial.printf( "│ quality     : %s (%s)\n", qualityStr(d.quality), d.reason);
  Serial.println("└────────────────────────────────┘");

  if (!d.valid) {
    Serial.printf(">> [SENSOR-ERROR] ค่าไม่น่าเชื่อถือ (%s) — ตรวจสอบสาย RS485/ไฟเลี้ยง/การจุ่ม probe\n", d.reason);
    return;
  }
  if (d.quality == 1) Serial.printf(">> [SUSPECT] %s — ค่าแปลกแต่ยังแสดงผล\n", d.reason);

  if      (d.moisture < 30) Serial.println(">> [แจ้งเตือน] ดินแห้ง — ควรรดน้ำ");
  else if (d.moisture > 80) Serial.println(">> [แจ้งเตือน] ดินชื้นเกินไป");
  else                      Serial.println(">> [OK] ความชื้นปกติ");
}

// ── Reconnect WiFi ────────────────────────────────────────
void checkWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi หลุด — กำลัง reconnect...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    uint8_t retry = 0;
    while (WiFi.status() != WL_CONNECTED && retry < 10) {
      delay(500);
      retry++;
    }
    if (WiFi.status() == WL_CONNECTED)
      Serial.printf("✅ Reconnect สำเร็จ! IP: %s\n", WiFi.localIP().toString().c_str());
  }
}

// ── RS485 DE/RE control ────────────────────────────────
void preTransmission()  { digitalWrite(DE_RE_PIN, HIGH); }
void postTransmission() { digitalWrite(DE_RE_PIN, LOW);  }

// ─────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== Agriscan + WiFi + WebServer ===");

  // เชื่อม WiFi
  WiFi.mode(WIFI_STA);
  connectWiFi();

  // ─── ตั้งชื่อ Local (mDNS) ───────────────────────────
  if (MDNS.begin("agriscan")) {
    Serial.println("✅ mDNS ทำงาน! สามารถเข้าผ่าน http://agriscan.local ได้");
  }

  // ─── ตั้ง Web Server ─────────────────────────────────
  server.on("/", HTTP_GET, []() {
    server.send(200, "text/html", dashboard_html);
  });
  server.on("/data", HTTP_GET,     handleData);
  server.on("/data", HTTP_OPTIONS, handleOptions);
  server.onNotFound([]() {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.send(404, "text/plain", "Not found");
  });
  server.begin();
  Serial.println("🌐 Web Server เริ่มต้นแล้ว");
  Serial.printf("📡 Dashboard IP: http://%s\n", WiFi.localIP().toString().c_str());
  Serial.println("📡 หรือเข้าผ่านชื่อ: http://agriscan.local\n");

  // เริ่ม RS485
  Serial2.begin(BAUD_RATE, SERIAL_8N1, RXD2, TXD2);
  pinMode(DE_RE_PIN, OUTPUT);
  digitalWrite(DE_RE_PIN, LOW);
  node.begin(MODBUS_ID, Serial2);
  node.preTransmission(preTransmission);
  node.postTransmission(postTransmission);
  delay(300);
  Serial.println("พร้อมอ่านค่าเซ็นเซอร์...\n");
}

void loop() {
  server.handleClient();   // ← ต้องเรียกทุก loop เพื่อรับ HTTP request

  checkWiFi();

  // อ่านค่า sensor ทุก 3 วินาที
  static unsigned long lastRead = 0;
  if (millis() - lastRead >= 3000) {
    lastRead = millis();

    SoilData d = readSensor();
    lastData = d;  // อัปเดตเสมอ — รวม valid=false เพื่อให้เว็บรู้ว่าเซ็นเซอร์เสีย (ไม่เงียบใช้ค่าเก่า)
    if (d.valid) {
      printSerial(d);
    } else {
      printSerial(d);
      Serial.printf("[ERROR] %s — แจ้งเว็บเป็น sensor-error\n", d.reason);
    }
    Serial.println();
  }

  // ส่งค่าจริงขึ้นคลาวด์ทุก POST_INTERVAL_MS (3 วินาที)
  static unsigned long lastUpload = 0;
  if (millis() - lastUpload >= POST_INTERVAL_MS) {
    lastUpload = millis();
    uploadReading();
  }
}
