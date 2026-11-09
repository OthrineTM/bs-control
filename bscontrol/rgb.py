"""Lighting animations for the cooler's 6 LEDs.

The firmware plays a loop of up to 10 frames. An upload is a 6-byte header
(version 0 2, loop start, loop end, frame time 1..11 where lower is faster, brightness 0..100)
followed by 6 LEDs x 10 frames of R G B. The effects below rebuild the frames the same way
Flydigi Space Station does.
"""

LEDS = 6
FRAMES = 10

EFFECTS = {
    "static": "Static",
    "multi": "Multi static",
    "breathing": "Breathing",
    "flash": "Flash",
    "wave": "Wave",
    "rotation": "Rotate",
    "rainbow": "Rainbow",
    "glow": "Dynamic glow",
}
# effects that use the color list (how many colors they take)
COLOR_SLOTS = {"static": 1, "multi": 3, "breathing": 5, "flash": 1, "wave": 1, "rotation": 6}
ANIMATED = {"breathing", "flash", "wave", "rotation", "rainbow", "glow"}

RAINBOW = [(255, 0, 0), (255, 127, 0), (255, 255, 0), (0, 255, 0), (0, 0, 255), (75, 0, 130), (148, 0, 211)]
GLOW = [(0, 0, 255), (0, 127, 127), (0, 255, 0), (127, 127, 0), (255, 0, 0), (127, 0, 127)]
BLACK = (0, 0, 0)


def loop_end(effect, n_colors):
    return {
        "breathing": min(9, n_colors * 2 - 1),
        "wave": LEDS - 1,
        "rainbow": 6,
        "flash": 1,
        "glow": 5,
        "rotation": 5,
    }.get(effect, 0)


def frame_color(effect, colors, led, frame, frame_count):
    base = colors[0] if colors else BLACK
    if effect == "static":
        return base
    if effect == "multi":
        if frame == 0 and colors:
            k = led % 3
            return colors[k] if k < min(len(colors), 3) else BLACK
        return BLACK
    if effect == "breathing":
        if not colors or frame > len(colors) * 2 or frame % 2 == 0:
            return BLACK
        return colors[frame // 2 % len(colors)]
    if effect == "flash":
        return base if frame % 2 == 0 else BLACK
    if effect == "wave":
        if frame >= frame_count:
            return BLACK
        k = (frame + led) % frame_count
        half = frame_count // 2
        f = k / half if k < half else (frame_count - k) / half
        return tuple(min(255, int(c * f)) for c in base)
    if effect == "rainbow":
        return RAINBOW[(frame + led) % 7] if frame < 7 else BLACK
    if effect == "glow":
        return GLOW[(frame + led) % 6] if frame < 6 else BLACK
    if effect == "rotation":
        if not colors or frame >= 6:
            return BLACK
        for i, c in enumerate(colors[:6]):
            if (6 + i - led) % 6 == frame:
                return c
        return BLACK
    return BLACK


def build(effect, colors, brightness=100, speed=50):
    """Frame data for an effect. `colors` is a list of (r, g, b); brightness and speed are 0..100."""
    colors = [tuple(c) for c in colors][: COLOR_SLOTS.get(effect, 0) or None]
    end = loop_end(effect, max(1, len(colors)))
    frame_time = max(1, min(10, speed // 10)) if effect in ANIMATED else 0
    data = bytearray([0, 2, 0, end, 11 - frame_time, max(0, min(100, brightness))])
    for led in range(LEDS):
        for frame in range(FRAMES):
            data += bytes(frame_color(effect, colors, led, frame, end + 1))
    return bytes(data)
