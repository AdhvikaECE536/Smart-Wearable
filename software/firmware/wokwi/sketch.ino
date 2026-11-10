// SOS wearable firmware: ESP32-S3. One file, two transports.
//   USE_WOKWI_WIFI 1 -> publishes over Wi-Fi (Wokwi simulation, PubSubClient over TCP)
//   USE_WOKWI_WIFI 0 -> publishes through SIMCom A7670C AT commands (real hardware; bring-up in Jan)
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <PubSubClient.h>
#include <esp_sleep.h>
#include <driver/rtc_io.h>

#define USE_WOKWI_WIFI   1
#define USE_DEEP_SLEEP   0      // 1 on hardware (GPIO4 wakes the chip). 0 = poll the button (safest in Wokwi)
#define SIM_FAKE_APS     1      // Wokwi only sees "Wokwi-GUEST"; pad the scan with the table below

#define SOS_PIN          4
#define DEVICE_ID        "w01-k7f3"
#define SEND_PERIOD_MS   10000UL
#define SOS_DURATION_MS  300000UL

const char* MQTT_HOST = "broker.emqx.io";
const int   MQTT_PORT = 1883;       // Standard plain TCP port for public testing
const char* MQTT_USER = "";
const char* MQTT_PASS = "";
String TOPIC = String("sos/") + DEVICE_ID + "/uplink";

// ---- Wi-Fi scan -> 21 byte payload: 3 x [6-byte BSSID][1 byte = -RSSI] ----
struct AP { uint8_t mac[6]; int rssi; };

#if SIM_FAKE_APS
const AP FAKE[3] = { {{0x02,0x00,0x00,0x00,0x06,0x1f}, -48}, {{0x02,0x00,0x00,0x00,0x05,0x72}, -61}, {{0x02,0x00,0x00,0x00,0x07,0x71}, -72} };
#endif
uint32_t g_lastScanMs = 0;
int scanTop3(AP out[3]) {
  uint32_t t0 = millis();
  int n = WiFi.scanNetworks(false, false, false, 40);
  int got = 0; bool used[64] = {false};
  for (; got < 3; got++) {
    int best = -1;
    for (int i = 0; i < n && i < 64; i++)
      if (!used[i] && (best < 0 || WiFi.RSSI(i) > WiFi.RSSI(best))) best = i;
    if (best < 0) break;
    used[best] = true;
    memcpy(out[got].mac, WiFi.BSSID(best), 6);
    int r = WiFi.RSSI(best);
    if (r > -1 || r < -100) r = -55;
    out[got].rssi = r;
  }
  WiFi.scanDelete();
#if SIM_FAKE_APS
    for (int i = 0; i < 3; i++) out[i] = FAKE[i];
  got = 3;
#endif
g_lastScanMs = millis() - t0;
  Serial.printf("scan: %d APs in %lu ms\n", got, millis() - t0);
  return got;
}

String buildPayloadHex() {
  AP ap[3]; memset(ap, 0, sizeof(ap));
  int n = scanTop3(ap);
  uint8_t buf[21] = {0};
  for (int i = 0; i < n; i++) {
    memcpy(&buf[i * 7], ap[i].mac, 6);
    buf[i * 7 + 6] = (uint8_t)min(255, -ap[i].rssi);
  }
  char hex[43];
  for (int i = 0; i < 21; i++) sprintf(&hex[i * 2], "%02x", buf[i]);
  hex[42] = 0;
  return String(hex);
}

// ---------------- transport ----------------
#if USE_WOKWI_WIFI
WiFiClient espClient;
PubSubClient mqtt(espClient);

bool transportUp() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.mode(WIFI_STA);
    WiFi.begin("Wokwi-GUEST", "", 6);
    uint32_t t = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t < 15000) delay(200);
    if (WiFi.status() != WL_CONNECTED) { Serial.println("wifi: FAILED"); return false; }
    Serial.println("wifi: connected");
  }
  
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  
  if (!mqtt.connected()) {
    // Unique client ID added here to prevent broker collision state=5
    bool ok = mqtt.connect("w01-k7f3-dev", MQTT_USER, MQTT_PASS);
    Serial.printf("mqtt: %s state=%d\n", ok ? "connected" : "FAILED", mqtt.state());
  }
  return mqtt.connected();
}

bool transportSend(const String& hex) { return mqtt.publish(TOPIC.c_str(), hex.c_str()); }

#else  // ---------- SIMCom A7670C over UART ----------
#define MODEM_TX 17
#define MODEM_RX 18
const char* APN = "internet";
bool modemReady = false, mqttReady = false;

