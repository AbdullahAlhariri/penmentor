"""Text with maths as images: real LaTeX when installed (Computer Modern via latex + dvipng), else matplotlib's mathtext."""
import functools
import io
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter

from .style import DRILL, FIX, GHOST, HEAD, NOTE, READ, TIP, UI_FONT

LATEX = bool(shutil.which('latex') and shutil.which('dvipng'))  # real LaTeX if installed, else matplotlib's imitation

W_ = r'(?![a-zA-Z])'  # end of a command name
TEX_FIXES = [  # LaTeX that matplotlib's mathtext lacks -> the nearest thing it has
    (r'\\(iff|Longleftrightarrow)' + W_, r'\\Leftrightarrow'), (r'\\implies' + W_, r'\\Rightarrow'),
    (r'\\impliedby' + W_, r'\\Leftarrow'), (r'\\le' + W_, r'\\leq'), (r'\\ge' + W_, r'\\geq'),
    (r'\\[lr]vert' + W_, '|'), (r'\\[lr]Vert' + W_, r'\\Vert'), (r'\\text(bf|it)' + W_, r'\\math\1'),
    (r'\\dd' + W_, 'd'), (r'\\color\{[^}]*\}', ''), (r'\\(begin|end)\{[^}]*\}', ''), (r'\\\\', r'\\;'), (r'(?<!\\)&', ''),
    (r'\\(displaystyle|textstyle|limits|nolimits|[bB]igg?[lr]?|boxed|cancel)' + W_, ''),
]


FN = r'(?<![\\a-zA-Z])(arcsin|arccos|arctan|sinh|cosh|tanh|sin|cos|tan|sec|csc|cot|ln|log|exp|lim)' + W_


def mathy(w):
    """Is this word really maths: x, -1, arcsin(y), x^2, dx, sin?"""
    if w in ('a', 'A', 'I'):
        return False
    core = re.sub(FN + r'|\\[a-zA-Z]+|^d[a-zθ]$', '', w)
    return not re.search('[A-Za-z]{2}', core) and (core != w or len(w) == 1 or bool(re.search(r'[\\^_={}<>+*/()\[\]\d−-]', w)))


def bare_math(t):
    """Wrap maths written without $ (arcsin(y), x^2, \\sqrt{x}) so it renders like the rest."""
    out, run = [], []
    for w in t.split(' '):
        core, tail = re.fullmatch(r'(.*?)([.,;:!?]*)', w).groups()
        if core and mathy(core):
            run.append(core)
            if tail:  # sentence punctuation stays outside the maths
                out.append(f"${' '.join(run)}${tail}")
                run = []
            continue
        if run:
            out.append(f"${' '.join(run)}$")
            run = []
        out.append(w)
    if run:
        out.append(f"${' '.join(run)}$")
    return ' '.join(out)


def tex_source(s, mathtext=True):
    """Claude's text -> maths in $...$; for mathtext also swap out what it lacks."""
    parts = s.split('$')
    if len(parts) % 2 == 0:  # unpaired $: guess where the maths is
        parts = [''.join(parts)]
    parts = '$'.join(p if i % 2 else bare_math(p) for i, p in enumerate(parts)).split('$')
    for i in range(1, len(parts), 2):
        m = re.sub(r'\\[tdc]?frac' + W_, r'\\dfrac', parts[i])  # full-size fractions read better on screen
        for a, b in TEX_FIXES if mathtext else ():
            m = re.sub(a, b, m)
        m = re.sub(FN, r'\\\1', m)  # arcsin -> \arcsin, upright like in print
        if len(re.findall(r'\\left' + W_, m)) != len(re.findall(r'\\right' + W_, m)):
            m = re.sub(r'\\(left|right)(\.|' + W_ + ')', '', m)
        parts[i] = f'${m}$' if m.strip() else ''
    return ''.join(parts)


def plain(s):
    """Last resort: LaTeX as readable unicode text."""
    from matplotlib._mathtext_data import tex2uni
    s = re.sub(r'\\dfrac\{([^{}]*)\}\{([^{}]*)\}', r'(\1)/(\2)', s)
    s = re.sub(r'\\(left|right|quad|qquad|mathrm|text|[,;:! ])' + W_, ' ', s)
    s = re.sub(r'\\([a-zA-Z]+)', lambda m: chr(tex2uni[m[1]]) if m[1] in tex2uni else m[1], s)
    return re.sub(r'[{}$\\]', '', s)


