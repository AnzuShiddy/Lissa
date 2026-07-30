"""Prayer times, qibla direction and the Hijri date — computed locally.

There are perfectly good prayer-time APIs, and every one of them is a network
round-trip that can fail, rate-limit, or quietly change its answers. The
underlying astronomy is a page of trigonometry, so it lives here instead: no
key, no outbound call, no dependency, and the same answer offline.

The method follows the standard convention used by PrayTimes and the major
calculators: solar declination and the equation of time from the low-precision
formulae in the Astronomical Almanac, then the hour angle at which the sun
reaches each prayer's defining altitude.

What this is NOT is an authority. Calculated times differ from a local
masjid's by a few minutes for real reasons — the convention chosen, the
elevation, how the masjid rounds — and the Hijri date here is the arithmetic
calendar, which can sit a day or two off a moon sighting. Everything that
leaves this module is labelled accordingly, and the system prompt tells the
model to defer to the local masjid. Treat it as an orientation, not a fatwa.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

# The Kaaba, for the qibla bearing.
KAABA_LAT, KAABA_LON = 21.4225, 39.8262

# Fajr and Isha are defined by how far the sun sits below the horizon, and the
# committees differ on the angle. Isha may instead be a fixed interval after
# Maghrib ("90 min"), which is the Umm al-Qura convention.
METHODS = {
    "MWL": {"label": "Muslim World League", "fajr": 18.0, "isha": 17.0},
    "ISNA": {"label": "Islamic Society of North America", "fajr": 15.0, "isha": 15.0},
    "Egypt": {"label": "Egyptian General Authority of Survey", "fajr": 19.5, "isha": 17.5},
    "Makkah": {"label": "Umm al-Qura, Makkah", "fajr": 18.5, "isha_minutes": 90},
    "Karachi": {"label": "University of Islamic Sciences, Karachi", "fajr": 18.0, "isha": 18.0},
    "Gulf": {"label": "Gulf Region", "fajr": 19.5, "isha_minutes": 90},
    "Singapore": {"label": "Majlis Ugama Islam Singapura", "fajr": 20.0, "isha": 18.0},
}
DEFAULT_METHOD = "MWL"

# Asr begins when an object's shadow equals its own length plus its noon
# shadow (the majority) or twice its length (the Hanafi position).
ASR_FACTORS = {"standard": 1, "hanafi": 2}

# Sunrise and sunset are reckoned at 0.833° below the horizon: the standard
# allowance for the sun's semi-diameter plus atmospheric refraction.
HORIZON = 0.833

PRAYERS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
# Sunrise is not a prayer — it's the end of Fajr's window — but it belongs on
# a timetable, so it is carried through and only excluded where it would be
# wrong (the "next prayer" countdown still includes it, because someone
# waiting for it usually has Fajr on their mind).

HIJRI_MONTHS = (
    "Muharram", "Safar", "Rabi' al-Awwal", "Rabi' ath-Thani",
    "Jumada al-Ula", "Jumada al-Akhirah", "Rajab", "Sha'ban",
    "Ramadan", "Shawwal", "Dhu al-Qi'dah", "Dhu al-Hijjah",
)

PRAYER_ARABIC = {
    "fajr": "الفجر", "sunrise": "الشروق", "dhuhr": "الظهر",
    "asr": "العصر", "maghrib": "المغرب", "isha": "العشاء",
}


# --- small trig helpers, in degrees ------------------------------------------

def _sin(d: float) -> float: return math.sin(math.radians(d))
def _cos(d: float) -> float: return math.cos(math.radians(d))
def _tan(d: float) -> float: return math.tan(math.radians(d))
def _arcsin(x: float) -> float: return math.degrees(math.asin(x))
def _arccos(x: float) -> float: return math.degrees(math.acos(x))
def _arctan2(y: float, x: float) -> float: return math.degrees(math.atan2(y, x))
def _arccot(x: float) -> float: return math.degrees(math.atan2(1.0, x))


def _fix(a: float, b: float) -> float:
    a = a - b * math.floor(a / b)
    return a + b if a < 0 else a


def _fix_angle(a: float) -> float: return _fix(a, 360.0)
def _fix_hour(a: float) -> float: return _fix(a, 24.0)


def julian_day(d: date) -> float:
    """Julian day number at 00:00 UT on `d`."""
    year, month, day = d.year, d.month, d.day
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    return (math.floor(365.25 * (year + 4716))
            + math.floor(30.6001 * (month + 1))
            + day + b - 1524.5)


def sun_position(jd: float) -> tuple[float, float]:
    """(declination, equation of time) for Julian day `jd`, degrees and hours.

    Low-precision solar coordinates from the Astronomical Almanac — good to
    about a minute of arc over the years this will plausibly be used, which is
    far below the precision anyone reads off a prayer timetable.
    """
    d = jd - 2451545.0
    g = _fix_angle(357.529 + 0.98560028 * d)      # mean anomaly
    q = _fix_angle(280.459 + 0.98564736 * d)      # mean longitude
    lam = _fix_angle(q + 1.915 * _sin(g) + 0.020 * _sin(2 * g))  # ecliptic longitude
    obliquity = 23.439 - 0.00000036 * d
    declination = _arcsin(_sin(obliquity) * _sin(lam))
    right_ascension = _fix_hour(_arctan2(_cos(obliquity) * _sin(lam), _cos(lam)) / 15.0)
    eq_time = q / 15.0 - right_ascension
    return declination, eq_time


class _Day:
    """One place on one date — the working state for a set of times.

    Times come out as hours after local midnight (so 5.5 is 05:30), and are
    computed in UT then shifted by the caller's offset at the end. Anything
    the sun never reaches at this latitude comes back as None rather than a
    fabricated time; see times() for what that means in practice.
    """

    def __init__(self, d: date, lat: float, lon: float, offset_hours: float):
        self.lat, self.lon = lat, lon
        self.offset = offset_hours
        # Shift to the local meridian so the day fractions below are local.
        self.jd = julian_day(d) - lon / (15.0 * 24.0)

    def midday(self, t: float) -> float:
        _, eq_time = sun_position(self.jd + t)
        return _fix_hour(12.0 - eq_time)

    def angle_time(self, angle: float, t: float, before_noon: bool) -> float | None:
        """When the sun sits `angle` degrees below the horizon on day-fraction
        `t`. None where it never does — a polar summer's Fajr and Isha."""
        declination, _ = sun_position(self.jd + t)
        numerator = -_sin(angle) - _sin(declination) * _sin(self.lat)
        denominator = _cos(declination) * _cos(self.lat)
        if denominator == 0:
            return None
        ratio = numerator / denominator
        if not -1.0 <= ratio <= 1.0:
            return None
        offset = _arccos(ratio) / 15.0
        return self.midday(t) + (-offset if before_noon else offset)

    def asr_time(self, factor: int, t: float) -> float | None:
        declination, _ = sun_position(self.jd + t)
        angle = -_arccot(factor + _tan(abs(self.lat - declination)))
        return self.angle_time(angle, t, before_noon=False)


