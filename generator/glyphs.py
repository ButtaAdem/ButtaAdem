"""
Brightness rasters -> animated matrix-glyph frames.

Every glyph's real ink density is measured from the font and bucketed into a
tonal ramp; a cell's brightness selects a bucket and a random glyph inside it.
So the *density* of characters describes the anatomy: dense on the breast and
leading wing edge (bright), medium across feather surfaces, sparse at the
trailing tips (dim).

Behaviour on top of that:
  * interior cells swap glyphs quickly (shimmering feathers); the face and the
    outer contour swap slowly, so the dove keeps its shape between frames
  * the dissolving trail is sampled from the TAIL only and drifts back/down
  * rain is kept out of a zone in front of the beak
All state is a pure function of (frame mod N), so the loop is seamless.
"""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from dove import COLS, ROWS, SX, SY, N_FRAMES, render, render_wings

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/Library/Fonts/Courier New Bold.ttf",
    "C:/Windows/Fonts/consolab.ttf",
]
FONT_FILE = next((f for f in FONT_CANDIDATES if os.path.exists(f)), "DejaVuSansMono-Bold.ttf")
CELL_W, CELL_H, FONT_PX = 8, 13, 13
CANDIDATES = [chr(c) for c in range(33, 127)]
K = 10                      # tonal buckets
BLANK_BELOW = 0.045         # raw brightness below this -> empty cell
GAMMA = 0.80               # curve for the quiet layers (trail, rain)
LIFT_FLOOR, LIFT_GAMMA = 0.22, 0.75   # bird: every bird cell stays visible, bright stays densest
FAST, SLOW = 3, 12          # frames between glyph swaps: interior vs face/contour
HOLD = 2.0                  # buckets of brightness drift a slow cell tolerates before changing

# background: Matrix rain over the whole canvas - evenly spaced columns, long streams of light
# punctuation, a brighter letter at the head
RAIN_STREAMS = 100           # about half the columns carry a stream at any moment
RAIN_HEAD = (0.50, 0.70)     # head brightness (a letter / digit)
RAIN_BODY = (0.17, 0.27)     # brightness just behind the head; fades to nothing (punctuation)
RAIN_TAIL = (12, 32)         # tail length in rows
RAIN_SPEED = (1.0, 2.6)      # rows per frame

# after-image: the wings (and tail) leave ghosts that drift back/down and dissolve into sparse glyphs
TRAIL_FRAMES = 9
TRAIL_DECAY = 0.74
TRAIL_DX = 1.7               # cells drifted back per frame of age
TRAIL_DY = 0.55              # cells drifted down per frame of age
TRAIL_GAIN = 0.95
TRAIL_KEEP = (0.82, 0.075, 0.08)   # share of cells kept: start, loss per frame of age, floor


