"""
Procedural 3D dove -> 2D brightness raster (one raster per flap frame).

Anatomy
  * small round head, short tapered beak, full curved breast, gently fanned tail
  * each wing: a broad bright leading band (arm + hand), two rows of coverts,
    then flight feathers that fade toward their tips - secondaries form a
    scalloped trailing edge, primaries end in a few distinct tips
Motion
  * shoulder leads the downstroke, the hand (tips) follows ~1 rad later
  * on the way back up the wrist flexes: the hand sweeps back, shortens and
    the primary fan closes; at the top of the stroke the wing is fully open
  * pitch and bob pivot on the head, so the head stays almost still
Camera
  * nearly side-on, so the wings sweep up and *back*, leaving a wedge of black
    between the near wing and the head; the beak is never occluded
Brightness encodes density downstream: breast / leading edge = 1.0 (densest
glyphs), feather surfaces ~0.6 (medium), trailing tips fade to ~0.2 (sparse).
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

# ---------------------------------------------------------------- canvas ----
COLS, ROWS = 130, 60          # character grid
SX, SY = 8, 13                # raster samples per character cell (w x h)
W, H = COLS * SX, ROWS * SY   # raster size in pixels
UNIT = 262.0                  # pixels per model unit
N_FRAMES = 24                 # frames in one flap cycle
STILL_FRAME = 7               # clearest wings-up pose (used for reduced motion)

# ---------------------------------------------------------------- camera ----
YAW = np.radians(-10.0)       # nearly side-on
PITCH = np.radians(13.0)      # looking slightly down on the bird
CX, CY = W * 0.585, H * 0.604   # where the bird's origin lands on the canvas

HEAD = np.array([0.80, 0.30, 0.0])           # pivot for pitch / bob
SHOULDER = np.array([0.12, 0.12, 0.06])


def rx(phi: float) -> np.ndarray:
    """Rotation about the body (x) axis; +phi lifts a +z wing upward."""
    c, s = np.cos(phi), np.sin(phi)
    return np.array([[1, 0, 0], [0, c, s], [0, -s, c]])


def place(p, beta: float, bob: float) -> np.ndarray:
    """Pitch the bird by `beta` about its head, then bob it (head barely moves)."""
    p = np.atleast_2d(np.asarray(p, float)) - HEAD
    c, s = np.cos(beta), np.sin(beta)
    x = c * p[:, 0] - s * p[:, 1]
    y = s * p[:, 0] + c * p[:, 1]
    return np.column_stack([x + HEAD[0], y + HEAD[1] + bob, p[:, 2] + HEAD[2]])


def project(p: np.ndarray) -> np.ndarray:
    """3D (x fwd, y up, z toward viewer) -> pixel coords."""
    p = np.atleast_2d(p)
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    x1 = x * np.cos(YAW) + z * np.sin(YAW)
    z1 = -x * np.sin(YAW) + z * np.cos(YAW)
    y2 = y * np.cos(PITCH) - z1 * np.sin(PITCH)
    return np.stack([CX + UNIT * x1, CY - UNIT * y2], axis=1)


def catmull_closed(pts, samples=14):
    pts = np.asarray(pts, float)
    n = len(pts)
    out = []
    for i in range(n):
        p0, p1, p2, p3 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        for t in np.linspace(0, 1, samples, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t
                              + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return np.array(out)


# profile (x fwd, y up): slim neck, FULL curved breast, tapering to a narrow tail base.
# (the first four and last point sit under the head and are left as they were)
BODY = [
    (0.88, 0.315), (0.82, 0.385), (0.73, 0.370), (0.62, 0.275), (0.40, 0.235),
    (0.12, 0.225), (-0.20, 0.165), (-0.44, 0.095), (-0.58, 0.040), (-0.58, -0.020),
    (-0.42, -0.090), (-0.18, -0.250), (0.12, -0.340), (0.42, -0.390), (0.64, -0.310),
    (0.78, -0.150), (0.82, 0.060), (0.88, 0.240),
]


def inside(poly, x, y):
    """Point-in-polygon (ray casting) for a 2D polygon given as an (n, 2) array."""
    xs, ys = poly[:, 0], poly[:, 1]
    xs2, ys2 = np.roll(xs, -1), np.roll(ys, -1)
    cond = (ys > y) != (ys2 > y)
    xint = xs + (y - ys) * (xs2 - xs) / (ys2 - ys + 1e-12)
    return bool(np.sum(cond & (x < xint)) % 2)


def val(v: float) -> int:
    return int(np.clip(v, 0, 1) * 255)


def yawvec(deg: float) -> np.ndarray:
    """Unit vector in the wing plane: 0 deg = along the span, 90 deg = straight back."""
    a = np.radians(deg)
    return np.array([-np.sin(a), 0.0, np.cos(a)])


# ---------------------------------------------------------------- feathers ---
def feather(base, d, normal, length, width, curl=0.08, n=12):
    """Leaf-shaped feather: returns (left edge, right edge, centre line) in 3D."""
    d = d / np.linalg.norm(d)
    p = np.cross(normal, d)
    s = np.linspace(0, 1, n)
    centre = base + np.outer(length * s, d) + np.outer(curl * length * s ** 2, p)
    w = width * np.sin(np.pi * s ** 0.62) ** 0.75
    return centre + np.outer(w / 2, p), centre - np.outer(w / 2, p), centre


def item(fe, b0, b1, layer):
    L, R, C = fe
    return dict(L=L, R=R, C=C, b0=b0, b1=b1, layer=layer)


PRIM_LEN = [0.76, 0.88, 0.90, 0.85, 0.77]                      # outermost first


def wing(phi_arm: float, phi_hand: float, fold: float):
    """One (near-side) wing. `fold` 0..1 = upstroke wrist flex."""
    R1, R2 = rx(phi_arm), rx(phi_hand)
    N1, N2 = R1 @ [0, 1, 0], R2 @ [0, 1, 0]
    L1, L2 = 0.62, 0.46 * (1 - 0.14 * fold)
    s2 = 24 + 34 * fold                                   # hand sweeps back when folding
    a1, h2 = R1 @ yawvec(14), R2 @ yawvec(s2)
    S = SHOULDER
    Wr = S + L1 * a1
    T = Wr + L2 * h2
    spread = 1 - 0.24 * fold                              # primary fan closes a little
    items = []

    # secondaries: scalloped trailing edge
    ns = 5
    for j in range(ns):
        f = (j + 0.5) / ns
        base = S + (0.10 + 0.80 * f) * L1 * a1
        d = R1 @ yawvec(98 - 24 * f)
        ln = 0.52 + 0.06 * np.sin(np.pi * f)
        items.append(item(feather(base, d, N1, ln, 0.21, curl=0.06), 0.80, 0.26, 0))

    # primaries: a few distinct tips (outermost drawn last, on top)
    for k in reversed(range(5)):
        f = k / 4
        base = Wr + L2 * 0.9 * (1 - f) * h2
        d = R2 @ yawvec(s2 - 8 + spread * f * 64)
        items.append(item(feather(base, d, N2, PRIM_LEN[k], 0.125 + 0.025 * f, curl=0.09), 0.84, 0.30, 1))

    # coverts: two short bright rows hide the feather roots
    for row, (ln, wd, br) in enumerate([(0.42, 0.17, 0.90), (0.27, 0.14, 1.0)]):
        npts = 16
        for i in range(npts):
            u = (i + 0.5) / npts
            if u < 0.58:
                f = u / 0.58
                base, R, N, eps = S + f * L1 * a1, R1, N1, 94 - 22 * f
            else:
                f = (u - 0.58) / 0.42
                base, R, N, eps = Wr + f * L2 * 0.9 * h2, R2, N2, s2 + 8
            items.append(item(feather(base, R @ yawvec(eps), N, ln * (1 - 0.28 * f), wd, curl=0.05, n=8),
                              br, br, 2 + row))
    return dict(items=items, S=S, Wr=Wr, T=T)


# ---------------------------------------------------------------- painter ----
def draw_feather(d, it, P, dim=1.0, edges=True):
    L, R, C = P(it["L"]), P(it["R"]), P(it["C"])
    n = len(C)
    for i in range(n - 1):
        s = (i + 0.5) / (n - 1)
        u = np.clip((s - 0.50) / 0.50, 0, 1)
        fade = 1 - u * u * (3 - 2 * u)              # smoothstep: plateau, then fade to the tip
        v = (it["b1"] + (it["b0"] - it["b1"]) * fade) * dim
        d.polygon([tuple(L[i]), tuple(L[i + 1]), tuple(R[i + 1]), tuple(R[i])], fill=val(v * 0.80))
        li, ri = C[i] + (L[i] - C[i]) * 0.5, C[i] + (R[i] - C[i]) * 0.5
        lj, rj = C[i + 1] + (L[i + 1] - C[i + 1]) * 0.5, C[i + 1] + (R[i + 1] - C[i + 1]) * 0.5
        d.polygon([tuple(li), tuple(lj), tuple(rj), tuple(ri)], fill=val(v))
    if edges:
        for E in (L, R):
            d.line([tuple(p) for p in E], fill=val(it["b1"] * dim * 0.45), width=1)


def draw_wing(d, wg, P, dim=1.0, halo=False):
    items = sorted(wg["items"], key=lambda it: it["layer"])
    if halo:                      # black rim: separates the near wing from what is behind it
        for it in items:
            if it["layer"] <= 1:
                pts = [tuple(p) for p in np.vstack([P(it["L"]), P(it["R"])[::-1]])]
                d.polygon(pts, fill=0)
                d.line(pts + [pts[0]], fill=0, width=26, joint="curve")
    for it in items:
        draw_feather(d, it, P, dim, edges=dim > 0.8)
    # broad, continuous leading edge: tapered arm band, then a thinner hand band
    S, Wr, T = P(wg["S"])[0], P(wg["Wr"])[0], P(wg["T"])[0]
    for a_, b_, wa, wb, va, vb in ((S, Wr, 40, 30, 1.0, 1.0), (Wr, T, 30, 11, 1.0, 0.70)):
        dv = b_ - a_
        ln = np.hypot(*dv) or 1.0
        nrm = np.array([-dv[1], dv[0]]) / ln
        steps = 4
        for k in range(steps):
            u0, u1 = k / steps, (k + 1) / steps
            p0, p1 = a_ + dv * u0, a_ + dv * u1
            w0, w1 = wa + (wb - wa) * u0, wa + (wb - wa) * u1
            v = (va + (vb - va) * (u0 + u1) / 2) * dim
            d.polygon([tuple(p0 + nrm * w0 / 2), tuple(p1 + nrm * w1 / 2),
                       tuple(p1 - nrm * w1 / 2), tuple(p0 - nrm * w0 / 2)], fill=val(v))
        d.ellipse([a_[0] - wa / 2, a_[1] - wa / 2, a_[0] + wa / 2, a_[1] + wa / 2], fill=val(va * dim))


def circle(cx, cy, r, n=28):
    a = np.linspace(0, 2 * np.pi, n)
    return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a), np.zeros(n)])


def body_feathers(img, body, body_px, P):
    """Folded back feathers + overlapping breast scales, drawn on a layer and clipped to the body."""
    lay, alp = Image.new("L", (W, H), 0), Image.new("L", (W, H), 0)
    dl, da = ImageDraw.Draw(lay), ImageDraw.Draw(alp)

    # long folded feathers lying along the back (they continue under the wing root)
    for j in range(5):
        base = np.array([0.34 - 0.115 * j, 0.200 - 0.012 * j, 0.0])
        ang = np.radians(10 + 3 * j)
        fe = feather(base, np.array([-np.cos(ang), -np.sin(ang), 0.0]), np.array([0, 0, 1.0]),
                     0.56 + 0.04 * j, 0.14, curl=-0.05)
        it = item(fe, 0.80, 0.52, 0)
        draw_feather(dl, it, P)
        poly = [tuple(q) for q in np.vstack([P(fe[0]), P(fe[1])[::-1]])]
        da.polygon(poly, fill=255)

    # breast / belly feathers: thin dark crescents along each feather's tip, rows overlapping.
    # They *modulate* the shading underneath, so the chest keeps its glow and gains a scalloped grain.
    flow = np.array([-0.30, -0.95]); flow /= np.linalg.norm(flow)
    perp = np.array([-flow[1], flow[0]])
    shrink = np.array([0.46, -0.10]) + (body - np.array([0.46, -0.10])) * 0.97
    edge = Image.new("L", (W, H), 0)
    de = ImageDraw.Draw(edge)
    for ri, y in enumerate(np.arange(-0.37, 0.07, 0.068)):
        for x in np.arange(-0.06 + 0.043 * (ri % 2), 0.80, 0.086):
            if not inside(shrink, x, y) or (x > 0.62 and y > -0.04):
                continue
            c = np.array([x, y])
            th = np.linspace(-0.95, 0.95, 9)                      # a crescent hugging the feather tip
            arc = np.array([c + flow * (0.050 * np.cos(a_) + 0.018) + perp * 0.058 * np.sin(a_) for a_ in th])
            xy = [tuple(q) for q in P(np.column_stack([arc, np.zeros(len(arc))]))]
            de.line(xy, fill=255, width=3, joint="curve")
    edge = edge.filter(ImageFilter.GaussianBlur(1.1))

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(body_px, fill=255)
    m = np.asarray(mask, np.float32) / 255.0
    e = np.asarray(edge, np.float32) / 255.0
    base = np.asarray(img, np.float32)
    out = base * (1 - 0.34 * e * m)
    img.paste(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)))
    # feathers folded along the back (kept from the layer above)
    img.paste(lay, mask=ImageChops.multiply(alp, mask))


def _pose(t: int, n: int):
    """Flap pose for frame t: (phase w, near arm, near hand, near fold, far arm, far hand, far fold, pitch, bob)."""
    w = 2 * np.pi * t / n
    # shoulder leads, hand lags ~1 rad; wrist flexes on the upstroke
    phi1, phi2 = np.radians(16 + 58 * np.sin(w)), np.radians(16 + 72 * np.sin(w - 1.0))
    fold = max(0.0, np.cos(w + 0.2))
    # far wing: a touch smaller and out of step, so the two wings never fuse
    wf = w - 0.35
    phi1f, phi2f = np.radians(14 + 52 * np.sin(wf)), np.radians(14 + 66 * np.sin(wf - 1.0))
    foldf = max(0.0, np.cos(wf + 0.2))
    beta = np.radians(3 + 4 * np.sin(w - 0.3))
    bob = 0.012 * np.sin(w - 0.5)
    return w, phi1, phi2, fold, phi1f, phi2f, foldf, beta, bob


def _projectors(beta: float, bob: float):
    mirror = np.diag([1, 1, -1])
    P = lambda pts: project(place(pts, beta, bob))
    Pf = lambda pts: project(place(np.atleast_2d(pts) @ mirror.T, beta, bob))
    return P, Pf


def render_wings(t: int, n: int = N_FRAMES) -> np.ndarray:
    """Both wings alone (no body, no rim) - the source of the wings' after-image."""
    w, phi1, phi2, fold, phi1f, phi2f, foldf, beta, bob = _pose(t, n)
    P, Pf = _projectors(beta, bob)
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    draw_wing(d, wing(phi1f, phi2f, foldf), Pf, dim=0.50)
    draw_wing(d, wing(phi1, phi2, fold), P, dim=1.0)
    return np.asarray(img, dtype=np.float32) / 255.0


