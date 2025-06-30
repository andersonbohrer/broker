import logging, json, threading, time, tkinter as tk
from tkinter import ttk
import paho.mqtt.client as mqtt

BROKER, PORT = "3e533850c6644a06ac4bf2bfe62a37f3.s1.eu.hivemq.cloud", 8883
MQTT_USERNAME = "abohrer"  # Seu usuário do HiveMQ
MQTT_PASSWORD = "SENHA"  # << IMPORTANTE: Substitua pela sua senha
TEMP_TOPIC   = "esp32/temperatura"

DEVICES = {               # nome → tópico base (Tasmota “Topic”)
    "esp32":  "esp32",
    "sonoff1": "sonoff1",
}

logging.basicConfig(level=logging.INFO)

class MqttGui:
    def __init__(self, root):
        self.root = root
        self.root.title("Monitor MQTT")

        # ---------- GUI ----------
        main = ttk.Frame(root, padding=20); main.grid()

        ttk.Label(main, text="Temperatura (°C)", font=("Segoe UI", 12))\
            .grid(row=0, column=0, columnspan=3)
        self.temp_var = tk.StringVar(value="----")
        ttk.Label(main, textvariable=self.temp_var, font=("Segoe UI", 32))\
            .grid(row=1, column=0, columnspan=3, pady=10)

        box = ttk.LabelFrame(main, text="Dispositivos")
        box.grid(row=2, column=0, columnspan=3, pady=10, sticky="ew")

        self.selected_device = tk.StringVar(value=next(iter(DEVICES)))
        self.status_labels = {}
        for r, name in enumerate(DEVICES):
            ttk.Radiobutton(box, text=name, variable=self.selected_device,
                            value=name).grid(row=r, column=0, sticky="w")
            lbl = tk.Label(box, width=20, height=1, bg="grey")
            lbl.grid(row=r, column=1, padx=10, pady=2, sticky="w")
            self.status_labels[name] = lbl

        ttk.Button(main, text="ON",  width=10,
                   command=lambda: self.publish("ON"))\
            .grid(row=3, column=0, pady=5)
        ttk.Button(main, text="OFF", width=10,
                   command=lambda: self.publish("OFF"))\
            .grid(row=3, column=1, pady=5)

        self.status_var = tk.StringVar(value="Desconectado")
        ttk.Label(main, textvariable=self.status_var)\
            .grid(row=4, column=0, columnspan=3, pady=(10,0))

        # ---------- MQTT ----------
        self.client = mqtt.Client()
        self.client.enable_logger()
        self.client.on_connect    = self.on_connect
        self.client.on_message    = self.on_message
        self.client.on_disconnect = lambda *_: self._set_status("Desconectado")

        threading.Thread(target=self._mqtt_loop, daemon=True).start()

    # ---------- MQTT callbacks ----------
    def on_connect(self, client, *_):
        self._set_status("Conectado")
        client.subscribe(TEMP_TOPIC)
        for t in DEVICES.values():
            client.subscribe(f"stat/{t}/#")
            client.subscribe(f"tele/{t}/#")   # <- novo
            client.publish(f"cmnd/{t}/state", "") # Request current state on connect

    def on_message(self, client, userdata, msg):
        tpc = msg.topic
        raw = msg.payload.decode(errors="ignore").strip()

        # temperatura
        if tpc == TEMP_TOPIC:
            self.root.after(0, self.temp_var.set, raw)
            try:
                temp_value = float(raw)
                if "sonoff1" in DEVICES:
                    target_topic = f"cmnd/{DEVICES['sonoff1']}/POWER1"
                    # It's better to check the actual device state if possible,
                    # but for simplicity, we'll rely on the GUI label state.
                    # This might lead to redundant commands if the GUI state is not perfectly in sync.
                    current_power_state_label = self.status_labels.get("sonoff1")
                    current_power_state = None
                    if current_power_state_label:
                        bg_color = current_power_state_label.cget("bg")
                        if bg_color == "green":
                            current_power_state = "ON"
                        elif bg_color == "red":
                            current_power_state = "OFF"

                    if temp_value < 10:
                        if current_power_state != "ON":
                            logging.info(f"Temperatura {temp_value}°C < 10°C. Ligando POWER1.")
                            self.client.publish(target_topic, "ON")
                        # else:
                        #     logging.info(f"Temperatura {temp_value}°C < 10°C, POWER1 já está ON.")
                    elif temp_value > 15:
                        if current_power_state != "OFF":
                            logging.info(f"Temperatura {temp_value}°C > 15°C. Desligando POWER1.")
                            self.client.publish(target_topic, "OFF")
                        # else:
                        #     logging.info(f"Temperatura {temp_value}°C > 15°C, POWER1 já está OFF.")
                else:
                    logging.warning("Dispositivo 'sonoff1' não encontrado no mapeamento DEVICES.")
            except ValueError:
                logging.warning(f"Valor de temperatura inválido recebido: {raw}")
            except Exception as e:
                logging.error(f"Erro ao processar atualização de temperatura: {e}")
            return # Important: return after processing temperature

        # filtra stat/… ou tele/… (para outros dispositivos)
        parts = tpc.split("/")
        if len(parts) < 3 or parts[0] not in ("stat", "tele"):
            return
        dev_name_from_topic = parts[1]

        # Encontra o nome do dispositivo em DEVICES que corresponde ao tópico base
        device_key = None
        for key, topic_base in DEVICES.items():
            if topic_base == dev_name_from_topic:
                device_key = key
                break

        if not device_key:
            # logging.debug(f"Tópico recebido para dispositivo não mapeado em DEVICES: {dev_name_from_topic}")
            return

        # tenta achar estado ON/OFF para o dispositivo
        state = None
        if raw.upper() in ("ON", "OFF"): # Direct ON/OFF state
            state = raw.upper()
        else: # Check for JSON payload like Tasmota's STATE or RESULT
            try:
                j = json.loads(raw)
                # Tasmota sends status in messages like:
                # tele/sonoff1/STATE = {"Time":"...","POWER1":"ON",...}
                # stat/sonoff1/RESULT = {"POWER1":"ON"}
                # stat/sonoff1/POWER1 = ON (older versions or specific commands)
                for k_json in ("POWER1", "POWER"): # Check common keys for power state
                    if k_json in j:
                        state = j[k_json].upper()
                        break
            except json.JSONDecodeError:
                # Not a JSON, or not the JSON we expect
                pass
            except Exception as e:
                logging.error(f"Erro ao decodificar JSON de {device_key}: {raw} - {e}")


        if state in ("ON", "OFF") and device_key in self.status_labels:
            colour = "green" if state == "ON" else "red"
            # Update GUI from the main thread
            self.root.after(0, self.status_labels[device_key].config, {"bg": colour})
            # Log state change
            # logging.info(f"Estado de {device_key} ({dev_name_from_topic}) atualizado para: {state}")


    # ---------- helpers ----------
    def publish(self, payload):
        dev_key = self.selected_device.get() # This is the key from DEVICES like "sonoff1"
        if dev_key in DEVICES:
            topic_base = DEVICES[dev_key] # This is the topic part like "sonoff1"
            # Always target POWER1 for ON/OFF buttons as per typical Tasmota setup for single-relay devices
            topic = f"cmnd/{topic_base}/POWER1"
            try:
                logging.info(f"Publicando '{payload}' para '{topic}'")
                self.client.publish(topic, payload)
            except Exception as e:
                self._set_status(f"Falha ao publicar: {e}")
        else:
            logging.error(f"Dispositivo selecionado '{dev_key}' não encontrado em DEVICES.")


    def _mqtt_loop(self):
        while True:
            try:
                self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
                self.client.connect(BROKER, PORT, 60)
                self.client.loop_forever()
            except Exception as e:
                self._set_status(f"Erro: {e} – reconectando em 5 s")
                time.sleep(5)

    def _set_status(self, txt):
        logging.info(f"Status MQTT: {txt}")
        self.root.after(0, self.status_var.set, txt)

# ---------- run ----------
if __name__ == "__main__":
    root = tk.Tk()
    root.tk_setPalette(background="#f0f0f0")
    app = MqttGui(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logging.info("Aplicação encerrada pelo usuário.")
    finally:
        if hasattr(app, 'client') and app.client.is_connected():
            logging.info("Desconectando cliente MQTT...")
            app.client.disconnect()
            # Allow some time for disconnect to complete
            # Note: loop_stop() might be needed if not using loop_forever in a thread that is gracefully shut down.
            # However, since loop_forever is used, disconnect() should be enough.
        logging.info("Programa finalizado.")
