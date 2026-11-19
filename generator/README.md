# Dove generator

Builds `assets/dove.svg`: a white dove flapping its wings, drawn from random
matrix glyphs on black. CSS animation only (no JS), so GitHub plays it inside a
README `<img>`. 24 frames at 12 fps, seamless loop.

```bash
pip install -r generator/requirements.txt
python3 generator/build.py          # writes assets/dove.svg
```

## How it works

| file | job |
| --- | --- |
| `dove.py` | 3D dove: small round head, short beak, full curved breast with a scalloped feather grain, folded back feathers, a five-feather tail fan set off by a dark seam; each wing = broad leading band + coverts + secondaries (scalloped edge) + 5 primaries (distinct tips). Shoulder leads the downstroke, the hand lags ~1 rad, the wrist flexes on the upstroke. Pitch/bob pivot on the head so it stays steady. Camera is near side-on, so wings sweep back and leave black between wing and head |
| `glyphs.py` | measures every glyph's ink density, buckets glyphs into a 10-step ramp, picks a random glyph per cell from the bucket matching its brightness. Breast + leading edge = dense, feather surfaces = medium, tips = sparse. Face and outer contour swap glyphs slowly (with hysteresis); the interior shimmers. After-image: the wings and tail leave ghosts that drift back/down and thin into sparse glyphs (the dove's own cells always win, with a one-cell clean edge). Background: Matrix rain over the whole canvas - evenly spaced columns, long streams of light punctuation with a brighter letter at the head, born anywhere along the column so top and bottom get equal rain, passing behind the dove, with a pocket kept clear ahead of the beak |
| `build.py` | writes the SVG (one `<g>` per frame, stepped by one CSS keyframe; faint glyphs are packed as one x-list `<text>` per row to keep the file small). `STILL_FRAME` is the wings-up pose shown under `prefers-reduced-motion` |

## Checking a change

```bash
node generator/review.cjs assets/dove.svg preview/review-540.png 540 7 13 20   # frames at 540 px wide
node generator/check_loop.cjs assets/dove.svg                                  # one frame visible at a time, reduced-motion pose
python3 generator/check_rain.py                                                 # no band of the canvas may go empty in any frame
node generator/gif.cjs assets/dove.svg /tmp/frames                              # PNG per frame -> make a GIF
python3 generator/dove.py 2 7 13 20                                             # raw silhouettes -> preview/silhouette_sheet.png
```

## Knobs

* `dove.py`: `COLS/ROWS` (grid), `UNIT` (bird size), `YAW/PITCH` (camera), flap angles in `render()`, `STILL_FRAME`
* `glyphs.py`: `LIFT_FLOOR/LIFT_GAMMA` (bird luminance), `FAST/SLOW/HOLD` (flicker vs. holding), `RAIN_STREAMS/RAIN_HEAD/RAIN_BODY/RAIN_TAIL/RAIN_SPEED` (rain), `TRAIL_*` (wing after-image)
* `build.py`: `FPS`, `FG` / `BG`, stroke weight

Earlier versions for A/B comparison live in `archive/` (not published).
