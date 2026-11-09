"""USB HID protocol of the Flydigi BS2 / BS3 laptop coolers.

Reverse engineered from Flydigi Space Station 36.9.5 (SpaceStationService.exe, Flydigi.CoolerSdk)
and checked on a BS3 Pro (37d7:1004, firmware 0.2.4.13).

Every request is a 32-byte output report without a report ID:

    5A A5 <cmd> <len> <payload...> <sum>

`len` counts itself, the command byte and the payload (so 2 for no payload) and `sum` is the
8-bit sum of cmd, len and payload. The cooler answers with a 32-byte input report that starts with
03 5A A5 <cmd> and carries its data from offset 5. About twice a second it also sends a status
report with command EF on its own.
"""

import os
import select
import time
from dataclasses import dataclass, field
from pathlib import Path

VENDOR_ID = 0x37D7
MODELS = {0x1001: "BS2", 0x1002: "BS2 Pro", 0x1003: "BS3", 0x1004: "BS3 Pro"}
PRO_MODELS = {0x1002, 0x1004}

# commands
CMD_FIRMWARE = 0x01
CMD_MAC = 0x04
CMD_AUTO_START = 0x0C
CMD_SMART_STOP = 0x0D
CMD_GEAR = 0x08
CMD_DEVICE_TYPE = 0x09
CMD_UUID = 0x0B
CMD_SET_SPEED = 0x21
CMD_GET_SPEED = 0x22
CMD_SMART_ON = 0x23
CMD_SMART_OFF = 0x24
CMD_FAN_MODE = 0x25
CMD_GEAR_SPEED = 0x26
CMD_GEAR_SPEEDS = 0x27
CMD_ACCEL = 0x2A
CMD_RGB_BEGIN = 0x41
CMD_RGB_END = 0x43
CMD_RGB_SMART = 0x44
CMD_RGB_STATUS = 0x45
CMD_RGB_ON = 0x46
CMD_RGB_DATA = 0x47
CMD_GEAR_LIGHT = 0x48
CMD_STATUS = 0xEF

GEARS = {1: "Silent", 2: "Standard", 3: "Strong", 4: "Overclock"}
ACCEL_LEVELS = 4
SMART_STOP = {0: "Off", 1: "Immediately", 2: "Delayed"}
POWER_SUPPLY = {0: "Unknown", 1: "USB (no fast charge)", 2: "QC fast charge", 3: "PD fast charge"}
MIN_SPEED = 1000


def max_speed(product_id, vbus):
    """Highest fan speed the current power supply allows (from the vendor app)."""
    if product_id in PRO_MODELS:
        return {2: 3300, 3: 4000}.get(vbus, 2700)
    return 2700 if vbus == 1 else 3000


class CoolerError(Exception):
    pass


@dataclass
class Status:
    running: bool = False
    gear: int = 1  # 1..4
    smart: bool = False  # host controlled speed ("smart speed")
    usb: bool = False
    bluetooth: bool = False
    vbus: int = 0  # see POWER_SUPPLY
    auto_start: bool = False
    smart_stop: int = 0
    gear_light: bool = False
    rgb_smart: bool = False
    rgb_on: bool = False
    rpm: int = 0
    target_rpm: int = 0
    accel: int = 0  # 0..3

    @classmethod
    def parse(cls, d):
        """`d` is the report starting at 5A A5."""
        b, b2, b3 = d[4], d[5], d[6]
        return cls(
            running=not (b & 1),
            gear=((b >> 1) & 3) + 1,
            bluetooth=bool(b & 0x08),
            usb=bool(b & 0x10),
            vbus=(b >> 5) & 3,
            smart=bool(b2 & 1),
            auto_start=bool(b2 & 2),
            smart_stop=(b2 >> 2) & 3,
            gear_light=bool(b3 & 1),
            rgb_smart=bool(b3 & 2),
            rgb_on=bool(b3 & 4),
            rpm=d[7] | d[8] << 8,
            target_rpm=d[9] | d[10] << 8,
            accel=d[11],
        )


@dataclass
class Info:
    model: str = ""
    product_id: int = 0
    firmware: str = ""
    uid: str = ""
    gear_speeds: list = field(default_factory=lambda: [0, 0, 0, 0])


def find_hidraw():
    for node in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        try:
            uevent = (node / "device/uevent").read_text()
        except OSError:
            continue
        for line in uevent.splitlines():
            if line.startswith("HID_ID="):
                _bus, vid, pid = line[7:].split(":")
                vid, pid = int(vid, 16), int(pid, 16)
                if vid == VENDOR_ID and pid & 0xFF00 == 0x1000:
                    return f"/dev/{node.name}", pid
    return None, None


def packet(cmd, payload=b""):
    n = 2 + len(payload)
    body = bytes([cmd, n]) + bytes(payload)
    return bytes([0x5A, 0xA5]) + body + bytes([sum(body) & 0xFF]) + bytes(31 - 3 - len(body))


