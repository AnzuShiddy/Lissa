# LucidDive

A few chatbots, each with its own job, sharing one engine and one server.
Powered by the **Google Gemini API free tier** — streaming replies, voice
both ways, and memory between visits, at no cost.

**Live:** <https://lissa-02zl.onrender.com> (free tier — the first visit
after a quiet spell takes ~30s to wake).

| bot | at | what it's for |
| --- | --- | --- |
| **Lissa** 💋 | `/lissa` | A warm, playful companion for late-night conversation. |
| **Athar** 🌙 | `/athar` | Questions about Islam, answered from the Qur'an and the authentic Sunnah. |
| **Somo** 📘 | `/somo` | A study partner for the Tanzanian secondary syllabus, Form One to Four. |

The landing page at `/` lists whatever bots are registered. Everything
below the persona — streaming, memory, recall, voice, analytics, rate
limits, the web UI — is shared; a bot is a configuration, not a fork.

> **Athar is an AI, not a scholar.** It can be wrong, and it is told to say
> so. Nothing there replaces a qualified teacher, and the app says as much
> at the top of every conversation.

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

**Web** (recommended — chat bubbles, mic button, spoken replies):

```bash
.venv/bin/uvicorn app:app --port 8000    # or ./run_web.sh
```

Open <http://localhost:8000> for the landing page, or go straight to
<http://localhost:8000/lissa> or <http://localhost:8000/athar>. The browser
handles the microphone and speakers, so nothing extra is needed. Tap 🎤 to
record (or **press and hold** to talk walkie-talkie style — release to
send), 🔊 to toggle spoken replies, 🔄 to start fresh (it asks for a second
tap so a stray click can't wipe the chat).

**Terminal** — one bot per run. Name it by slug, or omit it for a picker:

```bash
.venv/bin/python cli.py lissa
.venv/bin/python cli.py athar     # or ./run.sh <slug>
.venv/bin/python cli.py           # pick from the list
```

| Command   | Effect                                                 |
|-----------|--------------------------------------------------------|
| `/talk`   | Speak your message instead of typing (`/t` for short)  |
| `/voice`  | Toggle spoken replies on/off                           |
| `/memory` | Show what this bot remembers about you                 |
| `/forget` | Wipe its long-term memory                              |
| `/reset`  | Clear the current conversation (long-term memory kept) |
| `/quit`   | Exit (Ctrl-D also works)                               |

For spoken replies and voice input in the terminal, install the PulseAudio
tools (WSL2/Ubuntu — playback and mic in one):

```bash
sudo apt install -y pulseaudio-utils
```

**Mobile apps** (Android & iOS via Capacitor):

```bash
npm install
npm run cap:sync
npm run cap:open:android  # Android Studio
npm run cap:open:ios      # Xcode (macOS only)
```

See [docs/MOBILE.md](docs/MOBILE.md) for build and store-submission steps.

## Adding a bot

Create `bots/<slug>/`, build a `Bot` (see `core/persona.py` for the full
field list), and register it in `bots/__init__.py`. Nothing else needs to
change — routes, the landing page, the manifest, the UI theme and the
memory namespace all key off the slug.

The fields worth knowing: `system_prompt` and `sections` carry the voice;
`memory_prompt` and `extras_name` control what gets distilled and what the
third memory list is called (Lissa keeps running jokes, Athar keeps
resolutions); `flavours` is the per-day mood pool; `langs` and `rtl_langs`
set the UI languages; `greetings` / `returning` / `awhile` are the scripted
first lines; `edge_voice` and `edge_rate` pick the speaking voice;
`palette` and `avatar_svg` set the look; and `features` gates optional
machinery — a bot without `"prayer"` simply has no `/api/<slug>/prayer`
endpoint, and a bot without `"syllabus"` has no `/api/<slug>/syllabus`.

## How it works

### Shared engine (`core/`)

- **Streaming**: replies arrive chunk-by-chunk for a natural chat feel.
- **Model**: `gemini-flash-lite-latest` — an alias that always points at
  Google's newest Flash-Lite model, so nothing breaks when older models are
  retired. Lite is used because its free-tier daily quota is much higher
  than full Flash. Thinking is disabled for quick, snappy replies.
- **Sessions**: the web app is multi-user and stateless — each visitor gets
  an isolated in-memory session kept ~4 hours, then dropped. No database,
  no accounts.
- **Long-term memory** (weighted and decaying): when a chat ends, the
  conversation is distilled into short facts about you. Rather than a flat
  list rewritten wholesale, each fact is a **weighted record that fades
  unless you bring it up again** — a one-off remark decays over a few
  conversations while something you mention often hardens and sticks.
  Identity facts (name, where you live, your work) are marked **core** and
  never decay. In the browser these live in *your* local storage; the
  terminal keeps a file per bot under `.memory/<slug>.json`. Logic in
  `core/memory_store.py`, suite in `tests/test_memory_store.py`.
- **Relevant recall**: rather than dumping every fact into every prompt,
  each message is embedded and only the facts close to it (plus core facts,
  which are context for everything) ride along. It degrades to sending
  everything on any hiccup, and skips the embedding call entirely when
  there are only a handful of facts. Lives in `core/recall.py`.
- **Relationship continuity**: memory holds more than facts. Each bot
  tracks **open threads** — things you left unresolved — and asks about one
  in its first reply next time. It knows how long it's known you and how
  many times you've talked, and greets you differently after a long gap
  than after a day.
- **Voice in**: your speech is recorded (by the browser, or via `/talk` in
  the terminal), sent to Gemini for transcription, and chatted exactly as
  if you had typed it. Works in any language you speak.
- **Voice out (web)**: each bot speaks *while it types* — as each sentence
  streams in it's synthesized with Edge's free neural voices (via
  `edge-tts`) and the clips play in order, so the first sentence is audible
  while the rest is still being written. Voices are slowed a touch and
  given a breath between sentences so a long reply lands as separate
  thoughts. If the voice server is unreachable, the browser's built-in
  speech is the last resort. Capture runs on an `AudioWorklet`, with a
  `ScriptProcessorNode` fallback for older browsers.
- **The typing keeps step with the voice.** When a clip plays, its own
  duration paces the text. When there's no clip to measure — autoplay
  blocked before the first tap, a playback error, or the browser voice
  standing in — the pace is derived from the bot's speaking rate instead of
  a fixed guess, so slowing a bot down slows its typing to match. Set
  `PLATFORM_EDGE_RATE` (or `PLATFORM_EDGE_RATE_<SLUG>` for one bot) to
  change the speed without a code change; both the voice and the typing
  follow it, as does the browser stand-in voice.
- **Voice out (terminal)**: Gemini's free TTS
  (`gemini-3.1-flash-tts-preview`) through PulseAudio. That free tier is
  only ~10 requests/day, so the terminal falls back to text-only when it
  runs out; the web app sticks to Edge voices and never touches that quota.
- **Anonymous analytics**: one JSON event per visit, message and voice use
  — timestamps, message *lengths*, feature flags, and whether the visitor
  is new or returning. Never message content; sessions appear only as a
  one-way hash. Events append to `analytics.jsonl` and mirror to stdout so
  a host's log store keeps a durable copy — on a free tier with no disk that
  log *is* the archive, and `tools/ingest_analytics.py` merges an export back
  into the event log so a deploy doesn't cost you your history.
  `GET /api/stats` aggregates the last two weeks and **requires**
  `?token=<PLATFORM_STATS_TOKEN>`; with no token configured it is closed
  rather than open. `/healthz` is the open heartbeat and carries no counts.
  Logic in `core/analytics.py`, suites in `tests/test_analytics.py` and
  `tests/test_ingest.py`.
- **Rate limits**: a token bucket per session (`PLATFORM_RATE_PER_MIN`,
  default 8) and a daily ceiling (`PLATFORM_DAILY_CALLS`, default 600)
  protect the shared key. Hitting one gets an in-character "give me a sec"
  rather than an error, and the conversation is not lost.
- **Size limits**: a message is capped at `PLATFORM_MAX_MESSAGE` characters
  (default 4000) and a photo at 4 MB, so nothing unbounded reaches the model.
  The composer carries the same number, so a real visitor is stopped at the
  keyboard rather than trimmed on the way. The session store is capped too
  (`PLATFORM_MAX_SESSIONS`, default 400): sessions expire after ~4 hours, but
  age alone bounds how *long* a conversation is held rather than how many are
  held at once, and each one holds a full chat history. Over the cap, the
  least recently used are dropped. Suite in `tests/test_limits.py`.
- **Logs**: startup and shutdown, API errors (429s and the rest), and TTS
  fallbacks go to stdout alongside the `analytics ` lines — codes and bot
  slugs only, never message content. `PLATFORM_LOG_LEVEL` sets the level.

### The web UI (`static/app.html`)

One page serves every bot, themed from its palette at load. It gives you a
stop button that keeps the text already streamed, multiline input (Enter
sends, Shift+Enter newlines), smart scrolling that stays put while you
re-read, restoration after a refresh, copy buttons, retry on connection
errors, time labels between messages, a light/dark toggle with no flash of
the wrong theme, and a localized interface. Replies are announced to screen
readers, every control is labelled and focusable, Escape closes dialogs.

### Lissa

Her tastes are deliberately *specific* (Afrobeats and old soul, mangoes
over the sink, a night owl who burns everything she cooks except eggs)
rather than "she has opinions" — without fixed details a persona invents
different favourites every conversation, which is what makes a companion
feel like a vibe instead of a person. The prompt teaches her to read the
room: match energy and message length, don't end every message with a
question (the classic chatbot tell), validate before problem-solving, and
notice wind-down cues so a conversation gets to land. She has a spine, and
concedes only when actually convinced. She collects **running jokes** and
is told to call one back only when the moment invites it — never to explain
it, never in a serious moment.

**If you're in real distress** she stops performing: she drops the
flirtiness, takes it seriously the first time, and points you at people who
can actually help ([findahelpline.com](https://findahelpline.com) lists
free lines by country). She's told plainly that she isn't a therapist. An
ordinary bad day just gets a friend, not a hotline.

### Athar

Athar answers from the Qur'an, the authentic Sunnah and the understanding
of the salaf, in the voice of a warm friend rather than a lecture. It is
under strict instructions never to invent a verse, hadith, chain, number or
grading; to name the collection and grading when it cites one; and to say
plainly when it's recalling a meaning rather than a wording. It refers
anything that turns on the details of a real life — divorce, oaths,
inheritance, custody, contracts — to a qualified scholar or a local imam,
and represents genuine scholarly disagreement fairly. Hard limits: no
takfir of individuals, no insulting other Muslims or sects, nothing that
assists violence or helps anyone use religion to control another person.

**Prayer times, qibla and the Hijri date** are computed locally in
`core/prayer.py` from your coordinates — no key, no API call, works
offline. Solar declination and the equation of time come from the standard
low-precision almanac formulae, then the hour angle at which the sun
reaches each prayer's defining altitude. Seven conventions (MWL, ISNA,
Egypt, Umm al-Qura, Karachi, Gulf, Singapore) with majority or Hanafi Asr.
Spot-checked against published timetables in `tests/test_prayer.py`.

Two honest caveats, carried in the UI and in the prompt: calculated times
differ from a masjid's by a few minutes for real reasons (convention,
elevation, rounding) — **the local masjid takes precedence**; and the
Hijri date is the arithmetic calendar, which can sit a day off a moon
sighting, and around the two Eids that is the entire question. At high
latitudes, where the sun never reaches the Fajr or Isha angle, those times
come back empty rather than invented.