UNI = {'θ': r'\theta', 'π': r'\pi', 'α': r'\alpha', 'β': r'\beta', 'γ': r'\gamma', 'δ': r'\delta', 'ε': r'\varepsilon',
       'λ': r'\lambda', 'μ': r'\mu', 'σ': r'\sigma', 'φ': r'\varphi', 'ω': r'\omega', 'Δ': r'\Delta', 'Σ': r'\Sigma',
       '∞': r'\infty', '≤': r'\leq', '≥': r'\geq', '≠': r'\neq', '≈': r'\approx', '→': r'\to', '⇒': r'\Rightarrow',
       '⇔': r'\Leftrightarrow', '∫': r'\int', '√': r'\surd', '·': r'\cdot', '⋅': r'\cdot', '×': r'\times', '±': r'\pm',
       '−': '-', '∈': r'\in', '∑': r'\sum', '°': r'^\circ', '²': '^2', '³': '^3'}
UNI_RE = '[' + ''.join(map(re.escape, UNI)) + ']'
PREAMBLE = r"""\documentclass{article}
\usepackage[T1]{fontenc}\usepackage{lmodern}\usepackage{amsmath,amssymb,cancel}
\pagestyle{empty}""" + ''.join(rf'\DeclareMathSizes{{{z}}}{{{z * 1.05:.1f}}}{{{z * .8:.1f}}}{{{z * .6:.1f}}}'
                                for z in sorted({HEAD, NOTE, GHOST, FIX, TIP, READ, DRILL})) + r"\begin{document}"
SS, GAMMA = 3, '1.6'  # LaTeX supersampling factor, dvipng gamma
_typeset = {}  # (text, size) -> alpha mask from LaTeX, None if LaTeX choked on it


def latex_source(s):
    """Claude's text -> LaTeX source: unicode maths to commands, text-mode specials escaped."""
    parts = tex_source(s, mathtext=False).split('$')
    for i, p in enumerate(parts):
        parts[i] = (re.sub(UNI_RE, lambda m: UNI[m[0]] + ' ', re.sub(r'(?<!\\)([%#])', r'\\\1', p)) if i % 2 else
                    re.sub(UNI_RE, lambda m: f'${UNI[m[0]]}$', re.sub(r'(?<!\\)([%#&])', r'\\\1', p)))
    return '$'.join(parts)


def latex_ok(s):
    """Balanced braces and environments, so one bad string can't swallow the pages after it."""
    d = 0
    for c in re.sub(r'\\[{}]', '', s):
        d += (c == '{') - (c == '}')
        if d < 0:
            return False
    return d == 0 and s.count('\\begin{') == s.count('\\end{')


