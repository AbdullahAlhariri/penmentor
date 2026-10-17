"""Look of the overlay: colours, text sizes, fonts, spacing."""

PALETTE = {  # Okabe-Ito based so it survives colour blindness; shapes carry the meaning too
    'light': dict(error='#D55E00', fix='#009E73', ok='#009E73', carry='#E69F00', unsure='#E69F00',
                  a='#0072B2', b='#CC79A7', c='#1E9BD7', ask='#6A4CC2', ghost='#7A7F87'),
    'dark': dict(error='#FF6B4A', fix='#35D69B', ok='#35D69B', carry='#FFB224', unsure='#FFB224',
                 a='#4EA8FF', b='#F27BC9', c='#6FE0FF', ask='#B39DFF', ghost='#A3A9B3'),
}
LEGEND = {'error': 'mistake', 'fix': 'correction', 'ok': 'correct', 'carry': 'follows from the mistake',
          'unsure': 'unsure: check this', 'abc': 'same colour = same thing', 'ask': 'question for you',
          'ghost': 'suggested writing'}
VERDICT = {'correct': ('✓', 'ok'), 'mistake': ('✗', 'error'), 'unsure': ('?', 'unsure'), 'hint': ('→', 'a'), 'answer': ('•', 'a')}

UI_FONT = 'CMU Serif'  # 3Blue1Brown's look: CMU Serif words (his manim config), Computer Modern maths (his LaTeX)
HEAD, NOTE, GHOST, FIX, TIP, READ, DRILL = 17, 21, 22, 21, 16, 15, 19  # text sizes in pt; Computer Modern's thin serifs get grainy below ~16
NOTE_CH, TIP_CH = 34, 44  # wrap notes / hover tips at about this many characters
TOP = 36  # top bar's distance from the monitor top: clears i3's 22 px title/tab bar
BAR = 84  # usage-limit bar width in the stats panel, px
SPIN = '#4EA8FF'  # loading arc colour
PANEL = (18, 18, 22)  # panel background
