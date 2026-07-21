# Lissa 💋

A charming, warm companion chatbot for social conversation, powered by the
**Google Gemini API free tier** — streaming responses and multi-turn memory,
at no cost.

**Try her live:** <https://lissa-02zl.onrender.com> (free tier — the first
visit after a quiet spell takes ~30s to wake).

**Now available as a native mobile app!** Build for Android or iOS with Capacitor. See [MOBILE.md](MOBILE.md) for setup and build instructions.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Get a **free API key** (no credit card required):

1. Go to <https://aistudio.google.com/apikey>
2. Sign in with a Google account and click "Create API key"
3. Export it:

```bash
export GEMINI_API_KEY=your-key-here
```

## Run

**Web app** (recommended — chat bubbles, mic button, spoken replies in the
browser):

```bash
.venv/bin/uvicorn app:app --port 8000    # or ./run_web.sh
```

Then open <http://localhost:8000>. The browser handles the microphone and
speakers itself, so nothing extra needs to be installed. Tap 🎤 to record a
voice message (or **press and hold** to talk walkie-talkie style — release
to send), 🔊 to toggle spoken replies, and 🔄 to start a fresh conversation
(it asks for a second tap so a stray click can't wipe the chat).

The web chat also gives you:

- **Stop button** — the send button turns into a stop square while she's
  replying; stopping cuts her voice mid-sentence and keeps the text that
  already arrived.
- **Multiline input** — the box grows as you type; Enter sends,
  Shift+Enter makes a newline.
- **Smart scrolling** — scroll up to re-read and the view stays put while
  she keeps typing; a "new message" pill jumps you back down.
- **Survives a refresh** — reload the page and the conversation is
  restored (the server keeps your session for a few hours).
- **Copy button** on her messages (hover or tap a bubble).
- **Retry on connection errors** — a "try again" button resends your last
  message instead of dead-ending.
- **Time labels** appear between messages when more than 5 minutes pass.
- **Screen-reader and keyboard friendly** — replies are announced, every
  control is labelled and focusable, Escape closes dialogs.
- **Light/dark theme** — the sun/moon toggle in the header switches
  instantly, remembers your choice, and matches your system preference on
  first visit. No flash of the wrong theme on reload.
- **Localized interface** — English, Kiswahili, Français, or Português for
  the app's own buttons, labels, and messages (a switcher lives in the 🧠
  panel, defaulting to your browser's language). Her actual replies
  already follow whatever language you type in — this only covers the
  chrome around them, plus the scripted greeting and rate-limit messages,
  which are canned text rather than Gemini output.
- **Privacy notice** at `/privacy` (linked from the 🧠 panel) — plain
  language about what's stored where, in English only.

**Mobile apps** (Android & iOS via Capacitor):

```bash
npm install
npm run cap:sync
npm run cap:open:android  # Android Studio
npm run cap:open:ios      # Xcode (macOS only)
```

See [MOBILE.md](MOBILE.md) for detailed setup, build, and app store submission instructions.

**Terminal version**:

```bash
.venv/bin/python lissa.py
```

For spoken replies and voice input in the terminal, also install the
PulseAudio tools (WSL2/Ubuntu — provides both playback and mic recording):

```bash
sudo apt install -y pulseaudio-utils
```

## Terminal commands

| Command   | Effect                                                |
|-----------|-------------------------------------------------------|
| `/talk`   | Speak your message instead of typing (`/t` for short) |
| `/voice`  | Toggle spoken replies on/off                          |
| `/memory` | Show what Lissa remembers about you                   |
| `/forget` | Wipe her long-term memory                             |
| `/reset`  | Clear the current conversation (long-term memory kept)|
| `/quit`   | Exit (Ctrl-D also works)                              |

## How it works

- **Two front ends, one brain**: `lissa.py` holds the persona, memory,
  transcription and TTS logic and is also the terminal app; `app.py` is a
  small FastAPI server that exposes the same logic to the web page in
  `static/index.html`. The terminal app persists memory to
  `lissa_memory.json`; the web app is multi-user and stateless — each
  visitor gets an isolated in-memory session (kept ~4 hours) and nothing
  persists between sessions.
- **Persona** lives in the system prompt in `lissa.py` — edit it to tune
  Lissa's personality, style, and boundaries. Her tastes are deliberately
  *specific* (Afrobeats and old soul, mangoes over the sink, a night owl
  who burns everything she cooks except eggs, competitive about trivia,
  hopeless with directions) rather than "she has opinions" — without fixed
  details she invents different favourites every conversation, which is
  what makes a companion feel like a vibe instead of a person. Swap them
  for your own; keep them concrete, and keep a flaw or two.
- **If you're in real distress** she stops performing: she drops the
  flirtiness, takes it seriously the first time, and points you at people
  who can actually help — emergency services, a crisis line, or someone you
  trust ([findahelpline.com](https://findahelpline.com) lists free lines by
  country). She's told plainly that she isn't a therapist and shouldn't try
  to talk anyone through a crisis alone. An ordinary bad day just gets a
  friend, not a hotline.
- **Long-term memory**: when a chat ends (`/quit`, Ctrl-D, or `/reset`),
  Lissa distills the conversation into short facts about you — name,
  preferences, ongoing topics — saved to `lissa_memory.json`. On the next
  start those facts are woven into her persona, so she greets you like
  someone she knows. Delete the file (or use `/forget`) to start over.
- **She has her own day**: a mood is drawn once per calendar day and kept,
  so she's recognisably herself through a conversation rather than lurching
  about — restless, mellow, wistful, mischievous. It colours her tone and
  what she brings up unprompted, but it's *her* mood, not yours: she's
  never cold or short with you because of it, and it stops mattering
  entirely the moment you need her. The mood list lives in `lissa.py`.
- **Relationship continuity**: memory holds more than facts. She tracks
  **open threads** — things you left unresolved — and asks about one of
  them in her first reply next time ("wait, first — did you ever hear back
  about that interview?"). She also knows how long she's known you and how
  many times you've talked, which colours how she talks to you, and greets
  you differently after a long gap than after a day. Older `lissa_memory.json`
  files in the previous plain-list format upgrade automatically.
- **In-session memory**: the SDK's chat session keeps the conversation
  history, so Lissa remembers everything said in the session.
- **Voice input**: your speech is recorded (in the web app by the browser;
  in the terminal via `/talk`, with WSLg routing your Windows mic through
  PulseAudio), sent to Gemini for transcription, and the transcript is
  chatted to Lissa exactly as if you had typed it. Works in any language
  you speak.
- **Voice (web)**: she speaks *while she types* — as each sentence of the
  reply streams in, it's synthesized immediately with Edge's free neural
  voice (`en-US-AvaMultilingualNeural`, via `edge-tts`) and the clips play
  in order, so her first sentence is audible while the rest is still being
  written, with the text typing out in sync. If the voice server is
  unreachable, the browser's built-in speech is the last resort. Voice
  capture runs on an `AudioWorklet` (with a `ScriptProcessorNode` fallback
  for older browsers).
- **Voice (terminal)**: replies are spoken with Gemini's free TTS
  (`gemini-3.1-flash-tts-preview`, "Leda" voice) through PulseAudio. Note
  the Gemini TTS free tier is only ~10 requests/day; the terminal falls
  back to text-only when it runs out. The web app sticks to the Edge voice
  so sentence-level clips never touch that quota.
- **Streaming**: replies print chunk-by-chunk for a natural chat feel.
- **Model**: `gemini-flash-lite-latest` — an alias that always points at
  Google's newest Flash-Lite model, so Lissa keeps working when older models
  are retired. Lite is used because its free-tier daily quota is much higher
  than the full Flash model's. Thinking is disabled for quick, snappy
  conversational replies.

## Tests

`tests/ui_test.js` drives the web app end-to-end in headless Chromium
(Playwright) — 104 checks covering streaming, stop/retry, scrolling, voice
recording through a fake mic, photos, the header menu, memory and
relationship continuity, crisis handling, localization, themes and
accessibility. They run against the real Gemini API, so a full pass costs
roughly 20 calls of free-tier quota. With the server running on port 8765:

```bash
NODE_PATH=$(npm root -g) node tests/ui_test.js
```

## Free-tier limits

The Gemini free tier is rate-limited (around 15 requests per minute and a
daily cap) — plenty for personal chatting. If you ever hit the limit, Lissa
tells you to wait a few seconds; the conversation is not lost.
