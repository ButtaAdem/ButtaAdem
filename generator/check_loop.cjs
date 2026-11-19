// Verify the real CSS animation: at every sampled time exactly one frame group is visible,
// and it is the expected one. node check_loop.cjs <svg>
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const b = await chromium.launch();
  const page = await b.newPage({ viewport: { width: 900, height: 700 } });
  await page.goto('file://' + path.resolve(process.argv[2]));
  const res = await page.evaluate(() => {
    const gs = [...document.querySelectorAll('.f')], n = gs.length, out = [];
    const dur = document.getAnimations()[0].effect.getComputedTiming().duration;
    for (let k = 0; k < n * 2; k++) {                       // two full loops, mid-frame samples
      const T = (dur / n) * (k + 0.5);
      document.getAnimations().forEach(a => { a.pause(); a.currentTime = T; });
      const vis = gs.map((g, i) => +getComputedStyle(g).opacity > 0.5 ? i : -1).filter(i => i >= 0);
      out.push([k % n, vis]);
    }
    return { n, out };
  });
  const bad = res.out.filter(([k, v]) => v.length !== 1 || v[0] !== k);
  console.log(`${res.n} groups, ${res.out.length} samples over 2 loops, mismatches: ${bad.length}`, bad.slice(0, 3));
  await b.close();
})();
// reduced motion: only the dedicated wings-up frame may be visible
(async () => {
  const { chromium } = require('playwright'); const path = require('path');
  const b = await chromium.launch();
  const ctx = await b.newContext({ reducedMotion: 'reduce', viewport: { width: 900, height: 700 } });
  const page = await ctx.newPage();
  await page.goto('file://' + path.resolve(process.argv[2]));
  const vis = await page.evaluate(() => [...document.querySelectorAll('.f')].map((g, i) => +getComputedStyle(g).opacity > 0.5 ? i : -1).filter(i => i >= 0));
  const anims = await page.evaluate(() => document.getAnimations().length);
  console.log(`reduced-motion: visible groups = [${vis}], running animations = ${anims}`);
  await b.close();
})();
