"""What a bot *is* — and the machinery every bot shares.

A `Bot` is a data object: prompts, greetings, voice, palette, features. No
behaviour, no subclassing. Everything in this module takes a Bot and does the
same thing for all of them, which is the point — a new bot is a folder with a
Bot in it, not a new copy of the runtime.

The split to hold on to when adding one: if it would read differently for
Lissa than for Athar, it belongs on the Bot; if it would read the same, it
belongs here.
"""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core import memory_store, recall

# edge-tts takes a signed percentage against the voice's normal speed: "-8%"
# is 8% slower. Everything downstream also needs it as a number — how fast the
# words actually come out — because the page paces its typing off it, and text
# that finishes early or late is worse than text that never tried to match.
_RATE_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*%\s*$")


def rate_factor(rate: str) -> float:
    """Turn an edge-tts rate string into a speed multiplier.

    ``"-8%"`` -> ``0.92`` (slower, so the clip runs longer); ``"+10%"`` -> ``1.1``.
    Anything unparseable is 1.0, because a typo in a dashboard field should
    make the voice ordinary rather than absurd. The result is clamped to a
    sane band for the same reason: "-100%" would otherwise divide the typing
    pace by zero.
    """
    match = _RATE_RE.match(rate or "")
    if not match:
        return 1.0
    return min(3.0, max(0.25, 1.0 + float(match.group(1)) / 100.0))

# Every bot's long-term memory has the same shape. Two of the lists are named
# by the bot, because what's worth carrying forward differs: Lissa keeps
# running jokes, Athar keeps what someone resolved to do. The storage is
# identical; only the label and the prompt around it change.
BLANK = {"facts": [], "threads": [], "extras": [],
         "met": "", "last": "", "chats": 0, "flavour": "", "flavour_day": ""}

# Keys an older single-bot build wrote into the same browser. Read once so a
# returning visitor doesn't come back to a stranger.
LEGACY_ALIASES = {"extras": ("jokes", "commitments"), "flavour": ("mood",),
                  "flavour_day": ("mood_day",)}


@dataclass(frozen=True)
class Bot:
    """One chatbot: who it is, how it sounds, and what the UI shows."""

    slug: str                     # url segment and storage namespace
    name: str
    tagline: str                  # one line, for the landing page
    emoji: str

    system_prompt: str
    # Paragraphs appended to the system prompt when there is something to
    # append. Each takes {items} (a bulleted list), except "flavour" which
    # takes {flavour} and "history" which takes {history}. A bot may omit any
    # of them; the section is then skipped even when the data exists.
    sections: dict[str, str]

    memory_prompt: str            # the distillation instruction, with {facts} etc.
    extras_name: str              # what the third memory list is called in prompts
    max_facts: int = 30
    max_threads: int = 8
    max_extras: int = 5

    # Drawn once per calendar day and kept, so the bot is recognisably itself
    # across a conversation instead of lurching about message to message.
    flavours: tuple[str, ...] = ()

    langs: tuple[str, ...] = ("en",)
    rtl_langs: tuple[str, ...] = ()
    time_phrases: dict = field(default_factory=dict)
    greetings: dict = field(default_factory=dict)          # first meeting
    returning: dict = field(default_factory=dict)
    awhile: dict = field(default_factory=dict)             # after a long gap
    awhile_days: int = 10
    rate_limit_msg: dict = field(default_factory=dict)
    daily_cap_msg: dict = field(default_factory=dict)
    sign_off: str = ""            # the terminal app's goodbye

    tts_voice: str = "Leda"
    tts_style: str = "Say this warmly: "
    edge_voice: str = "en-US-AvaMultilingualNeural"
    edge_rate: str = "-8%"
    # Honorifics and glyphs a voice would otherwise stumble over.
    speech_swaps: dict = field(default_factory=dict)

    features: frozenset = frozenset(("voice", "memory", "photos"))
    palette: dict = field(default_factory=dict)
    avatar_svg: str = ""
    ui: dict = field(default_factory=dict)   # per-language string overrides

    def lang(self, lang: str) -> str:
        """The nearest language this bot actually speaks."""
        return lang if lang in self.langs else self.langs[0]

    def has(self, feature: str) -> bool:
        return feature in self.features

    @property
    def speech_rate(self) -> str:
        """This bot's speaking rate, overridable without a deploy.

        ``PLATFORM_EDGE_RATE_<SLUG>`` beats ``PLATFORM_EDGE_RATE`` beats the
        bot's own ``edge_rate``, so one dashboard field can slow everything
        down while a single bot can still be tuned on its own — the two ship
        at different speeds on purpose.

        Read at call time rather than import time: changing it on the host
        should take effect on the next request, not require remembering that
        a restart is also needed.
        """
        return (os.environ.get(f"PLATFORM_EDGE_RATE_{self.slug.upper()}")
                or os.environ.get("PLATFORM_EDGE_RATE")
                or self.edge_rate)

    def manifest(self) -> dict:
        """What the browser needs to dress itself as this bot."""
        return {
            "slug": self.slug, "name": self.name, "tagline": self.tagline,
            "emoji": self.emoji, "langs": list(self.langs),
            "rtl": list(self.rtl_langs), "features": sorted(self.features),
            "palette": self.palette, "avatar": self.avatar_svg,
            "ui": self.ui, "extrasLabel": self.extras_name,
            # How fast this bot speaks, as a multiplier. The page types in
            # step with the voice, so it has to know what the voice was told.
            "speechRate": rate_factor(self.speech_rate),
        }


