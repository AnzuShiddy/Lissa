/* End-to-end UI test for Lissa's web app (fixes 1-4, 6, 7).
   Run: NODE_PATH=$(npm root -g) node ui_test.js  (server on :8765) */
const { chromium } = require("playwright");

let failures = 0;
const check = (cond, name) => {
  console.log((cond ? "PASS" : "FAIL") + "  " + name);
  if (!cond) failures++;
};

(async () => {
  const browser = await chromium.launch({
    args: [
      "--autoplay-policy=user-gesture-required", // force the fix-6 path
      "--use-fake-ui-for-media-stream",          // auto-grant the mic prompt
      "--use-fake-device-for-media-stream",      // synthetic mic input
    ],
  });
  const context = await browser.newContext({
    permissions: ["microphone", "clipboard-read", "clipboard-write"],
  });
  const page = await context.newPage();
  // headless chromium ignores the autoplay policy flag, so emulate real
  // Chrome: play() rejects with NotAllowedError until the first pointerdown
  await page.addInitScript(() => {
    const orig = HTMLMediaElement.prototype.play;
    let allowed = false;
    document.addEventListener("pointerdown", () => { allowed = true; }, true);
    HTMLMediaElement.prototype.play = function () {
      if (!allowed)
        return Promise.reject(new DOMException(
          "play() failed because the user didn't interact with the document first.",
          "NotAllowedError"));
      return orig.call(this);
    };
  });
  page.on("pageerror", (e) => console.log("PAGE ERROR:", e.message));
  page.on("console", (m) => {
    if (m.type() === "error") console.log("CONSOLE ERROR:", m.text());
  });

  await page.goto("http://localhost:8765/");

  /* ---- greeting renders (fresh session) ---- */
  await page.waitForFunction(() => {
    const b = document.querySelector(".bubble.lissa");
    return b && !b.querySelector(".typing-dots") && b.textContent.length > 10;
  }, null, { timeout: 30000 });
  check(true, "greeting bubble rendered");

  /* ---- fix 6: autoplay-blocked hint ---- */
  let nudged = true;
  try {
    await page.waitForFunction(
      () => document.getElementById("toast").textContent.includes("muted"),
      null, { timeout: 25000 }
    );
  } catch { nudged = false; }
  check(nudged, "fix6: 'browser muted her' toast after autoplay block");

  // first tap replays the greeting clip (headless is silent, but the
  // speaking UI state proves the replay path ran)
  if (nudged) {
    await page.click("#title"); // neutral spot
    let replayed = true;
    try {
      await page.waitForFunction(
        () => document.getElementById("avatarWrap").classList.contains("speaking"),
        null, { timeout: 8000 }
      );
    } catch { replayed = false; }
    check(replayed, "fix6: first tap replays greeting (speaking UI active)");
    await page.evaluate(() => stopSpeaking());
  }

  /* voice off for deterministic streaming in the rest of the test */
  await page.click("#voiceBtn");

  /* ---- fix 3: multiline composer ---- */
  await page.click("#msg");
  await page.keyboard.type("line one");
  const h1 = await page.$eval("#msg", (el) => el.offsetHeight);
  await page.keyboard.down("Shift");
  await page.keyboard.press("Enter");
  await page.keyboard.up("Shift");
  await page.keyboard.type("line two");
  const h2 = await page.$eval("#msg", (el) => el.offsetHeight);
  check(h2 > h1, "fix3: textarea grows on Shift+Enter newline");
  check(
    (await page.inputValue("#msg")).includes("\n") &&
      (await page.$$(".bubble.user")).length === 0,
    "fix3: Shift+Enter inserts newline instead of sending"
  );
  await page.fill("#msg", "");

  /* ---- Enter sends; input clears and height resets ---- */
  await page.fill("#msg", "hi! reply with one short sentence please");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".bubble.user", { timeout: 5000 });
  check((await page.inputValue("#msg")) === "", "fix3: Enter sends and clears input");
  const h3 = await page.$eval("#msg", (el) => el.offsetHeight);
  check(h3 <= h1 + 2, "fix3: composer height resets after send");
  await page.waitForFunction(
    () => !document.getElementById("send").classList.contains("stop"),
    null, { timeout: 30000 }
  );
  check(
    (await page.$$eval(".bubble.lissa", (els) => els.at(-1).textContent)).length > 0,
    "reply streamed in"
  );

  /* ---- fix 4: stop button mid-stream ---- */
  await page.fill("#msg", "tell me a long detailed story about the sea, at least 300 words");
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    () => document.getElementById("send").classList.contains("stop"),
    null, { timeout: 5000 }
  );
  const stopVisible = await page.$eval(
    "#send .stop-icon", (el) => getComputedStyle(el).display !== "none"
  );
  check(stopVisible, "fix4: send button shows stop icon while streaming");
  // wait for some text to arrive, then stop
  await page.waitForFunction(() => {
    const els = document.querySelectorAll(".bubble.lissa");
    const b = els[els.length - 1];
    return b && !b.querySelector(".typing-dots") && b.textContent.length > 20;
  }, null, { timeout: 30000 });
  await page.click("#send");
  await page.waitForFunction(
    () => !document.getElementById("send").classList.contains("stop"),
    null, { timeout: 5000 }
  );
  const partial = await page.$$eval(".bubble.lissa", (els) => els.at(-1).textContent);
  await page.waitForTimeout(1500);
  const partial2 = await page.$$eval(".bubble.lissa", (els) => els.at(-1).textContent);
  check(partial.length > 20 && partial === partial2,
    "fix4: stop keeps partial text and halts the stream");
  check(await page.$eval("#mic", (el) => !el.disabled), "fix4: input unlocked after stop");

  /* ---- fix 1: smart auto-scroll + pill ---- */
  await page.evaluate(() => {
    for (let i = 0; i < 20; i++) addBubble("lissa", "filler line " + i + "\nmore text");
  });
  const chatBox = await page.$("#chat");
  const box = await chatBox.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -2000); // user scrolls up
  await page.waitForTimeout(400);
  const before = await page.$eval("#chat", (el) => el.scrollTop);
  await page.evaluate(() => addBubble("lissa", "new content while scrolled up"));
  await page.waitForTimeout(400);
  const after = await page.$eval("#chat", (el) => el.scrollTop);
  check(Math.abs(after - before) < 5, "fix1: no scroll yank while user is scrolled up");
  const pillShown = await page.$eval("#jump", (el) => el.classList.contains("show"));
  check(pillShown, "fix1: 'new message' pill appears");
  if (pillShown) {
    await page.click("#jump");
    await page.waitForTimeout(800);
    check(
      await page.$eval("#chat", (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 60),
      "fix1: pill click jumps to bottom"
    );
    check(
      await page.$eval("#jump", (el) => !el.classList.contains("show")),
      "fix1: pill hides after jumping"
    );
  } else {
    // recover so the remaining tests start from the bottom
    await page.evaluate(() => { chat.scrollTop = chat.scrollHeight; });
  }

  /* ---- fix 7: retry on connection error ---- */
  await page.route("**/api/chat", (r) => r.abort());
  const usersBefore = (await page.$$(".bubble.user")).length;
  await page.fill("#msg", "are you still there?");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".retryBtn", { timeout: 10000 });
  check(
    (await page.$$eval(".bubble.lissa", (els) => els.at(-1).textContent)).includes("reach the server"),
    "fix7: connection error shows message + retry button"
  );
  await page.unroute("**/api/chat");
  await page.click(".retryBtn");
  await page.waitForFunction(() => !document.querySelector(".retryBtn"), null, { timeout: 5000 });
  // generous: the server may still be draining the stopped story's stream
  // (it holds the session lock until Gemini finishes generating)
  await page.waitForFunction(
    () => !document.getElementById("send").classList.contains("stop"),
    null, { timeout: 90000 }
  );
  check(
    (await page.$$(".bubble.user")).length === usersBefore + 1,
    "fix7: retry does not duplicate the user bubble"
  );
  const retried = await page.$$eval(".bubble.lissa", (els) => els.at(-1).textContent);
  check(retried.length > 0 && !retried.includes("reach the server"),
    "fix7: retry resends and gets a real reply");

  /* ---- fix 2: reset needs a second tap ---- */
  const bubblesBefore = (await page.$$(".bubble")).length;
  await page.click("#resetBtn");
  await page.waitForTimeout(300);
  check(
    await page.$eval("#resetBtn", (el) => el.classList.contains("confirm")),
    "fix2: first tap arms the reset button"
  );
  check((await page.$$(".bubble")).length === bubblesBefore,
    "fix2: single tap does not wipe the chat");
  await page.click("#resetBtn");
  await page.waitForFunction(
    (n) => document.querySelectorAll(".bubble").length < n,
    bubblesBefore, { timeout: 15000 }
  );
  check((await page.$$(".bubble")).length === 1, "fix2: second tap resets to a fresh greeting");
  check(
    await page.$eval("#resetBtn", (el) => !el.classList.contains("confirm")),
    "fix2: confirm state cleared after reset"
  );

  /* ---- fix 8: accessibility ---- */
  check(
    await page.$eval("#chat", (el) => el.getAttribute("role") === "log"),
    "fix8: chat is a log landmark"
  );
  await page.waitForTimeout(300); // announce() sets the live region async
  check(
    (await page.$eval("#sr", (el) => el.textContent)).startsWith("Lissa:"),
    "fix8: screen-reader live region announced the reply"
  );
  check(
    await page.$eval("#voiceBtn", (el) => el.getAttribute("aria-pressed") === "false"),
    "fix8: voice toggle exposes pressed state (off)"
  );
  await page.click("#voiceBtn");
  check(
    await page.$eval("#voiceBtn", (el) => el.getAttribute("aria-pressed") === "true"),
    "fix8: aria-pressed follows the toggle"
  );
  await page.click("#voiceBtn"); // back off
  await page.focus("#avatarWrap");
  check(
    await page.evaluate(() => document.activeElement.id === "avatarWrap"),
    "fix8: avatar is keyboard-focusable"
  );
  await page.click("#memBtn");
  check(
    await page.$eval("#overlay", (el) => el.classList.contains("show")),
    "fix8: info panel opens"
  );
  await page.keyboard.press("Escape");
  check(
    await page.$eval("#overlay", (el) => !el.classList.contains("show")),
    "fix8: Escape closes the panel"
  );

  /* ---- fix 9: timestamps ---- */
  check(
    (await page.$$(".timestamp")).length === 1,
    "fix9: fresh conversation starts with one time label"
  );
  await page.evaluate(() => addBubble("user", "quick follow-up"));
  check(
    (await page.$$(".timestamp")).length === 1,
    "fix9: no label within the 5-minute window"
  );
  await page.evaluate(() => { lastStamp = Date.now() - 6 * 60 * 1000; });
  await page.evaluate(() => addBubble("user", "message after a long silence"));
  check(
    (await page.$$(".timestamp")).length === 2,
    "fix9: label appears after a >5-minute gap"
  );

  /* ---- fix 11: copy button on Lissa's bubbles ---- */
  const lastLissa = page.locator(".bubble.lissa").last();
  const lastText = await lastLissa.textContent();
  await lastLissa.hover();
  await lastLissa.locator(".copyBtn").click();
  await page.waitForFunction(
    () => document.getElementById("toast").textContent === "copied",
    null, { timeout: 5000 }
  );
  check(true, "fix11: copy button shows 'copied' toast");
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  check(clip === lastText, "fix11: clipboard holds the bubble's text");

  /* ---- fix 10 + 12: hold-to-talk on the AudioWorklet capture path ---- */
  const micBox = await page.locator("#mic").boundingBox();
  await page.mouse.move(micBox.x + micBox.width / 2, micBox.y + micBox.height / 2);
  await page.mouse.down();
  await page.waitForSelector("#recorder:not([hidden])", { timeout: 5000 });
  check(true, "fix10: recorder opens on mic press");
  const capture = await page.evaluate(() => rec && rec.proc.constructor.name);
  check(capture === "AudioWorkletNode",
    "fix12: capture uses AudioWorklet (got " + capture + ")");
  await page.waitForTimeout(900); // hold past the walkie-talkie threshold
  await page.mouse.up();
  await page.waitForFunction(
    () => document.getElementById("recorder").hidden, null, { timeout: 5000 });
  check(true, "fix10: releasing the hold ends the recording");
  // let the transcription attempt (and any resulting reply) finish
  await page.waitForFunction(
    () => !busy && !document.getElementById("mic").classList.contains("busy"),
    null, { timeout: 60000 }
  );

  /* quick tap still opens the recorder for hands-free finish */
  await page.locator("#mic").click();
  await page.waitForSelector("#recorder:not([hidden])", { timeout: 5000 });
  check(true, "fix10: quick tap opens the recorder");
  await page.locator("#recCancel").click();
  check(
    await page.$eval("#recorder", (el) => el.hidden),
    "fix10: cancel closes the recorder"
  );

  /* ---- sentence-by-sentence speech ---- */
  await page.click("#voiceBtn"); // voice back on
  const sayTimes = [];
  const onReq = (r) => { if (r.url().includes("/api/say")) sayTimes.push(Date.now()); };
  page.on("request", onReq);
  await page.fill("#msg", "count from one to seven — one short sentence per number, please");
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    () => !document.getElementById("send").classList.contains("stop"),
    null, { timeout: 60000 }
  );
  const streamDoneAt = Date.now();
  await page.waitForTimeout(2500); // let any trailing segments dispatch
  page.off("request", onReq);
  check(sayTimes.length >= 2,
    "speech: reply split into multiple clips (" + sayTimes.length + " requests)");
  check(sayTimes.length > 0 && sayTimes[0] < streamDoneAt,
    "speech: first clip requested before the text stream finished");
  await page.click("#avatarWrap"); // stop any ongoing speech
  await page.click("#voiceBtn");   // voice off again for the memory tests

  /* ---- web memory: facts persist in localStorage across reloads ---- */
  await page.fill("#msg", "By the way, my name is Zanzibar and I love mango juice. Remember that!");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => !busy, null, { timeout: 60000 });
  await page.click("#resetBtn");
  await page.click("#resetBtn"); // confirm — distills memory, then resets
  await page.waitForFunction(
    () => document.querySelectorAll(".bubble").length === 1, null, { timeout: 60000 });
  const stored = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("lissa_facts") || "[]"));
  check(stored.length > 0, "memory: facts distilled into localStorage on reset");
  check(stored.join(" ").toLowerCase().includes("zanzibar"),
    "memory: facts captured the name (got: " + stored.join(" | ").slice(0, 80) + ")");

  await page.reload();
  await page.waitForFunction(() => {
    const b = document.querySelector(".bubble.lissa");
    return b && !b.querySelector(".typing-dots") && b.textContent.length > 5;
  }, null, { timeout: 30000 });
  const greet2 = await page.$eval(".bubble.lissa", (el) => el.textContent);
  check(!greet2.includes("what's on your mind"),
    "memory: reload greets like a returning visitor");

  await browser.close();
  console.log(failures === 0 ? "\nALL PASSED" : `\n${failures} FAILURE(S)`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error("TEST CRASHED:", e); process.exit(2); });
