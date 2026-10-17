"""Show me: a 3Blue1Brown-style animation of the maths on screen, made with 3b1b's own manim (manimgl), in a window
you can play with: drag to move the bound, the number of rectangles, the point on the curve...

    python -m penmentor.plot JOB.json                  the window. JOB = {"rect": [x, y, w, h], "parent": pid}. It opens at once
                                                 with a loading animation; the maths comes in JOB.spec.json:
                                                 {"spec": Claude's plot} or {"error": "..."}. Only q closes it, not Esc.
    python -m penmentor.plot --png SPEC.json OUT.png   the last frame as an image (no window)
    python -m penmentor.plot --check                   build every kind once (penmentor --selftest)

Each kind below turns Claude's spec (see prompts.PLOT_KINDS) into mobjects, an intro animation, and a knob.
Runs in the Python that has manimgl (see README), not necessarily penmentor's own.
"""
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_argv, sys.argv = sys.argv, ['manimgl']  # manimlib parses the command line when it is imported
from manimlib import *  # noqa: E402,F403  (manim's own idiom)
from manimlib.window import Window  # noqa: E402
from moderngl_window.context.pyglet.window import Window as PygletWindow  # noqa: E402
sys.argv = _argv

from .expr import formula, number  # noqa: E402

# 3Blue1Brown's settings, from github.com/3b1b/videos custom_config.yml; everything else (letter and line spacing,
# Tex, sizes) stays at manim's defaults, as in his videos
manim_config.camera.background_color = '#000000'
manim_config.text.font, manim_config.text.alignment = 'CMU Serif', 'CENTER'
SPIN = '#4EA8FF'  # style.SPIN: the loader's blue
MONO = 'CMU Typewriter Text'  # 3b1b's typewriter face, fixed width: for the values you type
HINT = 'drag to explore   ·   click a value to change it   ·   scroll to zoom   ·   space replay   ·   q close'
FIELDS = ('f', 'g', 'a', 'b', 'n')  # the values you can click and retype
NAMES = {'series': {'f': 'a_n'}, 'polar': {'f': r'r(\theta)'}, 'parametric': {'f': 'x(t)', 'g': 'y(t)'},
         'substitution': {'f': 'f(u)', 'g': 'u'}, 'taylor': {'g': r'\text{term}_k'}}
VARS = {'series': {'f': ('n',)}, 'polar': {'f': ('t',)}, 'parametric': {'f': ('t',), 'g': ('t',)},
        'substitution': {'f': ('u', 'x')}, 'taylor': {'g': ('k', 'x')}}  # the variables each formula is in (default x)
WAIT = 600  # s: give up on Claude after this


def cmu_serif():
    """CMU Serif (words) and CMU Typewriter (what you type) ship with TeX Live; Pango only needs to be told where."""
    import manimpango
    for name in ('cmunrm.otf', 'cmuntt.otf'):
        if p := subprocess.run(['kpsewhich', name], capture_output=True, text=True).stdout.strip():
            manimpango.register_font(p)


# ---------- helpers ----------

def fn(s, key, names=('x',), default=None):
    src = s.get(key) or default
    if not src:
        raise ValueError(f'the plot needs "{key}"')
    f = formula(src, names)
    return lambda **kw: np.broadcast_to(np.asarray(f(**kw), float), np.shape(next(iter(kw.values()))))


def bounds(s, a=0., b=1.):
    a, b = number(s.get('a'), a), number(s.get('b'), b)
    return (a, b) if a <= b else (b, a)


def around(a, b, m=.15):
    d = (b - a) * m or 1
    return a - d, b + d


def integral(y, x):
    from scipy.integrate import cumulative_trapezoid
    return cumulative_trapezoid(np.nan_to_num(y), x, initial=0)


def step_for(span):
    """A round tick step giving about 8 ticks."""
    raw = span / 8 or 1
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)


def spread(*ys, pad=.12):
    """y from the curves (ignoring blow-ups) and 0."""
    v = np.concatenate([np.ravel(np.asarray(y, float)) for y in ys] + [np.zeros(1)])
    v = v[np.isfinite(v)]
    lo, hi = np.percentile(v, [1, 99]) if v.size > 2 else (-1, 1)
    lo, hi = min(lo, 0), max(hi, 0)
    hi = hi if hi - lo > 1e-9 else lo + 1
    return lo - (hi - lo) * pad, hi + (hi - lo) * pad


def plot_axes(x0, x1, y0, y1, width=12, height=4.8, labels=True):
    """Axes through the origin (manim draws them there), with round ticks."""
    x0, x1, y0, y1 = min(x0, 0), max(x1, 0), min(y0, 0), max(y1, 0)  # ponytail: far-off ranges get squashed; shift the origin if that matters
    sx, sy = step_for(x1 - x0), step_for(y1 - y0)
    xr = (math.floor(x0 / sx) * sx, math.ceil(x1 / sx) * sx, sx)
    yr = (math.floor(y0 / sy) * sy, math.ceil(y1 / sy) * sy, sy)
    axes = Axes(xr, yr, width=width, height=height)
    if labels:
        for axis, step in ((axes.x_axis, sx), (axes.y_axis, sy)):
            axis.add_numbers(font_size=20, excluding=[0], num_decimal_places=max(0, -math.floor(math.log10(step)))).set_opacity(.8)
    return axes


def curve(axes, xs, ys, color=BLUE, width=4):
    """The graph through (xs, ys), broken where it is undefined or leaves the axes."""
    y0, y1 = axes.y_range[:2]
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    ok = np.isfinite(ys) & (ys > y0 - (y1 - y0) * .02) & (ys < y1 + (y1 - y0) * .02)
    pts = axes.c2p(xs, np.clip(np.nan_to_num(ys), y0, y1))
    ends = np.flatnonzero(np.diff(np.r_[0, ok.astype(int), 0]))  # where the defined stretches start and stop
    return VGroup(*[VMobject().set_points_as_corners(pts[a:b]) for a, b in zip(ends[::2], ends[1::2]) if b - a > 1]).set_stroke(color, width)


def region(axes, xs, top, bottom, color=BLUE, opacity=.4):
    """Shade between two curves: blue where top is above, red where it is below (signed area)."""
    y0, y1 = axes.y_range[:2]
    top, bottom = np.clip(np.nan_to_num(top), y0, y1), np.clip(np.nan_to_num(bottom), y0, y1)
    out = VGroup()
    for hi, lo, c in ((np.maximum(top, bottom), bottom, color), (bottom, np.minimum(top, bottom), RED)):
        if len(xs) > 1 and np.any(hi - lo > 1e-12):
            pts = np.vstack([axes.c2p(xs, hi), axes.c2p(xs[::-1], lo[::-1])])
            out.add(Polygon(*pts, stroke_width=0, fill_color=c, fill_opacity=opacity))
    return out


def num(v, places=2, size=24):
    """A number as manim shows changing numbers: DecimalNumber reuses typeset digits, where Tex would run LaTeX
    (half a second) for every new value."""
    return DecimalNumber(v + 0, num_decimal_places=places, font_size=size)


def coords(x, y):
    """(x, y) the 3b1b way: Tex for the brackets (typeset once), DecimalNumbers for the values."""
    places = lambda v: 0 if abs(v - round(v)) < 5e-4 else 2
    out = VGroup(Tex('(', font_size=24), num(x, places(x)), Tex(r',', font_size=24), num(y, places(y)),
                 Tex(')', font_size=24)).arrange(RIGHT, buff=.05, aligned_edge=DOWN)
    out[3:].shift(RIGHT * .1)  # a thin space after the comma, as LaTeX sets "(x,\ y)"
    return out


def point_mark(axes, x, y, guide=True):
    """A point that matters, on top of everything: dashed guide down to the x-axis, dot, and its coordinates on a dark
    backing (3b1b style) so they read over the curves."""
    dot = Dot(axes.c2p(x, y), radius=.07, fill_color=WHITE)
    label = coords(x, y).next_to(dot, UR, buff=.08)
    line = DashedLine(axes.c2p(x, 0), axes.c2p(x, y), dash_length=.06).set_stroke(GREY_A, 2) if guide and abs(y) > 1e-9 else VGroup()
    return VGroup(line, dot, BackgroundRectangle(label, fill_opacity=.9, buff=.06), label).set_z_index(10)


