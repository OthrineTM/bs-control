"""Space Station style theme: dark graphite cards, rounded shapes and Flydigi blue.

The product photo belongs to Flydigi and is not shipped with this project. install.sh copies it
into assets/ from a local Flydigi Space Station install when it finds one; without it the window
shows the animated fan gauge only.
"""

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QAbstractButton, QFrame, QSizePolicy, QWidget

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

ACCENT = QColor("#3e95ff")
BG = QColor("#121315")
PANEL = QColor("#1b1c1f")
PANEL_HI = QColor("#25272b")
LINE = QColor("#2e3035")
TEXT = QColor("#f5f5f5")
MUTED = QColor("#7e858e")
GREEN = QColor("#2fd27a")
AMBER = QColor("#ffb020")
RED = QColor("#ff4d4f")


def font(size, weight=QFont.DemiBold):
    f = QFont("Noto Sans", size)
    f.setWeight(weight)
    return f


def stylesheet():
    a = ACCENT.name()
    return f"""
    QWidget {{ color: {TEXT.name()}; }}
    #Root {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #17191c, stop:1 {BG.name()}); }}
    QLabel#Caption {{ color: {MUTED.name()}; font-size: 8.5pt; }}
    QLabel#Value {{ color: {a}; font-weight: 600; }}
    QLabel#Big {{ font-size: 20pt; font-weight: 700; }}
    QSlider::groove:horizontal {{ height: 6px; background: {LINE.name()}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {a}; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        background: white; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
        border: 3px solid {a};
    }}
    QSlider::sub-page:horizontal:disabled {{ background: {LINE.name()}; }}
    QSlider::handle:horizontal:disabled {{ border-color: {MUTED.name()}; background: {PANEL_HI.name()}; }}
    QToolTip {{ background: {PANEL_HI.name()}; color: {TEXT.name()}; border: 1px solid {LINE.name()};
                border-radius: 6px; padding: 4px 8px; }}
    QMenu {{ background: {PANEL.name()}; border: 1px solid {LINE.name()}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {a}; }}
    QMenu::separator {{ height: 1px; background: {LINE.name()}; margin: 4px 6px; }}
    QMessageBox, QColorDialog {{ background: {PANEL.name()}; }}
    QPushButton {{ background: {PANEL_HI.name()}; border: 1px solid {LINE.name()}; border-radius: 8px;
                   padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {a}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    """


class Card(QFrame):
    """Rounded card with a title."""

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.title = title
        self.setContentsMargins(18, 42 if title else 16, 18, 16)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, PANEL_HI)
        g.setColorAt(1, PANEL)
        p.setBrush(g)
        p.setPen(QPen(LINE, 1))
        p.drawRoundedRect(r, 14, 14)
        if self.title:
            p.setPen(Qt.NoPen)
            p.setBrush(ACCENT)
            p.drawRoundedRect(QRectF(r.left() + 18, r.top() + 17, 4, 14), 2, 2)
            p.setPen(TEXT)
            p.setFont(font(10))
            p.drawText(QRectF(r.left() + 30, r.top() + 12, r.width() - 48, 24),
                       Qt.AlignLeft | Qt.AlignVCenter, self.title)


