/*
 * FIRMWARE ARDUINO - VERSION TF2 SABOTAGE
 * Ajout: Gestion du bouton "Sapper" physique
 */

#include <AccelStepper.h>

// --- PINOUT ---
#define X_STEP_PIN 2
#define X_DIR_PIN  5
#define Y_STEP_PIN 3
#define Y_DIR_PIN  6
#define EN_PIN     8 

#define PIN_RELAY_FIRE    12
#define PIN_VIBRO_AMMO    11
#define PIN_SENSOR_AMMO   A4

// NOUVEAU : Bouton Sabotage (Switch verrouillable)
// Connecté entre A2 et GND. 
// A2 est souvent libellé "Abort" ou "Hold" sur le CNC Shield.
#define PIN_SABOTAGE      A2 

#define PIN_VOLT_LOGIC    A5
#define PIN_VOLT_GEARBOX  A3

AccelStepper panMotor(AccelStepper::DRIVER, X_STEP_PIN, X_DIR_PIN);
AccelStepper tiltMotor(AccelStepper::DRIVER, Y_STEP_PIN, Y_DIR_PIN);

// Vitesses
const float MAX_SPEED_PAN = 800.0;
const float MAX_SPEED_TILT = 500.0;

// Variables
String inputString = "";
boolean stringComplete = false;
unsigned long lastCommandTime = 0;
unsigned long lastStatusSend = 0;
bool isFiring = false;
bool isSabotaged = false; // État du sabotage

void setup() {
  Serial.begin(115200);
  inputString.reserve(50);

  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW);

  pinMode(PIN_RELAY_FIRE, OUTPUT);
  digitalWrite(PIN_RELAY_FIRE, LOW);
  pinMode(PIN_VIBRO_AMMO, OUTPUT);
  digitalWrite(PIN_VIBRO_AMMO, LOW);

  pinMode(PIN_SENSOR_AMMO, INPUT);
  
  // Configuration du bouton Sabotage (Pullup interne)
  // Si le switch ferme le circuit vers GND -> LOW -> Sabotage ACTIF
  pinMode(PIN_SABOTAGE, INPUT_PULLUP);

  panMotor.setMaxSpeed(MAX_SPEED_PAN);
  panMotor.setAcceleration(400.0);
  tiltMotor.setMaxSpeed(MAX_SPEED_TILT);
  tiltMotor.setAcceleration(200.0);

  Serial.println("SYSTEM:ARDUINO_READY");
}

void loop() {
  // 1. VÉRIFICATION DU SABOTAGE (Priorité Absolue)
  // Lecture inverse car INPUT_PULLUP (LOW = Appuyé)
  bool sabotageState = !digitalRead(PIN_SABOTAGE); 

  if (sabotageState) {
    // --- MODE SABOTAGE ACTIF ---
    isSabotaged = true;
    isFiring = false;
    
    // a. Couper immédiatement le tir
    digitalWrite(PIN_RELAY_FIRE, LOW);
    digitalWrite(PIN_VIBRO_AMMO, LOW);
    
    // b. Simuler la "tête basse" (Désactivation)
    // On déplace le Tilt vers une position basse (ex: -2000 pas) lentement
    if (tiltMotor.currentPosition() > -100) { 
       tiltMotor.setSpeed(-200); // Descente lente
       tiltMotor.runSpeed();
    } else {
       tiltMotor.stop(); // Arrivé en bas
    }
    panMotor.stop(); // Pan figé

  } else {
    // --- MODE NORMAL ---
    isSabotaged = false;
    panMotor.runSpeed();
    tiltMotor.runSpeed();
  }

  // 2. Traitement des commandes (Seulement si PAS de sabotage)
  if (stringComplete) {
    if (!isSabotaged) {
        processCommand();
    } else {
        // Si on reçoit une commande pendant le sabotage, on l'ignore ou on répond erreur
        // (Optionnel)
    }
    inputString = "";
    stringComplete = false;
    lastCommandTime = millis();
  }

  // 3. Watchdog
  if (!isSabotaged && (millis() - lastCommandTime > 2000)) {
    stopAll();
  }

  // 4. Télémétrie (Inclut maintenant le statut Sabotage)
  if (millis() - lastStatusSend > 1000) {
    sendStatus();
    lastStatusSend = millis();
  }
}

void serialEvent() {
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    if (inChar == '\n') stringComplete = true;
    else inputString += inChar;
  }
}

void processCommand() {
  String cmd = inputString.substring(0, 1);
  String arg = inputString.substring(2);

  if (cmd == "P") {
    if (arg == "L") panMotor.setSpeed(-MAX_SPEED_PAN);
    else if (arg == "R") panMotor.setSpeed(MAX_SPEED_PAN);
    else if (arg == "S") panMotor.setSpeed(0);
  }
  else if (cmd == "T") {
    if (arg == "U") tiltMotor.setSpeed(MAX_SPEED_TILT);
    else if (arg == "D") tiltMotor.setSpeed(-MAX_SPEED_TILT);
    else if (arg == "S") tiltMotor.setSpeed(0);
  }
  else if (cmd == "F") {
    if (arg == "1") {
      isFiring = true;
      digitalWrite(PIN_RELAY_FIRE, HIGH);
      digitalWrite(PIN_VIBRO_AMMO, HIGH);
    } else {
      isFiring = false;
      digitalWrite(PIN_RELAY_FIRE, LOW);
      digitalWrite(PIN_VIBRO_AMMO, LOW);
    }
  }
}

void stopAll() {
  panMotor.setSpeed(0);
  tiltMotor.setSpeed(0);
  digitalWrite(PIN_RELAY_FIRE, LOW);
  digitalWrite(PIN_VIBRO_AMMO, LOW);
  isFiring = false;
}

void sendStatus() {
  float v1 = analogRead(PIN_VOLT_LOGIC) * (5.0 / 1023.0) * 3.0;
  float v2 = analogRead(PIN_VOLT_GEARBOX) * (5.0 / 1023.0) * 3.0;
  int ammo = digitalRead(PIN_SENSOR_AMMO);
  
  // Format: S|V1|V2|Ammo|SABOTAGE_STATE (0 ou 1)
  Serial.print("S|");
  Serial.print(v1); Serial.print("|");
  Serial.print(v2); Serial.print("|");
  Serial.print(ammo); Serial.print("|");
  Serial.println(isSabotaged ? 1 : 0);
}