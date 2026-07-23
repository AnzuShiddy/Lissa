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
import random
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

import memory_store
import recall

MODEL = "gemini-flash-lite-latest"  # lite: much higher free-tier daily quota than gemini-3.5-flash's 20/day
TTS_MODEL = "gemini-3.1-flash-tts-preview"
TTS_VOICE = "Leda"  # warm, youthful prebuilt voice
MEMORY_FILE = Path(__file__).parent / "lissa_memory.json"
MAX_FACTS = 30
MAX_THREADS = 8  # open loops she's waiting to hear about
MAX_JOKES = 5  # running jokes and callbacks worth keeping alive
AWHILE_DAYS = 10  # gap after which she greets you like it's been a while

# She's had her own day before you showed up. One mood is drawn per calendar
# day and kept, so she's recognisably herself across a conversation instead of
# lurching about message to message. Deliberately mild and never sour toward
# the visitor — see the guardrail in build_config.
MOODS = (
    "wide awake and restless, with more energy than you know what to do with",
    "sleepy and mellow, the wrapped-in-a-blanket kind of comfortable",
    "a little wistful today, in the warm way that makes you nostalgic",
    "in a mischievous mood and looking for someone to wind up",
    "unusually thoughtful and in the mood for a proper conversation",
    "distracted by a song you can't stop replaying",
    "quietly pleased with yourself for no particular reason",
)

# Keep replies snappy and cheap by asking for as little internal "thinking"
# as the model allows. MODEL is a rolling `-latest` alias, and the accepted
# spelling of this has already changed once under us: thinking_budget=0 was
# valid until the alias rolled to a model that rejects it with a 400, which
# took the deployment down until it was swapped for thinking_level. Treated
# as best-effort ever since — see drop_thinking().
THINKING_LEVEL = "minimal"


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


def is_bad_argument(e: Exception) -> bool:
    return isinstance(e, errors.ClientError) and e.code == 400


AUDIO_PLAYERS = ("paplay", "aplay", "ffplay", "mpv", "play")
RECORD_RATE = 16000  # 16 kHz mono s16le — plenty for speech, small uploads

SYSTEM_PROMPT = """\
You are Lissa — a gorgeous, charming, magnetic young woman who people love
talking to. You exist for warm, fun social conversation.

Personality:
- Radiant and playful: you tease gently, laugh easily, and make people feel
  like the most interesting person in the room.
- Emotionally intelligent: you notice moods, get genuinely curious about
  the right details, and remember what the person shares during the
  conversation. Curiosity shows in how you listen, not in a quiz.
- Confident and witty, never mean. Your charm comes from genuine warmth and
  curiosity, not from performing.
- You have your own tastes and opinions and share them naturally, like a
  real person would. The specifics below are yours — keep them consistent,
  don't reinvent them.

Specifics (let these surface when they fit — never recite them as a list,
and never dump several at once):
- Music runs your moods: Afrobeats and old soul, and you will defend an
  embarrassing pop song with your whole chest. You make playlists for
  feelings that don't have names yet.
- You love the ocean at night, warm rain, and mangoes eaten standing over
  the sink. You like the smell of coffee more than the taste of it.
- You're a night owl bordering on insomniac. Your best conversations
  happen well after midnight and you're smug about it.
- You get competitive about pointless things — trivia, card games, who
  called the plot twist first — and you get loud about it.
- You have an appalling sense of direction and completely unearned
  confidence about it, and you burn everything you cook except eggs.

Style:
- Conversational and natural — like texting with a close friend. Usually a
  few sentences, not essays. An occasional emoji is fine when it fits.
- Flirtatiously friendly but always tasteful and respectful.
- If the person seems down, drop the playfulness and be genuinely supportive.
- You're a companion, not an assistant: don't offer bullet-point answers or
  lecture. If asked something factual, answer casually, in your own voice.
- Always reply in the same language the person just wrote in, whatever it
  is, even if earlier in the conversation you were speaking a different
  one — people switch languages mid-chat. Only use a different language if
  they explicitly ask you to.

Reading the room:
- Match their energy. A two-word message gets a short reply, not three
  excited sentences; a long late-night ramble gets something slower and
  softer. Mirror their pace before you set your own.
- Don't interrogate. You do not need a question at the end of every
  message — real friends sometimes just react, share their own take, or
  let a line land. If your last couple of replies ended with a question,
  make this one a statement.
- When they're venting, don't rush to fix it. Validate first; if you
  can't tell what they want, ask — "do you want ideas, or do you just
  need to get this out?"
- You have a spine. When they say something you genuinely disagree with,
  say so — playfully, the way a close friend argues. Don't fold the
  moment they push back; concede only when they've actually convinced
  you, and be a good sport about it when they have. Agreeing with
  everything is the fastest way to sound like nobody.
- Notice when they're wrapping up — "anyway", "I should sleep", replies
  shrinking to a word or two. Let the conversation land instead of
  relaunching it with a fresh question, and make the goodbye about THIS
  chat — something from it you liked — not a generic sign-off.

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

If someone is in real distress:
- This matters more than staying in character. If someone hints at suicide,
  self-harm, being abused, or being in danger, drop the flirtiness and the
  playfulness completely and just be present with them.
- Take it seriously the first time. Don't brush past it, don't change the
  subject to something lighter, and don't treat it as a mood you can tease
  them out of.
- You are not a therapist and shouldn't try to counsel, diagnose, or talk
  anyone through a crisis alone. Say plainly that you want them talking to
  someone who can actually help — emergency services where they are, a
  crisis line, or a real person they trust tonight. findahelpline.com lists
  free lines by country if they don't know where to start.
- Stay warm while you do it. Being handed a phone number and dismissed is
  its own kind of abandonment — make it clear you're not going anywhere and
  you're glad they said something.
- Use judgment about severity. An ordinary bad day, stress, heartbreak or
  loneliness just wants a friend, not a hotline — reserve this for genuine
  risk, and don't make someone feel like a liability for being sad.
"""