class Pill(QAbstractButton):
    """Checkable rounded button for tabs and option tiles."""

    def __init__(self, text, parent=None, height=36, sub=""):
        super().__init__(parent)
        self.setText(text)
        self.sub = sub
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._h = height
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(max(fm.horizontalAdvance(self.text()), fm.horizontalAdvance(self.sub)) + 36, self._h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        rad = min(10, r.height() / 2)
        if self.isChecked():
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, ACCENT.lighter(115))
            g.setColorAt(1, ACCENT.darker(125))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
        else:
            hover = self.underMouse() and self.isEnabled()
            p.setBrush(PANEL_HI if hover else QColor(255, 255, 255, 8))
            p.setPen(QPen(ACCENT if hover else LINE, 1))
        p.drawRoundedRect(r, rad, rad)
        p.setPen(Qt.white if self.isChecked() else (TEXT if self.isEnabled() else MUTED))
        if self.sub:
            p.setFont(font(9.5))
            p.drawText(r.adjusted(0, 6, 0, -r.height() / 2), Qt.AlignHCenter | Qt.AlignBottom, self.text())
            p.setFont(font(8, QFont.Normal))
            p.setPen(QColor(255, 255, 255, 200) if self.isChecked() else MUTED)
            p.drawText(r.adjusted(0, r.height() / 2 + 1, 0, -4), Qt.AlignHCenter | Qt.AlignTop, self.sub)
        else:
            p.setFont(font(9.5))
            p.drawText(r, Qt.AlignCenter, self.text())

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class Toggle(QAbstractButton):
    """Rounded on/off switch with a label (and optional hint underneath)."""

    def __init__(self, text="", hint="", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.hint = hint
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(260, 44 if self.hint else 28)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        track = QRectF(self.width() - 46, (self.height() - 24) / 2, 44, 24)
        a = ACCENT if self.isEnabled() else MUTED
        p.setPen(Qt.NoPen)
        p.setBrush(a if on else LINE)
        p.drawRoundedRect(track, 12, 12)
        p.setBrush(Qt.white if self.isEnabled() else PANEL_HI)
        p.drawEllipse(QPointF(track.right() - 12 if on else track.left() + 12, track.center().y()), 9, 9)
        tr = QRectF(0, 0, self.width() - 56, self.height())
        p.setPen(TEXT if self.isEnabled() else MUTED)
        p.setFont(font(9.5, QFont.Normal))
        if self.hint:
            p.drawText(tr.adjusted(0, 2, 0, -self.height() / 2), Qt.AlignLeft | Qt.AlignBottom, self.text())
            p.setPen(MUTED)
            p.setFont(font(8, QFont.Normal))
            p.drawText(tr.adjusted(0, self.height() / 2 + 2, 0, 0), Qt.AlignLeft | Qt.AlignTop, self.hint)
        else:
            p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, self.text())


