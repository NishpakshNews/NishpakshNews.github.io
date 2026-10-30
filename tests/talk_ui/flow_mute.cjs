const { open, shot, SHOTS } = require("./lib.cjs");
const ok = (c, m) => console.log(c ? "PASS" : "FAIL", m);
(async () => {
  const h = await open(); const page = h.page;
  await page.waitForTimeout(300); await page.tap(".acts .talkbtn"); await page.waitForTimeout(500);
  const disabled = () => page.evaluate(() => document.querySelector(".tkmute").disabled);
  ok(await disabled(), "Mute is disabled while connecting");
  await page.evaluate(() => window.__mock.set("listening")); await page.waitForTimeout(300);
  ok(!(await disabled()), "Mute is enabled while listening");
  const h0 = await page.evaluate(() => document.querySelector(".tkcard").getBoundingClientRect().height);
  await page.tap(".tkmute"); await page.waitForTimeout(500);
  const v = await page.evaluate(() => ({ muted: document.querySelector(".tkcard").classList.contains("muted"), line: document.querySelector(".tkline").textContent, label: document.querySelector(".tkmute b").textContent, pressed: document.querySelector(".tkmute").getAttribute("aria-pressed"), log: window.__log.filter(x => x[0] === "mute").map(x => x[1]), h: document.querySelector(".tkcard").getBoundingClientRect().height }));
  ok(v.muted && v.line === "You're muted" && v.label === "Unmute" && v.pressed === "true" && v.log.join() === "true", "muting: " + JSON.stringify(v));
  ok(Math.abs(v.h - h0) < 1, "card height does not change when muted " + h0 + " -> " + v.h);
  await page.screenshot({ path: `${SHOTS}/50-muted.png` });
  // the guide speaking while muted still shows the speaking look
  await page.evaluate(() => window.__mock.set("speaking")); await page.waitForTimeout(300);
  ok(await page.evaluate(() => document.querySelector(".tkline").textContent !== "You're muted" && document.querySelector(".tkcard").classList.contains("muted")), "guide speaks while muted: speaking words, button stays muted");
  await page.evaluate(() => window.__mock.set("listening")); await page.waitForTimeout(200);
  // minimise: the floating button shows the badge
  await page.tap('[data-tk="min"]'); await page.waitForTimeout(600);
  ok(await page.evaluate(() => document.querySelector(".tkfloat").classList.contains("muted") && getComputedStyle(document.querySelector(".tkfloat .mbadge")).opacity === "1"), "floating button shows the muted badge");
  await page.screenshot({ path: `${SHOTS}/51-muted-mini.png` });
  await page.tap(".tkfloat"); await page.waitForTimeout(600);
  await page.tap(".tkmute"); await page.waitForTimeout(400);
  ok(await page.evaluate(() => !document.querySelector(".tkcard").classList.contains("muted") && document.querySelector(".tkline").textContent === "Go ahead, I'm listening" && window.__log.filter(x => x[0] === "mute").map(x => x[1]).join() === "true,false"), "unmuting restores listening");
  await page.screenshot({ path: `${SHOTS}/52-unmuted.png` });
  // settings view hides the pair; muting survives it
  await page.tap(".tkmute"); await page.waitForTimeout(200);
  await page.tap('[data-tk="openset"]'); await page.waitForTimeout(300);
  ok(await page.evaluate(() => getComputedStyle(document.querySelector(".tkpair")).display === "none"), "pair hidden in Voice and pace");
  await page.tap('[data-tk="back"]'); await page.waitForTimeout(300);
  ok(await page.evaluate(() => document.querySelector(".tkcard").classList.contains("muted")), "still muted after the settings view");
  // end and start again: not muted
  await page.tap('[data-tk="close"]'); await page.waitForTimeout(500);
  await page.tap(".acts .talkbtn"); await page.waitForTimeout(500); await page.evaluate(() => window.__mock.set("listening")); await page.waitForTimeout(300);
  ok(await page.evaluate(() => !document.querySelector(".tkcard").classList.contains("muted")), "a new conversation starts unmuted");
  await h.close();
})();