def bound_marks(sc, axes, f, g, a, b):
    """The vertical lines x = a and x = b, up to the curve(s), with where they meet them; drag one to move the bound."""
    sc.live, sc.handles = {'a': a, 'b': b}, [('a', axes), ('b', axes)]

    def mark(key):
        x = sc.live[key]
        y = float(np.nan_to_num(f(x=np.array([x]))[0]))
        out = point_mark(axes, x, y)
        if g is not None:
            yg = float(np.nan_to_num(g(x=np.array([x]))[0]))
            out.add(Line(axes.c2p(x, 0), axes.c2p(x, yg)).set_stroke(GREY_A, 2), point_mark(axes, x, yg, guide=False))
        tag = Tex(key, font_size=28).set_color(YELLOW).next_to(axes.c2p(x, 0), DOWN if y >= 0 else UP, buff=.52)  # past the tick numbers
        if abs(axes.c2p(x, 0)[0] - axes.c2p(0, 0)[0]) < .3:  # on the y-axis: beside its numbers, not on them
            tag.shift(RIGHT * .3)
        return out.add(tag).set_z_index(10)
    return VGroup(*[redraw(lambda key=key: mark(key), lambda key=key: sc.live[key]) for key in ('a', 'b')])


def crossings(axes, xs, F, G, most=6, skip=()):
    """Where F and G cross (G = 0: where F meets the x-axis), marked with point_mark. Jumps (asymptotes) are not
    crossings; x's in skip already have a mark (a bound)."""
    d = np.asarray(F, float) - np.asarray(G, float)
    span = axes.y_range[1] - axes.y_range[0]
    out = VGroup()
    for i in range(len(xs) - 1):
        a, b = d[i], d[i + 1]
        if not (np.isfinite(a) and np.isfinite(b)) or a * b > 0 or a == b or abs(a - b) > span / 2:
            continue
        if a == 0 and i and d[i - 1] == 0:  # touching along a stretch: one dot is enough
            continue
        x = xs[i] - a * (xs[i + 1] - xs[i]) / (b - a)
        y = float(np.interp(x, xs, np.asarray(G, float)))
        near = (xs[-1] - xs[0]) / 60
        if out and abs(x - out[-1].x) < near or any(abs(x - v) < near for v in skip) or not axes.y_range[0] <= y <= axes.y_range[1]:
            continue
        mark = point_mark(axes, x, y)
        mark.x = x
        out.add(mark)
        if len(out) == most:
            break
    return out


def reveal(marks):
    """The marks, one after another, each settling into place. Each is animated whole: animating a part of a group
    makes manim break the group up in the scene, and a bound mark's updater (it follows your drag) would be lost."""
    return LaggedStart(*[FadeIn(m, shift=DOWN * .15, scale=1.15) for m in marks], lag_ratio=.35, run_time=.6 + .3 * len(marks))


def follow(mob, ends):
    """Keep a line (or arrow) on ends() = (start, end): moved each frame it changes, not rebuilt."""
    last = [None]

    def update(m):
        p, q = ends()
        if last[0] is None or not (np.allclose(p, last[0][0]) and np.allclose(q, last[0][1])):
            last[0] = (p, q)
            m.put_start_and_end_on(p, q + (UP * 1e-4 if np.allclose(p, q) else 0))
    return mob.add_updater(update)


def redraw(make, key):
    """Like always_redraw, but rebuilt only when key() changes (while you drag or it animates), not every frame."""
    mob, last = make(), [key()]

    def update(m):
        if (k := key()) != last[0]:
            last[0] = k
            m.become(make())
    return mob.add_updater(update)


def ticker(get, places, rate=20):
    """A DecimalNumber updater: retypesetting a number costs ~3 ms, so it changes at most `rate` times a second
    (faster than anyone reads it) and only when what it shows changes; the motion around it stays at 60 fps."""
    since = [1.]

    def update(m, dt):
        since[0] += dt
        if since[0] >= 1 / rate and round(v := float(np.nan_to_num(get())), places) != round(m.get_value(), places):
            m.set_value(v)
            since[0] = 0
    return update


def readout(*rows):
    """Live numbers in a row under the title: (tex label, getter[, decimals]), or any mobject (a coloured name)."""
    out = VGroup()
    for row in rows:
        if isinstance(row, Mobject):
            out.add(row)
            continue
        label, get, *places = row
        d = DecimalNumber(get(), num_decimal_places=places[0] if places else 3, font_size=32)
        d.add_updater(ticker(get, d.num_decimal_places))
        out.add(VGroup(Tex(label, font_size=32), d).arrange(RIGHT, buff=.15))
    return out.arrange(RIGHT, buff=.9).move_to(UP * 2.75).fix_in_frame()


def inside(m, p):
    """p within m's bounding box (on screen: x and y)."""
    (x0, y0, _), (x1, y1, _) = m.get_corner(DL), m.get_corner(UR)
    return x0 <= p[0] <= x1 and y0 <= p[1] <= y1


def frac_x(axes, p):
    return (p[0] - axes.get_left()[0]) / max(axes.get_width(), 1e-9)


def pretty(src):
    """A Python formula as LaTeX for a label: x**2/(1+x) -> x^{2}/(1+x)."""
    import re
    t = re.sub(r'\*\*\(([^()]*)\)|\*\*([\w.]+)', lambda m: '^{' + (m[1] or m[2]) + '}', src).replace('*', r'\,')
    t = re.sub(r'\bsqrt\(([^()]*)\)', r'\\sqrt{\1}', t)
    t = re.sub(r'\bfactorial\(([^()]*)\)', r'(\1)!', t)
    t = re.sub(r'\binf\b', r'\\infty', t)
    return re.sub(r'\b(exp|log|ln|sin|cos|tan|arctan|arcsin|arccos|sinh|cosh|tanh|pi)\b', r'\\\1', t)


def nonzero(src):
    return (src or '0').strip() not in ('0', '0.0')


def tex_or_text(tex, plain, **kw):
    try:
        return Tex(tex, **kw)
    except Exception:  # LaTeX choked on it
        return Text(plain, **kw)


# ---------- the kinds: each adds its mobjects, plays its intro, and sets sc.knob (ValueTracker, lo, hi, drag) ----------

def area(sc, s):
    f, g = fn(s, 'f'), fn(s, 'g', default='0')
    a, b = bounds(s)
    lo, hi = around(a, b)
    xs = np.linspace(lo, hi, 600)
    axes = plot_axes(lo, hi, *spread(f(x=xs), g(x=xs))).shift(DOWN * .4)
    graphs = VGroup(curve(axes, xs, f(x=xs)), *([curve(axes, xs, g(x=xs), YELLOW)] if nonzero(s.get('g')) else []))
    xi = np.linspace(a, b, 240)
    fi, gi = f(x=xi), g(x=xi)
    total = integral(fi - gi, xi)
    k = ValueTracker(a)
    upto = lambda: max(2, int(np.searchsorted(xi, k.get_value())) + 1)
    shade = redraw(lambda: region(axes, xi[:upto()], fi[:upto()], gi[:upto()]), upto)
    edge = follow(Line(UP, DOWN).set_stroke(YELLOW, 2.5, .9).set_z_index(8), lambda: (
        axes.c2p(k.get_value(), 0), axes.c2p(k.get_value(), float(np.nan_to_num(f(x=np.array([k.get_value()]))[0])))))
    nums = readout(('x =', k.get_value), (r'\text{area} \approx', lambda: np.interp(k.get_value(), xi, total)))
    meets = crossings(axes, xs, f(x=xs), g(x=xs), skip=(a, b))
    ends = bound_marks(sc, axes, f, g if nonzero(s.get('g')) else None, a, b)
    sc.play(ShowCreation(axes), run_time=1)
    sc.play(*map(ShowCreation, graphs), run_time=1.5)
    sc.add(shade, edge, graphs, ends)  # ends itself too: its updater moves the lines while you drag a bound
    sc.play(reveal(ends))
    sc.play(reveal(meets)) if meets else None
    sc.play(FadeIn(nums, shift=DOWN * .1))
    sc.knob, sc.zone = (k, a, b, lambda p: axes.p2c(p)[0]), axes
    sc.wait(.3)
    sc.play(k.animate.set_value(b), run_time=3)


