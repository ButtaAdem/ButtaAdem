"""Build assets/dove.svg (animated, CSS-only so it runs inside a GitHub README)."""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dove import COLS, ROWS, N_FRAMES, STILL_FRAME           # noqa: E402
from glyphs import build_frames                              # noqa: E402

FONT = 13.3                  # px
CW = 8.0                     # cell width px  (0.6 em, typical monospace advance)
CH = 13.0                    # cell height px (line pitch) -> 8:13 matches the raster cell
WIDTH, HEIGHT = COLS * CW, ROWS * CH
FPS = 12
BG = "#050505"
FG = "#f2f2f2"


def frame_svg(frame) -> str:
    """Per row: stretches of 4+ equal-depth glyphs (the dove) become <tspan> runs; scattered glyphs
    (rain, after-image) go in ONE <text> per depth with a list of x positions - far cheaper."""
    rows, dims = frame
    out = []
    for r, (row, dim) in enumerate(zip(rows, dims)):
        y = f"{(r + 1) * CH - 2.6:.1f}"
        runs, loose, c = [], {"0": [], "1": []}, 0
        while c < COLS:
            if row[c] == " ":
                c += 1
                continue
            start, dv = c, dim[c]
            while c < COLS and row[c] != " " and dim[c] == dv:
                c += 1
            if dv == "0" and c - start >= 4:
                runs.append(f'<tspan x="{start * CW:.0f}">{html.escape(row[start:c], quote=False)}</tspan>')
            else:
                loose[dv].extend(range(start, c))
        if runs:
            out.append(f'<text y="{y}">{"".join(runs)}</text>')
        for dv, cells in loose.items():
            if cells:
                xs = " ".join(f"{i * CW:.0f}" for i in cells)
                cls = "" if dv == "0" else f' class="d{dv}"'
                out.append(f'<text{cls} y="{y}" x="{xs}">{html.escape("".join(row[i] for i in cells), quote=False)}</text>')
    return "".join(out)


def build(path: Path, n: int = N_FRAMES) -> int:
    frames = build_frames(n)
    dur = n / FPS
    step = 100.0 / n
    css = f"""
.bg{{fill:{BG}}}
text{{font-family:'JetBrains Mono','DejaVu Sans Mono',Menlo,Consolas,'Liberation Mono',monospace;font-size:{FONT}px;font-weight:700;font-variant-ligatures:none;font-feature-settings:'liga' 0,'calt' 0;fill:{FG};stroke:{FG};stroke-width:.8px;stroke-linejoin:round;white-space:pre}}
.d1{{fill-opacity:.62;stroke-opacity:.62}}.d2{{fill-opacity:.34;stroke-opacity:.34}}
.f{{opacity:0;animation:s {dur:.4f}s steps(1,end) infinite}}
@keyframes s{{0%{{opacity:1}}{step:.4f}%{{opacity:0}}100%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.f{{animation:none}}.f.still{{opacity:1}}}}
""".strip()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH:.0f} {HEIGHT:.0f}" width="{WIDTH:.0f}" height="{HEIGHT:.0f}" role="img" aria-label="A white dove made of falling matrix glyphs, flapping its wings">',
        f"<style>{css}</style>",
        f'<rect class="bg" width="{WIDTH:.0f}" height="{HEIGHT:.0f}" rx="14"/>',
    ]
    for i, rows in enumerate(frames):
        parts.append(f'<g class="f{" still" if i == STILL_FRAME else ""}" style="animation-delay:{-(dur - i / FPS):.4f}s">{frame_svg(rows)}</g>')
    parts.append("</svg>")
    path.write_text("".join(parts), encoding="utf-8")
    return path.stat().st_size


if __name__ == "__main__":
    out = Path(__file__).parent.parent / "assets" / "dove.svg"
    size = build(out)
    print(f"wrote {out}  {size/1024:.0f} KB  ({N_FRAMES} frames @ {FPS} fps, {COLS}x{ROWS} cells)")