class Swatch(QAbstractButton):
    """Round color chip; `selected` draws a ring."""

    def __init__(self, color, size=24, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.selected = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(self.color.name())

    def set_color(self, c):
        self.color = QColor(c)
        self.setToolTip(self.color.name())
        self.update()

    def set_selected(self, s):
        self.selected = s
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.selected or self.underMouse():
            p.setPen(QPen(Qt.white if self.selected else MUTED, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(self.color)
        p.drawEllipse(r.adjusted(2, 2, -2, -2))

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()


class FanGauge(QWidget):
    """Ring gauge with the live fan speed and a spinning fan, tinted by the light color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rpm, self.target, self.max_rpm = 0, 0, 4000
        self.connected = False
        self.glow = QColor(ACCENT)
        self.glow_on = True
        self.angle = 0.0
        self.timer = QTimer(self, interval=33, timeout=self._tick)
        self.timer.start()
        self.setMinimumSize(240, 240)
        self.product = None
        for name in ("bs3pro.png", "main.png"):
            if (ASSETS / name).exists():
                self.product = QPixmap(str(ASSETS / name))
                break

    def set_state(self, rpm, target, max_rpm, connected):
        self.rpm, self.target, self.max_rpm, self.connected = rpm, target, max(max_rpm, 1), connected
        self.update()

    def set_glow(self, color, on):
        self.glow, self.glow_on = QColor(color), on
        self.update()

    def _tick(self):
        if self.connected and self.rpm:
            # visibly proportional, not literal (that would alias)
            self.angle = (self.angle + self.rpm / 4000 * 22) % 360
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        top = r.top()
        if self.product and not self.product.isNull():
            ph = min(r.height() * 0.42, r.width() * 0.62 * self.product.height() / self.product.width())
            pw = ph * self.product.width() / self.product.height()
            p.setOpacity(1.0 if self.connected else 0.35)
            p.drawPixmap(QRectF(r.center().x() - pw / 2, top + 6, pw, ph), self.product,
                         QRectF(self.product.rect()))
            p.setOpacity(1.0)
            top += ph + 16
        area = QRectF(r.left(), top, r.width(), r.bottom() - top)
        d = min(area.width(), area.height()) * 0.86
        c = QPointF(area.center().x(), area.center().y())
        ring = QRectF(c.x() - d / 2, c.y() - d / 2, d, d)

        # glow behind the fan in the light color
        if self.connected and self.glow_on:
            g = QRadialGradient(c, d * 0.55)
            col = QColor(self.glow)
            col.setAlpha(70)
            g.setColorAt(0.55, col)
            col.setAlpha(0)
            g.setColorAt(1, col)
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawEllipse(c, d * 0.55, d * 0.55)

        # track + value arc (270° sweep starting bottom left)
        w = max(8.0, d * 0.045)
        p.setPen(QPen(LINE, w, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(ring, 225 * 16, -270 * 16)
        frac = min(1.0, self.rpm / self.max_rpm) if self.connected else 0
        if frac > 0:
            cg = QConicalGradient(c, 225)
            cg.setColorAt(0, ACCENT.lighter(140))
            cg.setColorAt(0.75, ACCENT.darker(120))
            p.setPen(QPen(QBrush(cg), w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(ring, 225 * 16, int(-270 * 16 * frac))
        # target tick
        if self.connected and self.target:
            t = math.radians(225 - 270 * min(1.0, self.target / self.max_rpm))
            ro, ri = d / 2 + w * 0.9, d / 2 - w * 0.9
            p.setPen(QPen(Qt.white, 2.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() + ri * math.cos(t), c.y() - ri * math.sin(t)),
                       QPointF(c.x() + ro * math.cos(t), c.y() - ro * math.sin(t)))

        # fan blades
        fr = d * 0.30
        p.save()
        p.translate(c)
        p.rotate(self.angle)
        blade = QColor(TEXT if self.connected else MUTED)
        blade.setAlpha(46)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(blade)
        for i in range(9):
            p.save()
            p.rotate(i * 40)
            path = QPainterPath(QPointF(0, -fr * 0.28))
            path.cubicTo(QPointF(fr * 0.35, -fr * 0.45), QPointF(fr * 0.42, -fr * 0.85), QPointF(fr * 0.12, -fr))
            path.cubicTo(QPointF(fr * 0.05, -fr * 0.7), QPointF(-fr * 0.02, -fr * 0.5), QPointF(0, -fr * 0.28))
            p.drawPath(path)
            p.restore()
        p.restore()
        p.setPen(Qt.NoPen)
        p.setBrush(PANEL)
        p.drawEllipse(c, fr * 0.3, fr * 0.3)

        # numbers
        p.setPen(TEXT if self.connected else MUTED)
        p.setFont(font(max(14, int(d * 0.11)), QFont.Bold))
        txt = f"{self.rpm}" if self.connected else "--"
        p.drawText(QRectF(c.x() - d / 2, c.y() + d * 0.16, d, d * 0.16), Qt.AlignCenter, txt)
        p.setPen(MUTED)
        p.setFont(font(max(7, int(d * 0.038)), QFont.Normal))
        sub = f"RPM   ·   TARGET {self.target}" if self.connected else "NOT CONNECTED"
        p.drawText(QRectF(c.x() - d / 2, c.y() + d * 0.31, d, d * 0.08), Qt.AlignCenter, sub)


class CurveEditor(QWidget):
    """Temperature → speed steps with draggable points and a marker for the current temperature."""

    changed = Signal(list)
    T_MIN, T_MAX = 25, 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.max_rpm, self.min_rpm = 4000, 1000
        self.temp = None
        self.editable = True
        self.drag = None
        self.setMinimumHeight(190)
        self.setMouseTracking(True)

    def set_curve(self, points, editable):
        self.points = [[float(t), int(s)] for t, s in points]
        self.editable = editable
        self.update()

    def set_limits(self, min_rpm, max_rpm):
        self.min_rpm, self.max_rpm = min_rpm, max_rpm
        self.update()

    def set_temp(self, t):
        self.temp = t
        self.update()

    def _plot(self):
        return QRectF(self.rect()).adjusted(46, 10, -12, -26)

    def _xy(self, t, s):
        r = self._plot()
        x = r.left() + (t - self.T_MIN) / (self.T_MAX - self.T_MIN) * r.width()
        y = r.bottom() - (s - 0) / self.max_rpm * r.height()
        return QPointF(x, y)

    def _ts(self, pt):
        r = self._plot()
        t = self.T_MIN + (pt.x() - r.left()) / r.width() * (self.T_MAX - self.T_MIN)
        s = (r.bottom() - pt.y()) / r.height() * self.max_rpm
        return t, s

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        p.setFont(font(7.5, QFont.Normal))
        for s in range(0, self.max_rpm + 1, 1000):
            y = self._xy(self.T_MIN, s).y()
            p.setPen(QPen(LINE, 1, Qt.DashLine if s else Qt.SolidLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(MUTED)
            p.drawText(QRectF(0, y - 8, r.left() - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{s}")
        for t in range(30, self.T_MAX + 1, 10):
            x = self._xy(t, 0).x()
            p.setPen(MUTED)
            p.drawText(QRectF(x - 20, r.bottom() + 4, 40, 16), Qt.AlignCenter, f"{t}°")
        # cap line
        if not self.points:
            return
        pts = sorted(self.points)
        path = QPainterPath(self._xy(self.T_MIN, pts[0][1]))
        for i, (t, s) in enumerate(pts):
            a = self._xy(t, s)
            path.lineTo(QPointF(a.x(), path.currentPosition().y()))
            path.lineTo(a)
        path.lineTo(QPointF(r.right(), path.currentPosition().y()))
        fill = QPainterPath(path)
        fill.lineTo(r.bottomRight())
        fill.lineTo(r.bottomLeft())
        fill.closeSubpath()
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        c = QColor(ACCENT)
        c.setAlpha(80)
        g.setColorAt(0, c)
        c.setAlpha(5)
        g.setColorAt(1, c)
        p.fillPath(fill, g)
        p.setPen(QPen(ACCENT if self.editable else MUTED.lighter(120), 2))
        p.drawPath(path)
        for i, (t, s) in enumerate(pts):
            a = self._xy(t, s)
            p.setPen(QPen(ACCENT if self.editable else MUTED, 2))
            p.setBrush(Qt.white if self.drag == i else PANEL)
            p.drawEllipse(a, 5.5, 5.5)
        if self.temp is not None:
            x = self._xy(min(max(self.temp, self.T_MIN), self.T_MAX), 0).x()
            p.setPen(QPen(AMBER, 1.5, Qt.DashLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(AMBER)
            p.setFont(font(8))
            p.drawText(QRectF(x + 4, r.top(), 60, 16), Qt.AlignLeft, f"{self.temp:.0f} °C")

    def mousePressEvent(self, e):
        if not self.editable:
            return
        pts = sorted(self.points)
        self.points = pts
        for i, (t, s) in enumerate(pts):
            a = self._xy(t, s)
            if (a - e.position()).manhattanLength() < 14:
                self.drag = i
                self.update()
                return

    def mouseMoveEvent(self, e):
        if self.drag is None:
            near = self.editable and any((self._xy(t, s) - e.position()).manhattanLength() < 14
                                         for t, s in self.points)
            self.setCursor(Qt.SizeAllCursor if near else Qt.ArrowCursor)
            return
        t, s = self._ts(e.position())
        i = self.drag
        lo = self.points[i - 1][0] + 1 if i > 0 else self.T_MIN
        hi = self.points[i + 1][0] - 1 if i + 1 < len(self.points) else self.T_MAX
        t = round(min(max(t, lo), hi))
        s = int(round(min(max(s, self.min_rpm), self.max_rpm) / 50) * 50)
        self.points[i] = [t, s]
        self.update()

    def mouseReleaseEvent(self, e):
        if self.drag is not None:
            self.drag = None
            self.update()
            self.changed.emit([(t, s) for t, s in self.points])