def riemann(sc, s):
    f = fn(s, 'f')
    a, b = bounds(s)
    most = min(max(int(s.get('n') or 32), 2), 256)
    lo, hi = around(a, b, .08)
    xs = np.linspace(lo, hi, 600)
    axes = plot_axes(lo, hi, *spread(f(x=xs))).shift(DOWN * .4)
    graph = curve(axes, xs, f(x=xs))
    xi = np.linspace(a, b, 4000)
    exact = integral(f(x=xi), xi)[-1]
    k = ValueTracker(0)  # log2 of n
    n_now = lambda: max(1, round(2 ** k.get_value()))

    def bars(n=None):
        n = n or n_now()
        w = (b - a) / n
        left = a + w * np.arange(n)
        h = np.nan_to_num(f(x=left + w / 2))
        y0, y1 = axes.y_range[:2]
        out = VGroup(*[Polygon(axes.c2p(x, 0), axes.c2p(x + w, 0), axes.c2p(x + w, min(max(v, y0), y1)),
                               axes.c2p(x, min(max(v, y0), y1))) for x, v in zip(left, h)])
        out.set_submobject_colors_by_gradient(BLUE, GREEN)  # manim's own Riemann rectangles
        out.set_style(stroke_color=BLACK, stroke_width=1 if n < 64 else 0, fill_opacity=.75)
        for r_, v in zip(out, h):
            r_.set_fill(RED) if v < 0 else None
        return out
    rects = redraw(bars, n_now)
    rects.suspend_updating()
    sum_now = lambda: float(np.nan_to_num(f(x=a + (b - a) / n_now() * (np.arange(n_now()) + .5))).sum() * (b - a) / n_now())
    nums = readout(('n =', n_now, 0), (r'\text{sum} \approx', sum_now), (r'\text{exact} \approx', lambda: exact))
    meets = crossings(axes, xs, f(x=xs), 0 * xs, skip=(a, b))
    ends = bound_marks(sc, axes, f, None, a, b)
    sc.play(ShowCreation(axes), run_time=1)
    sc.play(ShowCreation(graph), run_time=1.5)
    sc.add(rects, graph, meets, ends)
    sc.play(reveal(ends))
    sc.play(reveal(meets)) if meets else None
    sc.play(FadeIn(rects, lag_ratio=.1), FadeIn(nums, shift=DOWN * .1))
    top = math.log2(most)
    for n in sorted({min(2 ** i, most) for i in range(1, math.ceil(top) + 1)}) if not sc.quick else [most]:  # each rectangle splits in two
        sc.wait(.25)
        sc.play(Transform(rects, bars(n)), k.animate.set_value(math.log2(n)), run_time=.9)
    rects.resume_updating()
    sc.knob, sc.zone = (k, 0, top, lambda p: frac_x(axes, p) * top), axes


def improper(sc, s):
    from scipy.integrate import quad
    f = fn(s, 'f')
    a, b = number(s.get('a'), 0), number(s.get('b'), np.inf)
    toward = s.get('toward') or ('a' if np.isinf(a) and not np.isinf(b) else 'b')
    if toward == 'b':
        start = a
        path = (lambda u: a + 10 ** (3 * u) - 1) if np.isinf(b) else (lambda u: b - (b - a) / 2 * 10 ** (-4 * u))
        view = (a, a + 12) if np.isinf(b) else (a, b)
    else:
        start = b
        path = (lambda u: b - 10 ** (3 * u) + 1) if np.isinf(a) else (lambda u: a + (b - a) / 2 * 10 ** (-4 * u))
        view = (b - 12, b) if np.isinf(a) else (a, b)
    point = lambda x: float(np.nan_to_num(f(x=np.array([x]))[0], posinf=0, neginf=0))
    us = np.linspace(0, 1, 160)
    ts = np.array([path(u) for u in us])
    vals = np.array([quad(point, min(start, t), max(start, t), limit=200)[0] for t in ts])
    lo, hi = around(*view, .04)
    xs = np.linspace(lo, hi, 600)
    axes = plot_axes(lo, hi, *spread(f(x=xs)), width=7.6, height=4.8).to_edge(LEFT, buff=.7).shift(DOWN * .4)
    graph = curve(axes, xs, f(x=xs))
    side = plot_axes(0, 1, *spread(vals), width=4, height=3, labels=False).to_edge(RIGHT, buff=.8).shift(DOWN * .4)
    side_title = Text('area so far', font_size=24).next_to(side, UP)
    k = ValueTracker(0)
    t_now = lambda: float(np.interp(k.get_value(), us, ts))
    upto = lambda: round(k.get_value() * 200)
    seen = lambda: min(max(t_now(), lo), hi)
    shade = redraw(lambda: region(axes, (X := np.linspace(min(start, seen()), max(start, seen()), 200)),
                                  np.clip(f(x=X), *axes.y_range[:2]), 0 * X), upto)
    trail = redraw(lambda: curve(side, us[:max(2, int(k.get_value() * 159) + 1)], vals[:max(2, int(k.get_value() * 159) + 1)],
                                 YELLOW, 3), upto)
    limit = DashedLine(side.c2p(0, vals[-1]), side.c2p(1, vals[-1]), stroke_color=GREY_B, stroke_width=1.5)
    nums = readout(('t =', t_now, 2), (r'\text{area} \approx', lambda: np.interp(k.get_value(), us, vals)))
    sc.play(ShowCreation(axes), ShowCreation(side), FadeIn(side_title), run_time=1)
    sc.play(ShowCreation(graph), ShowCreation(limit), run_time=1.5)
    sc.add(shade, graph, trail)
    sc.play(FadeIn(nums, shift=DOWN * .1))
    sc.knob, sc.zone = (k, 0, 1, lambda p: frac_x(axes, p)), axes
    sc.wait(.3)
    sc.play(k.animate.set_value(1), run_time=4.5)


def substitution(sc, s):
    f, g = fn(s, 'f', ('u', 'x')), fn(s, 'g')
    a, b = bounds(s)
    x = np.linspace(a, b, 300)
    u = g(x=x)
    h = (b - a) * 1e-5
    y0 = f(u=u, x=x) * (g(x=x + h) - g(x=x - h)) / (2 * h)  # f(g(x)) g'(x)
    y1 = f(u=u, x=x)
    both = np.concatenate([x, u])
    lo, hi = around(np.nanmin(both), np.nanmax(both), .08)
    axes = plot_axes(lo, hi, *spread(y0, y1)).shift(DOWN * .4)
    k = ValueTracker(0)
    shape = lambda: ((1 - k.get_value()) * x + k.get_value() * u, (1 - k.get_value()) * y0 + k.get_value() * y1)
    colour = lambda: interpolate_color(BLUE, YELLOW, k.get_value())
    key = lambda: round(k.get_value(), 3)
    line = redraw(lambda: curve(axes, *shape(), colour()), key)
    shade = redraw(lambda: region(axes, *shape(), 0 * x, colour(), .3), key)
    value = integral(y0, x)[-1]
    before = Tex(r"\int f(g(x))\,g'(x)\,dx", font_size=36)
    after = Tex(r'\int f(u)\,du', font_size=36)
    for t in (before, after):
        t.move_to(UP * 2.75 + LEFT * 1.6).fix_in_frame()
    before.add_updater(lambda m: m.set_opacity(1 - k.get_value()))
    after.add_updater(lambda m: m.set_opacity(k.get_value()))
    nums = readout((r'\text{area} \approx', lambda: value)).next_to(before, RIGHT, buff=.9)
    sc.play(ShowCreation(axes), run_time=1)
    sc.add(shade, line)
    sc.play(FadeIn(shade), ShowCreation(line), FadeIn(before), FadeIn(nums), run_time=1.5)
    sc.add(after)
    sc.knob, sc.zone = (k, 0, 1, lambda p: frac_x(axes, p)), axes
    sc.wait(.5)
    sc.play(k.animate.set_value(1), run_time=3.5)