bool waitFor(const char* s, uint32_t to) {
  String b; uint32_t t = millis();
  while (millis() - t < to) {
    while (Serial1.available()) b += (char)Serial1.read();
    if (b.indexOf(s) >= 0) return true;
    if (b.indexOf("ERROR") >= 0) return false;
    delay(5);
  }
  return false;
}
bool at(const String& c, const char* ok = "OK", uint32_t to = 2000) {
  while (Serial1.available()) Serial1.read();
  Serial1.println(c);
  return waitFor(ok, to);
}
bool transportUp() {
  if (!modemReady) {
    Serial1.begin(115200, SERIAL_8N1, MODEM_RX, MODEM_TX);
    bool ok = false;
    for (int i = 0; i < 10 && !ok; i++) ok = at("AT");
    if (!ok) return false;
    at("ATE0");
    at("AT+CGATT=1", "OK", 20000);
    at(String("AT+CGDCONT=1,\"IP\",\"") + APN + "\"");
    bool reg = false;
    for (int i = 0; i < 30 && !reg; i++) { reg = at("AT+CEREG?", "+CEREG: 0,1", 1000) || at("AT+CEREG?", "+CEREG: 0,5", 1000); delay(1000); }
    if (!reg) return false;
    modemReady = true;
  }
  if (!mqttReady) {
    at("AT+CMQTTSTOP", "OK", 3000);
    if (!at("AT+CMQTTSTART", "+CMQTTSTART: 0", 12000)) return false;
    if (!at(String("AT+CMQTTACCQ=0,\"") + DEVICE_ID + "\",1")) return false;
    at("AT+CSSLCFG=\"sslversion\",0,4");
    at("AT+CSSLCFG=\"authmode\",0,0");
    at("AT+CSSLCFG=\"enableSNI\",0,1");
    at("AT+CSSLCFG=\"ignorelocaltime\",0,1");
    at("AT+CMQTTSSLCFG=0,0");
    String c = String("AT+CMQTTCONNECT=0,\"tcp://") + MQTT_HOST + ":" + MQTT_PORT + "\",60,1,\"" + MQTT_USER + "\",\"" + MQTT_PASS + "\"";
    if (!at(c, "+CMQTTCONNECT: 0,0", 20000)) return false;
    mqttReady = true;
  }
  return true;
}
bool transportSend(const String& hex) {
  if (!at("AT+CMQTTTOPIC=0," + String(TOPIC.length()), ">", 2000)) { mqttReady = false; return false; }
  Serial1.print(TOPIC); if (!waitFor("OK", 2000)) return false;
  if (!at("AT+CMQTTPAYLOAD=0," + String(hex.length()), ">", 2000)) return false;
  Serial1.print(hex); if (!waitFor("OK", 2000)) return false;
  bool ok = at("AT+CMQTTPUB=0,1,60", "+CMQTTPUB: 0,0", 15000);
  if (!ok) mqttReady = false;
  return ok;
}
#endif

// ---------------- SOS session ----------------
void runSOS() {
  Serial.println("SOS triggered");
  uint32_t start = millis();
  while (millis() - start < SOS_DURATION_MS) {
    String hex = buildPayloadHex();
    bool up = transportUp();
    bool sent = up && transportSend(hex);
    uint32_t sentAt = millis();
    Serial.printf("t=%lus payload=%s up=%d sent=%d\n", (sentAt - start) / 1000, hex.c_str(), up, sent);
    uint32_t due = sentAt + SEND_PERIOD_MS - g_lastScanMs;   // start the next scan early, so packets leave 10 s apart
    while ((int32_t)(millis() - due) < 0) delay(20);
  }
}
void armAndSleep() {
#if USE_DEEP_SLEEP
  while (digitalRead(SOS_PIN) == LOW) delay(10);
  rtc_gpio_pullup_en((gpio_num_t)SOS_PIN);
  rtc_gpio_pulldown_dis((gpio_num_t)SOS_PIN);
  esp_sleep_enable_ext0_wakeup((gpio_num_t)SOS_PIN, 0);
  Serial.println("armed, sleeping");
  Serial.flush();
  esp_deep_sleep_start();
#endif
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(SOS_PIN, INPUT_PULLUP);
  WiFi.mode(WIFI_STA);
#if !USE_WOKWI_WIFI
  WiFi.disconnect();
#endif
  bool wokeByButton = esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0;
  Serial.println(wokeByButton ? "woke from button" : "boot: armed, press SOS (GPIO4)");
  if (wokeByButton) { runSOS(); armAndSleep(); }
  else armAndSleep();
}

void loop() {
  if (digitalRead(SOS_PIN) == LOW) {
    delay(40);
    if (digitalRead(SOS_PIN) == LOW) { runSOS(); while (digitalRead(SOS_PIN) == LOW) delay(10); }
  }
  delay(10);
}
