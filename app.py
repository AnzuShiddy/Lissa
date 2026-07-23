#!/usr/bin/env python3
"""Lissa web app — FastAPI backend wrapping the chatbot logic in lissa.py.

Run:  .venv/bin/uvicorn app:app --port 8000
Then open http://localhost:8000 in your browser.

Multi-user, stateless. Each visitor has an isolated session; no memory persists.
The browser handles the microphone and speaker; this server keeps the Gemini
API key private and reuses lissa.py for the persona, transcription and TTS.
"""

import base64
import os
import queue
import secrets
import threading
import time
from pathlib import Path

import edge_tts
from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.genai import errors, types
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import analytics
import lissa

STATIC_DIR = Path(__file__).parent / "static"

# When set, /api/stats requires ?token=<this>; unset leaves it open.
STATS_TOKEN = os.environ.get("LISSA_STATS_TOKEN", "")

# Free neural voice for greetings and for when Gemini's TTS quota is spent.
EDGE_VOICE = "en-US-AvaMultilingualNeural"

# After a Gemini TTS quota 429, don't retry it for this long.
GEMINI_TTS_COOLDOWN = 30 * 60

# The public deployment serves everyone from one shared API key, so throttle
# quota-burning calls: a per-visitor token bucket plus a global daily cap.
RATE_PER_MIN = float(os.environ.get("LISSA_RATE_PER_MIN", "8"))
DAILY_CALLS = int(os.environ.get("LISSA_DAILY_CALLS", "600"))

_daily_lock = threading.Lock()
_daily = {"day": "", "count": 0}

# These are canned strings (not Gemini output), so unlike her actual replies
# they don't automatically follow the visitor's language — localize by hand.
RATE_LIMIT_MSG = {
    "en": "(whoa, you're fast 😅 — give me about {wait}s to catch my breath)",
    "sw": "(lo, wewe ni mwepesi 😅 — nipe sekunde {wait} nipumzike)",
    "fr": "(waouh, tu es rapide 😅 — laisse-moi environ {wait}s pour reprendre mon souffle)",
    "pt": "(uau, você é rápido 😅 — me dê uns {wait}s para recuperar o fôlego)",
}
DAILY_CAP_MSG = {
    "en": "(I've been chatting all day and I need to rest my voice — come back tomorrow? 💋)",
    "sw": "(Nimekuwa nikizungumza siku nzima na ninahitaji kupumzisha sauti yangu — unaweza kurudi kesho? 💋)",
    "fr": "(J'ai discuté toute la journée et j'ai besoin de reposer ma voix — tu reviens demain ? 💋)",
    "pt": "(Eu conversei o dia todo e preciso descansar minha voz — pode voltar amanhã? 💋)",
}

app = FastAPI(title="Lissa")


def take_quota(sess: "UserSession", lang: str = "en", per_minute: bool = True) -> tuple[str, int] | None:
    """Spend one quota-burning Gemini call. Returns None when allowed,
    otherwise (in-character message, seconds to wait; 0 = no countdown).
    Background calls (memory distillation) pass per_minute=False so they
    only count against the daily cap, never starve the visitor's chatting."""
    lang = lang if lang in lissa.SUPPORTED_LANGS else "en"
    if per_minute:
        now = time.time()
        sess.tokens = min(
            RATE_PER_MIN, sess.tokens + (now - sess.tokens_at) * (RATE_PER_MIN / 60.0)
        )
        sess.tokens_at = now
        if sess.tokens < 1.0:
            wait = int((1.0 - sess.tokens) * 60.0 / RATE_PER_MIN) + 1
            msg = RATE_LIMIT_MSG.get(lang, RATE_LIMIT_MSG["en"]).format(wait=wait)
            return (msg, wait)
    with _daily_lock:
        today = time.strftime("%Y-%m-%d")
        if _daily["day"] != today:
            _daily["day"], _daily["count"] = today, 0
        if _daily["count"] >= DAILY_CALLS:
            return (DAILY_CAP_MSG.get(lang, DAILY_CAP_MSG["en"]), 0)
        _daily["count"] += 1
    if per_minute:
        sess.tokens -= 1.0
    return None