# --- memory -----------------------------------------------------------------

def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def days_since(stamp: str) -> int | None:
    try:
        return (datetime.now().date()
                - datetime.strptime(stamp, "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


def blank_memory() -> dict:
    return {k: (list(v) if isinstance(v, list) else v) for k, v in BLANK.items()}


def clean_memory(bot: Bot, raw) -> dict:
    """Coerce anything — client JSON, an old memory file, junk — into the
    memory shape. Client-supplied data reaches a system prompt from here, so
    every field is bounded and the flavour must be one we wrote ourselves."""
    mem = blank_memory()
    if isinstance(raw, list):
        raw = {"facts": raw}
    if not isinstance(raw, dict):
        return mem

    def pick(key):
        if key in raw:
            return raw[key]
        for alias in LEGACY_ALIASES.get(key, ()):
            if alias in raw:
                return raw[alias]
        return None

    def strs(value, cap):
        if not isinstance(value, list):
            return []
        return [s.strip()[:200] for s in value if isinstance(s, str) and s.strip()][:cap]

    mem["facts"] = memory_store.normalize(raw.get("facts"), bot.max_facts)
    mem["threads"] = strs(raw.get("threads"), bot.max_threads)
    mem["extras"] = strs(pick("extras"), bot.max_extras)
    for key in ("met", "last"):
        value = raw.get(key)
        mem[key] = value if isinstance(value, str) and days_since(value) is not None else ""
    chats = raw.get("chats")
    mem["chats"] = chats if isinstance(chats, int) and 0 <= chats < 100000 else 0
    flavour = pick("flavour")
    mem["flavour"] = flavour if flavour in bot.flavours else ""
    day = pick("flavour_day")
    mem["flavour_day"] = day if isinstance(day, str) and days_since(day) is not None else ""
    return mem


def roll_flavour(bot: Bot, mem: dict) -> dict:
    """Draw today's mood/theme if the stored one isn't from today."""
    mem = clean_memory(bot, mem)
    if bot.flavours and (not mem["flavour"] or mem["flavour_day"] != today()):
        mem["flavour"] = random.choice(bot.flavours)
        mem["flavour_day"] = today()
    return mem


def touch_memory(bot: Bot, mem: dict) -> dict:
    """Record that a conversation happened today."""
    mem = roll_flavour(bot, mem)
    mem["chats"] += 1
    mem["met"] = mem["met"] or today()
    mem["last"] = today()
    return mem


def history_line(bot: Bot, mem: dict) -> str:
    """How long they've known each other, the vague way a person would put it."""
    chats, gap = mem.get("chats") or 0, days_since(mem.get("met") or "")
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
    away = days_since(mem.get("last") or "")
    line = f"This is conversation number {chats + 1} between you — {since}."
    if away is not None and away >= bot.awhile_days:
        line += f" You haven't spoken in {away} days."
    return line


# --- the system prompt ------------------------------------------------------

def build_prompt(bot: Bot, mem: dict, context: str = "") -> str:
    """Persona, then whatever this person and this moment add to it.

    `context` is a situational note from a feature module (prayer times, say)
    — empty for bots and visitors that have none.
    """
    mem = clean_memory(bot, mem)
    out = [bot.system_prompt]
    section = bot.sections.get

    if context and section("context"):
        out.append(section("context").format(items=context))
    if mem["flavour"] and section("flavour"):
        out.append(section("flavour").format(flavour=mem["flavour"]))
    if mem["facts"] and section("facts"):
        # Strongest first (memory_store ranks them), so a model that skims
        # skims what matters most about this person.
        out.append(section("facts").format(
            items="\n".join(f"- {t}" for t in memory_store.texts(mem["facts"]))))
    history = history_line(bot, mem)
    if history and section("history"):
        out.append(section("history").format(history=history))
    if mem["extras"] and section("extras"):
        out.append(section("extras").format(
            items="\n".join(f"- {e}" for e in mem["extras"])))
    if mem["threads"] and section("threads"):
        out.append(section("threads").format(
            items="\n".join(f"- {t}" for t in mem["threads"])))
    return "\n".join(out)


def turn_prompt(bot: Bot, client, mem: dict, message: str, context: str = "") -> str:
    """A per-message prompt holding only the memories this message calls for.

    recall.relevant() degrades to every fact on any failure, which is the old
    behaviour and never worse than a wrong subset.
    """
    mem = clean_memory(bot, mem)
    facts = recall.relevant(client, mem["facts"], message)
    return build_prompt(bot, {**mem, "facts": facts}, context)


# --- greeting ---------------------------------------------------------------

def time_phrase(bot: Bot, lang: str, hour: int | None) -> str:
    """The visitor's own hour decides this: the server runs in UTC and is
    hours off from most of them."""
    if hour is None:
        hour = datetime.now().hour
    if 6 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 17:
        period = "afternoon"
    elif 17 <= hour < 21:
        period = "evening"
    else:
        period = "night"
    phrases = bot.time_phrases.get(lang) or bot.time_phrases.get(bot.langs[0], {})
    return phrases.get(period, "")


def greeting(bot: Bot, mem: dict, lang: str = "en", hour: int | None = None) -> str:
    lang = bot.lang(lang)
    mem = clean_memory(bot, mem)
    if not mem["facts"]:
        return bot.greetings[lang].format(time_phrase=time_phrase(bot, lang, hour))
    away = days_since(mem["last"])
    if away is not None and away >= bot.awhile_days:
        return bot.awhile[lang]
    return bot.returning[lang]


def canned(messages: dict, lang: str, fallback: str, **fmt) -> str:
    """One of the hand-localized strings (rate limits, caps). Unlike replies,
    these never pass through the model, so they don't follow the visitor's
    language on their own."""
    return messages.get(lang, messages.get(fallback, "")).format(**fmt)


# --- distillation -----------------------------------------------------------

def transcript_of(bot: Bot, session) -> str:
    lines = []
    for content in session.get_history():
        speaker = "User" if content.role == "user" else bot.name
        for part in content.parts or []:
            if part.text:
                lines.append(f"{speaker}: {part.text}")
    return "\n".join(lines)


def memory_schema(types):
    """The JSON shape the distiller must return. Takes the genai `types`
    module so this stays importable without the SDK for tests.

    "name" is a field of its own rather than one more entry in "facts". Every
    bot's prompt already says the name is the most important thing to keep and
    to always mark it core, and the model still drops it — it competes for a
    slot against everything else the conversation turned up, and a lively hour
    about the sea crowds it out. Asked as a direct question with a slot that
    must be filled, the same model answers it reliably. name_fact() then makes
    the promotion to a core fact ours rather than the model's.
    """
    strings = types.Schema(type=types.Type.ARRAY,
                           items=types.Schema(type=types.Type.STRING))
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "name": types.Schema(type=types.Type.STRING),
            "facts": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={"text": types.Schema(type=types.Type.STRING),
                                "core": types.Schema(type=types.Type.BOOLEAN)},
                    required=["text", "core"])),
            "outdated": strings,
            "threads": strings,
            "extras": strings,
        },
        required=["name", "facts", "outdated", "threads", "extras"],
    )


