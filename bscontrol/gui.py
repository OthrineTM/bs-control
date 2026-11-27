"""Control panel, tray icon and smart speed loop for the Flydigi BS2 / BS3 coolers."""

import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSettings, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QColorDialog, QGridLayout, QHBoxLayout, QLabel, QMenu, QSlider,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import device, rgb, smart, temps
from .device import Cooler, CoolerError
from .theme import (
    ACCENT, AMBER, BG, GREEN, MUTED, PANEL, PANEL_HI, TEXT, Card, CurveEditor, FanGauge, Pill,
    Swatch, Toggle, font, stylesheet,
)

APP_NAME = "BS Control"
APP_ID = "bs-control"
ICON_PATH = Path(__file__).resolve().parent.parent / "icons/bs-control.svg"
AUTOSTART = Path.home() / ".config/autostart/bs-control.desktop"
PALETTE = ["#3e95ff", "#00e5ff", "#2fd27a", "#c6ff00", "#ffd400", "#ff8a00", "#ff2d55", "#ff00c8",
           "#8a2be2", "#ffffff"]
TICK_MS = 1000
RGB_SMART_LEVELS = ((60, 1), (85, 2), (90, 3))  # below 60 °C -> 1 ... from 90 °C -> 4


def caption(text):
    lbl = QLabel(text)
    lbl.setObjectName("Caption")
    lbl.setWordWrap(True)
    return lbl


def hexes(colors):
    return [QColor(c).name() for c in colors]


def panel_text_color():
    """Text color of the Plasma color scheme (what monochrome tray icons use)."""
    path = Path.home() / ".config/kdeglobals"
    try:
        section = None
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line
            elif section == "[Colors:Window]" and line.startswith("ForegroundNormal="):
                r, g, b = (int(x) for x in line.split("=", 1)[1].split(",")[:3])
                return QColor(r, g, b)
    except (OSError, ValueError):
        pass
    return QColor("#fcfcfc")