def times(
    d: date,
    lat: float,
    lon: float,
    offset_hours: float,
    method: str = DEFAULT_METHOD,
    asr: str = "standard",
) -> dict[str, float | None]:
    """Prayer times for one day, as hours after local midnight.

    `offset_hours` is the place's UTC offset — the browser's own offset, not
    the server's: this app is deployed in UTC and its visitors are not.

    Each time is computed twice, the second pass seeded with the first pass's
    answer. The sun's declination changes over the day, so a single pass using
    a rough guess for "when Fajr is" carries a small error into the answer;
    one refinement drops it below the minute the caller will round to.
    """
    if method not in METHODS:
        method = DEFAULT_METHOD
    conf = METHODS[method]
    factor = ASR_FACTORS.get(asr, 1)
    day = _Day(d, lat, lon, offset_hours)

    # Rough starting points, in fractions of a day.
    guess = {"fajr": 5 / 24, "sunrise": 6 / 24, "dhuhr": 12 / 24,
             "asr": 13 / 24, "maghrib": 18 / 24, "isha": 18 / 24}
    result: dict[str, float | None] = dict.fromkeys(PRAYERS)

    for _ in range(2):
        result["fajr"] = day.angle_time(conf["fajr"], guess["fajr"], before_noon=True)
        result["sunrise"] = day.angle_time(HORIZON, guess["sunrise"], before_noon=True)
        result["dhuhr"] = day.midday(guess["dhuhr"])
        result["asr"] = day.asr_time(factor, guess["asr"])
        result["maghrib"] = day.angle_time(HORIZON, guess["maghrib"], before_noon=False)
        if "isha_minutes" in conf:
            result["isha"] = (result["maghrib"] + conf["isha_minutes"] / 60.0
                              if result["maghrib"] is not None else None)
        else:
            result["isha"] = day.angle_time(conf["isha"], guess["isha"], before_noon=False)
        guess = {k: (v / 24.0 if v is not None else guess[k]) for k, v in result.items()}

    # Dhuhr is the sun's transit; the prayer begins once it has visibly moved
    # off the meridian, and every calculator adds a small allowance for it.
    if result["dhuhr"] is not None:
        result["dhuhr"] += 65 / 3600.0

    shift = day.offset - lon / 15.0
    return {
        name: (_fix_hour(value + shift) if value is not None else None)
        for name, value in result.items()
    }


