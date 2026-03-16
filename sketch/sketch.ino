#include <Arduino.h>
#include <DHT.h>
#include <avr/sleep.h>

#define FAN1_PIN 2
#define FAN2_PIN 3
#define LED_PIN  5
#define DHT_PIN  4
#define DHTTYPE  DHT11

#define IDLE_TIMEOUT    600000UL   // 10 mins no serial → slow mode
#define DHT_FAST        2000UL     // 2 sec normal read interval
#define DHT_SLOW        300000UL   // 5 min slow read interval

DHT dht(DHT_PIN, DHTTYPE);

bool fan1 = false, fan2 = false;
bool dangerShutdown = false;
bool ledEnabled = true;
float temp = 0, hum = 0;
unsigned long dhtTimer = 0;
unsigned long lastSerialTime = 0;

float warnTemp   = 35.0;
float dangerTemp = 50.0;

enum LEDMode { STATIC_ON, BREATHE_SLOW, BREATHE_FAST, STATIC_OFF };
LEDMode ledMode = STATIC_ON;

void setFans(bool f1, bool f2) {
  fan1 = f1; fan2 = f2;
  digitalWrite(FAN1_PIN, f1 ? HIGH : LOW);
  digitalWrite(FAN2_PIN, f2 ? HIGH : LOW);
  if (!ledEnabled) return;
  if (!f1 && !f2)    ledMode = STATIC_ON;
  else if (f1 && f2) ledMode = BREATHE_FAST;
  else               ledMode = BREATHE_SLOW;
}

void updateLED() {
  if (!ledEnabled) { analogWrite(LED_PIN, 0); return; }
  if (ledMode == STATIC_ON)        analogWrite(LED_PIN, 255);
  else if (ledMode == STATIC_OFF)  analogWrite(LED_PIN, 0);
  else if (ledMode == BREATHE_SLOW) {
    float v = (exp(sin(millis() / 2000.0 * PI)) - 0.36787944) * 108.0;
    analogWrite(LED_PIN, (int)v);
  } else if (ledMode == BREATHE_FAST) {
    float v = (exp(sin(millis() / 250.0 * PI)) - 0.36787944) * 108.0;
    analogWrite(LED_PIN, (int)v);
  }
}

void checkTemp() {
  unsigned long interval = (millis() - lastSerialTime > IDLE_TIMEOUT) ? DHT_SLOW : DHT_FAST;
  if (millis() - dhtTimer < interval) return;
  dhtTimer = millis();
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (!isnan(t)) temp = t;
  if (!isnan(h)) hum  = h;
  if (temp >= dangerTemp && !dangerShutdown) {
    dangerShutdown = true;
    setFans(false, false);
    ledMode = STATIC_OFF;
  }
}

void goIdle() {
  set_sleep_mode(SLEEP_MODE_IDLE);
  sleep_enable();
  sleep_mode();
  sleep_disable();
}

void sendStatus() {
  Serial.print("{\"t\":"); Serial.print(temp, 1);
  Serial.print(",\"h\":"); Serial.print(hum, 1);
  Serial.print(",\"f1\":"); Serial.print(fan1 ? 1 : 0);
  Serial.print(",\"f2\":"); Serial.print(fan2 ? 1 : 0);
  Serial.print(",\"danger\":"); Serial.print(dangerShutdown ? 1 : 0);
  Serial.print(",\"led\":"); Serial.print(ledEnabled ? 1 : 0);
  Serial.println("}");
}

void setup() {
  Serial.begin(9600);
  pinMode(FAN1_PIN, OUTPUT);
  pinMode(FAN2_PIN, OUTPUT);
  pinMode(LED_PIN,  OUTPUT);
  dht.begin();
  setFans(false, false);
}

void loop() {
  checkTemp();
  updateLED();
  if (Serial.available()) {
    lastSerialTime = millis();
    char cmd = Serial.read();
    if (dangerShutdown && cmd != 'r') return;
    switch(cmd) {
      case '1': setFans(true,  fan2); break;
      case '2': setFans(false, fan2); break;
      case '3': setFans(fan1,  true); break;
      case '4': setFans(fan1, false); break;
      case '5': setFans(true,  true); break;
      case '0': setFans(false, false); break;
      case 'l':
        ledEnabled = !ledEnabled;
        if (!ledEnabled) analogWrite(LED_PIN, 0);
        else setFans(fan1, fan2);
        break;
      case 'r': dangerShutdown = false; setFans(false, false); break;
      case 's': sendStatus(); break;
    }
  } else {
    goIdle();
  }
}
