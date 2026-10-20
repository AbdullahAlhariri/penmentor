"""penmentor: press a key, ask about the maths on screen, the model draws the answer on it.

  penmentor                          screenshot every monitor, rofi question, overlay
  penmentor --last                   show the last answer again
  penmentor --ask MODE               skip the menu (for pen-tablet buttons); MODE is one of the presets in prompts.py
  penmentor --test IMG [MODE|"question"]   offline: ask the model about IMG, writes IMG.penmentor.{json,png}
  penmentor --render IMG JSON        offline: redraw a saved answer (tune visuals without the model)
  penmentor --selftest

The marks stay over your live screen while you keep writing; tap the buttons on their bar (or press the penmentor
key again for the same as a menu): check new work, more help, ask, show me, what I read, stats, replay.
Esc stops penmentor at any point, the model included.
Hover or tap a mark for its one-line "why".
"""
import faulthandler
import fcntl
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path

from . import harness, show, xournal
from .config import CACHE, CHOICES, CONF, SESSION, STATE, save, set_state
from .desktop import Oops, capture, notify, on_escape, rofi, select_region
from .prompts import BOX_QS, PRESETS, TASKS

SETTINGS_ROW, CLEAR_ROW, HISTORY_ROW = '⚙  Settings', '✕  Clear context', 'history'


def model_choices():
    """The models of the harnesses you have installed, and the one you use now even if it is not listed."""
    have = harness.installed()
    out = [(a, n) for a, n in CHOICES['model'] if harness.pick(a)[0] in have]
    return out if any(a == CONF['model'] for a, _ in out) else [(CONF['model'], '(yours)')] + out


def label(key, value):
    """A settings row's value: models show their harness first ("codex   gpt-5.6-terra"), the rest as they are."""
    if key != 'model':
        return f'{value:<8}'
    h, m = harness.pick(value)
    return f'{h:<7}{m:<28}'


def settings(reopen):
    """Pick model / effort / context until Esc; each pick is saved at once. History: reopen(spec) an old animation."""
    shown = lambda k: ':'.join(harness.pick(CONF[k])) if k == 'model' else CONF[k]  # the model with its harness, always
    while c := rofi([f'{k:<8}{shown(k)}' for k in CHOICES] + [HISTORY_ROW], 'settings'):
        if c == HISTORY_ROW:
            return past_animations(reopen)
        key = c.split()[0]
        if key not in CHOICES:
            continue
        choices = model_choices() if key == 'model' else CHOICES[key]
        rows = [f'{"●" if a == CONF[key] else "○"}  {label(key, a)}{name}' for a, name in choices]
        free = key == 'model'  # any model id works, typed as harness:model; a mistyped effort would only break the next ask
        if (v := rofi(rows, key)) is None:
            return
        v = dict(zip(rows, (a for a, _ in choices))).get(v, v if free else None)
        if v:
            save(**{key: v})


def past_animations(reopen):
    """Every Show-me animation, newest first; the one you pick plays again (no model needed)."""
    from .typeset import plain
    past = show.history()
    rows = [f'{time.strftime("%d %b %H:%M", time.localtime(h["t"]))}    {plain(h["spec"].get("title") or h["spec"].get("kind", "?"))}'
            for h in past]
    if not rows:
        return notify('No animations yet: ask "Show me" first.', ms=3000)
    if (pick := rofi(rows, 'history')) in rows:
        reopen(past[rows.index(pick)]['spec'])


def nudge_running(what='menu'):
    """Another penmentor holds the lock. If its marks are up, this key press opens their menu ('menu'), or a pad
    button asks its question about the work on screen (a preset mode)."""
    try:
        state = STATE.read_text().split()
        if state[0] == 'open' and b'penmentor' in Path(f'/proc/{int(state[1])}/cmdline').read_bytes():
            (CACHE / 'poke').write_text(what)
            return os.kill(int(state[1]), signal.SIGUSR1)
    except (OSError, ValueError, IndexError):
        pass
    notify('Still answering the last question…', ms=2500)


def app_and_overlay():
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication
    from .overlay import Overlay
    if not QThread.isMainThread():  # Qt got loaded on another thread: its windows would hold the keyboard and ignore it
        raise RuntimeError('Qt was started off the main thread')
    return QApplication(sys.argv), Overlay


def watchdog(app):
    """Last resort: if the Qt loop ever stalls for 20 s (while the overlay may hold your keyboard and mouse),
    write where it hung to ~/.cache/penmentor/freeze.log and exit, so X gives them back."""
    from PyQt6.QtCore import QTimer
    log = open(CACHE / 'freeze.log', 'w')
    arm = lambda: faulthandler.dump_traceback_later(20, exit=True, file=log)
    arm()
    QTimer(app, interval=2000, timeout=arm).start()