def render(t: int, n: int = N_FRAMES):
    """-> (bird raster, tail-only raster, meta) for flap frame t."""
    w, phi1, phi2, fold, phi1f, phi2f, foldf, beta, bob = _pose(t, n)
    P, Pf = _projectors(beta, bob)

    img = Image.new("L", (W, H), 0)
    tail_img = Image.new("L", (W, H), 0)
    d, dt = ImageDraw.Draw(img), ImageDraw.Draw(tail_img)

    # far wing first (dimmer)
    draw_wing(d, wing(phi1f, phi2f, foldf), Pf, dim=0.50)

    # tail: a clear fan - feathers narrow at the tips so each one stands apart
    spread = np.array([0.0, 0.92, 0.38])
    back = np.array([-1.0, -0.10 - 0.06 * np.sin(w), 0.0])
    tn = np.cross(back, spread)
    tn /= np.linalg.norm(tn)
    amp = 31 + 3 * np.sin(w - 0.6)
    base_t = np.array([-0.52, 0.01, 0.0])
    for a_ in np.linspace(-amp, amp, 5):
        ar = np.radians(a_)
        fe = feather(base_t, back * np.cos(ar) + spread * np.sin(ar), tn,
                     0.88 - 0.20 * abs(a_) / amp, 0.15, curl=0.0)
        it = item(fe, 0.90, 0.24, 0)
        draw_feather(d, it, P)
        draw_feather(dt, it, P)

    # body: dark seam first (separates body from tail / far wing), then a smooth shading field
    body = catmull_closed(BODY)
    body_px = [tuple(q) for q in P(np.column_stack([body, np.zeros(len(body))]))]
    d.polygon(body_px, fill=0)
    d.line(body_px + [body_px[0]], fill=0, width=9, joint="curve")
    cb = np.array([0.46, -0.12])                       # light pools on the breast; back and belly stay medium
    for k in range(13):
        u = k / 12
        shape = cb + (body - cb) * (1.0 - 0.72 * u)
        v = 0.34 + 0.66 * u ** 0.85
        d.polygon([tuple(q) for q in P(np.column_stack([shape, np.zeros(len(shape))]))], fill=val(v))
    body_feathers(img, body, body_px, P)

    # small rounded head (bright), short tapered beak (medium), dark eye
    d.polygon([tuple(p) for p in P(circle(0.80, 0.298, 0.121))], fill=0)      # rim
    d.polygon([tuple(p) for p in P(circle(0.80, 0.298, 0.105))], fill=255)
    beak = np.array([[0.88, 0.346, 0], [1.085, 0.294, 0], [0.88, 0.244, 0]])
    d.polygon([tuple(p) for p in P(beak)], fill=val(0.95))
    d.polygon([tuple(p) for p in P(circle(0.84, 0.322, 0.026, 14))], fill=0)

    # near wing last, brighter, with a black rim
    draw_wing(d, wing(phi1, phi2, fold), P, dim=1.0, halo=True)

    # anatomy landmarks in character cells (row, col) for the glyph pass
    pts = P(np.array([HEAD, [1.02, 0.288, 0], [-1.38, 0.0, 0], [-0.30, 0.0, 0]]))
    cell = lambda q: (q[1] / SY, q[0] / SX)
    meta = dict(head=cell(pts[0]), beak=cell(pts[1]), tail=cell(pts[2]), rear=cell(pts[3]))
    f = lambda im: np.asarray(im, dtype=np.float32) / 255.0
    return f(img), f(tail_img), meta


if __name__ == "__main__":
    import sys
    frames = [int(a) for a in sys.argv[1:]] or [2, 8, 12, 20]
    tiles = [Image.fromarray((render(t)[0] * 255).astype(np.uint8)).resize((W // 3, H // 3)) for t in frames]
    sheet = Image.new("L", (tiles[0].width * len(tiles), tiles[0].height))
    for i, im in enumerate(tiles):
        sheet.paste(im, (i * im.width, 0))
    sheet.save("preview/silhouette_sheet.png")
    print("frames", frames, sheet.size)
