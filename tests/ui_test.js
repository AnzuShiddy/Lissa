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

  // the five header controls live in the overflow menu now: open it first,
  // unless a previous item left it open (toggles keep it up)
  const menuClick = async (sel) => {
    if (await page.$eval("#menu", (el) => el.hidden)) await page.click("#menuBtn");
    await page.click(sel);
  };

  await page.goto("http://localhost:8765/");

  /* ---- greeting renders (fresh session) ---- */
  // dots gone = the reveal has begun (network latency for /api/hello and
  // the clip fetch happens before this point, so timing from here on is
  // purely the text-reveal pace, not fetch time)
  await page.waitForFunction(() => {
    const b = document.querySelector(".bubble.lissa");
    return b && !b.querySelector(".typing-dots");
  }, null, { timeout: 30000 });
  const revealStart = Date.now();
  await page.waitForFunction(() => {
    const b = document.querySelector(".bubble.lissa");
    return b && b.textContent.length > 10;
  }, null, { timeout: 15000 });
  check(true, "greeting bubble rendered");

  /* ---- unvoiced first message still types at a natural pace ----
     Autoplay is blocked in this suite's browser context (see the play()
     override above), so the greeting's clip never plays — it must still
     type out gradually like every other message, not paste in within a
     couple hundred ms just because there's no audio to pace against. */
  await page.waitForFunction(() => {
    const b = document.querySelector(".bubble.lissa");
    return b && b.textContent.trim().endsWith("?");
  }, null, { timeout: 15000 });
  const revealMs = Date.now() - revealStart;
  check(revealMs > 800,
    "unvoiced greeting: types out gradually, not pasted instantly (took " + revealMs + "ms)");

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
  await menuClick("#voiceBtn");

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

  /* ---- she replies in whatever language the message is in ----
     Her conversational language, separate from the UI chrome's language
     (#langSelect, tested elsewhere) — a French message should get a
     French reply regardless of what the buttons are labeled in. Wording
     is model-generated and non-deterministic, so match on common
     function words rather than anything exact. A mid-conversation
     switch (same session, no reset) covers "even if she was just
     speaking another language". Placed early, on a fresh session — deep
     in a long-lived test session that's sent dozens of prior messages,
     an occasional genuinely empty reply has been observed from the API
     itself (reproduced directly against the endpoint, not a client
     race), so one retry guards against that transient case here too. */
  const sendAndGetReply = async (text) => {
    for (let attempt = 0; attempt < 2; attempt++) {
      await page.fill("#msg", text);
      await page.keyboard.press("Enter");
      await page.waitForFunction(
        () => !document.getElementById("send").classList.contains("stop"),
        null, { timeout: 30000 }
      );
      const reply = await page.$$eval(".bubble.lissa", (els) => els.at(-1).textContent);
      if (reply.trim()) return reply;
    }
    return "";
  };
  const frReply = await sendAndGetReply(
    "Réponds uniquement par une courte phrase en français : comment vas-tu ?");
  check(/[éèêàçùâî]|\b(je|tu|et|le|la|les)\b/i.test(frReply),
    "language: French message gets a French reply (got: " + frReply.slice(0, 70) + ")");
  const swReply = await sendAndGetReply(
    "Jibu kwa sentensi fupi moja tu kwa Kiswahili: unaendeleaje leo?");
  // no strict \b boundaries: Swahili is agglutinative, so subject/tense
  // markers are prefixes glued onto the verb (e.g. "Ninaendelea" = ni-
  // na-endelea, "I am continuing") rather than separate words like "ni"
  check(/asante|karibu|habari|nzuri|vizuri|vyema|wewe|leo|ninaendelea|naendelea/i.test(swReply),
    "language: switches to Swahili mid-conversation (got: " + swReply.slice(0, 70) + ")");

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
  await menuClick("#resetBtn");
  await page.waitForTimeout(300);
  check(
    await page.$eval("#resetBtn", (el) => el.classList.contains("confirm")),
    "fix2: first tap arms the reset button"
  );
  check((await page.$$(".bubble")).length === bubblesBefore,
    "fix2: single tap does not wipe the chat");
  await menuClick("#resetBtn");
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
    await page.$eval("#voiceBtn", (el) => el.getAttribute("aria-checked") === "false"),
    "fix8: voice toggle exposes pressed state (off)"
  );
  await menuClick("#voiceBtn");
  check(
    await page.$eval("#voiceBtn", (el) => el.getAttribute("aria-checked") === "true"),
    "fix8: aria-checked follows the toggle"
  );
  await menuClick("#voiceBtn"); // back off
  await page.focus("#avatarWrap");
  check(
    await page.evaluate(() => document.activeElement.id === "avatarWrap"),
    "fix8: avatar is keyboard-focusable"
  );
  await menuClick("#memBtn");
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
  await menuClick("#voiceBtn"); // voice back on
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
  await menuClick("#voiceBtn");   // voice off again for the memory tests

  /* ---- photo understanding ---- */
  const png1x1 = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "base64"); // single green pixel
  await page.setInputFiles("#file", { name: "dot.png", mimeType: "image/png", buffer: png1x1 });
  await page.waitForSelector("#attachPreview:not([hidden])", { timeout: 5000 });
  check(true, "photo: picking a file shows the preview chip");
  await page.fill("#msg", "what color is this image? one short sentence");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".bubble.user img", { timeout: 5000 });
  check(true, "photo: user bubble shows the image");
  check(
    await page.$eval("#attachPreview", (el) => el.hidden),
    "photo: preview clears after sending"
  );
  await page.waitForFunction(
    () => !document.getElementById("send").classList.contains("stop"),
    null, { timeout: 60000 }
  );
  const visionReply = await page.$$eval(".bubble.lissa", (els) => els.at(-1).textContent);
  check(visionReply.length > 5 && !visionReply.includes("API error"),
    "photo: she replied about the image (got: " + visionReply.slice(0, 60) + ")");

  /* ---- PWA: manifest, icons, service worker ---- */
  const pwa = await page.evaluate(async () => {
    const man = await fetch("/static/manifest.json").then((r) => (r.ok ? r.json() : null));
    const icon = await fetch("/static/icon-192.png").then((r) => r.ok);
    const sw = await fetch("/sw.js").then((r) => r.ok && (r.headers.get("content-type") || "").includes("javascript"));
    const reg = await navigator.serviceWorker.getRegistration().then((r) => !!r).catch(() => false);
    return { name: man && man.name, icons: man && man.icons.length, icon, sw, reg };
  });
  check(pwa.name === "Lissa" && pwa.icons === 2, "pwa: manifest serves with icons");
  check(pwa.icon, "pwa: app icon serves");
  check(pwa.sw, "pwa: service worker serves from the root");
  check(pwa.reg, "pwa: service worker registered");
  check(
    await page.$eval('link[rel="manifest"]', () => true).catch(() => false),
    "pwa: page links the manifest"
  );

  /* ---- hands-free conversation mode ---- */
  await menuClick("#hfBtn");
  await page.waitForSelector("#recorder:not([hidden])", { timeout: 8000 });
  check(true, "handsfree: toggling on opens the mic by itself");
  check(
    await page.evaluate(() => rec && rec.auto === true),
    "handsfree: recording is in auto (VAD) mode"
  );
  check(
    await page.evaluate(() => voiceOn),
    "handsfree: spoken replies auto-enabled"
  );
  await menuClick("#hfBtn"); // off
  await page.waitForFunction(
    () => document.getElementById("recorder").hidden, null, { timeout: 5000 });
  check(true, "handsfree: toggling off stops listening");
  check(
    await page.$eval("#hfBtn", (el) => el.getAttribute("aria-checked") === "false"),
    "handsfree: button state cleared"
  );
  await menuClick("#voiceBtn"); // voice off again for the remaining tests

  /* ---- web memory: facts persist in localStorage across reloads ---- */
  await page.fill("#msg", "By the way, my name is Zanzibar and I love mango juice. Remember that!");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => !busy, null, { timeout: 60000 });
  await menuClick("#resetBtn");
  await menuClick("#resetBtn"); // confirm — distills memory, then resets
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

  /* ---- transcript export ---- */
  await menuClick("#memBtn");
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 10000 }),
    page.click("#exportBtn"),
  ]);
  check(download.suggestedFilename() === "lissa-chat.txt",
    "export: downloads lissa-chat.txt");
  const saved = require("fs").readFileSync(await download.path(), "utf8");
  check(saved.includes("Lissa: "), "export: transcript contains her messages");
  await page.click("#closeBtn"); // the panel stayed open for the export click

  /* ---- header overflow menu ---- */
  const menuHidden = () => page.$eval("#menu", (el) => el.hidden);
  check(await menuHidden(), "menu: closed on load");
  await page.click("#menuBtn");
  check(!(await menuHidden()), "menu: opens on click");
  check(
    await page.$eval("#menuBtn", (el) => el.getAttribute("aria-expanded") === "true"),
    "menu: trigger reports expanded"
  );
  check(
    (await page.$$eval("#menu .menuItem:not(.langRow)", (els) => els.map((e) => e.id))).join() ===
      "hfBtn,voiceBtn,themeBtn,memBtn,resetBtn",
    "menu: holds all five relocated controls"
  );
  check(
    await page.$eval("#menu #langSelect", (el) => !!el),
    "menu: language select lives in the menu, not the memory panel"
  );
  check(
    (await page.$$("#panel #langSelect")).length === 0,
    "menu: memory panel no longer has a language select"
  );
  // a toggle keeps the menu open so its new state is visible
  await page.click("#voiceBtn");
  check(!(await menuHidden()), "menu: stays open after a toggle");
  await page.click("#voiceBtn"); // restore
  // arrow keys move between items
  await page.click("#menuBtn"); // close
  await page.click("#menuBtn"); // reopen with a clean focus state
  await page.keyboard.press("ArrowDown");
  check(await page.evaluate(() => document.activeElement.id === "hfBtn"),
    "menu: ArrowDown focuses the first item");
  await page.keyboard.press("ArrowDown");
  check(await page.evaluate(() => document.activeElement.id === "voiceBtn"),
    "menu: ArrowDown moves to the next item");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp"); // wraps to the last
  check(await page.evaluate(() => document.activeElement.id === "resetBtn"),
    "menu: ArrowUp wraps to the last item");
  await page.keyboard.press("Escape");
  check(await menuHidden(), "menu: Escape closes it");
  check(await page.evaluate(() => document.activeElement.id === "menuBtn"),
    "menu: Escape returns focus to the trigger");
  // nothing may paint over the open menu. The header's backdrop-filter
  // makes it a stacking context, so without a layer of its own it sits
  // under #chat and a wide bubble covers the menu (seen on Android).
  await page.click("#menuBtn");
  await page.evaluate(() => {
    // a bubble wide enough to reach under the menu
    addBubble("lissa", "x".repeat(400));
    chat.scrollTop = 0;
  });
  const covering = await page.evaluate(() => {
    const menu = document.getElementById("menu");
    const m = menu.getBoundingClientRect();
    const bad = [];
    for (const fx of [0.05, 0.3, 0.6, 0.95])
      for (const fy of [0.1, 0.35, 0.6, 0.9]) {
        const el = document.elementFromPoint(m.left + m.width * fx, m.top + m.height * fy);
        if (!menu.contains(el)) bad.push(el ? el.className || el.tagName : "null");
      }
    return [...new Set(bad)];
  });
  check(covering.length === 0,
    "menu: nothing paints over it" + (covering.length ? " (covered by " + covering.join() + ")" : ""));
  await page.click("#menuBtn"); // close

  await page.click("#menuBtn");
  await page.click("#title"); // click outside
  check(await menuHidden(), "menu: clicking outside dismisses it");

  // closing must not strand focus inside the hidden menu: a key pressed
  // there still routes through the menu's handler and would swallow the
  // Escape meant for whatever the item opened (caught by CI, not locally)
  await menuClick("#memBtn"); // opens the panel and closes the menu
  check(
    await page.evaluate(() => !document.getElementById("menu").contains(document.activeElement)),
    "menu: closing moves focus out of the hidden menu"
  );
  await page.keyboard.press("Escape");
  check(
    await page.$eval("#overlay", (el) => !el.classList.contains("show")),
    "menu: Escape still reaches the panel opened from the menu"
  );

  // Tab must reach the language <select> — it's excluded from arrow-key
  // roving (a native <select> isn't a roving-tabindex item) but still
  // needs to be keyboard-reachable
  await page.click("#menuBtn");
  await page.keyboard.press("ArrowDown"); // focuses hfBtn
  for (let i = 0; i < 5; i++) await page.keyboard.press("Tab"); // through the 5 items
  check(await page.evaluate(() => document.activeElement.id === "langSelect"),
    "menu: Tab reaches the language select after the five items");
  await page.keyboard.press("Tab"); // leaves the menu entirely
  check(await menuHidden(), "menu: tabbing out of it closes it");

  /* ---- time-of-day greeting follows the VISITOR's clock ----
     The server runs in UTC on Render, hours off from most visitors, so
     the phrase has to come from the browser's own hour. Two timezones a
     long way apart: at any moment at least one differs from the server. */
  const phraseFor = (h) =>
    h >= 6 && h < 12 ? "this morning"
      : h >= 12 && h < 17 ? "this afternoon"
        : h >= 17 && h < 21 ? "this evening"
          : "tonight";
  for (const tz of ["Africa/Dar_es_Salaam", "America/Los_Angeles"]) {
    const tzCtx = await browser.newContext({ timezoneId: tz });
    const tzPage = await tzCtx.newPage();
    await tzPage.goto("http://localhost:8765/"); // fresh visitor: no facts
    // she types the greeting out in sync with her speech, so wait for the
    // whole sentence — a partial one has no time phrase in it yet
    await tzPage.waitForFunction(() => {
      const b = document.querySelector(".bubble.lissa");
      return b && !b.querySelector(".typing-dots") && b.textContent.trim().endsWith("?");
    }, null, { timeout: 30000 });
    const tzHour = await tzPage.evaluate(() => new Date().getHours());
    const tzGreet = await tzPage.$eval(".bubble.lissa", (el) => el.textContent);
    check(tzGreet.includes(phraseFor(tzHour)),
      `timezone: ${tz} (hour ${tzHour}) greeted with "${phraseFor(tzHour)}"`);
    await tzCtx.close();
  }

  /* ---- light/dark theme toggle ---- */
  const isLight = () => page.evaluate(() => document.documentElement.getAttribute("data-theme") === "light");
  const themeLightBefore = await isLight();
  await menuClick("#themeBtn");
  const themeLightAfter = await isLight();
  check(themeLightAfter !== themeLightBefore, "theme: toggle flips the active theme");
  check(
    await page.$eval(
      "#themeBtn",
      (el, expected) => el.getAttribute("aria-checked") === expected,
      String(themeLightAfter)
    ),
    "theme: menu item aria-checked matches the active theme"
  );
  const themeStored = await page.evaluate(() => localStorage.getItem("lissa_theme"));
  check(themeStored === (themeLightAfter ? "light" : "dark"),
    "theme: choice persisted to localStorage");

  await page.reload();
  await page.waitForFunction(() => {
    const b = document.querySelector(".bubble.lissa");
    return b && !b.querySelector(".typing-dots");
  }, null, { timeout: 30000 });
  check(await isLight() === themeLightAfter,
    "theme: survives a reload with no flash (set before first paint)");

  /* ---- UI localization ---- */
  const enPlaceholder = await page.$eval("#msg", (el) => el.placeholder);
  if (await page.$eval("#menu", (el) => el.hidden)) await page.click("#menuBtn");
  await page.selectOption("#langSelect", "fr");
  await page.click("#menuBtn"); // close the menu
  await page.waitForTimeout(100);
  check(
    await page.$eval("#msg", (el) => el.placeholder) !== enPlaceholder,
    "i18n: switching language changes chrome text (placeholder)"
  );
  check(
    await page.evaluate(() => document.documentElement.lang) === "fr",
    "i18n: <html lang> follows the selected language"
  );
  const langStored = await page.evaluate(() => localStorage.getItem("lissa_lang"));
  check(langStored === "fr", "i18n: choice persisted to localStorage");

  await page.fill("#msg", "dis bonjour en un mot");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => !document.getElementById("send").classList.contains("stop"),
    null, { timeout: 30000 });
  check(true, "i18n: chat still works with a non-English UI language");

  await page.reload();
  await page.waitForFunction(() => {
    const b = document.querySelector(".bubble.lissa");
    return b && !b.querySelector(".typing-dots");
  }, null, { timeout: 30000 });
  check(
    await page.$eval("#msg", (el) => el.placeholder) !== enPlaceholder,
    "i18n: chosen language survives a reload"
  );
  if (await page.$eval("#menu", (el) => el.hidden)) await page.click("#menuBtn");
  await page.selectOption("#langSelect", "en"); // restore for cleanliness
  await page.click("#menuBtn"); // close the menu

  /* ---- privacy page ---- */
  await menuClick("#memBtn");
  const privacyHref = await page.$eval(".privacyLink", (el) => el.getAttribute("href"));
  check(privacyHref === "/privacy", "privacy: link in the panel points at /privacy");
  const privacyResp = await page.request.get("http://localhost:8765/privacy");
  check(privacyResp.ok(), "privacy: /privacy serves 200");
  const privacyBody = await privacyResp.text();
  check(privacyBody.includes("Gemini") && privacyBody.includes("Forget me"),
    "privacy: page mentions Gemini and the Forget-me control");
  await page.click("#closeBtn");

  await browser.close();
  console.log(failures === 0 ? "\nALL PASSED" : `\n${failures} FAILURE(S)`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error("TEST CRASHED:", e); process.exit(2); });
