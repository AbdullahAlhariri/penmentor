"""Pen strokes that look hand-drawn: rings, ticks, curved arrows, the loading arc."""
import math
import random
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen, QPolygonF

from .style import PANEL, SPIN


def panel(p, r, radius=10, alpha=228):
    """Dark rounded panel behind text."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(*PANEL, alpha))
    p.drawRoundedRect(r, radius, radius)


def pen(color, width=3.2, dashed=False):
    p = QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    if dashed:
        p.setDashPattern([2.2, 2.2])
    return p


def line_pts(*pts, n=12):
    out = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        out += [QPointF(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n)]
    return out + [QPointF(*pts[-1])]


def ring(r, seed):
    """Hand-drawn circle: starts top-left, overshoots, slightly uneven, like a teacher's pen."""
    rnd = random.Random(seed)
    c = r.center()
    a, b = r.width() / 2 * 1.12 + 9, r.height() / 2 * 1.2 + 8
    a0, ph = rnd.uniform(-2.7, -2.1), rnd.uniform(0, 6.3)
    pts = []
    for i in range(73):
        t = a0 + (2 * math.pi + .5) * i / 72
        f = 1 + .035 * math.sin(2 * t + ph) + .07 * i / 72
        pts.append(QPointF(c.x() + a * f * math.cos(t), c.y() + b * f * math.sin(t)))
    return pts


def curve(a, b, bend=.18):
    mx, my = (a.x() + b.x()) / 2, (a.y() + b.y()) / 2
    dx, dy = b.x() - a.x(), b.y() - a.y()
    c = QPointF(mx - dy * bend, my + dx * bend)
    path = QPainterPath(a)
    path.quadTo(c, b)
    return [path.pointAtPercent(i / 40) for i in range(41)]


def edge(r, toward, pad=5):
    """Point on r's border (plus pad) on the way from its centre to `toward`."""
    c = r.center()
    dx, dy = toward.x() - c.x(), toward.y() - c.y()
    if not dx and not dy:
        return c
    s = min(abs((r.width() / 2 + pad) / dx) if dx else 1e9, abs((r.height() / 2 + pad) / dy) if dy else 1e9)
    return QPointF(c.x() + dx * s, c.y() + dy * s)


def arrowhead(p, a, b, color, size=11):
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    tri = QPolygonF([b] + [QPointF(b.x() - size * math.cos(ang + s), b.y() - size * math.sin(ang + s)) for s in (.45, -.45)])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(tri)


def qrect(t):
    return QRectF(QPointF(t[0], t[1]), QPointF(t[2], t[3]))


def tup(r):
    return r.left(), r.top(), r.right(), r.bottom()


def spin(p, c, t0, r=8):
    """Loading arc around c: a thin ring that turns while it stretches and shrinks."""
    t = time.monotonic() - t0
    box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(pen('#33ffffff', 2.4))
    p.drawEllipse(box)
    p.setPen(pen(SPIN, 2.4))
    p.drawArc(box, int(-t * 330 * 16) % 5760, int((40 + 230 * (.5 - .5 * math.cos(t * 4))) * 16))


def ring_rect(b):
    return QRectF(b.center().x() - b.width() / 2 * 1.2 - 12, b.center().y() - b.height() / 2 * 1.28 - 11,
                  b.width() * 1.2 + 24, b.height() * 1.28 + 22)