def revolution(sc, s):
    f, g = fn(s, 'f'), fn(s, 'g', default='0')
    a, b = bounds(s)
    spin_y = s.get('axis') == 'y'
    x = np.linspace(a, b, 200)
    F, G = np.nan_to_num(f(x=x)), np.nan_to_num(g(x=x))
    if spin_y:  # shells: the region between the curves, at distance |x| from the axis
        vol = 2 * np.pi * integral(np.abs(x) * np.abs(F - G), x)[-1]
    else:  # washers
        vol = np.pi * integral(F ** 2 - G ** 2, x)[-1]
    m = max(np.max(np.abs(F)), np.max(np.abs(G)), np.max(np.abs(x)) if spin_y else 0, 1e-9) * 1.1
    rng = lambda lo_, hi_: (lo_, hi_, step_for(hi_ - lo_))
    axes = ThreeDAxes(rng(-m, m) if spin_y else rng(min(a, 0), max(b, 0)), rng(-m, m), rng(min(0, F.min()), m) if spin_y else rng(-m, m),
                      width=5, height=4, depth=4)
    R = lambda v: float(np.interp(v, x, F))
    r = lambda v: float(np.interp(v, x, G))
    if spin_y:
        sheet = lambda h, frac: ParametricSurface(lambda uu, vv: axes.c2p(uu * math.cos(vv), uu * math.sin(vv), h(uu)),
                                                  u_range=(a, b), v_range=(0, TAU * frac), resolution=(64, 64))
        profile = curve(axes, x, F, YELLOW).rotate(PI / 2, RIGHT, about_point=axes.c2p(0, 0, 0))
    else:
        sheet = lambda h, frac: ParametricSurface(lambda uu, vv: axes.c2p(uu, h(uu) * math.cos(vv), h(uu) * math.sin(vv)),
                                                  u_range=(a, b), v_range=(0, TAU * frac), resolution=(64, 64))
        profile = curve(axes, x, F, YELLOW)
    k = ValueTracker(.02)
    surfaces = redraw(lambda: Group(sheet(R, k.get_value()).set_color(BLUE, .55),
                                    *([sheet(r, k.get_value()).set_color(TEAL, .55)] if s.get('g') else [])),
                      lambda: round(k.get_value(), 3))
    nums = readout((r'V \approx', lambda: vol))
    sc.frame.reorient(-50, 65, 0, (0, 0, .4), 9.5)
    sc.play(ShowCreation(axes), ShowCreation(profile), FadeIn(nums), run_time=1.5)
    sc.add(surfaces)
    sc.bring_to_front(*[m for m in sc.mobjects if m.is_fixed_in_frame()])  # the title stays over the solid
    sc.knob, sc.zone = (k, .02, 1, None), None  # dragging turns the view instead, anywhere
    turn = lambda fr, dt: fr.increment_theta(dt * .1)
    sc.frame.add_updater(turn)
    sc.play(k.animate.set_value(1), run_time=4)
    sc.wait(1)
    sc.frame.remove_updater(turn)


def series(sc, s):
    t = fn(s, 'f', ('n',))
    start = int(number(s.get('a'), 1))
    count = min(max(int(s.get('n') or 25), 2), 300)
    n = np.arange(start, start + count, dtype=float)
    an = t(n=n)
    S = np.nancumsum(an)
    far = [(k_, np.nansum(t(n=np.arange(start, start + k_, dtype=float)))) for k_ in (10 ** 3, 10 ** 5)]
    top = plot_axes(n[0] - 1, n[-1] + 1, *spread(an), height=2).shift(UP * .9)
    bottom = plot_axes(n[0] - 1, n[-1] + 1, *spread(S), height=2).shift(DOWN * 1.8)
    labels = VGroup(*[Tex(t_, font_size=30).next_to(ax.y_axis.get_top(), RIGHT) for t_, ax in (('a_n', top), ('S_n', bottom))])
    k = ValueTracker(1)
    shown = lambda: int(min(max(k.get_value(), 1), count))
    bars = redraw(lambda: VGroup(*[Line(top.c2p(v, 0), top.c2p(v, np.clip(np.nan_to_num(y), *top.y_range[:2])),
                                        stroke_color=BLUE, stroke_width=6) for v, y in zip(n[:shown()], an[:shown()])]), shown)
    dots = redraw(lambda: VGroup(*[Dot(bottom.c2p(v, np.clip(np.nan_to_num(y), *bottom.y_range[:2])), radius=.05, fill_color=YELLOW)
                                   for v, y in zip(n[:shown()], S[:shown()])]), shown)
    nums = readout(('n =', lambda: n[shown() - 1], 0), (r'S_n =', lambda: S[shown() - 1]))
    tail = readout(*[(rf'S_{{{k_}}} \approx', lambda v=v: v, 5) for k_, v in far]).set_color(GREY_B).next_to(nums, DOWN, buff=.15)
    sc.play(ShowCreation(top), ShowCreation(bottom), FadeIn(labels), FadeIn(nums, shift=DOWN * .1), run_time=1.2)
    sc.add(bars, dots)
    sc.knob, sc.zone = (k, 1, count, lambda p: 1 + frac_x(top, p) * count), VGroup(top, bottom)
    sc.wait(.3)
    sc.play(k.animate.set_value(count), run_time=4.5)
    sc.play(FadeIn(tail, shift=DOWN * .1))


def taylor(sc, s):
    f, term = fn(s, 'f'), fn(s, 'g', ('k', 'x'))
    a, b = bounds(s, -3, 3)
    count = min(max(int(s.get('n') or 8), 1), 40)
    x = np.linspace(a, b, 500)
    F = f(x=x)
    P = np.nancumsum([np.nan_to_num(term(k=np.full_like(x, k_), x=x)) for k_ in range(count)], axis=0)
    axes = plot_axes(a, b, *spread(F, pad=.5)).shift(DOWN * .4)
    graph = curve(axes, x, F, BLUE, 6)
    k = ValueTracker(1)
    m_now = lambda: int(min(max(round(k.get_value()), 1), count))
    poly = lambda m: curve(axes, x, P[m - 1], YELLOW, 4)
    approx = redraw(lambda: poly(m_now()), m_now)
    approx.suspend_updating()
    nums = readout((r'\text{terms} =', m_now, 0))
    sc.play(ShowCreation(axes), run_time=1)
    sc.play(ShowCreation(graph), run_time=1.5)
    sc.add(approx)
    sc.play(ShowCreation(approx), FadeIn(nums, shift=DOWN * .1))
    for m in sorted({round(v) for v in np.linspace(1, count, 12)} - {1}):  # more terms: it bends further along the curve
        sc.wait(.2)
        sc.play(Transform(approx, poly(m)), k.animate.set_value(m), run_time=.8)
    approx.resume_updating()
    sc.knob, sc.zone = (k, 1, count, lambda p: 1 + frac_x(axes, p) * (count - 1)), axes


