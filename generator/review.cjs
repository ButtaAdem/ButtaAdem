// Review sheet at a fixed width: node review.cjs <svg> <out.png> <width> <frame...>
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const [svg, out, width, ...frames] = process.argv.slice(2);
  const w = parseInt(width);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1000 } });
  await page.goto('file://' + path.resolve(svg));
  const [vw, vh] = await page.evaluate(() => { const r = document.documentElement.viewBox.baseVal; return [r.width, r.height]; });
  const h = Math.round(w * vh / vw);
  await page.setViewportSize({ width: w, height: h });
  await page.evaluate(([w, h]) => { const r = document.documentElement; r.setAttribute('width', w); r.setAttribute('height', h); }, [w, h]);
  const dur = await page.evaluate(() => document.getAnimations()[0].effect.getComputedTiming().duration);
  // deterministic: stop the CSS animation and show exactly one frame group
  await page.evaluate(() => document.querySelectorAll('.f').forEach(g => { g.style.animation = 'none'; g.style.opacity = 0; }));
  const shots = [];
  for (const f of frames) {
    await page.evaluate((i) => document.querySelectorAll('.f').forEach((g, k) => { g.style.opacity = k === i ? 1 : 0; }), parseInt(f));
    await page.waitForTimeout(250);
    shots.push((await page.screenshot()).toString('base64'));
  }
  const cols = Math.min(3, shots.length);
  const b = await browser.newPage({ viewport: { width: cols * w, height: Math.ceil(shots.length / cols) * h } });
  await b.setContent(`<body style="margin:0;background:#222;display:grid;grid-template-columns:repeat(${cols},${w}px)">` +
    shots.map(s => `<img style="width:${w}px;height:${h}px;display:block" src="data:image/png;base64,${s}">`).join('') + '</body>');
  await b.waitForTimeout(300);
  await b.screenshot({ path: out });
  await browser.close();
})();