def typeset(keys):
    """One LaTeX run for many (text, size): a page each, cropped tight by dvipng into alpha masks."""
    todo = [k for k in dict.fromkeys(keys) if k not in _typeset]
    if not LATEX or not todo:
        return
    src = ['\n'.join(map(latex_source, t.split('\n'))) for t, _ in todo]
    line = lambda t: rf'\strut {t if latex_ok(t) else "x"}'
    box = lambda t: line(t) if '\n' not in t else r'\vbox{' + ''.join(rf'\hbox{{{line(l)}}}' for l in t.split('\n')) + '}'
    # several lines: one vbox, so TeX spaces them itself (\baselineskip = 1.2 x the size, as in print)
    body = [rf'\newpage\hbox{{\fontsize{{{z}}}{{{z * 1.2:.1f}}}\selectfont {box(t)}}}' for t, (_, z) in zip(src, todo)]
    first = PREAMBLE.count('\n') + 2  # source line of the first page
    try:
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'x.tex').write_text(PREAMBLE + '\n' + '\n'.join(body) + '\n\\end{document}\n')
            subprocess.run(['latex', '-interaction=nonstopmode', '-no-shell-escape', 'x.tex'], cwd=d, capture_output=True, timeout=30)
            # 115 dpi matches the handwriting. dvipng anti-aliases with only 15 alpha levels (jagged edges), so render 3x
            # and scale down smoothly; gamma thickens Computer Modern's thin strokes a little so they read on screen
            subprocess.run(['dvipng', '-T', 'tight', '-D', str(115 * SS), '-bg', 'Transparent', '--gamma', GAMMA, '-q', '-o', 'p%d.png', 'x.dvi'],
                           cwd=d, capture_output=True, timeout=30)
            log = Path(d, 'x.log').read_text(errors='replace')
            bad = {int(n) - first for n in re.findall(r'^!.*?^l\.(\d+)', log, re.M | re.S)}
            aligned = len(list(Path(d).glob('p*.png'))) == len(todo)
            for i, k in enumerate(todo):
                img = QImage(str(Path(d, f'p{i + 1}.png'))) if aligned and i not in bad and latex_ok(src[i]) else None
                _typeset[k] = None if img is None or img.isNull() else img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(
                    round(img.width() / SS), round(img.height() / SS), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    except Exception:
        _typeset.update(dict.fromkeys(todo))


def tint(mask, color):
    img = mask.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(img.rect(), QColor(color))
    p.end()
    return img


def tex(s, color, size=15):
    """Text with $maths$ as a QImage: real LaTeX (Latin Modern), else matplotlib mathtext, else plain text."""
    typeset([(s, size)])
    if _typeset.get((s, size)) is not None:
        return tint(_typeset[(s, size)], color)
    import matplotlib
    from matplotlib import mathtext
    from matplotlib.font_manager import FontProperties
    matplotlib.rcParams['savefig.transparent'] = True
    matplotlib.rcParams['mathtext.fontset'] = 'cm'  # Computer Modern, the LaTeX look
    for f in font_paths():
        matplotlib.font_manager.fontManager.addfont(f)
    s = tex_source(s)
    for _ in range(6):
        buf = io.BytesIO()
        try:
            mathtext.math_to_image(s, buf, prop=FontProperties(family=[UI_FONT, 'sans-serif'], size=size),
                                   dpi=100, format='png', color=color)
            return QImage.fromData(buf.getvalue())
        except Exception as e:
            bad = re.search(r'Unknown symbol: (\\[a-zA-Z]+)', str(e))
            if not bad:
                break
            s = tex_source(re.sub(re.escape(bad[1]) + W_, ' ', s))
    return text_img(plain(s), color, round(size * 100 / 72))


def wrap(s, chars):
    """Lines of about `chars` visible characters; never breaks inside $...$."""
    lines, cur, n = [], [], 0
    for w in re.findall(r'(?:[^\s$]|\$[^$]*\$)+', tex_source(s or '', mathtext=False)):
        k = len(re.sub(r'[{}^_$]', '', re.sub(r'\\[a-zA-Z]+', 'x', w)))
        if cur and n + k > chars:
            lines.append(' '.join(cur))
            cur, n = [], 0
        cur.append(w)
        n += k + 1
    return [l for l in lines + [' '.join(cur)] if l]


def as_math(w):
    return w if '$' in w else f'${w}$'


def read_line(l):
    return f"${l.replace('$', '')}$"


def lines_key(s, size, chars):
    """(text, size) for s wrapped at about `chars`: the key tex_lines typesets, so callers can batch it."""
    return '\n'.join(wrap(s, chars)) or s or '', size


def tex_lines(s, color, size=15, chars=40):
    """tex() wrapped over several lines: with LaTeX one box whose line spacing is TeX's own, else stacked lines."""
    text, _ = lines_key(s, size, chars)
    typeset([(text, size)])
    if '\n' not in text or _typeset.get((text, size)) is not None:
        return tex(text, color, size)
    imgs = [tex(l, color, size) for l in text.split('\n')]
    gap = 4
    out = QImage(max(i.width() for i in imgs), sum(i.height() + gap for i in imgs) - gap, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    p, y = QPainter(out), 0
    for i in imgs:
        p.drawImage(0, y, i)
        y += i.height() + gap
    p.end()
    return out


def shrink(img, maxw):
    return img.scaledToWidth(int(maxw), Qt.TransformationMode.SmoothTransformation) if img.width() > maxw else img


@functools.cache
def font_paths():
    """CMU Serif ships with TeX Live (cm-unicode), so nothing needs a system-wide install."""
    return subprocess.run(['kpsewhich', 'cmunrm.otf'], capture_output=True, text=True).stdout.split() if shutil.which('kpsewhich') else []


@functools.cache
def font_files():
    """CMU Serif registered with Qt (needs the QApplication)."""
    for f in font_paths():
        QFontDatabase.addApplicationFont(f)
    return font_paths()


def ui_font(px):
    font_files()
    f = QFont(UI_FONT)
    f.setPixelSize(px)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)  # the font's own letter spacing, as TeX and manim draw it
    return f


def text_img(s, color, px=20, width=2000):
    f = ui_font(px)
    r = QFontMetrics(f).boundingRect(QRect(0, 0, width, 4000), Qt.TextFlag.TextWordWrap, s)
    img = QImage(r.width() + 4, r.height() + 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(2, 0, r.width() + 2, r.height() + 2), Qt.TextFlag.TextWordWrap, s)
    p.end()
    return img