class UserSession:
    """Isolated chat session for one user, no persistent memory."""

    def __init__(self) -> None:
        self.client = lissa.make_client()
        self.lock = threading.Lock()
        self.tts_retry_at = 0.0
        self.last_used = time.time()
        self.tokens = RATE_PER_MIN  # rate-limit token bucket
        self.tokens_at = time.time()
        self.mem: dict = lissa.blank_memory()
        self.session = self.client.chats.create(
            model=lissa.MODEL,
            config=lissa.build_config(lissa.blank_memory()),  # personalized later via /api/hello
        )

    def touch(self) -> None:
        """Update last-used timestamp for cleanup."""
        self.last_used = time.time()

    def rebuild(self, mem: dict) -> None:
        """Start a fresh chat session personalized with the given memory.
        Call with the session lock held."""
        self.mem = mem
        self.session = self.client.chats.create(
            model=lissa.MODEL, config=lissa.build_config(mem)
        )


# Global session store: session_id -> UserSession
_sessions: dict[str, UserSession] = {}
_sessions_lock = threading.Lock()


def get_or_create_session(session_id: str | None) -> tuple[str, UserSession]:
    """Get or create a user session, return (session_id, session)."""
    with _sessions_lock:
        if session_id and session_id in _sessions:
            sess = _sessions[session_id]
            sess.touch()
            return session_id, sess
        # New session
        sid = session_id or secrets.token_urlsafe(16)
        sess = UserSession()
        _sessions[sid] = sess
        # Cleanup old sessions (>4 hours inactive)
        now = time.time()
        for old_sid, old_sess in list(_sessions.items()):
            if now - old_sess.last_used > 4 * 3600:
                del _sessions[old_sid]
        return sid, sess


MAX_IMAGE_BYTES = 4 * 1024 * 1024


class ChatIn(BaseModel):
    message: str = ""
    image: str | None = None  # optional data URL (image/*)
    lang: str = "en"  # UI language, for the rate-limit message only


def decode_image(data_url: str) -> tuple[bytes, str] | None:
    """Decode a data URL into (bytes, mime). None if invalid or too big."""
    try:
        head, b64 = data_url.split(",", 1)
        mime = head.split(":", 1)[1].split(";", 1)[0]
        if not mime.startswith("image/"):
            return None
        raw = base64.b64decode(b64)
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            return None
        return raw, mime
    except Exception:
        return None


class TTSIn(BaseModel):
    text: str
    edge: bool = False  # true = don't spend Gemini quota on this (greetings)


class FactsIn(BaseModel):
    # The visitor's whole memory record, kept in their own browser. `facts`
    # are weighted records ({text, weight, core, ...}); bare strings are
    # still accepted so browsers holding memory from an older version keep it.
    facts: list[dict | str] = []
    threads: list[str] = []
    jokes: list[str] = []  # running jokes she can call back to
    met: str = ""
    last: str = ""
    chats: int = 0
    mood: str = ""       # her mood, drawn once a day and kept
    mood_day: str = ""
    lang: str = "en"  # UI language, for the greeting only
    hour: int | None = None  # visitor's local hour, for the greeting only

    def memory(self) -> dict:
        return lissa.clean_memory({
            "facts": self.facts, "threads": self.threads,
            "jokes": self.jokes,
            "met": self.met, "last": self.last, "chats": self.chats,
            "mood": self.mood, "mood_day": self.mood_day,
        })


def clean_hour(hour: int | None) -> int | None:
    """The visitor's own clock decides the time-of-day greeting — the server
    runs in UTC and is hours off from most of them. Ignore nonsense values."""
    return hour if isinstance(hour, int) and 0 <= hour <= 23 else None


# Client-supplied memory is sanitized by lissa.clean_memory: it lives in the
# visitor's browser and personalizes only their own session.


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    # served from the root so its scope can cover the whole app
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/privacy")
def privacy() -> FileResponse:
    return FileResponse(STATIC_DIR / "privacy.html", media_type="text/html")


@app.get("/")
def index(sid: str | None = Cookie(None)) -> Response:
    session_id, _ = get_or_create_session(sid)
    html = (STATIC_DIR / "index.html").read_text()
    r = Response(html, media_type="text/html")
    r.set_cookie("sid", session_id, max_age=14400, httponly=True, samesite="lax")
    return r