### Somo

Somo teaches by asking. A tutor that simply answers is a worse search engine,
so its first move is almost never the answer: it's a question back, aimed
just past what the student has shown it they can do, one at a time. It says
plainly whether an answer was right before moving on, and when someone is
wrong it asks the question that makes the contradiction visible rather than
correcting them outright. Two failed attempts on the same step and it stops
asking and teaches it — Socratic method with someone genuinely lost is just
cruelty with extra steps. Facts get told, not interrogated: a definition, a
formula, a date is simply given. Homework gets walked through a step at a
time, never done.

**It is grounded in the real syllabus.** `core/syllabus.py` reads the
Tanzania Institute of Education 2023 competence-based syllabus for Ordinary
Secondary Education from `data/syllabus/` — 14 subjects, Form I–IV, 769
learning activities parsed from the official TIE PDFs, each keeping the main
competence, the specific competence and the activity as TIE worded them. No
key, no API call, offline, like `core/prayer.py`.

That wording is the point: Somo can quote what a student is actually assessed
against instead of improvising a plausible topic list, and it is told not to
present anything outside that text as syllabus. `GET /api/somo/syllabus`
lists what it holds, because the honest answer to "does it know my subject"
is that list rather than the bot's own say-so.

The unit of grounding is (subject, form) — the whole syllabus is ~206k
characters, far too much for a prompt, while one form of one subject is
~2–3k. So Somo's first job is establishing which one it's working in, in
either English or Kiswahili ("form two biology", "kidato cha nne, fizikia").
That's held on the conversation rather than in the browser: it's settled by
asking, and re-asking after a few hours away is natural for a tutor in a way
that re-asking for someone's coordinates would not be.