def trace(sc, s, xy, polar_):
    a, b = bounds(s, 0, 2 * np.pi)
    t = np.linspace(a, b, 600)
    X, Y = xy(t)
    ok = np.isfinite(X) & np.isfinite(Y)
    m = max(np.max(np.abs(X[ok])) if ok.any() else 1, np.max(np.abs(Y[ok])) if ok.any() else 1) * 1.15
    unit = min(12 / (2 * m), 5.4 / (2 * m))  # equal scales: a circle stays round
    axes = plot_axes(-m, m, -m, m, width=2 * m * unit, height=2 * m * unit).shift(DOWN * .4)
    ghost = curve(axes, X, Y, GREY_D, 2)
    swept = integral(.5 * (X ** 2 + Y ** 2), t) if polar_ else integral(np.hypot(np.gradient(X, t), np.gradient(Y, t)), t)
    k = ValueTracker(0)
    i_now = lambda: int(min(max(k.get_value(), 0), 1) * (len(t) - 1))
    path = redraw(lambda: curve(axes, X[:i_now() + 2], Y[:i_now() + 2], BLUE, 4), i_now)
    head = lambda: axes.c2p(np.nan_to_num(X[i_now()]), np.nan_to_num(Y[i_now()]))
    dot = Dot(head(), radius=.08, fill_color=YELLOW).set_z_index(8).add_updater(lambda m: m.move_to(head()))
    if polar_:
        arm = follow(Line(LEFT, RIGHT).set_stroke(YELLOW, 3), lambda: (axes.c2p(0, 0), head()))
        fan = redraw(lambda: Polygon(axes.c2p(0, 0), *axes.c2p(np.nan_to_num(X[:i_now() + 2]), np.nan_to_num(Y[:i_now() + 2])),
                                     stroke_width=0, fill_color=BLUE, fill_opacity=.25), i_now)
        nums = readout((r'\theta =', lambda: t[i_now()]), (r'\text{area} \approx', lambda: swept[i_now()]))
    else:
        dX, dY = np.gradient(X, t), np.gradient(Y, t)
        sc_ = lambda i: m * .25 / (math.hypot(dX[i], dY[i]) or 1)
        arm = follow(Arrow(LEFT, RIGHT, buff=0).set_color(YELLOW), lambda: (
            head(), axes.c2p(X[i_now()] + dX[i_now()] * sc_(i_now()), Y[i_now()] + dY[i_now()] * sc_(i_now()))))
        fan = VGroup()
        nums = readout(('t =', lambda: t[i_now()]), (r'\text{length} \approx', lambda: swept[i_now()]))

    def nearest(p):  # drag the point along the curve
        px, py = axes.p2c(p)[:2]
        return float(np.nanargmin((X - px) ** 2 + (Y - py) ** 2)) / (len(t) - 1)
    sc.play(ShowCreation(axes), ShowCreation(ghost), run_time=1.2)
    sc.add(fan, path, arm, dot)
    sc.play(FadeIn(nums, shift=DOWN * .1), GrowFromCenter(dot))
    sc.knob, sc.zone = (k, 0, 1, nearest), axes
    sc.wait(.3)
    sc.play(k.animate.set_value(1), run_time=5)


def polar(sc, s):
    r = fn(s, 'f', ('t',))
    return trace(sc, s, lambda t: (r(t=t) * np.cos(t), r(t=t) * np.sin(t)), True)


def parametric(sc, s):
    fx, fy = fn(s, 'f', ('t',)), fn(s, 'g', ('t',))
    return trace(sc, s, lambda t: (fx(t=t), fy(t=t)), False)


def curves(sc, s):
    f, g = fn(s, 'f'), fn(s, 'g', default='0')
    a, b = bounds(s)
    x = np.linspace(a, b, 600)
    F, G = f(x=x), g(x=x)
    axes = plot_axes(a, b, *spread(F, G)).shift(DOWN * .4)
    cf, cg = curve(axes, x, F), curve(axes, x, G, YELLOW)
    names = VGroup(tex_or_text(pretty(s['f']), s['f'], font_size=30).set_color(BLUE),
                   tex_or_text(pretty(s.get('g') or '0'), s.get('g') or '0', font_size=30).set_color(YELLOW))
    between = region(axes, x[::3], F[::3], G[::3], BLUE, .15)
    k = ValueTracker(a)
    at = lambda: (k.get_value(), float(np.interp(k.get_value(), x, np.nan_to_num(F))), float(np.interp(k.get_value(), x, np.nan_to_num(G))))
    cut = follow(Line(UP, DOWN).set_stroke(WHITE, 3).set_z_index(8), lambda: (axes.c2p(at()[0], at()[2]), axes.c2p(at()[0], at()[1])))
    nums = readout(*names, ('x =', lambda: at()[0]), (r'f(x) - g(x) =', lambda: at()[1] - at()[2]))
    meets = crossings(axes, x, F, G)
    sc.play(ShowCreation(axes), run_time=1)
    sc.play(ShowCreation(cf), ShowCreation(cg), run_time=2)
    sc.add(between, cf, cg, meets)
    sc.play(FadeIn(between), FadeIn(nums, shift=DOWN * .1))
    sc.play(reveal(meets)) if meets else None
    sc.play(ShowCreation(cut))
    sc.knob, sc.zone = (k, a, b, lambda p: axes.p2c(p)[0]), axes
    sc.wait(.3)
    sc.play(k.animate.set_value(b), run_time=3.5)


KINDS = dict(area=area, riemann=riemann, improper=improper, substitution=substitution, revolution=revolution,
             series=series, taylor=taylor, polar=polar, parametric=parametric, curves=curves)


class Field:
    """The value you are typing: its text, the caret and the selection (anchor..caret), edited like any text box."""

    def __init__(self, key, text, now):
        self.key, self.text = key, text
        self.anchor, self.caret = 0, len(text)  # all selected at first: typing replaces it, an arrow keeps it
        self.touched, self.clicked, self.geom = now, -1, (0, 1)

    def span(self):
        return None if self.anchor is None or self.anchor == self.caret else tuple(sorted((self.anchor, self.caret)))

    def selected(self):
        lo, hi = self.span()
        return self.text[lo:hi]

    def insert(self, t):
        if sel := self.span():
            self.text, self.caret = self.text[:sel[0]] + self.text[sel[1]:], sel[0]
        self.text = self.text[:self.caret] + t + self.text[self.caret:]
        self.caret, self.anchor = self.caret + len(t), None

    def move(self, motion, select):
        """A pyglet text motion: arrows, Ctrl+arrows (a word), Home/End, Backspace/Delete; select: with Shift."""
        import re
        from pyglet.window import key
        if motion in (key.MOTION_BACKSPACE, key.MOTION_DELETE):
            if not self.span():
                c = self.caret
                self.anchor, self.caret = (c, max(c - 1, 0)) if motion == key.MOTION_BACKSPACE else (c, min(c + 1, len(self.text)))
            return self.insert('')
        sel = self.span()
        if select and self.anchor is None:
            self.anchor = self.caret
        c, n = self.caret, len(self.text)
        words = [m.start() for m in re.finditer(r'\w+', self.text)] + [n]
        if not select and sel and motion in (key.MOTION_LEFT, key.MOTION_RIGHT):
            c = sel[0] if motion == key.MOTION_LEFT else sel[1]  # an arrow on a selection lands at its end
        else:
            c = {key.MOTION_LEFT: c - 1, key.MOTION_RIGHT: c + 1, key.MOTION_BEGINNING_OF_LINE: 0, key.MOTION_END_OF_LINE: n,
                 key.MOTION_BEGINNING_OF_FILE: 0, key.MOTION_END_OF_FILE: n,
                 key.MOTION_PREVIOUS_WORD: max([w for w in words if w < c] or [0]),
                 key.MOTION_NEXT_WORD: min([w for w in words if w > c] or [n])}.get(motion, c)
        self.caret = min(max(c, 0), n)
        if not select:
            self.anchor = None


# ---------- the scene and its window ----------

