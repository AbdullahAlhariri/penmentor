"""Where penmentor keeps things, and your settings (model, effort, context), saved in ~/.config/penmentor/settings.json."""
import json
import os
from pathlib import Path

CACHE = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'penmentor'
SETTINGS = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'penmentor' / 'settings.json'
SESSION = CACHE / 'session.json'  # the conversation every question builds on (and its harness), until Clear context
DATA = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'penmentor'  # kept: Show-me history, manim
MANIM = DATA / 'manim' / 'bin' / 'python'  # a venv with manimgl (README), for Show me
STATE = CACHE / 'state'  # 'busy', or 'waiting <pid>' while penmentor waits for you to write; read by a second penmentor

CHOICES = {  # models as harness:model (which command-line agent runs it; see harness.py), effort levels, shared context
    'model': [('claude:opus', 'Opus 5.5'), ('claude:sonnet', 'Sonnet 5.5'), ('claude:haiku', 'Haiku 5.5'), ('claude:fable', 'Fable 5.1'),
              ('agy:gemini-4-argon-medium', 'Gemini 4 Argon'), ('agy:gemini-3.8-flash-medium', 'Gemini 3.8 Flash'),
              ('agy:claude-opus-5-5-medium', 'Claude Opus 5.5 through Antigravity'),
              ('codex:gpt-5.6-terra', 'GPT-5.6 Terra')],
    'effort': [('low', 'fastest'), ('medium', 'balanced'), ('high', 'more careful'), ('xhigh', 'slower'), ('max', 'slowest, most careful')],
    'context': [('on', 'each question builds on the earlier ones'), ('off', 'each question starts fresh')],
}
CONF = {'model': 'claude:opus', 'effort': 'medium', 'context': 'on', 'stats': False, 'read': False}  # stats/read: s and t panels, kept on between questions
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
