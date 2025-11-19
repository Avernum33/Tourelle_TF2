# Fichier : controller_server.py (RPi Manette - Version Finale avec Audio)
import os
import signal
import RPi.GPIO as GPIO
import time
import requests
import threading
import subprocess
from flask import Flask, request, jsonify, send_file

# --- CONFIGURATION API & RÉSEAU ---
# TOURELLE_IP = "10.0.0.1"  <-- Mettre ça en commentaire pour l'instant
TOURELLE_IP = "192.168.1.116" # <-- Mets ici l'IP DE TON PC SIMULATEUR
TOURELLE_API_URL = f"http://{TOURELLE_IP}:5000" 
LOCAL_MANETTE_PORT = 5001 
app = Flask(__name__)

# --- CONFIGURATION AUDIO (ALERTE SABOTAGE) ---
SOUND_DIR = "/home/soren/sounds/"
ALARM_FILE = "sentry_sap.wav" # Nom du fichier alarme
NOTIFICATION_FILE = "tf_notification.wav"
alarm_process = None # Variable pour stocker le processus audio

# --- CONFIGURATION GPIO (Bouton FIRE) ---
PIN_FIRE_BUTTON = 17 
is_fire_button_pressed = False 
last_fire_state = True 

# --- INITIALISATION GPIO ---
def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN_FIRE_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    print("GPIO configuré. Surveillance du Bouton FIRE (Pin 17).")