class Cooler:
    def __init__(self, path=None):
        pid = None
        if path is None:
            path, pid = find_hidraw()
        if path is None:
            raise CoolerError("Cooler not found")
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            raise CoolerError("No permission (install the udev rule)") from None
        except OSError as e:
            raise CoolerError(str(e)) from None
        self.path = path
        self.product_id = pid or 0x1004
        self.model = MODELS.get(self.product_id, "BS cooler")
        self.last_status = None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # --- transport ------------------------------------------------------

    def _read(self, timeout):
        r, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not r:
            return None
        try:
            d = os.read(self.fd, 64)
        except BlockingIOError:
            return None
        except OSError as e:
            raise CoolerError("Cooler disconnected") from e
        i = d.find(b"\x5a\xa5")
        if i < 0 or len(d) < i + 5:
            return None
        d = d[i:]
        if d[2] == CMD_STATUS and len(d) >= 14:
            self.last_status = Status.parse(d)
        return d

    def drain(self, seconds=0.0):
        """Consume pending input (status reports) for up to `seconds`."""
        end = time.monotonic() + seconds
        while True:
            if self._read(max(0.0, end - time.monotonic())) is None and time.monotonic() >= end:
                return

    def request(self, cmd, payload=b"", timeout=0.5, retries=3):
        for _ in range(retries):
            self.drain()
            try:
                os.write(self.fd, b"\x00" + packet(cmd, payload))
            except OSError as e:
                raise CoolerError("Cooler disconnected") from e
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                d = self._read(end - time.monotonic())
                if d is not None and d[2] == cmd:
                    return d[4:]
        raise CoolerError(f"No answer to command {cmd:#04x}")

    def command(self, cmd, payload=b""):
        """Send a setter and check its ack byte."""
        r = self.request(cmd, payload)
        if r[0] != 1:
            raise CoolerError(f"Command {cmd:#04x} was rejected")

    # --- reads ----------------------------------------------------------

    def status(self, wait=1.5):
        """Latest status report (they arrive about twice a second)."""
        self.last_status = None
        end = time.monotonic() + wait
        while self.last_status is None and time.monotonic() < end:
            self._read(end - time.monotonic())
        if self.last_status is None:
            raise CoolerError("No status from the cooler")
        return self.last_status

    def info(self):
        i = Info(model=self.model, product_id=self.product_id)
        fw = self.request(CMD_FIRMWARE)
        i.firmware = ".".join(str(x) for x in fw[:4])
        i.uid = self.request(CMD_UUID)[:13].hex()
        i.gear_speeds = self.gear_speeds()
        return i

    def gear_speeds(self):
        r = self.request(CMD_GEAR_SPEEDS)
        return [r[k] | r[k + 1] << 8 for k in (0, 2, 4, 6)]

    def max_speed(self, status=None):
        s = status or self.last_status or self.status()
        return max_speed(self.product_id, s.vbus)

    # --- fan ------------------------------------------------------------

    def set_gear(self, gear):
        """Switch to one of the four fixed gears (leaves smart speed)."""
        self.command(CMD_GEAR, bytes([gear]))

    def set_gear_speed(self, gear, rpm):
        """Store a new speed for a gear and switch to it."""
        self.command(CMD_GEAR_SPEED, bytes([gear - 1, rpm & 0xFF, rpm >> 8]))

    def smart_mode(self, on):
        """Smart speed: the cooler follows set_speed() calls from the host."""
        self.command(CMD_SMART_ON if on else CMD_SMART_OFF)

    def set_speed(self, rpm):
        self.command(CMD_SET_SPEED, bytes([rpm & 0xFF, rpm >> 8]))

    def set_accel(self, level):
        """How fast the fan ramps to a new speed, 0 (gentle) .. 3 (fastest)."""
        self.command(CMD_ACCEL, bytes([level]))

    # --- system ---------------------------------------------------------

    def set_auto_start(self, on):
        """Start the fan when the laptop powers the cooler."""
        self.command(CMD_AUTO_START, bytes([1 if on else 2]))

    def set_smart_stop(self, mode):
        """Stop the fan when the laptop sleeps or shuts down: 0 off, 1 immediately, 2 delayed."""
        self.command(CMD_SMART_STOP, bytes([mode]))

    # --- lighting -------------------------------------------------------

    def set_rgb(self, on):
        self.command(CMD_RGB_ON, bytes([1 if on else 0]))

    def set_gear_light(self, on):
        """The small lights that show the current gear."""
        self.command(CMD_GEAR_LIGHT, bytes([1 if on else 0]))

    def set_rgb_smart(self, level):
        """Firmware 'smart' lighting, colored by temperature level 1..4 (0 = exit)."""
        self.command(CMD_RGB_SMART, bytes([level]))

    def upload_rgb(self, data):
        """Upload an animation (see rgb.build) in 10-byte chunks."""
        self.request(CMD_RGB_BEGIN)
        for idx, k in enumerate(range(0, len(data), 10)):
            self.request(CMD_RGB_DATA, bytes([idx]) + data[k:k + 10], timeout=1.0)
        self.request(CMD_RGB_END)
