"""The X11 desktop: screenshots, monitors, i3 windows, rofi menus, notifications."""
import ctypes
import json
import re
import subprocess
import threading

from PIL import ImageGrab


class Oops(Exception):
    """A problem you can fix: shown as a plain notification, no traceback."""


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def notify(msg, ms=None, critical=False, title='penmentor'):
    subprocess.run(['notify-send', *(['-t', str(ms)] if ms else []), *(['-u', 'critical'] if critical else []), title, msg])


def monitors():
    """Active monitors (x, y, w, h), left to right."""
    try:
        out = sh('xrandr', '--listactivemonitors')
    except (OSError, subprocess.CalledProcessError):
        return []
    return sorted((int(x), int(y), int(w), int(h)) for w, h, x, y in re.findall(r'(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)', out))


def windows(tree, visible):
    """Windows (x, y, w, h) on the visible i3 workspaces, the rect of whatever has the focus,
    and each monitor's area without its i3 bars."""
    wins, focus, areas = [], None, []

    def walk(n, on):
        nonlocal focus
        on = on or (n.get('type') == 'workspace' and n.get('name') in visible)
        r = n.get('rect') or {}
        rect = (r.get('x', 0), r.get('y', 0), r.get('width', 0), r.get('height', 0))
        if n.get('focused'):
            focus = rect  # a window, or an empty workspace
        if n.get('type') == 'con' and n.get('name') == 'content' and rect[2] > 0 < rect[3]:
            areas.append(rect)
        if on and n.get('window') and rect[2] > 0 and rect[3] > 0 and rect not in wins:
            wins.append(rect)
        for c in n.get('nodes', []) + n.get('floating_nodes', []):
            walk(c, on)
    walk(tree, False)
    return wins, focus, sorted(areas)


def capture():
    """Everything on screen: (desktop image, monitors left to right, index of the focused one, visible windows)."""
    try:
        shot = ImageGrab.grab(xdisplay='').convert('RGB')  # whole X screen, no cursor; ~15x faster than maim's PNG
    except OSError:
        raise Oops('Could not take a screenshot.')
    try:
        wins, focus, screens = windows(json.loads(sh('i3-msg', '-t', 'get_tree')),
                                       {w['name'] for w in json.loads(sh('i3-msg', '-t', 'get_workspaces')) if w['visible']})
        if not wins:
            raise Oops('Nothing on screen to look at. Open your notes, then press the key again.')
    except (OSError, subprocess.CalledProcessError, ValueError):
        wins, focus, screens = [], None, []  # not i3: one page per monitor
    screens = screens or monitors() or [(0, 0, *shot.size)]  # i3's areas skip the bars, so panels sit above them; xrandr is slow (~0.6 s)
    if focus is None:  # focus follows the mouse
        try:
            g = dict(kv.split('=', 1) for kv in sh('xdotool', 'getmouselocation', '--shell').split())
            focus = (int(g['X']), int(g['Y']), 1, 1)
        except (OSError, subprocess.CalledProcessError, KeyError, ValueError):
            focus = screens[0]
    cx, cy = focus[0] + focus[2] / 2, focus[1] + focus[3] / 2
    main = next((i for i, (x, y, w, h) in enumerate(screens) if x <= cx < x + w and y <= cy < y + h), 0)
    return shot, screens, main, wins


def active_window():
    """The focused app's X window id (to hand the focus back later), or None."""
    p = subprocess.run(['xdotool', 'getactivewindow'], capture_output=True, text=True)
    return p.stdout.strip() or None


def activate(window):
    """Give the focus back: once the overlay has had the keyboard, neither X nor i3 returns it to the app by itself."""
    if window:
        subprocess.run(['xdotool', 'windowactivate', window], capture_output=True)


def on_escape(callback):
    """callback() on a thread whenever Escape is pressed, wherever the focus is (other keys still reach your apps),
    so Esc stops penmentor while Claude thinks. Windows that grab the keyboard (rofi, the overlay) get their Esc themselves."""
    try:
        x = ctypes.CDLL('libX11.so.6')
    except OSError:
        return
    dpy_t = ctypes.c_void_p
    x.XOpenDisplay.restype, x.XDefaultRootWindow.restype, x.XSetErrorHandler.restype = dpy_t, ctypes.c_ulong, ctypes.c_void_p
    x.XDefaultRootWindow.argtypes, x.XKeysymToKeycode.argtypes = [dpy_t], [dpy_t, ctypes.c_ulong]
    x.XGrabKey.argtypes = [dpy_t, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    x.XSync.argtypes, x.XNextEvent.argtypes = [dpy_t, ctypes.c_int], [dpy_t, ctypes.c_char_p]
    on_escape.ignore = ctypes.CFUNCTYPE(ctypes.c_int, dpy_t, dpy_t)(lambda *a: 0)  # kept alive: C calls it later
    x.XSetErrorHandler.argtypes = [type(on_escape.ignore)]
    dpy = x.XOpenDisplay(None)  # our own connection: Qt's is only ever touched by Qt's thread
    if not dpy:
        return
    x.XSetErrorHandler(on_escape.ignore)  # BadAccess if another program already has a combination: skip that one
    root, esc = x.XDefaultRootWindow(dpy), x.XKeysymToKeycode(dpy, 0xFF1B)  # XK_Escape
    for mods in (0, 2, 16, 18):  # plain, with Caps Lock, Num Lock, both
        x.XGrabKey(dpy, esc, mods, root, 1, 1, 1)  # owner_events, GrabModeAsync pointer and keyboard
    x.XSync(dpy, 0)
    event = ctypes.create_string_buffer(192)  # sizeof(XEvent)

    def wait():
        while True:
            x.XNextEvent(dpy, event)
            if event.raw[0] == 2:  # KeyPress
                callback()
    threading.Thread(target=wait, daemon=True).start()


def rofi(options, prompt):
    """The picked (or typed) row, None on Esc. No options: a plain text box."""
    p = subprocess.run(['rofi', '-dmenu', '-i', '-p', prompt],
                       input='\n'.join(options), capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def select_region(geom):
    p = subprocess.run(['slop', '-f', '%x %y %w %h', '-b', '3', '-c', '0,0.86,1,0.9'], capture_output=True, text=True)
    if p.returncode or not p.stdout.strip():
        return None
    x, y, w, h = map(int, p.stdout.split())
    return (x - geom[0], y - geom[1], x - geom[0] + w, y - geom[1] + h)