class Show(Scene):
    """Loading animation until the maths arrives, then the kind's intro, then yours to play with."""
    drag_to_pan = False  # dragging moves the knob; scroll still zooms

    def __str__(self):
        return 'penmentor · show me'  # the window title

    def __init__(self, spec=None, job=None, **kw):
        self.spec, self.job, self.knob, self.again, self.goal = spec, job, None, False, None
        self.zone, self.handles, self.live, self.values = None, [], {}, VGroup()
        self.editing, self.dragging, self.hand, self.quick, self.reopen, self.selecting = None, None, False, False, None, False
        super().__init__(**kw)
        self.preview_while_skipping = False  # a redraw after you change a value shows only when it is complete
        if self.window:
            self.camera.fps = 60  # manimgl caps its window at 30
            # manimgl measures its window once (as 1280x720) and sizes line edges by that: use the real size
            c = self.camera
            c.get_pixel_shape = lambda: tuple(c.window_fbo.viewport[2:]) if c.fbo is c.window_fbo else c.fbo.size

    def construct(self):
        if self.spec is None:
            self.spec = self.wait_for_maths()
        self.build()

    def wait_for_maths(self):
        # the same loader as penmentor's top badge: a faint ring, and a blue arc turning round its centre as it stretches and shrinks
        centre, t0 = UP * .5, self.time
        ring = Circle(radius=.4).move_to(centre).set_stroke(WHITE, 5, opacity=.15)
        arc = always_redraw(lambda: Arc(-(self.time - t0) * 330 * DEG, (40 + 230 * (.5 - .5 * math.cos((self.time - t0) * 4))) * DEG,
                                        radius=.4, arc_center=centre).set_stroke(SPIN, 5))
        word = Text('Drawing your animation', font_size=36).set_color(GREY_A).next_to(ring, DOWN, buff=.6)
        self.add(ring, arc)
        self.play(FadeIn(word), run_time=.4)
        spec_file, parent, end = Path(self.job['path']).with_suffix('.spec.json'), self.job.get('parent'), time.monotonic() + WAIT
        while not spec_file.exists():
            if (parent and os.getppid() != parent) or time.monotonic() > end:  # penmentor stopped (Esc) before Claude answered
                break
            self.wait(.1)
        got = json.loads(spec_file.read_text()) if spec_file.exists() else {'error': 'Stopped before Claude answered.'}
        arc.clear_updaters()
        self.play(FadeOut(VGroup(ring, arc, word)), run_time=.4)
        return got.get('spec') or {'error': got.get('error') or 'no animation this time'}

    def build(self):
        """Title, the kind (its intro unless self.quick: after you change a value it just redraws), values row, hint."""
        self.knob, self.zone, self.handles, s = None, None, [], self.spec
        skipping = self.skip_animations
        self.skip_animations = skipping or self.quick
        try:
            if 'error' in s:
                raise ValueError(s['error'])
            if s.get('title'):
                try:
                    title = TexText(s['title'])
                except Exception:  # LaTeX choked on Claude's title
                    title = Text(s['title'].replace('$', ''))
                title.set_max_width(FRAME_WIDTH - 1).to_edge(UP, buff=.35).fix_in_frame()
                # written on slowly, in the background, while the plot draws itself
                self.add(title if self.skip_animations else turn_animation_into_updater(Write(title, run_time=3.5, lag_ratio=.15)))
            KINDS[s.get('kind')](self, s)
            self.goal = self.knob[0].get_value() if self.knob else None
            self.values = self.values_row(s)
            self.place_row()
            self.play(FadeIn(self.values, shift=UP * .1), FadeIn(Text(HINT, font_size=20).set_color(GREY_B).to_edge(DOWN, buff=.2).fix_in_frame()))
            self.reopen_now()  # you were stepping or tabbing: the field stays open
        except EndScene:
            raise
        except Exception as ex:
            self.clear().add(self.frame)
            self.values = VGroup()
            self.add(VGroup(Text("Couldn't draw this one"), Text(str(ex)[:120], font_size=24).set_color(GREY_B))
                     .arrange(DOWN, buff=.4).fix_in_frame(), Text('q close', font_size=20).set_color(GREY_B).to_edge(DOWN, buff=.2))
        finally:
            self.skip_animations, self.quick = skipping, False

    @property
    def char_w(self):
        """Width of one character of the typewriter face."""
        if not hasattr(self, '_char_w'):
            self._char_w = Text('0' * 40, font=MONO, font_size=24).get_width() / 40
        return self._char_w

    def chip(self, key):
        """One value in the row, as maths: "a = 0", "f(x) = x e^{-x}"."""
        s = self.spec
        name = NAMES.get(s.get('kind'), {}).get(key, {'f': 'f(x)', 'g': 'g(x)'}.get(key, key))
        text = str(s[key])
        if re.fullmatch(r'-?\d+(\.\d+)?', text):  # a plain number: digits that are typeset already, no LaTeX run
            body = VGroup(Tex(f'{name} =', font_size=26), num(float(text), len(text.partition('.')[2]), 26)).arrange(RIGHT, buff=.12)
        else:
            body = tex_or_text(rf'{name} = {pretty(text)}', f'{key} = {text}', font_size=26)
        box = RoundedRectangle(width=body.get_width() + .36, height=max(body.get_height(), .3) + .22, corner_radius=.1)
        chip = VGroup(box.set_stroke(GREY_C, 1.5).set_fill(BLACK, .85).move_to(body), body)
        chip.key = key
        return chip.set_z_index(12).fix_in_frame()

    def field_chip(self, colour=YELLOW):
        """The value you are typing, in CMU Typewriter (fixed width, so the caret and selection line up exactly):
        "b = 2.5" with a blinking caret and the selection shaded."""
        f, cw = self.editing, self.char_w
        prefix = f'{f.key} = '
        text = Text(prefix + f.text, font=MONO, font_size=24)
        left, y = text.get_left()[0], text.get_center()[1]
        at = lambda i: left + (len(prefix) + i) * cw
        f.geom = (left + len(prefix) * cw, cw)  # where the text starts, for clicks
        width = (len(prefix) + len(f.text) + 1) * cw
        box = RoundedRectangle(width=width + .36, height=.52, corner_radius=.1).set_stroke(colour, 2).set_fill(BLACK, .9)
        box.move_to([left + width / 2, y, 0])
        chip = VGroup(box)
        if sel := f.span():
            chip.add(Rectangle(width=(sel[1] - sel[0]) * cw, height=.36).set_stroke(width=0).set_fill(BLUE_D, .85)
                     .move_to([(at(sel[0]) + at(sel[1])) / 2, y, 0]))
        caret = Line(UP * .17, DOWN * .17).set_stroke(WHITE, 2).move_to([at(f.caret), y, 0])
        caret.add_updater(lambda m: m.set_opacity(1 if (self.time - f.touched) % 1.06 < .6 else 0))  # blinks, steady while typing
        chip.add(text, caret)
        chip.key = f.key
        return chip.set_z_index(12).fix_in_frame()

    def values_row(self, s):
        keys = [k for k in FIELDS if s.get(k) not in (None, '') and not (k == 'g' and s.get('kind') == 'area' and not nonzero(s[k]))]
        return VGroup(*[self.chip(k) for k in keys])

    def place_row(self):
        self.values.arrange(RIGHT, buff=.3).move_to(DOWN * 3.3)

    def play(self, *animations, **kw):
        """After you change a value the plot is rebuilt with no intro: every animation lands on its end at once,
        without manim copying each shape to animate it (60% of a rebuild)."""
        if not self.quick:
            return super().play(*animations, **kw)
        for a in animations:
            self.land(a)

    def land(self, a):
        from manimlib.mobject.mobject import _AnimationBuilder
        if isinstance(a, _AnimationBuilder):  # tracker.animate.set_value(...): cheap, let manim do it
            super().play(a)
        elif isinstance(a, AnimationGroup):
            for part in a.animations:
                self.land(part)
        elif type(a) in (Transform, ReplacementTransform):
            a.mobject.become(a.target_mobject)
            self.add(a.mobject)
        elif isinstance(a, FadeOut):
            self.remove(a.mobject)
        else:  # ShowCreation, FadeIn, Write, GrowFromCenter...: the mobject as built is the end state
            self.add(a.mobject)

    def wait(self, *args, **kw):
        return None if self.quick else super().wait(*args, **kw)

    def interact(self):
        self.skip_animations = False
        while not self.is_window_closing():
            if self.again:
                self.again = False
                self.clear().add(self.frame)
                if not self.quick:
                    self.frame.to_default_state()
                self.build()
            if self.knob and self.goal is not None:  # glide toward where you put it, quick then settling, like a hand
                k = self.knob[0]
                k.set_value(k.get_value() + (self.goal - k.get_value()) * (1 - math.exp(-14 / self.camera.fps)))
            self.update_frame(1 / self.camera.fps)

    # --- changing a value: retype it, step it, or drag a bound line ---
    def chip_at(self, point):
        fixed = self.frame.to_fixed_frame_point(point)  # the row is fixed in the frame (it stays put in 3D)
        return next((c for c in self.values if inside(c, fixed)), None)

    def handle_at(self, point):
        return next((key for key, axes in self.handles
                     if abs(point[0] - axes.c2p(self.live[key], 0)[0]) < .22 and inside(axes, point)), None)

    def change(self, key, text):
        """The spec with key = text, if it makes sense (a formula in the right variables, a number), else None."""
        try:
            if key in ('f', 'g'):
                formula(text, VARS.get(self.spec.get('kind'), {}).get(key, ('x',)))
            elif key == 'n':
                text = max(1, int(float(text)))
            else:
                number(text)
        except (ValueError, SyntaxError, TypeError, OverflowError):
            return None
        return dict(self.spec, **{key: text})

    def redraw_with(self, spec, keep_typing=False):
        """Your change: draw it at once (no intro) and keep it in the history. keep_typing: the field stays open."""
        self.spec, self.quick, self.again = spec, True, True
        self.reopen = self.editing if keep_typing else None
        try:
            from .show import remember
            remember(spec)
        except Exception:  # the history is a nicety
            pass

    def edit(self, key):
        self.editing = Field(key, str(self.spec[key]), self.time)
        self.show_edit()

    def show_edit(self, colour=YELLOW):
        self.editing.touched = self.time
        i = next(i for i, c in enumerate(self.values) if c.key == self.editing.key)
        self.remove(self.values)
        self.values.replace_submobject(i, self.field_chip(colour))
        self.place_row()
        self.add(self.values)

    def end_edit(self, commit, then=None):
        """commit: use the value (Enter, Tab, clicking elsewhere); one that makes no sense turns red and stays open.
        Not commit: Esc, back as it was. then: the key to type in next (Tab)."""
        f = self.editing
        spec = self.change(f.key, f.text.strip()) if commit else self.spec
        if spec is None:
            self.show_edit(RED)
            return False
        self.editing = None
        i = next(i for i, c in enumerate(self.values) if c.key == f.key)
        self.remove(self.values)
        self.values.replace_submobject(i, self.chip(f.key))  # back to maths
        self.place_row()
        self.add(self.values)
        if spec != self.spec:
            self.redraw_with(spec)
        if then:
            self.reopen = Field(then, str(spec[then]), self.time)
            if spec == self.spec:
                self.reopen_now()
        return True

    def reopen_now(self):
        """After a redraw: the field you were in (stepping, Tab) is open again, caret where it was."""
        if self.reopen:
            self.editing, self.reopen = self.reopen, None
        if self.editing and any(c.key == self.editing.key for c in self.values):
            self.show_edit()
        else:
            self.editing = None

    def step(self, direction, big):
        """Up/Down on a number: one step up or down (Shift: ten), redrawn at once."""
        f = self.editing
        if f.key not in ('a', 'b', 'n'):
            return
        try:
            v = number(f.text)
        except ValueError:
            return
        d = (1 if f.key == 'n' else .1) * (10 if big else 1) * direction
        f.text = str(int(max(1, v + d))) if f.key == 'n' else f'{v + d:.10g}'
        f.caret, f.anchor = len(f.text), None
        if spec := self.change(f.key, f.text):
            self.redraw_with(spec, keep_typing=True)
        self.show_edit()

    def on_text(self, text):
        if self.editing and text.isprintable():
            self.editing.insert(text)
            self.show_edit()

    def on_text_motion(self, motion, select=False):
        from pyglet.window import key
        f = self.editing
        if not f:
            return
        if motion in (key.MOTION_UP, key.MOTION_DOWN):
            return self.step(1 if motion == key.MOTION_UP else -1, select)
        if motion == key.MOTION_COPY:
            return f.span() and self.window._window.set_clipboard_text(f.selected())
        if motion == key.MOTION_PASTE:
            f.insert(' '.join(self.window._window.get_clipboard_text().split()))
        else:
            f.move(motion, select)
        self.show_edit()

    def on_escape(self):
        if self.editing:
            self.end_edit(False)

    # --- the pen and the keys ---
    def turn(self, point):
        if self.knob and self.knob[3]:
            k, lo, hi, at = self.knob
            self.goal = min(max(at(point), lo), hi)

    def on_mouse_motion(self, point, d_point):
        super().on_mouse_motion(point, d_point)
        grab = self.chip_at(point) or self.handle_at(point) or self.dragging or (
            self.knob and (self.zone is None or inside(self.zone, point)))
        if bool(grab) != self.hand and self.window:  # a hand wherever you can drag or click
            w = self.window._window
            w.set_mouse_cursor(w.get_system_mouse_cursor(w.CURSOR_HAND) if grab else None)
            self.hand = bool(grab)

    def on_mouse_press(self, point, button, mods):
        super().on_mouse_press(point, button, mods)
        chip = self.chip_at(point)
        if self.editing and chip and chip.key == self.editing.key:  # in the field: place the caret, double-click selects all
            f, x = self.editing, self.frame.to_fixed_frame_point(point)[0]
            again = self.time - f.clicked < .4
            f.clicked = self.time
            f.caret = f.anchor = min(max(round((x - f.geom[0]) / f.geom[1]), 0), len(f.text))
            if again:
                f.anchor, f.caret = 0, len(f.text)
            self.selecting = True
            return self.show_edit()
        if self.editing and not self.end_edit(True) and self.editing:  # clicking elsewhere uses the value; nonsense stays
            return
        if chip:
            return self.edit(chip.key)
        if key := self.handle_at(point):
            self.dragging = key
            return
        self.turn(point)

    def on_mouse_drag(self, point, d_point, buttons, modifiers):
        super().on_mouse_drag(point, d_point, buttons, modifiers)
        if self.selecting and self.editing:  # drag across the text to select
            f = self.editing
            f.caret = min(max(round((self.frame.to_fixed_frame_point(point)[0] - f.geom[0]) / f.geom[1]), 0), len(f.text))
            self.show_edit()
        elif self.dragging:
            axes = dict(self.handles)[self.dragging]
            lo, hi = axes.x_range[:2]
            if self.dragging == 'a':
                hi = self.live['b'] - (hi - lo) / 100
            else:
                lo = self.live['a'] + (hi - lo) / 100
            self.live[self.dragging] = min(max(axes.p2c(point)[0], lo), hi)
        elif self.knob and self.knob[3] is None:  # 3D: drag turns the view
            self.frame.increment_theta(-d_point[0] * .4)
            self.frame.increment_phi(d_point[1] * .4)
        else:
            self.turn(point)

    def on_mouse_release(self, point, button, mods):
        super().on_mouse_release(point, button, mods)
        self.selecting = False
        if key := self.dragging:
            self.dragging = None
            self.redraw_with(dict(self.spec, **{key: f'{self.live[key]:.3g}'}))

    def on_mouse_scroll(self, point, offset, x_pixel_offset, y_pixel_offset):
        """Over a number: scroll steps it. Elsewhere: zoom."""
        chip = self.chip_at(point)
        if chip and chip.key in ('a', 'b', 'n'):
            if not (self.editing and self.editing.key == chip.key):
                if self.editing and not self.end_edit(True):
                    return
                self.edit(chip.key)
            return self.step(1 if y_pixel_offset > 0 else -1, False)
        super().on_mouse_scroll(point, offset, x_pixel_offset, y_pixel_offset)

    def on_key_press(self, symbol, modifiers):
        from pyglet.window import key
        if self.editing:  # typing a value: keys are for the text (motions, Esc and characters come separately)
            f, ctrl = self.editing, modifiers & key.MOD_CTRL
            if symbol in (key.RETURN, key.ENTER):
                self.end_edit(True)
            elif symbol == key.TAB:  # the next value (Shift: the previous one)
                keys = [c.key for c in self.values]
                self.end_edit(True, then=keys[(keys.index(f.key) + (-1 if modifiers & key.MOD_SHIFT else 1)) % len(keys)])
            elif ctrl and symbol == key.A:
                f.anchor, f.caret = 0, len(f.text)
                self.show_edit()
            elif ctrl and symbol == key.X and f.span():
                self.window._window.set_clipboard_text(f.selected())
                f.insert('')
                self.show_edit()
        elif symbol == key.SPACE:
            self.again = True
        elif symbol == key.Q:  # not Esc: Esc is for penmentor, and this stays until you are done with it
            self.quit_interaction = True
        elif symbol in (key.LEFT, key.RIGHT) and self.knob:
            k, lo, hi, _ = self.knob
            self.goal = min(max((self.goal if self.goal is not None else k.get_value()) + (hi - lo) / 40 * (1 if symbol == key.RIGHT else -1), lo), hi)
        else:
            super().on_key_press(symbol, modifiers)