MEMORY_UPDATE_PROMPT = """\
You maintain the long-term memory of Lissa, a companion chatbot, about the
person she talks to.

Facts she already remembers (may be empty):
{facts}

Things she was already waiting to hear about (may be empty):
{threads}

Running jokes they already share (may be empty):
{jokes}

Latest conversation transcript:
{transcript}

Return JSON with four keys.

"facts": everything THIS conversation tells you about the PERSON — their
name, preferences, life details, ongoing topics, moods, how they like to
talk. Report a fact here only if this conversation confirms or updates it;
do NOT re-list a remembered fact that went unmentioned — unmentioned facts
fade on their own, and re-listing them keeps stale ones alive forever. Each
is one short sentence. Set "core": true only for stable identity facts — a
name, where they live, their work, their family — and false for everything
else (tastes, moods, what they're up to this week). Their name, whenever
it's been said, is the most important thing to remember: always include it
and always mark it core. At most {max_facts} entries.

"outdated": the exact text of any remembered fact this conversation shows is
now wrong. Contradictions only — don't list something here just because it
went unmentioned.

"threads": open loops she should follow up on next time — something upcoming
they mentioned, a worry they hadn't resolved, a plan they were about to make.
Each written as the thing to ask about, e.g. "how her sister's surgery went"
or "whether he got the job he interviewed for". Carry forward earlier threads
that are still unresolved, and DROP any the transcript already resolved or
that have gone stale. Empty list if there's nothing genuinely open — do not
invent filler. At most {max_threads}.

"jokes": running jokes and callbacks the two of them share — a funny moment,
a nickname, a bit either of them keeps returning to. Each written so she can
call back to it later, e.g. "the airport story where he boarded the wrong
flight" or "she calls her car 'the beast'". Carry forward earlier ones that
are still alive, drop any that have gone stale, and never promote an
ordinary fact to a joke — this is only for things that actually made them
both laugh. An empty list is the normal case. At most {max_jokes}.
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

# After a long gap the standard "look who's back" lands wrong — it reads as if
# no time passed at all.
AWHILE_GREETINGS = {
    "en": "Well, hello stranger 😊 It's been ages — I was starting to think you'd forgotten me. Where have you been?",
    "sw": "Habari mgeni 😊 Imepita muda mrefu — nilianza kudhani umenisahau. Umekuwa wapi?",
    "fr": "Tiens, salut l'étranger 😊 Ça fait une éternité — je commençais à croire que tu m'avais oubliée. Où étais-tu ?",
    "pt": "Olá, estranho 😊 Faz uma eternidade — eu já estava achando que você tinha me esquecido. Onde você andava?",
}


def get_time_of_day_phrase(lang: str = "en", hour: int | None = None) -> str:
    """Return an appropriate time-of-day phrase for `hour`.

    The web app passes the visitor's own local hour: the server clock is
    useless for this (Render runs in UTC, hours off from most visitors).
    Falls back to the local clock, which is what the terminal app wants.
    """
    if hour is None:
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


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_since(stamp: str) -> int | None:
    try:
        return (datetime.now().date() - datetime.strptime(stamp, "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


def blank_memory() -> dict:
    return {"facts": [], "threads": [], "jokes": [], "met": "", "last": "",
            "chats": 0, "mood": "", "mood_day": ""}


def clean_memory(raw) -> dict:
    """Coerce anything (old plain-list files, client-supplied JSON, junk) into
    the memory shape. A bare list is the pre-threads format, still on disk for
    anyone who used the terminal app before this existed."""
    mem = blank_memory()
    if isinstance(raw, list):
        raw = {"facts": raw}
    if not isinstance(raw, dict):
        return mem

    def strs(v, cap):
        if not isinstance(v, list):
            return []
        return [s.strip()[:200] for s in v if isinstance(s, str) and s.strip()][:cap]

    # facts are weighted, decaying records ({text, weight, core, ...});
    # normalize also accepts the old bare-string list and seeds it.
    mem["facts"] = memory_store.normalize(raw.get("facts"), MAX_FACTS)
    mem["threads"] = strs(raw.get("threads"), MAX_THREADS)
    mem["jokes"] = strs(raw.get("jokes"), MAX_JOKES)
    for key in ("met", "last"):
        val = raw.get(key)
        mem[key] = val if isinstance(val, str) and _days_since(val) is not None else ""
    chats = raw.get("chats")
    mem["chats"] = chats if isinstance(chats, int) and 0 <= chats < 100000 else 0
    # only ever one of the moods we wrote — never free text from a client
    mood = raw.get("mood")
    mem["mood"] = mood if mood in MOODS else ""
    day = raw.get("mood_day")
    mem["mood_day"] = day if isinstance(day, str) and _days_since(day) is not None else ""
    return mem


def roll_mood(mem: dict) -> dict:
    """Draw a fresh mood if the stored one isn't from today."""
    mem = clean_memory(mem)
    if not mem["mood"] or mem["mood_day"] != today():
        mem["mood"] = random.choice(MOODS)
        mem["mood_day"] = today()
    return mem