def show_last():
    from PIL import Image
    d = json.loads((CACHE / 'last.json').read_text())
    app, Overlay = app_and_overlay()
    ov = Overlay(Image.open(CACHE / 'last.png').convert('RGB'), d['geom'], None, d.get('screens'), d.get('main', 0),
                 d.get('wins'), d.get('mode', 'check'))
    ov.set_result(d['result'])
    ov.present()
    on_escape(lambda: os._exit(0))  # the marks stay over your live screen until Esc
    watchdog(app)
    app.exec()


def offline(a):
    from PIL import Image
    from .harness import ask
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    img = Path(a[1])
    shot = Image.open(img).convert('RGB')
    mode = a[2] if a[0] == '--test' and len(a) > 2 else 'check'
    app, Overlay = app_and_overlay()
    ov = Overlay(shot, (0, 0, *shot.size), mode=mode)  # ponytail: one screen; offline multi-monitor needs a saved screens list
    if a[0] == '--test':
        t = time.time()
        r = ask(ov.shots, TASKS.get(mode, mode), keep=False)
        print(f'{CONF["model"]}/{CONF["effort"]}: {time.time() - t:.1f}s', file=sys.stderr)
        img.with_suffix('.penmentor.json').write_text(json.dumps({'result': r}, indent=1, ensure_ascii=False))
    else:
        r = json.loads(Path(a[2]).read_text())['result']
    ov.set_result(r)
    ov.t0 = -1e9  # skip the animation
    ov.grab().save(str(img.with_suffix('.penmentor.png')))
    print(json.dumps(r, indent=1, ensure_ascii=False))


def main(a):
    if a[:1] == ['--selftest']:
        from .selftest import selftest
        return selftest()
    if a[:1] in (['--test'], ['--render']):
        return offline(a)
    CACHE.mkdir(parents=True, exist_ok=True)
    lock = open(CACHE / 'lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return nudge_running(a[1] if a[:1] == ['--ask'] and a[1:2] else 'menu')
    set_state('busy')
    if a[:1] == ['--last']:
        return show_last()
    shot, screens, main_screen, wins = capture()  # before rofi draws over the screen
    page = xournal.PageRequest()  # now, while the keyboard still goes to xournal
    on_escape(lambda: (harness.stop(), os._exit(0)))  # Esc anywhere stops penmentor, even while the model thinks
    geom = (0, 0, *shot.size)
    on = CONF['context'] == 'on'
    if a[:1] == ['--ask']:  # a tablet button: straight to the question
        choice = next((label for label, m in PRESETS if a[1:2] == [m]), None)
        if not choice:
            raise Oops(f'penmentor --ask needs one of: {", ".join(m for _, m in PRESETS)}')
    while not a[:1] == ['--ask']:
        on = CONF['context'] == 'on'
        choice = rofi([label for label, _ in PRESETS] + [SETTINGS_ROW] + [CLEAR_ROW] * on, 'ask')
        if choice == SETTINGS_ROW:
            return settings(lambda spec: show.open_window(show.rect(show.monitor(screens, main_screen, geom)), spec))
        elif on and choice == CLEAR_ROW:
            SESSION.unlink(missing_ok=True)
        else:
            break
    if not choice:
        return
    if not on:  # context off: start fresh, but follow-ups in this overlay still share one conversation
        SESSION.unlink(missing_ok=True)
    mode = dict(PRESETS).get(choice, 'free')
    task = TASKS.get(mode, choice)
    boxes = None
    if mode == 'box':
        if not (box := select_region(geom)) or not (q := rofi(BOX_QS, 'about the box')):
            return
        boxes, task = [box], TASKS['explain'] if q == BOX_QS[0] else task + q
    app, Overlay = app_and_overlay()
    keep = []

    def ask(boxes, task):
        keep.append(ov := Overlay(shot, geom, boxes, screens, main_screen, wins, mode, page))
        ov.request(task)
    if mode == 'show':  # box what to show first
        from .overlay import BoxPicker, qimage
        keep.append(picker := BoxPicker(qimage(shot), geom, screens[main_screen],
                                        lambda boxes: ask(boxes, TASKS['show_boxes'] if boxes else task)))
        picker.present()
    else:
        ask(boxes, task)
    watchdog(app)
    app.exec()


def run():
    try:
        main(sys.argv[1:])
    except Oops as ex:
        notify(str(ex))
    except Exception as ex:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / 'error.log').write_text(traceback.format_exc())
        notify(f'{type(ex).__name__}: {str(ex)[:200]}\nDetails: ~/.cache/penmentor/error.log', critical=True, title='penmentor crashed')
        raise
