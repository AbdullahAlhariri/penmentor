"""The overlay: a frozen frame of your screen with Claude's marks drawn on it, and the small badge at the top."""
import json
import math
import re
import os
import signal
import threading
import time

import numpy as np
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBitmap, QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPolygonF, QRegion
from PyQt6.QtWidgets import QApplication, QWidget

from . import show, xournal
from .harness import ask, pick, prepare
from .config import CACHE, CONF, save, set_state
from .desktop import Oops, activate, active_window, capture, pointer, rofi
from .draw import arrowhead, curve, edge, line_pts, panel, pen, qrect, ring, ring_rect, spin, tup
from .page import Page
from .prompts import FOLLOWUPS, MORE, TASKS, TECHNIQUES
from .style import BAR, DRILL, FIX, GHOST, HEAD, LEGEND, NOTE, NOTE_CH, PALETTE, READ, SPIN, TIP, TIP_CH, TOP, VERDICT
from .typeset import as_math, lines_key, read_line, shrink, tex, tex_lines, text_img, typeset, ui_font


def tex_jobs(r):
    """Every (text, size) the overlay draws for answer r, so LaTeX typesets them all in one run."""
    jobs = [(r.get('headline', ''), HEAD)] + [(read_line(l), READ) for l in r.get('read_as', [])]
    for m in r.get('marks', []):
        jobs += [lines_key(m.get('note'), NOTE, NOTE_CH), lines_key(m.get('why'), TIP, TIP_CH)]
        if m.get('write'):
            jobs.append((as_math(m['write']), GHOST if m['shape'] == 'ghost' else FIX))
    d = r.get('drill') or {}
    jobs += [lines_key(display(d.get('problem')), DRILL, 60)] + [(display(l), DRILL) for l in [*(d.get('lines') or []), d.get('fix')]]
    return [j for j in jobs + [lines_key(d.get('why'), TIP, TIP_CH)] if j[0]]


def display(s):
    """Full-size integrals and sums, as in a worked solution (inline maths shrinks them)."""
    return re.sub(r'\$([^$]+)\$', lambda m: '$\\displaystyle ' + m[1] + '$', s or '')


def qimage(pil):
    return QImage(pil.tobytes(), pil.width, pil.height, 3 * pil.width, QImage.Format.Format_RGB888).copy()


def save_last(ov, result):
    ov.shot_pil.save(CACHE / 'last.png', compress_level=1)  # the whole desktop: fast beats small
    (CACHE / 'last.json').write_text(json.dumps({'geom': ov.geom, 'screens': ov.screens, 'main': ov.main,
                                                 'wins': ov.wins, 'mode': ov.mode, 'result': result}))


