"""penmentor --selftest: the logic that is easy to break, checked without Claude or a real screen."""
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np


def pages():
    from .page import Page
    rgb = np.zeros((300, 600, 3), np.uint8)
    rgb[100:140, 200:230] = 255  # a symbol
    rgb[100:140, 300:330] = 255  # its neighbour
    pg = Page(rgb)
    assert pg.dark
    assert pg.snap((190, 95, 240, 150)) == (200, 100, 230, 140)  # loose box tightens
    assert pg.snap((205, 104, 236, 138)) == (200, 100, 230, 140)  # offset box still finds the whole symbol
    assert pg.snap((150, 200, 180, 230)) == (150, 200, 180, 230)  # no ink: box kept
    r = pg.place((80, 30), (200, 100, 230, 140), [])
    assert not pg.busy(r, []), r
    assert pg.busy((290, 110, 320, 120), [])  # on ink
    side = np.zeros((300, 600, 3), np.uint8)
    side[:, 100:115] = 53  # a sidebar frame: black inside, like the paper
    side[:20] = 53  # a toolbar
    ps = Page(side)
    assert ps.busy((10, 100, 60, 130), [], ink=False)  # inside the sidebar
    assert ps.busy((200, 5, 260, 30), [], ink=False)  # on the toolbar
    assert not ps.busy((200, 100, 260, 130), [], ink=False)  # on the page
    x0, y0, x1, y1 = ps.place((60, 30), (120, 100, 140, 130), [])
    assert x0 >= 115 and y0 >= 20, (x0, y0)
    full = [(0, 0, 600, 300)]  # no room anywhere: the note still lands on screen
    for target in ((560, 10, 598, 40), (2, 260, 40, 298)):
        x0, y0, x1, y1 = pg.place((200, 40), target, full)
        assert 0 <= x0 and x1 <= 600 and 0 <= y0 and y1 <= 300, (target, x0, y0, x1, y1)
    po = Page(rgb, (1000, 50))  # same page, placed further along the desktop
    assert po.snap((1190, 145, 1240, 200)) == (1200, 150, 1230, 190)
    assert po.busy((1290, 160, 1320, 170), []) and not po.busy(po.place((80, 30), (1200, 150, 1230, 190), []), [])
    assert po.fit((900, 0, 960, 30)) == (1006, 56, 1066, 86)


def text():
    from . import typeset
    from .typeset import latex_source, plain, tex_source, typeset as run_latex
    for raw, want in ((r'$a \iff b \le c \ge d$', r'$a \Leftrightarrow b \leq c \geq d$'),
                      (r'$\frac{3}{2}\left[$', r'$\dfrac{3}{2}[$'),
                      (r'$\left(\tfrac{1}{2}\right)$', r'$\left(\dfrac{1}{2}\right)$'),
                      (r'use x^2 and \sqrt{x} here', r'use $x^2$ and $\sqrt{x}$ here'),
                      (r'angle with $\sin\theta=1$?', r'angle with $\sin\theta=1$?'),
                      ('odd $ count x^2', 'odd  count $x^2$'), ('plain words', 'plain words'),
                      ('arcsin(y) is the angle whose sine is y.', r'$\arcsin(y)$ is the angle whose sine is $y$.'),
                      ('take ln of both sides, then dx', r'take $\ln$ of both sides, then $dx$'),
                      ('e.g. a sign slip (not yours)', 'e.g. a sign slip (not yours)'),
                      ('so arcsin(1) = ?', r'so $\arcsin(1) =$ ?'), (r'$\theta=arcsin(x)$', r'$\theta=\arcsin(x)$')):
        assert tex_source(raw) == want, (raw, tex_source(raw))
    assert plain(r'$\dfrac{\pi}{2} \cdot x$') == '(π)/(2) ⋅ x', plain(r'$\dfrac{\pi}{2} \cdot x$')
    assert latex_source('θ ≤ 1, 50% done') == r'$\theta  \leq  1$, $50\%$ done', latex_source('θ ≤ 1, 50% done')
    if typeset.LATEX:
        ks = [(r'$\iff$ ok', 19), (r'$\nosuchcmd x$', 19), (r'$\frac{1}{2$', 19), (r'$|x|=\begin{cases}x\\-x\end{cases}$', 19)]
        run_latex(ks)
        assert [typeset._typeset[k] is not None for k in ks] == [True, False, False, True], [typeset._typeset[k] for k in ks]
        assert typeset._typeset[ks[3]].height() > typeset._typeset[ks[0]].height()  # the cases page really is the cases page


