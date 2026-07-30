"""Voice, both directions — transcription in, synthesis out.

Gemini's TTS carries the persona (each bot picks a prebuilt voice and the
direction it's read in); Microsoft's Edge neural voices are the fallback when
the free TTS quota runs out, which on a shared key it eventually does.
"""

from __future__ import annotations

import io
import re
import threading
import time
import wave

from google.genai import errors, types

from core.persona import Bot

RECORD_RATE = 16000   # 16 kHz mono s16le in, plenty for speech
TTS_RATE = 24000      # what Gemini returns

TTS_MODEL = "gemini-3.1-flash-tts-preview"

TRANSCRIBE_PROMPT = (
    "Transcribe this voice recording word for word, in whatever language it "
    "is spoken. Phrases from another language may appear mid-sentence — "
    "transcribe them as spoken. Return only the transcribed words, nothing "
    "else. If there is no intelligible speech, return exactly: NO_SPEECH"
)

# After a TTS quota 429, don't retry Gemini for this long. The quota belongs
# to the one shared key rather than to a visitor, so the cooldown is global: a
# 429 from anyone means everyone falls back for a while. Per-session it would
# be useless — every other visitor would keep paying a failed round-trip
# before each fallback.
GEMINI_TTS_COOLDOWN = 30 * 60
_tts_lock = threading.Lock()
_tts_retry_at = 0.0


class VoiceQuotaError(Exception):
    """The free-tier TTS quota is spent."""


def gemini_tts_available() -> bool:
    with _tts_lock:
        return time.time() >= _tts_retry_at


def note_tts_quota_hit() -> None:
    global _tts_retry_at
    with _tts_lock:
        _tts_retry_at = time.time() + GEMINI_TTS_COOLDOWN


def clean_for_speech(bot: Bot, text: str) -> str:
    """Strip what a voice would read aloud as noise. Each bot names its own
    swaps: honorific ligatures render as a single glyph that TTS either skips
    or mangles, and they matter enough to spell out."""
    for glyph, spoken in bot.speech_swaps.items():
        text = text.replace(glyph, spoken)
    text = re.sub(r"[*_#`]", "", text)                        # markdown markers
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text)   # emoji
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)
    return buf.getvalue()


def transcribe_wav(client, wav_bytes: bytes, thinking=None) -> str | None:
    """Speech to text. None on failure or when nothing intelligible was said."""
    try:
        response = client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=[types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                      TRANSCRIBE_PROMPT],
            config=types.GenerateContentConfig(thinking_config=thinking),
        )
    except errors.APIError:
        return None
    text = (response.text or "").strip()
    return None if not text or "NO_SPEECH" in text else text


def transcribe_pcm(client, pcm: bytes, thinking=None) -> str | None:
    return transcribe_wav(client, _wav(pcm, RECORD_RATE), thinking)


def synthesize(bot: Bot, client, text: str) -> bytes | None:
    """Speak `text` in this bot's voice. WAV bytes, or None when there's
    nothing to say or a skippable error happened. Raises VoiceQuotaError when
    the free tier is spent, so the caller can stop trying for a while."""
    text = clean_for_speech(bot, text)
    if not text:
        return None
    try:
        response = client.models.generate_content(
            model=TTS_MODEL,
            contents=bot.tts_style + text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=bot.tts_voice))),
            ),
        )
        pcm = response.candidates[0].content.parts[0].inline_data.data
    except errors.ClientError as e:
        if e.code == 429:
            raise VoiceQuotaError from e
        return None  # other errors: skip this clip, keep the voice on
    except Exception:
        return None
    return _wav(pcm, TTS_RATE)
