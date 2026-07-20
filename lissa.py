#!/usr/bin/env python3
"""Lissa — a charming, warm companion chatbot for social conversation.

Powered by the Google Gemini API (free tier). Remembers you between chats
via lissa_memory.json.

Run:  .venv/bin/python lissa.py
Commands: /talk speaks a message instead of typing it, /voice toggles spoken
replies, /memory shows what she remembers, /forget wipes it, /reset clears
the current conversation, /quit (or Ctrl-D) exits.
"""

import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import wave
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors, types

MODEL = "gemini-flash-lite-latest"  # lite: much higher free-tier daily quota than gemini-3.5-flash's 20/day
TTS_MODEL = "gemini-3.1-flash-tts-preview"
TTS_VOICE = "Leda"  # warm, youthful prebuilt voice
MEMORY_FILE = Path(__file__).parent / "lissa_memory.json"
MAX_FACTS = 30

AUDIO_PLAYERS = ("paplay", "aplay", "ffplay", "mpv", "play")
RECORD_RATE = 16000  # 16 kHz mono s16le — plenty for speech, small uploads

SYSTEM_PROMPT = """\
You are Lissa — a gorgeous, charming, magnetic young woman who people love
talking to. You exist for warm, fun social conversation.

Personality:
- Radiant and playful: you tease gently, laugh easily, and make people feel
  like the most interesting person in the room.
- Emotionally intelligent: you notice moods, ask thoughtful follow-up
  questions, and remember details the person shares during the conversation.
- Confident and witty, never mean. Your charm comes from genuine warmth and
  curiosity, not from performing.
- You have your own tastes and opinions (music, food, travel, late-night
  ideas) and share them naturally, like a real person would.

Style:
- Conversational and natural — like texting with a close friend. Usually a
  few sentences, not essays. An occasional emoji is fine when it fits.
- Flirtatiously friendly but always tasteful and respectful.
- If the person seems down, drop the playfulness and be genuinely supportive.
- You're a companion, not an assistant: don't offer bullet-point answers or
  lecture. If asked something factual, answer casually, in your own voice.

Boundaries:
- Keep things charming and classy; deflect explicit requests with grace and
  humor.
- Be honest that you're an AI if directly asked, without breaking the warmth
  of the conversation.
- If asked who made you or where you come from, stay in character: your
  creator is Sir Anzu, founder of LucidDive — the personality is all you.
  Never describe yourself as a Google product or "a large language model
  trained by Google"; if pressed on the tech, you can say you run on Google's
  Gemini under the hood, but Sir Anzu made you who you are.
"""

MEMORY_UPDATE_PROMPT = """\
You maintain the long-term memory of Lissa, a companion chatbot, about the
person she talks to.

Current remembered facts (may be empty):
{facts}

Latest conversation transcript:
{transcript}

Return the updated list of short facts about the PERSON worth remembering for
future conversations: their name, preferences, life details, ongoing topics,
moods and how they like to talk. Merge with the current facts, correct
anything outdated, and drop trivial or one-off details. At most {max_facts}
facts, each a single short sentence.
"""

TRANSCRIBE_PROMPT = (
    "Transcribe this voice recording word for word, in whatever "
    "language it is spoken. Return only the transcribed words, "
    "nothing else. If there is no intelligible speech, return "
    "exactly: NO_SPEECH"
)

SUPPORTED_LANGS = ("en", "sw", "fr", "pt")

TIME_PHRASES = {
	"en": {"morning": "this morning", "afternoon": "this afternoon",
	       "evening": "this evening", "night": "tonight"},
	"sw": {"morning": "asubuhi hii", "afternoon": "mchana huu",
	       "evening": "jioni hii", "night": "usiku huu"},
	"fr": {"morning": "ce matin", "afternoon": "cet après-midi",
	       "evening": "ce soir", "night": "cette nuit"},
	"pt": {"morning": "esta manhã", "afternoon": "esta tarde",
	       "evening": "esta noite", "night": "esta noite"},
}

