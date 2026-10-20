"""Asking the model you picked in Settings, through its own command-line agent, on your own subscription.

The model setting says which harness runs it: "claude:opus" (Claude Code), "agy:gemini-4-argon-medium" (Antigravity),
"codex:gpt-5.6-terra" (Codex). A bare name ("opus") is Claude Code's. Each gets the same screenshots, the same
instructions and the same JSON schema, and answers in the same shape.
"""
import atexit
import base64
import io
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import CACHE, CONF, SESSION
from .prompts import SCHEMA, SYSTEM

HARNESSES = {'claude': 'Claude Code', 'agy': 'Antigravity', 'codex': 'Codex'}
BIN = {h: shutil.which(h) or str(Path.home() / '.local/bin' / h) for h in HARNESSES}  # i3's PATH may lack ~/.local/bin
SEND_EDGE = 1568  # long edge of the images the model sees; its boxes come back in that space
TURN = CACHE / 'turn'  # the screenshots as files, for the harnesses that take images as files
VIEW_ONLY = ('Open these image files with your file viewer, in this order, and use only the file viewer: run no commands '
             'and use no other tools. Everything you need is in the images and this message.')


def pick(model=None):
    """(harness, model) for a model setting: "codex:gpt-5.6-terra" -> ('codex', 'gpt-5.6-terra'), "opus" -> ('claude', 'opus')."""
    m = model or CONF['model']
    h, sep, name = m.partition(':')
    return (h, name) if sep and h in HARNESSES else ('claude', m)


def installed():
    return [h for h in HARNESSES if os.access(BIN[h], os.X_OK)]


def prepare(shot, boxes=()):
    """PNG bytes the model sees (your boxes drawn on in cyan: [(number or None, (x0, y0, x1, y1))]; shrunk) and its size."""
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


RUNNING = set()  # harness processes still answering


@atexit.register
def stop():
    """Kill the model mid-answer: Esc, or penmentor quitting for any reason, must not leave it running on your plan."""
    for p in list(RUNNING):
        p.kill()


def run(cmd, stdin, cwd):
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd) as p:
        RUNNING.add(p)
        try:
            return p.communicate(stdin, timeout=300)
        finally:
            p.kill()  # only does something on a timeout or when penmentor stops
            RUNNING.discard(p)


def events(out):
    for line in out.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            pass


def strict(s):
    """OpenAI's strict JSON schema (Codex insists): every key required, the optional ones allowed to be null."""
    if isinstance(s, list):
        return [strict(v) for v in s]
    if not isinstance(s, dict):
        return s
    out = {k: (v if k in ('properties', 'required', 'enum') else strict(v)) for k, v in s.items()}
    if 'properties' in out:
        need = set(s.get('required', []))
        out['properties'] = {k: strict(v) if k in need else {'anyOf': [strict(v), {'type': 'null'}]} for k, v in s['properties'].items()}
        out['required'] = list(out['properties'])
    return out


def unnull(x):
    """Back from strict: the nulls go, so the answer looks the same whichever model gave it."""
    if isinstance(x, dict):
        return {k: unnull(v) for k, v in x.items() if v is not None}
    return [unnull(v) for v in x] if isinstance(x, list) else x


def files(parts):
    """The images as files in TURN, in order: [(path, (w, h))]."""
    shutil.rmtree(TURN, ignore_errors=True)
    TURN.mkdir(parents=True)
    out = []
    for i, (png, size) in enumerate(p for kind, p in parts if kind == 'image'):
        path = TURN / f'image{i + 1}.png'
        path.write_bytes(png)
        out.append((path, size))
    return out


def as_text(parts, names):
    """The message as one text, each image replaced by the name it goes by."""
    it = iter(names)
    return '\n'.join(p if kind == 'text' else f'[{next(it)}]' for kind, p in parts)


# ---------- the harnesses: (parts, model, resume id or None, keep) -> (answer, session id, tokens, plan limits) ----------

