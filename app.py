#!/usr/bin/env python3
"""LucidDive — a small platform for chatbots.

One service, one API key, many bots. The landing page lists them; each bot
lives at /<slug> and talks over /api/<slug>/…, served by the same shell and
the same runtime with a different persona bolted in.

Run:  .venv/bin/uvicorn app:app --port 8000

Multi-user and stateless. A visitor's long-term memory and their coordinates
live in their own browser and ride up with each request; the server keeps a
conversation in memory for a few hours and then forgets it. Nothing about
anyone is written to disk.
"""

import base64
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path

import edge_tts
from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.genai import types
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import bots
from core import analytics, engine, persona, prayer, speech
from core.persona import Bot

STATIC = Path(__file__).parent / "static"
SITE = "LucidDive"

# When set, /api/stats requires ?token=<this>; unset leaves it open.
STATS_TOKEN = os.environ.get("PLATFORM_STATS_TOKEN", "")

MAX_IMAGE_BYTES = 4 * 1024 * 1024

app = FastAPI(title=SITE)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def bot_or_404(slug: str) -> Bot:
    bot = bots.get(slug)
    if bot is None:
        raise HTTPException(status_code=404, detail="no such bot")
    return bot


def feature_or_404(bot: Bot, feature: str) -> Bot:
    if not bot.has(feature):
        raise HTTPException(status_code=404, detail=f"{bot.slug} has no {feature}")
    return bot


# --- request bodies ---------------------------------------------------------

class Place(BaseModel):
    """Where and when the visitor is, as their browser reports it.

    Every field is optional and every one is bounds-checked before use: this
    is client-supplied data that ends up in a system prompt, so nothing here
    is trusted further. With no coordinates the location features simply
    don't appear.
    """

    lat: float | None = None
    lon: float | None = None
    tz: int | None = None            # minutes east of UTC
    method: str = prayer.DEFAULT_METHOD
    asr: str = "standard"

    def coords(self) -> tuple[float, float] | None:
        if self.lat is None or self.lon is None:
            return None
        if not (-90.0 <= self.lat <= 90.0 and -180.0 <= self.lon <= 180.0):
            return None
        return self.lat, self.lon

    def offset_hours(self) -> float:
        # -12:00 to +14:00 covers every real zone; anything else is junk.
        if self.tz is None or not (-720 <= self.tz <= 840):
            return 0.0
        return self.tz / 60.0

    def local_now(self) -> datetime:
        return datetime.utcnow() + timedelta(hours=self.offset_hours())

    def prayer_data(self) -> dict | None:
        coords = self.coords()
        if coords is None:
            return None
        method = self.method if self.method in prayer.METHODS else prayer.DEFAULT_METHOD
        asr = self.asr if self.asr in prayer.ASR_FACTORS else "standard"
        try:
            return prayer.summary(coords[0], coords[1], self.offset_hours(),
                                  method, asr, self.local_now())
        except Exception:
            # A location the astronomy can't resolve must never cost someone
            # their answer — the conversation goes on without it.
            return None

    def context_for(self, bot: Bot) -> str:
        """The situational note for this bot, or "" when it has no use for
        one. Only bots with the prayer feature get times and qibla."""
        if not bot.has("prayer"):
            return ""
        data = self.prayer_data()
        return prayer.context(data, self.local_now()) if data else ""


class ChatIn(Place):
    message: str = ""
    image: str | None = None  # data URL (image/*)
    lang: str = "en"


class MemoryIn(Place):
    # The visitor's whole memory record, kept in their own browser. `facts`
    # are weighted records; bare strings are accepted so memory written by an
    # older build still loads.
    facts: list[dict | str] = []
    threads: list[str] = []
    extras: list[str] = []
    met: str = ""
    last: str = ""
    chats: int = 0
    flavour: str = ""
    flavour_day: str = ""
    lang: str = "en"
    hour: int | None = None   # visitor's local hour, for the greeting

    def memory(self, bot: Bot) -> dict:
        return persona.clean_memory(bot, {
            "facts": self.facts, "threads": self.threads, "extras": self.extras,
            "met": self.met, "last": self.last, "chats": self.chats,
            "flavour": self.flavour, "flavour_day": self.flavour_day,
        })


class TTSIn(BaseModel):
    text: str
    edge: bool = False  # true = don't spend Gemini quota on this (greetings)


def clean_hour(hour: int | None) -> int | None:
    return hour if isinstance(hour, int) and 0 <= hour <= 23 else None


def decode_image(data_url: str) -> tuple[bytes, str] | None:
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


# --- pages ------------------------------------------------------------------

def render(path: Path, **swaps: str) -> str:
    html = path.read_text(encoding="utf-8")
    for key, value in swaps.items():
        html = html.replace("{{%s}}" % key, value)
    return html


