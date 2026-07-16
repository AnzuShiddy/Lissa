# Lissa 💋

A charming, warm companion chatbot for social conversation, powered by the
**Google Gemini API free tier** — streaming responses and multi-turn memory,
at no cost.

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
speakers itself, so nothing extra needs to be installed. Click 🎤 to speak a
message (click again to finish), 🔊 to toggle spoken replies, 🧠 to see (or
wipe) her memory, and 🔄 to start a fresh conversation.

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
  `static/index.html`. Both share `lissa_memory.json`, so she remembers you
  across either.
- **Persona** lives in the system prompt in `lissa.py` — edit it to tune
  Lissa's personality, style, and boundaries.
- **Long-term memory**: when a chat ends (`/quit`, Ctrl-D, or `/reset`),
  Lissa distills the conversation into short facts about you — name,
  preferences, ongoing topics — saved to `lissa_memory.json`. On the next
  start those facts are woven into her persona, so she greets you like
  someone she knows. Delete the file (or use `/forget`) to start over.
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
  written. If the voice server is unreachable, the browser's built-in
  speech is the last resort.
- **Voice (terminal)**: replies are spoken with Gemini's free TTS
  (`gemini-3.1-flash-tts-preview`, "Leda" voice) through PulseAudio. Note
  the Gemini TTS free tier is only ~10 requests/day; the terminal falls
  back to text-only when it runs out, and the web app doesn't use it at
  all.
- **Streaming**: replies print chunk-by-chunk for a natural chat feel.
- **Model**: `gemini-flash-latest` — an alias that always points at Google's
  newest Flash model (currently Gemini 3.5 Flash), so Lissa keeps working
  when older models are retired. Thinking is disabled for quick, snappy
  conversational replies.

## Free-tier limits

The Gemini free tier is rate-limited (around 15 requests per minute and a
daily cap) — plenty for personal chatting. If you ever hit the limit, Lissa
tells you to wait a few seconds; the conversation is not lost.