def claude(parts, model, sid, keep):
    content = [{'type': 'text', 'text': p} if kind == 'text' else
               {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': base64.b64encode(p[0]).decode()}}
               for kind, p in parts]
    new = sid or str(uuid.uuid4())
    # isolated from your own Claude Code setup: no tools, hooks, plugins or MCP servers
    cmd = [BIN['claude'], '-p', '--restricted', '--strict-mcp-config', '--tools', '', '--disable-slash-commands',
           *(['--resume', sid] if sid else ['--session-id', new] if keep else ['--no-session-persistence']),
           '--model', model, '--effort', CONF['effort'], '--system-prompt', SYSTEM,
           '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose', '--json-schema', json.dumps(SCHEMA)]
    out, err = run(cmd, json.dumps({'type': 'user', 'message': {'role': 'user', 'content': content}}), CACHE)
    for e in reversed(list(events(out))):
        if e.get('type') == 'result':
            if e.get('is_error') or 'structured_output' not in e:
                raise RuntimeError(str(e.get('result') or e.get('subtype')))
            u = e.get('usage') or {}  # this question only; modelUsage adds up the whole session, every model in it
            spent = sum(u.get(k, 0) for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'))
            total = sum(m.get(k, 0) for m in (e.get('modelUsage') or {}).values()
                        for k in ('inputTokens', 'cacheCreationInputTokens', 'cacheReadInputTokens', 'outputTokens'))
            lim = [l['rate_limit_info'] for l in events(out) if l.get('type') == 'rate_limit_event']
            return e['structured_output'], new, [spent, u.get('cache_read_input_tokens', 0), total], \
                lim[-1].get('unifiedWindows', {}) if lim else {}  # plan usage: 5-hour and weekly
    raise RuntimeError(err.strip()[-300:] or 'no answer from claude')


def agy(parts, model, sid, keep):
    """Antigravity's print mode takes text only: the screenshots are files its agent opens with its viewer. Headless,
    it can't be granted commands (they are denied), and its terminal is sandboxed."""
    imgs = files(parts)
    names = [f'{p.name}, {w}x{h} px' for p, (w, h) in imgs]
    text = (SYSTEM + '\n\n' if not sid else '') + (f'{VIEW_ONLY}\n' + '\n'.join(map(str, (p for p, _ in imgs))) + '\n\n' if imgs else '')
    effort = [] if model.rsplit('-', 1)[-1] in ('low', 'medium', 'high') else ['--effort', CONF['effort']]  # the name may say it
    cmd = [BIN['agy'], '--model', model, *effort, '--sandbox', '--disable-slash-commands', *(['--conversation', sid] if sid else []),
           '--input-format', 'stream-json', '--output-format', 'stream-json', '--json-schema', json.dumps(SCHEMA), '--print=']
    out, err = run(cmd, json.dumps({'event': 'user', 'message': {'content': text + as_text(parts, names)}}), TURN if imgs else CACHE)
    for e in reversed(list(events(out))):
        if e.get('event') == 'result':
            r = e['result']
            if r.get('status') != 'SUCCESS' or not isinstance(r.get('structured_output'), dict):
                raise RuntimeError(r.get('error') or err.strip()[-300:] or 'no answer from agy')
            u = r.get('usage') or {}
            return r['structured_output'], r.get('conversation_id'), [u.get('total_tokens', 0), u.get('cache_read_tokens', 0)], {}
    raise RuntimeError(err.strip()[-300:] or 'no answer from agy')


def codex(parts, model, sid, keep):
    """Codex attaches the screenshots itself; its schema must be strict. Read-only sandbox, none of your codex config."""
    imgs = files(parts)
    names = [f'attached image {i + 1}, {w}x{h} px' for i, (_, (w, h)) in enumerate(imgs)]
    schema = TURN / 'schema.json' if imgs else CACHE / 'schema.json'
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text(json.dumps(strict(SCHEMA)))
    effort = {'max': 'xhigh'}.get(CONF['effort'], CONF['effort'])
    cmd = [BIN['codex'], 'exec', *(['resume', sid] if sid else []), '--skip-git-repo-check', '--json',
           *([] if sid else ['--sandbox', 'read-only']), '--ignore-rules', '--ignore-user-config', *([] if keep else ['--ephemeral']),
           '-m', model, '-c', f'model_reasoning_effort="{effort}"', '--output-schema', str(schema),
           *[f'--image={p}' for p, _ in imgs], '-']
    text = (SYSTEM + '\n\n' if not sid else '') + 'Use no tools: everything you need is in the images and this message.\n\n'
    out, err = run(cmd, text + as_text(parts, names), schema.parent)
    thread, answer, usage = sid, None, {}
    for e in events(out):
        if e.get('type') == 'thread.started':
            thread = e.get('thread_id')
        elif e.get('type') == 'item.completed' and (e.get('item') or {}).get('type') == 'agent_message':
            answer = e['item'].get('text')
        elif e.get('type') == 'turn.completed':
            usage = e.get('usage') or {}
        elif e.get('type') in ('error', 'turn.failed'):
            raise RuntimeError(str(e.get('message') or e.get('error'))[-300:])
    try:
        answer = unnull(json.loads(answer))
    except (TypeError, ValueError):
        raise RuntimeError(err.strip()[-300:] or 'no answer from codex')
    spent = sum(usage.get(k, 0) for k in ('input_tokens', 'output_tokens', 'reasoning_output_tokens'))
    return answer, thread, [spent, usage.get('cached_input_tokens', 0)], {}


RUN = {'claude': claude, 'agy': agy, 'codex': codex}


def ask(shots, text, main=0, new_shot=True, keep=True, page=None):
    """shots: [(png, (w, h))] per monitor, left to right; main: the focused one; page: (png, label) of the whole xournal page.
    new_shot=False: a follow-up on the screenshots the model already has. keep=False: no shared context (offline tests)."""
    h, model = pick()
    s = session() if keep else None
    sid = s['id'] if s and s.get('harness', 'claude') == h else None  # another harness can't pick up this conversation
    new_shot = new_shot or not sid
    parts = [('text', text)]
    if new_shot:
        parts = []
        for i, shot in enumerate(shots):
            parts += [('text', f'Screen {i}' + (' (focused)' if i == main else '') + f': {shot[1][0]}x{shot[1][1]} px'), ('image', shot)]
        if page:
            parts += [('text', f'The whole {page[1]} of the xournal notes, for context only (no marks on it):'),
                      ('image', prepare(Image.open(io.BytesIO(page[0])).convert('RGB')))]
        parts.append(('text', 'Give every box in its own screen\'s pixels.\n\n' + text))
    CACHE.mkdir(parents=True, exist_ok=True)
    t = time.monotonic()
    try:
        answer, new, tokens, limits = RUN[h](parts, model, sid, keep)
    except RuntimeError:
        if not sid:
            raise
        SESSION.unlink(missing_ok=True)  # the harness lost that conversation: start a new one, screenshots included
        return ask(shots, text, main, True, keep, page)
    if keep and new:
        SESSION.write_text(json.dumps({'harness': h, 'id': new}))
    return dict(answer, _secs=round(time.monotonic() - t, 1), _tokens=tokens, _limits=limits)