def desktop():
    from .desktop import windows
    tree = {'type': 'root', 'nodes': [{'type': 'output', 'nodes': [
        {'type': 'con', 'name': 'content', 'rect': {'x': 0, 'y': 0, 'width': 199, 'height': 90}},
        {'type': 'workspace', 'name': '1', 'rect': {'x': 0, 'y': 0, 'width': 99, 'height': 99}, 'nodes': [
            {'window': 7, 'focused': True, 'rect': {'x': 0, 'y': 0, 'width': 50, 'height': 99}},
            {'window': 8, 'rect': {'x': 50, 'y': 0, 'width': 49, 'height': 99}}]},
        {'type': 'workspace', 'name': '2', 'nodes': [{'window': 9, 'rect': {'x': 0, 'y': 0, 'width': 99, 'height': 99}}]},
        {'type': 'workspace', 'name': '3', 'focused': True, 'rect': {'x': 100, 'y': 0, 'width': 99, 'height': 99}}]}]}
    assert windows(tree, {'1', '3'}) == ([(0, 0, 50, 99), (50, 0, 49, 99)], (100, 0, 99, 99), [(0, 0, 199, 90)])  # hidden ws 2 skipped; empty ws 3 focused


def menus():
    from . import cli, config, show
    real, saved, conf, past = cli.rofi, config.SETTINGS, dict(config.CONF), show.HISTORY
    with tempfile.TemporaryDirectory() as d:
        config.SETTINGS, show.HISTORY = Path(d) / 'settings.json', Path(d) / 'history.jsonl'
        # settings page → effort → 3rd row (high) → model → typed id → effort → typo (ignored) → esc
        answers = iter([lambda r: r[1], lambda r: r[2], lambda r: r[0], lambda r: 'claude-sonnet-5-5',
                        lambda r: r[1], lambda r: 'hgih', lambda r: None])
        cli.rofi = lambda rows, *a: next(answers)(rows)
        try:
            cli.settings(None)
            assert config.CONF['effort'] == 'high' and config.CONF['model'] == 'claude-sonnet-5-5', config.CONF
            assert json.loads(config.SETTINGS.read_text()) == config.CONF
            # two animations shown → settings → history → the older one plays again
            for title in ('Area under $e^{-x}$', 'Riemann sums'):
                show.HISTORY.write_text((show.HISTORY.read_text() if show.HISTORY.exists() else '') +
                                        json.dumps({'t': time.time(), 'spec': {'kind': 'area', 'title': title}}) + '\n')
            answers, reopened = iter([lambda r: r[-1], lambda r: r[1]]), []
            cli.settings(reopened.append)
            assert reopened == [{'kind': 'area', 'title': 'Area under $e^{-x}$'}], reopened
        finally:
            cli.rofi, config.SETTINGS, show.HISTORY = real, saved, past
            config.CONF.clear(), config.CONF.update(conf)


def formulas():
    from .expr import formula, number
    x = np.array([0., 1, 2])
    assert np.allclose(formula('x^2*exp(-x) + 2x')(x=x), x ** 2 * np.exp(-x) + 2 * x)
    assert np.allclose(formula('(-1)**k*x**(2*k+1)/factorial(2*k+1)', ('k', 'x'))(k=np.arange(3.), x=1.), [1, -1 / 6, 1 / 120])
    assert np.isnan(formula('1/x')(x=0.)) and formula('log10(x)')(x=100.) == 2 and formula('sqrt(1-theta)', ('t',))(t=0.) == 1
    assert (number('pi/2'), number('-inf'), number('1e-5')) == (np.pi / 2, -np.inf, 1e-5)
    for bad in ["__import__('os').system('true')", 'x.__class__', '(lambda: 1)()', '[x for x in ()]', "open('f')",
                'x[0]', "'a'", 'y+1', 'sin(x, out=x)', 'True', 'exec("1")', 'globals()']:
        try:
            formula(bad)
            raise AssertionError(f'formula let through: {bad}')
        except ValueError:
            pass
    t = time.monotonic()
    formula('9**9**9')()  # float powers: overflow, not a hang building a giant int
    assert time.monotonic() - t < 1