class Pill(QWidget):
    """The badge at the top: 'Thinking' while Claude works, or a button. Never takes the focus from xournal.
    Without a compositor X can't make its corners transparent, so it paints the screenshot behind its rounded ends."""

    def __init__(self, backdrop, geom, text='Thinking', on_click=None, busy=True):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.backdrop, self.text, self.busy, self.on_click = backdrop, text, busy, on_click or QApplication.quit
        self.err, self.t0 = False, time.monotonic()
        self.set_size(geom, (66 if busy else 44) + QFontMetrics(ui_font(18)).horizontalAdvance(text))
        QTimer(self, interval=16 if busy else 250, timeout=lambda: self.update()).start()  # Python, so signal handlers get to run

    def set_size(self, geom, w, h=42):
        x, y, W, _ = geom
        self.geom = geom
        self.setGeometry(x + (W - w) // 2, y + TOP, w, h)

    def fail(self, msg):
        self.text, self.err, self.busy = msg, True, False
        self.set_size(self.geom, min(900, 40 + 9 * len(msg)))
        QTimer.singleShot(9000, QApplication.quit)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.drawImage(r, self.backdrop, QRectF(self.geometry()))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#9b1c1c' if self.err else '#16161a'))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setFont(ui_font(18))
        if self.busy:
            spin(p, QPointF(29, r.height() / 2), self.t0)
        p.setPen(QColor('white' if self.err else '#E6E6E6'))
        p.drawText(r.adjusted(48, 0, 0, 0) if self.busy else r, Qt.AlignmentFlag.AlignVCenter |
                   (Qt.AlignmentFlag.AlignLeft if self.busy else Qt.AlignmentFlag.AlignHCenter), self.text)

    def mousePressEvent(self, e):
        (QApplication.quit if e.button() == Qt.MouseButton.RightButton or self.err else self.on_click)()


class BoxPicker(QWidget):
    """Show me, step one: drag boxes round what to show (as many as you like) on the frozen frame. Tap the badge or
    press Enter to send them, right-click to take the last one back; Esc stops penmentor, as everywhere."""
    CYAN = QColor(0, 220, 255)

    def __init__(self, shot, geom, top, done):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.X11BypassWindowManagerHint)
        self.shot, self.done, self.boxes, self.drag, self.start = shot, done, [], None, QPointF()
        self.setGeometry(*geom)
        self.setCursor(Qt.CursorShape.CrossCursor)
        x, y, w, _ = top  # the focused monitor, in shot pixels (= ours)
        self.badge = QRectF(x + w / 2 - 260, y + TOP, 520, 44)

    def present(self):
        self.show()
        self.raise_()
        QTimer.singleShot(80, lambda: (self.activateWindow(), self.grabKeyboard()))

    def finish(self):
        self.releaseKeyboard()
        self.close()
        self.done([tup(b) for b in self.boxes])

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawImage(0, 0, self.shot)
        p.setFont(ui_font(18))
        for i, b in enumerate(self.boxes + [self.drag] * bool(self.drag)):
            p.setPen(pen(self.CYAN, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(b)
            if i < len(self.boxes) and len(self.boxes) > 1:
                p.setFont(ui_font(26))
                p.drawText(b.topLeft() + QPointF(10, 30), str(i + 1))
                p.setFont(ui_font(18))
        panel(p, self.badge, self.badge.height() / 2, 240)
        n = len(self.boxes)
        p.setPen(QColor('#E6E6E6'))
        p.drawText(self.badge, Qt.AlignmentFlag.AlignCenter, 'Box what to show, then tap here' if not n else
                   f'{n} box{"es" * (n > 1)}   ·   tap here to show {"them" if n > 1 else "it"}')

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.boxes = self.boxes[:-1]
        elif self.badge.contains(e.position()):
            return self.finish()
        else:
            self.start = e.position()
            self.drag = QRectF(self.start, self.start)
        self.update()

    def mouseMoveEvent(self, e):
        if self.drag is not None:
            self.drag = QRectF(self.start, e.position()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if self.drag is not None and self.drag.width() > 12 and self.drag.height() > 12:  # a tap is not a box
            self.boxes.append(self.drag)
        self.drag = None
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            QApplication.quit()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.finish()
        elif e.key() == Qt.Key.Key_Backspace or e.text() == 'z':
            self.boxes = self.boxes[:-1]
            self.update()


class Overlay(QWidget):
    """Claude's marks over your live screen, on every monitor it looked at. The window is shaped to the marks and
    panels themselves (an X shape: no compositor needed), so everywhere else you see and use your apps: write, scroll,
    move windows, while the marks stay. Only Esc closes it; the bar's buttons (or the penmentor key again) do the rest.
    geom: where the shot sits on the desktop. screens (monitors) and wins (windows) are (x, y, w, h) in shot pixels;
    the panels go on screens[main], the focused monitor."""
    done = pyqtSignal(object)
    asked = pyqtSignal(object)
    chose = pyqtSignal(object)

    def __init__(self, shot, geom, region=None, screens=None, main=0, wins=None, mode='check', page=None):
        # region: your boxes [(x0, y0, x1, y1)] in shot pixels, drawn on what Claude sees
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.X11BypassWindowManagerHint)
        self.geom, self.region, self.mode, self.page_req = tuple(geom), region, mode, page  # page: a xournal.PageRequest
        self.cache, self.locks = {}, {'pages': threading.Lock(), 'shots': threading.Lock()}
        self.load(shot, screens, main, wins)
        self.result, self.items, self.read_imgs, self.head, self.head_box, self.drill = None, [], None, None, None, None
        self.busy, self.error, self.hover, self.pinned = False, None, None, None
        self.want_plot = mode == 'show'
        self.app_window = active_window()  # xournal, usually: it gets the focus back after the box picker had the keyboard
        self.pill, self.t0, self.end, self.tip_pos, self.pin_pos = None, time.monotonic(), 0, QPointF(0, 0), QPointF(0, 0)
        self.setGeometry(*geom)
        self.setMouseTracking(True)
        self.done.connect(self.on_done)
        self.asked.connect(self.on_asked)
        self.chose.connect(self.on_chose)
        self.tips, self.head_img, self.legend = {}, QImage(), None
        self.base, self.bar_items, self.bar_hover = QRegion(), [], None  # base: the shape of everything but tooltips
        self.tick = QTimer(self, interval=16, timeout=self.update)
        QTimer(self, interval=33, timeout=self.track).start()  # hover from where the pointer is; and Python runs often
        # enough that the signal below is heard
        signal.signal(signal.SIGUSR1, lambda *a: QTimer.singleShot(0, self.poked))  # the penmentor key again

    def load(self, shot, screens, main, wins):
        """Freeze this frame. Its pages and Claude's copies are made from it lazily (the pages on a background thread)."""
        self.shot_pil = shot
        self.screens = [tuple(r) for r in screens or [(0, 0, *shot.size)]]
        self.main, self.wins = main if 0 <= main < len(self.screens) else 0, [tuple(r) for r in wins or []]
        self.M = QRectF(*self.screens[self.main])
        self.shot = qimage(shot)
        self.pal = PALETTE['dark']  # the focused window's, once its page is known
        threading.Thread(target=lambda: self.pages, daemon=True).start()  # ~0.5 s a monitor: while Claude thinks

    def per_frame(self, name, make):
        """make(shot) once per frame; a second caller waits for the first instead of doing it again."""
        shot = self.shot_pil
        with self.locks[name]:
            if self.cache.get(name, (None,))[0] is not shot:
                self.cache[name] = shot, make(shot)
            return self.cache[name][1]

    @property
    def pages(self):
        """One Page per visible window, and per monitor without one: each app has its own paper colour and chrome."""
        def make(shot):
            W, H = shot.size
            bare = [(x, y, w, h) for x, y, w, h in self.screens
                    if not any(x <= a + c / 2 < x + w and y <= b + d / 2 < y + h for a, b, c, d in self.wins)]
            rects = [(max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)) for x, y, w, h in self.wins + bare]
            return [Page(np.asarray(shot.crop(r)), r[:2]) for r in rects if r[2] > r[0] and r[3] > r[1]]
        return self.per_frame('pages', make)

    @property
    def shots(self):
        """What Claude sees: one shrunk PNG per monitor, with your boxes (numbered when several).
        Built on the worker thread (0.2 s), so the pill shows at once."""
        boxes = list(enumerate(self.region or [], 1))
        return self.per_frame('shots', lambda shot: [
            prepare(shot.crop((x, y, x + w, y + h)), [(n if len(boxes) > 1 else None, (a - x, b - y, c - x, d - y))
                                                      for n, (a, b, c, d) in boxes if a < x + w and c > x and b < y + h and d > y])
            for x, y, w, h in self.screens])

    def top_geom(self):
        x, y, w, h = self.screens[self.main]
        return self.geom[0] + x, self.geom[1] + y, w, h

    def page_for(self, r):
        """The page under the middle of r (desktop coords), else the nearest one."""
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        return min(self.pages, key=lambda p: math.dist((cx, cy), (min(max(cx, p.ox), p.ox + p.w), min(max(cy, p.oy), p.oy + p.h))))

    # --- talking to Claude ---
    def request(self, text, new_shot=True):
        self.busy, self.error, self.busy_t0 = True, None, time.monotonic()
        set_state('busy')
        if self.want_plot:
            screen = show.monitor(self.screens, self.main, self.geom)
            spot = show.rect(screen)
            show.open_window(spot)  # now, so its loading animation runs while Claude thinks
        if self.isVisible():
            self.tick.start()
            self.reshape()  # the headline turns into "Thinking"
        else:
            self.pill = Pill(self.shot, self.top_geom())
            self.pill.show()
        page = self.page_req if new_shot else None

        def work():
            try:
                r = ask(self.shots, text, self.main, new_shot, page=page and page.result())
            except Exception as ex:
                r = {'error': str(ex)[:300]}
            self.done.emit(r)
        threading.Thread(target=work, daemon=True).start()

    def followup(self, text):
        self.request(text, new_shot=self.result is None)  # Claude already has this screenshot once it has answered

    def on_done(self, r):
        self.busy = False
        if self.want_plot:
            self.want_plot = False
            show.send(spec=r['plot']) if r.get('plot') else show.send(error=r.get('error') or 'No animation came with this answer.')
        if 'error' in r:
            if self.isVisible():
                self.error = r['error']
                self.reshape()
                self.update()
                set_state(f'open {os.getpid()}')
            else:
                self.pill.fail(r['error'])
            return
        if self.pill:
            self.pill.close()
            self.pill = None
        save_last(self, r)
        self.set_result(r)
        if not self.isVisible():
            self.present()
        set_state(f'open {os.getpid()}')  # the penmentor key opens the marks' menu again

    def present(self):
        """Show the marks without taking the keyboard: it stays with the app you were writing in."""
        self.reshape()
        self.show()
        self.raise_()
        set_state(f'open {os.getpid()}')

    def reshape(self):
        """The window becomes exactly what is drawn on it (every mark at its end state, the panels): your live screen
        shows everywhere else and the pen reaches the app below. Pixels with any coverage count, so edges stay smooth."""
        img = QImage(self.size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_layer(p, math.inf, tips=False)
        p.end()
        a = np.frombuffer(img.bits().asarray(img.sizeInBytes()), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
        a[..., 3] = np.where(a[..., 3] > 0, 255, 0)  # createAlphaMask thresholds at half: keep the faint antialiased edge
        self.base = QRegion(QBitmap.fromImage(img.createAlphaMask()))
        self.apply_shape()

    def apply_shape(self):
        """base plus the tooltip, which moves with the pointer (cheap: a rectangle)."""
        shape = QRegion(self.base)
        if why := self.pinned or self.hover:
            shape = shape.united(QRegion(self.tip_rect(why, self.pin_pos if self.pinned else self.tip_pos)[0].toAlignedRect().adjusted(-2, -2, 2, 2)))
        self.setMask(shape)

    # --- turning the answer into drawables ---
    def set_result(self, r):
        self.result, self.read_imgs, self.pinned, self.hover = r, None, None, None
        self.pal = PALETTE['dark' if self.page_for(tup(self.M)).dark else 'light']
        typeset(tex_jobs(r))
        self.head_img = shrink(tex(r.get('headline', ''), 'white', HEAD), self.M.width() * .7)
        marks = r.get('marks', [])
        boxes, pgs = [], []
        for m in marks:
            k = m.get('screen')
            k = k if isinstance(k, int) and 0 <= k < len(self.screens) else self.main
            (x, y, w, _), s = self.screens[k], self.screens[k][2] / self.shots[k][1][0]
            b = [x + m['box'][0] * s, y + m['box'][1] * s, x + m['box'][2] * s, y + m['box'][3] * s]
            pgs.append(page := self.page_for(b))
            boxes.append(qrect(page.clip(b) if m['shape'] == 'ghost' else page.snap(b)))
        pals = [PALETTE['dark' if pg.dark else 'light'] for pg in pgs]
        outer = [ring_rect(b) if m['shape'] == 'circle' else b.adjusted(-6, -6, 46 if m['shape'] == 'check' else 6, 6)
                 for m, b in zip(marks, boxes)]
        taken = [tup(o.adjusted(-6, -6, 6, 6)) for m, o in zip(marks, outer) if m['shape'] != 'ghost']
        self.legend = self.legend_rows(marks)
        if self.legend:
            taken.append(tup(self.legend[0].adjusted(-8, -8, 8, 8)))
        if CONF['stats']:
            taken.append(tup(self.stats()[0].adjusted(-8, -8, 8, 8)))
        self.drill = self.make_drill(r['drill']) if isinstance(r.get('drill'), dict) else None
        self.head = self.head_spot(r, taken)
        taken.append(tup(self.head.adjusted(-10, -10, 10, 10)))
        writes = {i: as_math(m['write']) for i, m in enumerate(marks)
                  if m.get('write') and m['shape'] in ('strike', 'ghost')}
        ghosts = {i: tex(w, pals[i]['ghost'], GHOST) for i, w in writes.items() if marks[i]['shape'] == 'ghost'}
        gf = min([1] + [(pgs[i].w - 12) / max(g.width(), 1) for i, g in ghosts.items()])  # one size; only shrinks to fit the window
        written = {}  # ghosts and corrections claim their space before any note bubble does
        for i, w in writes.items():
            m, b, page = marks[i], boxes[i], pgs[i]
            if i in ghosts:
                img = ghosts[i]
                size = (img.width() * gf, img.height() * gf)
                spot = (b.left(), b.top(), b.left() + size[0], b.top() + size[1])
            else:  # correction written just above the crossed-out part
                img = shrink(tex(w, pals[i]['fix'], FIX), page.w - 12)
                size = (img.width(), img.height())
                spot = (b.center().x() - size[0] / 2, b.top() - size[1] - 6, b.center().x() + size[0] / 2, b.top() - 6)
            if page.busy(spot, taken):
                spot = page.place(size, tup(b), taken)
            taken.append(spot)
            written[i] = (img, qrect(spot))
            if m['shape'] == 'ghost':
                outer[i] = qrect(spot).adjusted(-4, -4, 4, 4)
        items = []
        order = sorted(range(len(marks)), key=lambda i: (marks[i].get('step') or i + 1, i))
        for k, i in enumerate(order):
            m, b, o, page, pal = marks[i], boxes[i], outer[i], pgs[i], pals[i]
            col, T = pal.get(m['role'], pal['a']), .25 + k * .5
            dashed = m['role'] in ('carry', 'unsure')
            sh_ = m['shape']
            stroke = lambda pts, w=3.2, t=T, d=.4, head=False, c=col, dash=dashed: items.append(
                dict(kind='stroke', pts=pts, pen=pen(c, w, dash), t=t, dur=d, head=head, layer=1))
            if sh_ == 'circle':
                stroke(ring(b, i))
            elif sh_ == 'mark':
                items.append(dict(kind='fill', rect=b.adjusted(-6, -4, 6, 4), color=col, t=T, dur=.3, layer=0, page=page))
            elif sh_ == 'underline':
                y = b.bottom() + 6
                stroke(line_pts((b.left() - 3, y), (b.right() + 3, y + 1)))
            elif sh_ == 'wavy':
                y, x0, n = b.bottom() + 7, b.left() - 3, max(8, int(b.width() / 3))
                stroke([QPointF(x0 + (b.width() + 6) * j / n, y + 3.5 * math.sin(j / n * (b.width() + 6) / 14 * 2 * math.pi))
                        for j in range(n + 1)])
            elif sh_ == 'strike':
                stroke(line_pts((b.left() - 4, b.center().y() + 4), (b.right() + 4, b.center().y() - 4)))
            elif sh_ == 'check':
                x, y = min(b.right() + 16, page.ox + page.w - 30), b.center().y()
                stroke(line_pts((x, y), (x + 7, y + 9), (x + 24, y - 14)), w=3.6, d=.3)
            elif sh_ == 'box':
                path = QPainterPath()
                path.addRoundedRect(b.adjusted(-6, -5, 6, 5), 7, 7)
                stroke([path.pointAtPercent(j / 60) for j in range(61)])
            if i in written:
                img, spot = written[i]
                ghost = sh_ == 'ghost'
                items.append(dict(kind='image', img=img, rect=spot, t=T if ghost else T + .35, dur=.5 if ghost else .3,
                                  layer=2, alpha=.8 if ghost else 1))
            if m.get('note'):
                img = shrink(tex_lines(m['note'], col, NOTE, NOTE_CH), page.w - 40)
                spot = qrect(page.place((img.width() + 22, img.height() + 14), tup(o), taken))
                taken.append(tup(spot))
                a = edge(spot, o.center(), 2)
                stroke(curve(a, edge(o, a, 3)), w=2.4, t=T + .35, d=.3, head=True, dash=False)
                items.append(dict(kind='bubble', img=img, rect=spot, color=col, t=T + .55, dur=.25, layer=2, why=m.get('why'), page=page))
            j = m.get('link')
            if isinstance(j, int) and 0 <= j < len(marks) and j != i:
                a = edge(o, outer[j].center())
                z = edge(outer[j], a)
                if math.dist((a.x(), a.y()), (z.x(), z.y())) < 40:
                    continue  # neighbours: a stub arrow reads as noise
                stroke(curve(a, z, .25), w=2.6, t=T + .4, d=.4, head=True,
                       dash=marks[j]['role'] == 'carry')
        self.hits = [(o, m.get('why')) for o, m in zip(outer, marks) if m.get('why')]
        self.items = sorted(items, key=lambda d: d['layer'])
        self.end = max([d['t'] + d['dur'] for d in items], default=0) + .1
        self.replay()
        self.reshape()

    def replay(self):
        self.t0 = time.monotonic()
        self.tick.start()

    # --- painting ---
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(0, 0, self.shot)  # under the marks: their soft edges blend onto what was there
        now = time.monotonic() - self.t0
        if now > self.end and not self.busy:
            self.tick.stop()
        self.paint_layer(p, now)

    def paint_layer(self, p, now, tips=True):
        """Everything penmentor draws, as of `now` seconds into the marks' animation (inf: the end)."""
        dim = .3 if self.busy else 1
        for d in self.items:
            k = min(1, max(0, (now - d['t']) / d['dur']))
            if k > 0:
                self.draw(p, d, k, dim)
        p.setOpacity(1)
        if self.legend and self.result:
            self.draw_legend(p)
        if self.drill:
            self.draw_drill(p)
        self.draw_headline(p)
        why = self.pinned or self.hover
        if why and tips:
            self.draw_tip(p, why)
        if CONF['read']:
            self.draw_read(p)

    def draw(self, p, d, k, dim):
        kind = d['kind']
        p.setOpacity(dim * d.get('alpha', 1) * (1 if kind == 'stroke' else k))
        if kind == 'fill':  # highlighter that keeps the ink crisp, on dark or light paper
            c = QColor(d['color'])
            c.setAlphaF(.42 if d['page'].dark else .45)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen if d['page'].dark
                                 else QPainter.CompositionMode.CompositionMode_Multiply)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(d['rect'], 6, 6)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        elif kind == 'stroke':
            pts = d['pts']
            n = max(2, round(len(pts) * k))
            p.setPen(d['pen'])
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF(pts[:n]))
            if d['head']:
                arrowhead(p, pts[n - 2], pts[n - 1], d['pen'].color())
        elif kind == 'image':
            p.drawImage(d['rect'], d['img'])
        elif kind == 'bubble':
            bg = QColor(*d['page'].bg.tolist(), 235)
            p.setPen(pen(d['color'], 2))
            p.setBrush(bg)
            p.drawRoundedRect(d['rect'], 10, 10)
            p.drawImage(d['rect'].topLeft() + QPointF(11, 7), d['img'])

    def headline(self):
        r = self.result or {}
        if self.error:
            icon, col, img = '!', '#FF6B4A', text_img(self.error[:90], 'white', 19)
        elif self.busy:
            icon, col, img = '◌', SPIN, text_img('Thinking', '#E6E6E6', 19)  # spin() draws over the ◌ slot
        else:
            icon, role = VERDICT.get(r.get('verdict'), ('•', 'a'))
            icon, col, img = icon, self.pal[role], self.head_img
        f = ui_font(19)
        return icon, col, img, f, QFontMetrics(f).horizontalAdvance(f'{icon}   ') + img.width() + 44

    def legend_rows(self, marks):
        """Legend for the colours this answer uses: (rect, [(colours, dashed, label)])."""
        keys = list(dict.fromkeys('ghost' if m['shape'] == 'ghost' else 'abc' if m['role'] in 'abc' else m['role']
                                  for m in marks))
        abc = [self.pal[x] for x in 'abc' if any(m['role'] == x and m['shape'] != 'ghost' for m in marks)]
        rows = [(abc if k == 'abc' else [self.pal[k]], k in ('carry', 'unsure'), LEGEND[k]) for k in keys]
        if not rows:
            return None
        w = 66 + max(QFontMetrics(ui_font(16)).horizontalAdvance(l) for *_, l in rows)
        h = 14 + 26 * len(rows)
        return QRectF(self.M.right() - w - 12, self.M.bottom() - 46 - h, w, h), rows

    def draw_legend(self, p):
        r, rows = self.legend
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 22, 215))
        p.drawRoundedRect(r, 10, 10)
        p.setFont(ui_font(16))
        y = r.top() + 7
        for cols, dashed, label in rows:
            seg = 30 / len(cols)
            for j, c in enumerate(cols):  # a line sample per colour, drawn like the marks
                x = r.left() + 14 + j * seg
                p.setPen(pen(c, 3.6, dashed))
                p.drawLine(QPointF(x, y + 13), QPointF(x + seg - 6, y + 13))
            p.setPen(QColor(215, 215, 222))
            p.drawText(QRectF(r.left() + 54, y, r.width() - 60, 26), Qt.AlignmentFlag.AlignVCenter, label)
            y += 26

    def head_spot(self, r, taken):
        """Headline pill goes where it hides no handwriting: top, below the toolbars, bottom, corners."""
        w, (X, Y, W, H) = self.headline()[4], self.screens[self.main]
        spots = () if self.drill else (  # a drill card sits right under the top spot
            (X + (W - w) / 2, Y + TOP), (X + (W - w) / 2, Y + TOP + 56), (X + (W - w) / 2, Y + H - 92), (X + W - w - 16, Y + TOP), (X + 16, Y + TOP))
        for x, y in spots:
            spot = (x, y, x + w, y + 42)
            if not self.page_for(spot).on_writing(spot) and not any(
                    spot[0] < t[2] and t[0] < spot[2] and spot[1] < t[3] and t[1] < spot[3] for t in taken):
                return qrect(spot)
        return qrect((X + (W - w) / 2, Y + TOP, X + (W + w) / 2, Y + TOP + 42))

    def draw_headline(self, p):
        icon, col, img, f, w = self.headline()
        head = self.head or QRectF(self.M.center().x(), self.M.top() + TOP, 0, 42)
        h = max(42, img.height() + 14)
        box = self.head_box = QRectF(head.center().x() - w / 2, head.top(), w, h)
        p.setFont(f)
        fm = QFontMetrics(f)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 22, 228))
        p.drawRoundedRect(box, 21, 21)
        p.setPen(QColor(col))
        if self.busy and not self.error:
            spin(p, QPointF(box.left() + 22 + fm.horizontalAdvance(icon) / 2, box.center().y()), self.busy_t0)
        else:
            p.drawText(box.adjusted(22, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, icon)
        p.drawImage(QPointF(box.left() + 22 + fm.horizontalAdvance(icon + '   '), box.center().y() - img.height() / 2), img)
        self.draw_actions(p)
        if CONF['stats']:
            self.draw_stats(p)

    def stats(self):
        """Bottom-left panel: (rect, label column width, rows). A row is (label, text, bar fraction or None); None is a gap."""
        r = self.result or {}
        rows = [('model', ':'.join(pick()), None), ('effort', CONF['effort'], None), ('context', CONF['context'], None)]
        n, cached, *total = r.get('_tokens') or [None, None]
        run = [('took', f"{r['_secs']:.1f} s", None)] if '_secs' in r else []
        if n is not None:
            run.append(('question', f'{n / 1000:.1f}k tokens ({cached / 1000:.1f}k cached)', None))
            run += [('session', f'{total[0] / 1000:.1f}k tokens', None)] if total else []
        rows += [None, *run] if run else []
        lim = r.get('_limits') or {}
        lims = [(label, f"{w['utilization']:.0%}  ·  resets {time.strftime(fmt, time.localtime(w['resetsAt']))}", w['utilization'])
                for key, label, fmt in (('five_hour', '5 hours', '%H:%M'), ('seven_day', 'week', '%a %H:%M'))
                if (w := lim.get(key)) and 'utilization' in w]
        rows += [None, *lims] if lims else []
        fm = QFontMetrics(ui_font(15))
        lw = max(fm.horizontalAdvance(x[0]) for x in rows if x) + 14
        vw = max(fm.horizontalAdvance(t) + (0 if f is None else BAR + 10) for x in rows if x for _, t, f in [x])
        h = 12 + sum(22 if x else 8 for x in rows)
        return QRectF(self.M.left() + 12, self.M.bottom() - 8 - h, 24 + lw + vw, h), lw, rows

    def draw_stats(self, p):
        r, lw, rows = self.stats()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 22, 240))  # xournal's sidebar sits under it
        p.drawRoundedRect(r, 10, 10)
        p.setFont(ui_font(15))
        y = r.top() + 6
        for row in rows:
            if not row:
                y += 8
                continue
            label, text, frac = row
            p.setPen(QColor(120, 120, 132))
            p.drawText(QRectF(r.left() + 12, y, lw, 22), Qt.AlignmentFlag.AlignVCenter, label)
            x = r.left() + 12 + lw
            if frac is not None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(58, 58, 66))
                p.drawRoundedRect(QRectF(x, y + 8, BAR, 6), 3, 3)
                p.setBrush(QColor(self.pal['error' if frac >= .9 else 'unsure' if frac >= .7 else 'ok']))
                p.drawRoundedRect(QRectF(x, y + 8, max(6, BAR * min(frac, 1)), 6), 3, 3)
                x += BAR + 10
            p.setPen(QColor(200, 200, 208))
            p.drawText(QRectF(x, y, r.right() - x, 22), Qt.AlignmentFlag.AlignVCenter, text)
            y += 22

    def draw_actions(self, p):
        """The bar of buttons, bottom right: tap one with the pen (the penmentor key opens the same as a menu)."""
        f = ui_font(15)
        fm = QFontMetrics(f)
        acts = self.actions()
        widths = [fm.horizontalAdvance(label) + 26 for label, _ in acts]
        x, y = self.M.right() - sum(widths) - 4 * (len(acts) - 1) - 12, self.M.bottom() - 36
        p.setFont(f)
        self.bar_items = []
        for (label, act), w in zip(acts, widths):
            r, hot = QRectF(x, y, w, 28), self.bar_hover == label
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(48, 48, 58, 240) if hot else QColor(18, 18, 22, 215))
            p.drawRoundedRect(r, 14, 14)
            p.setPen(QColor(238, 238, 242) if hot and not self.busy else QColor(170, 170, 180))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
            self.bar_items.append((r, label, act))
            x += w + 4

    def tip_rect(self, text, pos):
        if text not in self.tips:
            self.tips[text] = shrink(tex_lines(text, 'white', TIP, TIP_CH), self.width() - 48)
        img = self.tips[text]
        r = QRectF(pos.x() + 18, pos.y() + 18, img.width() + 24, img.height() + 16)
        if r.right() > self.width():
            r.moveRight(pos.x() - 12)
        if r.bottom() > self.height():
            r.moveBottom(pos.y() - 12)
        r.moveTo(max(r.left(), 4), max(r.top(), 4))
        return r, img

    def draw_tip(self, p, text):
        r, img = self.tip_rect(text, self.pin_pos if self.pinned else self.tip_pos)  # a pinned tip stays where you tapped
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 22, 240))
        p.drawRoundedRect(r, 9, 9)
        p.drawImage(r.topLeft() + QPointF(12, 8), img)

    def draw_read(self, p):
        if self.read_imgs is None:
            self.read_imgs = [shrink(tex(read_line(l), '#E8E8EC', READ), self.M.width() - 64)
                              for l in (self.result or {}).get('read_as', [])]
        w = max([i.width() for i in self.read_imgs] + [260]) + 32
        h = sum(i.height() + 10 for i in self.read_imgs) + 54
        r = QRectF(self.M.right() - w - 16, self.M.top() + TOP + 56, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 22, 235))
        p.drawRoundedRect(r, 12, 12)
        p.drawImage(r.topLeft() + QPointF(16, 12), text_img('What I read:', '#9A9AA5', 14))
        y = r.top() + 42
        for img in self.read_imgs:
            p.drawImage(QPointF(r.left() + 16, y), img)
            y += img.height() + 10

    # --- input ---
    def mouseMoveEvent(self, e):
        """Over what we drew (the window is shaped): light a button or a drill row; marks' whys come from hover_at."""
        pos = e.position()
        bar = next((label for r, label, _ in self.bar_items if r.contains(pos)), None)
        if bar != self.bar_hover:
            self.bar_hover = bar
            self.update()
        row = self.drill_row(pos) if self.drill else None
        if self.drill and row != self.drill['hover']:
            self.drill['hover'] = row
            self.update()
        head = self.mode == 'technique' and self.head_box and self.head_box.contains(pos)
        self.setCursor(Qt.CursorShape.PointingHandCursor if bar or row is not None or head or self.hover else Qt.CursorShape.ArrowCursor)
        self.hover_at(pos)

    def track(self):
        """Hover a mark, anywhere over it, for its why, as before the marks went live: the window is only their pixels,
        so the pointer is usually over your app and we never hear of it. Ask X where it is instead (a hovering pen
        moves it too); while you draw (a button or the pen tip down) no tooltip pops up."""
        where = pointer()
        if where and self.isVisible():
            x, y, held = where
            self.hover_at(QPointF(x - self.geom[0], y - self.geom[1]), held)

    def hover_at(self, pos, held=False):
        old, self.tip_pos = self.tip_pos, pos
        hit = None
        if self.result and not self.drill and not held:
            hit = next((why for o, why in self.hits if o.contains(pos)), None) or next(
                (d['why'] for d in self.items if d['kind'] == 'bubble' and d.get('why') and d['rect'].contains(pos)), None)
        if hit != self.hover:
            self.hover = hit
            self.apply_shape()
            self.update()
        elif hit and not self.pinned and pos != old:  # the tip follows the pointer: repaint where it was and where it goes
            self.apply_shape()
            for p in (old, pos):
                self.update(self.tip_rect(hit, p)[0].toAlignedRect().adjusted(-2, -2, 2, 2))

    def leaveEvent(self, e):
        if self.bar_hover:  # the marks' whys follow the pointer anyway (track)
            self.bar_hover = None
            self.update()

    def mousePressEvent(self, e):
        """A tap acts on what it hits. Nothing makes the marks go away but Esc (or the close button)."""
        self.tip_pos = e.position()
        if item := next(((label, act) for r, label, act in self.bar_items if r.contains(self.tip_pos)), None):
            if not self.busy or item[0].startswith('close'):
                item[1]()
        elif self.drill and (row := self.drill_row(self.tip_pos)) is not None:
            self.pick_line(row)
        elif self.mode == 'technique' and not self.busy and self.head_box and self.head_box.contains(self.tip_pos):
            self.pick_technique()
        elif self.hover:  # tap a mark to pin its "why" (pens don't hover well)
            self.pinned, self.pin_pos = None if self.pinned == self.hover else self.hover, self.tip_pos
            self.apply_shape()
            self.update()

    def on_asked(self, q):
        if q is None:  # Esc in rofi stops penmentor, like Esc anywhere else
            return self.close()
        if q:
            self.followup(q)

    def closeEvent(self, e):
        QApplication.quit()

    # --- the modes ---
    def actions(self):
        """What you can do next: the bar's buttons, and the menu the penmentor key opens. (label, what it does)"""
        if self.drill:
            first = [('new drill', lambda: self.followup(TASKS['drill_more']))]
        else:
            first = {'technique': [('pick the technique', self.pick_technique)],
                     'why': [('type your answer', lambda: self.ask_rofi([], 'your answer', TASKS['why_typed'])),
                             ('check what I wrote', lambda: self.check_new(TASKS['why_written']))]}.get(
                self.mode, [('check new work', lambda: self.check_new(TASKS['written']))])
        return first + [('more help', lambda: self.followup(MORE)), ('ask…', lambda: self.ask_rofi(FOLLOWUPS, 'follow-up')),
                        ('show me', self.pick_then_show), ('what I read', lambda: self.toggle('read')),
                        ('stats', lambda: self.toggle('stats')), ('replay', self.replay), ('close · esc', self.close)]

    def toggle(self, key):
        save(**{key: not CONF[key]})
        self.reshape()
        self.update()

    def poked(self):
        """The penmentor key (or a pad button) while the marks are up: the actions as a menu, or straight to that question."""
        try:
            what = (CACHE / 'poke').read_text().strip()
        except OSError:
            what = 'menu'
        if self.busy:
            return
        if what in TASKS:  # a pad button: that question about the work as it is now (you have probably written more)
            return self.check_new(TASKS[what])
        rows = [label for label, _ in self.actions()]
        threading.Thread(target=lambda: self.chose.emit(rofi(rows, 'penmentor')), daemon=True).start()

    def on_chose(self, label):
        if label is None:  # Esc: as everywhere
            return self.close()
        act = dict(self.actions()).get(label)
        if act:
            act()

    def pick_then_show(self):
        """Show me: box what to show on this frame, then Claude animates it (no boxes: what the problem is about)."""
        def chosen(boxes):
            activate(self.app_window)  # the picker had the keyboard; give it back to the app
            self.region, self.want_plot = boxes, True
            self.cache.pop('shots', None)  # redraw what Claude sees, with the boxes
            self.request(TASKS['show_boxes' if boxes else 'show'], new_shot=bool(boxes) or self.result is None)
        self.picker = BoxPicker(self.shot, self.geom, self.screens[self.main], chosen)
        self.picker.present()

    def ask_rofi(self, rows, prompt, template='{}'):
        """A rofi pick (or typed text) turned into a follow-up. No rows: just a text box."""
        def pick():  # on a thread: rofi waits for you, the marks keep drawing
            c = rofi(rows, prompt)
            self.asked.emit(None if c is None else c and template.format(c))  # None: Esc
        threading.Thread(target=pick, daemon=True).start()

    def pick_technique(self):
        self.ask_rofi(TECHNIQUES, 'technique', TASKS['pick'])

    def check_new(self, task):
        """Check what you wrote since: the marks step aside for the screenshot, then come back with the answer."""
        self.hide()
        QTimer.singleShot(150, lambda: self.reshoot(task))  # let X repaint where the marks were

    def reshoot(self, task):
        try:
            shot, screens, main, wins = capture()
        except Oops as ex:
            self.pill = Pill(self.shot, self.top_geom())
            self.pill.show()
            return self.pill.fail(str(ex))
        self.page_req, self.region, self.result = xournal.PageRequest(), None, None
        self.load(shot, screens, main, wins)
        self.request(task, new_shot=True)

    # --- find-the-error drill ---
    def make_drill(self, d):
        lines = [l for l in d.get('lines') or [] if isinstance(l, str)]
        wrong = d.get('wrong') if isinstance(d.get('wrong'), int) and 0 <= d['wrong'] < len(lines) else None
        maxw = self.M.width() * .6
        prob = shrink(tex_lines(display(d.get('problem')), '#E8E8EC', DRILL, 60), maxw)
        imgs = [shrink(tex(display(l), 'white', DRILL), maxw) for l in lines]
        fix = shrink(tex(display(d.get('fix')), self.pal['fix'], DRILL), maxw - 40)
        why = shrink(tex_lines(d.get('why') or '', '#C8C8D0', TIP, TIP_CH), maxw)
        said = text_img(f'line {(wrong or 0) + 1} should be', '#9A9AA5', 15)
        hint = text_img('One line has a mistake. Tap it.', '#7A7A86', 16)
        pad, num = 22, 40
        heights = [max(i.height(), 28) + 16 for i in imgs]
        W = max([prob.width(), said.width() + 12 + fix.width(), why.width(), *(i.width() for i in imgs)]) + num + 2 * pad
        reveal = max(said.height(), fix.height()) + why.height() + 34  # always reserved, so the card's size gives nothing away
        card = QRectF(self.M.center().x() - W / 2, self.M.top() + TOP + 62, W, pad + prob.height() + 18 + sum(heights) + reveal + pad)
        rows, y = [], card.top() + pad + prob.height() + 18
        for h, img in zip(heights, imgs):
            rows.append((QRectF(card.left() + 10, y, W - 20, h), img))
            y += h
        return dict(card=card, prob=prob, rows=rows, wrong=wrong, fix=fix, why=why, said=said, hint=hint, pad=pad, num=num, y=y,
                    hover=None, picked=set(), revealed=False, found=False)

    def drill_row(self, pos):
        return next((i for i, (r, _) in enumerate(self.drill['rows']) if r.contains(pos)), None)

    def pick_line(self, i):
        d = self.drill
        if d['revealed'] or i in d['picked']:
            return
        d['found'] = i == d['wrong']
        if not d['found']:
            d['picked'].add(i)
        d['revealed'] = d['found'] or d['wrong'] is None or len(d['picked']) >= 2  # two misses: show it
        if d['revealed']:
            text = 'Found it' if d['found'] else f"It was line {(d['wrong'] or 0) + 1}"
            self.result = dict(self.result, headline=text, verdict='correct' if d['found'] else 'mistake')
            self.head_img = tex(text, 'white', HEAD)
        self.reshape()
        self.update()

    def draw_drill(self, p):
        d, pal = self.drill, self.pal
        c = d['card']
        panel(p, c, 14, 255)
        p.drawImage(QPointF(c.left() + d['pad'], c.top() + d['pad']), d['prob'])
        y = c.top() + d['pad'] + d['prob'].height() + 9
        p.setPen(pen('#3a3a44', 1.2))
        p.drawLine(QPointF(c.left() + d['pad'], y), QPointF(c.right() - d['pad'], y))
        p.setFont(ui_font(16))
        for i, (r, img) in enumerate(d['rows']):
            miss, hit = i in d['picked'], d['revealed'] and i == d['wrong']
            if hit or miss or (i == d['hover'] and not d['revealed']):
                p.setPen(pen(pal['error'], 2.2) if hit else Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 178, 36, 30) if miss else QColor(255, 255, 255, 16 if not hit else 0))
                p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor(120, 120, 132))
            p.drawText(QRectF(r.left(), r.top(), d['num'], r.height()), Qt.AlignmentFlag.AlignCenter, str(i + 1))
            p.drawImage(QPointF(r.left() + d['num'], r.center().y() - img.height() / 2), img)
            if miss:
                p.setPen(QColor(pal['unsure']))
                p.drawText(r.adjusted(0, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, 'this line is fine')
        x, y = c.left() + d['pad'], d['y'] + 18
        if not d['revealed']:
            p.drawImage(QPointF(x, y), d['hint'])
        elif d['wrong'] is not None:
            p.drawImage(QPointF(x, y + (d['fix'].height() - d['said'].height()) / 2), d['said'])
            p.drawImage(QPointF(x + d['said'].width() + 12, y), d['fix'])
            p.drawImage(QPointF(x, y + max(d['fix'].height(), d['said'].height()) + 10), d['why'])