# --- GESTION AUDIO LOCALE (MANETTE) ---
def manage_local_alarm(should_ring):
    """ Active ou désactive l'alarme locale en boucle """
    global alarm_process
    
    full_path = os.path.join(SOUND_DIR, ALARM_FILE)

    if should_ring:
        # Si on doit sonner et que ça ne sonne pas déjà
        if alarm_process is None:
            print("ALERTE SABOTAGE : Démarrage de l'alarme manette !")
            # On lance une boucle infinie en shell
            cmd = f"while true; do aplay -q {full_path}; done"
            # preexec_fn=os.setsid permet de créer un groupe de processus pour tout tuer d'un coup
            try:
                alarm_process = subprocess.Popen(cmd, shell=True, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
            except Exception as e:
                print(f"Erreur lancement audio: {e}")
    else:
        # Si on ne doit pas sonner, mais que ça sonne encore
        if alarm_process is not None:
            print("FIN ALERTE : Arrêt de l'alarme.")
            try:
                # On tue le groupe de processus (le while ET le aplay)
                os.killpg(os.getpgid(alarm_process.pid), signal.SIGTERM)
            except Exception as e:
                print(f"Erreur arrêt audio: {e}")
            alarm_process = None

# --- FONCTION D'ENVOI DE COMMANDES À LA TOURELLE ---
def send_command_to_tourelle(action):
    endpoint = f"{TOURELLE_API_URL}/command"
    try:
        response = requests.post(endpoint, json={'action': action}, timeout=0.5)
        response_json = response.json()
        response_json['status_code'] = response.status_code
        return response_json
    except requests.exceptions.RequestException as e:
        print(f"Erreur connexion tourelle: {e}")
        return {"status": "error", "message": "Tourelle non joignable.", "status_code": 503}

# --- SURVEILLANCE DU BOUTON FIRE PHYSIQUE ---
def monitor_fire_button():
    global last_fire_state, is_fire_button_pressed
    while True:
        current_state = GPIO.input(PIN_FIRE_BUTTON)
        
        # Front descendant (Presse)
        if current_state == False and last_fire_state == True:
            send_command_to_tourelle("FIRE_START")
            is_fire_button_pressed = True
            
        # Front montant (Relâche)
        elif current_state == True and last_fire_state == False:
            send_command_to_tourelle("FIRE_STOP")
            is_fire_button_pressed = False

        last_fire_state = current_state
        time.sleep(0.05)

# --- ENDPOINTS API FLASK ---

@app.route('/')
def serve_interface():
    try:
        return send_file('control_interface.html', mimetype='text/html') 
    except FileNotFoundError:
        return "Erreur: Fichier control_interface.html non trouvé.", 500

@app.route('/api/command', methods=['POST'])
def handle_browser_command():
    data = request.get_json()
    action = data.get('action', 'UNKNOWN')
    
    if action == "UNKNOWN":
        return jsonify({"status": "error", "message": "Action inconnue."}), 400
    
    tourelle_response = send_command_to_tourelle(action)
    return jsonify(tourelle_response), tourelle_response.get("status_code", 200)

@app.route('/api/status/tourelle', methods=['GET'])
def get_tourelle_status():
    """ Relaye le statut ET gère l'alarme locale """
    status_endpoint = f"{TOURELLE_API_URL}/status"
    try:
        # 1. On interroge la tourelle
        response = requests.get(status_endpoint, timeout=1.0)
        data = response.json()
        
        # 2. VÉRIFICATION CRITIQUE : Est-ce qu'on est saboté ?
        # La tourelle renvoie {"sabotaged": true/false}
        is_sabotaged = data.get('sabotaged', False)
        
        # 3. Gestion du son local
        manage_local_alarm(is_sabotaged)
        
        # 4. On renvoie les données à l'interface web
        return jsonify(data), response.status_code

    except requests.exceptions.RequestException:
        # En cas de perte de connexion, on coupe l'alarme par sécurité
        manage_local_alarm(False)
        
        return jsonify({
            "voltage": 0.0,
            "ammo_status": "OFFLINE",
            "message": "La tourelle est injoignable."
        }), 503

@app.route('/api/kiosk_kill', methods=['POST'])
def kill_kiosque():
    print("Arrêt du mode Kiosque demandé.")
    # Coupe l'alarme si elle sonne avant de quitter
    manage_local_alarm(False) 
    os.system("pkill firefox") 
    return jsonify({"status": "ok", "message": "Kiosque arrêté."}), 200

@app.route('/api/play_notification', methods=['POST'])
def play_notification():
    """ Joue un son de notification court (sans bloquer) """
    full_path = os.path.join(SOUND_DIR, NOTIFICATION_FILE)
    try:
        # On lance aplay en tâche de fond et on laisse faire
        subprocess.Popen(["aplay", "-q", full_path], stderr=subprocess.DEVNULL)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Erreur son notification: {e}")
        return jsonify({"status": "error"}), 500

# ... (Le début du code reste identique) ...

# --- NOUVEAU : THREAD DE SURVEILLANCE SABOTAGE ---
def monitor_sabotage_loop():
    print("--- DÉBUT SURVEILLANCE SABOTAGE ---")
    while True:
        try:
            endpoint = f"{TOURELLE_API_URL}/status"
            # On ajoute un timeout court pour ne pas bloquer
            response = requests.get(endpoint, timeout=2.0)
            
            if response.status_code == 200:
                data = response.json()
                is_sabotaged = data.get('sabotaged', False)
                
                # DEBUG : Affiche ce qu'on reçoit
                # print(f"Reçu de la tourelle : {is_sabotaged}") 
                
                if is_sabotaged:
                    print("!!! SABOTAGE DÉTECTÉ -> SONNERIE !!!")
                    manage_local_alarm(True)
                else:
                    manage_local_alarm(False)
            else:
                print(f"Erreur API: Code {response.status_code}")
                manage_local_alarm(False)
                
        except Exception as e:
            print(f"Erreur connexion: {e}")
            manage_local_alarm(False)
            
        time.sleep(1.0)

# --- DÉMARRAGE ---
if __name__ == '__main__':
    try:
        setup_gpio()
        
        # Thread Bouton Fire
        gpio_thread = threading.Thread(target=monitor_fire_button)
        gpio_thread.daemon = True 
        gpio_thread.start()
        
        # NOUVEAU : Thread Surveillance Sabotage
        sabotage_thread = threading.Thread(target=monitor_sabotage_loop)
        sabotage_thread.daemon = True
        sabotage_thread.start()
        
        print(f"Serveur Manette démarré sur le port {LOCAL_MANETTE_PORT}...")
        if not os.path.exists(SOUND_DIR):
            print(f"ATTENTION : Le dossier {SOUND_DIR} n'existe pas !")

        app.run(host='0.0.0.0', port=LOCAL_MANETTE_PORT, debug=False)
    except Exception as e:
        print(f"Erreur fatale : {e}")
    finally:
        manage_local_alarm(False)
        GPIO.cleanup()