@app.post("/api/hello")
def hello(body: FactsIn, sid: str | None = Cookie(None)) -> dict:
    """Personalize a fresh session with the visitor's remembered facts
    (stored in their browser) and return the matching greeting. An ongoing
    conversation is never rebuilt — the page restores it via /api/history."""
    _, sess = get_or_create_session(sid)
    # chats/met arrive from the browser's own memory record, so new-vs-return
    # is known without any server-side visitor tracking
    analytics.record("visit", sid, lang=body.lang, chats=body.chats,
                     met=body.met[:10], last=body.last[:10])
    mem = lissa.touch_memory(body.memory())  # this visit counts as one
    with sess.lock:
        if not lissa.transcript_of(sess.session):
            sess.rebuild(mem)
    return {
        "text": lissa.greeting(sess.mem, body.lang, clean_hour(body.hour)),
        "memory": sess.mem,  # the bumped chats/met/last go back to the browser
    }


@app.post("/api/memorize")
def memorize(body: FactsIn, sid: str | None = Cookie(None)) -> dict:
    """Distill the conversation so far into updated facts for the visitor's
    browser to keep. Counts against the daily quota cap only."""
    _, sess = get_or_create_session(sid)
    mem = body.memory()
    if take_quota(sess, per_minute=False):
        return {"memory": mem}
    with sess.lock:
        mem = lissa.distill_facts(sess.client, sess.session, mem)
    return {"memory": mem}


@app.get("/api/history")
def history(sid: str | None = Cookie(None)) -> dict:
    """Return the conversation so far so a page refresh can restore it.
    Empty when the session is new (or expired server-side)."""
    _, sess = get_or_create_session(sid)
    messages = []
    with sess.lock:
        for content in sess.session.get_history():
            text = "".join(p.text for p in content.parts or [] if p.text)
            if any(p.inline_data for p in content.parts or []):
                text = ("📷 " + text).strip() if text else "📷 (photo)"
            if not text:
                continue
            who = "user" if content.role == "user" else "lissa"
            # streamed replies are recorded chunk by chunk — merge them back
            # into one message per turn
            if messages and messages[-1]["who"] == who:
                messages[-1]["text"] += text
            else:
                messages.append({"who": who, "text": text})
    return {"messages": messages}


@app.post("/api/chat")
def chat(body: ChatIn, sid: str | None = Cookie(None)) -> StreamingResponse:
    _, sess = get_or_create_session(sid)

    parts: list = []
    if body.image:
        img = decode_image(body.image)
        if img:
            parts.append(types.Part.from_bytes(data=img[0], mime_type=img[1]))
    text = body.message.strip()
    if text:
        parts.append(text)
    if not parts:
        return StreamingResponse(iter([]), media_type="text/plain; charset=utf-8")

    limited = take_quota(sess, body.lang)
    # lengths and flags only — message content is never logged
    analytics.record("message", sid, len=len(text), image=bool(body.image),
                     lang=body.lang,
                     limited=("day" if limited and not limited[1] else
                              "rate" if limited else None))
    if limited:
        text, wait = limited
        return StreamingResponse(
            iter([text]),
            media_type="text/plain; charset=utf-8",
            headers={"x-ratelimited": str(wait)},  # lets the page show a countdown
        )

    # Generate in a dedicated thread that always runs the Gemini stream to
    # completion. If the client disconnects mid-reply (stop button, closed
    # tab), the abandoned response generator would otherwise stay suspended
    # inside `with sess.lock:` forever and deadlock the whole session.
    q: queue.Queue[str | None] = queue.Queue()

    def produce() -> None:
        try:
            with sess.lock:
                try:
                    sent = False
                    # Narrow the remembered facts to the ones this message
                    # calls for (an embedding round-trip; skipped for small
                    # memories and for a caption-less photo, which has nothing
                    # to match on). The session's own config holds the fuller
                    # set, so a failed lookup just falls back to it.
                    cfg = lissa.turn_config(sess.client, sess.mem, text)
                    for chunk in sess.session.send_message_stream(parts, config=cfg):
                        sent = True
                        if chunk.text:
                            q.put(chunk.text)
                except errors.ClientError as e:
                    # A 400 before any output usually means the request carried
                    # something this model no longer accepts. MODEL is a rolling
                    # alias, and exactly this took the deployment down once when
                    # thinking_budget=0 stopped being valid — so drop the
                    # optional thinking setting and rebuild rather than serving
                    # an error to every visitor until someone notices.
                    if e.code == 400 and not sent and lissa.drop_thinking():
                        try:
                            sess.rebuild(sess.mem)
                            cfg = lissa.turn_config(sess.client, sess.mem, text)
                            for chunk in sess.session.send_message_stream(parts, config=cfg):
                                if chunk.text:
                                    q.put(chunk.text)
                            return
                        except errors.APIError as retry_err:
                            e = retry_err
                    if getattr(e, "code", None) == 429:
                        q.put("\n\n(Free-tier rate limit hit — wait a few seconds and try again.)")
                    else:
                        q.put(f"\n\n(API error {e.code}: {e.message})")
                except errors.APIError as e:
                    q.put(f"\n\n(Gemini had a hiccup ({e.code}) — try again in a moment.)")
        finally:
            q.put(None)  # end of stream

    threading.Thread(target=produce, daemon=True).start()

    def gen():
        while (text := q.get()) is not None:
            yield text

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


