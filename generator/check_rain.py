"""Fail if any horizontal band of the canvas goes (nearly) empty in any frame.

Checks the FINAL composite (dove + after-image + rain), band by band.  It exists because an
earlier version looked fine on average but left the bottom fifth of the canvas empty.
    python3 generator/check_rain.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np                                            # noqa: E402
from dove import COLS, ROWS, N_FRAMES                         # noqa: E402
from glyphs import build_frames                               # noqa: E402

BANDS = 5
MIN_WORST_FRAME = 0.05      # every band holds >= 5% glyphs in its emptiest frame
MIN_EDGE_RATIO = 0.6        # the bottom band holds at least 60% as much as the top band (and vice versa);
                            # the middle bands are not compared: the dove itself sits there

rows = [f[0] for f in build_frames()]
occ = np.array([[sum(ch != " " for ch in rows[t][r]) / COLS for r in range(ROWS)] for t in range(N_FRAMES)])
edges = np.linspace(0, ROWS, BANDS + 1).astype(int)
mean = [occ[:, a:b].mean() for a, b in zip(edges, edges[1:])]
worst = [min(occ[t, a:b].mean() for t in range(N_FRAMES)) for a, b in zip(edges, edges[1:])]
print("band (top->bottom)   mean    emptiest frame")
for i, (m, w) in enumerate(zip(mean, worst)):
    print(f"  {i + 1}                 {m*100:5.1f}%   {w*100:5.1f}%")
edge = min(mean[0], mean[-1]) / max(mean[0], mean[-1])
print(f"top/bottom balance: {edge:.2f} (need >= {MIN_EDGE_RATIO})")
ok = min(worst) >= MIN_WORST_FRAME and edge >= MIN_EDGE_RATIO
print("OK" if ok else "FAIL: a band of the canvas is empty in some frame, or top and bottom are unbalanced")
sys.exit(0 if ok else 1)