@app.get("/")
def landing() -> Response:
    """The platform's front door: every bot, in registry order."""
    cards = "\n".join(
        f'''      <a class="bot" href="/{b.slug}" style="--accent:{b.palette['dark']['accent']};--accent-rgb:{b.palette['dark']['accentRgb']}">
        <span class="mark">{b.avatar_svg}</span>
        <span class="meta"><b>{b.name}</b><span>{b.tagline}</span></span>
      </a>''' for b in bots.all_bots())
    return Response(render(STATIC / "landing.html", site=SITE, cards=cards),
                    media_type="text/html")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    # served from the root so its scope can cover every bot
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/privacy")
def privacy() -> FileResponse:
    return FileResponse(STATIC / "privacy.html", media_type="text/html")


@app.get("/{slug}")
def bot_page(slug: str, sid: str | None = Cookie(None)) -> Response:
    bot = bot_or_404(slug)
    session_id, _ = engine.get_session(sid, bot)
    html = render(STATIC / "app.html",
                  site=SITE,
                  title=f"{bot.name} {bot.emoji}",
                  manifest=json.dumps(bot.manifest(), ensure_ascii=False),
                  theme_color=bot.palette["dark"]["bg1"])
    r = Response(html, media_type="text/html")
    # One session id across the platform; conversations are keyed by
    # (id, bot), so talking to one bot never disturbs another.
    r.set_cookie("sid", session_id, max_age=14400, httponly=True, samesite="lax")
    return r