@lru_cache(maxsize=1)
def ramp() -> list[list[str]]:
    """Glyphs bucketed into K equal-population ink-density classes (dim -> dense)."""
    font = ImageFont.truetype(FONT_FILE, FONT_PX)
    ink = {}
    for ch in CANDIDATES:
        im = Image.new("L", (CELL_W, CELL_H), 0)
        ImageDraw.Draw(im).text((0, 0), ch, font=font, fill=255)
        ink[ch] = np.asarray(im, np.float32).mean() / 255.0
    ordered = [c for c in sorted(CANDIDATES, key=lambda c: ink[c]) if ink[c] > 0.03]
    return [ordered[i * len(ordered) // K:(i + 1) * len(ordered) // K] for i in range(K)]


def cell_brightness(img: np.ndarray) -> np.ndarray:
    return img.reshape(ROWS, SY, COLS, SX).mean(axis=(1, 3))


def _shift(a: np.ndarray, dx: int, dy: int) -> np.ndarray:
    out = np.zeros_like(a)
    h, w = a.shape
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(dx, w), slice(0, w - dx)) if dx >= 0 else (slice(0, w + dx), slice(-dx, w))
    out[yd, xd] = a[ys, xs]
    return out


def _contour(mask: np.ndarray) -> np.ndarray:
    """Cells on the outer edge of a boolean mask."""
    inner = mask.copy()
    inner[1:] &= mask[:-1]
    inner[:-1] &= mask[1:]
    inner[:, 1:] &= mask[:, :-1]
    inner[:, :-1] &= mask[:, 1:]
    return mask & ~inner


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    f = mask.astype(np.float32)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= _shift(f, dx, dy) > 0
    return out


def _make_streams(rng, n):
    """Rain streams with a life cycle (born, fall, fade).  A stream is a pure function of
    (t - f0) mod n, so the loop is seamless.  Columns are spread evenly (with a little jitter).
    Streams are born anywhere along the column - from just above the canvas to just below it - so every
    row gets the same amount of rain (born only at the top, the lower half of the canvas stayed empty)."""
    cols = np.round(np.linspace(0, COLS - 1, RAIN_STREAMS) + rng.uniform(-1.1, 1.1, RAIN_STREAMS))
    cols = np.clip(cols, 0, COLS - 1).astype(int)
    life = n - 3                                             # a few frames of rest keep the loop seam clean
    streams = []
    for c in cols:
        tail = int(rng.integers(*RAIN_TAIL))
        speed = float(rng.uniform(*RAIN_SPEED))
        r0 = float(rng.uniform(-0.6 * speed * life, ROWS + 12))   # heads born slightly below still light the bottom rows
        streams.append(dict(col=int(c), tail=tail, r0=r0, speed=speed, life=life, f0=int(rng.integers(0, n)),
                            head=float(rng.uniform(*RAIN_HEAD)), body=float(rng.uniform(*RAIN_BODY))))
    return streams


def _rain(t, n, streams):
    """-> (field, heads): a bright head falls down each column, a light tail fading behind it."""
    field = np.zeros((ROWS, COLS), np.float32)
    heads = np.zeros((ROWS, COLS), bool)
    r = np.arange(ROWS)
    for st in streams:
        a = (t - st["f0"]) % n
        if a >= st["life"]:
            continue
        env = min(1.0, (a + 1) / 2.0, (st["life"] - a) / 4.0)
        head = st["r0"] + st["speed"] * a
        d = head - r
        body = st["body"] * np.clip(1 - d / st["tail"], 0, 1) ** 0.9
        v = np.where((d >= 0) & (d < st["tail"]), np.where(d < 1, st["head"], body), 0.0) * env
        c = st["col"]
        field[:, c] = np.maximum(field[:, c], v)
        hr = int(np.floor(head))
        if 0 <= hr < ROWS and v[hr] > 0:
            heads[hr, c] = True
    return field, heads


def build_frames(n: int = N_FRAMES, seed: int = 7):
    """Returns frames -> (rows, dims): rows are strings of length COLS (space = empty); dims are
    strings of '0' (full) or '1' (dim) per cell."""
    rng = np.random.default_rng(seed)
    buckets = ramp()

    birds, tails, wings, metas = [], [], [], []
    for t in range(n):
        img, tail, meta = render(t, n)
        birds.append(np.clip(cell_brightness(img), 0, 1))
        tails.append(np.clip(cell_brightness(tail), 0, 1))
        wings.append(np.clip(cell_brightness(render_wings(t, n)), 0, 1))
        metas.append(meta)

    # the dove's glyph picks keep the original draw order (never reshuffled by the background)
    glyph_rand = rng.integers(0, 1 << 16, size=(ROWS, COLS, n // FAST + 2))
    offsets = rng.integers(0, n, size=(ROWS, COLS))
    speckle = rng.random((n, ROWS, COLS))
    rng = np.random.default_rng(seed + 1000)
    head_rand = rng.integers(0, 1 << 16, size=(n, ROWS, COLS))
    CC, RR = np.meshgrid(np.arange(COLS), np.arange(ROWS))
    streams = _make_streams(rng, n)

    frames = []
    prev_cls = None
    for step in range(2 * n):        # two passes: the first only warms the hysteresis memory
        t = step % n
        B, meta = birds[t], metas[t]

        # after-image: ghosts of the wings and tail, drifting back/down, thinning out with age
        trail = np.zeros_like(B)
        for a in range(1, TRAIL_FRAMES + 1):
            src = np.maximum(tails[(t - a) % n], wings[(t - a) % n])
            moved = _shift(src, int(round(a * TRAIL_DX)), int(round(a * TRAIL_DY)))
            keep = speckle[(t + a) % n] < max(TRAIL_KEEP[2], TRAIL_KEEP[0] - TRAIL_KEEP[1] * a)
            trail = np.maximum(trail, moved * keep * (TRAIL_DECAY ** a) * TRAIL_GAIN)

        # rain: passes behind the dove (a thin dark halo keeps its edge crisp); a pocket stays clear ahead of the beak
        rain, rain_head = _rain(t, n, streams)
        halo = _dilate(B > 0.04, 1)
        trail = trail * (~halo)
        br, bc = meta["beak"]
        zone = ((CC - (bc + 8)) / 17.0) ** 2 + ((RR - br) / 9.0) ** 2
        rain = rain * ((~halo) & (zone > 1.0))

        # ---- which layer owns each cell?  (higher tone wins; the dove always wins where it is solid)
        lift = np.where(B > BLANK_BELOW, LIFT_FLOOR + (1 - LIFT_FLOOR) * B ** LIFT_GAMMA, 0.0)
        layers = [
            (3, np.where(rain > BLANK_BELOW, rain ** GAMMA, 0.0)),
            (2, np.where(trail > BLANK_BELOW, trail ** GAMMA, 0.0)),
        ]
        tone, src_map = np.zeros_like(B), np.zeros(B.shape, int)
        for code, tarr in layers:
            m = tarr > tone
            tone, src_map = np.where(m, tarr, tone), np.where(m, code, src_map)
        m = (lift > 0) & ((B > 0.12) | (lift > tone))
        tone, src_map = np.where(m, lift, tone), np.where(m, 1, src_map)
        cls = np.clip((tone * K).astype(int), 0, K - 1)

        # face + outer contour hold their glyphs longer
        hr, hc = meta["head"]
        face = ((CC - hc) / 7.0) ** 2 + ((RR - hr) / 4.5) ** 2 < 1
        slow = (_contour(B > 0.10) | face) & (B > 0.10)
        if prev_cls is not None:
            hold = slow & (np.abs(tone * K - (prev_cls + 0.5)) < HOLD)
            cls = np.where(hold, prev_cls, cls)
        prev_cls = cls

        ph = (t + offsets) % n
        pick_fast = np.take_along_axis(glyph_rand, (ph // FAST)[..., None], axis=2)[..., 0]
        pick_slow = np.take_along_axis(glyph_rand, (ph // SLOW)[..., None], axis=2)[..., 0]
        pick = np.where(slow, pick_slow, pick_fast)
        head_pick = head_rand[t]

        rows, dims = [], []
        for r in range(ROWS):
            chars, dd = [], []
            for c in range(COLS):
                code = src_map[r, c]
                if code == 0:
                    chars.append(" "); dd.append("0")
                    continue
                pool = buckets[cls[r, c]]
                if code == 1:                                          # the dove
                    chars.append(pool[pick[r, c] % len(pool)]); dd.append("0")
                elif code == 2:                                        # after-image: fades with age
                    chars.append(pool[pick[r, c] % len(pool)]); dd.append("0" if tone[r, c] > 0.42 else "1")
                else:                                                  # rain: a flickering head, a steadier tail
                    chars.append(pool[(head_pick[r, c] if rain_head[r, c] else pick[r, c]) % len(pool)]); dd.append("0")
            rows.append("".join(chars)); dims.append("".join(dd))
        if step >= n:
            frames.append((rows, dims))
    return frames
