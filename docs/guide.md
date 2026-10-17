# penmentor: the full guide

Press a key while you work through maths by hand, and Claude answers by drawing on your screen, the way a teacher
marks work with coloured pens: rings round the mistake, ticks on the right lines, a faint ghost of the next step,
arrows from cause to effect. Words are a last resort.

Built for [xournal++](https://xournalpp.github.io/) and a pen tablet on Linux (X11, works best with i3), for calculus,
but it reads whatever maths is on screen.

## What it can do

| Menu entry | What you get |
|---|---|
| Did I make any mistakes? | the first real error circled with its fix, later lines that inherit it underlined, correct lines ticked |
| Solution check | is the final answer right, and is anything missing (+C, bounds, absolute values…)? |
| Give me a hint | the smallest nudge: one thing highlighted, the next step not given away |
| Which technique? | the features that point to a method are coloured, no method named; you pick one (`p`) and Claude says whether it fits |
| Quiz me on my steps | a question at the 1 or 2 steps that matter most; answer by typing (`a`) or by writing on the page (`w`) |
| Find-the-error drill | a new worked problem like yours with one planted mistake; tap the wrong line |
| Show me (animation) | box what you want to see (one box or several), then get an animation of it made with 3Blue1Brown's own [manim](https://github.com/3b1b/manim), on the other monitor, that you can play with: Riemann sums, areas, improper integrals, substitution as a stretch of the axis, solids of revolution, series, Taylor polynomials, polar and parametric curves |
| Ask about a box | drag a box round something and ask about just that |

In the answer overlay:

| Key | |
|---|---|
| `h` | more help, one rung up the ladder: nudge → name the technique → ghost the next line → full fix |
| `?` | a follow-up question |
| `g` | show me: box what to animate, then watch it |
| `w` | step aside so you can write more; tap the badge at the top (or press an penmentor key) when done and it checks the new part |
| `t` / `s` | what Claude read / model, tokens and plan usage |
| `r` | replay the marks |
| `Esc` | stop penmentor, wherever you are: in a menu, while Claude is still thinking (Claude stops too), or while you write |

Show me starts on the frozen screen: drag boxes round what to animate (right-click takes one back), then tap the badge
or press Enter. The window opens straight away (a loading animation runs while Claude thinks) and stays until you
press `q` in it (Esc leaves it open). Drag in it to move the bound, the number of rectangles, the degree, the point on the
curve (or turn a 3D solid); where curves cross, and where the bounds x = a and x = b meet them, is marked with
its coordinates. Change the maths in place: click a value in the row at the bottom (the function, a, b, n) and type a
new one, or drag a bound line; it redraws at once (and goes in the history). Scroll to zoom, arrows to step, space to replay. Every animation is kept: *Settings →
history* plays an old one again, without asking Claude.

Hover or tap a mark for its one-line "why". Questions build on each other (one Claude conversation) until you pick
*Clear context*; turn that off in *Settings*, where you also choose the model and effort.

## How it works, and what leaves your computer

A screenshot of every monitor, plus (with the xournal++ plugin) the whole current page of your notes, goes to Claude
through the [Claude Code](https://claude.com/claude-code) CLI (`claude -p`), so it runs on your Claude subscription.
Claude answers in JSON (what it read, a verdict, marks with boxes); penmentor snaps the boxes onto your ink and draws them
on a frozen copy of the screen. Nothing else is sent and nothing runs in the background between questions.

## Install

Linux with X11. On Arch:

```sh
sudo pacman -S python-pyqt6 python-numpy python-scipy python-pillow python-matplotlib rofi slop xdotool libnotify
sudo pacman -S texlive-latex texlive-latexextra texlive-fontsextra   # optional: real LaTeX and the CMU fonts
```

Install [Claude Code](https://claude.com/claude-code) and log in once (`claude`). Then:

```sh
git clone <this repo> ~/src/penmentor
~/src/penmentor/bin/penmentor --selftest
```

Bind a key: see [contrib/i3.conf](../contrib/i3.conf) (or `pip install .` and bind `penmentor`).

**xournal++ plugin** (so Claude also sees the parts of the page that are scrolled away, and your unsaved strokes):

```sh
ln -s ~/src/penmentor/xournalpp-plugin/penmentor ~/.config/xournalpp/plugins/penmentor
```

and restart xournal++. It adds *Plugin → penmentor: share the current page* on Ctrl+Alt+Shift+F12, which penmentor presses for you.

**Show me** needs manimgl (3Blue1Brown's manim) and its OpenGL window. Put it in its own environment, where penmentor
looks for it:

```sh
uv venv --system-site-packages ~/.local/share/penmentor/manim
uv pip install -p ~/.local/share/penmentor/manim/bin/python manimgl audioop-lts
```

(or `pip install '.[show]'` into the Python that runs penmentor).

**Tablet buttons:** `penmentor --ask check` skips the menu; [contrib/wacom.sh](../contrib/wacom.sh) maps two pad buttons to it.

## Development

```sh
bin/penmentor --selftest                       # page analysis, text, formulas, plots, drill logic; no Claude, no screen
bin/penmentor --test shot.png check            # ask Claude about a saved screenshot: shot.penmentor.json and shot.penmentor.png
bin/penmentor --render shot.png shot.penmentor.json  # redraw a saved answer without Claude (tune the visuals)
PYTHONPATH=src ~/.local/share/penmentor/manim/bin/python -m penmentor.plot --png spec.json out.png   # one animation's last frame
~/.local/share/penmentor/manim/bin/python docs/assets.py   # the README's banner
```

| Module | |
|---|---|
| `cli.py` | entry point: capture, menu, settings |
| `prompts.py` | everything Claude is told, and the JSON schema it answers in |
| `claude.py` | the `claude -p` call, sessions, token and usage stats |
| `desktop.py`, `xournal.py` | screenshots, monitors, i3 windows, rofi; the whole-page export |
| `page.py` | where the ink is: snapping boxes onto strokes, finding empty space |
| `overlay.py`, `draw.py`, `style.py` | the frozen frame, the marks, the modes |
| `typeset.py` | LaTeX (or mathtext) into images |
| `plot.py`, `show.py`, `expr.py` | Show me: the manim scenes (run by manim's Python), opening their window and its history, and a safe evaluator for Claude's formulas |