Two honest limits. Literature in English only runs Form III–IV, and the data
says so rather than inventing a Form One syllabus. And 22 of the 769 learning
activities didn't survive extraction from TIE's PDFs; the competence above
each is intact, so those rows still carry, but the gap is real — and it is a
gap in the parse, not in the syllabus.

## Layout

| path | what it is |
| --- | --- |
| `app.py` | FastAPI server — slug-routed chat, voice, prayer, stats |
| `cli.py` | terminal app for any bot: `python cli.py <slug>` |
| `core/engine.py` | sessions, streaming, rate limits, model calls |
| `core/persona.py` | the `Bot` type and the registry |
| `core/memory_store.py` | weighted, decaying long-term memory |
| `core/recall.py` | semantic recall — only the relevant facts per message |
| `core/speech.py` | transcription and TTS |
| `core/prayer.py` | prayer times, qibla, Hijri date (standard library only) |
| `core/syllabus.py` | the TIE secondary syllabus, read locally |
| `data/syllabus/` | 14 subjects, Form I–IV, from the official TIE 2023 PDFs |
| `core/analytics.py` | anonymous usage counters |
| `bots/<slug>/` | one directory per bot: prompts, config, avatar |
| `static/landing.html` | the bot picker at `/` |
| `static/app.html` | the chat UI, themed per bot |
| `tools/ingest_analytics.py` | merge a Render log export back into the event log |
| `tools/` | icon generation and other one-off scripts |

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

