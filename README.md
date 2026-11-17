# Crypto Mesh Map — Observer & Telemetry Tools

Official client tools and gateway setup guide for **[Crypto Mesh Map](https://cryptomeshmap.com/)** — an interactive live map, packet analyzer, `#Public` channel decoder, and Line-of-Sight (LoS) terrain calculator for **MeshCore (LoRa 868 MHz)** networks.

- 🌐 **Live Map (UA):** https://cryptomeshmap.com/
- 🌍 **Live Map (EN):** https://cryptomeshmap.com/en/
- 📖 **User Guide:** https://cryptomeshmap.com/en/guide/ ([Українською](https://cryptomeshmap.com/guide/))
- 📱 **Android APK (v2.2.7, Android 4.4–15+):** https://cryptomeshmap.com/CryptoMeshMap.apk

---

## What is included in this repository

1. **`meshcore-telemetry-agent.py`** — Python agent that reads battery voltage, temperature, and external **BMP280 / BME280** weather telemetry (temperature, humidity, pressure) from a local MeshCore Companion (via USB Serial or Bluetooth LE) or remote Repeater/RoomServer over LoRa, and publishes it to `https://cryptomeshmap.com/api/observer/telemetry`.
2. **`companion-http-observer.py`** — USB/BLE Companion HTTP Observer bridge for boards without Wi-Fi (such as **Heltec T114** or **RAK4631**). Listens to `RX_LOG_DATA` radio frames and forwards them over HTTPS to `https://cryptomeshmap.com/api/observer/ingest`.
3. **`examples/gessaman-mqtt-commands.txt`** — Ready-to-use Serial Console command template to connect a **Gessaman MQTT Observer** gateway to `mqtt://cryptomeshmap.com:1883`.
4. **`examples/cmm-telemetry.service` & `examples/cmm-observer.service`** — `systemd` unit files for 24/7 autostart on Raspberry Pi / Linux.

---

## 1. Connect a Gessaman MQTT Observer Gateway

1. Sign in at [cryptomeshmap.com](https://cryptomeshmap.com/en/) (via email, GitHub, or Telegram) and open **Cabinet → Observer** to get your `YOUR_USERNAME` and `YOUR_OBSERVER_TOKEN`.
2. Flash your board via [MeshCore Flasher](https://flasher.meshcore.io/) or [Gessaman Observer](https://observer.gessaman.com/?config=mqtt-observer).
3. Open the device Serial Console and run the commands from `examples/gessaman-mqtt-commands.txt` (replace `YOUR_USERNAME`, `YOUR_OBSERVER_TOKEN`, `YOUR_IATA`, and your regional radio preset):

```text
set radio.freq 869.618,62.5,8,8
set radio.tx 22
set station.iata OZH
set mqtt1.url mqtt://cryptomeshmap.com:1883
set mqtt1.user YOUR_USERNAME
set mqtt1.pass YOUR_OBSERVER_TOKEN
set mqtt1.topic meshcore/{IATA}/{PUBLIC_KEY}
set mqtt1.enable true
save
reboot
```

Once connected, LoRa `ADVERT`, `#Public` messages, and radio receptions heard by your gateway will automatically appear on the live map.

---

## 2. Run the Python Telemetry & BME280 Agent

### Install requirements
Requires Python 3.10+:

```bash
python -m pip install -r requirements.txt
```

### Usage examples

Poll the **local Companion** (and attached BME280/BMP280 sensor) once over USB Serial:
```bash
python meshcore-telemetry-agent.py --serial COM13
```

Poll a **remote Repeater or RoomServer** over LoRa every 5 minutes (`300` seconds):
```bash
python meshcore-telemetry-agent.py --serial /dev/ttyUSB0 --target FULL_64_HEX_PUBLIC_KEY --interval 300
```

If the remote node requires a MeshCore password, add `--login`.  
To connect over Bluetooth LE instead of USB, use `--ble XX:XX:XX:XX:XX:XX` (and `--ble-pin` if paired with PIN).

You can also pass your Observer token via environment variable instead of interactive prompt:
```bash
export CMM_OBSERVER_TOKEN="your_observer_token_here"
```

---

## 3. Run a USB/BLE Companion as an HTTP Observer (`companion-http-observer.py`)

If your board does not have Wi-Fi (e.g., **nRF52840 / Heltec T114 / RAK4631**), you can connect a regular **MeshCore Companion** to a PC or Raspberry Pi and forward heard LoRa frames (`RX_LOG_DATA`) over HTTPS:

```bash
export CMM_OBSERVER_TOKEN="your_observer_token_here"
python companion-http-observer.py --serial /dev/ttyUSB0 --region OZH
```

---

## 4. 24/7 Autostart on Raspberry Pi / Linux (`systemd`)

1. Copy the repository to `/opt/cryptomeshmap-observer` and install `meshcore==2.3.17`.
2. Copy `examples/cmm-telemetry.service` or `examples/cmm-observer.service` to `/etc/systemd/system/`.
3. Replace `YOUR_OBSERVER_TOKEN`, serial port, and `--region`, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cmm-observer
sudo journalctl -u cmm-observer -f
```

---

## Українською (коротко)

Офіційні клієнтські інструменти для підключення до **[Crypto Mesh Map](https://cryptomeshmap.com/)**:
- **Підключення шлюзу Gessaman Observer:** увійдіть у кабінет на `cryptomeshmap.com`, отримайте токен Observer і виконайте команди з `examples/gessaman-mqtt-commands.txt` у Serial-консолі плати.
- **Опитування батареї та датчиків BME280/BMP280:** встановіть `pip install -r requirements.txt` і запустіть `python meshcore-telemetry-agent.py --serial COM_PORT --interval 300`.

---

## License
MIT — see [LICENSE](LICENSE).
