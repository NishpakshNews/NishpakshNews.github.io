const { open, shot, SHOTS } = require("./lib.cjs");
const rect = (page, sel) => page.evaluate((s) => { const b = document.querySelector(s).getBoundingClientRect(); return [b.left, b.top].map(Math.round); }, sel);
const ok = (c, m) => console.log(c ? "PASS" : "FAIL", m);
(async () => {
  const h = await open(); const { page } = h;
  await page.waitForTimeout(300);
  await page.tap(".acts .talkbtn"); await page.waitForTimeout(500);
  await page.evaluate(() => window.__mock.set("listening"));
  await page.tap('[data-tk="min"]'); await page.waitForTimeout(900);
  const anchor = await rect(page, ".acts .talkbtn"), fl1 = await rect(page, ".tkfloat");
  ok(Math.abs(anchor[0]-fl1[0])<=1 && Math.abs(anchor[1]-fl1[1])<=1, `at the top the floating button sits on the article's button ${anchor} vs ${fl1}`);
  const st = await page.evaluate(() => ({ on: document.querySelector(".tkfloat").classList.contains("on"), docked: document.querySelector(".tkfloat").classList.contains("docked"), cardHidden: getComputedStyle(document.querySelector(".tkcard")).visibility, veil: document.querySelector(".tkveil").classList.contains("on"), btnOp: getComputedStyle(document.querySelector(".acts .talkbtn")).opacity, inert: document.getElementById("sheet").inert }));
  ok(st.on && st.docked && st.cardHidden==="hidden" && !st.veil && st.btnOp==="0" && !st.inert, "collapsed: float on+docked, card hidden, blur off, page usable " + JSON.stringify(st));
  await page.evaluate(() => window.__mock.set("speaking"));
  await page.waitForTimeout(400); await page.screenshot({ path: `${SHOTS}/20-docked-speaking.png`, clip: {x:0,y:360,width:390,height:100} });
  // scroll down: it must come to the bottom right
  await page.evaluate(() => { document.getElementById("sheet-scroll").scrollTo({ top: 900 }); });
  await page.waitForTimeout(150); await page.screenshot({ path: `${SHOTS}/21-travelling.png` });
  await page.waitForTimeout(900);
  const fl2 = await rect(page, ".tkfloat");
  ok(fl2[0]===anchor[0] && Math.abs(fl2[1] - (844-18-52))<=14, `scrolled away: bottom right ${fl2}`);
  await page.screenshot({ path: `${SHOTS}/22-corner-speaking.png` });
  await page.evaluate(() => window.__mock.set("listening"));
  await page.waitForTimeout(300); await page.screenshot({ path: `${SHOTS}/23-corner-listening.png`, clip: {x:230,y:700,width:160,height:144} });
  // scroll back up: it must glide to the article button and dock exactly
  await page.evaluate(() => { document.getElementById("sheet-scroll").scrollTo({ top: 0 }); });
  await page.waitForTimeout(1200);
  const a3 = await rect(page, ".acts .talkbtn"), fl3 = await rect(page, ".tkfloat");
  ok(Math.abs(a3[0]-fl3[0])<=1 && Math.abs(a3[1]-fl3[1])<=1, `back at the top it docked again ${a3} vs ${fl3}`);
  // mid-scroll: slow scroll keeps it glued while the anchor is in view
  await page.evaluate(() => { document.getElementById("sheet-scroll").scrollTo({ top: 60 }); });
  await page.waitForTimeout(400);
  const a4 = await rect(page, ".acts .talkbtn"), fl4 = await rect(page, ".tkfloat");
  ok(Math.abs(a4[1]-fl4[1])<=1, `small scroll: stays glued ${a4} vs ${fl4}`);
  // expand from the float
  await page.tap(".tkfloat"); await page.waitForTimeout(700);
  const st2 = await page.evaluate(() => ({ ui: TK.ui, floatOn: document.querySelector(".tkfloat").classList.contains("on"), veil: document.querySelector(".tkveil").classList.contains("on"), cardVis: getComputedStyle(document.querySelector(".tkcard")).visibility, inert: document.getElementById("sheet").inert }));
  ok(st2.ui==="card" && !st2.floatOn && st2.veil && st2.cardVis==="visible" && st2.inert, "tapping the float reopens the card " + JSON.stringify(st2));
  // Escape collapses, does not leave the article
  await page.keyboard.press("Escape"); await page.waitForTimeout(600);
  ok(await page.evaluate(() => TK.ui==="mini" && !!openId), "Escape collapses; the article stays open");
  // close via X after reopening: conversation stops, everything goes
  await page.tap(".tkfloat"); await page.waitForTimeout(600);
  await page.tap('[data-tk="close"]'); await page.waitForTimeout(700);
  const st3 = await page.evaluate(() => ({ ui: TK.ui, log: window.__log.map(x=>x[0]), floatOn: document.querySelector(".tkfloat").classList.contains("on"), btnOp: getComputedStyle(document.querySelector(".acts .talkbtn")).opacity, cls: document.documentElement.className }));
  ok(st3.ui==="closed" && st3.log.at(-1)==="stop" && !st3.floatOn && st3.btnOp==="1", "close ends it " + JSON.stringify(st3));
  await h.close();
})();