Pure logic — no API calls, no key needed.

`tests/ui_test.js` drives the web app end-to-end in headless Chromium
(Playwright), covering streaming, stop/retry, scrolling, voice recording
through a fake mic, photos, the header menu, memory and relationship
continuity, crisis handling, localization, themes and accessibility. It
runs against the real Gemini API, so a full pass costs roughly 20 calls of
free-tier quota. With the server running on port 8765:

```bash
NODE_PATH=$(npm root -g) node tests/ui_test.js
```

## Deploy

`render.yaml` is set up for Render's free tier; set `GEMINI_API_KEY` in the
dashboard. Useful environment variables: `PLATFORM_EDGE_RATE` (and
`PLATFORM_EDGE_RATE_<SLUG>`) to change how fast a bot speaks — the typing
follows it — `PLATFORM_RATE_PER_MIN`, `PLATFORM_DAILY_CALLS`,
`PLATFORM_MAX_MESSAGE`, `PLATFORM_MAX_SESSIONS`, `PLATFORM_LOG_LEVEL`,
`PLATFORM_STATS_TOKEN` (**required** to open `/api/stats` at all),
`PLATFORM_ANALYTICS_FILE`. Details in
[docs/DEPLOY.md](docs/DEPLOY.md).

## Launch & demo tooling

- **[docs/LAUNCH.md](docs/LAUNCH.md)** — copy-paste launch-post drafts, one
  per platform (Reddit, Show HN, X, Discord, Facebook).
- **`togif.sh`** — turn a screen recording into a small, sharp GIF for
  those posts, using ffmpeg's two-pass palette method so on-screen text
  stays legible. Needs `ffmpeg`.

  ```bash
  ./togif.sh recording.mp4                       # -> recording.gif
  START=2 DURATION=10 ./togif.sh recording.mp4   # trim to 10s from 0:02
  FPS=10 WIDTH=480 ./togif.sh recording.mp4      # smaller file
  ```