@app.get("/{slug}/manifest.webmanifest")
def web_manifest(slug: str) -> Response:
    """Each bot installs as its own app, with its own name and icons."""
    bot = bot_or_404(slug)
    return Response(json.dumps({
        "name": f"{bot.name} — {SITE}",
        "short_name": bot.name,
        "description": bot.tagline,
        "start_url": f"/{bot.slug}",
        "scope": f"/{bot.slug}",
        "display": "standalone",
        "background_color": bot.palette["dark"]["bg0"],
        "theme_color": bot.palette["dark"]["bg1"],
        "icons": [
            {"src": f"/static/icons/{bot.slug}-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": f"/static/icons/{bot.slug}-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }, ensure_ascii=False), media_type="application/manifest+json")


# --- api --------------------------------------------------------------------

@app.post("/api/{slug}/hello")
def hello(slug: str, body: MemoryIn, sid: str | None = Cookie(None)) -> dict:
    """Personalize a fresh session with the memory this browser is holding and
    return the matching greeting. An ongoing conversation is never rebuilt —
    the page restores that through /history."""
    bot = bot_or_404(slug)
    _, sess = engine.get_session(sid, bot)
    analytics.record("visit", sid, bot=bot.slug, lang=body.lang, chats=body.chats,
                     met=body.met[:10], last=body.last[:10])
    mem = persona.touch_memory(bot, body.memory(bot))
    with sess.lock:
        if not sess.transcript():
            sess.rebuild(mem, body.context_for(bot))
    return {
        "text": persona.greeting(bot, sess.mem, body.lang, clean_hour(body.hour)),
        "memory": sess.mem,
    }


@app.get("/api/{slug}/history")
def history(slug: str, sid: str | None = Cookie(None)) -> dict:
    """The conversation so far, so a refresh doesn't look like a loss."""
    bot = bot_or_404(slug)
    _, sess = engine.get_session(sid, bot)
    messages: list[dict] = []
    with sess.lock:
        for content in sess.chat.get_history():
            text = "".join(p.text for p in content.parts or [] if p.text)
            if any(p.inline_data for p in content.parts or []):
                text = ("📷 " + text).strip() if text else "📷 (photo)"
            if not text:
                continue
            who = "user" if content.role == "user" else "bot"
            # streamed replies are recorded chunk by chunk — merge them back
            if messages and messages[-1]["who"] == who:
                messages[-1]["text"] += text
            else:
                messages.append({"who": who, "text": text})
    return {"messages": messages}


@app.post("/api/{slug}/chat")
def chat(slug: str, body: ChatIn, sid: str | None = Cookie(None)) -> StreamingResponse:
    bot = bot_or_404(slug)
    _, sess = engine.get_session(sid, bot)

    parts: list = []
    if body.image and bot.has("photos"):
        img = decode_image(body.image)
        if img:
            parts.append(types.Part.from_bytes(data=img[0], mime_type=img[1]))
    text = body.message.strip()
    if text:
        parts.append(text)
    if not parts:
        return StreamingResponse(iter([]), media_type="text/plain; charset=utf-8")

    limited = engine.take_quota(sess, body.lang)
    # lengths and flags only — message content is never logged
    analytics.record("message", sid, bot=bot.slug, len=len(text),
                     image=bool(body.image), lang=body.lang,
                     limited=("day" if limited and not limited[1] else
                              "rate" if limited else None))
    if limited:
        message, wait = limited
        return StreamingResponse(
            iter([message]),
            media_type="text/plain; charset=utf-8",
            headers={"x-ratelimited": str(wait)},
        )

    # Recomputed per message rather than per session: "how long until
    # Maghrib?" has to be answered from the clock now, not from whenever the
    # page was opened.
    context = body.context_for(bot)
    return StreamingResponse(engine.stream_reply(sess, parts, text, context),
                             media_type="text/plain; charset=utf-8")


@app.post("/api/{slug}/memorize")
def memorize(slug: str, body: MemoryIn, sid: str | None = Cookie(None)) -> dict:
    """Distill the conversation so far into updated facts for the browser to
    keep. Counts against the daily cap only."""
    bot = bot_or_404(slug)
    _, sess = engine.get_session(sid, bot)
    mem = body.memory(bot)
    if engine.take_quota(sess, per_minute=False):
        return {"memory": mem}
    with sess.lock:
        mem = engine.distill(sess, mem)
    return {"memory": mem}


@app.post("/api/{slug}/reset")
def reset(slug: str, body: MemoryIn | None = None,
          sid: str | None = Cookie(None)) -> dict:
    """Start a new conversation, personalized with whatever the browser sends
    (nothing = a first meeting)."""
    bot = bot_or_404(slug)
    _, sess = engine.get_session(sid, bot)
    analytics.record("reset", sid, bot=bot.slug)
    mem = body.memory(bot) if body else persona.blank_memory()
    lang = body.lang if body else "en"
    hour = clean_hour(body.hour) if body else None
    with sess.lock:
        sess.rebuild(mem, body.context_for(bot) if body else "")
    return {"text": persona.greeting(bot, mem, lang, hour), "memory": mem}


@app.post("/api/{slug}/transcribe")
async def transcribe(slug: str, request: Request, lang: str = "en",
                     sid: str | None = Cookie(None)) -> dict:
    bot = feature_or_404(bot_or_404(slug), "voice")
    _, sess = engine.get_session(sid, bot)
    limited = engine.take_quota(sess, lang)
    analytics.record("transcribe", sid, bot=bot.slug, limited=bool(limited))
    if limited:
        return {"text": None, "error": limited[0]}
    wav = await request.body()
    if len(wav) < 4000:  # far too short to hold speech
        return {"text": None}
    text = await run_in_threadpool(speech.transcribe_wav, sess.client, wav,
                                   engine.thinking())
    return {"text": text}


@app.post("/api/{slug}/say")
async def say(slug: str, body: TTSIn, sid: str | None = Cookie(None)) -> Response:
    """Speak in this bot's Gemini voice while the free tier allows, falling
    back to its Edge neural voice. The browser sends a whole reply as one
    request, so each reply costs one TTS call; greetings pass edge=true to
    skip Gemini entirely."""
    bot = feature_or_404(bot_or_404(slug), "voice")
    _, sess = engine.get_session(sid, bot)
    text = speech.clean_for_speech(bot, body.text)
    if not text:
        return Response(status_code=204)
    analytics.record("say", sid, bot=bot.slug, edge=body.edge)

    if not body.edge and speech.gemini_tts_available():
        try:
            wav = await run_in_threadpool(speech.synthesize, bot, sess.client, text)
            if wav:
                return Response(wav, media_type="audio/wav")
        except speech.VoiceQuotaError:
            speech.note_tts_quota_hit()
    try:
        stream = edge_tts.Communicate(text, voice=bot.edge_voice,
                                      rate=bot.speech_rate).stream()
        first = None
        async for msg in stream:
            if msg["type"] == "audio" and msg["data"]:
                first = msg["data"]
                break
        if first is None:
            return Response(status_code=503)

        async def mp3():
            yield first
            try:
                async for msg in stream:
                    if msg["type"] == "audio" and msg["data"]:
                        yield msg["data"]
            except Exception:
                pass

        return StreamingResponse(mp3(), media_type="audio/mpeg")
    except Exception:
        return Response(status_code=503)


@app.post("/api/{slug}/prayer")
def prayer_times(slug: str, body: Place) -> dict:
    """Today's timetable, qibla and Hijri date. Pure arithmetic — no model
    call, so it costs no quota and is never rate limited. 422 rather than a
    guess when the coordinates are missing or impossible: a wrong prayer time
    is worse than none."""
    feature_or_404(bot_or_404(slug), "prayer")
    data = body.prayer_data()
    if data is None:
        raise HTTPException(status_code=422, detail="valid lat/lon required")
    return data


@app.get("/api/bots")
def bot_list() -> dict:
    """The registry, for anything that wants to enumerate the platform."""
    return {"bots": [{"slug": b.slug, "name": b.name, "tagline": b.tagline,
                      "emoji": b.emoji, "features": sorted(b.features)}
                     for b in bots.all_bots()]}


@app.get("/api/stats")
def usage_stats(token: str = "") -> dict:
    """Aggregate usage — counts only, nothing personal. Set
    PLATFORM_STATS_TOKEN to require ?token=."""
    if STATS_TOKEN and not secrets.compare_digest(token, STATS_TOKEN):
        raise HTTPException(status_code=403)
    return {**analytics.stats(), "sessions_live": engine.session_count()}