# A model told to return "" when it doesn't know the name sometimes says so in
# words instead. These are never a real name, and one of them written into
# memory as a core fact would outlive everything else in there.
_NOT_A_NAME = frozenset(
    ["unknown", "none", "n/a", "na", "null", "nil", "undefined", "unnamed",
     "user", "the user", "student", "the student", "anonymous", "-"]
)
NAME_MAX = 60  # a name, not a sentence — anything longer is the model rambling

# Phrasings whose entire purpose is to state a name, in the five languages the
# platform speaks. "I'm ..." is deliberately absent: "I'm tired" is not an
# introduction, and a wrong name written in as core never decays back out.
_NAME_LEAD = re.compile(
    r"(?:my\s+name\s+is|my\s+name's|call\s+me|i\s+go\s+by"
    r"|jina\s+langu\s+ni|(?:ni)?naitwa"
    r"|je\s+m'?appelle|mon\s+nom\s+est"
    r"|meu\s+nome\s+[eé]|me\s+chamo"
    r"|اسمي)\s+",
    re.IGNORECASE,
)

# Where a name stops: punctuation, or the connective starting the next clause.
# "my name is Zanzibar and I love mango juice" gives up the name, not the juice.
_NAME_END = re.compile(
    r"[,.;:!?]|\s+(?:and|but|or|so|because|na|lakini|et|mais|e|mas|y|و)\s+",
    re.IGNORECASE,
)

