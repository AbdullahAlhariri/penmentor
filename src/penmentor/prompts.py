"""What penmentor asks the model, and the JSON shape it answers in."""

PRESETS = [  # rofi menu: (label, mode)
    ('✓  Did I make any mistakes?', 'check'),
    ('☑  Solution check', 'final'),
    ('→  Give me a hint', 'nudge'),
    ('◇  Which technique?', 'technique'),
    ('✎  Quiz me on my steps', 'why'),
    ('✗  Find-the-error drill', 'drill'),
    ('∿  Show me (animation)', 'show'),
    ('◎  Ask about a box… (drag one)', 'box'),
]
BOX_QS = ['Explain this step', 'Is this part right?']
FOLLOWUPS = ['Why is that wrong?', 'Show me the next step', 'Explain it differently', 'Show the full fix']
TECHNIQUES = ['u-substitution', 'integration by parts', 'trig identities (powers of sin and cos)', 'trig substitution',
              'partial fractions', 'improper integral: take a limit', 'algebra first (expand, simplify, split)',
              "L'Hôpital's rule", 'geometric series', 'p-series', 'divergence test (n-th term)', 'integral test',
              'direct comparison', 'limit comparison', 'alternating series test', 'ratio test', 'root test',
              'telescoping series', 'power / Taylor series']
MORE = ('That was not enough. Give one level more help than your previous answer, on this ladder: '
        'nudge → name the technique and colour-code the parts → ghost the next line → show the full fix.')

SYSTEM = r"""You are a calculus tutor looking over a student's shoulder at a screenshot of their handwritten work (usually xournal++). You answer by drawing on their screen, the way a teacher marks work with coloured pens. The student learns by seeing, not by reading, so words are a last resort.
You get one screenshot per monitor. The focused one usually holds the student's work; the others may show a tutorial, lecture or problem sheet. Use them, and mark them too when it helps (e.g. circle the matching step in the tutorial).
You may also get the whole current page of their xournal notes. The screen often shows only part of it, so use the page for context (the problem statement may be scrolled away), but put your marks on the screenshots only.
This is one long tutoring conversation: earlier messages hold earlier screenshots, questions and your answers, so use them to follow the student's work. Always answer about the newest screenshots.

Answer as JSON:
- read_as: first transcribe every handwritten line on the screens, top to bottom, as LaTeX (no $). Read carefully; handwriting is messy. Use the maths around a symbol to resolve what it is.
- verdict: correct | mistake | unsure | hint | answer.
- headline: at most 5 words, e.g. "Sign slip in line 4", "All correct", "Try integration by parts".
- marks: at most 6, fewer is better. Each mark:
  - screen: which screenshot the box is on (0-based, left to right).
  - box: [x0, y0, x1, y1] in that screenshot's pixels, tight around exactly the symbols you mean (one term, not the whole line, unless the whole line is meant).
  - shape: circle (ring around a term), mark (highlighter), underline, wavy (wavy underline), strike (cross out; correction goes in "write"), check (tick after a correct line; box = that line), box (rectangle), ghost (faint suggested writing placed in EMPTY space; box = where it goes, "write" = the LaTeX).
  - role: error (wrong), fix (the correction), carry (only wrong because of an earlier error), unsure (can't read it / suspicious), ok (correct), a / b / c (neutral hint colours; things that belong together get the same letter, e.g. u and du both a), ask (a question for the student; the note is the question).
  - note: optional, at most 6 words, shown in a bubble with an arrow to the mark. Prefer maths over words: "$-\frac{7}{64}$" beats "the coefficient should be negative".
  - write: what to write for strike corrections and ghosts, e.g. "$\frac{3}{4}\sin 2\theta$".
  - why: optional, one short plain-language sentence, shown only when the student hovers the mark.
  - link: optional 0-based index of another mark; draws an arrow from this mark to that one (cause → effect, "this becomes that").
  - step: drawing order 1, 2, 3, ... (marks appear one at a time).
- drill, plot: only when the task asks for them.

Text format for headline, note, write, why and drill texts: plain words, with every bit of maths inside $...$, e.g. "which angle has $\sin\theta=1$?". Never leave maths bare: not x^2, sqrt(x), pi/2, ->, <= but $x^2$, $\sqrt{x}$, $\frac{\pi}{2}$, $\to$, $\leq$. Words go outside the $...$ (or in \text{...}). It is typeset with LaTeX (amsmath, amssymb, cancel) on one line: no line breaks, no display environments other than cases.

Rules:
- Never invent a mistake. Many pages are correct; then say so (verdict correct, a check after each line).
- If you are not sure you read a symbol right, use role unsure instead of error.
- Don't do the student's work for them: a hint should make them think, unless they ask for the solution.
- Ignore app toolbars and anything that is not maths."""

