"""The runtime every bot shares: model config, sessions, quota, streaming.

Nothing here knows which bot it is serving; it takes one as an argument. The
Gemini specifics — the model alias, the thinking setting, the error handling
that keeps a rolling alias from taking the deployment down — live here once.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import sys
import threading
import time

try:
    from google import genai
    from google.genai import errors, types
except ImportError:  # pragma: no cover - depends on the environment
    # The unit job runs on the standard library alone — that is what makes it
    # the gate that protects the branch, since it needs no key and no network.
    # core.recall defers its import for the same reason and says so. Every use
    # of these three is downstream of a live client, which cannot exist without
    # the SDK, so a None here is unreachable rather than merely unlikely.
    genai = errors = types = None

from core import persona
from core.persona import Bot

log = logging.getLogger("luciddive.engine")

MODEL = "gemini-flash-lite-latest"  # lite: much higher free-tier daily quota

# Keep replies snappy and cheap by asking for as little internal "thinking" as
# the model allows. MODEL is a rolling `-latest` alias and the accepted
# spelling of this has already changed once under us: thinking_budget=0 was
# valid until the alias rolled to a model that rejects it with a 400, which
# took the deployment down until it was swapped for thinking_level. Best
# effort ever since — see drop_thinking().
THINKING_LEVEL = "minimal"

SESSION_TTL = 4 * 3600  # a conversation outlives a coffee break, not a day

# A ceiling as well as an age limit. Eviction used to be by TTL alone, which
# bounds how *long* a conversation is held but not how many are held at once:
# inside any four-hour window the store grew one entry per (visitor, bot) with
# nothing to stop it, and each entry holds a full chat history. On a free
# instance that is the memory limit, reached by ordinary traffic rather than
# by anyone attacking it.
MAX_SESSIONS = int(os.environ.get("PLATFORM_MAX_SESSIONS", "400"))

# The public deployment serves every bot from one shared API key, so throttle
# quota-burning calls: a per-visitor token bucket plus a global daily cap.
RATE_PER_MIN = float(os.environ.get("PLATFORM_RATE_PER_MIN", "8"))
DAILY_CALLS = int(os.environ.get("PLATFORM_DAILY_CALLS", "600"))


def thinking() -> "types.ThinkingConfig | None":
    return types.ThinkingConfig(thinking_level=THINKING_LEVEL) if THINKING_LEVEL else None


def drop_thinking() -> bool:
    """Stop sending the thinking setting after the API has rejected it.
    Returns True the first time, so the caller knows a retry is worthwhile."""
    global THINKING_LEVEL
    if THINKING_LEVEL is None:
        return False
    THINKING_LEVEL = None
    return True


def make_client() -> genai.Client:
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        print("No Gemini credentials found. Get a free API key at "
              "https://aistudio.google.com/apikey and run:\n"
              "  export GEMINI_API_KEY=your-key-here")
        sys.exit(1)
    return genai.Client()


def config_for(bot: Bot, mem: dict, context: str = "") -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=persona.build_prompt(bot, mem, context),
        max_output_tokens=2048,
        thinking_config=thinking(),
    )


def turn_config(bot: Bot, client, mem: dict, message: str,
                context: str = "") -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=persona.turn_prompt(bot, client, mem, message, context),
        max_output_tokens=2048,
        thinking_config=thinking(),
    )


# --- quota ------------------------------------------------------------------

_daily_lock = threading.Lock()
_daily = {"day": "", "count": 0}


def take_quota(sess: "Session", lang: str = "en", per_minute: bool = True
               ) -> tuple[str, int] | None:
    """Spend one quota-burning call. None when allowed, otherwise the
    in-character message to show and the seconds to wait (0 = no countdown).

    Background work (memory distillation) passes per_minute=False so it counts
    against the daily cap only and never starves the visitor's own messages.
    The daily cap is global because the key is: one bot's busy day is every
    bot's busy day.
    """
    bot = sess.bot
    lang = bot.lang(lang)
    if per_minute:
        now = time.time()
        sess.tokens = min(RATE_PER_MIN,
                          sess.tokens + (now - sess.tokens_at) * (RATE_PER_MIN / 60.0))
        sess.tokens_at = now
        if sess.tokens < 1.0:
            wait = int((1.0 - sess.tokens) * 60.0 / RATE_PER_MIN) + 1
            return (persona.canned(bot.rate_limit_msg, lang, bot.langs[0], wait=wait), wait)
    with _daily_lock:
        today = time.strftime("%Y-%m-%d")
        if _daily["day"] != today:
            _daily["day"], _daily["count"] = today, 0
        if _daily["count"] >= DAILY_CALLS:
            return (persona.canned(bot.daily_cap_msg, lang, bot.langs[0]), 0)
        _daily["count"] += 1
    if per_minute:
        sess.tokens -= 1.0
    return None


# --- sessions ---------------------------------------------------------------

class Session:
    """One visitor's conversation with one bot. Nothing persists: memory
    lives in their browser and is sent up with each request."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.client = make_client()
        self.lock = threading.Lock()
        self.last_used = time.time()
        self.tokens = RATE_PER_MIN
        self.tokens_at = time.time()
        self.mem: dict = persona.blank_memory()
        # What a tutoring bot has established the student is working on, as
        # (subject, form). It belongs to the conversation rather than the
        # browser: it's settled by asking, and re-asking after a few hours
        # away is natural for a tutor in a way that re-asking for someone's
        # coordinates would not be. Bots without the syllabus feature never
        # touch it.
        self.study: tuple[str | None, str | None] = (None, None)
        self.chat = self.client.chats.create(
            model=MODEL, config=config_for(bot, self.mem))

    def touch(self) -> None:
        self.last_used = time.time()

    def rebuild(self, mem: dict, context: str = "") -> None:
        """Start a fresh conversation personalized with `mem`. Call with the
        session lock held."""
        self.mem = mem
        self.chat = self.client.chats.create(
            model=MODEL, config=config_for(self.bot, mem, context))

    def transcript(self) -> str:
        return persona.transcript_of(self.bot, self.chat)


