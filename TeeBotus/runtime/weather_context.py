from __future__ import annotations

import json
import hashlib
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from TeeBotus.runtime.accounts import AccountStore, utc_now

WEATHER_CONTEXT_SCHEMA_VERSION = 1
WEATHER_CHECK_INTERVAL = timedelta(hours=2)
WEATHER_TIMEOUT_SECONDS = 2.5
MAX_CITY_LENGTH = 80
_RESIDENCE_DURATION = (
    r"(?:(?:mehr\s+als|über|ueber|knapp|gut|etwa|ungefähr|ungefaehr|"
    r"fast|circa|ca\.|rund|mindestens|hoechstens|höchstens)\s+)?"
    r"(?:\d{4}|kurzem|kurzer\s+zeit|einiger\s+zeit|jeher|"
    r"(?:dem\s+)?(?:letzten|letztem|vergangenen|vergangenem|aktuellen|aktuellem|diesem)\s+(?:jahr|sommer|winter)|"
    r"(?:meiner\s+)?(?:kindheit|jugend|geburt)|dem\s+(?:studium|umzug)|"
    r"(?:(?:ein\s+paar|\w+)\s+(?:tag(?:en)?|woche(?:n)?|monat(?:en)?|jahr(?:en)?)|"
    r"tag(?:en)?|woche(?:n)?|monat(?:en)?|jahr(?:en)?))"
)
_RESIDENCE_TIME_QUALIFIER = (
    rf"(?:(?:schon\s+)?seit\s+{_RESIDENCE_DURATION}|schon\s+lange|seitdem|"
    r"jetzt|nun|aktuell|derzeit|gerade|momentan|inzwischen|mittlerweile|"
    r"weiterhin|nach\s+wie\s+vor|noch\s+immer|immer\s+noch|"
    r"dauerhaft|permanent|ständig|staendig|"
    r"vor(?:uebergehend|übergehend))"
)
_RESIDENCE_LOCATION_ADVERB = (
    r"(?:hier|dort|da|direkt|nur|allein|überwiegend|ueberwiegend|"
    r"hauptsächlich|hauptsaechlich|vorwiegend|meistens)"
)
_PRIMARY_RESIDENCE_LABEL = r"(?:lebensmittelpunkt|hauptwohnsitz)"

