"""Renders the README's pictures with manim, the way penmentor draws its own:

    ~/.local/share/penmentor/manim/bin/python docs/assets.py      writes docs/banner.png and docs/showme.gif (needs ffmpeg)
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS.parent / 'src'))
from penmentor import plot  # noqa: E402  (sets up manim with 3b1b's settings)
from penmentor.plot import (BLUE, DOWN, GREEN, GREY_B, LEFT, RIGHT, UP, WHITE, YELLOW, Axes, Circle, Dot,  # noqa: E402
                      Scene, Tex, Text, VGroup, curve, np, region)


class Banner(Scene):
    """The wordmark beside a little plot: an area filling under a curve, rectangles, a teacher's circle. Laid out in
    the middle strip of manim's 16:9 frame (its camera assumes 16:9), which banner() then crops out."""

    def construct(self):
        word = Text('penmentor', font_size=104)
        line = Text('a maths mentor at the tip of your pen:\nhints, not answers, so you really learn', font_size=26).set_color(GREY_B)
        left = VGroup(word, line).arrange(DOWN, aligned_edge=LEFT, buff=.3).move_to(LEFT * 3.7)
        axes = Axes((0, 4, 1), (0, 1.2, .5), width=6.4, height=3.1).move_to(RIGHT * 3.4 + DOWN * .1)
        f = lambda x: 1.6 * x * np.exp(-x) + .1
        xs = np.linspace(0, 4, 300)
        rects = VGroup(*[plot.Polygon(axes.c2p(x, 0), axes.c2p(x + .25, 0), axes.c2p(x + .25, f(x + .125)), axes.c2p(x, f(x + .125)))
                         for x in np.arange(.5, 3, .25)])
        rects.set_submobject_colors_by_gradient(BLUE, GREEN).set_style(stroke_color='#000000', stroke_width=1.5, fill_opacity=.75)
        peak = axes.c2p(1, f(1))
        ring = Circle(radius=.36).move_to(peak).stretch(1.3, 0).rotate(.2).set_stroke(YELLOW, 4)
        mark = VGroup(Dot(peak, radius=.055, fill_color=WHITE), Tex(r'(1,\ 0.69)', font_size=24).next_to(peak, UP, buff=.45))
        self.add(left, region(axes, xs, f(xs), 0 * xs, BLUE, .18), rects, axes, curve(axes, xs, f(xs), BLUE, 4), ring, mark)


def banner(out):
    plot.cmu_serif()
    scene = Banner(camera_config=dict(resolution=(2560, 1440)), skip_animations=True)
    scene.run()
    scene.update_frame(force_draw=True)
    scene.get_image().convert('RGB').crop((0, 360, 2560, 1080)).save(out)  # the middle strip: 2560 x 720


class Recording(plot.Show):
    """A Show-me window's intro, frame by frame."""

    def __init__(self, folder, **kw):
        self.folder, self.n = folder, 0
        super().__init__(**kw)

    def emit_frame(self):
        self.get_image().convert('RGB').save(self.folder / f'{self.n:05d}.png')
        self.n += 1


def gif(spec, out, seconds_after=1.5):
    plot.cmu_serif()
    with tempfile.TemporaryDirectory() as d:
        scene = Recording(Path(d), spec=spec)
        scene.setup()
        scene.construct()
        scene.wait(seconds_after)  # hold the last frame a little
        # two-pass palette: smooth gradients and crisp text at a sane size
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', '30', '-i', f'{d}/%05d.png', '-vf',
                        'fps=20,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];'
                        '[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle', str(out)], check=True)


if __name__ == '__main__':
    if not shutil.which('ffmpeg'):
        sys.exit('needs ffmpeg')
    banner(DOCS / 'banner.png')
    gif(dict(kind='riemann', f='sin(x)', a='0', b='pi', n=32, title=r'Riemann sums for $\int_0^\pi \sin x\,dx$'), DOCS / 'showme.gif')
    print('wrote', DOCS / 'banner.png', DOCS / 'showme.gif')