def plots():
    """Every Show-me kind builds in manim, and a hostile formula is refused: run in the Python that has manimgl."""
    import subprocess
    import sys
    from .config import CACHE, MANIM
    python = str(MANIM) if MANIM.exists() else sys.executable
    src = str(Path(__file__).resolve().parent.parent)
    CACHE.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([python, '-c', 'import manimlib'], capture_output=True)
    if p.returncode:
        return print('plots skipped: no manimgl (see README)')
    p = subprocess.run([python, '-m', 'penmentor.plot', '--check'], capture_output=True, text=True, cwd=CACHE,
                       env=dict(os.environ, PYTHONPATH=src), timeout=600)
    assert p.returncode == 0 and 'plots ok' in p.stdout, (p.stdout + p.stderr)[-2000:]


def overlay():
    """Drill, technique and Pill wiring, on an offscreen Qt."""
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PIL import Image
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication
    from .overlay import Overlay, Pill, display, tex_jobs
    app = QApplication.instance() or QApplication([])
    shot = Image.new('RGB', (1200, 800), (20, 20, 24))
    ov = Overlay(shot, (0, 0, 1200, 800), mode='drill')
    drill = dict(problem=r'Find $\int x e^x\,dx$', lines=[r'$u = x,\ dv = e^x dx$', r'$du = dx,\ v = e^x$', r'$= x e^x + \int e^x\,dx$', r'$= x e^x + e^x + C$'],
                 wrong=2, fix=r'$= x e^x - \int e^x\,dx$', why='Integration by parts subtracts: $uv - \\int v\\,du$.')
    r = dict(read_as=[], verdict='hint', headline='Find the mistake', marks=[], drill=drill)
    assert (display(drill['fix']), 19) in tex_jobs(r)
    ov.set_result(r)
    d = ov.drill
    assert len(d['rows']) == 4 and ov.actions()[0][0] == 'new drill'
    centre = lambda i: d['rows'][i][0].center()
    assert ov.drill_row(centre(1)) == 1 and ov.drill_row(QPointF(-5, -5)) is None
    ov.pick_line(0)
    assert d['picked'] == {0} and not d['revealed']
    ov.pick_line(2)
    assert d['revealed'] and d['found'] and ov.result['verdict'] == 'correct'
    ov.grab()  # paints the card without errors
    ov.set_result(dict(r, drill=dict(drill)))
    ov.pick_line(0), ov.pick_line(1)  # two misses: the answer shows
    assert ov.drill['revealed'] and not ov.drill['found'] and ov.result['headline'] == 'It was line 3'
    tech = Overlay(shot, (0, 0, 1200, 800), mode='technique')
    tech.set_result(dict(read_as=[], verdict='hint', headline='Which technique fits?', marks=[]))
    tech.grab()
    assert tech.drill is None and tech.actions()[0][0] == 'pick the technique' and tech.head_box is not None
    # the marks sit on the live screen: the window is shaped to what is drawn, everything else stays the apps'
    from PyQt6.QtCore import QPoint
    assert not tech.base.isEmpty() and not tech.base.contains(QPoint(60, 400)) and tech.base.contains(tech.head_box.center().toPoint())
    assert [label for _, label, _ in tech.bar_items][-1] == 'close · esc'  # the bar's buttons were laid out
    pill = Pill(tech.shot, (0, 0, 1200, 800))
    assert not pill.grab().isNull()


def page_export():
    """A xournal++ that never answers (started before the plugin was installed) costs one wait, not one per question."""
    from . import xournal as X
    saved = X.PLUGIN, X.PAGE, X.INFO, X.MISS, X.focused, X.PageRequest.poke
    with tempfile.TemporaryDirectory() as d:
        X.PLUGIN, X.PAGE, X.INFO, X.MISS = Path(d), Path(d, 'page.png'), Path(d, 'page.txt'), Path(d, 'page.miss')
        pid, pokes = ['123'], []
        X.focused, X.PageRequest.poke = lambda: pid[0], staticmethod(lambda: pokes.append(1))
        try:
            assert X.PageRequest().result(wait=.1) is None and len(pokes) == 2  # asked twice, then gave up
            assert not X.PageRequest().on  # same xournal: not asked again
            pid[0] = '456'  # restarted, plugin loaded now
            r = X.PageRequest()
            X.INFO.write_text('3 5')
            X.PAGE.write_bytes(b'png')
            assert r.on and r.result() == (b'png', 'page 3 of 5') and not X.MISS.exists()
        finally:
            X.PLUGIN, X.PAGE, X.INFO, X.MISS, X.focused, X.PageRequest.poke = saved