class QuietWindow(Window):
    """manimgl's window, opened as a floating dialog that doesn't take the focus (your pen stays in xournal),
    where penmentor put it (the overlay leaves that spot uncovered)."""

    def __init__(self, rect):
        x, y, w, h = rect
        self.scene, self.pressed_keys = None, set()
        self.default_size, self.default_position = (w, h), (x, y)
        # 4x multisampling: smooth edges, 3D too. aspect_ratio: resizing never squashes the picture, it stays 16:9 in the
        # middle (the bars are black, like the background). Invisible at first, so the hints are set before i3 sees it.
        PygletWindow.__init__(self, samples=4, visible=False, aspect_ratio=16 / 9)
        self.exit_key = None  # moderngl_window closes on Esc by default, and so does pyglet underneath it: stop Esc here
        from pyglet.window import key  # (it only cancels typing a value), and pass typed text to the scene

        def esc(symbol, mods):
            if symbol == key.ESCAPE:
                self.scene and self.scene.on_escape()
                return True
        self._window.push_handlers(on_key_press=esc, on_text=lambda text: self.scene and self.scene.on_text(text),
                                   on_text_motion=lambda m: self.scene and self.scene.on_text_motion(m),
                                   on_text_motion_select=lambda m: self.scene and self.scene.on_text_motion(m, True))
        win = self._window
        win.set_caption('penmentor · show me')
        win._set_atoms_property('_NET_WM_WINDOW_TYPE', ('_NET_WM_WINDOW_TYPE_DIALOG',))  # i3 floats dialogs
        from ctypes import POINTER, byref, c_ubyte, c_ulong, cast
        from pyglet.libs.x11 import xlib
        atom = lambda name: xlib.XInternAtom(win._x_display, name.encode(), False)
        zero = c_ulong(0)  # user time 0: don't focus it
        xlib.XChangeProperty(win._x_display, win._window, atom('_NET_WM_USER_TIME'), atom('CARDINAL'), 32,
                             xlib.PropModeReplace, cast(byref(zero), POINTER(c_ubyte)), 1)
        self.to_default_position()
        win.set_visible(True)
        # i3 opens floating windows on the focused screen: move it to the one we want (no-op elsewhere)
        subprocess.run(['i3-msg', f'[id={win._window}] move absolute position {self.default_position[0]} {self.default_position[1]}'],
                       capture_output=True)

    def pixel_coords_to_space_coords(self, px, py, relative=False):
        """Window pixels to scene coordinates, through the 16:9 area (manimgl's own version assumes the whole window)."""
        if self.scene is None or not hasattr(self.scene, 'frame'):
            return np.zeros(3)
        vx, vy, vw, vh = self.viewport
        coords = np.zeros(3)
        coords[:2] = np.array(FRAME_SHAPE) / (vw, vh) * ((px, py) if relative else (px - vx, py - vy))
        if not relative:
            coords[:2] -= .5 * np.array(FRAME_SHAPE)
        return self.scene.frame.from_fixed_frame_point(coords, relative)


