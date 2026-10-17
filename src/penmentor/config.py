"""Where penmentor keeps things, and your settings (model, effort, context), saved in ~/.config/penmentor/settings.json."""
import json
import os
from pathlib import Path

CACHE = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'penmentor'
SETTINGS = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'penmentor' / 'settings.json'
SESSION = CACHE / 'session.json'  # the Claude conversation every question builds on, until Clear context
DATA = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'penmentor'  # kept: Show-me history, manim
MANIM = DATA / 'manim' / 'bin' / 'python'  # a venv with manimgl (README), for Show me
STATE = CACHE / 'state'  # 'busy', or 'waiting <pid>' while penmentor waits for you to write; read by a second penmentor

CHOICES = {  # claude --model aliases, --effort levels, shared context
    'model': [('opus', 'Opus 5.5'), ('sonnet', 'Sonnet 5.5'), ('haiku', 'Haiku 5.5'), ('fable', 'Fable 5.1')],
    'effort': [('low', 'fastest'), ('medium', 'balanced'), ('high', 'more careful'), ('xhigh', 'slower'), ('max', 'slowest, most careful')],
    'context': [('on', 'each question builds on the earlier ones'), ('off', 'each question starts fresh')],
}
CONF = {'model': 'opus', 'effort': 'medium', 'context': 'on', 'stats': False, 'read': False}  # stats/read: s and t panels, kept on between questions
try:
    CONF |= json.loads(SETTINGS.read_text())
except (OSError, ValueError):
    pass


def save(**kw):
    CONF.update(kw)
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(CONF))


def set_state(s):
    CACHE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(s)
