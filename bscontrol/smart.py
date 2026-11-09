"""Smart speed: fan speed from the hottest of CPU and GPU, like Flydigi Space Station.

The vendor app keeps the cooler in 'smart' mode and sends a new speed once a second from a
temperature curve. Its curves are steps (the speed of the highest point at or below the
temperature) with 2 °C hysteresis while cooling down. The presets depend on the power supply,
since that caps the top speed.
"""

from . import device

QUIET = {
    "pro": {
        3: [(30, 1300), (40, 1300), (50, 1700), (60, 2100), (70, 2700), (80, 3000), (90, 3300), (100, 3500)],
        2: [(30, 1300), (40, 1300), (50, 1700), (60, 2100), (70, 2700), (80, 3000), (90, 3300), (100, 3300)],
        1: [(30, 1300), (40, 1300), (50, 1700), (60, 2100), (70, 2400), (80, 2700), (90, 2700), (100, 2700)],
    },
    "std": {
        2: [(30, 1300), (40, 1300), (50, 1700), (60, 2100), (70, 2400), (80, 2700), (90, 2700), (100, 2700)],
        1: [(30, 1300), (40, 1300), (50, 1700), (60, 2100), (70, 2400), (80, 2700), (90, 2700), (100, 2700)],
    },
}
PERFORMANCE = {
    "pro": {
        3: [(30, 1700), (40, 1700), (50, 2100), (60, 2700), (70, 3300), (80, 3500), (90, 4000), (100, 4000)],
        2: [(30, 1700), (40, 1700), (50, 2100), (60, 2700), (70, 3300), (80, 3300), (90, 3300), (100, 3300)],
        1: [(30, 1300), (40, 1700), (50, 2100), (60, 2400), (70, 2700), (80, 2700), (90, 2700), (100, 2700)],
    },
    "std": {
        2: [(30, 1700), (40, 1700), (50, 2100), (60, 2400), (70, 2700), (80, 3000), (90, 3000), (100, 3000)],
        1: [(30, 1300), (40, 1700), (50, 2100), (60, 2400), (70, 2700), (80, 2700), (90, 2700), (100, 2700)],
    },
}
PRESETS = {"quiet": "Quiet", "performance": "Performance", "custom": "Custom"}
DEFAULT_CUSTOM = [(40, 1300), (50, 1700), (60, 2100), (70, 2400), (80, 2700), (90, 2700)]
HYSTERESIS = 2.0


def preset_curve(preset, product_id, vbus):
    table = QUIET if preset == "quiet" else PERFORMANCE
    family = table["pro" if product_id in device.PRO_MODELS else "std"]
    if family is table["std"]:
        vbus = 2 if vbus in (2, 3) else 1
    return list(family.get(vbus, family[1]))


class Curve:
    def __init__(self, points, cap=None):
        pts = sorted((float(t), int(s)) for t, s in points)
        self.points = [(t, min(s, cap) if cap else s) for t, s in pts]
        self._last = None

    def speed(self, temp):
        rising = self._last is None or temp > self._last
        self._last = temp
        if not rising:
            temp -= HYSTERESIS
        for t, s in reversed(self.points):
            if temp >= t:
                return s
        return self.points[0][1]