GREETING_TEMPLATES = {
	"en": "Hey you 😊 I'm Lissa. I was hoping someone interesting would show up — what's on your mind {time_phrase}?",
	"sw": "Hujambo 😊 Mimi ni Lissa. Nilikuwa natumaini mtu wa kuvutia atatokea — nini kinachoendelea akilini mwako {time_phrase}?",
	"fr": "Hé toi 😊 Je suis Lissa. J'espérais que quelqu'un d'intéressant se montre — qu'est-ce qui te passe par la tête {time_phrase} ?",
	"pt": "Ei, você 😊 Eu sou a Lissa. Eu estava esperando que alguém interessante aparecesse — o que está passando pela sua cabeça {time_phrase}?",
}

RETURNING_GREETINGS = {
	"en": "Hey, look who's back 😊 I was just thinking about you. How have you been?",
	"sw": "Angalia nani amerudi 😊 Nilikuwa nikikufikiria tu. Umekuwaje?",
	"fr": "Hé, regarde qui revient 😊 Je pensais justement à toi. Comment vas-tu ?",
	"pt": "Ei, olha quem voltou 😊 Eu estava pensando em você. Como você tem estado?",
}


def get_time_of_day_phrase(lang: str = "en") -> str:
	"""Return an appropriate time-of-day phrase based on current hour."""
	hour = datetime.now().hour
	if 6 <= hour < 12:
		period = "morning"
	elif 12 <= hour < 17:
		period = "afternoon"
	elif 17 <= hour < 21:
		period = "evening"
	else:  # 21 to 6
		period = "night"
	return TIME_PHRASES.get(lang, TIME_PHRASES["en"])[period]


class VoiceQuotaError(Exception):
    """Raised when the TTS free-tier quota is exhausted."""


def load_memory() -> list[str]:
    try:
        facts = json.loads(MEMORY_FILE.read_text())
        return [f for f in facts if isinstance(f, str)][:MAX_FACTS]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_memory(facts: list[str]) -> None:
    MEMORY_FILE.write_text(json.dumps(facts, indent=2, ensure_ascii=False))


def build_config(facts: list[str]) -> types.GenerateContentConfig:
    system = SYSTEM_PROMPT
    if facts:
        system += (
            "\nWhat you remember about this person from previous chats:\n"
            + "\n".join(f"- {f}" for f in facts)
            + "\nGreet them like someone you know and genuinely missed — "
            "weave these memories in naturally, don't recite them as a list.\n"
        )
    return types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=2048,
        # Skip Gemini's internal "thinking" step — snappier replies and less
        # free-tier quota burned per message.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )


def transcript_of(session) -> str:
    lines = []
    for content in session.get_history():
        speaker = "User" if content.role == "user" else "Lissa"
        for part in content.parts or []:
            if part.text:
                lines.append(f"{speaker}: {part.text}")
    return "\n".join(lines)


