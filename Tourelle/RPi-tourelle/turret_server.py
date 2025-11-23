# Fichier : turret_server.py (RPi Tourelle - Mise à jour Audio & Sabotage)
import os
import time
import serial
import threading
import subprocess
from flask import Flask, request, jsonify

# --- CONFIGURATION ---
SERIAL_PORT = '/dev/ttyACM0' 
BAUD_RATE = 115200
MOCK_MODE = False 

# Chemins des sons
AUDIO_PATH = "./sounds/"
S_BUILDUP = "sentry_buildup.wav" # 10s
S_IDLE    = "sentry_idle.wav"    # 3s
S_SAP     = "sentry_sap.wav"     # 12s (Boucle)
S_SPOT    = "sentry_spot.wav"    # <1s (Une fois)
S_TAUNT   = "tf_domination.wav"  # Meilleurs Amis ! (Une fois par pression)

app = Flask(__name__)

# --- GESTION AUDIO AVANCÉE ---
class AudioManager:
    def __init__(self):
        self.sap_process = None
        self.last_idle_time = time.time()
        
        # Jouer le son de construction au démarrage du script
        self.play_one_shot(S_BUILDUP)

    def play_taunt(self):
        """ Joue le son de troll """
        self.play_one_shot(S_TAUNT)

    def play_one_shot(self, filename):
        """ Feu et oublie """
        subprocess.Popen(["aplay", "-q", os.path.join(AUDIO_PATH, filename)], stderr=subprocess.DEVNULL)

    def play_spot_sound(self):
        """ Son de détection avant tir """
        self.play_one_shot(S_SPOT)

    def manage_idle(self, is_sabotaged, is_active):
        """ Gestion du bip toutes les 10s """
        # Pas de bip si saboté ou en train de tirer/bouger
        if is_sabotaged or is_active:
            self.last_idle_time = time.time() # Reset le timer pour ne pas bipper dès l'arrêt
            return

        # Si écoulé > 10s
        if time.time() - self.last_idle_time > 10.0:
            self.play_one_shot(S_IDLE)
            self.last_idle_time = time.time()

    def set_sabotage_loop(self, active):
        """ Gère la boucle sonore de l'alarme """
        if active:
            if self.sap_process is None:
                # On lance le son en boucle infinie (ou on laisse le fichier de 12s se finir et on relance)
                # Ici on relance le fichier wav via une boucle while en shell pour faire simple
                cmd = f"while true; do aplay -q {os.path.join(AUDIO_PATH, S_SAP)}; done"
                self.sap_process = subprocess.Popen(cmd, shell=True, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
        else:
            if self.sap_process:
                # Tuer le processus et le groupe de processus (le while et le aplay)
                try:
                    os.killpg(os.getpgid(self.sap_process.pid), 15) # SIGTERM
                except:
                    pass
                self.sap_process = None

audio = AudioManager()

# --- CONTROLEUR ---
class TurretController:
    def __init__(self):
        self.ser = None
        self.voltage_gearbox = 0.0
        self.ammo_ok = 1
        self.sabotage_active = False
        self.is_firing = False
        self.lock = threading.Lock()
        self.connect()

    def connect(self):
        if MOCK_MODE: return
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2)
        except Exception as e:
            print(f"Erreur Série: {e}")

    def send_command(self, cmd):
        # Sécurité : On interdit l'envoi de commande si SABOTAGE actif
        if self.sabotage_active:
            print("COMMANDE BLOQUÉE : TOURELLE SABOTÉE")
            return

        if self.ser and self.ser.is_open:
            with self.lock:
                self.ser.write(f"{cmd}\n".encode('utf-8'))

    def read_status(self):
        if MOCK_MODE: return
        if self.ser and self.ser.in_waiting > 0:
            with self.lock:
                try:
                    line = self.ser.readline().decode('utf-8').strip()
                    if line.startswith("S|"):
                        parts = line.split("|")
                        # Format attendu: S|V1|V2|Ammo|Sabotage
                        if len(parts) >= 5:
                            self.voltage_gearbox = float(parts[2])
                            self.ammo_ok = int(parts[3])
                            self.sabotage_active = (int(parts[4]) == 1)
                except Exception:
                    pass

turret = TurretController()

# --- TÂCHE DE FOND ---
def background_task():
    while True:
        turret.read_status()
        
        # Gestion Audio "Sapping" (Prioritaire)
        audio.set_sabotage_loop(turret.sabotage_active)
        
        # Gestion Audio "Idle" (Si pas saboté)
        # On considère 'is_active' comme firing ou sabotage
        audio.manage_idle(turret.sabotage_active, turret.is_firing)
        
        # Keep Alive Arduino
        if not turret.sabotage_active:
            turret.send_command("K:0")
        
        time.sleep(0.1) # Rafraichissement rapide pour réactivité sabotage

# --- API ---
@app.route('/command', methods=['POST'])
def handle_command():
    # Si saboté, on rejette tout de suite
    if turret.sabotage_active:
        return jsonify({"status": "error", "message": "SABOTAGE EN COURS"}), 403

    data = request.get_json()
    action = data.get('action', 'UNKNOWN')

    if action == "FIRE_START":
        audio.play_spot_sound() # SON SPOT <1s
        turret.send_command("F:1")
        turret.is_firing = True
    elif action == "FIRE_STOP":
        turret.send_command("F:0")
        turret.is_firing = False
    # ... (Mouvements identiques au précédent code) ...
    elif action == "PAN_LEFT":   turret.send_command("P:L")
    elif action == "PAN_RIGHT": turret.send_command("P:R")
    elif action == "PAN_STOP":  turret.send_command("P:S")
    elif action == "TILT_UP":   turret.send_command("T:U")
    elif action == "TILT_DOWN": turret.send_command("T:D")
    elif action == "TILT_STOP": turret.send_command("T:S")
    elif action == "TAUNT":
        audio.play_one_shot(S_TAUNT)

    return jsonify({"status": "ok"}), 200

@app.route('/status', methods=['GET'])
def get_status():
    # L'interface Client devra lire 'sabotaged' pour jouer le son aussi de son côté !
    return jsonify({
        "voltage": turret.voltage_gearbox,
        "ammo_status": "OK" if turret.ammo_ok else "AMMO_LOW",
        "sabotaged": turret.sabotage_active
    }), 200

if __name__ == '__main__':
    t = threading.Thread(target=background_task)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=5000)