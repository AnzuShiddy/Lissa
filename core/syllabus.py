"""The Tanzanian secondary syllabus, read locally.

Like :mod:`core.prayer`, this knows something on its own: no key, no API call,
no network. The data in ``data/syllabus/`` is the Tanzania Institute of
Education 2023 competence-based syllabus for Ordinary Secondary Education
(Form I–IV), parsed from the official PDFs — each entry keeps the main
competence, the specific competence beneath it, and the learning activity as
TIE worded them.

That wording is the point. A tutor that grounds on it can say "this is the
competence you're being examined against" instead of improvising a plausible
topic list, and it can be held to the text: everything here is quotable, and
nothing outside it should be presented as syllabus.

Sizing drove the shape. The whole syllabus is ~206k characters, far too much
for a prompt; one form of one subject is ~2k, which fits comfortably. So the
unit of grounding is (subject, form), and the tutor's job is to establish
which one it's working in.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "syllabus"

FORMS = ("Form One", "Form Two", "Form Three", "Form Four")

# How a student actually names a form, in either language. Ordered longest
# first where prefixes overlap, so "form one" can't be read as "form on".
_FORM_WORDS = {
    "Form One": ("form one", "form 1", "form i", "f1", "kidato cha kwanza",
                 "kidato cha 1", "first form"),
    "Form Two": ("form two", "form 2", "form ii", "f2", "kidato cha pili",
                 "kidato cha 2", "second form"),
    "Form Three": ("form three", "form 3", "form iii", "f3", "kidato cha tatu",
                   "kidato cha 3", "third form"),
    "Form Four": ("form four", "form 4", "form iv", "f4", "kidato cha nne",
                  "kidato cha 4", "fourth form"),
}

# Names a student is likely to use for a subject that the syllabus titles
# differently — Swahili names, common short forms, and the everyday word for
# a subject whose official title is a mouthful.
_SUBJECT_WORDS = {
    "Biology": ("biolojia",),
    "Chemistry": ("kemia",),
    "Physics": ("fizikia", "fizikia"),
    "Mathematics": ("maths", "math", "hisabati", "basic mathematics"),
    "Geography": ("jiografia",),
    "History": ("historia",),
    "Kiswahili": ("swahili",),
    "English Language": ("english", "kiingereza"),
    "Literature in English": ("literature", "fasihi"),
    "Business Studies": ("business", "biashara", "commerce"),
    "Computer Science": ("computer", "computers", "ict", "tehama"),
    "Bible Knowledge": ("bible", "biblia"),
    "Elimu ya Dini ya Kiislamu": ("islamic knowledge", "dini ya kiislamu",
                                  "elimu ya dini", "islamic studies"),
    "Historia ya Tanzania na Maadili": ("historia ya tanzania", "maadili",
                                        "history of tanzania"),
}


def _fold(text: str) -> str:
    """Lowercase, strip accents, squash punctuation to single spaces.

    Students type "form-2", "FORM 2:", "kidato cha pili?" — matching should
    not care, and neither should it care about the accents a phone keyboard
    may or may not produce.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    """Every subject, keyed by its official title. Cached: the files never
    change while the process runs, and a tutor asks for them constantly.

    A missing or unreadable file is skipped rather than fatal — one bad
    subject shouldn't take the bot down with it.
    """
    out: dict[str, dict] = {}
    if not DATA.is_dir():
        return out
    for path in sorted(DATA.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("subject") and data.get("forms"):
                out[data["subject"]] = data
        except (OSError, ValueError):
            continue
    return out


def subjects() -> list[str]:
    """Official subject titles, alphabetically."""
    return sorted(_load())


def forms_for(subject: str) -> list[str]:
    """Which forms this subject actually has data for, in school order."""
    data = _load().get(subject)
    if not data:
        return []
    return [f for f in FORMS if f in data["forms"]]


def find_subject(text: str) -> str | None:
    """The subject named in `text`, or None.

    Longest match wins, so "literature in english" isn't captured by the
    "english" alias of English Language.
    """
    folded = _fold(text)
    if not folded:
        return None
    candidates: list[tuple[int, str]] = []
    for subject in _load():
        names = (subject,) + _SUBJECT_WORDS.get(subject, ())
        for name in names:
            needle = _fold(name)
            if needle and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", folded):
                candidates.append((len(needle), subject))
    if not candidates:
        return None
    return max(candidates)[1]


def find_form(text: str) -> str | None:
    """The form named in `text`, or None. Longest match wins for the same
    reason: "form 1" must not win inside "form 10" — and "f1" must not fire
    on the "f1" inside a word."""
    folded = _fold(text)
    if not folded:
        return None
    best: tuple[int, str] | None = None
    for form, words in _FORM_WORDS.items():
        for word in words:
            needle = _fold(word)
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", folded):
                if best is None or len(needle) > best[0]:
                    best = (len(needle), form)
    return best[1] if best else None


def detect(text: str) -> tuple[str | None, str | None]:
    """Pull (subject, form) out of something a student typed.

    Either half may come back None — "I'm in form two" settles the form and
    leaves the subject open, which is a perfectly normal thing to say, and
    the tutor asks for the rest.
    """
    return find_subject(text), find_form(text)


def activities(subject: str, form: str) -> list[dict]:
    data = _load().get(subject)
    if not data:
        return []
    return data["forms"].get(form, [])


def _and_list(items: list[str]) -> str:
    """"a", "a and b", "a, b and c" — the tutor reads this aloud."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def catalogue() -> str:
    """The one-line inventory the tutor always carries, so it knows the edge
    of what it can ground on before a student names anything.

    The forms are read off the data rather than asserted. Not every subject
    runs the full four: Literature in English starts in Form Three in the
    Tanzanian system, and a blanket "each covers Form One to Form Four" told
    the tutor it held a Form One Literature syllabus that does not exist —
    the exact invention test_a_subject_only_taught_in_the_upper_forms_says_so
    guards the data against.
    """
    names = subjects()
    if not names:
        return ""
    line = "Subjects you have the TIE syllabus for: " + ", ".join(names) + "."
    odd = [(name, forms) for name in names
           if (forms := forms_for(name)) != list(FORMS)]
    if not odd:
        return line + " Each covers Form One to Form Four."
    if len(odd) < len(names):
        line += " Each covers Form One to Form Four, except:"
    else:
        line += " The forms each one covers:"
    return line + " " + "; ".join(
        f"{name} ({_and_list(forms)} only)" for name, forms in odd) + "."


def context(subject: str | None, form: str | None) -> str:
    """The situational note for a tutoring session.

    With no subject or form settled it returns the catalogue alone, which is
    what lets the tutor ask a precise question ("which subject, and which
    form?") rather than a vague one. With both settled it adds that form's
    competences verbatim.
    """
    parts = [catalogue()]
    rows = activities(subject, form) if subject and form else []
    if rows:
        data = _load()[subject]
        lines = []
        seen_main = None
        for row in rows:
            if row["main"] != seen_main:
                seen_main = row["main"]
                lines.append(f"  {row['main']}")
            lines.append(f"    {row['competence']}")
            # A handful of learning activities (22 of 769, all in Chemistry
            # and Physics) didn't survive the extraction from TIE's PDFs. The
            # competence above them is intact and is the part a student is
            # assessed against, so the row is still worth carrying — but an
            # empty line under it would read as a gap in the syllabus rather
            # than a gap in our parse.
            if row["activity"].strip():
                lines.append(f"      {row['activity']}")
        parts.append(
            f"\nThis student is working on {subject}, {form} "
            f"({data.get('syllabus_edition', 'TIE')} syllabus). The "
            f"competences and learning activities for that form, as TIE "
            f"worded them:\n" + "\n".join(lines) +
            "\n\nYou already know their subject and form — they are stated "
            "above. Do not ask for either again in this conversation; asking "
            "someone something they have just told you is the fastest way to "
            "look like you weren't listening.\n"
            "Stay inside this when you talk about what the syllabus "
            "covers. Quote a competence when it helps them see what they are "
            "actually being assessed on. If they ask about something that "
            "isn't here, say plainly that it isn't in this form's syllabus — "
            "it may be in another form, or not in the syllabus at all — and "
            "then help them anyway if it's a fair question."
        )
    elif subject and form:
        parts.append(f"\nYou have no syllabus data for {subject}, {form}. "
                     "Say so rather than inventing it.")
    return "\n".join(p for p in parts if p)
