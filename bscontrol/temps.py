"""CPU / GPU temperatures for smart speed, read without waking a sleeping dGPU."""

import shutil
import subprocess
import time
from pathlib import Path

CPU_DRIVERS = ("k10temp", "zenpower", "coretemp")
CPU_LABELS = ("Tctl", "Tdie", "Package id 0")


def _read(p):
    try:
        return int(Path(p).read_text()) / 1000
    except (OSError, ValueError):
        return None


def _labels(hwmon):
    for lbl in sorted(hwmon.glob("temp*_label")):
        try:
            yield lbl.read_text().strip(), _read(str(lbl).replace("_label", "_input"))
        except OSError:
            continue


class Sensors:
    def __init__(self):
        self._nv_cache = (0.0, None)

    def cpu(self):
        best = None
        for h in Path("/sys/class/hwmon").glob("hwmon*"):
            try:
                name = (h / "name").read_text().strip()
            except OSError:
                continue
            if name not in CPU_DRIVERS:
                continue
            temps = dict(_labels(h))
            for lbl in CPU_LABELS:
                if temps.get(lbl) is not None:
                    return temps[lbl]
            best = best or _read(h / "temp1_input")
        return best

    def gpu(self):
        """Hottest GPU we can see: EC-reported GPU temp (laptop platform drivers), amdgpu,
        and NVIDIA through nvidia-smi only while the card is already awake."""
        vals = []
        ec_gpu = False
        for h in Path("/sys/class/hwmon").glob("hwmon*"):
            try:
                name = (h / "name").read_text().strip()
            except OSError:
                continue
            for lbl, v in _labels(h):
                if v is None:
                    continue
                if lbl.upper() == "GPU":
                    vals.append(v)
                    ec_gpu = True
                elif name == "amdgpu" and lbl == "edge":
                    vals.append(v)
        nv = None if ec_gpu else self._nvidia()
        if nv is not None:
            vals.append(nv)
        return max(vals) if vals else None

    def _nvidia(self):
        t, v = self._nv_cache
        if time.monotonic() - t < 3:
            return v
        v = None
        awake = False
        for d in Path("/sys/bus/pci/devices").glob("*"):
            try:
                if (d / "vendor").read_text().strip() == "0x10de" and \
                        (d / "class").read_text().startswith("0x03"):
                    awake = awake or (d / "power/runtime_status").read_text().strip() == "active"
            except OSError:
                continue
        if awake and shutil.which("nvidia-smi"):
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                                     capture_output=True, text=True, timeout=2).stdout
                v = max(float(x) for x in out.split())
            except (OSError, ValueError, subprocess.SubprocessError):
                v = None
        self._nv_cache = (time.monotonic(), v)
        return v

    def read(self):
        return self.cpu(), self.gpu()
