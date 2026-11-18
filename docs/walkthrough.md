# Walkthrough GIF: the screens it shows

`docs/assets/walkthrough.gif` replaces the planned 90-second video (D-57). It is silent, loops,
and holds each screen for 2.5 seconds (22.5 seconds in all, 960 px wide, 128 colours). Every
screen is a real capture of committed outputs, with no keys, no spend and no passkey: the demo
runs locally, where it needs none (OWNER D-48). All outcomes shown are simulated, as each
screen says.

| # | Screen | Source |
|---|---|---|
| 1 | Report: the headline, central variant | `results/kkbox/report/index.html`, top |
| 2 | Report: every policy, central variant | same, `#policies-central` |
| 3 | Report: members kept against discount spent | same, `#frontier-central` |
| 4 | Report: the respect audit, every rollout | same, `#audit` |
| 5 | Report: off-policy estimates against the exact oracle | same, `#ope` |
| 6 | CLI: the release gates with `evalkit gate`, and `offers monitor check` | real output on `results/kkbox/metrics.json`; long rows are summarised in `#` lines, and the claim rows drop their repeated `a`/`b` labels |
| 7 | Demo: the policy simulator | `src/respectful_offers/demo/app.py` on `demo/cube.json`, run locally |
| 8 | Demo: the frontier chart and the live respect audit | same, scrolled |
| 9 | Case study | `docs/site/case-study.html` |

Captured at 1280×800 with headless Chrome over the DevTools protocol (scroll positions and
hiding Streamlit's local toolbar), joined with:

```
ffmpeg -framerate 1/2.5 -i seq%02d.png -vf "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=5" -loop 0 docs/assets/walkthrough.gif
```