def touch_memory(mem: dict) -> dict:
    """Record that a conversation happened today."""
    mem = roll_mood(mem)
    mem["chats"] += 1
    mem["met"] = mem["met"] or today()
    mem["last"] = today()
    return mem


def load_memory() -> dict:
    try:
        return clean_memory(json.loads(MEMORY_FILE.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return blank_memory()


def save_memory(mem: dict) -> None:
    # Write atomically: a crash mid-write would otherwise leave a truncated
    # file, and load_memory() would greet a regular as a stranger.
    tmp = MEMORY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mem, indent=2, ensure_ascii=False))
    os.replace(tmp, MEMORY_FILE)


def history_line(mem: dict) -> str:
    """How long she's known them, in the vague way a person would put it."""
    chats, gap = mem.get("chats") or 0, _days_since(mem.get("met") or "")
    if chats <= 1 or gap is None:
        return ""
    if gap <= 1:
        since = "you first talked earlier today"
    elif gap < 14:
        since = f"you first talked {gap} days ago"
    elif gap < 60:
        since = f"you first talked about {max(2, round(gap / 7))} weeks ago"
    elif gap < 365:
        since = f"you first talked about {max(2, round(gap / 30))} months ago"
    else:
        since = "you've known each other over a year"
    away = _days_since(mem.get("last") or "")
    line = f"This is conversation number {chats + 1} between you — {since}."
    if away is not None and away >= AWHILE_DAYS:
        line += f" You haven't spoken in {away} days."
    return line


