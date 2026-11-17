"""Forward MeshCore over-the-air packets from a USB/BLE Companion to Crypto Mesh Map."""

import argparse
import asyncio
import getpass
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def extract_hex(payload):
    raw = payload.get("payload") or payload.get("raw") or payload.get("raw_hex") or payload.get("data")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).hex().upper()
    if isinstance(raw, str):
        clean = re.sub(r"\s+", "", raw).upper()
        if re.fullmatch(r"[0-9A-F]{16,}", clean):
            return clean
    return None


def post_ingest(server, token, body):
    request = Request(
        server.rstrip("/") + "/api/observer/ingest",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.load(response)


async def run(args, token, ble_pin):
    from meshcore import EventType, MeshCore

    if args.serial:
        radio = await MeshCore.create_serial(args.serial)
    else:
        radio = await MeshCore.create_ble(args.ble, pin=ble_pin)
    if not radio:
        raise RuntimeError("Could not connect to the Companion.")

    info = await radio.commands.send_appstart()
    if info.type != EventType.SELF_INFO:
        await radio.disconnect()
        raise RuntimeError("The connected device did not answer as a MeshCore Companion.")

    obs_key = str(info.payload.get("public_key", "")).upper()
    obs_name = args.name or str(info.payload.get("name") or f"OBS-{obs_key[:6]}")
    if not re.fullmatch(r"[0-9A-F]{64}", obs_key):
        await radio.disconnect()
        raise RuntimeError("Companion did not return a valid 64-char hex public_key.")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    def on_rx_log(event):
        payload = getattr(event, "payload", None) or {}
        raw_hex = extract_hex(payload)
        if not raw_hex:
            return
        item = {
            "raw": raw_hex,
            "rssi": payload.get("rssi"),
            "snr": payload.get("snr"),
        }
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except asyncio.QueueFull:
            pass

    sub = radio.subscribe(EventType.RX_LOG_DATA, on_rx_log)
    print(f"Observer online: {obs_name} ({obs_key[:12]}...) region={args.region}", flush=True)

    async def send_status():
        body = {
            "observer_status": True,
            "observer_online": True,
            "observer_key": obs_key,
            "observer_name": obs_name,
            "sender_key": obs_key,
            "sender_name": obs_name,
            "sender_role": "Observer",
            "region": args.region,
            "packet_type": "OBSERVER_STATUS",
            "payload_summary": f"Observer Gateway Online [{obs_name}]",
        }
        await asyncio.to_thread(post_ingest, args.server, token, body)

    last_status = 0.0
    try:
        while True:
            now = time.monotonic()
            if now - last_status >= 300:
                try:
                    await send_status()
                    last_status = now
                except HTTPError as err:
                    if err.code in (401, 403):
                        raise RuntimeError(f"Authentication failed ({err.code}). Check Observer token.") from err
                    print(f"Status update failed: HTTP {err.code}", flush=True)
                except (OSError, URLError) as err:
                    print(f"Status update failed: {err}", flush=True)

            try:
                item = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                continue

            body = {
                "observer_key": obs_key,
                "observer_name": obs_name,
                "sender_key": obs_key,
                "sender_name": obs_name,
                "region": args.region,
                "raw": item["raw"],
                "rssi": item["rssi"],
                "snr": item["snr"],
            }
            try:
                await asyncio.to_thread(post_ingest, args.server, token, body)
                print(f"Forwarded RF frame ({len(item['raw']) // 2} B, RSSI={item['rssi']}, SNR={item['snr']})", flush=True)
            except HTTPError as err:
                if err.code in (401, 403):
                    raise RuntimeError(f"Authentication failed ({err.code}). Check Observer token.") from err
                print(f"Ingest failed: HTTP {err.code}", flush=True)
            except (OSError, URLError) as err:
                print(f"Ingest failed: {err}", flush=True)
    finally:
        radio.unsubscribe(sub)
        await radio.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection = parser.add_mutually_exclusive_group(required=True)
    connection.add_argument("--serial", help="USB serial port, for example COM13 or /dev/ttyUSB0")
    connection.add_argument("--ble", help="Companion Bluetooth address")
    parser.add_argument("--ble-pin", action="store_true", help="Prompt for the Companion Bluetooth PIN")
    parser.add_argument("--region", required=True, help="3-letter IATA region code, e.g. OZH, IEV, LWO")
    parser.add_argument("--name", help="Optional custom Observer display name")
    parser.add_argument("--server", default="https://cryptomeshmap.com")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9]{1,5}", args.region):
        parser.error("--region must be 1-5 alphanumeric characters (e.g. OZH)")
    args.region = args.region.upper()
    if args.ble_pin and not args.ble:
        parser.error("--ble-pin requires --ble")
    if urlsplit(args.server).scheme != "https":
        parser.error("--server must use HTTPS")

    token = os.environ.get("CMM_OBSERVER_TOKEN") or getpass.getpass("Observer token from the cabinet: ")
    ble_pin = getpass.getpass("Companion Bluetooth PIN: ") if args.ble_pin else None
    try:
        asyncio.run(run(args, token, ble_pin))
    except ModuleNotFoundError as error:
        raise SystemExit("Install the Companion library with: python -m pip install meshcore==2.3.17") from error
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