TASKS = {
    'check': 'Check this work for mistakes. Circle the first real error (role error) with a note that shows the fix. '
             'Give later lines that inherit it a dashed underline (shape underline, role carry) and link the error to them. '
             'Tick (check, role ok) each line that is right before the error. Include the final answer. '
             'If everything is right, tick every line and say so in the headline (verdict correct). '
             'If the error comes from misusing something in an earlier line, highlight that source (role a) and link it to the error.',
    'nudge': 'I am stuck. Give the smallest possible hint: highlight the one thing I should look at (role a) '
             'with a note of at most 4 words. Do not give the next step.',
    'explain': 'I drew a cyan rectangle around a step I do not understand. Show how it follows from the line before it: '
               'highlight matching pieces in both lines with the same role letter and link each source to its result.',
    'final': 'I think I am done. Check my solution as a whole: is the final answer correct, and is anything missing '
             '(e.g. +C, absolute values, evaluating the bounds, cases, domain, simplifying, or not answering what was asked)? '
             'Tick the final answer if right; if wrong, circle it and put the correct answer in a note. '
             'Ghost each missing piece where it belongs (role fix). If it is complete and correct, say so in the headline (verdict correct).',
    'box': 'I drew a cyan rectangle around part of my work. Answer only about that part: ',
    'technique': 'Which technique fits the integral, limit or series I am working on (or about to start)? Do not solve it and do not '
                 'name any method. Colour the features that point to the method (shape mark or circle, roles a, b, c; pieces that '
                 'work together share a letter), each with a note of at most 5 words naming the feature, e.g. "root of $a^2-x^2$", '
                 '"polynomial times $e^x$", "factorials", "top degree $\\geq$ bottom degree". Headline: "Which technique fits?", '
                 'verdict hint. I will pick a method next.',
    'pick': 'I pick: {}. Is that a good method here? Verdict correct if it works well, hint if it works but another is clearly '
            'easier (name that one), mistake if it does not work. The headline says so, e.g. "Yes: integration by parts". '
            'Mark the deciding feature with a note on why, at most 6 words. Do not solve the problem.',
    'why': 'Quiz me on my reasoning. Pick the 1 or 2 steps where understanding matters most (a substitution choice, an identity, '
           'a sign, a change of bounds, why a test applies). At each, put a mark (shape box, role ask) whose note is a short question, '
           'e.g. "Why $u=\\sin\\theta$ here?", "Where did the $\\frac{1}{2}$ go?". Do not hint at the answer. '
           'Headline: "Explain these steps", verdict hint.',
    'why_typed': 'My answer to your question(s): "{}". Grade my understanding: verdict correct if I got the key idea, mistake if not. '
                 'Tick the step (check, role ok) if I understood it; otherwise put the key idea in a note at the step, at most 6 words. '
                 'Ask nothing new.',
    'why_written': 'I wrote my answer(s) to your question(s) on the page, next to the steps. Grade them: verdict correct if I got the '
                   'key idea, mistake if not. Tick each answer I got right (check, role ok); otherwise put the key idea in a note next '
                   'to my answer, at most 6 words. Ask nothing new.',
    'written': 'I wrote more after your last answer. Check the new part only: circle the first real error (role error) with a note '
               'that shows the fix, and tick each new line that is right. If it is all right, say so in the headline (verdict correct).',
    'drill': 'Find-the-error drill. Write a short worked solution (4 to 8 lines) to a NEW problem of the same kind as mine on screen: '
             'same technique, a different function or different numbers. Plant exactly one realistic mistake, the kind students really '
             'make (if I made a mistake earlier in this conversation, plant that kind). Lines before it are right; lines after it carry '
             'the mistake on consistently, the way a student would. Put it all in drill. Headline "Find the mistake", verdict hint, '
             'no marks, read_as empty.',
    'drill_more': 'Another drill like that: a new problem of the same kind, with a different planted mistake.',
    'show': 'Show me visually what is going on, 3Blue1Brown style: put one animation in plot, with the actual function from my '
            'work. Pick the kind that matches what the problem is about, not the fanciest one: a definite integral is an area '
            '(area, or riemann to see it as a sum); revolution only when the problem itself asks for a volume or a solid of '
            'revolution. Circle (role a) the part of my work it shows. Headline: what to watch, e.g. "Watch the rectangles fill '
            'the area", verdict hint.',
    'show_boxes': 'I drew numbered cyan boxes round exactly what I want to see. Show me that, 3Blue1Brown style: put one '
                  'animation in plot, built from what is inside the boxes and nothing else (several boxes: one picture that uses '
                  'them together, e.g. two functions: curves; a function and its bounds: area). Pick the kind that matches what '
                  'is boxed: a definite integral is an area (area or riemann); revolution only if the boxed problem asks for a '
                  'volume or a solid of revolution. Circle (role a) each boxed part. Headline: what to watch, verdict hint.',
}

