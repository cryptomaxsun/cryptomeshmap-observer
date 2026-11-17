
"""Read MeshCore battery and temperature through a local Companion."""

import argparse
import asyncio
import getpass
import json
import math
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def battery_curve(text):
    try:
        points = [tuple(map(int, point.split(":"))) for point in text.split(",")]
        if len(points) >= 2 and all(len(point) == 2 for point in points):
            if all(0 < mv <= 65535 and 0 <= pct <= 100 for mv, pct in points):
                if all(a[0] < b[0] and a[1] <= b[1] for a, b in zip(points, points[1:])):
                    return points
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Use increasing calibrated mV:percent pairs separated by commas.")


def estimate_charge(voltage_mv, curve):
    if voltage_mv <= curve[0][0]:
        return curve[0][1]
    for (left_mv, left_pct), (right_mv, right_pct) in zip(curve, curve[1:]):
        if voltage_mv <= right_mv:
            return round(left_pct + (right_pct - left_pct) * (voltage_mv - left_mv) / (right_mv - left_mv))
    return curve[-1][1]


def device_readings(sensors):
    readings = {}
    external = {}
    weather_fields = {
        "temperature": ("weather_temperature_c", -40, 85),
        "humidity": ("weather_humidity_percent", 0, 100),
        "barometer": ("weather_pressure_hpa", 300, 1100),
    }
    for sensor in sensors or []:
        channel = sensor["channel"]
        sensor_type = sensor["type"]
        value = sensor["value"]
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        if channel == 1:
            if sensor_type == "voltage" and 0 < value <= 65.535:
                readings["voltage_mv"] = round(value * 1000)
            elif sensor_type == "temperature" and -100 <= value <= 150:
                readings["temperature_c"] = value
        elif channel > 1 and sensor_type in weather_fields:
            field, lower, upper = weather_fields[sensor_type]
            if lower <= value <= upper:
                external.setdefault(channel, {})[field] = value
    for channel in sorted(external):
        if len(external[channel]) == len(weather_fields):
            readings.update(external[channel])
            break
    return readings


async def read_node(commands, key, self_key, password, events):
    if key == self_key:
        telemetry = await commands.get_self_telemetry()
        readings = device_readings(telemetry.payload.get("lpp") if telemetry.type == events.TELEMETRY_RESPONSE else None)
        battery = await commands.get_bat()
        voltage = battery.payload.get("level") if battery.type == events.BATTERY else None
    else:
        if password:
            login = await commands.send_login_sync(key, password, min_timeout=10)
            if not login or login.type != events.LOGIN_SUCCESS:
                raise RuntimeError("MeshCore login was not confirmed.")
        sensors = await commands.req_telemetry_sync(key, min_timeout=10)
        readings = device_readings(sensors)
        status = await commands.req_status_sync(key, min_timeout=10)
        voltage = status.get("bat") if status else None
    if isinstance(voltage, int) and 0 < voltage <= 65535:
        readings["voltage_mv"] = voltage
    return readings


def publish(server, token, key, readings):
    request = Request(
        server.rstrip("/") + "/api/observer/telemetry",
        data=json.dumps({"public_key": key, **readings}).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        if not json.load(response).get("success"):
            raise RuntimeError("The site did not confirm the update.")


async def run(args, token, password, ble_pin):
    from meshcore import EventType, MeshCore

    if args.serial:
        radio = await MeshCore.create_serial(args.serial)
    else:
        radio = await MeshCore.create_ble(args.ble, pin=ble_pin)
    if not radio:
        raise RuntimeError("Could not connect to the Companion.")
    try:
        info = await radio.commands.send_appstart()
        if info.type != EventType.SELF_INFO:
            raise RuntimeError("The connected device did not answer as a MeshCore Companion.")
        self_key = info.payload["public_key"].upper()
        key = args.target.upper() if args.target else self_key
        if key != self_key:
            await radio.commands.get_contacts()
        while True:
            try:
                readings = await read_node(radio.commands, key, self_key, password, EventType)
                if not readings:
                    raise RuntimeError("No battery or temperature reading returned by the node.")
                if args.curve and "voltage_mv" in readings:
                    readings["battery_level"] = estimate_charge(readings["voltage_mv"], args.curve)
                    readings["battery_level_estimated"] = True
                await asyncio.to_thread(publish, args.server, token, key, readings)
                print(f"{key[:12]}: {json.dumps(readings)}", flush=True)
            except (OSError, RuntimeError) as error:
                if not args.interval or (isinstance(error, HTTPError) and error.code in (401, 403)):
                    raise
                print(f"Poll failed: {error}", flush=True)
            if not args.interval:
                break
            await asyncio.sleep(args.interval)
    finally:
        await radio.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection = parser.add_mutually_exclusive_group(required=True)
    connection.add_argument("--serial", help="USB serial port, for example COM13 or /dev/ttyUSB0")
    connection.add_argument("--ble", help="Companion Bluetooth address")
    parser.add_argument("--ble-pin", action="store_true", help="Prompt for the Companion Bluetooth PIN")
    parser.add_argument("--target", help="Full public key of the remote node. Defaults to the Companion itself.")
    parser.add_argument("--login", action="store_true", help="Prompt for the remote node's MeshCore password")
    parser.add_argument("--server", default="https://cryptomeshmap.com")
    parser.add_argument("--interval", type=int, default=0, help="Poll interval in seconds, at least 120. Default: once.")
    parser.add_argument("--curve", type=battery_curve, help="Optional calibrated mV:percent curve for this node")
    args = parser.parse_args()
    if args.target and not re.fullmatch(r"[a-fA-F0-9]{64}", args.target):
        parser.error("--target must be the full 64-character hex public key")
    if args.interval and args.interval < 120:
        parser.error("--interval must be 120 seconds or longer")
    if args.ble_pin and not args.ble:
        parser.error("--ble-pin requires --ble")
    if args.login and not args.target:
        parser.error("--login requires --target")
    if urlsplit(args.server).scheme != "https":
        parser.error("--server must use HTTPS")

    token = os.environ.get("CMM_OBSERVER_TOKEN") or getpass.getpass("Observer token from the cabinet: ")
    password = getpass.getpass("Remote MeshCore password: ") if args.login else None
    ble_pin = getpass.getpass("Companion Bluetooth PIN: ") if args.ble_pin else None
    try:
        asyncio.run(run(args, token, password, ble_pin))
    except ModuleNotFoundError as error:
        raise SystemExit("Install the Companion library with: python -m pip install meshcore==2.3.17") from error
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
