"""Command line interface: `bs3-control <command>`; no command opens the GUI."""

import argparse
import sys

from . import device, rgb
from .device import Cooler, CoolerError

GEAR_NAMES = {n.lower(): g for g, n in device.GEARS.items()}


def on_off(v):
    if v.lower() in ("on", "1", "true", "yes"):
        return True
    if v.lower() in ("off", "0", "false", "no"):
        return False
    raise argparse.ArgumentTypeError("expected on/off")


def gear(v):
    if v.isdigit() and 1 <= int(v) <= 4:
        return int(v)
    if v.lower() in GEAR_NAMES:
        return GEAR_NAMES[v.lower()]
    raise argparse.ArgumentTypeError("expected 1-4 or silent/standard/strong/overclock")


def color(v):
    v = v.lstrip("#")
    if len(v) != 6:
        raise argparse.ArgumentTypeError("expected RRGGBB")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def print_status(d):
    s, i = d.status(), d.info()
    mode = "smart speed (host controlled)" if s.smart else f"gear {s.gear} ({device.GEARS[s.gear]})"
    print(f"Model:            Flydigi {i.model}, firmware {i.firmware}")
    print(f"Fan:              {s.rpm} rpm (target {s.target_rpm}), {'running' if s.running else 'stopped'}")
    print(f"Mode:             {mode}")
    print("Gear speeds:      " + ", ".join(f"{device.GEARS[g + 1]} {sp}" for g, sp in enumerate(i.gear_speeds)))
    print(f"Acceleration:     Lv{s.accel + 1}")
    print(f"Power supply:     {device.POWER_SUPPLY.get(s.vbus, s.vbus)} (smart speed max "
          f"{device.max_speed(d.product_id, s.vbus)} rpm)")
    print(f"Connection:       {'USB' if s.usb else ''}{' + ' if s.usb and s.bluetooth else ''}"
          f"{'Bluetooth' if s.bluetooth else ''}")
    print(f"Lighting:         RGB {'on' if s.rgb_on else 'off'}{' (smart)' if s.rgb_smart else ''}, "
          f"gear light {'on' if s.gear_light else 'off'}")
    print(f"Power-on start:   {'on' if s.auto_start else 'off'}")
    print(f"Smart stop:       {device.SMART_STOP.get(s.smart_stop, s.smart_stop)}")
    print(f"UID:              {i.uid}")


def main(argv):
    p = argparse.ArgumentParser(prog="bs3-control", description="Flydigi BS2/BS3 laptop cooler control for Linux")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the control panel (default)").add_argument("--tray", action="store_true")
    sub.add_parser("status", help="show cooler state")
    sub.add_parser("rpm", help="print the fan speed only")
    s = sub.add_parser("gear", help="switch gear, optionally storing a new speed for it")
    s.add_argument("gear", type=gear, help="1-4 or silent/standard/strong/overclock")
    s.add_argument("--rpm", type=int, help="new speed for this gear")
    s = sub.add_parser("speed", help="hold a fixed speed (smart mode without a curve; resets to the gear on 'gear')")
    s.add_argument("rpm", type=int)
    sub.add_parser("accel", help="fan acceleration level 1-4").add_argument("level", type=int, choices=range(1, 5))
    s = sub.add_parser("light", help="set lighting")
    s.add_argument("effect", choices=list(rgb.EFFECTS) + ["smart", "off", "on"])
    s.add_argument("--color", type=color, action="append", help="RRGGBB, repeat for multi-color effects")
    s.add_argument("--brightness", type=int, default=100, metavar="0-100")
    s.add_argument("--speed", type=int, default=50, metavar="10-100")
    sub.add_parser("gear-light", help="gear indicator lights on/off").add_argument("state", type=on_off)
    sub.add_parser("auto-start", help="start the fan when the laptop powers the cooler").add_argument(
        "state", type=on_off)
    sub.add_parser("smart-stop", help="stop the fan when the laptop sleeps").add_argument(
        "mode", choices=["off", "immediately", "delayed"])
    args = p.parse_args(argv)

    if args.cmd in (None, "gui"):
        from .gui import main as gui_main
        return gui_main(sys.argv[:1] + (["--tray"] if getattr(args, "tray", False) else []))

    try:
        with Cooler() as d:
            if args.cmd == "status":
                print_status(d)
            elif args.cmd == "rpm":
                print(d.status().rpm)
            elif args.cmd == "gear":
                if d.status().smart:
                    d.smart_mode(False)
                if args.rpm:
                    d.set_gear_speed(args.gear, args.rpm)
                else:
                    d.set_gear(args.gear)
            elif args.cmd == "speed":
                if not d.status().smart:
                    d.smart_mode(True)
                d.set_speed(max(device.MIN_SPEED, args.rpm))
            elif args.cmd == "accel":
                d.set_accel(args.level - 1)
            elif args.cmd == "light":
                if args.effect in ("off", "on"):
                    d.set_rgb(args.effect == "on")
                elif args.effect == "smart":
                    d.set_rgb(True)
                    d.set_rgb_smart(1)
                else:
                    if d.status().rgb_smart:
                        d.set_rgb_smart(0)
                    d.upload_rgb(rgb.build(args.effect, args.color or [(62, 149, 255)], args.brightness, args.speed))
                    d.set_rgb(True)
            elif args.cmd == "gear-light":
                d.set_gear_light(args.state)
            elif args.cmd == "auto-start":
                d.set_auto_start(args.state)
            elif args.cmd == "smart-stop":
                d.set_smart_stop({"off": 0, "immediately": 1, "delayed": 2}[args.mode])
    except CoolerError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0
