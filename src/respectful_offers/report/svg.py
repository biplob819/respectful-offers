"""Tiny inline-SVG charts for the static report (OWNER D-15): no JavaScript, no external files.

Every series is told apart by colour *and* marker shape *and* a direct label, never colour
alone (RPT-06). Colours are the Okabe–Ito palette, safe for the common colour-vision
deficiencies, and read from CSS custom properties so the page can theme them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

W, H = 640, 360
PAD_L, PAD_R, PAD_T, PAD_B = 64, 150, 24, 52

POLICY_STYLE: dict[str, tuple[str, str]] = {
    # policy: (CSS colour variable, marker)
    "no_offer": ("--c-grey", "circle"),
    "status_quo": ("--c-orange", "square"),
    "rule_following_baseline": ("--c-blue", "triangle"),
    "bandit": ("--c-green", "diamond"),
    "segment_oracle": ("--c-purple", "star"),
    "holdout": ("--c-grey", "cross"),
}
POLICY_SHORT = {  # direct labels in a chart's right margin; tables use the full names
    "no_offer": "No offer",
    "status_quo": "Status quo",
    "rule_following_baseline": "Rule-following",
    "bandit": "Bandit",
    "segment_oracle": "Oracle",
    "holdout": "Holdout",
}
VARIANT_STYLE: dict[str, tuple[str, str]] = {
    "conservative": ("--c-orange", "square"),
    "central": ("--c-blue", "circle"),
    "optimistic": ("--c-green", "triangle"),
}
POLICY_LABEL = {
    "no_offer": "No offer",
    "status_quo": "Status quo (not respectful)",
    "rule_following_baseline": "Rule-following baseline",
    "bandit": "Bandit",
    "segment_oracle": "Segment oracle (ceiling)",
    "holdout": "Holdout",
}


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    lo: float | None = None
    hi: float | None = None
    ref: float | None = None  # a per-row reference value (the exact oracle in the OPE chart)


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return [0.0]
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step  # the last tick covers the largest value
    count = round((end - start) / step)
    return [round(start + i * step, 10) for i in range(count + 1)]


def marker(shape: str, x: float, y: float, colour: str, r: float = 5.0) -> str:
    fill = f'fill="var({colour})" stroke="var(--bg)" stroke-width="1"'
    if shape == "circle":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" {fill}/>'
    if shape == "square":
        return f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" {fill}/>'
    if shape == "triangle":
        pts = f"{x:.1f},{y - r * 1.2:.1f} {x - r * 1.1:.1f},{y + r * 0.8:.1f} {x + r * 1.1:.1f},{y + r * 0.8:.1f}"
        return f'<polygon points="{pts}" {fill}/>'
    if shape == "diamond":
        pts = f"{x:.1f},{y - r * 1.3:.1f} {x + r:.1f},{y:.1f} {x:.1f},{y + r * 1.3:.1f} {x - r:.1f},{y:.1f}"
        return f'<polygon points="{pts}" {fill}/>'
    if shape == "star":
        pts = []
        for i in range(10):
            rad = r * 1.4 if i % 2 == 0 else r * 0.6
            a = math.pi / 2 + i * math.pi / 5
            pts.append(f"{x + rad * math.cos(a):.1f},{y - rad * math.sin(a):.1f}")
        return f'<polygon points="{" ".join(pts)}" {fill}/>'
    d = r
    return (
        f'<path d="M{x - d:.1f},{y - d:.1f}L{x + d:.1f},{y + d:.1f}M{x - d:.1f},{y + d:.1f}'
        f'L{x + d:.1f},{y - d:.1f}" stroke="var({colour})" stroke-width="2.5"/>'
    )


class Frame:
    """Linear axes inside a fixed canvas."""

    def __init__(self, xs: Sequence[float], ys: Sequence[float], x_label: str, y_label: str):
        self.xt = nice_ticks(min(xs), max(xs))
        self.yt = nice_ticks(min(ys), max(ys))
        self.x_label, self.y_label = x_label, y_label

    def x(self, v: float) -> float:
        lo, hi = self.xt[0], self.xt[-1]
        return PAD_L + (v - lo) / ((hi - lo) or 1.0) * (W - PAD_L - PAD_R)

    def y(self, v: float) -> float:
        lo, hi = self.yt[0], self.yt[-1]
        return H - PAD_B - (v - lo) / ((hi - lo) or 1.0) * (H - PAD_T - PAD_B)

    def axes(self) -> str:
        out = []
        for t in self.yt:
            y = self.y(t)
            out.append(
                f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{_fmt(t)}</text>'
            )
        for t in self.xt:
            x = self.x(t)
            out.append(
                f'<text x="{x:.1f}" y="{H - PAD_B + 18}" text-anchor="middle" class="tick">{_fmt(t)}</text>'
            )
        out.append(
            f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{H - PAD_B}" y2="{H - PAD_B}" class="axis"/>'
            f'<text x="{(PAD_L + W - PAD_R) / 2:.1f}" y="{H - 10}" text-anchor="middle" class="label">'
            f"{escape(self.x_label)}</text>"
            f'<text transform="translate(16,{(PAD_T + H - PAD_B) / 2:.1f}) rotate(-90)" '
            f'text-anchor="middle" class="label">{escape(self.y_label)}</text>'
        )
        return "".join(out)


def svg(body: str, title: str, desc: str) -> str:
    return (
        f'<svg viewBox="0 0 {W} {H}" role="img" class="chart">'
        f"<title>{escape(title)}</title><desc>{escape(desc)}</desc>{body}</svg>"
    )


def line_chart(
    series: dict[str, list[Point]],
    x_label: str,
    y_label: str,
    title: str,
    desc: str,
    styles: dict[str, tuple[str, str]] | None = None,
    labels: dict[str, str] | None = None,
) -> str:
    """One line per series, each point with an optional interval whisker, labelled at its end
    with the series' own marker beside the label."""
    styles = POLICY_STYLE if styles is None else styles
    labels = POLICY_SHORT if labels is None else labels
    pts = [p for s in series.values() for p in s]
    ys = [v for p in pts for v in (p.y, p.lo, p.hi) if v is not None]
    f = Frame([p.x for p in pts], ys, x_label, y_label)
    body = [f.axes()]
    label_y: list[float] = []
    for name, s in series.items():
        colour, shape = styles.get(name, ("--c-grey", "circle"))
        s = sorted(s, key=lambda p: p.x)
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{f.x(p.x):.1f},{f.y(p.y):.1f}" for i, p in enumerate(s)
        )
        body.append(f'<path d="{path}" fill="none" stroke="var({colour})" stroke-width="2"/>')
        for p in s:
            if p.lo is not None and p.hi is not None:
                body.append(
                    f'<line x1="{f.x(p.x):.1f}" x2="{f.x(p.x):.1f}" y1="{f.y(p.lo):.1f}" '
                    f'y2="{f.y(p.hi):.1f}" stroke="var({colour})" stroke-width="1.5"/>'
                )
            body.append(marker(shape, f.x(p.x), f.y(p.y), colour))
        end = s[-1]
        ly = f.y(end.y)
        while any(abs(ly - o) < 13 for o in label_y):  # keep direct labels from overlapping
            ly += 13
        label_y.append(ly)
        body.append(marker(shape, W - PAD_R + 14, ly, colour, r=4.0))
        body.append(
            f'<text x="{W - PAD_R + 24}" y="{ly + 4:.1f}" class="series">'
            f"{escape(labels.get(name, name))}</text>"
        )
    return svg("".join(body), title, desc)


