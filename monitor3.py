import logging, json, threading, time, tkinter as tk
from tkinter import ttk
import paho.mqtt.client as mqtt

BROKER, PORT = "3e533850c6644a06ac4bf2bfe62a37f3.s1.eu.hivemq.cloud", 8883
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
            client.publish(f"cmnd/{t}/state", "")

    def on_message(self, client, userdata, msg):
        tpc = msg.topic
        raw = msg.payload.decode(errors="ignore").strip()

        # temperatura
        if tpc == TEMP_TOPIC:
            self.root.after(0, self.temp_var.set, raw)
            return

        # filtra stat/… ou tele/…
        parts = tpc.split("/")
        if len(parts) < 3 or parts[0] not in ("stat", "tele"):
            return
        dev = parts[1]

        # tenta achar estado ON/OFF
        state = None
        if raw.upper() in ("ON", "OFF"):
            state = raw.upper()
        else:
            try:
                j = json.loads(raw)
                for k in ("POWER1", "POWER"):
                    if k in j:
                        state = j[k].upper(); break
            except json.JSONDecodeError:
                pass

        if state in ("ON", "OFF") and dev in self.status_labels:
            colour = "green" if state == "ON" else "red"
            self.root.after(0, self.status_labels[dev].config, {"bg": colour})

    # ---------- helpers ----------
    def publish(self, payload):
        dev = self.selected_device.get()
        topic = f"cmnd/{DEVICES[dev]}/POWER1"
        try:
            self.client.publish(topic, payload)
        except Exception as e:
            self._set_status(f"Falha: {e}")

    def _mqtt_loop(self):
        while True:
            try:
                self.client.connect(BROKER, PORT, 60)
                self.client.loop_forever()
            except Exception as e:
                self._set_status(f"Erro: {e} – reconectando em 5 s")
                time.sleep(5)

    def _set_status(self, txt):
        self.root.after(0, self.status_var.set, txt)

# ---------- run ----------
root = tk.Tk()
root.tk_setPalette(background="#f0f0f0")
MqttGui(root)
root.mainloop()