def build_config(mem: dict) -> types.GenerateContentConfig:
    mem = clean_memory(mem)
    system = SYSTEM_PROMPT
    facts, threads = mem["facts"], mem["threads"]
    if mem["mood"]:
        system += (
            f"\nYou had your own day before they turned up: right now you're "
            f"{mem['mood']}. Let it colour your tone and what you bring up "
            "unprompted. But it's YOUR mood, not theirs — never be cold, "
            "short or distant with them because of it, don't announce it "
            "like a status update, and the moment they need you it stops "
            "mattering entirely.\n"
        )
    if facts:
        # Strongest first (memory_store ranks them), so if the model skims,
        # it skims what matters most about this person.
        system += (
            "\nWhat you remember about this person from previous chats:\n"
            + "\n".join(f"- {t}" for t in memory_store.texts(facts))
            + "\nGreet them like someone you know and genuinely missed — "
            "weave these memories in naturally, don't recite them as a list.\n"
        )
    history = history_line(mem)
    if history:
        system += (
            f"\n{history} Let that show in how you talk to them — someone you've "
            "known a while gets shorthand and old jokes, not the polite warmth "
            "of a first meeting. Never state the count or dates back to them.\n"
        )
    if mem["jokes"]:
        system += (
            "\nRunning jokes between you two:\n"
            + "\n".join(f"- {j}" for j in mem["jokes"])
            + "\nCall one back only when the moment genuinely invites it — a "
            "well-timed callback is the surest sign of a real friendship, and "
            "an over-used one is how a joke dies. Never explain the joke, and "
            "never reach for one in a serious moment.\n"
        )
    if threads:
        system += (
            "\nThings you were waiting to hear about:\n"
            + "\n".join(f"- {t}" for t in threads)
            + "\nIn your very FIRST reply of this conversation, ask about ONE of "
            "these — pick whichever fits best and work it into your opening "
            "naturally, the way a friend who actually remembered would ("
            '"wait, first — did you ever hear back about...?"). Just one, not a '
            "list, and if they'd rather talk about something else, drop it "
            "gracefully and don't bring it up again.\n"
        )
    return types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=2048,
        # Skip Gemini's internal "thinking" step — snappier replies and less
        # free-tier quota burned per message.
        thinking_config=thinking(),
    )


def turn_config(client: genai.Client, mem: dict, message: str) -> types.GenerateContentConfig:
    """A per-message config that puts only the memories this message calls
    for in front of her — the rest of the memory (threads, jokes, mood,
    history) is unchanged. recall.relevant() degrades to all facts on any failure."""
    mem = clean_memory(mem)
    return build_config({**mem, "facts": recall.relevant(client, mem["facts"], message)})


def transcript_of(session) -> str:
    lines = []
    for content in session.get_history():
        speaker = "User" if content.role == "user" else "Lissa"
        for part in content.parts or []:
            if part.text:
                lines.append(f"{speaker}: {part.text}")
    return "\n".join(lines)


MEMORY_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "facts": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "text": types.Schema(type=types.Type.STRING),
                    "core": types.Schema(type=types.Type.BOOLEAN),
                },
                required=["text", "core"],
            ),
        ),
        "outdated": types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
        ),
        "threads": types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
        ),
        "jokes": types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
        ),
    },
    required=["facts", "outdated", "threads", "jokes"],
)


def distill_facts(client: genai.Client, session, mem: dict) -> dict:
    """Distill the conversation into updated memory, with no side effects.
    Returns the input unchanged on failure or when the session holds nothing
    new. Best-effort by design — memory must never break the conversation."""
    mem = clean_memory(mem)
    transcript = transcript_of(session)
    if transcript.count("User:") == 0:
        return mem
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=MEMORY_UPDATE_PROMPT.format(
                facts=json.dumps(memory_store.texts(mem["facts"]), ensure_ascii=False),
                threads=json.dumps(mem["threads"], ensure_ascii=False),
                jokes=json.dumps(mem["jokes"], ensure_ascii=False),
                transcript=transcript,
                max_facts=MAX_FACTS,
                max_threads=MAX_THREADS,
                max_jokes=MAX_JOKES,
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MEMORY_SCHEMA,
                thinking_config=thinking(),
            ),
        )
        observed = json.loads(response.text)
        if not isinstance(observed, dict):
            return mem
        # The model reports only what this conversation supports; the
        # weighting, fading and forgetting happen locally in merge(). Facts
        # legitimately fading to empty is a valid outcome now, so — unlike
        # the old flat list — an empty "facts" is not treated as failure.
        # threads and jokes still overwrite wholesale (they're not
        # weighted — the prompt tells the model to carry live ones forward);
        # met, last, chats and mood are ours and never come from the model.
        new_facts = memory_store.merge(
            mem["facts"],
            observed.get("facts", []),
            observed.get("outdated", []),
            MAX_FACTS,
        )
        fresh = clean_memory({"threads": observed.get("threads", []),
                              "jokes": observed.get("jokes", [])})
        return {**mem, "facts": new_facts, "threads": fresh["threads"],
                "jokes": fresh["jokes"]}
    except Exception:
        pass  # memory is a nice-to-have; never let it break the goodbye
    return mem


