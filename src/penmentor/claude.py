"""Asking Claude through the Claude Code CLI (`claude -p`), so it runs on your Claude subscription."""
import atexit
import base64
import io
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import CACHE, CONF, SESSION
from .prompts import SCHEMA, SYSTEM

CLAUDE = shutil.which('claude') or str(Path.home() / '.local/bin/claude')  # i3's PATH may lack ~/.local/bin
SEND_EDGE = 1568  # long edge of the image Claude sees; its boxes come back in that space


def prepare(shot, boxes=()):
    """PNG bytes Claude sees (your boxes drawn on in cyan: [(number or None, (x0, y0, x1, y1))]; shrunk) and its size."""
    img = shot.copy()
    draw = ImageDraw.Draw(img)
    for n, box in boxes:
        draw.rectangle(box, outline=(0, 220, 255), width=4)
        if n:
            draw.text((box[0] + 8, box[1] + 4), str(n), fill=(0, 220, 255), font=ImageFont.load_default(30))
    s = min(1, SEND_EDGE / max(img.size))
    if s < 1:
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue(), img.size


def session():
    try:
        return json.loads(SESSION.read_text())
    except (OSError, ValueError):
        return None


RUNNING = set()  # claude processes still answering


@atexit.register
def stop():
    """Kill Claude mid-answer: Esc, or penmentor quitting for any reason, must not leave it running on your plan."""
    for p in list(RUNNING):
        p.kill()


def image(png):
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': base64.b64encode(png).decode()}}


def ask(shots, text, main=0, new_shot=True, keep=True, page=None):
    """shots: [(png, (w, h))] per monitor, left to right; main: the focused one; page: (png, label) of the whole xournal page.
    new_shot=False: a follow-up on the screenshots Claude already has. keep=False: no shared context (offline tests)."""
    content = [{'type': 'text', 'text': text}]
    if new_shot:
        content = []
        for i, (png, (w, h)) in enumerate(shots):
            content += [{'type': 'text', 'text': f'Screen {i}' + (' (focused)' if i == main else '') + f': {w}x{h} px'}, image(png)]
        if page:
            content += [{'type': 'text', 'text': f'The whole {page[1]} of the xournal notes, for context only (no marks on it):'},
                        image(prepare(Image.open(io.BytesIO(page[0])).convert('RGB'))[0])]
        content.append({'type': 'text', 'text': 'Give every box in its own screen\'s pixels.\n\n' + text})
    msg = {'type': 'user', 'message': {'role': 'user', 'content': content}}
    s = session() if keep else None
    sid = s['id'] if s else str(uuid.uuid4())
    # isolated from your own Claude Code setup: no tools, hooks, plugins or MCP servers
    cmd = [CLAUDE, '-p', '--restricted', '--strict-mcp-config', '--tools', '', '--disable-slash-commands',
           *(['--resume', sid] if s else ['--session-id', sid] if keep else ['--no-session-persistence']),
           '--model', CONF['model'], '--effort', CONF['effort'], '--system-prompt', SYSTEM,
           '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
           '--json-schema', json.dumps(SCHEMA)]
    CACHE.mkdir(parents=True, exist_ok=True)
    t = time.monotonic()
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=CACHE) as p:
        RUNNING.add(p)
        try:
            out, err = p.communicate(json.dumps(msg), timeout=300)
        finally:
            p.kill()  # only does something on a timeout or when penmentor stops
            RUNNING.discard(p)
    for line in reversed(out.splitlines()):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('type') == 'result':
            if e.get('is_error') or 'structured_output' not in e:
                raise RuntimeError(str(e.get('result') or e.get('subtype')))
            if keep:
                SESSION.write_text(json.dumps({'id': sid}))
            u = e.get('usage') or {}  # this question only; modelUsage adds up the whole session, every model in it
            spent = sum(u.get(k, 0) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'))
            total = sum(m.get(k, 0) for m in (e.get('modelUsage') or {}).values()
                        for k in ('inputTokens', 'cacheCreationInputTokens', 'cacheReadInputTokens', 'outputTokens'))
            lim = [json.loads(l)['rate_limit_info'] for l in out.splitlines() if '"rate_limit_event"' in l]
            return dict(e['structured_output'], _secs=round(time.monotonic() - t, 1), _tokens=[spent, u.get('cache_read_input_tokens', 0), total],
                        _limits=lim[-1].get('unifiedWindows', {}) if lim else {})  # plan usage: 5-hour and weekly
    if s and 'No conversation found' in err:  # Claude Code pruned the old session: start a new one, screenshots included
        SESSION.unlink()
        return ask(shots, text, main, True, keep, page)
    raise RuntimeError(err.strip()[-300:] or 'no answer from claude')
