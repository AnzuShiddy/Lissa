#!/usr/bin/env python3
"""Lissa web app — FastAPI backend wrapping the chatbot logic in lissa.py.

Run:  .venv/bin/uvicorn app:app --port 8000
Then open http://localhost:8000 in your browser.

Multi-user, stateless. Each visitor has an isolated session; no memory persists.
The browser handles the microphone and speaker; this server keeps the Gemini
API key private and reuses lissa.py for the persona, transcription and TTS.
"""

import secrets
import threading
import time
from pathlib import Path

import edge_tts
from fastapi import Cookie, FastAPI, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from google.genai import errors
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import lissa

STATIC_DIR = Path(__file__).parent / "static"

# Free neural voice for greetings and for when Gemini's TTS quota is spent.
EDGE_VOICE = "en-US-AvaMultilingualNeural"

# After a Gemini TTS quota 429, don't retry it for this long.
GEMINI_TTS_COOLDOWN = 30 * 60

app = FastAPI(title="Lissa")


class UserSession:
    """Isolated chat session for one user, no persistent memory."""

    def __init__(self) -> None:
        self.client = lissa.make_client()
        self.lock = threading.Lock()
        self.tts_retry_at = 0.0
        self.last_used = time.time()
        self.session = self.client.chats.create(
            model=lissa.MODEL, config=lissa.build_config([])  # no memory, fresh start
        )

    def touch(self) -> None:
        """Update last-used timestamp for cleanup."""
        self.last_used = time.time()


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


class ChatIn(BaseModel):
    message: str


class TTSIn(BaseModel):
    text: str
    edge: bool = False  # true = don't spend Gemini quota on this (greetings)


@app.get("/")
def index(sid: str | None = Cookie(None)) -> Response:
    session_id, _ = get_or_create_session(sid)
    html = (STATIC_DIR / "index.html").read_text()
    r = Response(html, media_type="text/html")
    r.set_cookie("sid", session_id, max_age=14400, httponly=True, samesite="lax")
    return r


@app.get("/api/greeting")
def greeting(sid: str | None = Cookie(None)) -> dict:
    _, sess = get_or_create_session(sid)
    return {"text": lissa.greeting([]), "returning": False}


@app.get("/api/history")
def history(sid: str | None = Cookie(None)) -> dict:
    """Return the conversation so far so a page refresh can restore it.
    Empty when the session is new (or expired server-side)."""
    _, sess = get_or_create_session(sid)
    messages = []
    with sess.lock:
        for content in sess.session.get_history():
            text = "".join(p.text for p in content.parts or [] if p.text)
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

    def gen():
        with sess.lock:
            try:
                for chunk in sess.session.send_message_stream(body.message):
                    if chunk.text:
                        yield chunk.text
            except errors.ClientError as e:
                if e.code == 429:
                    yield "\n\n(Free-tier rate limit hit — wait a few seconds and try again.)"
                else:
                    yield f"\n\n(API error {e.code}: {e.message})"
            except errors.APIError as e:
                yield f"\n\n(Gemini had a hiccup ({e.code}) — try again in a moment.)"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


@app.post("/api/transcribe")
async def transcribe(request: Request, sid: str | None = Cookie(None)) -> dict:
    _, sess = get_or_create_session(sid)
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
def reset(sid: str | None = Cookie(None)) -> dict:
    _, sess = get_or_create_session(sid)
    with sess.lock:
        sess.session = sess.client.chats.create(
            model=lissa.MODEL, config=lissa.build_config([])
        )
    return {"text": lissa.greeting([])}