def render(spec, out=None):
    """Build spec with no window; the last frame to out (a PNG)."""
    scene = Show(spec=spec, skip_animations=True)
    scene.setup()
    scene.construct()
    scene.update_frame(force_draw=True)  # skipping animations draws nothing by itself
    if out:
        scene.get_image().save(out)
    return scene


def check():
    """Every kind builds without errors, and a hostile formula is refused (shown as a message, not run)."""
    specs = [dict(kind='area', f='x*exp(-x)', g='0', a='0', b='4'), dict(kind='riemann', f='sin(x)', a='0', b='pi', n=20),
             dict(kind='improper', f='1/x**2', a='1', b='inf'), dict(kind='improper', f='1/sqrt(x)', a='0', b='1', toward='a'),
             dict(kind='substitution', f='cos(u)', g='x**2', a='0', b='1'), dict(kind='revolution', f='sqrt(x)', a='0', b='4'),
             dict(kind='revolution', f='x*(2-x)', a='0', b='2', axis='y'), dict(kind='series', f='1/n**2', a='1', n=20),
             dict(kind='taylor', f='exp(x)', g='x**k/factorial(k)', a='-2', b='2', n=6), dict(kind='polar', f='1+cos(t)', a='0', b='2*pi'),
             dict(kind='parametric', f='cos(t)', g='sin(2*t)', a='0', b='2*pi'), dict(kind='curves', f='1/x**2', g='1/(x**2+1)', a='1', b='5', title='Two $1/x$ curves')]
    assert {s['kind'] for s in specs} == set(KINDS)
    for spec in specs + [dict(kind='area', f="__import__('os')", a='0', b='1')]:
        scene = render(spec)
        failed = any(isinstance(m, VGroup) and len(m) == 2 and isinstance(m[0], Text) and m[0].text == "Couldn't draw this one"
                     for m in scene.mobjects)
        assert failed == spec['f'].startswith('__'), spec
        assert spec['f'].startswith('__') or scene.knob, spec
    # retyping a value: sensible text gives a new spec, nonsense (or code) gives none
    scene = render(specs[0])
    assert scene.change('b', 'pi')['b'] == 'pi' and scene.change('n', '12') and scene.change('f', 'x**2 + 1')
    assert not scene.change('a', 'zero') and not scene.change('f', "__import__('os')") and not scene.change('f', 'y + 1')
    assert [c.key for c in scene.values] == ['f', 'a', 'b']  # g = 0 is not worth a chip
    from pyglet.window import key
    f = Field('f', 'x*exp(-x)', 0)
    f.insert('sin(x)')  # all selected at first: typing replaces it
    assert (f.text, f.caret) == ('sin(x)', 6)
    f.move(key.MOTION_LEFT, False), f.move(key.MOTION_LEFT, True), f.move(key.MOTION_LEFT, True)  # Shift+Left twice: '(x'
    assert f.selected() == '(x'
    f.insert('^2(x')
    f.move(key.MOTION_BEGINNING_OF_LINE, False), f.move(key.MOTION_DELETE, False), f.move(key.MOTION_NEXT_WORD, False)
    assert (f.text, f.caret) == ('in^2(x)', 3), (f.text, f.caret)  # Ctrl+Right: the start of the next word
    f.move(key.MOTION_END_OF_LINE, False), f.move(key.MOTION_BACKSPACE, False)
    assert f.text == 'in^2(x'
    scene.edit('b')  # Up on a number steps it and redraws, the field stays open
    scene.step(1, False)
    assert scene.spec['b'] == '4.1' and scene.reopen is scene.editing
    print('plots ok')


def main(argv):
    cmu_serif()
    if argv[:1] == ['--check']:
        return check()
    if argv[:1] == ['--png']:
        return render(json.loads(Path(argv[1]).read_text()), argv[2])
    job = dict(json.loads(Path(argv[0]).read_text()), path=argv[0])
    Show(job=job, window=QuietWindow(job.get('rect') or (160, 90, 1600, 900))).run()


if __name__ == '__main__':
    main(sys.argv[1:])