# Keyed by (session id, bot slug): one visitor talking to two bots gets two
# independent conversations, which is the whole point of a platform.
_sessions: dict[tuple[str, str], Session] = {}
_sessions_lock = threading.Lock()


def evict(sessions: dict, now: float, ttl: float = SESSION_TTL,
          cap: int = MAX_SESSIONS) -> None:
    """Drop what's stale, then what's oldest if there are still too many.

    In place, and pure enough to test without an API key — building a real
    Session needs a client. Age goes first because a finished conversation is
    worth less than a live one; only if that leaves the store over the cap
    does least-recently-used come into it, which under real pressure means
    someone loses a conversation they were having. That is the honest trade
    against the process dying and everyone losing theirs.
    """
    for key, sess in list(sessions.items()):
        if now - sess.last_used > ttl:
            del sessions[key]
    if len(sessions) <= cap:
        return
    oldest = sorted(sessions.items(), key=lambda kv: kv[1].last_used)
    for key, _ in oldest[:len(sessions) - cap]:
        del sessions[key]


def get_session(sid: str | None, bot: Bot) -> tuple[str, Session]:
    with _sessions_lock:
        if sid and (sid, bot.slug) in _sessions:
            sess = _sessions[(sid, bot.slug)]
            sess.touch()
            return sid, sess
        sid = sid or secrets.token_urlsafe(16)
        sess = Session(bot)
        _sessions[(sid, bot.slug)] = sess
        # after the insert, so the session we just handed out is the newest
        # and cannot be the one evicted
        evict(_sessions, time.time())
        return sid, sess


def session_count() -> int:
    with _sessions_lock:
        return len(_sessions)


# --- talking ----------------------------------------------------------------

def stream_reply(sess: Session, parts: list, text: str, context: str = ""):
    """Yield reply chunks as they arrive.

    Generation runs in its own thread that always drains the stream. If the
    client disconnects mid-reply (stop button, closed tab), an abandoned
    generator would otherwise stay suspended inside `with sess.lock:` forever
    and deadlock every later message in that session.
    """
    q: queue.Queue[str | None] = queue.Queue()

    def produce() -> None:
        try:
            with sess.lock:
                try:
                    sent = False
                    cfg = turn_config(sess.bot, sess.client, sess.mem, text, context)
                    for chunk in sess.chat.send_message_stream(parts, config=cfg):
                        sent = True
                        if chunk.text:
                            q.put(chunk.text)
                except errors.ClientError as e:
                    # A 400 before any output usually means the request carried
                    # something this model no longer accepts. Drop the optional
                    # thinking setting and retry once, rather than serving an
                    # error to every visitor until someone notices.
                    if e.code == 400 and not sent and drop_thinking():
                        try:
                            sess.rebuild(sess.mem, context)
                            cfg = turn_config(sess.bot, sess.client, sess.mem, text, context)
                            for chunk in sess.chat.send_message_stream(parts, config=cfg):
                                if chunk.text:
                                    q.put(chunk.text)
                            return
                        except errors.APIError as retry_err:
                            e = retry_err
                    # Codes and bot slugs only — never the message. What is
                    # worth knowing from a log here is "the key is spent" or
                    # "the alias moved again", and neither needs the content.
                    if getattr(e, "code", None) == 429:
                        log.warning("chat rate-limited by the API (bot=%s)", sess.bot.slug)
                        q.put("\n\n(Free-tier rate limit hit — wait a few seconds and try again.)")
                    else:
                        log.error("chat client error %s (bot=%s)", e.code, sess.bot.slug)
                        q.put(f"\n\n(API error {e.code}: {e.message})")
                except errors.APIError as e:
                    log.error("chat api error %s (bot=%s)", e.code, sess.bot.slug)
                    q.put(f"\n\n(Gemini had a hiccup ({e.code}) — try again in a moment.)")
        finally:
            q.put(None)

    threading.Thread(target=produce, daemon=True).start()
    while (chunk := q.get()) is not None:
        yield chunk


def distill(sess: Session, mem: dict) -> dict:
    return distill_chat(sess.bot, sess.client, sess.chat, mem)


def distill_chat(bot: Bot, client, chat, mem: dict) -> dict:
    """Distill the conversation into updated memory. Returns the input
    unchanged on failure or when nothing has been said yet — memory is a
    nice-to-have and must never break a conversation."""
    mem = persona.clean_memory(bot, mem)
    transcript = persona.transcript_of(bot, chat)
    if transcript.count("User:") == 0:
        return mem
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=persona.distill_prompt(bot, mem, transcript),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=persona.memory_schema(types),
                thinking_config=thinking(),
            ),
        )
        observed = json.loads(response.text)
        if not isinstance(observed, dict):
            return mem
        return persona.fold_observations(bot, mem, observed, transcript)
    except Exception:
        pass
    return mem