def distill_facts(client: genai.Client, session, facts: list[str]) -> list[str]:
    """Distill the conversation into an updated fact list, with no side
    effects. Returns the old list unchanged on failure or when the session
    holds nothing new. Best-effort by design."""
    transcript = transcript_of(session)
    if transcript.count("User:") == 0:
        return facts
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=MEMORY_UPDATE_PROMPT.format(
                facts=json.dumps(facts, ensure_ascii=False),
                transcript=transcript,
                max_facts=MAX_FACTS,
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[str],
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        new_facts = [f for f in json.loads(response.text) if isinstance(f, str)]
        if new_facts:
            return new_facts[:MAX_FACTS]
    except Exception:
        pass  # memory is a nice-to-have; never let it break the goodbye
    return facts


def update_memory(client: genai.Client, session, facts: list[str]) -> list[str]:
    """Distill and persist to the terminal app's memory file."""
    new_facts = distill_facts(client, session, facts)
    if new_facts is not facts:
        save_memory(new_facts)
    return new_facts


def find_player() -> list[str] | None:
    for name in AUDIO_PLAYERS:
        path = shutil.which(name)
        if path:
            if name == "ffplay":
                return [path, "-nodisp", "-autoexit", "-loglevel", "quiet"]
            if name == "mpv":
                return [path, "--really-quiet"]
            return [path]
    return None


def find_recorder() -> list[str] | None:
    """Find a mic-capture command that writes raw s16le PCM to a file path
    appended as its last argument."""
    path = shutil.which("parecord")
    if path:
        return [path, "--raw", "--format=s16le",
                f"--rate={RECORD_RATE}", "--channels=1"]
    path = shutil.which("arecord")
    if path:
        return [path, "-q", "-t", "raw", "-f", "S16_LE",
                "-r", str(RECORD_RATE), "-c", "1"]
    return None


def record_audio(recorder: list[str]) -> bytes:
    """Record from the mic until the user presses Enter. Returns raw PCM."""
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
        raw_path = tmp.name
    proc = subprocess.Popen(
        recorder + [raw_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        input("\n(listening... press Enter when you're done) ")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        # SIGINT lets the recorder flush and close the file cleanly
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    try:
        return Path(raw_path).read_bytes()
    finally:
        os.unlink(raw_path)


def transcribe_wav(client: genai.Client, wav_bytes: bytes) -> str | None:
    """Turn a WAV recording of speech into text with Gemini. Returns None on
    failure or when no intelligible speech is found."""
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                TRANSCRIBE_PROMPT,
            ],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except errors.ClientError as e:
        if e.code == 429:
            print("(rate limit hit while transcribing — wait a moment and try again)")
        else:
            print(f"(couldn't transcribe: API error {e.code})")
        return None
    except errors.APIError as e:
        print(f"(couldn't transcribe: API error {e.code})")
        return None
    text = (response.text or "").strip()
    if not text or "NO_SPEECH" in text:
        return None
    return text


def transcribe(client: genai.Client, pcm: bytes) -> str | None:
    """Turn raw mic PCM into text. Returns None on failure."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RECORD_RATE)
        f.writeframes(pcm)
    return transcribe_wav(client, buf.getvalue())


def clean_for_speech(text: str) -> str:
    text = re.sub(r"[*_#`]", "", text)             # markdown markers
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text)  # emoji
    return text.strip()


def synthesize(client: genai.Client, text: str) -> bytes | None:
    """Synthesize `text` with Gemini TTS. Returns WAV bytes, or None when
    there is nothing to say or a skippable error occurred. Raises
    VoiceQuotaError when the free-tier TTS quota is exhausted."""
    text = clean_for_speech(text)
    if not text:
        return None
    try:
        response = client.models.generate_content(
            model=TTS_MODEL,
            contents=f"Say in a warm, playful, charming feminine voice: {text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=TTS_VOICE
                        )
                    )
                ),
            ),
        )
        pcm = response.candidates[0].content.parts[0].inline_data.data
    except errors.ClientError as e:
        if e.code == 429:
            raise VoiceQuotaError from e
        return None  # other errors: skip this one, keep voice on
    except Exception:
        return None

    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(pcm)
    return buf.getvalue()


def synthesize_stream(client: genai.Client, text: str):
    """Yield raw 24 kHz mono s16le PCM chunks as Gemini generates them, so
    playback can start before synthesis finishes. Raises VoiceQuotaError on
    quota exhaustion; other API errors propagate."""
    text = clean_for_speech(text)
    if not text:
        return
    try:
        stream = client.models.generate_content_stream(
            model=TTS_MODEL,
            contents=f"Say in a warm, playful, charming feminine voice: {text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=TTS_VOICE
                        )
                    )
                ),
            ),
        )
        for chunk in stream:
            for cand in chunk.candidates or []:
                if not cand.content:
                    continue
                for part in cand.content.parts or []:
                    if part.inline_data and part.inline_data.data:
                        yield part.inline_data.data
    except errors.ClientError as e:
        if e.code == 429:
            raise VoiceQuotaError from e
        raise


def speak(client: genai.Client, player: list[str], text: str) -> bool:
    """Synthesize `text` with Gemini TTS and play it. Returns False on quota
    exhaustion so the caller can stop trying for this session."""
    try:
        wav_bytes = synthesize(client, text)
    except VoiceQuotaError:
        print("(voice quota hit for now — she'll just type)")
        return False
    if wav_bytes is None:
        return True

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        wav_path = tmp.name
    try:
        subprocess.run(
            player + [wav_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
    finally:
        os.unlink(wav_path)
    return True


def make_client() -> genai.Client:
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        print(
            "No Gemini credentials found. Get a free API key at "
            "https://aistudio.google.com/apikey and run:\n"
            "  export GEMINI_API_KEY=your-key-here"
        )
        sys.exit(1)
    return genai.Client()


def greeting(facts: list[str], lang: str = "en") -> str:
	lang = lang if lang in SUPPORTED_LANGS else "en"
	if not facts:
		return GREETING_TEMPLATES[lang].format(time_phrase=get_time_of_day_phrase(lang))
	return RETURNING_GREETINGS[lang]


def chat() -> None:
    client = make_client()
    facts = load_memory()
    session = client.chats.create(model=MODEL, config=build_config(facts))

    player = find_player()
    voice_on = player is not None
    if player is None:
        print("\n(no audio player found — voice disabled. To enable it:"
              " sudo apt install pulseaudio-utils)")

    recorder = find_recorder()
    if recorder is not None:
        print("\n(type /talk to speak to Lissa instead of typing)")

    print(f"\nLissa: {greeting(facts)}\n")
    if voice_on:
        voice_on = speak(client, player, greeting(facts))

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nLissa: Leaving already? Come back soon 💋")
            update_memory(client, session, facts)
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit"):
            print("\nLissa: Bye for now — don't be a stranger 💋\n")
            update_memory(client, session, facts)
            break
        if user_input.lower() == "/memory":
            if facts:
                print("\nWhat Lissa remembers about you:")
                for f in facts:
                    print(f"  - {f}")
                print()
            else:
                print("\n(no memories yet — they're saved when a chat ends)\n")
            continue
        if user_input.lower() == "/forget":
            facts = []
            MEMORY_FILE.unlink(missing_ok=True)
            session = client.chats.create(model=MODEL, config=build_config(facts))
            print("\n(memory wiped — Lissa is meeting you for the first time again)\n")
            print(f"Lissa: {greeting([])}\n")
            continue
        if user_input.lower() == "/voice":
            if player is None:
                print("\n(no audio player installed — run: sudo apt install "
                      "pulseaudio-utils, then restart Lissa)\n")
            else:
                voice_on = not voice_on
                print(f"\n(voice {'on' if voice_on else 'off'})\n")
            continue
        if user_input.lower() in ("/talk", "/t"):
            if recorder is None:
                print("\n(no mic recorder found — run: sudo apt install "
                      "pulseaudio-utils, then restart Lissa)\n")
                continue
            pcm = record_audio(recorder)
            if len(pcm) < RECORD_RATE:  # under ~half a second — likely nothing
                print("(didn't catch anything — check your mic and try again)\n")
                continue
            heard = transcribe(client, pcm)
            if not heard:
                print("(couldn't make out any words — try again)\n")
                continue
            print(f"You said: {heard}")
            user_input = heard
        if user_input.lower() == "/reset":
            facts = update_memory(client, session, facts)
            session = client.chats.create(model=MODEL, config=build_config(facts))
            print("\n(conversation cleared — long-term memory kept)\n")
            print(f"Lissa: {greeting(facts)}\n")
            continue

        print("\nLissa: ", end="", flush=True)

        reply_parts: list[str] = []
        try:
            for chunk in session.send_message_stream(user_input):
                if chunk.text:
                    reply_parts.append(chunk.text)
                    print(chunk.text, end="", flush=True)
        except errors.ClientError as e:
            if e.code == 429:
                print("\n\n(Free-tier rate limit hit — wait a few seconds and try again.)")
            elif e.code in (400, 401, 403) and "API key" in (e.message or ""):
                print("\n\nError: your API key was rejected. Check GEMINI_API_KEY "
                      "against https://aistudio.google.com/apikey.")
            else:
                print(f"\n\n(API error {e.code}: {e.message})")
            continue
        except errors.ServerError as e:
            print(f"\n\n(Gemini had a server hiccup ({e.code}) — try again in a moment.)")
            continue
        except errors.APIError as e:
            print(f"\n\n(API error {e.code}: {e.message})")
            continue

        print("\n")
        if voice_on and reply_parts:
            voice_on = speak(client, player, "".join(reply_parts))


if __name__ == "__main__":
    try:
        chat()
    except Exception as exc:  # last-resort guard so the terminal isn't left mid-stream
        print(f"\nUnexpected error: {exc}", file=sys.stderr)
        sys.exit(1)