def format_hm(hours: float | None) -> str | None:
    """Hours-after-midnight as HH:MM, rounded to the nearest minute."""
    if hours is None:
        return None
    total = int(round(hours * 60)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def next_prayer(day_times: dict[str, float | None], now_hours: float
                ) -> tuple[str, float] | None:
    """The next prayer and how many hours away it is.

    Wraps past midnight to tomorrow's Fajr, which is the answer anyone asking
    after Isha actually wants. None only if nothing could be computed at all.
    """
    upcoming = [(name, t) for name, t in day_times.items()
                if t is not None and t > now_hours]
    if upcoming:
        name, when = min(upcoming, key=lambda pair: pair[1])
        return name, when - now_hours
    fajr = day_times.get("fajr")
    if fajr is None:
        return None
    return "fajr", (24.0 - now_hours) + fajr


def qibla(lat: float, lon: float) -> float:
    """Compass bearing to the Kaaba, in degrees clockwise from true north.

    Great-circle initial bearing — the direction the fiqh intends, and the one
    that looks wrong on a flat map from northern latitudes (from London it
    points south-east, not south).
    """
    delta = KAABA_LON - lon
    y = _sin(delta)
    x = _cos(lat) * _tan(KAABA_LAT) - _sin(lat) * _cos(delta)
    return _fix_angle(_arctan2(y, x))


COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def compass_point(bearing: float) -> str:
    return COMPASS[int((bearing + 11.25) % 360 // 22.5)]


def hijri(d: date) -> tuple[int, int, int]:
    """(year, month, day) in the tabular Islamic calendar.

    Arithmetic, not observational: it assumes the standard 30-year cycle of
    11 leap years rather than an actual sighting of the crescent, so it can
    land a day either side of what a given country announces — and around the
    two Eids that difference is the whole question. Always present it as
    approximate.
    """
    jdn = int(julian_day(d) + 0.5)
    l = jdn - 1948440 + 10632
    n = (l - 1) // 10631
    l = l - 10631 * n + 354
    j = ((10985 - l) // 5316) * ((50 * l) // 17719) + (l // 5670) * ((43 * l) // 15238)
    l = (l - ((30 - j) // 15) * ((17719 * j) // 50)
         - (j // 16) * ((15238 * j) // 43) + 29)
    month = (24 * l) // 709
    day = l - (709 * month) // 24
    year = 30 * n + j - 30
    return year, month, day


def hijri_text(d: date) -> str:
    year, month, day = hijri(d)
    name = HIJRI_MONTHS[min(max(month, 1), 12) - 1]
    return f"{day} {name} {year} AH"


def summary(
    lat: float,
    lon: float,
    offset_hours: float,
    method: str = DEFAULT_METHOD,
    asr: str = "standard",
    now: datetime | None = None,
) -> dict:
    """Everything the UI and the prompt need for one place, right now.

    `now` is the visitor's own local time — the caller reconstructs it from
    their UTC offset, because the server's clock is in UTC and would put half
    the world's visitors in the wrong prayer.
    """
    now = now or datetime.utcnow() + timedelta(hours=offset_hours)
    day_times = times(now.date(), lat, lon, offset_hours, method, asr)
    now_hours = now.hour + now.minute / 60.0 + now.second / 3600.0

    upcoming = next_prayer(day_times, now_hours)
    bearing = qibla(lat, lon)
    return {
        "date": now.date().isoformat(),
        "hijri": hijri_text(now.date()),
        "method": method,
        "method_label": METHODS.get(method, METHODS[DEFAULT_METHOD])["label"],
        "asr": asr,
        "times": {name: format_hm(t) for name, t in day_times.items()},
        "next": upcoming[0] if upcoming else None,
        "next_in_minutes": int(round(upcoming[1] * 60)) if upcoming else None,
        "qibla": round(bearing, 1),
        "qibla_compass": compass_point(bearing),
        # Anything downstream that renders this should carry the caveat with
        # it, so it can't be quoted as though it were the masjid's timetable.
        "approximate": True,
    }


def _relative(minutes: int) -> str:
    if minutes < 60:
        return f"in {minutes} minutes"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"in {hours} hour{'s' if hours > 1 else ''}"
    return f"in {hours}h{mins:02d}m"


def context(data: dict | None, now: datetime | None = None) -> str:
    """The situational note that goes into the system prompt.

    Kept to a few plain lines: the model needs enough to answer "how long
    until Maghrib?" without being handed a table it will start reciting.
    Returns "" when the visitor hasn't shared a location, which is the normal
    case — the whole feature is opt-in.
    """
    if not data:
        return ""
    lines = [f"Today is {data['hijri']} (approximate — the arithmetic calendar, "
             f"not a moon sighting), {data['date']} in the Gregorian calendar."]
    if now is not None:
        lines.append(f"Their local time is {now.strftime('%H:%M')}.")
    order = [p for p in PRAYERS if data["times"].get(p)]
    if order:
        table = ", ".join(f"{p.capitalize()} {data['times'][p]}" for p in order)
        lines.append(f"Prayer times where they are ({data['method_label']}, "
                     f"{data['asr']} Asr): {table}.")
    if data.get("next") and data.get("next_in_minutes") is not None:
        lines.append(f"Next up is {data['next'].capitalize()} "
                     f"{_relative(data['next_in_minutes'])}.")
    lines.append(f"The qibla from where they are is {data['qibla']}° "
                 f"({data['qibla_compass']}) from true north.")
    return "\n".join(lines)
