"""Where the ink is: snap Claude's rough boxes onto the handwriting, and find empty space for notes."""
import math

import numpy as np


class Page:
    """One window (or bare monitor) of the screenshot. Every method takes and returns desktop coordinates."""

    def __init__(self, rgb, origin=(0, 0)):
        from scipy import ndimage  # slow import (0.2 s): only pages need it, and they are built while Claude thinks
        self.ox, self.oy = origin  # where this window sits on the desktop
        h, w = rgb.shape[:2]  # paper colour = most common colour mid-window (edges are toolbars, margins)
        vals, counts = np.unique(rgb[h // 4:3 * h // 4:4, w // 4:3 * w // 4:4].reshape(-1, 3), axis=0, return_counts=True)
        self.bg = vals[counts.argmax()]
        self.dark = self.bg.mean() < 128
        occ = np.abs(rgb.astype(np.int16) - self.bg).sum(2) > 90
        f = occ.astype(np.float32)
        # long straight runs are ruling, page edges or app chrome, not handwriting
        hrun, vrun = (ndimage.uniform_filter1d(f, 121, axis=ax) > .97 for ax in (1, 0))
        self.ink = occ & ~(hrun | vrun)
        self.paper = ~occ
        self.h, self.w = occ.shape
        # app chrome = thick long bands (toolbars, status bar, panel frames); the page is the open area around
        # the window centre, and whatever the chrome walls off from it (a sidebar) is off-limits too
        solid = ndimage.binary_opening(occ, np.ones((9, 9), bool)) & (hrun | vrun)
        lab, _ = ndimage.label(~solid)
        mid = lab[h // 2, w // 2]
        chrome = (lab != mid) if mid else solid
        # notes may cover ruled lines, never handwriting or chrome
        integral = lambda m: np.pad(m.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        self.sum, self.chrome_sum = integral(ndimage.binary_dilation(self.ink, iterations=8) | chrome), integral(chrome)

    def local(self, r):
        return r[0] - self.ox, r[1] - self.oy, r[2] - self.ox, r[3] - self.oy

    def desk(self, r):
        return r[0] + self.ox, r[1] + self.oy, r[2] + self.ox, r[3] + self.oy

    def clip(self, b):
        return self.desk(self._clip(self.local(b)))

    def _clip(self, b):
        x0, y0, x1, y1 = (int(round(v)) for v in b)
        x0, x1 = sorted((min(max(x0, 0), self.w - 1), min(max(x1, 1), self.w)))
        y0, y1 = sorted((min(max(y0, 0), self.h - 1), min(max(y1, 1), self.h)))
        return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)

    def snap(self, box, pad=14):
        """Tight box around the ink strokes that lie mostly inside `box`."""
        from scipy import ndimage
        x0, y0, x1, y1 = self._clip(self.local(box))
        X0, Y0, X1, Y1 = self._clip((x0 - pad, y0 - pad, x1 + pad, y1 + pad))
        win = self.ink[Y0:Y1, X0:X1]
        lab, n = ndimage.label(ndimage.binary_dilation(win, iterations=3))
        lab = lab * win
        inside = np.zeros_like(win)
        inside[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = True
        tot = np.bincount(lab.ravel(), minlength=n + 1)
        ins = np.bincount(lab[inside].ravel(), minlength=n + 1)
        keep = [i for i in range(1, n + 1) if ins[i] and ins[i] >= .3 * tot[i]]
        if not keep:
            return self.desk((x0, y0, x1, y1))
        ys, xs = np.nonzero(np.isin(lab, keep))
        return self.desk((X0 + xs.min(), Y0 + ys.min(), X0 + xs.max() + 1, Y0 + ys.max() + 1))

    def busy(self, r, taken, ink=True):
        x0, y0, x1, y1 = (int(v) for v in self.local(r))
        if x0 < 0 or y0 < 0 or x1 > self.w or y1 > self.h:
            return True
        S = self.sum if ink else self.chrome_sum
        if S[y1, x1] - S[y0, x1] - S[y1, x0] + S[y0, x0]:
            return True
        return any(r[0] < t[2] and t[0] < r[2] and r[1] < t[3] and t[1] < r[3] for t in taken)

    def fit(self, r, m=6):
        """r moved fully inside the window (left edge wins if it is too wide)."""
        x0, y0, x1, y1 = self.local(r)
        dx = max(min(0, self.w - m - x1), m - x0)
        dy = max(min(0, self.h - m - y1), m - y0)
        return self.desk((x0 + dx, y0 + dy, x1 + dx, y1 + dy))

    def place(self, size, target, taken):
        """Nearest empty spot for a w×h note on rings around target; right, below, above, left first."""
        w, h = size
        tx0, ty0, tx1, ty1 = target
        cx, cy, rx, ry = (tx0 + tx1) / 2, (ty0 + ty1) / 2, (tx1 - tx0 + w) / 2, (ty1 - ty0 + h) / 2
        for ink in (True, False):  # no empty paper left: cover ink rather than leave the page
            for d in (24, 50, 90, 140, 210, 300, 420, 580):
                for deg in (0, 90, -90, 180, 30, -30, 60, -60, 120, -120, 150, -150):
                    x = cx + math.cos(math.radians(deg)) * (rx + d) - w / 2
                    y = cy + math.sin(math.radians(deg)) * (ry + d) - h / 2
                    if not self.busy((x, y, x + w, y + h), taken, ink):
                        return x, y, x + w, y + h
        return self.fit((tx1 + 24, cy - h / 2, tx1 + 24 + w, cy + h / 2))

    def on_writing(self, r, pad=8):
        """Does r cover handwriting on the page? (covering app chrome is fine)"""
        x0, y0, x1, y1 = self._clip(self.local((r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad)))
        return self.paper[y0:y1, x0:x1].mean() > .5 and self.ink[y0:y1, x0:x1].any()
