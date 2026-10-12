// "Reading: <headline>" on the card when the guide opens another article by itself (article's conversation); cleared when the conversation ends.
const { open } = require("./lib.cjs");
const ok = (c, m) => { console.log(c ? "PASS" : "FAIL", m); if (!c) process.exitCode = 1; };
(async () => {
  for (const lang of ["en", "hi"]) {
    const h = await open({ lang }); const { page } = h;
    await page.tap(".acts .talkbtn"); await page.waitForTimeout(500);
    await page.evaluate(() => window.__mock.set("listening")); await page.waitForTimeout(200);
    const hint = () => page.evaluate(() => document.querySelector(".tkhint").textContent);
    const before = await hint();
    await page.evaluate(() => window.__mock.opts.onArticle({ id: 7, headline: "Court strikes down the order" })); await page.waitForTimeout(200);
    const pre = await page.evaluate(() => T[lang].talkReading);
    ok((await hint()) === pre + "Court strikes down the order", `[${lang}] the card says "${await hint()}" (was "${before}")`);
    await page.tap('[data-tk="close"]'); await page.waitForTimeout(600);
    await page.tap(".acts .talkbtn"); await page.waitForTimeout(500);
    await page.evaluate(() => window.__mock.set("listening")); await page.waitForTimeout(200);
    ok((await hint()) === before, `[${lang}] a new conversation starts without it`);
    await h.close();
  }
})();