def stopping():
    """Esc kills a claude that is still answering instead of leaving it running on your plan."""
    import threading
    from . import harness
    with tempfile.TemporaryDirectory() as d:
        stub, saved, failed = Path(d) / 'claude', harness.BIN['claude'], []
        stub.write_text('#!/bin/sh\nexec sleep 30\n')
        stub.chmod(0o755)
        harness.BIN['claude'] = str(stub)
        def ask():
            try:
                harness.ask([], 'hi', keep=False)
            except RuntimeError:
                failed.append(True)
        try:
            t = threading.Thread(target=ask)
            t.start()
            for _ in range(300):
                if harness.RUNNING:
                    break
                time.sleep(.01)
            harness.stop()
            t.join(5)
            assert not t.is_alive() and failed and not harness.RUNNING
        finally:
            harness.BIN['claude'] = saved


STUB = r"""#!/usr/bin/env python3
import json, os, sys
open(os.environ['PM_LOG'], 'a').write(json.dumps({'argv': sys.argv, 'stdin': sys.stdin.read()}) + '\n')
answer = {'read_as': [], 'verdict': 'correct', 'headline': 'ok', 'marks': []}
name = os.path.basename(sys.argv[0])
if name == 'claude':
    print(json.dumps({'type': 'result', 'structured_output': answer, 'usage': {'input_tokens': 5, 'output_tokens': 2}}))
elif name == 'agy':
    print(json.dumps({'event': 'init', 'conversation_id': 'conv-1'}))
    print(json.dumps({'event': 'result', 'result': {'status': 'SUCCESS', 'conversation_id': 'conv-1', 'structured_output': answer,
                                                    'usage': {'total_tokens': 7}}}))
else:
    print(json.dumps({'type': 'thread.started', 'thread_id': 'thr-1'}))
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(dict(answer, drill=None, plot=None))}}))
    print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 5, 'output_tokens': 2}}))
"""


def harnesses():
    """Claude Code, Antigravity and Codex, played by stand-ins that answer in each one's own format: the same answer
    shape whichever runs it, follow-ups resume that harness's conversation, switching harness starts a new one."""
    from . import config, harness
    saved = dict(harness.BIN), harness.SESSION, harness.TURN, harness.CACHE, dict(config.CONF)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        log = d / 'log.jsonl'
        os.environ['PM_LOG'] = str(log)
        for h in harness.HARNESSES:
            (d / h).write_text(STUB)
            (d / h).chmod(0o755)
            harness.BIN[h] = str(d / h)
        harness.SESSION, harness.TURN, harness.CACHE = d / 'session.json', d / 'turn', d
        shot = harness.prepare(__import__('PIL.Image').Image.new('RGB', (40, 30), 'white'))
        calls = lambda: [json.loads(l) for l in log.read_text().splitlines()]
        try:
            assert harness.pick('codex:gpt-x') == ('codex', 'gpt-x') and harness.pick('opus') == ('claude', 'opus')
            for h, resumes in (('claude', '--resume'), ('agy', '--conversation'), ('codex', 'resume')):
                config.CONF['model'] = f'{h}:m'
                r = harness.ask([shot], 'is it right?')
                assert r['headline'] == 'ok' and 'drill' not in r and r['_tokens'][0] > 0, (h, r)
                assert json.loads(harness.SESSION.read_text())['harness'] == h
                first = calls()[-1]
                strict = json.loads((d / 'turn' / 'schema.json').read_text()) if h == 'codex' else None
                harness.ask([shot], 'and now?', new_shot=False)  # a follow-up: the same conversation
                assert resumes in calls()[-1]['argv'], (h, calls()[-1]['argv'])
                if h == 'agy':  # its print mode takes text only: the screenshot is a file it is told to open
                    assert str(d / 'turn' / 'image1.png') in first['stdin'] and '--sandbox' in first['argv']
                if h == 'codex':  # attached by Codex; its schema strict (every key required)
                    assert f"--image={d / 'turn' / 'image1.png'}" in first['argv']
                    assert set(strict['required']) == set(strict['properties']) and '--sandbox' in first['argv']
            config.CONF['model'] = 'agy:m'  # a codex conversation can't continue in agy: a new one, screenshots included
            harness.ask([shot], 'and now?', new_shot=False)
            assert '--conversation' not in calls()[-1]['argv'] and 'image1.png' in calls()[-1]['stdin']
        finally:
            harness.BIN.update(saved[0])
            harness.SESSION, harness.TURN, harness.CACHE = saved[1:4]
            config.CONF.clear(), config.CONF.update(saved[4])


def selftest():
    for check in (pages, text, desktop, menus, formulas, plots, overlay, page_export, stopping, harnesses):
        check()
    print('selftest ok')