CITY_CHANGE_PATTERNS = (
    re.compile(
        rf"\b(?:mein(?:e)?\s+)?{_PRIMARY_RESIDENCE_LABEL}\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"[^,.;!?]{1,80}?(?:,|;|[-–—])\s*(?:aber|doch|jedoch)?\s*"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER})\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?\s+)?{_PRIMARY_RESIDENCE_LABEL}\s+(?:ist|liegt|befindet\s+sich)\s+"
        r"nicht(?:\s+mehr)?\s+(?:(?:in|bei)\s+)?[^,.;!?]{1,80}?"
        r"(?:\s*(?:,|;|[-–—])\s*|\s+)sondern\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?\s+)?{_PRIMARY_RESIDENCE_LABEL}\s+war\s+"
        r"[^,.;!?]{1,80}?(?:,|;|[-–—])\s*(?:aber\s+)?"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?\s+)?{_PRIMARY_RESIDENCE_LABEL}\s+wurde\s+(?:(?:nach|in|zu)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+verlegt\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich\s+)?habe\s+(?:meinen|den)\s+{_PRIMARY_RESIDENCE_LABEL}\s+(?:nach|in|zu)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+verlegt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+wohne|ich\s+lebe)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}[.!?]\s*(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem|sondern)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80}[.!?]\s*"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:ich\s+)?(?:wohne|lebe)(?:\s+ich)?\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zu\s+hause|zuhause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+[^,.;!?]{1,80}[.!?]\s*"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:ich\s+)?(?:wohne|lebe)(?:\s+ich)?\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80}[.!?]\s*"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zu\s+hause|zuhause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+[^,.;!?]{1,80}[.!?]\s*"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zu\s+hause|zuhause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+"
        r"nicht(?:\s+mehr)?\s+(?:(?:in|bei)\s+)?[^,.;!?]{1,80}?"
        r"(?:\s*(?:,|;|[-–—])\s*|\s+)sondern\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zu\s+hause|zuhause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+"
        r"[^,.;!?]{1,80}?(?:,|;|[-–—])\s*(?:aber|doch|jedoch)\s+"
        rf"{_RESIDENCE_TIME_QUALIFIER}\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zu\s+hause|zuhause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+[^,.;!?]{1,80}?"
        r"(?:\s*(?:,|;|[-–—])\s*|\s+und\s+)"
        rf"{_RESIDENCE_TIME_QUALIFIER}\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zu\s+hause|zuhause|daheim)\s+war\s+"
        r"[^,.;!?]{1,80}?(?:\s+und\s+ist|(?:,|;|[-–—])\s*ist)\s+(?:aber\s+)?"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zu\s+hause|zuhause|daheim)\s+war\s+"
        r"[^,.;!?]{1,80}?(?:,|;|[-–—])\s*(?:aber\s+)?"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:(?:in|bei)\s+)?"
        r"(?!(?:arbeite|studiere|lerne|schlafe|besuche|reise|pendle)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohnte|lebte)\s+(?:(?:früher|frueher|vorher|damals)\s+)?"
        r"(?:in|bei)\s+[^,.;!?]{1,80}(?:,|;|[-–—])\s*(?:aber\s+)?"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+zwar\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        rf"aber\s+(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        rf"(?:aber\s+)?(?:{_RESIDENCE_TIME_QUALIFIER}\s+)(?:ich\s+)?(?:wohne|lebe)\s+"
        rf"(?:ich\s+)?(?:aber\s+)?(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80}\s+und\s+"
        r"(?:ich\s+)?(?:wohne|lebe)\s+(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+wohne|ich\s+lebe)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+(?:in|bei)\s+[^,.;!?]{{1,80}}?"
        r"(?:,|;|[-–—])\s*(?:(?:sondern|aber)\s+)?"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)?\s*(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+wohne|ich\s+lebe)\s+"
        r"(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+(?:in|bei)\s+[^,.;!?]{1,80}?\s+"
        r"(?:sondern|aber|doch|jedoch)\s+(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)?\s*"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80}?"
        r"(?:,|;|[-–—])\s*(?:aber\s+)?(?:jetzt|nun|aktuell|derzeit|"
        r"inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80}(?:,|;|[-–—])\s*"
        r"(?:doch|jedoch)\s+(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:ich\s+)?(?:wohne|lebe)\s+(?:aber\s+)?"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+"
        r"(?:in|bei)\s+[^,.;!?]{1,80}?"
        r"(?:\s*(?:,|;|[-–—])\s*|\s+)"
        r"(?:sondern|aber|doch|jedoch)\s+"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)?\s*"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?bin\s+umgezogen\s+von\s+[^,.;!?]{1,80}\s+nach\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?bin\s+(?:von|aus)\s+[^,.;!?]{1,80}\s+nach\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:gezogen|umgezogen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?bin\s+von\s+[^,.;!?]{1,80}\s+nach\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+gezogen\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?bin\s+(?:nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+gezogen\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?bin\s+(?:nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+umgezogen\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?zog\s+(?:von|aus)\s+[^,.;!?]{1,80}\s+nach\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?bin\s+(?:von|aus)\s+[^,.;!?]{1,80}\s+nach\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:gezogen|umgezogen|gewechselt|weggezogen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?habe\s+(?:meinen|den)\s+(?:wohnort|wohnsitz)\s+von\s+"
        r"[^,.;!?]{1,80}\s+nach\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+verlegt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+wurde\s+(?:(?:nach|in|zu)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+verlegt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+"
        r"(?:änderte|aenderte)\s+sich\s+(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+hat\s+sich\s+(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:geändert|geaendert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?habe\s+(?:meinen|den)\s+(?:wohnort|wohnsitz)\s+(?:nach|in|zu)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+verlegt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+wohne|ich\s+lebe)\s+nicht\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:(?:sondern|aber)\s+)?(?:jetzt\s+|nun\s+|aktuell\s+|derzeit\s+|inzwischen\s+|mittlerweile\s+|seitdem\s+)?"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:nicht\s+mehr|nicht\s+l(?:aenger|änger))\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:(?:sondern|aber)\s+)?(?:jetzt\s+|nun\s+|aktuell\s+|derzeit\s+|inzwischen\s+|mittlerweile\s+|seitdem\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:nicht\s+mehr|nicht\s+l(?:aenger|änger))(?:\s*,)?\s+"
        r"(?:jetzt|nun|aktuell|derzeit)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
)
CITY_PATTERNS = (
    re.compile(
        rf"\b(?:mein(?:e)?\s+)?{_PRIMARY_RESIDENCE_LABEL}"
        rf"(?:\s+(?:ist|liegt|befindet\s+sich|bleibt)\s*|:\s*)(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich\s+)?habe\s+(?:meinen|den)\s+{_PRIMARY_RESIDENCE_LABEL}\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?habe\s+meinen\s+(?:festen|ständigen|staendigen|permanenten)\s+"
        r"(?:wohnort|wohnsitz|hauptwohnsitz)\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bwir\s+(?:wohnen|leben)\s+(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?"
        rf"(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_RESIDENCE_TIME_QUALIFIER}\s+(?:wohnen|leben)\s+wir\s+"
        rf"(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?wir\s+sind\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+wohnhaft\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?sind\s+wir\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+wohnhaft\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwir\s+haben\s+unseren\s+(?:wohnort|wohnsitz|hauptwohnsitz)\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zu\s+hause|zuhause|daheim|{_PRIMARY_RESIDENCE_LABEL})\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung|stadt)(?:\s+von)?|im\s+raum|nahe|unweit\s+von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:(?:aktuell(?:er|e)?|jetzig(?:er|e)|derzeitig(?:er|e)?|gegenwärtig(?:er|e)?)\s+)?"
        rf"(?:wohnort|wohnsitz|wohnstadt|stadt|ort)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:zu\s+hause|zuhause|daheim)\s+"
        rf"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+ist\s+"
        r"mein(?:e)?\s+(?:wohnort|wohnsitz|stadt|ort|zuhause)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich\s+)?bin\s+(?:ich\s+)?"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohnhaft|ansässig|ansaessig)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:(?:aktuell(?:er|e)?|jetzig(?:er|e)|derzeitig(?:er|e)?|gegenwärtig(?:er|e)?)\s+)?"
        rf"(?:wohnort|wohnsitz|wohnstadt|stadt|ort)(?:\s+(?:ist|heisst|heißt|bleibt)\s*|:\s*)"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?habe\s+meinen\s+(?:wohnort|wohnsitz)\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?bin\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+wohnhaft\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:zu\s+hause|zuhause|daheim)"
        rf"(?:\s+(?:ist|liegt|befindet\s+sich|bleibt)\s*|:\s*)(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?"
        rf"(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:zu\s+hause|zuhause|daheim)\s+bin\s+(?:ich\s+)?in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich\s+)?bin\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?(?:ich\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:zu\s+hause|zuhause)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich\s+)?(?:wohn(?:e)?|lebe)\s+"
        rf"(?:ich\s+)?(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?bei\s+[^,.;!?]{{1,80}}\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmein(?:e)?\s+(?:(?:aktuell(?:er|e)?|jetzig(?:er|e)|derzeitig(?:er|e)?|gegenwärtig(?:er|e)?)\s+)?"
        rf"(?:wohnort|wohnstadt|stadt|ort)(?:\s+(?:ist|heisst|heißt|bleibt)\s*|:\s*)"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+wohne|ich\s+lebe|wohn(?:e)?|lebe)\s+"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung|gegend)\s+von|in\s+der\s+stadt|im\s+raum|rund\s+um|nahe|unweit\s+von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich\s+)?(?:wohn(?:e)?|lebe)\s+"
        rf"(?:ich\s+)?(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:zwar\s+)?(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+wohne|ich\s+lebe|wohn(?:e)?|lebe)\s+"
        r"(?:(?:jetzt|aktuell|derzeit)\s+)?(?:zwar\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:meine\s+stadt|mein\s+wohnort|mein\s+ort)\s+(?:ist|heisst|heißt)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})", re.IGNORECASE),
)
CITY_TRAILING_STOP_RE = re.compile(
    r"\s+(?:und|aber|weil|wenn|falls|seit|schon|mit|bei|in|auf|neben|nahe|"
    r"innerhalb|au(?:ßerhalb|sserhalb)|unter|aus|wegen|als|im|"
    r"am\s+(?:stadtrand|see|bahnhof|fluss|rand)|f(?:ür|uer)|"
    r"w(?:ährend|aehrend)|zusammen|obwohl|wobei|denn|da|dort|[-–—]|"
    r"heute|morgen|gestern|gerade|aktuell|jetzt|nun|momentan|derzeit|"
    r"zurzeit|zur\s+zeit|weiterhin|inzwischen|mittlerweile|dauerhaft|"
    r"permanent|ständig|staendig|vor(?:uebergehend|übergehend)|"
    r"frueh|früh|morgens|vormittags|mittags|nachmittags|abends|nachts|\.|,|;|:|!|\?).*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WeatherContextResult:
    city: str = ""
    weather_text: str = ""
    checked: bool = False
    skipped_reason: str = ""


WeatherProvider = Callable[[str], str]


def update_city_and_weather_context(
    account_store: AccountStore,
    account_id: str,
    text: str,
    *,
    now: datetime | None = None,
    provider: WeatherProvider | None = None,
) -> WeatherContextResult:
    if not account_id:
        return WeatherContextResult(skipped_reason="missing_account")
    with account_store.account_memory_lock(account_id):
        return _update_city_and_weather_context_unlocked(
            account_store,
            account_id,
            text,
            now=now,
            provider=provider,
        )


def _update_city_and_weather_context_unlocked(
    account_store: AccountStore,
    account_id: str,
    text: str,
    *,
    now: datetime | None = None,
    provider: WeatherProvider | None = None,
) -> WeatherContextResult:
    resolved_now = _aware(now or datetime.now(timezone.utc))
    state = account_store.read_agent_state(account_id)
    weather_state = _ensure_weather_state(state)
    city = extract_residence_city(text)
    city_changed = False
    if city:
        previous_city = str(weather_state.get("city") or "").strip()
        city_changed = _city_comparison_key(city) != _city_comparison_key(previous_city)
        if not city_changed:
            city = previous_city
        weather_state["city"] = city
        weather_state["city_updated_at"] = resolved_now.isoformat(timespec="seconds")
        if city_changed:
            # A cached summary belongs to the previous city and must not be
            # presented as current weather while the global check window is active.
            weather_state["summary"] = ""
            weather_state["last_error"] = ""
        _append_city_memory(account_store, account_id, city, resolved_now)
    current_city = str(weather_state.get("city") or "").strip()
    if not current_city:
        account_store.write_agent_state(account_id, state) if city else None
        return WeatherContextResult(skipped_reason="no_city")
    last_checked = _parse_datetime(str(weather_state.get("last_checked_at") or ""))
    elapsed_since_check = resolved_now - last_checked if last_checked is not None else None
    if not city_changed and elapsed_since_check is not None and timedelta(0) <= elapsed_since_check < WEATHER_CHECK_INTERVAL:
        return WeatherContextResult(
            city=current_city,
            weather_text=str(weather_state.get("summary") or "").strip(),
            skipped_reason="rate_limited",
        )
    weather_provider = provider or fetch_weather_summary
    try:
        summary = weather_provider(current_city).strip()
    except Exception as exc:
        weather_state["summary"] = ""
        weather_state["last_error"] = f"{type(exc).__name__}: {exc}"[:240]
        weather_state["last_checked_at"] = resolved_now.isoformat(timespec="seconds")
        account_store.write_agent_state(account_id, state)
        return WeatherContextResult(city=current_city, checked=True, skipped_reason="weather_error")
    weather_state["summary"] = summary[:500]
    weather_state["last_checked_at"] = resolved_now.isoformat(timespec="seconds")
    weather_state["last_error"] = ""
    weather_state["updated_at"] = utc_now()
    account_store.write_agent_state(account_id, state)
    return WeatherContextResult(city=current_city, weather_text=weather_state["summary"], checked=True)


def _append_city_memory(account_store: AccountStore, account_id: str, city: str, now: datetime) -> None:
    memory_id = f"mem_residence_city_{_city_id_token(city)}"
    try:
        rows = account_store.read_memory_entries(account_id)
        has_current_memory = any(
            str(entry.get("id") or "").strip() == memory_id
            for entry in rows
            if isinstance(entry, Mapping)
        )
        entry = {
            "id": memory_id,
            "created_at": now.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
            "kind": "biographical_fact",
            "memory_type": "semantic",
            "importance": 4,
            "user_text": f"User erwaehnt als Wohnstadt: {city}.",
            "bot_text": "Als Wohnort fuer Wetter- und Kontextchecks gemerkt.",
            "keywords": ["wohnort", "stadt", city.casefold()],
        }
        obsolete_rows = [
            row
            for row in rows
            if isinstance(row, Mapping)
            and str(row.get("id") or "").strip().startswith("mem_residence_city_")
            and str(row.get("id") or "").strip() != memory_id
        ]
        if not obsolete_rows:
            if has_current_memory:
                return
            account_store.append_structured_memory_entry(account_id, entry)
            return
        previous_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
        previous_index = account_store.read_memory_index(account_id)
        retained_rows = [
            dict(row)
            for row in rows
            if not (
                isinstance(row, Mapping)
                and str(row.get("id") or "").strip().startswith("mem_residence_city_")
                and str(row.get("id") or "").strip() != memory_id
            )
        ]
        try:
            account_store.write_memory_entries(account_id, retained_rows)
            account_store.rebuild_structured_memory_index(account_id)
            if not has_current_memory:
                account_store.append_structured_memory_entry(account_id, entry)
        except Exception:
            account_store.write_memory_entries(account_id, previous_rows)
            account_store.write_memory_index(account_id, previous_index)
            raise
    except Exception:
        return


def weather_context_text(account_store: AccountStore, account_id: str) -> str:
    state = account_store.read_agent_state(account_id)
    weather_state = state.get("weather_context")
    if not isinstance(weather_state, Mapping):
        return ""
    city = str(weather_state.get("city") or "").strip()
    summary = str(weather_state.get("summary") or "").strip()
    checked_at = str(weather_state.get("last_checked_at") or "").strip()
    last_error = str(weather_state.get("last_error") or "").strip()
    if not city or not summary or last_error:
        return ""
    return f"Stadt/Wohnort: {city}\nLetzter Wettercheck: {checked_at or 'unbekannt'}\nKurz-Wetter: {summary}"


def extract_residence_city(text: str) -> str:
    source = str(text or "")
    for pattern in CITY_CHANGE_PATTERNS:
        match = pattern.search(source)
        if not match:
            continue
        if _has_unresolved_location_separator(source, match.end("city")):
            return ""
        city = _clean_city(match.group("city"))
        if city:
            return city
    if _has_ambiguous_residence_targets(source):
        return ""
    for pattern in CITY_PATTERNS:
        match = pattern.search(source)
        if not match:
            continue
        if _has_unresolved_location_separator(source, match.end("city")):
            return ""
        city = _clean_city(match.group("city"))
        if city:
            return city
    return ""


def _has_ambiguous_residence_targets(source: str) -> bool:
    residence = r"(?:wohne|wohnen|lebe|leben|wohn|leb)"
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
        rf"(?:(?:ich\s+)?{residence}\s+)?(?:in|bei)\s+",
        source,
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
            r"(?!bin\b|sind\b|sein\b|arbeit\w*\b|studier\w*\b|lern\w*\b|"
            r"schlaf\w*\b|mach\w*\b|komm\w*\b|fahr\w*\b|geh\w*\b|"
            r"hab\w*\b|besuch\w*\b|verbring\w*\b|treff\w*\b|reis\w*\b|"
            r"pendl\w*\b|seh\w*\b|übernacht\w*\b|uebernacht\w*\b)[\wÄÖÜäöüß'-]+",
            source,
            re.IGNORECASE,
        )
    )