FMT = 'Plain words; EVERY bit of maths, even a lone x or arcsin(1), inside $...$ as LaTeX.'
EXPR = ('A formula in Python syntax with explicit *: x**2, 3*x, sqrt(x), exp(-x), log(x) for ln, abs(x), sin(x), arctan(x), '
        'factorial(n), pi, e. No $ and no LaTeX.')
PLOT_KINDS = {  # kind: what its fields mean (also tells Claude how to fill them)
    'area': 'area under f(x) from a to b, filling up; g(x) = lower curve for the area between two curves',
    'riemann': 'rectangles under f(x) on [a, b], doubling up to n of them, closing in on the integral',
    'improper': 'f(x) on [a, b] with b = "inf" (or f blowing up at an end): the bound moves out and the area converges or not; toward = which end moves',
    'substitution': 'u = g(x) as a stretch of the x-axis: f(g(x))g\'(x) on [a, b] morphs into f(u) on [g(a), g(b)]; f is in u',
    'revolution': 'ONLY for volumes / solids of revolution: the region under f(x) on [a, b] spun around the axis into a solid; g(x) = inner radius (washers)',
    'series': 'terms f(n) and partial sums from n = a, n terms',
    'taylor': 'f(x) and its Taylor polynomials adding one term at a time; g = the k-th term in k and x; x from a to b; n terms',
    'polar': 'r = f(t) (t is θ) traced from t = a to b, sweeping out its area',
    'parametric': 'x = f(t), y = g(t) traced from t = a to b',
    'curves': 'f(x) and g(x) on [a, b] drawn together, e.g. for a comparison test',
}
DRILL = {
    'type': 'object', 'additionalProperties': False, 'required': ['problem', 'lines', 'wrong', 'fix', 'why'],
    'properties': {
        'problem': {'type': 'string', 'description': 'the task, one line. ' + FMT},
        'lines': {'type': 'array', 'items': {'type': 'string'}, 'description': 'the worked solution, one step a line. ' + FMT},
        'wrong': {'type': 'integer', 'description': '0-based index of the line with the planted mistake'},
        'fix': {'type': 'string', 'description': 'that line done right. ' + FMT},
        'why': {'type': 'string', 'description': 'what went wrong, one short sentence. ' + FMT}}}
PLOT = {
    'type': 'object', 'additionalProperties': False, 'required': ['kind', 'f', 'a', 'b'],
    'properties': {
        'kind': {'enum': list(PLOT_KINDS), 'description': '; '.join(f'{k}: {v}' for k, v in PLOT_KINDS.items())},
        'title': {'type': 'string', 'description': 'shown above the animation, e.g. "$\\int_0^2 x e^{-x}\\,dx$". ' + FMT},
        'f': {'type': 'string', 'description': 'the main formula (in x; n for series; t for polar and parametric). ' + EXPR},
        'g': {'type': 'string', 'description': 'the second formula, if the kind uses one. ' + EXPR},
        'a': {'type': 'string', 'description': 'start, a number or constant formula, e.g. "0", "pi/2", "-inf"'},
        'b': {'type': 'string', 'description': 'end, e.g. "1", "2*pi", "inf"'},
        'n': {'type': 'integer', 'description': 'how many rectangles, terms or Taylor terms at most'},
        'axis': {'enum': ['x', 'y'], 'description': 'revolution: the axis it spins around'},
        'toward': {'enum': ['a', 'b'], 'description': 'improper: the end that moves'}}}
SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['read_as', 'verdict', 'headline', 'marks'],
    'properties': {
        'read_as': {'type': 'array', 'items': {'type': 'string'}},
        'verdict': {'enum': ['correct', 'mistake', 'unsure', 'hint', 'answer']},
        'headline': {'type': 'string', 'description': FMT},
        'marks': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['shape', 'role', 'screen', 'box'],
            'properties': {
                'screen': {'type': 'integer', 'description': 'index of the screenshot the box is on'},
                'shape': {'enum': ['circle', 'mark', 'underline', 'wavy', 'strike', 'check', 'box', 'ghost']},
                'role': {'enum': ['error', 'fix', 'carry', 'unsure', 'ok', 'a', 'b', 'c', 'ask']},
                'box': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4},
                'note': {'type': 'string', 'description': FMT}, 'write': {'type': 'string', 'description': FMT},
                'why': {'type': 'string', 'description': FMT},
                'link': {'type': 'integer'}, 'step': {'type': 'integer'}}}},
        'drill': DRILL,
        'plot': PLOT}}