def dot_chart(
    rows: list[tuple[str, str, Point]],
    x_label: str,
    title: str,
    desc: str,
    reference: float | None = None,
) -> str:
    """Horizontal dot-and-whisker rows: (row label, policy for style, point with x and lo/hi)."""
    xs = [v for _, _, p in rows for v in (p.x, p.lo, p.hi, p.ref) if v is not None]
    if reference is not None:
        xs.append(reference)
    height = max(H, PAD_T + PAD_B + 26 * len(rows))
    xt = nice_ticks(min(xs), max(xs))
    longest = max((len(label) for label, _, _ in rows), default=10)
    left, right = max(160, int(6.8 * longest) + 24), 30  # room for the longest row label
    width = left + 420 + right

    def X(v: float) -> float:
        return left + (v - xt[0]) / ((xt[-1] - xt[0]) or 1.0) * (width - left - right)

    body = []
    for t in xt:
        body.append(
            f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{PAD_T}" y2="{height - PAD_B}" class="grid"/>'
            f'<text x="{X(t):.1f}" y="{height - PAD_B + 18}" text-anchor="middle" class="tick">{_fmt(t)}</text>'
        )
    if reference is not None:
        body.append(
            f'<line x1="{X(reference):.1f}" x2="{X(reference):.1f}" y1="{PAD_T}" '
            f'y2="{height - PAD_B}" class="ref"/>'
        )
    for i, (label, policy, p) in enumerate(rows):
        y = PAD_T + 13 + 26 * i
        colour, shape = POLICY_STYLE.get(policy, ("--c-grey", "circle"))
        body.append(
            f'<text x="{left - 10}" y="{y + 4}" text-anchor="end" class="series">{escape(label)}</text>'
        )
        if p.lo is not None and p.hi is not None:
            body.append(
                f'<line x1="{X(p.lo):.1f}" x2="{X(p.hi):.1f}" y1="{y}" y2="{y}" '
                f'stroke="var({colour})" stroke-width="2"/>'
            )
        if p.ref is not None:  # the reference as a tall black tick behind the estimate
            body.append(
                f'<line x1="{X(p.ref):.1f}" x2="{X(p.ref):.1f}" y1="{y - 9}" y2="{y + 9}" class="oracle"/>'
            )
        body.append(marker(shape, X(p.x), y, colour))
    body.append(
        f'<text x="{(left + width - right) / 2:.1f}" y="{height - 10}" text-anchor="middle" class="label">'
        f"{escape(x_label)}</text>"
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">'
        f"<title>{escape(title)}</title><desc>{escape(desc)}</desc>{''.join(body)}</svg>"
    )


def reliability_chart(bins: Sequence[tuple[float, float, int]], title: str, desc: str) -> str:
    """Predicted against observed churn per bin, marker area by members, with the diagonal."""
    top = max([0.05, *(max(p, o) for p, o, _ in bins)])
    f = Frame([0.0, top], [0.0, top], "Predicted churn risk", "Observed churn rate")
    body = [
        f.axes(),
        f'<line x1="{f.x(0):.1f}" y1="{f.y(0):.1f}" x2="{f.x(f.xt[-1]):.1f}" y2="{f.y(f.yt[-1]):.1f}" class="ref"/>',
    ]
    biggest = max([1, *(n for _, _, n in bins)])
    for p, o, n in bins:
        r = 3 + 7 * math.sqrt(n / biggest)
        body.append(marker("circle", f.x(p), f.y(o), "--c-blue", r=r))
    return svg("".join(body), title, desc)
