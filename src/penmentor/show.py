"""The Show-me window (plot.py, run by the Python that has manimgl): where it opens, starting it, feeding it the
maths, and the history of every animation, which Settings → History brings back."""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import CACHE, DATA, MANIM
from .desktop import notify

JOB = CACHE / 'plot.json'  # the window's job; the maths follows in plot.spec.json
HISTORY = DATA / 'history.jsonl'  # one {"t": unix time, "spec": Claude's plot} per line, oldest first
KEEP = 300


def monitor(screens, main, geom):
    """The monitor Show me opens on (desktop pixels): the biggest other one, the nearest of those."""
    mx = screens[main][0]
    others = [r for i, r in enumerate(screens) if i != main] or screens
    x, y, w, h = max(others, key=lambda r: (r[2] * r[3], -abs(r[0] - mx)))
    return geom[0] + x, geom[1] + y, w, h


def rect(screen):
    """The window on it: 16:9, centred."""
    x, y, w, h = screen
    W = min(int(w * .7), int(h * .8 * 16 / 9))
    H = W * 9 // 16
    return x + (w - W) // 2, y + (h - H) // 2, W, H


def open_window(where, spec=None):
    """Open the window now, replacing the last one; it shows a loading animation until send() gives it the maths
    (or plays spec at once, from the history). Its own process, so it outlives penmentor: only q closes it."""
    python = str(MANIM) if MANIM.exists() else sys.executable
    if python == sys.executable and not importlib.util.find_spec('manimlib'):
        notify('Show me needs manimgl: see the README', ms=6000)
        return
    JOB.with_suffix('.spec.json').unlink(missing_ok=True)
    if spec:
        send(spec=spec, keep=False)
    JOB.write_text(json.dumps({'rect': list(where), 'parent': os.getpid()}))
    pid = CACHE / 'plot.pid'
    try:
        old = int(pid.read_text())
        if b'penmentor.plot' in Path(f'/proc/{old}/cmdline').read_bytes():  # never signal a stranger that reused the pid
            os.kill(old, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    src = str(Path(__file__).resolve().parent.parent)  # works from a checkout too, not only when installed
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [src, os.environ.get('PYTHONPATH')])))
    with open(CACHE / 'plot.log', 'w') as log:
        p = subprocess.Popen([python, '-m', 'penmentor.plot', str(JOB)], env=env, stdout=log, stderr=log, start_new_session=True, cwd=CACHE)
    pid.write_text(str(p.pid))


def send(keep=True, **msg):
    """spec=Claude's plot (kept in the history), or error=why there is none, for the window open_window opened."""
    tmp = JOB.with_suffix('.tmp')
    tmp.write_text(json.dumps(msg))
    tmp.replace(JOB.with_suffix('.spec.json'))  # whole or not at all: the window polls for it
    if keep and msg.get('spec'):
        remember(msg['spec'])


def remember(spec):
    """Add an animation to the history (Claude's, or one you changed in the window)."""
    DATA.mkdir(parents=True, exist_ok=True)
    lines = HISTORY.read_text().splitlines()[-(KEEP - 1):] if HISTORY.exists() else []
    HISTORY.write_text('\n'.join(lines + [json.dumps({'t': time.time(), 'spec': spec})]) + '\n')


def history():
    """Every animation shown, newest first."""
    out = []
    for line in reversed(HISTORY.read_text().splitlines() if HISTORY.exists() else []):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out