@app.post("/api/transcribe")
async def transcribe(request: Request, lang: str = "en", sid: str | None = Cookie(None)) -> dict:
    _, sess = get_or_create_session(sid)
    limited = take_quota(sess, lang)
    analytics.record("transcribe", sid, limited=bool(limited))
    if limited:
        return {"text": None, "error": limited[0]}
    wav_bytes = await request.body()
    if len(wav_bytes) < 4000:  # far too short to contain speech
        return {"text": None}
    text = await run_in_threadpool(lissa.transcribe_wav, sess.client, wav_bytes)
    return {"text": text}


@app.post("/api/say")
async def say(body: TTSIn, sid: str | None = Cookie(None)) -> Response:
    """Speak with Gemini TTS ("Leda", the terminal app's voice) when its
    free-tier quota allows, falling back to the Edge neural voice. The
    browser sends the whole reply as one request so each reply costs one
    Gemini TTS call; greetings set edge=true to skip Gemini entirely."""
    _, sess = get_or_create_session(sid)
    text = lissa.clean_for_speech(body.text)
    if not text:
        return Response(status_code=204)
    analytics.record("say", sid, edge=body.edge)
    if not body.edge and time.time() >= sess.tts_retry_at:
        try:
            wav = await run_in_threadpool(lissa.synthesize, sess.client, text)
            if wav:
                return Response(wav, media_type="audio/wav")
        except lissa.VoiceQuotaError:
            sess.tts_retry_at = time.time() + GEMINI_TTS_COOLDOWN
    try:
        edge_stream = edge_tts.Communicate(text, voice=EDGE_VOICE).stream()
        first = None
        async for msg in edge_stream:
            if msg["type"] == "audio" and msg["data"]:
                first = msg["data"]
                break
        if first is None:
            return Response(status_code=503)

        async def mp3_stream():
            yield first
            try:
                async for msg in edge_stream:
                    if msg["type"] == "audio" and msg["data"]:
                        yield msg["data"]
            except Exception:
                pass

        return StreamingResponse(mp3_stream(), media_type="audio/mpeg")
    except Exception:
        return Response(status_code=503)


@app.post("/api/reset")
def reset(body: FactsIn | None = None, sid: str | None = Cookie(None)) -> dict:
    """Start a new conversation, personalized with whatever facts the
    visitor's browser sends (none = she meets them fresh)."""
    _, sess = get_or_create_session(sid)
    analytics.record("reset", sid)
    mem = body.memory() if body else lissa.blank_memory()
    lang = body.lang if body else "en"
    hour = clean_hour(body.hour) if body else None
    with sess.lock:
        sess.rebuild(mem)
    return {"text": lissa.greeting(mem, lang, hour), "memory": mem}


@app.get("/api/stats")
def usage_stats(token: str = "") -> dict:
    """Aggregate usage numbers (visitors, returning, messages…) for the last
    two weeks — counts only, nothing personal. Note the free tier wipes the
    event file on spin-down; the durable copy is the `analytics` lines in
    Render's logs. Set LISSA_STATS_TOKEN to require ?token=."""
    if STATS_TOKEN and not secrets.compare_digest(token, STATS_TOKEN):
        raise HTTPException(status_code=403)
    return analytics.stats()
