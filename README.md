<p align="center"><img src="docs/banner.png" alt="penmentor" width="100%"></p>

<p align="center">
A maths mentor at the tip of your pen. Press a key while you work by hand: Claude marks your work on the screen like a<br>
teacher with coloured pens, gives you hints instead of answers, and shows the idea as a 3Blue1Brown-style animation.
</p>

<p align="center"><img src="docs/showme.gif" alt="Show me: Riemann sums closing in on the integral of sin x from 0 to π" width="760"></p>

## Why I use it

I study calculus with a pen tablet in xournal++. I kept screenshotting my work into Claude and reading long answers
back, when what I wanted was a teacher looking over my shoulder: circle the mistake, tick what's right, nudge me toward
the next step, and *show* me why. penmentor is that, one key away, on my own Claude subscription.

## How it helps you learn

- **Hints, not answers.** A ladder from a nudge to naming the technique to a faint ghost of the next line: you do
  the thinking, which is what makes it stick.
- **Feedback on your own work.** The first real mistake circled where you made it, correct lines ticked, later lines
  that inherit the mistake underlined.
- **Practice that makes you recall.** Questions on your key steps (answer by typing or by writing), find-the-error
  drills, "which technique fits?".
- **See it.** Box what you want to understand and get an interactive animation made with 3Blue1Brown's own
  [manim](https://github.com/3b1b/manim): drag the bounds, retype a value, watch Riemann sums close in.
- **Whole page aware.** A small xournal++ plugin shares the page you are on, not just what fits on screen.

## Quick start

```sh
git clone https://github.com/AbdullahAlhariri/penmentor ~/src/penmentor
~/src/penmentor/bin/penmentor --selftest
```

Linux on X11 (best with i3), with [Claude Code](https://claude.com/claude-code) logged in, `rofi`, `slop`, `xdotool`
and PyQt6. Bind `bin/penmentor` to a key ([example](contrib/i3.conf)). Setup, keys and how it works: [the guide](docs/guide.md).

## License

[MIT](LICENSE)