def mono_fan(p, color, size=64):
    """Single-color fan glyph: gauge ring and seven blades."""
    c = size / 2
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(color, size * 0.07, Qt.SolidLine, Qt.RoundCap))
    m = size * 0.08
    p.drawArc(QRectF(m, m, size - 2 * m, size - 2 * m), 225 * 16, -270 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    for i in range(7):
        p.save()
        p.translate(c, c)
        p.rotate(i * 360 / 7)
        path = QPainterPath(QPointF(0, -size * 0.11))
        path.cubicTo(QPointF(size * 0.14, -size * 0.15), QPointF(size * 0.17, -size * 0.30),
                     QPointF(size * 0.05, -size * 0.36))
        path.cubicTo(QPointF(size * 0.02, -size * 0.26), QPointF(-size * 0.02, -size * 0.18),
                     QPointF(0, -size * 0.11))
        p.drawPath(path)
        p.restore()
    p.drawEllipse(QPointF(c, c), size * 0.07, size * 0.07)


def tray_icon(connected, mono=False):
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if mono:
        color = panel_text_color()
        if not connected:
            color.setAlphaF(0.45)
        mono_fan(p, color)
    else:
        QIcon(str(ICON_PATH)).paint(p, 0, 0, 64, 64)
        if not connected:
            p.setBrush(QColor(0, 0, 0, 150))
            p.setPen(Qt.NoPen)
            p.drawEllipse(36, 36, 26, 26)
            p.setPen(MUTED)
            p.setFont(font(16))
            p.drawText(36, 36, 26, 26, Qt.AlignCenter, "×")
    p.end()
    return QIcon(pm)


class PillGroup(QWidget):
    """Grid of exclusive pills mapping to values."""

    changed = Signal(object)

    def __init__(self, options, columns=None, height=36, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.group = QButtonGroup(self)
        self.buttons = {}
        columns = columns or len(options)
        for i, opt in enumerate(options):
            label, value = opt[0], opt[1]
            b = Pill(label, height=height, sub=opt[2] if len(opt) > 2 else "")
            self.group.addButton(b)
            self.buttons[value] = b
            grid.addWidget(b, i // columns, i % columns)
            b.clicked.connect(lambda _=False, v=value: self.changed.emit(v))

    def value(self):
        for v, b in self.buttons.items():
            if b.isChecked():
                return v
        return None

    def set_value(self, value):
        b = self.buttons.get(value)
        if b:
            b.setChecked(True)

    def set_sub(self, value, sub):
        b = self.buttons.get(value)
        if b:
            b.sub = sub
            b.update()


class LabeledSlider(QWidget):
    released = Signal(int)

    def __init__(self, minimum, maximum, fmt=str, step=1, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal, minimum=minimum, maximum=maximum)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(step * 5)
        self.value_lbl = QLabel()
        self.value_lbl.setObjectName("Value")
        self.value_lbl.setMinimumWidth(78)
        self.value_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.fmt = fmt
        self.step = step
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderReleased.connect(lambda: self.released.emit(self.slider.value()))
        row.addWidget(self.slider)
        row.addWidget(self.value_lbl)

    def _changed(self, v):
        if self.step > 1 and v % self.step:
            self.slider.setValue(round(v / self.step) * self.step)
            return
        self.value_lbl.setText(self.fmt(v))

    def value(self):
        return self.slider.value()

    def setValue(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.value_lbl.setText(self.fmt(v))


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.settings = QSettings(APP_ID, APP_ID)
        self.dev = None
        self.info = None
        self.status = None
        self.sensors = temps.Sensors()
        self.cpu = self.gpu = None
        self.loading = False
        self.curve = None
        self.smart_sent_at = 0.0
        self.mode_changed_at = 0.0
        self.last_speed = None
        self.rgb_smart_level = None
        self.retry_at = 0.0
        self.color_slot = 0

        self.build_ui()
        self.build_tray()
        self.resize(1000, 640)
        self.load_settings_ui()

        self.gear_timer = QTimer(self, singleShot=True, interval=350, timeout=self.apply_gear_speed)
        self.light_timer = QTimer(self, singleShot=True, interval=250, timeout=self.apply_lighting)
        self.tick_timer = QTimer(self, interval=TICK_MS, timeout=self.tick)
        self.tick_timer.start()
        QTimer.singleShot(0, self.tick)
        QApplication.instance().aboutToQuit.connect(self.on_quit)

    # --- settings -------------------------------------------------------

    def setting(self, key, default):
        v = self.settings.value(key, default)
        if isinstance(default, bool):
            return v in (True, "true", "1", 1)
        if isinstance(default, int):
            return int(v)
        if isinstance(default, (list, dict)):
            try:
                return json.loads(v) if isinstance(v, str) else default
            except ValueError:
                return default
        return v

    def put(self, key, value):
        self.settings.setValue(key, json.dumps(value) if isinstance(value, (list, dict)) else value)

    @property
    def fan_mode(self):
        return self.setting("fan/mode", "gear")

    # --- layout ---------------------------------------------------------

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 16)
        root.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel()
        self.title.setFont(font(21))
        titles.addWidget(self.title)
        titles.addWidget(caption("Laptop cooler  ·  Linux control"))
        head.addLayout(titles)
        head.addStretch()
        self.temp_lbl = QLabel()
        self.temp_lbl.setFont(font(10))
        self.temp_lbl.setTextFormat(Qt.RichText)
        head.addWidget(self.temp_lbl)
        head.addSpacing(26)
        box = QVBoxLayout()
        box.setSpacing(2)
        self.conn = QLabel("SEARCHING")
        self.conn.setFont(font(10))
        self.conn.setTextFormat(Qt.RichText)
        box.addWidget(self.conn, alignment=Qt.AlignRight)
        self.power_lbl = caption("")
        self.power_lbl.setWordWrap(False)
        box.addWidget(self.power_lbl, alignment=Qt.AlignRight)
        head.addLayout(box)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        self.gauge = FanGauge()
        left.addWidget(self.gauge, 1)
        self.info_lbl = caption("")
        self.info_lbl.setAlignment(Qt.AlignCenter)
        left.addWidget(self.info_lbl)
        body.addLayout(left, 4)

        right = QVBoxLayout()
        right.setSpacing(12)
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.tab_group = QButtonGroup(self)
        self.pages = QStackedWidget()
        for i, (name, page) in enumerate([("Fan", self.page_fan()), ("Lighting", self.page_lighting()),
                                          ("System", self.page_system())]):
            b = Pill(name, height=38)
            self.tab_group.addButton(b, i)
            tabs.addWidget(b)
            self.pages.addWidget(page)
        self.tab_group.idClicked.connect(self.pages.setCurrentIndex)
        self.tab_group.button(0).setChecked(True)
        right.addLayout(tabs)
        right.addWidget(self.pages, 1)
        body.addLayout(right, 6)
        self.update_title()

    def page(self, *panels, stretch=True):
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        for p in panels:
            col.addWidget(p)
        if stretch:
            col.addStretch()
        return w

    def page_fan(self):
        mode = Card("Mode")
        lay = QVBoxLayout(mode)
        self.mode = PillGroup([(n, g, "") for g, n in device.GEARS.items()] + [("Smart", "smart", "by temperature")],
                              height=50)
        self.mode.changed.connect(self.on_mode)
        lay.addWidget(self.mode)

        self.gear_card = Card("Gear speed")
        lay = QVBoxLayout(self.gear_card)
        self.gear_speed = LabeledSlider(device.MIN_SPEED, 4000, lambda v: f"{v} rpm", step=100)
        self.gear_speed.slider.valueChanged.connect(lambda _: self.loading or self.gear_timer.start())
        lay.addWidget(self.gear_speed)
        lay.addWidget(caption("Saved in the cooler for this gear, so the button on the cooler uses it too."))

        self.smart_card = Card("Smart speed")
        lay = QVBoxLayout(self.smart_card)
        self.preset = PillGroup(list((n, k) for k, n in smart.PRESETS.items()), height=32)
        self.preset.changed.connect(self.on_preset)
        lay.addWidget(self.preset)
        self.curve_edit = CurveEditor()
        self.curve_edit.changed.connect(self.on_curve_edited)
        lay.addWidget(self.curve_edit, 1)
        self.smart_hint = caption("")
        lay.addWidget(self.smart_hint)

        accel = Card("Fan acceleration")
        lay = QVBoxLayout(accel)
        self.accel = PillGroup([(f"Lv{i + 1}", i) for i in range(device.ACCEL_LEVELS)], height=32)
        self.accel.changed.connect(lambda v: self.send(lambda d: d.set_accel(v)))
        lay.addWidget(self.accel)
        lay.addWidget(caption("How quickly the fan ramps to a new speed."))
        return self.page(mode, self.gear_card, self.smart_card, accel)

    def page_lighting(self):
        light = Card("Light")
        lay = QVBoxLayout(light)
        self.light_on = Toggle("RGB lighting")
        self.light_on.toggled.connect(self.on_light_on)
        lay.addWidget(self.light_on)
        self.gear_light = Toggle("Gear light display", "Small lights that show the current gear")
        self.gear_light.toggled.connect(lambda v: self.send(lambda d: d.set_gear_light(v)))
        lay.addWidget(self.gear_light)

        effect = Card("Effect")
        lay = QVBoxLayout(effect)
        self.effect = PillGroup([(n, k) for k, n in rgb.EFFECTS.items()] + [("Smart", "smart")], columns=3,
                                height=32)
        self.effect.changed.connect(self.on_effect)
        lay.addWidget(self.effect)
        self.effect_hint = caption("")
        lay.addWidget(self.effect_hint)

        self.colors_card = Card("Colors")
        lay = QVBoxLayout(self.colors_card)
        slots = QHBoxLayout()
        slots.setSpacing(6)
        self.slots = []
        for i in range(6):
            s = Swatch("#3e95ff", size=36)
            s.clicked.connect(lambda _=False, i=i: self.select_slot(i))
            self.slots.append(s)
            slots.addWidget(s)
        slots.addStretch()
        custom = Pill("Custom…", height=30)
        custom.setCheckable(False)
        custom.setFixedWidth(110)
        custom.clicked.connect(self.pick_color)
        slots.addWidget(custom)
        lay.addLayout(slots)
        pal = QHBoxLayout()
        pal.setSpacing(4)
        for c in PALETTE:
            s = Swatch(c, size=26)
            s.clicked.connect(lambda _=False, c=c: self.set_slot_color(QColor(c)))
            pal.addWidget(s)
        pal.addStretch()
        lay.addLayout(pal)

        self.level_card = Card("Brightness and speed")
        grid = QGridLayout(self.level_card)
        grid.setVerticalSpacing(6)
        self.brightness = LabeledSlider(0, 100, lambda v: f"{v} %", step=5)
        self.brightness.slider.valueChanged.connect(self.queue_lighting)
        self.speed = LabeledSlider(10, 100, lambda v: f"{v} %", step=10)
        self.speed.slider.valueChanged.connect(self.queue_lighting)
        grid.addWidget(caption("Brightness"), 0, 0)
        grid.addWidget(self.brightness, 0, 1)
        grid.addWidget(caption("Speed"), 1, 0)
        grid.addWidget(self.speed, 1, 1)
        return self.page(light, effect, self.colors_card, self.level_card)

    def page_system(self):
        power = Card("Power")
        lay = QVBoxLayout(power)
        self.auto_start = Toggle("Power-on auto start", "Start the fan as soon as the laptop powers the cooler")
        self.auto_start.toggled.connect(lambda v: self.send(lambda d: d.set_auto_start(v)))
        lay.addWidget(self.auto_start)
        lay.addSpacing(6)
        lay.addWidget(caption("Smart stop: stop the fan when the laptop sleeps or shuts down"))
        self.smart_stop = PillGroup([(n, v) for v, n in device.SMART_STOP.items()], height=32)
        self.smart_stop.changed.connect(lambda v: self.send(lambda d: d.set_smart_stop(v)))
        lay.addWidget(self.smart_stop)

        supply = Card("Power supply")
        lay = QVBoxLayout(supply)
        self.supply_lbl = QLabel()
        self.supply_lbl.setWordWrap(True)
        self.supply_lbl.setTextFormat(Qt.RichText)
        lay.addWidget(self.supply_lbl)

        app = Card("App")
        lay = QVBoxLayout(app)
        self.autostart = Toggle("Start in the tray at login",
                                "Smart speed and smart lighting need the app running")
        self.autostart.setChecked(AUTOSTART.exists())
        self.autostart.toggled.connect(self.on_autostart)
        lay.addWidget(self.autostart)
        self.mono = Toggle("Monochrome tray icon", "Single color that follows the Plasma color scheme")
        self.mono.setChecked(self.setting("tray/mono", False))
        self.mono.toggled.connect(self.on_mono)
        lay.addWidget(self.mono)
        return self.page(power, supply, app)

    def update_title(self):
        model = self.dev.model if self.dev else "Cooler"
        self.title.setText(f"<span style='color:{ACCENT.name()}'>FLYDIGI</span> {model.upper()}")

    # --- tray -----------------------------------------------------------

    def build_tray(self):
        self.tray = QSystemTrayIcon(tray_icon(False, self.setting("tray/mono", False)), self)
        menu = QMenu()
        menu.addAction(QAction("Show", self, triggered=self.show_window))
        menu.addSeparator()
        self.tray_modes = QActionGroup(self)
        self.tray_actions = {}
        for value, name in list(device.GEARS.items()) + [("smart", "Smart speed")]:
            a = QAction(name, self, checkable=True)
            a.triggered.connect(lambda _=False, v=value: self.on_mode(v))
            self.tray_modes.addAction(a)
            self.tray_actions[value] = a
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(QAction("Quit", self, triggered=QApplication.quit))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.toggle_window() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def update_tray_icon(self, connected):
        mono = self.setting("tray/mono", False)
        key = (connected, mono, panel_text_color().name() if mono else "")
        if key != getattr(self, "_tray_key", None):
            self._tray_key = key
            self.tray.setIcon(tray_icon(connected, mono))

    def on_mono(self, on):
        self.put("tray/mono", on)
        self.update_tray_icon(self.status is not None)

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_window(self):
        self.hide() if self.isVisible() else self.show_window()

    def closeEvent(self, event):
        if self.tray.isVisible():
            event.ignore()
            self.hide()

    # --- device ---------------------------------------------------------

    def connect_device(self):
        try:
            self.dev = Cooler()
            self.info = self.dev.info()
            self.status = self.dev.status()
        except CoolerError as e:
            self.drop_device()
            self.show_error(e)
            return False
        self.update_title()
        self.gauge.set_product(self.dev.product_id)
        self.last_speed = None
        self.rgb_smart_level = None
        if self.fan_mode == "smart":
            self.enter_smart()
        elif self.status.smart:
            self.send(lambda d: d.smart_mode(False))
        self.load_device_ui()
        return True

    def drop_device(self):
        if self.dev:
            self.dev.close()
        self.dev = None
        self.status = None
        self.retry_at = time.monotonic() + 3

    def show_error(self, e):
        self.conn.setText(f"<span style='color:{AMBER.name()}'>{str(e).upper()}</span>")
        self.gauge.set_state(0, 0, 4000, False)
        self.pages.setEnabled(False)
        self.update_tray_icon(False)
        self.tray.setToolTip(f"{APP_NAME}: {e}")

    def send(self, fn):
        if self.loading or self.dev is None:
            return False
        try:
            fn(self.dev)
            return True
        except CoolerError as e:
            self.drop_device()
            self.show_error(e)
            return False

    def enter_smart(self):
        self.curve = smart.Curve(self.curve_points(), cap=self.max_rpm())
        self.last_speed = None
        if self.send(lambda d: d.smart_mode(True)):
            self.smart_sent_at = time.monotonic()

    def max_rpm(self):
        if not self.dev or not self.status:
            return 4000
        return device.max_speed(self.dev.product_id, self.status.vbus)

    def curve_points(self):
        preset = self.setting("fan/preset", "quiet")
        if preset == "custom":
            return self.setting("fan/custom", smart.DEFAULT_CUSTOM)
        pid = self.dev.product_id if self.dev else 0x1004
        return smart.preset_curve(preset, pid, self.status.vbus if self.status else 1)

    # --- periodic -------------------------------------------------------

    def tick(self):
        self.cpu, self.gpu = self.sensors.read()
        if self.dev is None:
            if time.monotonic() < self.retry_at or not self.connect_device():
                self.update_temps()
                return
        try:
            self.dev.drain()
            st = self.dev.last_status
        except CoolerError as e:
            self.drop_device()
            self.show_error(e)
            return
        if st is None:
            return
        old = self.status
        self.status = st
        if old and old.vbus != st.vbus and self.fan_mode == "smart":
            self.curve = smart.Curve(self.curve_points(), cap=self.max_rpm())
        self.run_smart(st)
        self.run_rgb_smart()
        self.update_live(st)

    def hottest(self):
        vals = [v for v in (self.cpu, self.gpu) if v is not None]
        return max(vals) if vals else None

    def run_smart(self, st):
        if time.monotonic() - self.mode_changed_at < 2.5:
            return  # status reports lag a little behind our own changes
        if self.fan_mode != "smart":
            if st.gear != self.mode.value() and not self.loading:
                self.set_mode_ui(st.gear)  # gear button on the cooler
            return
        if not st.smart:
            if time.monotonic() - self.smart_sent_at < 3:
                return
            # someone pressed the gear button on the cooler: follow it like Space Station does
            self.put("fan/mode", "gear")
            self.set_mode_ui(st.gear)
            return
        t = self.hottest()
        target = 1500 if t is None else self.curve.speed(t)
        target = max(device.MIN_SPEED, min(target, self.max_rpm()))
        if target != self.last_speed or st.target_rpm != target:
            if self.send(lambda d: d.set_speed(target)):
                self.last_speed = target

    def run_rgb_smart(self):
        if self.setting("light/effect", "glow") != "smart" or not self.setting("light/on", True):
            self.rgb_smart_level = None
            return
        t = self.hottest() or 0
        level = next((lv for limit, lv in RGB_SMART_LEVELS if t < limit), 4)
        if level != self.rgb_smart_level and self.send(lambda d: d.set_rgb_smart(level)):
            self.rgb_smart_level = level

    def update_temps(self):
        def fmt(name, v):
            if v is None:
                return ""
            color = AMBER.name() if v >= 85 else TEXT.name()
            return (f"<span style='color:{MUTED.name()}'>{name}</span> "
                    f"<span style='color:{color}'>{v:.0f}°C</span>&nbsp;&nbsp;&nbsp;")
        self.temp_lbl.setText(fmt("CPU", self.cpu) + fmt("GPU", self.gpu))
        t = self.hottest()
        self.curve_edit.set_temp(t)
        src = " and ".join(n for n, v in (("CPU", self.cpu), ("GPU", self.gpu)) if v is not None) or "no sensor"
        self.smart_hint.setText(f"Follows the hotter of {src}. Runs while this app is open, also from the tray. "
                                f"Top speed with this power supply: {self.max_rpm()} rpm.")

    def update_live(self, st):
        self.pages.setEnabled(True)
        state = "RUNNING" if st.running else "STOPPED"
        self.conn.setText(f"<span style='color:{GREEN.name() if st.running else MUTED.name()}'>●</span> "
                          f"{state}  ·  {'USB' if st.usb else 'BLUETOOTH' if st.bluetooth else ''}")
        self.power_lbl.setText(f"{device.POWER_SUPPLY.get(st.vbus, '?')}  ·  max {self.max_rpm()} rpm")
        gear_max = max(self.info.gear_speeds) if self.info else 0
        self.gauge.set_state(st.rpm, st.target_rpm, max(self.max_rpm(), gear_max), True)
        self.update_temps()
        mode = "Smart speed" if self.fan_mode == "smart" else device.GEARS.get(st.gear, "")
        t = self.hottest()
        self.update_tray_icon(True)
        self.tray.setToolTip(f"{self.dev.model}: {st.rpm} rpm ({mode})" + (f" · {t:.0f}°C" if t else ""))
        if self.accel.value() != st.accel:
            self.accel.set_value(st.accel)
        pro = self.dev.product_id in device.PRO_MODELS
        self.supply_lbl.setText(
            f"<b>{device.POWER_SUPPLY.get(st.vbus, '?')}</b>: smart speed tops out at "
            f"<b>{self.max_rpm()} rpm</b>.<br><span style='color:{MUTED.name()}'>"
            + ("A PD 18 W+ adapter on the cooler unlocks 3300 rpm, PD 27 W+ unlocks 4000 rpm."
               if pro else "A PD 18 W+ adapter on the cooler unlocks 3000 rpm.") + "</span>")

    # --- loading state into widgets ---------------------------------------

    def load_settings_ui(self):
        self.loading = True
        self.preset.set_value(self.setting("fan/preset", "quiet"))
        self.effect.set_value(self.setting("light/effect", "glow"))
        self.brightness.setValue(self.setting("light/brightness", 50))
        self.speed.setValue(self.setting("light/speed", 60))
        self.light_on.setChecked(self.setting("light/on", True))
        self.refresh_color_slots()
        self.refresh_effect_ui()
        self.refresh_curve()
        self.loading = False

    def load_device_ui(self):
        st, info = self.status, self.info
        self.loading = True
        for g, sp in enumerate(info.gear_speeds, 1):
            self.mode.set_sub(g, f"{sp} rpm")
        self.set_mode_ui("smart" if self.fan_mode == "smart" else st.gear)
        self.accel.set_value(st.accel)
        self.gear_light.setChecked(st.gear_light)
        self.light_on.setChecked(st.rgb_on)
        self.put("light/on", st.rgb_on)
        self.auto_start.setChecked(st.auto_start)
        self.smart_stop.set_value(st.smart_stop)
        self.info_lbl.setText(f"{info.model.upper()}   ·   FIRMWARE {info.firmware}   ·   {info.uid.upper()}")
        self.loading = False
        self.refresh_curve()
        self.update_live(st)

    def set_mode_ui(self, value):
        was = self.loading
        self.loading = True
        self.mode.set_value(value)
        if value in self.tray_actions:
            self.tray_actions[value].setChecked(True)
        smart_on = value == "smart"
        self.gear_card.setVisible(not smart_on)
        self.smart_card.setVisible(smart_on)
        if not smart_on and self.info:
            self.gear_speed.slider.setMaximum(4000 if (self.dev and self.dev.product_id in device.PRO_MODELS)
                                              else 3000)
            self.gear_speed.setValue(self.info.gear_speeds[value - 1])
            self.gear_card.title = f"{device.GEARS[value]} gear speed"
            self.gear_card.update()
        self.loading = was

    def refresh_curve(self):
        preset = self.setting("fan/preset", "quiet")
        self.curve_edit.set_limits(device.MIN_SPEED, 4000)
        self.curve_edit.set_curve(self.curve_points(), editable=preset == "custom")

    # --- fan actions ------------------------------------------------------

    def on_mode(self, value):
        if self.dev is None:
            return
        self.mode_changed_at = time.monotonic()
        if value == "smart":
            self.put("fan/mode", "smart")
            self.set_mode_ui("smart")
            self.enter_smart()
            self.tick()
            return
        self.put("fan/mode", "gear")
        self.set_mode_ui(value)
        if self.status and self.status.smart:
            self.send(lambda d: d.smart_mode(False))
        self.send(lambda d: d.set_gear(value))

    def apply_gear_speed(self):
        gear = self.mode.value()
        if gear == "smart" or gear is None or not self.info:
            return
        rpm = self.gear_speed.value()
        if self.send(lambda d: d.set_gear_speed(gear, rpm)):
            self.info.gear_speeds[gear - 1] = rpm
            self.mode.set_sub(gear, f"{rpm} rpm")

    def on_preset(self, preset):
        self.put("fan/preset", preset)
        self.refresh_curve()
        if self.fan_mode == "smart":
            self.curve = smart.Curve(self.curve_points(), cap=self.max_rpm())
            self.last_speed = None

    def on_curve_edited(self, points):
        self.put("fan/custom", [[t, s] for t, s in points])
        if self.fan_mode == "smart":
            self.curve = smart.Curve(points, cap=self.max_rpm())
            self.last_speed = None

    # --- lighting actions -------------------------------------------------

    def colors(self):
        return self.setting("light/colors", ["#3e95ff", "#ff2d55", "#2fd27a", "#ffd400", "#8a2be2", "#00e5ff"])

    def refresh_color_slots(self):
        effect = self.effect.value()
        n = rgb.COLOR_SLOTS.get(effect, 0)
        cols = self.colors()
        self.color_slot = min(self.color_slot, max(0, n - 1))
        for i, s in enumerate(self.slots):
            s.setVisible(i < n)
            s.set_color(cols[i])
            s.set_selected(i == self.color_slot and n > 1)
        self.colors_card.setVisible(n > 0)
        on = self.light_on.isChecked() and effect not in ("smart",)
        self.colors_card.setEnabled(on)
        self.level_card.setEnabled(on)
        self.speed.setEnabled(effect in rgb.ANIMATED)
        if n and on:
            self.gauge.set_glow(cols[0], True)
        else:
            self.gauge.set_glow(ACCENT, self.light_on.isChecked())

    def refresh_effect_ui(self):
        hints = {
            "smart": "Colors follow the CPU/GPU temperature: blue when cool, red when hot.",
            "multi": "Three colors, repeated around the fan.",
            "breathing": "Breathes through up to five colors.",
            "rotation": "Up to six colors chase around the fan.",
            "rainbow": "Fixed rainbow colors.",
            "glow": "Fixed color flow.",
        }
        self.effect_hint.setText(hints.get(self.effect.value(), ""))
        self.effect_hint.setVisible(self.effect.value() in hints)

    def on_effect(self, effect):
        self.put("light/effect", effect)
        self.refresh_effect_ui()
        self.refresh_color_slots()
        if not self.light_on.isChecked():
            self.light_on.setChecked(True)
        self.queue_lighting()

    def on_light_on(self, on):
        self.put("light/on", on)
        self.refresh_color_slots()
        if not self.loading:
            self.light_timer.start()

    def select_slot(self, i):
        self.color_slot = i
        self.refresh_color_slots()

    def set_slot_color(self, color):
        cols = self.colors()
        cols[self.color_slot] = QColor(color).name()
        self.put("light/colors", cols)
        self.refresh_color_slots()
        self.queue_lighting()

    def pick_color(self):
        c = QColorDialog.getColor(QColor(self.colors()[self.color_slot]), self, "Light color")
        if c.isValid():
            self.set_slot_color(c)

    def queue_lighting(self, *_):
        if not self.loading:
            self.put("light/brightness", self.brightness.value())
            self.put("light/speed", self.speed.value())
            self.light_timer.start()

    def apply_lighting(self):
        if self.dev is None:
            return
        effect = self.effect.value()
        on = self.light_on.isChecked()
        st = self.status

        def do(d):
            if not on:
                d.set_rgb(False)
                return
            if effect == "smart":
                self.rgb_smart_level = None  # the next tick picks the level
                d.set_rgb(True)
                return
            if st and st.rgb_smart:
                d.set_rgb_smart(0)
            cols = [tuple(QColor(c).getRgb()[:3]) for c in self.colors()]
            d.upload_rgb(rgb.build(effect, cols, self.brightness.value(), self.speed.value()))
            d.set_rgb(True)
        self.send(do)
        if effect == "smart" and on:
            self.run_rgb_smart()

    # --- system -----------------------------------------------------------

    def on_autostart(self, on):
        if on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text("[Desktop Entry]\nType=Application\nName=BS Control\n"
                                 "Exec=bs-control gui --tray\nIcon=bs-control\nX-GNOME-Autostart-enabled=true\n")
        else:
            AUTOSTART.unlink(missing_ok=True)

    def on_quit(self):
        # hand the fan back to the cooler's own gear so it doesn't stay at the last smart speed
        if self.dev and self.fan_mode == "smart":
            try:
                self.dev.smart_mode(False)
            except CoolerError:
                pass


INSTANCE_NAME = f"bs-control-{os.getuid()}"


def signal_running_instance(show):
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"show" if show else b"noop")
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def listen_for_instances(win):
    QLocalServer.removeServer(INSTANCE_NAME)
    server = QLocalServer(win)
    server.listen(INSTANCE_NAME)

    def on_connection():
        conn = server.nextPendingConnection()
        conn.waitForReadyRead(300)
        if conn.readAll().data() == b"show":
            win.show_window()
        conn.disconnectFromServer()

    server.newConnection.connect(on_connection)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    if signal_running_instance(show="--tray" not in argv):
        return 0
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.Base, PANEL), (QPalette.AlternateBase, PANEL_HI),
                        (QPalette.Button, PANEL_HI), (QPalette.Text, TEXT), (QPalette.WindowText, TEXT),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT)):
        pal.setColor(role, color)
    app.setPalette(pal)
    f = app.font()
    f.setPointSize(10)
    app.setFont(f)
    app.setStyleSheet(stylesheet())
    win = Window()
    listen_for_instances(win)
    if "--tray" not in argv:
        win.show()
    return app.exec()