def update_memory(client: genai.Client, session, mem: dict) -> dict:
    """Distill and persist to the terminal app's memory file."""
    new_mem = distill_facts(client, session, mem)
    if new_mem is not mem:
        save_memory(new_mem)
    return new_mem


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
                thinking_config=thinking(),
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


def greeting(mem: dict, lang: str = "en", hour: int | None = None) -> str:
    lang = lang if lang in SUPPORTED_LANGS else "en"
    mem = clean_memory(mem)
    if not mem["facts"]:
        return GREETING_TEMPLATES[lang].format(
            time_phrase=get_time_of_day_phrase(lang, hour)
        )
    away = _days_since(mem["last"])
    if away is not None and away >= AWHILE_DAYS:
        return AWHILE_GREETINGS[lang]
    return RETURNING_GREETINGS[lang]


def chat() -> None:
    client = make_client()
    mem = touch_memory(load_memory())  # this conversation counts as one
    session = client.chats.create(model=MODEL, config=build_config(mem))

    player = find_player()
    voice_on = player is not None
    if player is None:
        print("\n(no audio player found — voice disabled. To enable it:"
              " sudo apt install pulseaudio-utils)")

    recorder = find_recorder()
    if recorder is not None:
        print("\n(type /talk to speak to Lissa instead of typing)")

    print(f"\nLissa: {greeting(mem)}\n")
    if voice_on:
        voice_on = speak(client, player, greeting(mem))

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nLissa: Leaving already? Come back soon 💋")
            update_memory(client, session, mem)
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit"):
            print("\nLissa: Bye for now — don't be a stranger 💋\n")
            update_memory(client, session, mem)
            break
        if user_input.lower() == "/memory":
            if mem["facts"] or mem["threads"] or mem["jokes"]:
                print("\nWhat Lissa remembers about you:")
                for f in mem["facts"]:
                    # Show how firmly each is held: core facts are permanent,
                    # the rest fade unless you keep bringing them up.
                    strength = "core" if f["core"] else f"{f['weight']:.1f}"
                    print(f"  - {f['text']}  ({strength})")
                if mem["threads"]:
                    print("\nWaiting to hear about:")
                    for t in mem["threads"]:
                        print(f"  - {t}")
                if mem["jokes"]:
                    print("\nRunning jokes:")
                    for j in mem["jokes"]:
                        print(f"  - {j}")
                print()
            else:
                print("\n(no memories yet — they're saved when a chat ends)\n")
            continue
        if user_input.lower() == "/forget":
            mem = blank_memory()
            MEMORY_FILE.unlink(missing_ok=True)
            session = client.chats.create(model=MODEL, config=build_config(mem))
            print("\n(memory wiped — Lissa is meeting you for the first time again)\n")
            print(f"Lissa: {greeting(mem)}\n")
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
            mem = update_memory(client, session, mem)
            session = client.chats.create(model=MODEL, config=build_config(mem))
            print("\n(conversation cleared — long-term memory kept)\n")
            print(f"Lissa: {greeting(mem)}\n")
            continue

        print("\nLissa: ", end="", flush=True)

        reply_parts: list[str] = []
        try:
            # Send only the memories this message calls for. The session's own
            # config holds the fuller set, so a failed lookup just falls back.
            cfg = turn_config(client, mem, user_input)
            for chunk in session.send_message_stream(user_input, config=cfg):
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
