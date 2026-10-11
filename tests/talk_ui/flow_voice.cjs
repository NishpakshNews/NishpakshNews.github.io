const { open, shot, SHOTS } = require("./lib.cjs");
const ok = (c, m) => console.log(c ? "PASS" : "FAIL", m);
(async () => {
  let h = await open(); let page = h.page;
  await page.waitForTimeout(300); await page.tap(".acts .talkbtn"); await page.waitForTimeout(500);
  await page.evaluate(() => window.__mock.set("listening"));
  // open the panel while live
  await page.tap('[data-tk="openset"]'); await page.waitForTimeout(500);
  const v = await page.evaluate(() => ({ set: document.querySelector(".tkcard").classList.contains("set"), title: document.querySelector(".tkname").textContent, leftIs: document.querySelector(".tkhead .bx").dataset.tk, on: [...document.querySelectorAll(".tkopts .on")].map(b => b.dataset.tkv || b.dataset.tks), vis: getComputedStyle(document.querySelector(".tkstage")).display, r: (() => { const c = document.querySelector(".tkcard").getBoundingClientRect(); return [Math.round(c.top), Math.round(c.height), innerHeight]; })() }));
  ok(v.set && v.title === "Voice and pace" && v.leftIs === "back" && v.vis === "none", "panel opens, back arrow replaces minimise " + JSON.stringify(v));
  ok(v.on.join() === "Kore,pace:natural,tone:warm,accent:indian", "defaults are Kore / natural / warm / Indian: " + v.on.join());
  await page.screenshot({ path: `${SHOTS}/40-settings.png` });
  // change while live: pace, tone are nudged, voice is not
  await page.tap('[data-tks="pace:slow"]'); await page.tap('[data-tks="tone:news"]'); await page.tap('[data-tkv="Achird"]'); await page.waitForTimeout(200);
  const log = await page.evaluate(() => window.__log.filter(x => x[0] === "nudge").map(x => x[1]));
  ok(log.length === 2 && /slowly/.test(log[0]) && /newsreader/.test(log[1]), "pace and tone said to the guide at once, voice not: " + JSON.stringify(log));
  ok(await page.evaluate(() => JSON.parse(localStorage.getItem("np-voice")).voice === "Achird"), "kept on the device");
  // while the guide speaks, a change waits until it listens
  await page.evaluate(() => window.__mock.set("speaking"));
  await page.tap('[data-tks="accent:neutral"]'); await page.waitForTimeout(150);
  ok(await page.evaluate(() => window.__log.filter(x => x[0] === "nudge").length) === 2, "nothing said over the guide's own voice");
  await page.evaluate(() => window.__mock.set("listening")); await page.waitForTimeout(150);
  ok(await page.evaluate(() => window.__log.filter(x => x[0] === "nudge").length) === 3, "...it is said when the guide is listening");
  // back (arrow, then Escape twice behaviour)
  await page.tap('[data-tk="back"]'); await page.waitForTimeout(300);
  ok(await page.evaluate(() => !document.querySelector(".tkcard").classList.contains("set") && TK.ui === "card"), "back returns to the card");
  await page.tap('[data-tk="openset"]'); await page.keyboard.press("Escape"); await page.waitForTimeout(300);
  ok(await page.evaluate(() => !document.querySelector(".tkcard").classList.contains("set") && TK.ui === "card"), "Escape leaves the panel first, the card stays");
  // end, start again: the saved style goes to the function
  await page.tap('[data-tk="close"]'); await page.waitForTimeout(500);
  await page.tap(".acts .talkbtn"); await page.waitForTimeout(500);
  const st = await page.evaluate(() => window.__log.filter(x => x[0] === "start").at(-1)[1]);
  ok(JSON.stringify(st.style) === JSON.stringify({ voice: "Achird", pace: "slow", tone: "news", accent: "neutral" }), "next start sends the saved style " + JSON.stringify(st.style));
  // reset
  await page.tap('[data-tk="openset"]'); await page.tap('[data-tk="reset"]'); await page.waitForTimeout(200);
  ok(await page.evaluate(() => JSON.stringify(tkStyle()) === JSON.stringify(STYLE_DEFAULT)), "reset goes back to the Indian default");
  // collapse from inside the panel works too
  await page.tap('[data-tk="back"]'); await page.tap('[data-tk="min"]'); await page.waitForTimeout(500);
  ok(await page.evaluate(() => TK.ui === "mini"), "collapse still works");
  await h.close();

  // Hindi, and a small screen
  h = await open({ lang: "hi", width: 360, height: 640 }); page = h.page;
  await page.waitForTimeout(300); await page.tap(".acts .talkbtn"); await page.waitForTimeout(500);
  await page.evaluate(() => window.__mock.set("listening"));
  await page.tap('[data-tk="openset"]'); await page.waitForTimeout(500);
  const hi = await page.evaluate(() => { const c = document.querySelector(".tkcard"); const r = c.getBoundingClientRect(); return { title: document.querySelector(".tkname").textContent, top: Math.round(r.top), bottom: Math.round(r.bottom), vh: innerHeight, scrolls: c.scrollHeight > c.clientHeight, labs: [...document.querySelectorAll(".tkopts .olab")].map(x => x.textContent) }; });
  ok(hi.title === "आवाज़ और रफ़्तार" && hi.top >= 0 && hi.bottom <= hi.vh, "Hindi panel fits a 360x640 screen " + JSON.stringify(hi));
  await page.screenshot({ path: `${SHOTS}/41-settings-hindi-small.png` });
  await h.close();
})();
