
#include <Wire.h>

const uint8_t AS5600_ADDRESS = 0x36;
const uint8_t RAW_ANGLE_REGISTER = 0x0C;

const uint8_t BUTTON_1_PIN = A0;
const uint8_t BUTTON_2_PIN = A1;

// 450 degrees each side = 900 degrees total.
const long MAX_COUNTS_FROM_CENTER = 5120;
const float SMOOTHING_ALPHA = 0.25f;

uint16_t previousRawAngle = 0;
long unwrappedCounts = 0;
float filteredCounts = 0.0f;

bool readRawAngle(uint16_t &angle) {
  Wire.beginTransmission(AS5600_ADDRESS);
  Wire.write(RAW_ANGLE_REGISTER);

  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(AS5600_ADDRESS, (uint8_t)2) != 2) return false;

  uint8_t highByte = Wire.read();
  uint8_t lowByte = Wire.read();
  angle = (((uint16_t)highByte << 8) | lowByte) & 0x0FFF;
  return true;
}

void setup() {
  Wire.begin();
  Serial.begin(9600);

  pinMode(BUTTON_1_PIN, INPUT_PULLUP);
  pinMode(BUTTON_2_PIN, INPUT_PULLUP);

  // Keep the wheel centered while the Arduino starts.
  while (!readRawAngle(previousRawAngle)) {
    delay(500);
  }
}

void loop() {
  uint16_t rawAngle;
  if (!readRawAngle(rawAngle)) {
    delay(10);
    return;
  }

  // Track movement across the AS5600's 0/4095 wrap point.
  int delta = (int)rawAngle - (int)previousRawAngle;
  if (delta > 2047) {
    delta -= 4096;
  } else if (delta < -2048) {
    delta += 4096;
  }

  // Keep this accumulated value unclamped so overtravel is remembered.
  unwrappedCounts += delta;
  previousRawAngle = rawAngle;

  // Clamp only the controller output.
  long targetCounts = constrain(
    unwrappedCounts,
    -MAX_COUNTS_FROM_CENTER,
     MAX_COUNTS_FROM_CENTER
  );

  filteredCounts +=
    (targetCounts - filteredCounts) * SMOOTHING_ALPHA;

  float degreesFloat = filteredCounts * 360.0f / 4096.0f;
  long steeringDegrees = (long)(
    degreesFloat >= 0
      ? degreesFloat + 0.5f
      : degreesFloat - 0.5f
  );

  steeringDegrees = constrain(steeringDegrees, -450, 450);

  int button1 = (digitalRead(BUTTON_1_PIN) == LOW) ? 1 : 0;
  int button2 = (digitalRead(BUTTON_2_PIN) == LOW) ? 1 : 0;

  if (steeringDegrees > 0) Serial.print('+');
  Serial.print(steeringDegrees);
  Serial.print(',');
  Serial.print(button1);
  Serial.print(',');
  Serial.println(button2);

  delay(10);
}
