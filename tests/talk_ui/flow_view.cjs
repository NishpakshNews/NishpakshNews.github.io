const { open, SHOTS } = require("./lib.cjs");
const ok = (c, m) => console.log(c ? "PASS" : "FAIL", m);
(async () => {
  const h = await open(); const page = h.page;
  await page.waitForTimeout(300); await page.tap(".acts .talkbtn"); await page.waitForTimeout(500);
  await page.evaluate(() => window.__mock.set("listening")); await page.waitForTimeout(300);
  const st = () => page.evaluate(() => ({ ui: TK.ui, view: TK.view, set: document.querySelector(".tkcard").classList.contains("set"), hs: history.length, h: document.querySelector(".tkcard").style.height }));
  await page.tap('[data-tk="openset"]');
  await page.waitForTimeout(120);
  const mid = await page.evaluate(() => { const c = document.querySelector(".tkcard"), g = c.querySelector(".tkghost"); return { h: c.style.height, morph: c.classList.contains("morph"), cardOpacity: getComputedStyle(c).opacity, ghost: !!g, ghostKids: g ? g.children.length : 0, bg: getComputedStyle(c).backgroundColor !== "rgba(0, 0, 0, 0)" }; });
  ok(mid.morph && /px$/.test(mid.h) && mid.cardOpacity === "1" && mid.ghost && mid.ghostKids > 0 && true, "the card stays opaque and resizes while the old content fades under the new " + JSON.stringify(mid));
  await page.waitForTimeout(700);
  let s = await st(); ok(s.set && s.view === "set" && s.h === "", "Voice and pace open, height released after the animation " + JSON.stringify(s));
  await page.screenshot({ path: `${SHOTS}/60-settings.png` });
  // the phone's back: to the talk card, not out of it
  await page.goBack(); await page.waitForTimeout(900);
  s = await st(); ok(s.ui === "card" && s.view === "main" && !s.set, "phone back from Voice and pace returns to the talk card " + JSON.stringify(s));
  // and the next back closes (minimises) the card as before
  await page.goBack(); await page.waitForTimeout(700);
  s = await st(); ok(s.ui === "mini", "the next back minimises the card " + JSON.stringify(s));
  await page.tap(".tkfloat"); await page.waitForTimeout(600);
  // twice in a row: settings, arrow back, settings, Escape
  await page.tap('[data-tk="openset"]'); await page.waitForTimeout(900);
  await page.tap('[data-tk="back"]'); await page.waitForTimeout(900);
  s = await st(); ok(s.ui === "card" && s.view === "main", "arrow back works " + JSON.stringify(s));
  await page.tap('[data-tk="openset"]'); await page.waitForTimeout(900); await page.keyboard.press("Escape"); await page.waitForTimeout(900);
  s = await st(); ok(s.ui === "card" && s.view === "main", "Escape works " + JSON.stringify(s));
  // rapid taps do not leave the card stuck
  await page.tap('[data-tk="openset"]'); await page.waitForTimeout(100); await page.tap('[data-tk="back"]').catch(() => {}); await page.waitForTimeout(1200);
  s = await st(); ok(s.h === "" && (await page.evaluate(() => document.querySelectorAll(".tkghost").length)) === 0, "no stuck height or ghost after quick taps " + JSON.stringify(s));
  await h.close();
})();