# Words that follow the lead-in without being a name.
_NOT_A_NAME_OPENER = frozenset(
    ["a", "an", "the", "not", "just", "only", "still", "actually", "really"]
)
_NOT_A_NAME_WORD = frozenset(
    ["later", "back", "tomorrow", "tonight", "soon", "now", "again", "anytime",
     "sometime", "when", "whenever", "if", "please", "maybe", "that", "this",
     # "my name is a secret" is a refusal to give one, not a name
     "secret", "private", "important", "irrelevant", "mystery", "none"]
)


def stated_name(transcript: str) -> str | None:
    """A name the person gave in so many words, or None.

    The model is asked for the name directly and still leaves the field empty
    often enough to lose someone's name — see memory_schema(). Where the
    person said it outright, no model needs to be involved at all.

    Deliberately narrow, because a false positive here is written to memory as
    a core fact and core facts never decay: only lead-ins that exist to
    introduce someone, only the user's own lines (the bot says its own name
    constantly), and only the last one, since a correction should win.
    """
    found = None
    for line in (transcript or "").splitlines():
        speaker, sep, said = line.partition(":")
        if not sep or speaker.strip().lower() != "user":
            continue
        for lead in _NAME_LEAD.finditer(said):
            tail = said[lead.end():]
            stop = _NAME_END.search(tail)
            if stop:
                tail = tail[:stop.start()]
            words = tail.split()
            while words and words[0].lower().strip(".,'\"") in _NOT_A_NAME_OPENER:
                words.pop(0)
            if not words or words[0].lower().strip(".,'\"") in _NOT_A_NAME_WORD:
                continue
            # The first word, then only further *capitalized* ones: that takes
            # "Zanzibar Mwinyi" whole while leaving the tail of "Zanzibar these
            # days" behind. Scripts without case (Arabic) give one word, which
            # is the common shape there anyway.
            name = [words[0]]
            for word in words[1:3]:
                if not word[:1].isupper():
                    break
                name.append(word)
            candidate = " ".join(name).strip(" '\"“”‘’-")
            if candidate and not any(ch.isdigit() for ch in candidate):
                found = candidate
    return found


def name_fact(raw: Any) -> dict | None:
    """The core fact a reported name earns, or None if it isn't one.

    Kept deliberately close to how the model phrases the rest of the list, so
    memory_store.merge() matches it against a name fact from an earlier cycle
    and reinforces that record instead of stacking up a second one.
    """
    if not isinstance(raw, str):
        return None
    name = " ".join(raw.split())  # newlines and runs of spaces collapse
    if not name or len(name) > NAME_MAX or name.lower() in _NOT_A_NAME:
        return None
    return {"text": f"Their name is {name}.", "core": True}


def fold_observations(bot: Bot, mem: dict, observed: dict,
                      transcript: str = "") -> dict:
    """Merge one distillation cycle into memory.

    The model reports only what this conversation supports; the weighting,
    fading and forgetting happen locally in memory_store.merge(). Facts fading
    to empty is a legitimate outcome, so an empty list is not failure. threads
    and extras overwrite wholesale — they aren't weighted, and the prompt asks
    the model to carry live ones forward. met/last/chats/flavour are ours and
    never come from the model.

    A reported name is folded in as a core fact whether or not the model also
    thought to list it — see memory_schema() for why that isn't left to the
    prompt. When the model did list it, that entry is promoted to core rather
    than a second one being added: merge() deliberately refuses to land two
    observations on the same record, so adding both would leave the person
    with their name twice over.

    `transcript` is the last resort under that: where someone introduced
    themselves in so many words, stated_name() reads it off what they wrote
    and no model judgment is involved. The model's own answer still wins when
    it gives one — it catches the phrasings a pattern never will.
    """
    mentioned = [dict(f) if isinstance(f, dict) else {"text": f}
                 for f in observed.get("facts", []) if f]
    named = name_fact(observed.get("name")) or name_fact(stated_name(transcript))
    if named:
        already = next(
            (f for f in mentioned
             if memory_store.similarity(named["text"], f.get("text") or "")
             >= memory_store.MATCH_THRESHOLD),
            None,
        )
        if already:
            already["core"] = True
        else:
            mentioned.insert(0, named)
    facts = memory_store.merge(mem["facts"], mentioned,
                               observed.get("outdated", []), bot.max_facts)
    fresh = clean_memory(bot, {"threads": observed.get("threads", []),
                               "extras": observed.get("extras", [])})
    return {**mem, "facts": facts, "threads": fresh["threads"],
            "extras": fresh["extras"]}


def distill_prompt(bot: Bot, mem: dict, transcript: str) -> str:
    return bot.memory_prompt.format(
        facts=json.dumps(memory_store.texts(mem["facts"]), ensure_ascii=False),
        threads=json.dumps(mem["threads"], ensure_ascii=False),
        extras=json.dumps(mem["extras"], ensure_ascii=False),
        transcript=transcript,
        max_facts=bot.max_facts,
        max_threads=bot.max_threads,
        max_extras=bot.max_extras,
    )