def _has_unresolved_location_separator(source: str, city_end: int) -> bool:
    tail = source[city_end:]
    boundary = re.search(r"[.!?;\n]", tail)
    segment = tail if boundary is None else tail[: boundary.start()]
    return bool(
        re.match(
            r"\s*(?:/|&)\s*(?!arbeite\b|studiere\b|lerne\b|schlafe\b|"
            r"besuche\b|reise\b|pendle\b|fahre\b|gehe\b|komme\b|"
            r"habe\b|bin\b|mein(?:e)?\b|der\b|die\b|das\b)[A-ZÄÖÜäöüß]",
            segment,
            re.IGNORECASE,
        )
    )


def fetch_weather_summary(city: str) -> str:
    query = urllib.parse.quote(str(city or "").strip())
    if not query:
        return ""
    url = f"https://wttr.in/{query}?format=j1"
    request = urllib.request.Request(url, headers={"User-Agent": "TeeBotus/1 weather context"})
    with urllib.request.urlopen(request, timeout=WEATHER_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    current = payload.get("current_condition", [{}])[0]
    area = payload.get("nearest_area", [{}])[0]
    name = _area_name(area) or city
    temp = str(current.get("temp_C") or "").strip()
    feels = str(current.get("FeelsLikeC") or "").strip()
    desc_values = current.get("weatherDesc") if isinstance(current.get("weatherDesc"), list) else []
    desc = str(desc_values[0].get("value") or "").strip() if desc_values and isinstance(desc_values[0], Mapping) else ""
    humidity = str(current.get("humidity") or "").strip()
    wind = str(current.get("windspeedKmph") or "").strip()
    parts = [name]
    if temp:
        parts.append(f"{temp} C")
    if feels and feels != temp:
        parts.append(f"gefuehlt {feels} C")
    if desc:
        parts.append(desc)
    if humidity:
        parts.append(f"Luftfeuchte {humidity}%")
    if wind:
        parts.append(f"Wind {wind} km/h")
    return ", ".join(parts)


def _ensure_weather_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("schema_version", 1)
    weather_state = state.setdefault("weather_context", {})
    if not isinstance(weather_state, dict):
        weather_state = {}
        state["weather_context"] = weather_state
    weather_state["schema_version"] = WEATHER_CONTEXT_SCHEMA_VERSION
    return weather_state


def _clean_city(value: str) -> str:
    source = str(value or "")
    if re.search(r"(?i)\s+(?:oder|sowie|bzw\.?|beziehungsweise)\s+", source):
        return ""
    city = CITY_TRAILING_STOP_RE.sub("", source).strip(" .,:;!?")
    city = re.sub(r"\s+", " ", city)
    city = re.split(r"(?<!\bSt)[.!?]\s+", city, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,:;!?")
    city = re.sub(r"(?i)^(?:in|bei)\s+", "", city)
    if not city or len(city) > MAX_CITY_LENGTH:
        return ""
    if any(char.isdigit() for char in city):
        return ""
    if re.match(
        r"(?i)^(?:der|die|das|den|dem|des|dies(?:er|e|es)|jen(?:er|e|es)|"
        r"welch(?:er|e|es)|irgendein|mehrere|einige|manche|hier|dort|da)\b",
        city,
    ):
        return ""
    if re.match(
        r"(?i)^(?:nahe|innerhalb|außerhalb|ausserhalb|unter|aus|f(?:ür|uer)|"
        r"wegen|als|neben|mit|w(?:ährend|aehrend)|zusammen|auf|am|im)\b",
        city,
    ):
        return ""
    if re.search(r"(?i)\b(?:nicht(?:\s+mehr)?|kein(?:e|er|em|en)?|mein(?:e|er|em|en)?|ein(?:e|er|em|en)?)\b", city):
        return ""
    return city


def _city_id_token(city: str) -> str:
    normalized = re.sub(r"\s+", "_", city.strip().casefold())
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
    return normalized[:48] or hashlib.sha256(city.encode("utf-8")).hexdigest()[:16]


def _city_comparison_key(city: str) -> str:
    return re.sub(r"\s+", " ", str(city or "").strip()).casefold()


def _area_name(area: Mapping[str, Any]) -> str:
    values = area.get("areaName")
    if isinstance(values, list) and values and isinstance(values[0], Mapping):
        return str(values[0].get("value") or "").strip()
    return ""


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
