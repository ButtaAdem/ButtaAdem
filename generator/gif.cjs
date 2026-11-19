// One PNG per frame group (deterministic): node gif.cjs <svg> <outDir>
const { chromium } = require('playwright');
const path = require('path'), fs = require('fs');
(async () => {
  const [svg, dir] = process.argv.slice(2);
  fs.mkdirSync(dir, { recursive: true });
  const b = await chromium.launch();
  const page = await b.newPage({ viewport: { width: 1040, height: 780 } });
  await page.goto('file://' + path.resolve(svg));
  await page.evaluate(() => document.querySelectorAll('.f').forEach(g => { g.style.animation = 'none'; g.style.opacity = 0; }));
  const n = await page.evaluate(() => document.querySelectorAll('.f').length);
  for (let i = 0; i < n; i++) {
    await page.evaluate((k) => document.querySelectorAll('.f').forEach((g, j) => { g.style.opacity = j === k ? 1 : 0; }), i);
    await page.waitForTimeout(150);
    await page.screenshot({ path: `${dir}/f${String(i).padStart(2, '0')}.png` });
  }
  await b.close();
})();
