from __future__ import annotations

import json
import hashlib
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from TeeBotus.runtime.accounts import AccountStore

WEATHER_CONTEXT_SCHEMA_VERSION = 1
WEATHER_CHECK_INTERVAL = timedelta(hours=2)
WEATHER_TIMEOUT_SECONDS = 2.5
MAX_CITY_LENGTH = 80
_NON_CITY_RESIDENCE_NAMES = frozenset(
    {
        "deutschland",
        "österreich",
        "oesterreich",
        "schweiz",
        "frankreich",
        "italien",
        "spanien",
        "polen",
        "tschechien",
        "niederlande",
        "belgien",
        "luxemburg",
        "großbritannien",
        "grossbritannien",
        "vereinigtes königreich",
        "vereinigte staaten",
        "kanada",
        "japan",
        "amerika",
        "ausland",
        "inland",
        "europa",
        "afrika",
        "asien",
        "australien",
        "welt",
    }
)
_NON_CITY_CONTEXT_TOKENS = frozenset(
    {
        "heute",
        "gestern",
        "morgen",
        "jetzt",
        "nun",
        "aktuell",
        "derzeit",
        "momentan",
        "gerade",
        "inzwischen",
        "mittlerweile",
        "seit",
        "damals",
        "früher",
        "frueher",
        "nächstes jahr",
        "naechstes jahr",
        "nächstem jahr",
        "naechstem jahr",
        "kommendes jahr",
        "kommenden jahr",
        "zukunft",
        "nie",
        "künftig",
        "kuenftig",
        "zukünftig",
        "zukuenftig",
        "demnächst",
        "demnaechst",
        "bald",
        "januar",
        "februar",
        "märz",
        "maerz",
        "april",
        "mai",
        "juni",
        "juli",
        "august",
        "september",
        "oktober",
        "november",
        "dezember",
        "geplant",
        "vielleicht",
        "vermutlich",
        "angeblich",
        "bitte",
        "fast",
        "beinahe",
        "möglicherweise",
        "moeglicherweise",
        "irgendwo",
        "unklar",
        "egal",
        "daheim",
        "zuhause",
        "zu hause",
        "lautet",
        "überall",
        "ueberall",
        "wechselnd",
        "variabel",
        "flexibel",
        "offen",
        "mobil",
        "temporär",
        "temporaer",
        "region",
        "freunden",
        "freundinnen",
        "bekannten",
        "verwandten",
        "kollegen",
        "kolleginnen",
        "eltern",
        "familie",
        "partner",
        "partnerin",
        "partnern",
        "gemeinsam",
    }
)
_NON_CITY_REGION_NAMES = frozenset(
    {
        "brandenburg",
        "bayern",
        "hessen",
        "sachsen",
        "sachsen-anhalt",
        "thueringen",
        "thüringen",
        "nordrhein-westfalen",
        "baden-württemberg",
        "baden-wuerttemberg",
        "rheinland-pfalz",
        "saarland",
        "schleswig-holstein",
        "mecklenburg-vorpommern",
        "niedersachsen",
        "norddeutschland",
        "süddeutschland",
        "sueddeutschland",
        "westdeutschland",
        "ostdeutschland",
        "mitteldeutschland",
        "ruhrgebiet",
        "rheinland",
    }
)
_IRREGULAR_CITY_ADJECTIVE_BASES = {
    "brem": "Bremen",
    "dresdn": "Dresden",
    "münchn": "München",
}
_KNOWN_COMPOUND_CITY_NAMES = {
    "brandenburg an der havel": "Brandenburg an der Havel",
    "frankfurt an der oder": "Frankfurt an der Oder",
    "königstein im taunus": "Königstein im Taunus",
    "ludwigshafen am rhein": "Ludwigshafen am Rhein",
    "mülheim an der ruhr": "Mülheim an der Ruhr",
    "rüdesheim am rhein": "Rüdesheim am Rhein",
    "halle (saale)": "Halle (Saale)",
    "st. georgen im schwarzwald": "St. Georgen im Schwarzwald",
    "wörth am rhein": "Wörth am Rhein",
}
_GENITIVE_CITY_REPAIRS = {
    "pari": "Paris",
    "reim": "Reims",
    "worm": "Worms",
    "tour": "Tours",
    "canne": "Cannes",
    "len": "Lens",
}
_CITY_AREA_SUFFIXES = (
    "stadtmitte",
    "stadtrand",
    "innenstadt",
    "altstadt",
    "zentrum",
    "mitte",
    "stadt",
)
_RESIDENCE_DURATION = (
    r"(?:(?:mehr\s+als|über|ueber|knapp|gut|etwa|ungefähr|ungefaehr|"
    r"fast|circa|ca\.|rund|mindestens|hoechstens|höchstens)\s+)?"
    r"(?:\d{4}|kurzem|kurzer\s+zeit|einiger\s+zeit|jeher|"
    r"(?:dem\s+)?(?:letzten|letztem|vergangenen|vergangenem|aktuellen|aktuellem|diesem)\s+(?:jahr|sommer|winter)|"
    r"(?:meiner\s+)?(?:kindheit|jugend|geburt)|(?:dem|meinem|meiner)\s+"
    r"(?:(?:letzten|letztem|vergangenen|vergangenem|ersten)\s+)?"
    r"(?:studium|umzug|einzug|ausbildung|lehre)|"
    r"(?:(?:dem|der)\s+)?(?:beginn|ende|abschluss)\s+"
    r"(?:(?:meines|meiner|des|der)\s+)?(?:studiums|ausbildung|lehre)|"
    r"(?:dem|meinem)\s+ersten\s+tag|"
    r"(?:januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember)(?:\s+\d{4})?|"
    r"(?:dem\s+)?(?:(?:anfang|ende|mitte|beginn|letzte[rnm]?|dies(?:e[mr]?|en)|vergangen(?:e[rnm]?))\s+)?"
    r"(?:\d{1,2}\.\s+)?(?:januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember)(?:\s+\d{4})?|"
    r"(?:anfang|ende|mitte|beginn)\s+\d{4}|"
    r"(?:dem\s+)?\d{1,2}\.\d{1,2}\.(?:\d{2,4})?|"
    r"(?:dem\s+)?(?:sommer|winter|frühling|fruehling|herbst|weihnachten|ostern|neujahr)|"
    r"(?:(?:ein\s+paar|\w+)\s+(?:tag(?:e|en)?|woche(?:n)?|monat(?:e|en)?|jahr(?:e|en)?)|"
    r"tag(?:e|en)?|woche(?:n)?|monat(?:e|en)?|jahr(?:e|en)?))"
)
_RESIDENCE_TIME_QUALIFIER = (
    rf"(?:(?:schon\s+)?seit\s+{_RESIDENCE_DURATION}|schon\s+lange|seitdem|"
    r"(?:schon\s+)?seit\s+(?:gestern|heute|vorgestern)|jetzt|nun|nunmehr|aktuell|derzeit|gerade|grad|momentan|inzwischen|mittlerweile|zurzeit|zur\s+zeit|"
    r"weiterhin|nach\s+wie\s+vor|noch\s+immer|immer\s+noch|"
    rf"dauerhaft|permanent|langfristig|kurzfristig|befristet|unbefristet|vorläufig|vorlaeufig|"
    rf"ständig|staendig|wieder|erneut|für\s+{_RESIDENCE_DURATION}|"
    r"zur\s+(?:miete|untermiete|zwischenmiete)|"
    r"bis\s+(?:auf\s+weiteres|zum\s+ende\s+(?:des\s+)?(?:monats|jahres)|"
    r"ende\s+(?:des\s+)?(?:monats|jahres)|(?:monats|jahres)ende)|"
    r"vor(?:uebergehend|übergehend))"
)
_RESIDENCE_LOCATION_ADVERB = (
    r"(?:(?:hier|dort|da|direkt|nur|allein|überwiegend|ueberwiegend|"
    r"hauptsächlich|hauptsaechlich|vorwiegend|meistens|irgendwo|dahoam|erst|immer|"
    r"bisher|bislang|vorerst|zeitweise)|"
    r"(?:sicher|wirklich|definitiv|tatsächlich|tatsaechlich))"
)
_RESIDENCE_DISTANCE_PREFIX = (
    r"(?:(?:ungefähr|ungefaehr|ca\.?|circa|etwa|rund|knapp)\s+)?"
    r"(?:\d+(?:[,.]\d+)?|ein(?:e|en)?|ein\s+paar|mehrere|wenige)\s*"
    r"(?:km|kilometer)\s+"
)
_PRIMARY_RESIDENCE_LABEL = r"(?:lebensmittelpunkt|hauptwohnsitz)"

CITY_CHANGE_PATTERNS = (
    re.compile(
        r"\b[^,.;!?]{1,80}\s+nicht\s*,\s+sondern\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+(?!(?:ist|war|bleibt|wird)\b)"
        r"[\wÄÖÜäöüß'-]+){0,6})"
        r"(?:\s+ist)?(?=\s+(?:mein|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[^,.;!?]{1,80}\s+(?:ist|war)\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:frühere|fruehere|ehemalige|alte)\s+)?"
        r"(?:heimat|heimatstadt|herkunftsort|herkunftsstadt|geburtsort|geburtsstadt)\s*,\s*"
        r"(?:dort|da)\s+(?:wohne|lebe)\s+(?:ich|wir)\s+nicht\s*,?\s+"
        r"sondern\s+(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\)),\s*"
        r"(?:dort|da|daheim|zuhause|zu\s+hause)?\s*(?:bin|wohne|lebe)\s+(?:ich|wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))\s+ist\s+"
        r"(?:dort|da)\s*,?\s*wo\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:keinesfalls|keineswegs|niemals|nirgendwo|nirgends|nie)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}?,\s*sondern\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:manchmal|gelegentlich|oft|häufig|haeufig|selten)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80},\s*(?:aber\s+)?"
        r"(?:meist\w*|hauptsächlich|hauptsaechlich|überwiegend|ueberwiegend|"
        r"vorwiegend|mehrheitlich|in\s+der\s+regel)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?!(?:ich|wir|wohne|wohnen|lebe|leben|arbeite|arbeiten|studiere|studieren|lerne|lernen)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,\s*(?:"
        r"(?:daheim|zuhause|zu\s+hause)\s+(?:bin|wohne|lebe)\s+(?:ich|wir)|"
        r"(?:dort|da)\s+(?:wohne|lebe)\s+(?:ich|wir)|"
        r"(?:dort|da)\s+bin\s+(?:ich|wir)\s+(?:daheim|zuhause|zu\s+hause))(?=\s*[.!?;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:arbeite|arbeiten|studiere|studieren|lerne|lernen)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,?\s*wo\s+"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:arbeite|arbeiten|studiere|studieren|lerne|lernen)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,?\s*(?:dort|da)\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:dort|da)\s*,?\s*wo\s+"
        r"(?:ich|wir)\s+(?:arbeite|arbeiten|studiere|studieren|lerne|lernen)\s*:?[ \t]*(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:komm(?:e|en)|stamm(?:e|en))\s+aus\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*"
        r"(?:und\s+|,\s*(?:aber\s+)?)"
        r"(?:(?:wohne|wohnen|lebe|leben)\s+(?:aber\s+)?dort(?:\s+(?:weiterhin|immer\s+noch))?|"
        r"(?:bin|sind)\s+dort\s+(?:wohnhaft|ansässig|ansaessig))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+ist\s*,?\s*"
        r"wo\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwo\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s*,?\s*ist\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+ist\s+"
        r"(?:die\s+stadt|der\s+ort)\s*,?\s*(?:in\s+(?:der|dem)\s+|wo\s+)"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+ist\s+"
        r"(?:dort|da)\s*,?\s*wo\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+habe\s+[^,.;!?]{1,80}\s+als\s+"
        r"(?:geburtsort|geburtsstadt)\s+und\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+als\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|hauptwohnsitz)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:geburtsort|geburtsstadt)\s*[:=]?\s*[^,.;!?]{1,80}[,;]\s*"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|hauptwohnsitz)\s*[:=]?\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wechselte|wechselten|wechsle|wechseln)\s+(?:von|aus)\s+"
        r"[^,.;!?]{1,80}\s+(?:nach|zu|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei)\s+[^,.;!?]{1,80}\s+nach\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:gezogen|umgezogen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohnte|wohnten|lebte|lebten)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:wohne|wohnen|lebe|leben|bin|sind)\s+(?:aber\s+)?"
        r"(?:(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+)?"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+war(?:en)?\s+(?:in|bei)\s+[^,.;!?]{1,80}\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet),\s*(?:aber\s+)?"
        r"(?:wohne|wohnen|lebe|leben|bin|sind)\s+(?:aber\s+)?"
        r"(?:(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+)?"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)\s+war\s+"
        r"[^,.;!?]{1,80},\s*(?:aber\s+)?(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:(?:ist|liegt|befindet\s+sich)\s+)?(?:es|er|sie)?\s*(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+(?:aber\s+)?"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber|doch|jedoch)\s+(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+ist\s+nicht(?:\s+mehr)?\s+mein(?:e)?\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)"
        r"\s*,?\s*sondern\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohnte|wohnten|lebte|lebten)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80},\s*(?:bin|sind)\s+(?:aber\s+)?"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:habe|haben|hab)\s+(?:in|bei)\s+[^,.;!?]{1,80}\s+"
        r"(?:gewohnt|gelebt),\s*(?:bin|sind)\s+(?:aber\s+)?"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:habe|haben|hab)\s+(?:in|bei)\s+[^,.;!?]{1,80}\s+"
        r"(?:gewohnt|gelebt),\s*(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+war\s+"
        r"(?:(?:früher|frueher|ehemals|damals)\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)"
        r"\s*,\s*(?:aber\s+)?(?:ich|wir)\s+(?:bin|sind)\s+"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+war\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)"
        r"\s*,\s*(?:aber\s+)?(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:bin|sind|wohne|wohnen|lebe|leben)\s+(?:ich|wir)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+war\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)"
        r"\s+und\s+(?:aber\s+)?(?:ich|wir)\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+)?nicht\s+mehr\s+"
        r"(?:in|bei)\s+[^,.;!?]{1,80},\s*sondern\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:früher|frueher|ehemals|damals)\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}[,;]\s*(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohnte|wohnten|lebte|lebten)\s+(?:in|bei)\s+[^.!?]{1,80}[.!?]\s*"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+ist\s+nicht(?:\s+mehr)?\s+mein(?:e)?\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)"
        r"\s*[.!?;]\s*(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:früher|frueher|ehemals|damals)\s+war\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?|"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+war)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)\s*"
        r"(?:,|;|[-–—]|[.!?])\s*(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:(?:ist|liegt|befindet\s+sich|bleibt)(?:\s+(?:er|sie|es))?\s+)?"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+war(?:en)?\s+(?:in|bei)\s+[^,.;!?]{1,80}\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s*,\s*"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))|"
        r"(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)))\s+"
        r"(?:(?:kurz|direkt|knapp|etwa|ungefähr|ungefaehr)\s+)?(?:vor|hinter)\s+"
        r"(?:der\s+stadt\s+)?(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+)"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:geboren\s+(?:wurde\s+)?(?:(?:ich|wir)\s+)?)|"
        r"(?:(?:ich|wir)\s+wurde(?:n)?\s+))"
        r"(?:in|bei)\s+[^,.;!?]{1,80}?\s*(?:geboren\s+)?(?:,|und)\s*"
        r"(?:lebe|wohne|wohnen|leben)\s+(?:(?:ich|wir)\s+)?"
        r"(?:heute|jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)?\s*"
        r"(?:aber\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)nicht\s+(?:in\s+|bei\s+)?[^,.;!?]{1,80}?,\s*sondern\s+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:ist|bleibt)\s+(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+war\s+[^,.;!?]{1,80}?(?:[.!?;,]|[-–—])\s*"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+"
        r"(?:(?:bin|wohne|lebe)\s+(?:ich|wir)\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:früher|frueher|ehemals|damals)\s+(?:wohnte|lebte)\s+(?:ich|wir)\s+"
        r"[^,.;!?]{1,80}?(?:[.!?;,]|[-–—])\s*"
        r"(?:heute|jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+"
        r"(?:(?:(?:wohne|lebe)\s+(?:ich|wir)\s+)?(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*lebensmittelpunkt\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:in\s+der|im)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:region|gegend|gebiet)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*lebensmittelpunkt\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+au(?:ßerhalb|sserhalb)\s+"
        r"(?:der\s+stadt\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:eine|einer|die|der)\s+stadt,?\s+die\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:heißt|heisst)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+in\s+"
        r"(?:einer|der)\s+stadt,?\s+die\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:heißt|heisst)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+nenn(?:t|en)\s+sich\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+"
        r"(?:im\s+zentrum|in\s+der\s+innenstadt)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+"
        r"(?:im\s+zentrum|in\s+der\s+innenstadt)\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\s+(?:zentrum|innenstadt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:zentrum|innenstadt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+am\s+stadtrand\s+"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+am\s+stadtrand\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+"
        r"au(?:ßerhalb|sserhalb)\s+(?:(?:der|des)\s+stadt\s+)?"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?!von\s+)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s(?=\s*(?:[.!?;,]|$|"
        r"\b(?:und|aber|doch|jedoch)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+"
        r"au(?:ßerhalb|sserhalb)\s+(?:(?:der|des)\s+stadt\s+)?"
        r"(?!von\s+)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$|"
        r"\b(?:und|aber|doch|jedoch)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+in\s+der\s+stadtmitte\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+in\s+der\s+stadtmitte\s+"
        r"(?:von\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+innerhalb\s+"
        r"(?:(?:des\s+stadtgebiets?|der\s+stadt)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s(?=\s*(?:[.!?;,]|$|"
        r"\b(?:und|aber|doch|jedoch)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+innerhalb\s+"
        r"(?:(?:des\s+stadtgebiets?|der\s+stadt)\s+)?(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$|"
        r"\b(?:und|aber|doch|jedoch)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+(?:im|in\s+dem|in\s+der|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:stadtgebiet|stadtteil|bezirk|innenstadt|stadtmitte|stadtrand|rand|vorstadt|vorort|"
        r"umland|stadtzentrum|zentrum|raum|region|gebiet)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+im\s+stadtgebiet\s+von\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben))\s+im\s+stadtgebiet\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|war)|"
        r"(?:ich|wir)\s+(?:wohne|wohnen|wohnte|wohnten|lebe|leben|lebte|lebten))\s+"
        r"[^,.;!?]{1,80}?(?:,|;|[-–—])\s*(?:aber|doch|jedoch)?\s*"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)?\s*"
        r"(?:in\s+der|im|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er\s+(?:raum|umgebung|nähe)|-\s*nähe)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+der|im|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er\s+(?:raum|umgebung|nähe)|-\s*nähe)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"im\s+(?:nördlichen|südlichen|östlichen|westlichen|nord[-\s]?östlichen|"
        r"nord[-\s]?westlichen|süd[-\s]?östlichen|süd[-\s]?westlichen)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+im\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:norden|süden|osten|westen|nord[-\s]?osten|nord[-\s]?westen|"
        r"süd[-\s]?osten|süd[-\s]?westen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"im\s+(?:norden|süden|osten|westen|nord[-\s]?osten|nord[-\s]?westen|"
        r"süd[-\s]?osten|süd[-\s]?westen)\s+"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"in\s+der\s+region\s+um\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in\s+der|im)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:region|gegend|gebiet)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+und\s+umgebung\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"in\s+der\s+region\s+um\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+der|im)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:region|gegend|gebiet)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"im\s+gebiet\s+von\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+und\s+"
        r"umgebung\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+der|im|in\s+einem|in\s+einer|in|am)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:innenstadt|stadtmitte|zentrum|stadtrand|rand|vorstadt|vorort)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+der\s+innenstadt|im\s+zentrum|am\s+rand)\s+(?:von\s+)?"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:im|in\s+der)\s+(?:stadtteil|bezirk|viertel|ortsteil|altstadt)\s+"
        r"(?:[^,.;!?]{1,80}?\s+)?(?:in|bei|von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+im\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:stadtteil|bezirk|viertel|ortsteil)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:liegt|befindet\s+sich)\s+"
        r"au(?:ßerhalb|sserhalb)\s+der\s+stadt\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,?\s+wo\s+"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,?\s+wo\s+"
        r"(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:wohnort|wohnsitz)\s*:\s*[^,.;!?]{1,100}?"
        r"(?:straße|strasse|weg|allee|gasse|platz|ufer|ring|chaussee|steig|promenade)\s+"
        r"\d+[a-z]?\s*,\s*(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:(?:im|in\s+der|in\s+einem|in\s+einer)\s+"
        r"(?:dorf|ort|gemeinde)|(?:ein(?:e|em|er)?|der|die|das)\s+gemeinde)\s+"
        r"(?:(?:namens|genannt)\s+)?(?:nahe|unweit\s+von|rund\s+um|bei)?\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|im)\s+"
        r"(?:(?:bundesland|land)\s+)?(?:brandenburg|bayern|hessen|sachsen|"
        r"sachsen-anhalt|thüringen|thueringen|nordrhein-westfalen|"
        r"baden-württemberg|baden-wuerttemberg|rheinland-pfalz|saarland|"
        r"schleswig-holstein|mecklenburg-vorpommern|niedersachsen)\s+"
        r"(?:bei|in)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in|im)\s+(?:(?:bundesland|land)\s+)?"
        r"(?:brandenburg|bayern|hessen|sachsen|sachsen-anhalt|thüringen|thueringen|"
        r"nordrhein-westfalen|baden-württemberg|baden-wuerttemberg|rheinland-pfalz|"
        r"saarland|schleswig-holstein|mecklenburg-vorpommern|niedersachsen)\s+"
        r"(?:bei|in)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:in\s+)?(?:deutschland|österreich|oesterreich|(?:der\s+)?schweiz)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+)?(?:deutschland|österreich|oesterreich|(?:der\s+)?schweiz)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:es\s+ist\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,?\s+"
        r"wo\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,?\s+(?:hier|dort|da)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+ist\s+"
        r"(?:die|der|das)\s+(?:stadt|ort|platz)\s*,?\s*"
        r"(?:in\s+der|an\s+dem|wo)\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:der|die|das)\s+(?:ort|stadt|platz)\s*,?\s*"
        r"(?:in\s+der|an\s+dem|wo)\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s*,?\s+ist\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:da|dort)\s*,?\s*wo\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s*,?\s+ist\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+nie\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}?\s*(?:,|;|[-–—])?\s*sondern\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:bin|sind)\s+(?:ich|wir)\s+(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+nenn(?:e|en)?\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"lebensmittelpunkt|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+nenn(?:e|en)?\s+"
        r"(?:ich|i)\s+(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:bei|mit|zusammen\s+mit)\s+"
        r"(?!(?:(?!\s+(?:in|bei)\s+)[^,.;!?])*\b(?:arbeit\w*|studier\w*|"
        r"studium\w*|ausbildung\w*|lern\w*)\b)"
        r"[^,.;!?]{1,80}?\s*,?\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+und\s+"
        r"(?:(?:(?:ich|wir)\s+)?(?:arbeite\w*|studier\w*|lern\w*|schlaf\w*|"
        r"besuch\w*|reis\w*|pendl\w*|fahr\w*|geh\w*|komm\w*)|"
        r"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        r"(?:arbeit|studium|ausbildung|schule)\b|"
        r"(?:(?:ich|wir)\s+)?bin\s+(?:heute|gerade|nur|unterwegs)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:bei|mit|zusammen\s+mit)\s+"
        r"(?!(?:(?!\s+(?:in|bei)\s+)[^,.;!?])*\b(?:arbeit\w*|studier\w*|"
        r"studium\w*|ausbildung\w*|lern\w*)\b)"
        r"[^,.;!?]{1,80}?\s*,?\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+und\s+"
        r"(?:(?:(?:ich|wir)\s+)?(?:arbeite\w*|studier\w*|lern\w*|schlaf\w*|"
        r"besuch\w*|reis\w*|pendl\w*|fahr\w*|geh\w*|komm\w*)|"
        r"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        r"(?:arbeit|studium|ausbildung|schule)\b|"
        r"(?:(?:ich|wir)\s+)?bin\s+(?:heute|gerade|nur|unterwegs)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+der\s+region|im\s+großraum|im\s+grossraum)\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+im\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+großraum\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:unweit|nahe)\s+(?:von\s+)?"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:unweit|nahe)\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+und\s+"
        r"(?:(?:ich|wir)\s+(?:arbeite\w*|studier\w*|lern\w*|schlaf\w*|"
        r"besuch\w*|reis\w*|pendl\w*|fahr\w*|geh\w*|komm\w*)|"
        r"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        r"(?:arbeit|studium|ausbildung|schule)\b|"
        r"(?:ich|wir)\s+bin\s+(?:heute|gerade|nur|unterwegs)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+und\s+"
        r"(?:(?:ich|wir)\s+(?:arbeite\w*|studier\w*|lern\w*|schlaf\w*|"
        r"besuch\w*|reis\w*|pendl\w*|fahr\w*|geh\w*|komm\w*)|"
        r"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        r"(?:arbeit|studium|ausbildung|schule)\b|"
        r"(?:ich|wir)\s+bin\s+(?:heute|gerade|nur|unterwegs)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:im|am)\s+(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:umland|stadtrand|rand)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"in\s+der\s+(?:nähe|naehe|umgebung|gegend)\s+"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"in\s+der\s+gegend\s+um\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+um\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+herum)?(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"ist\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]\s*"
        r"(?:war\s+)?(?:aber\s+)?(?:früher|frueher|ehemals|damals|vormalig\w*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*"
        r"(?::|=|,)?\s*[^,.;!?]{1,80}[,;]\s*"
        r"(?:(?:aber|doch|jedoch)\s+)?"
        r"(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich|"
        r"jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s*:?[ \t]+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+(?:wohne|wohn|lebe|leb)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:grad\s+|gerade\s+|jetzt\s+|nun\s+|aktuell\s+|derzeit\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+(?:wohne|wohn|lebe|leb)\s+"
        r"(?:nimmer|nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}[,;]\s*(?:sondern|aber)\s+"
        r"(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+)?"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+war\s+[^,.;!?]{1,80},\s*"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+ist\s+"
        r"(?:er|sie|es)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:sondern|aber)\s+(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:früher|frueher|ehemals|damals)\s+war\s+(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+[^.!?]{1,80}[.!?]\s*"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+ist\s+(?:er|sie|es)\s+(?:in|bei)?\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        r"(?:(?:gerade|vor\s+kurzem|vor\s+(?:\w+\s+)?(?:tag(?:en)?|woche(?:n)?|monat(?:en)?|jahr(?:en)?))\s+)?"
        r"(?:nach|in)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:gezogen|umgezogen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+[^,.;!?]{1,80}\s+und\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber|doch|jedoch|sondern|jetzt|nun|aktuell|derzeit)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:lebensmittelpunkt|hauptwohnsitz|wohnort|wohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+(?:alte|ehemalige|frühere|fruehere)\s+"
        r"(?:wohnadresse|wohnanschrift|adresse|anschrift)\s+war\s+[^,.;!?]{1,80},\s*"
        r"(?:aktuell|jetzt|nun|heute|derzeit)\s+ist\s+(?:sie\s+)?(?:in|bei)?\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse|anschrift)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+nicht\s+(?:in|bei)?\s*[^,.;!?]{1,80},\s*"
        r"(?:sondern|aber|jetzt|nun|aktuell|derzeit)\s+(?:in|bei)?\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:früher|frueher|ehemals|damals)\s+(?:wohnte|lebte)\s+(?:ich|wir)\s+"
        r"(?:in|bei)\s+[^,.;!?]{1,80},\s*(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:früher|frueher|ehemals|damals)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:jetzt|heute|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        r"(?:(?:letzten|vergangenen|diesem|vorigen|vorherigen)\s+(?:monat|jahr|woche)\s+)?"
        r"(?:nach|in)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:gezogen|umgezogen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+nach\s+"
        r"(?:dem|meinem|unserem)\s+umzug\s+(?:nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:gezogen|umgezogen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+zog(?:en)?\s+(?:nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:komm(?:e|en)|stamm(?:e|en))\s+aus\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        rf"(?:aber\s+)?(?:heute|{_RESIDENCE_TIME_QUALIFIER})?\s*"
        rf"(?:aber\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80},\s*(?:aber\s+)?(?:bin|sind)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich|wir)?\s*(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:nach\s+(?:meinem|unserem)\s+umzug\s+)?(?:ich\s+)?bin\s+ich\s+(?:nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:gezogen|umgezogen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+ist\s+nicht\s+(?:mehr\s+)?mein(?:e)?\s+"
        r"(?:(?:aktuell(?:er|e)?|jetzig(?:er|e)|derzeitig(?:er|e)?|gegenwärtig(?:er|e)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)\s*,?\s*"
        r"(?:sondern|aber|jetzt|nun|aktuell|derzeit)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+habe(?:n)?\s+mich\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:niedergelassen|angesiedelt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei|nach)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:eingezogen|sesshaft(?:\s+geworden)?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:ließ|liess|ließen|liessen)\s+mich\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+nieder\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:in|bei)\s+[^,.;!?]{1,80}[,;]\s*"
        r"(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s*:?[ \t]+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+[^,.;!?]{1,80}[,;]\s*"
        r"(?:genauer(?:\s+gesagt)?|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s*:?[ \t]+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}|seit\s+heute|heute)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"nicht(?:\s+mehr)?\s+(?:(?:in|bei)\s+)?[^,.;!?]{1,80}?"
        r"(?:\s*(?:,|;|[-–—])\s*|\s+)sondern\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
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
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?\s+)?{_PRIMARY_RESIDENCE_LABEL}\s+wurde\s+"
        r"(?:(?:von|aus)\s+[^,.;!?]{1,80}\s+(?:nach|in|zu)\s+|(?:nach|in|zu)\s+)?"
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
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?"
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
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?!\s+(?:arbeite|studiere|lerne|schlafe|besuche|reise|pendle|fahre|gehe|"
        r"komme|mache|sehe|übernach\w*|uebernach\w*)\b)"
        r"(?:\s+(?:wohne|lebe)(?:\s+(?:ich|wir))?)?"
        r"(?=\s*[.!?;,:]|$)",
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
        rf"\b(?:ich\s+)?(?:wohne|lebe)\s+(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+[^,.;!?]{{1,80}}?"
        rf"(?:,|;|[-–—])\s*(?:aber\s+)?(?:{_RESIDENCE_TIME_QUALIFIER})\s+(?:in|bei)\s+"
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
        r"\b(?:ich\s+)?habe\s+(?:meinen|den)\s+(?:wohnort|wohnsitz)\s+(?:von|aus)\s+"
        r"[^,.;!?]{1,80}\s+nach\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+verlegt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+wurde\s+"
        r"(?:(?:von|aus)\s+[^,.;!?]{1,80}\s+(?:nach|in|zu)\s+|(?:nach|in|zu)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:verlegt|verschoben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+(?:wohnort|wohnsitz|wohnstadt)\s+ist\s+"
        r"(?:(?:von|aus)\s+[^,.;!?]{1,80}\s+(?:nach|in|zu)\s+|(?:nach|in|zu)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:verlegt|verschoben)\s+worden\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+"
        r"(?:änderte|aenderte)\s+sich\s+(?:(?:von|aus)\s+[^,.;!?]{1,80}\s+)?(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+hat\s+sich\s+(?:(?:von|aus)\s+[^,.;!?]{1,80}\s+)?(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:geändert|geaendert|verändert|veraendert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt)\s+hat\s+sich\s+"
        r"(?:(?:von|aus)\s+[^,.;!?]{1,80}\s+)?(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:verlagert|verschoben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+wechselte\s+"
        r"(?:(?:von|aus)\s+[^,.;!?]{1,80}\s+)?(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+ist\s+(?:von|aus)\s+"
        r"[^,.;!?]{1,80}\s+(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+gewechselt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt)\s+verlegte\s+sich\s+(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+(?:wohnort|wohnsitz|wohnstadt)\s+verlegte\s+sich\s+"
        r"(?:von|aus)\s+[^,.;!?]{1,80}\s+(?:zu|nach|in)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
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
    re.compile(
        r"\bwir\s+(?:wohnen|leben|wohnten|lebten)\s+(?:in|bei)\s+[^,.;!?]{1,80}?"
        r"(?:[.!?]|,|;|[-–—])\s*(?:aber\s+)?"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwir\s+(?:wohnen|leben)\s+(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+"
        r"(?:in|bei)\s+[^,.;!?]{1,80}?"
        r"(?:[.!?]|,|;|[-–—])\s*(?:(?:sondern|aber)\s+)?"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe|wohnen|leben)\s+"
        r"(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+(?:in|bei)\s+[^,.;!?]{1,80}?"
        r"(?:\s*(?:,|;|[-–—])\s*|\s+)sondern\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:bei|mit|zusammen\s+mit)\s+[^,.;!?]{{1,80}}\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+nicht(?:\s+mehr)?\s+"
        r"[^,.;!?]{1,80}?(?:\s*(?:,|;|[-–—])\s*|\s+)sondern\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:bei|mit|zusammen\s+mit)\s+[^,.;!?]{{1,80}}\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|lebe|wohnen|leben)\s+(?:aber|doch|jedoch)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,\-]\s*(?:aber|doch|jedoch)?\s*)(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:bei|mit|zusammen\s+mit)\s+"
        r"(?!(?:[^,.;!?]*\b(?:arbeit\w*|studier\w*|studium\w*|ausbildung\w*|"
        r"lern\w*|schlaf\w*|mach\w*)\b))"
        r"[^,.;!?]{1,80}\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,\-]\s*(?:aber|doch|jedoch)?\s*)(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung|gegend)\s+von|in\s+der\s+stadt|"
        r"im\s+raum|rund\s+um|nahe|unweit\s+von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+herum)?(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+"
        r"(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:ich|wir)\s+)?"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s+)(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+"
        r"(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:ich|wir)\s+)?"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung|gegend)\s+von\s+|"
        r"in\s+der\s+(?:schweiz|stadt)\s*|im\s+(?:raum|bundesland)\s+|"
        r"in\s+(?:deutschland|österreich|oesterreich|schweiz)\s*)"
        r"[^,.;!?]{0,80},\s*(?:(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|"
        r"besser\s+gesagt|sprich)\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+"
        r"(?:(?:ich|wir)\s+)?(?:bin|sind)\s+"
        r"(?:(?:ich|wir)\s+)?"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung|gegend)\s+von\s+|"
        r"in\s+der\s+(?:schweiz|stadt)\s*|im\s+(?:raum|bundesland)\s+|"
        r"in\s+(?:deutschland|österreich|oesterreich|schweiz)\s*)"
        r"[^,.;!?]{0,80},\s*(?:(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|"
        r"besser\s+gesagt|sprich)\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}|seit\s+heute|heute)\s+"
        r"(?:(?:ich|wir)\s+)?(?:bin|sind)\s+"
        r"(?:(?:ich|wir)\s+)?"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung|gegend)\s+von\s+|"
        r"in\s+der\s+(?:schweiz|stadt)\s*|im\s+(?:raum|bundesland)\s+|"
        r"in\s+(?:deutschland|österreich|oesterreich|schweiz)\s*)"
        r"[^,.;!?]{0,80},\s*(?:(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|"
        r"besser\s+gesagt|sprich)\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:nicht|keinesfalls|keineswegs|niemals|nirgendwo|nirgends|nie)\s+"
        r"(?:(?:in|bei)\s+)?[^,.;!?]{1,80},\s*"
        r"(?:sondern|aber)\s+(?:(?:jetzt|aktuell|derzeit|nun)\s+)?(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:nicht\s+mehr|nicht\s+l(?:ä|a)nger|nie\s+wieder)\s+[^,.;!?]{1,80},\s*"
        r"(?:jetzt|nun|aktuell|derzeit)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s+(?:ist|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|"
        r"zu\s+hause|daheim)\b)\s+(?:ist|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bnein\s*[,;:]?\s+(?:nicht|keinesfalls|keineswegs|niemals|nie)\s+"
        r"(?:(?:in|bei)\s+)?[^,.;!?]{1,80},\s*sondern\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
)
CITY_PATTERNS = (
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>(?:Frankfurt\s+an\s+der\s+Oder|Ludwigshafen\s+am\s+Rhein)|"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|adresse|wohnadresse|wohnanschrift|anschrift)\s+"
        r"(?:in|bei)\s+|"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|adresse|wohnadresse|wohnanschrift|anschrift)\s+"
        r"(?:ist|liegt|lautet|befindet\s+sich|bleibt|:)\s*(?:(?:in|bei)\s+)?)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))\s+"
        r"(?:ist|bleibt)\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|bleibe|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        r"(?:(?:offiziell|polizeilich|privat|dauerhaft|permanent|vorübergehend|vorlaeufig)\s+)?"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))\s+"
        r"(?:(?:offiziell|polizeilich|privat|dauerhaft|permanent|vorübergehend|vorlaeufig)\s+)?"
        r"(?:gemeldet|registriert|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|bleibe)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s*,\s*"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:(?:einen|einem|meinen|meine|mein|unseren|unsere|unser)\s+)?"
        r"(?:(?:fest\w*|dauerhaft\w*|offiziell\w*|privat\w*|"
        r"ständig\w*|staendig\w*|stabil\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+"
        r"(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+"
        r"(?:offiziell\w*|privat\w*|aktuell\w*|dauerhaft\w*|fest\w*|"
        r"ständig\w*|staendig\w*|stabil\w*|gegenwärtig\w*|gegenwaertig\w*)\s+"
        r"(?:adresse|wohnadresse|wohnanschrift|anschrift)\s+"
        r"(?:ist|liegt|lautet|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+eine\s+"
        r"(?:feste|dauerhafte|ständige|staendige|stabile)\s+bleibe\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|bleibe|"
        r"zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:auf\s+(?:dem|einem)\s+Dorf\s+(?:bei|in)\s+|im\s+(?:Landkreis|Kreis)\s+(?:von\s+)?)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:im\s+einzugsgebiet\s+von|in\s+der\s+peripherie\s+von|"
        r"in\s+der\s+metropolregion(?:\s+von)?|im\s+gebiet\s+um)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:das\s+ist\s+)?(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:zuhause|zu\s+hause|daheim|bleibe)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:ist|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+(?:(?:feste|dauerhafte|ständige|staendige|stabile)\s+)?"
        r"(?:zuhause|zu\s+hause|daheim|bleibe)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:eine\s+)?"
        r"(?:(?:feste|dauerhafte|ständige|staendige|stabile)\s+)?"
        r"(?:unterkunft|bleibe|mietwohnung)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:feste|dauerhafte|ständige|staendige|stabile)\s+)?"
        r"(?:unterkunft|bleibe|mietwohnung)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+miet(?:e|en|et)\s+(?:eine\s+)?wohnung\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:eine\s+)?(?:feste\s+)?bleibe\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,:]\s*)(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim)\s+"
        r"(?!(?:ist|war|wird|liegt|befindet\s+sich|bleibt|heißt|heisst|lautet|nennt|"
        r"soll|sollte|wäre|waere)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+am\s+see\s+"
        r"(?:bei|in|nahe|unweit\s+von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+in\s+"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\s+"
        r"(?:gegend|region|gebiet)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+im\s+herzen\s+"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+im\s+herzen\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:wir|ich)\s+(?:wohnen|leben|wohne|lebe)\s+zusammen\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,\s*"
        r"(?:mein(?:e)?|unser(?:e)?)\s+(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:wohne|wohnen|lebe|leben)\s+(?:tue|tun)\s+(?:ich|wir)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:tue|tun)\s+(?:ich|wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:zu\s+hause|zuhause|daheim)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:die|der|eine|einer|ein)\s+(?:stadt|ort)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwo\s+(?:(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)|"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir))\s*[?:]\s*"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|zurzeit|zur\s+zeit)\s*:\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|zurzeit|zur\s+zeit)\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\s*:\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)?\s*(?:adresse|wohnadresse|wohnanschrift|privatadresse|privatanschrift)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+in\s+"
        r"(?:deutschland|österreich|oesterreich|(?:der\s+)?schweiz)\s*,\s*"
        r"(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,:]\s*)(?:meine|unsere)?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz|privatadresse|privatanschrift)\s*"
        r"(?::|=|,)\s*(?:(?:in|bei)\s+)?"
        r"(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere|mein|unser)\s+(?:meldadresse|meldeadresse|meldeanschrift|meldesitz)\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+(?:wohnung|wg|unterkunft)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+)"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:(?:derzeit|aktuell|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:gemeldet|registriert)\s+(?:in|bei)\s+"
        r"(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+)"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:(?:derzeit|aktuell|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:in|bei)\s+(?![^.!?;,]*\b(?:beruflich|dienstlich|zur\s+schule|zur\s+arbeit)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+registriert\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:(?:derzeit|aktuell|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:in|bei)\s+(?![^.!?;,]*\b(?:beruflich|dienstlich|zur\s+schule|zur\s+arbeit)\b)"
        r"(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:gemeldet|registriert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?![^.!?;,]*\b(?:beruflich|dienstlich|zur\s+schule|zur\s+arbeit)\b)"
        r"(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:bin|sind)\s+(?:ich|wir)\s+(?:(?:derzeit|aktuell|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:gemeldet|registriert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER})\s+(?:ist|bleibt)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:in|bei|an)\s+(?:der|dem|einer|einem)\s+|am\s+)"
        r"(?:ort|ortschaft|gemeinde|kommune|metropole|hauptstadt|hansestadt|hafenstadt|"
        r"universitätsstadt|universitaetsstadt|kreisstadt|landeshauptstadt)\s+(?:von\s+)?"
        r"(?:(?:namens|genannt)\s+|nahe\s+|unweit\s+von\s+|rund\s+um\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?!(?:[^,.;!?]*\b(?:arbeit\w*|studier\w*|studium\w*|ausbildung\w*|"
        r"lern\w*|schlaf\w*)\b))"
        r"(?:bei|mit|zusammen\s+mit)\s+[^,.;!?]{1,80}\s+in\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+der\s+(?:nähe|naehe|umgebung|gegend)\s+(?:von\s+)?|im\s+raum\s+|"
        r"rund\s+um\s+|nahe\s+|unweit\s+von\s+|"
        r"am\s+(?:stadt)?rand\s+von\s+|im\s+umland\s+(?:von\s+)?|"
        r"im\s+(?:norden|süden|osten|westen)\s+von\s+)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+herum)?(?=\s*(?:[.!?;,]|$|"
        r"\b(?:und|aber|doch|jedoch)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"(?:{_RESIDENCE_DISTANCE_PREFIX})?"
        r"(?:nördlich|südlich|östlich|westlich|nord[-\s]?östlich|nord[-\s]?westlich|"
        r"süd[-\s]?östlich|süd[-\s]?westlich)\s+(?:von\s+)?"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"(?:{_RESIDENCE_DISTANCE_PREFIX})?"
        r"(?:nördlich|südlich|östlich|westlich|nord[-\s]?östlich|nord[-\s]?westlich|"
        r"süd[-\s]?östlich|süd[-\s]?westlich)\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$|"
        r"\b(?:und|aber|doch|jedoch)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+)?(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\s+(?:nähe|naehe|umgebung|umland|vorstadt|vorort)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:in\s+)?(?:einer|einem|der)\s+(?:stadt|ort)\s+(?:namens|genannt)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        rf"zuhause|zu\s+hause|daheim)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+sofort|gegenwärtig|gegenwaertig)\s+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+sofort|gegenwärtig|gegenwaertig)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        r"zuhause|zu\s+hause|daheim)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+nenn(?:e|en)?\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+nenn(?:e|en)?\s+(?:ich|i)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s*,\s*"
        r"(?:das|dort|hier|da)\s+ist\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:heißt|heisst)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|derzeit\w*|jetzig\w*|gegenwärtig\w*|gegenwaertig\w*|neu\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+wird\s+(?:als\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|derzeit\w*|jetzig\w*|gegenwärtig\w*|gegenwaertig\w*|neu\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+genannt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+nennt\s+man\s+"
        r"(?:mein(?:en|e)?|unser(?:en|e)?)\s+"
        r"(?:(?:aktuell\w*|derzeit\w*|jetzig\w*|gegenwärtig\w*|gegenwaertig\w*|neu\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:ist|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|derzeit\w*|jetzig\w*|gegenwärtig\w*|gegenwaertig\w*|offiziell\w*)\s+)?"
        r"(?:wohnadresse|wohnanschrift|meldeadresse|anschrift|adresse)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+als\s+"
        r"(?:(?:mein(?:e)?|unser(?:e)?)\s+)?"
        r"(?:wohnadresse|wohnanschrift|meldeadresse|anschrift|adresse)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,\n]\s*)als\s+"
        r"(?:wohnadresse|wohnanschrift|meldeadresse|anschrift|adresse)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:der|die|das|ein(?:e)?|eine)\s+"
        r"(?:wohnadresse|wohnanschrift|meldeadresse|anschrift|adresse)\s+"
        r"(?:ist|liegt|lautet|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,\n]\s*)(?:(?:eigentlich|aktuell|derzeit|momentan|nun|jetzt|gerade)\s+)?"
        r"(?!(?:ist|war|bleibt|wird)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*"
        r"(?:\s+(?!(?:ist|war|bleibt|wird)\b)[\wÄÖÜäöüß'-]+){0,6})\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,\n]\s*)(?:(?:eigentlich|aktuell|derzeit|momentan|nun|jetzt|gerade)\s+)?"
        r"(?!(?:ist|war|bleibt|wird)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+(?!(?:ist|war|bleibt|wird)\b)"
        r"[\wÄÖÜäöüß'-]+){0,6})\s+als\s+"
        r"(?:(?:mein(?:e)?|unser(?:e)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,\n]\s*)als\s+"
        r"(?:(?:mein(?:e)?|unser(?:e)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*"
        r"(?:ist|lautet|:)??\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+[\wÄÖÜäöüß'-]+){0,6})"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,\n]\s*)(?:(?:eigentlich|aktuell|derzeit|momentan|nun|jetzt|gerade)\s+)?"
        r"(?!(?:nächste\w*|naechste\w*|kommende\w*)\s+jahr\b)"
        r"(?!(?:ist|war|bleibt|wird)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*"
        r"(?:\s+(?!(?:ist|war|bleibt|wird)\b)[\wÄÖÜäöüß'-]+){0,6})"
        r"(?:\s+(?:ist|bleibt)|\s*,)?\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|derzeit\w*|momentan\w*|hauptsächlich\w*|hauptsaechlich\w*|neu\w*|"
        r"jetzig\w*|gegenwärtig\w*|gegenwaertig\w*|vorläufig\w*|vorlaeufig\w*|dauerhaft|permanent|"
        r"temporär|temporaer|vorübergehend|voruebergehend|befristet|unbefristet|kurzfristig|langfristig|"
        r"gemeldet\w*|offiziell\w*|fest\w*|tatsächlich\w*|tatsaechlich\w*|privat\w*|polizeilich\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim)\s+nenn(?:e|en)?\s+(?:ich|wir)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+habe\s+(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+als\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+(?:bin|sein)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:zu\s+hause|zuhause|daheim|dahoam)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i|wir)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+"
        r"(?:in\s+der\s+(?:nähe|naehe|umgebung)\s+(?:von\s+)?)"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i|wir)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+"
        r"(?:in\s+)?(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\s+(?:nähe|naehe|umgebung)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i|wir)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+"
        r"(?:(?:in\s+der\s+(?:gegend|umgebung)\s+)?um)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+herum)?(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i|wir)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+"
        rf"(?:{_RESIDENCE_DISTANCE_PREFIX})?"
        r"(?:nördlich|südlich|östlich|westlich|nord[-\s]?östlich|nord[-\s]?westlich|"
        r"süd[-\s]?östlich|süd[-\s]?westlich)\s+(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i|wir)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+"
        rf"(?:{_RESIDENCE_DISTANCE_PREFIX})?"
        r"(?:nördlich|südlich|östlich|westlich|nord[-\s]?östlich|nord[-\s]?westlich|"
        r"süd[-\s]?östlich|süd[-\s]?westlich)\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$|"
        r"\b(?:und|aber|doch|jedoch)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i|wir)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+"
        r"(?:au(?:ßerhalb|sserhalb))\s+(?:der\s+stadt|des\s+orts|des\s+ortes)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i|wir)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+"
        r"im\s+(?:nördlichen|südlichen|östlichen|westlichen|nord[-\s]?östlichen|"
        r"nord[-\s]?westlichen|süd[-\s]?östlichen|süd[-\s]?westlichen)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
        rf"zuhause|zu\s+hause|daheim|{_PRIMARY_RESIDENCE_LABEL})\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"(?:{_RESIDENCE_LOCATION_ADVERB})\s*,?\s*(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|i)\s+(?:wohne|wohn|lebe|leb)\s+(?:{_RESIDENCE_LOCATION_ADVERB})\s*,?\s*"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+(?:wohne|wohn|lebe|leb)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,\s*(?:hier|dort|da)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:hier|dort|da)\s*,?\s*"
        r"wo\s+(?:ich|wir)\s+arbeit\w*\s*[:,-]?\s*(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?<!s)s\s+"
        r"(?:norden|süden|osten|westen|nord[-\s]?osten|nord[-\s]?westen|"
        r"süd[-\s]?osten|süd[-\s]?westen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|i)\s+(?:bin|sein)\s+(?:{_RESIDENCE_LOCATION_ADVERB})\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:zu\s+hause|zuhause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+(?:wohne|wohn|lebe|leb)\s+"
        rf"(?:(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+sofort|im\s+moment|gegenwärtig|gegenwaertig|"
        r"(?:derzeit|aktuell)\s+noch)\s+)?"
        r"(?:in|bei)\s+"
        r"(?!(?:[A-ZÄÖÜ][\wÄÖÜäöüß .'-]*s)\s+(?:nähe|naehe|umgebung)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i)\s+(?:bin|sein)\s+(?:dahoam|daheim|zuhause|zu\s+hause)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:wohne|wohn|wohnen|lebe|leb|leben)\s+(?:ich|i|wir)\b"
        r"(?!\s+(?:nicht|früher|frueher|ehemals)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:au(?:ßerhalb|sserhalb)|am\s+rand|im\s+umland|im\s+(?:norden|süden|osten|westen)|"
        r"nördlich|südlich|östlich|westlich)\s+(?:von\s+)?"
        r"(?P<city>Paris|Reims|Worms|Tours|Cannes|Lens)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"in\s+der\s+(?:nähe|naehe|umgebung)\s+(?:des|der)\s+[^,.;!?]{1,80}\s+"
        r"(?:von|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+in\s+der\s+nähe\s+(?:von\s+)?"
        r"(?P<city>Paris|Reims|Worms|Tours|Cannes|Lens)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine\s+|unsere\s+)?(?:adresse|wohnadresse|wohnanschrift|anschrift)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+\d{5}\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine\s+|unsere\s+)?(?:privatadresse|private\s+adresse|hauptadresse)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}\s+bei\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|"
        r"besser\s+gesagt|sprich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+[^,.;!?]{1,80},\s*"
        r"(?:aber\s+)?(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|"
        r"besser\s+gesagt|sprich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+bei\s+[^,.;!?]{1,80},\s*"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"wird\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+genannt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+wird\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+genannt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:heißt|heisst)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:bereits|schon|noch)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+neben\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:wohnhaft|ansässig|ansaessig)\s+(?:bin ich|sind wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:im|in\s+der|in\s+dem|in\s+einem|in\s+einer|in|am)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]*?)(?:er|(?<!s)s)\s+"
        r"(?:stadtteil|bezirk|innenstadt|stadtmitte|stadtrand|rand|vorstadt|vorort|umland|stadtzentrum|zentrum|raum|region|gebiet)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:in\s+der\s+(?:region|gegend|umgebung)|im\s+gebiet)\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]*?(?<!s))s\s+nähe\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:nördlich|südlich|östlich|westlich)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]*?(?<!s))s\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine\s+|unsere\s+)?(?:adresse|wohnadresse|wohnanschrift|anschrift)\s*:\s*"
        r"\d{5}\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine\s+|unsere\s+)?(?:adresse|wohnadresse|wohnanschrift|anschrift)\s*:\s*"
        r"[^,.;!?]{1,100}?(?:straße|strasse|weg|allee|gasse|platz|ufer|ring|chaussee|steig|promenade)\s+"
        r"\d+[a-z]?\s*,\s*(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine\s+|unsere\s+)?(?:adresse|wohnadresse|wohnanschrift|anschrift)\s*:\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:während\s+(?:(?:meines|des)\s+studiums|(?:meiner|der)\s+(?:ausbildung|lehre))|"
        r"nach\s+(?:dem\s+studium|der\s+(?:ausbildung|lehre)|(?:dem|meinem)\s+umzug))\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s*(?:,|[-–—])\s*"
        r"(?:hier|dort|da)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+(?:ich|i|wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:bin|sind)\s+(?:ich|wir)\s+(?:hier|dort|da\s+)?"
        r"(?:zu\s+hause|zuhause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:in|bei)\s+"
        r"(?:deutschland|österreich|oesterreich|schweiz)\s*,\s*"
        r"(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|"
        r"besser\s+gesagt|sprich)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b(?!\s+(?:nicht|früher|frueher|ehemals)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bbei\s+[^,.;!?]{1,80}?\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b(?!\s+(?:nicht|früher|frueher|ehemals)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung)\s+von|im\s+raum|"
        r"nahe|unweit\s+von|au(?:ßerhalb|sserhalb)\s+von|am\s+stadtrand\s+von|"
        r"im\s+umland\s+von|im\s+(?:norden|süden|osten|westen)\s+von|am\s+rand\s+von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b(?!\s+(?:nicht|früher|frueher|ehemals)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"habe(?:n)?\s+(?:ich|wir)\s+(?:meinen|meine|mein|unseren|unsere|unser|den|die|das)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:(?:aktuell(?:er|e)?|jetzig(?:er|e)|derzeitig(?:er|e)?|gegenwärtig(?:er|e)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*"
        r"(?:(?:bitte|aktuell|derzeitig|derzeit|gegenwärtig)\s*)?"
        r"(?::|=|,)?\s*(?!(?:ist|war|w(?:äre|urde)|liegt|befindet|bleibt|nicht)\b)"
        r"(?:(?:bitte|aktuell|derzeitig|derzeit|gegenwärtig)\s*)?"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b\s*"
        r"(?::|=|,)?\s*(?!(?:bin|sind|war|w(?:äre|urde)|nicht)\b)"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|wohnen|lebe|leben)\b\s*"
        r"(?:(?::|=|,)\s*(?:(?:in|bei)\s+)?|(?:in|bei)\s+)"
        r"(?!(?:ich|wir|ist|war|w(?:äre|urde)|nicht|künft\w*|kuenft\w*|"
        r"zukünft\w*|zukuenft\w*|bald|morgen|nächste\w*|naechste\w*)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"tue\s+(?:ich|wir)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?!(?:ich|wir|tue|tun|mal|teils|abwechselnd|aber|doch|jedoch|zwischen|irgendwo|mit|auf|aus|von|nach|für|fuer|ab|bis|seit|"
        r"nur\s+am\s+wochenende|am\s+wochenende|"
        r"während|waehrend|montags?|dienstags?|mittwochs?|donnerstags?|freitags?|samstags?|sonntags?|"
        r"morgens|vormittags|mittags|nachmittags|abends|nachts|täglich|taeglich|wöchentlich|woechentlich|"
        r"monatlich|jährlich|jaehrlich|tagsüber|tagsueber|jeden|jede|jedes|alle|an|jetzt|inzwischen|aktuell|derzeit|nun|"
        r"oft|häufig|haeufig|meist\w*|gelegentlich|regelmäßig|regelmaessig|selten|manchmal)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)|"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:liegt|befindet\s+sich))\s+"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung)|unweit|"
        r"au(?:ßerhalb|sserhalb)|am\s+rand|im\s+umland|"
        r"im\s+(?:norden|süden|osten|westen))\s+(?:von\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß '-]{1,80})(?<!s)(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)|"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:liegt|befindet\s+sich))\s+"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung)|unweit|"
        r"au(?:ßerhalb|sserhalb)|am\s+rand|im\s+umland|"
        r"im\s+(?:norden|süden|osten|westen))\s+(?:von\s+)?"
        r"(?!(?:paris|reims|worms|tours|cannes|lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß '-]{1,80}(?<!s))s(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben))\s+(?:in|bei)\s+"
        r"\d{5}\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*"
        r"(?:ist|liegt|befindet\s+sich|bleibt|:)\s*(?:(?:in|bei)\s+)?"
        r"\d{5}\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben))\s+"
        r"[^,.;!?]{1,100}?(?:straße|strasse|weg|allee|gasse|platz|ufer|ring|chaussee|steig|promenade)\s+"
        r"\d+[a-z]?\s*(?:,\s*|\s+)(?:(?:in|bei)\s+)?(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:adresse|wohnadresse|wohnanschrift|anschrift|wohnort|wohnsitz)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        r"[^,.;!?]{1,100}?(?:straße|strasse|weg|allee|gasse|platz|ufer|ring|chaussee|steig|promenade)\s+"
        r"\d+[a-z]?\s*(?:,\s*|\s+)(?:(?:in|bei)\s+)?(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:meine|unsere)\s+"
        r"(?:adresse|wohnadresse|wohnanschrift|anschrift)\s+"
        r"[^,.;!?]{1,100}?(?:straße|strasse|weg|allee|gasse|platz|ufer|ring|chaussee|steig|promenade)\s+"
        r"\d+[a-z]?\s*(?:,\s*|\s+)(?:(?:in|bei)\s+)?(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)|"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:liegt|befindet\s+sich))\s+"
        r"(?:im\s+(?:norden|süden|osten|westen)|am\s+rand)\s+von\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:ist|bleibt)\s+"
        r"mein(?:e)?\s+"
        r"(?:(?:aktuell(?:er|e)?|jetzig(?:er|e)|derzeitig(?:er|e)?|gegenwärtig(?:er|e)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|lebensmittelpunkt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<!beruflich\s)(?<!dienstlich\s)(?<!zur schule )(?<!zur arbeit )\b"
        r"(?!(?:beruflich|dienstlich|zur\s+schule|zur\s+arbeit)\s+)"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+(?:bin\s+ich|sind\s+wir)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser|den|die|das)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|bleibe)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)|"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:liegt|befindet\s+sich))\s+"
        r"(?:im|in\s+(?:dem|der|einem|einer))\s+"
        r"(?:stadtteil|bezirk|viertel|kiez|ortsteil|quartier|altstadt|stadtzentrum|zentrum|innenstadt)\s+"
        r"(?!(?:(?!\s+(?:in|bei|von)\s+)[^,.;!?])*\b(?:und|aber|doch|jedoch|"
        r"arbeite\w*|studier\w*|lern\w*|schlaf\w*|pendl\w*|reis\w*|"
        r"besuch\w*|übernacht\w*|uebernacht\w*)\b)"
        r"[^,.;!?]{1,80}?\s+(?:in|bei|von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)|"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:liegt|befindet\s+sich))\s+"
        r"(?:im|in\s+(?:dem|der|einem|einer))\s+"
        r"(?:stadtteil|bezirk|viertel|kiez|ortsteil|quartier|altstadt|stadtzentrum|zentrum|innenstadt)\s+von\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?\s+)?{_PRIMARY_RESIDENCE_LABEL}"
        rf"(?:\s+(?:ist|liegt|befindet\s+sich|bleibt)\s*|:\s*)(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}|seit\s+heute|heute)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}|seit\s+heute|heute)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:in\s+der\s+(?:schweiz|stadt)|in\s+(?:deutschland|österreich|oesterreich|schweiz)\s*|"
        r"im\s+(?:raum|bundesland)\s+)[^,.;!?]{0,80},\s*"
        r"(?:(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s+)?"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?"
        r"(?:in\s+der\s+(?:schweiz|stadt)|in\s+(?:deutschland|österreich|oesterreich|schweiz)\s*|"
        r"im\s+(?:raum|bundesland)\s+)[^,.;!?]{0,80},\s*"
        r"(?:(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s+)?"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:seit\s+heute|heute|jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        rf"(?:(?:{_RESIDENCE_TIME_QUALIFIER}|offiziell|polizeilich|privat|dauerhaft|permanent|"
        r"vorübergehend|vorlaeufig|nur\s+vorübergehend|nur\s+vorlaeufig)\s+)?"
        rf"(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:(?:offiziell|polizeilich|privat|dauerhaft|permanent|vorübergehend|vorlaeufig)\s+)?"
        r"(?:gemeldet|registriert|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:ich|wir)\s+)?residier(?:e|en|t)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich\s+)?bin\s+"
        rf"(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+gemeldet\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich|wir)\s+"
        r"(?:bin|sind)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+beheimatet\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:ich\s+)?habe\s+(?:meine|unsere)\s+bleibe|"
        r"(?:meine|unsere)\s+bleibe\s+(?:ist|liegt|befindet\s+sich))\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:zuhause|zu\s+hause|daheim)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung|gegend)\s+von\s+|"
        r"in\s+der\s+(?:schweiz|stadt)\s*|im\s+(?:raum|bundesland)\s+|"
        r"in\s+(?:deutschland|österreich|oesterreich|schweiz)\s*)"
        r"[^,.;!?]{0,80},\s*(?:(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|"
        r"besser\s+gesagt|sprich)\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+)?"
        r"(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:ich|wir)\s+)?"
        r"(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+)?"
        r"(?:auf\s+dem\s+land|in\s+(?:einer|einem|der)\s+"
        r"(?:(?:klein|groß|gross)(?:e|en|er|es|em)?\s*)?"
        r"(?:stadt|vorstadt|dorf|ort|vorort)(?![\wÄÖÜäöüß])|"
        r"im\s+(?:(?:klein|groß|gross)(?:e|en|er|es|em)?\s*)?"
        r"(?:dorf|ort|vorort|großraum|grossraum)(?![\wÄÖÜäöüß]))\s*"
        r"(?:,\s*)?"
        r"(?:\s*(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s*)?"
        r"(?:(?:in\s+(?:der\s+)?(?:naehe|n(?:ä|ae)he|umgebung)\s+von|"
        r"unweit\s+von|rund\s+um|bei|nahe|in|von)\s+)?"
        r"(?:(?:namens|genannt)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|stadt|ort)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:(?:ein(?:e|em|er)?|der|die|das)\s+)?"
        r"(?:(?:klein|groß|gross)(?:e|en|er|es|em)?\s*)?"
        r"(?:stadt|vorstadt|dorf|ort|vorort)(?![\wÄÖÜäöüß])\s*"
        r"(?:,\s*)?"
        r"(?:\s*(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s*)?"
        r"(?:(?:in\s+(?:der\s+)?(?:naehe|n(?:ä|ae)he|umgebung)\s+von|"
        r"unweit\s+von|rund\s+um|bei|nahe|in|von)\s+)?"
        r"(?:(?:namens|genannt)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|stadt|ort|zuhause|zu\s+hause|daheim)\s+"
        r"nennt\s+sich\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+"
        r"(?:(?:aktuell(?:e|er)?|jetzig(?:e|er)?|derzeitig(?:e|er)?|gegenwärtig(?:e|er)?)\s+)?"
        r"(?:wohnadresse|wohnanschrift|adresse|anschrift)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+habe(?:n)?\s+(?:meine|unsere)\s+"
        r"(?:(?:aktuell(?:e|er)?|jetzig(?:e|er)?|derzeitig(?:e|er)?|gegenwärtig(?:e|er)?)\s+)?"
        r"(?:wohnadresse|wohnanschrift|adresse|anschrift)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        rf"(?:(?:{_RESIDENCE_TIME_QUALIFIER}|{_RESIDENCE_LOCATION_ADVERB})\s+)+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich\s+)?habe\s+(?:meinen|den)\s+{_PRIMARY_RESIDENCE_LABEL}\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+)?habe\s+(?:meinen|einen)\s+(?:festen|ständigen|staendigen|permanenten)\s+"
        r"(?:wohnort|wohnsitz|hauptwohnsitz)\s+(?:in|bei)\s+"
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
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?sind\s+wir\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:wohnhaft|ansässig|ansaessig)\b",
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
        r"\b(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zuhause|zu\s+hause|daheim)\s+"
        r"(?:liegt|befindet\s+sich)\s+"
        r"(?:au(?:ßerhalb|sserhalb)\s+von|am\s+stadtrand\s+von|im\s+umland\s+von|"
        r"nord[-\s]?östlich\s+von|nord[-\s]?westlich\s+von|süd[-\s]?östlich\s+von|"
        r"süd[-\s]?westlich\s+von|"
        r"nördlich\s+von|südlich\s+von|östlich\s+von|westlich\s+von)\s+"
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
        r"(?:^|[.!?;\n]\s*)(?:(?:(?:ich|wir)\s+)?(?:bin|sind)\s+)?"
        r"(?:ich\s+)?(?:wohnhaft|ansässig|ansaessig)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}|seit\s+heute|heute)\s+"
        r"(?:(?:ich|wir)\s+)?(?:wohnhaft|ansässig|ansaessig)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}|seit\s+heute|heute)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,:]\s*)(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?\s+)?(?:(?:aktuell(?:er|e)?|jetzig(?:er|e)|derzeitig(?:er|e)?|gegenwärtig(?:er|e)?)\s+)?"
        rf"(?:wohnort|wohnsitz|wohnstadt|stadt|ort|zuhause|zu\s+hause|daheim)(?:\s+(?:ist|heisst|heißt|lautet|liegt|befindet\s+sich|bleibt)\s*|:\s*)"
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
        rf"(?:ich\s+)?(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?bei\s+"
        r"(?![^,.;!?]*\b(?:arbeit\w*|job\w*|büro\w*|buero\w*|studier\w*|studium\w*|lern\w*)\b)"
        rf"[^,.;!?]{{1,80}}\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?wir\s+(?:wohnen|leben)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?bei\s+[^,.;!?]{{1,80}}\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?wir\s+(?:wohnen|leben)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:zusammen\s+mit|gemeinsam\s+mit|mit|neben)\s+"
        r"(?![^,.;!?]*\b(?:arbeit\w*|job\w*|büro\w*|buero\w*|studier\w*|studium\w*|lern\w*)\b)"
        rf"[^,.;!?]{{1,80}}\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich\s+)?(?:wohne|lebe)\s+"
        rf"(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:zusammen\s+mit|gemeinsam\s+mit|mit|neben)\s+"
        r"(?![^,.;!?]*\b(?:arbeit\w*|job\w*|büro\w*|buero\w*|studier\w*|studium\w*|lern\w*)\b)"
        rf"[^,.;!?]{{1,80}}\s+(?:in|bei)\s+"
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
        r"\b(?:ich\s+wohne|ich\s+lebe|wir\s+wohnen|wir\s+leben|wohn(?:e)?|lebe)\s+"
        r"(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung|gegend)\s+von|in\s+der\s+stadt|im\s+raum|"
        r"au(?:ßerhalb|sserhalb)\s+von|am\s+stadtrand\s+von|im\s+umland\s+von|"
        r"nord[-\s]?östlich\s+von|nord[-\s]?westlich\s+von|süd[-\s]?östlich\s+von|"
        r"süd[-\s]?westlich\s+von|"
        r"nördlich\s+von|südlich\s+von|östlich\s+von|westlich\s+von|rund\s+um|nahe|unweit\s+von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+herum)?(?=\s*(?:[.!?;,]|$|"
        r"\b(?:und|aber|doch|jedoch)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich\s+)?(?:wohn(?:e)?|lebe)\s+"
        rf"(?:ich\s+)?(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:zwar\s+)?(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|im|bei)\s+"
        r"(?:(?:meine|meiner|meinem|meinen|mein|unsere|unserer|unserem|unseren|unser|"
        r"eine|einer|einem|eines|ein|der|dem|den)\s+)?"
        r"(?:wohnung|haus|eigenheim|unterkunft|appartement|apartment|wg|wohnheim|"
        r"studentenwohnheim|internat|mehrfamilienhaus|übergangswohnung|uebergangswohnung|zwischenwohnung)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich\s+wohne|ich\s+lebe|wohn(?:e)?|lebe)\s+"
        r"(?:(?:jetzt|aktuell|derzeit)\s+)?(?:zwar\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:meine\s+stadt|mein\s+wohnort|mein\s+ort)\s+(?:ist|heisst|heißt)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})", re.IGNORECASE),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+ist\s+"
        r"(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+neue[rsnm]?\s+"
        r"(?:wohnort|wohnsitz|zuhause|zu\s+hause)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+ist\s+"
        r"(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|noch\s+immer|immer\s+noch|weiterhin|"
        r"nach\s+wie\s+vor|gegenwärtig|gegenwaertig|jetzig\w*|vorläufig|vorlaeufig|dauerhaft|permanent|"
        r"temporär|temporaer|vorübergehend|voruebergehend|befristet|unbefristet|kurzfristig|langfristig)\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+(?:wohnort|wohnsitz|zuhause|zu\s+hause)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+ist\s+(?:der|ein)\s+"
        r"(?:(?:aktuell\w*|derzeit\w*|gegenwärtig\w*|gegenwaertig\w*|gemeldet\w*|offiziell\w*|"
        r"fest\w*|tatsächlich\w*|tatsaechlich\w*|dauerhaft\w*|privat\w*|polizeilich\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:wegen|aufgrund)\s+[^,.;!?]{1,80}|aus\s+[^,.;!?]{1,80}\s+"
        r"gr(?:ünden|uenden))\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+ist\s+der\s+ort,\s+"
        r"in\s+dem\s+ich\s+(?:lebe|wohne)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bder\s+ort,\s+in\s+dem\s+ich\s+(?:lebe|wohne),\s+ist\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+an\s+"
        r"(?:einem|einer)\s+ort\s+namens\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind|wurde|wurden)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}\s+geboren"
        r"(?:\s*,\s*|\s*;\s*|\s+(?:und|sowie)\s+)"
        r"(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+ist)?(?=\s+(?:(?:mein|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)|"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert))\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)\s+)?"
        r"(?:heimat|heimatstadt|herkunftsort|herkunftsstadt|geburtsort|geburtsstadt)\s*[:=]\s*"
        r"[^,.;!?]{1,80}?"
        r"(?:\s*,\s*(?:(?:aber|doch|jedoch|dafür|stattdessen|während|waehrend)\s+)?(?:ist\s+)?|"
        r"\s*;\s*|\s+(?:und|sowie|während|waehrend)\s+)"
        r"(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+ist)?(?=\s+(?:(?:mein|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)|"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert))\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[^,.;!?]{1,80}\s+(?:ist|war)\s+"
        r"(?:"
        r"(?:mein(?:e)?|unser(?:e)?)\s+(?:(?:frühere|fruehere|ehemalige|alte)\s+)?"
        r"(?:heimat|heimatstadt|herkunftsort|herkunftsstadt|geburtsort|geburtsstadt)"
        r"|(?:der|ein)\s+ort\s+meiner\s+geburt"
        r")"
        r"(?:\s*,\s*(?:(?:aber|doch|jedoch|dafür|stattdessen|während|waehrend)\s+)?(?:ist\s+)?|"
        r"\s*;\s*|"
        r"\s+(?:und|sowie|während|waehrend)\s+)"
        r"(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+ist)?(?=\s+(?:(?:mein|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)|"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert))\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:frühere|fruehere|ehemalige|alte)\s+)?"
        r"(?:heimat|heimatstadt|herkunftsort|herkunftsstadt|geburtsort|geburtsstadt)\s+"
        r"(?:ist|war)\s+[^,.;!?]{1,80}?"
        r"(?:\s*,\s*(?:(?:aber|doch|jedoch|dafür|stattdessen|während|waehrend)\s+)?(?:ist\s+)?|"
        r"\s*;\s*|\s+(?:und|sowie|während|waehrend)\s+)"
        r"(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+ist)?(?=\s+(?:(?:mein|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)|"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert))\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:eigentlich|aktuell|derzeit|momentan|nun|jetzt|gerade)\s+"
        r"(?:ist|bleibt)\s+(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|zuhause|zu\s+hause|daheim)\s+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift)\s+"
        r"(?:ist|liegt|lautet|befindet\s+sich|bleibt|:)\s*"
        r"(?:(?:eigentlich|genau|aktuell|derzeit|momentan|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:(?:in|bei)\s+)?"
        r"(?P<city>[^\W\d_][\wÄÖÜäöüß .'-]{1,80})(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[^\W\d_][\wÄÖÜäöüß .'-]{1,80})\s+(?:ist|bleibt)\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift)\s*"
        r"(?:ist|liegt|lautet|befindet\s+sich|bleibt|:|=)\s*(?::\s*)?"
        r"(?:(?:in|bei)\s+)?[\"'„“‚‘«(]?"
        r"(?:laut\s+(?:der\s+)?(?:melde)?adresse\s+)?"
        r"(?:(?:sicher|wirklich|definitiv|tatsächlich|tatsaechlich)\s+)?"
        r"(?:\d{5}\s+)?(?P<city>[^\W\d_][\wÄÖÜäöüß .()-]{1,80})"
        r"[\"'”“’»)]?(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:\bwo\s+(?:(?:genau|eigentlich)\s+)?(?:wohnst|lebst)\s+du(?:\s+(?:genau|eigentlich|denn))?|"
        r"\bwo\s+in\s+(?:deutschland|österreich|oesterreich|schweiz)\s+"
        r"(?:wohnst|lebst)\s+du(?:\s+denn)?|"
        r"\bin\s+welcher\s+stadt\s+(?:wohnst|lebst)\s+du(?:\s+denn)?|"
        r"\ban\s+welchem\s+ort\s+(?:wohnst|lebst)\s+du(?:\s+denn)?|"
        r"\bwo\s+(?:bist|bleibst)\s+du\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)|"
        r"\bwo\s+ist\s+"
        r"(?:dein(?:e)?|euer(?:e)?|mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift|meldeadresse|zuhause|"
        r"zu\s+hause|daheim)|"
        r"\b(?:(?:dein(?:e)?|euer(?:e)?|mein(?:e)?|unser(?:e)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift|meldeadresse|zuhause|"
        r"zu\s+hause|daheim))"
        r"(?:\s+(?:ist|lautet))?\s*(?:eigentlich|genau|aktuell|derzeit)?\s*[?:]\s*"
        r"(?:(?:antwort\s+(?:ist|lautet)|antwort)\s*(?::|=)?\s*)?"
        r"(?:(?:in|bei)\s+)?"
        r"(?P<city>[^\W\d_][\wÄÖÜäöüß .'-]{1,80})(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
)
CITY_TRAILING_STOP_RE = re.compile(
    r"\s+(?:und|aber|weil|wenn|falls|seit|schon|mit|bei|in|auf|neben|nahe|"
    r"innerhalb|au(?:ßerhalb|sserhalb)|unter|aus|wegen|als|statt|anstatt|anstelle\s+von|im|"
    r"am\s+(?:stadtrand|see|bahnhof|fluss|rand|spree|elbe|donau|rhein|isar|weser|oder|neckar|ruhr|havel|saale)|"
    r"an\s+der\s+(?:spree|elbe|donau|rhein|main|isar|weser|oder|neckar|ruhr|havel|saale)\b|"
    r"f(?:ür|uer)|"
    r"w(?:ährend|aehrend)|zusammen|ohne|obwohl|wobei|denn|da|dort|[-–—]|"
    r"heute|morgen|gestern|gerade|aktuell|jetzt|nun|momentan|derzeit|"
    r"zurzeit|zur\s+zeit|weiterhin|inzwischen|mittlerweile|dauerhaft|"
    r"permanent|ständig|staendig|vor(?:uebergehend|übergehend)|"
    r"frueh|früh|morgens|vormittags|mittags|nachmittags|abends|nachts|"
    r"zuhause|zu\s+hause|daheim|wohnhaft|ansässig|ansaessig|geworden|"
    r"zur\s+(?:unter|zwischen)miete|nur\s+vor(?:uebergehend|übergehend)|zur\s+miete|"
    r"laut\b.*|"
    r"ab\s+sofort|"
    r"bis\s+(?:auf\s+weiteres|zum\s+ende\s+(?:des\s+)?(?:monats|jahres)|"
    r"ende\s+(?:des\s+)?(?:monats|jahres))|"
    r"\.|,|;|:|!|\?)(?=\s|[.!?;,]|$).*$",
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
        if not _append_city_memory(account_store, account_id, city, resolved_now):
            return WeatherContextResult(
                city=previous_city,
                weather_text=str(weather_state.get("summary") or "").strip(),
                skipped_reason="memory_error",
            )
        weather_state["city"] = city
        weather_state["city_updated_at"] = resolved_now.isoformat(timespec="seconds")
        if city_changed:
            # A cached summary belongs to the previous city and must not be
            # presented as current weather while the global check window is active.
            weather_state["summary"] = ""
            weather_state["last_error"] = ""
    current_city = str(weather_state.get("city") or "").strip()
    if not current_city:
        account_store.write_agent_state(account_id, state) if city else None
        return WeatherContextResult(skipped_reason="no_city")
    last_checked = _parse_datetime(str(weather_state.get("last_checked_at") or ""))
    elapsed_since_check = resolved_now - last_checked if last_checked is not None else None
    if not city_changed and elapsed_since_check is not None and timedelta(0) <= elapsed_since_check < WEATHER_CHECK_INTERVAL:
        if city:
            account_store.write_agent_state(account_id, state)
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
        weather_state["updated_at"] = resolved_now.isoformat(timespec="seconds")
        account_store.write_agent_state(account_id, state)
        return WeatherContextResult(city=current_city, checked=True, skipped_reason="weather_error")
    weather_state["summary"] = summary[:500]
    weather_state["last_checked_at"] = resolved_now.isoformat(timespec="seconds")
    weather_state["last_error"] = ""
    weather_state["updated_at"] = resolved_now.isoformat(timespec="seconds")
    account_store.write_agent_state(account_id, state)
    return WeatherContextResult(city=current_city, weather_text=weather_state["summary"], checked=True)


def _append_city_memory(account_store: AccountStore, account_id: str, city: str, now: datetime) -> bool:
    memory_id = f"mem_residence_city_{_city_id_token(city)}"
    try:
        rows = account_store.read_memory_entries(account_id)
        has_current_memory = any(
            str(entry.get("id") or "").strip() == memory_id
            for entry in rows
            if isinstance(entry, Mapping)
        )
        current_memory_count = sum(
            1
            for entry in rows
            if isinstance(entry, Mapping) and str(entry.get("id") or "").strip() == memory_id
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
        if not obsolete_rows and current_memory_count < 2:
            if has_current_memory:
                return True
            account_store.append_structured_memory_entry(account_id, entry)
            return True
        previous_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
        previous_index = account_store.read_memory_index(account_id)
        retained_rows: list[dict[str, Any]] = []
        kept_current_memory = False
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            row_id = str(row.get("id") or "").strip()
            if row_id.startswith("mem_residence_city_"):
                if row_id != memory_id or kept_current_memory:
                    continue
                kept_current_memory = True
            retained_rows.append(dict(row))
        try:
            account_store.write_memory_entries(account_id, retained_rows)
            account_store.rebuild_structured_memory_index(account_id)
            if not has_current_memory:
                account_store.append_structured_memory_entry(account_id, entry)
            return True
        except Exception:
            account_store.write_memory_entries(account_id, previous_rows)
            account_store.write_memory_index(account_id, previous_index)
            raise
    except Exception:
        return False


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
    if source.strip().endswith("?"):
        return ""

    def latest_match(patterns: tuple[re.Pattern[str], ...]) -> str:
        candidates: list[tuple[int, str]] = []

        def collect_matches(value: str, offset: int) -> None:
            for pattern in patterns:
                for match in pattern.finditer(value):
                    pattern_start = offset + match.start()
                    city_start = offset + match.start("city")
                    city_end = offset + match.end("city")
                    if _has_historical_residence_prefix(source, pattern_start):
                        continue
                    if _has_non_residential_label_prefix(source, pattern_start):
                        continue
                    if _has_future_residence_prefix(source, pattern_start, city_start):
                        continue
                    if _has_unresolved_location_separator(source, city_end):
                        continue
                    if _has_future_residence_suffix(source, city_end):
                        continue
                    if _has_historical_residence_suffix(source, city_end):
                        continue
                    if _has_temporal_residence_suffix_text(match.group("city")):
                        continue
                    city = _clean_city(match.group("city"))
                    if city:
                        candidates.append((city_start, city))

        collect_matches(source, 0)
        for boundary in re.finditer(r"(?<!\bSt)[.!?;]\s+", source, re.IGNORECASE):
            collect_matches(source[boundary.end() :], boundary.end())
        if candidates:
            return max(candidates, key=lambda candidate: candidate[0])[1]
        return ""

    if _has_conflicting_residence_address_targets(source) or _has_explicit_residence_multiplicity(source):
        return ""
    city = latest_match(CITY_CHANGE_PATTERNS)
    if city:
        return city
    if _has_ambiguous_residence_targets(source):
        return ""
    return latest_match(CITY_PATTERNS)


def _has_explicit_residence_multiplicity(source: str) -> bool:
    multiplicity_source = source
    question_answer = re.search(
        r"(?:\bwo\s+(?:(?:genau|eigentlich)\s+)?(?:wohnst|lebst)\s+du(?:\s+(?:genau|eigentlich|denn))?|"
        r"\bwo\s+in\s+(?:deutschland|österreich|oesterreich|schweiz)\s+"
        r"(?:wohnst|lebst)\s+du(?:\s+denn)?|"
        r"\bin\s+welcher\s+stadt\s+(?:wohnst|lebst)\s+du(?:\s+denn)?|"
        r"\ban\s+welchem\s+ort\s+(?:wohnst|lebst)\s+du(?:\s+denn)?|"
        r"\bwo\s+(?:bist|bleibst)\s+du\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)|"
        r"\bwo\s+ist\s+"
        r"(?:dein(?:e)?|euer(?:e)?|mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift|meldeadresse|zuhause|"
        r"zu\s+hause|daheim)|"
        r"\b(?:(?:dein(?:e)?|euer(?:e)?|mein(?:e)?|unser(?:e)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift|meldeadresse|zuhause|"
        r"zu\s+hause|daheim))"
        r"(?:\s+(?:ist|lautet))?\s*(?:eigentlich|genau|aktuell|derzeit)?\s*[?:]\s*"
        r"(?P<answer>[^.!?\n]{1,160})",
        source,
        re.IGNORECASE,
    )
    if question_answer:
        answer = question_answer.group("answer")
        if re.search(
            r"\b(?:und|oder)\s+(?:(?:in|bei)\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß'-]*",
            answer,
        ) and not re.search(r"\bund\s+(?:umgebung|region|nähe|naehe)\b", answer, re.IGNORECASE):
            return True
        separator = re.search(r"[,;]\s*(?P<second>[^,;.!?\n]+)", answer)
        if separator and not re.search(r"\d", answer[: separator.start()]):
            second_raw = separator.group("second").strip()
            if not re.match(
                r"(?i)^(?:aber|doch|jedoch|genauer\b|konkret\b|nämlich\b|naemlich\b|und\s+zwar\b|"
                r"besser\s+gesagt\b|sprich\b)",
                second_raw,
            ):
                second = _clean_city(second_raw)
                if second and second.casefold() not in (_NON_CITY_RESIDENCE_NAMES | _NON_CITY_REGION_NAMES):
                    return True
    multiplicity_source = re.sub(
        r"\ban\s+der\s+Oder\b",
        "",
        multiplicity_source,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bmanchmal\b", source, re.IGNORECASE) and re.search(
        r"\b(?:hauptsächlich|hauptsaechlich|überwiegend|ueberwiegend|vorwiegend|meistens|mehrheitlich|"
        r"primaer|primär|in\s+der\s+regel)\b",
        source,
        re.IGNORECASE,
    ):
        multiplicity_source = re.sub(r"\bmanchmal\b", "", source, flags=re.IGNORECASE)
    return bool(
        re.search(
            r"\b(?:wohne|wohnen|lebe|leben)\b[^.!?;\n]*\b(?:mal|manchmal|teils|teilweise|abwechselnd|zwischen|"
            r"oder|beziehungsweise|bzw\.?)\b|"
            r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnorte|wohnsitze)\b",
            multiplicity_source,
            re.IGNORECASE,
        )
    )


def _has_non_residential_label_prefix(source: str, pattern_start: int) -> bool:
    prefix = source[:pattern_start]
    if re.search(r"\b(?:dein(?:e)?|euer(?:e)?)\s*$", prefix, re.IGNORECASE) and re.match(
        r"\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\b",
        source[pattern_start:],
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            r"(?:\b(?:dienst\w*|beruf\w*|arbeits[-\s]?\w*)\s*|"
            r"\b(?:der|die|das|sein(?:e|en|em|er)?|ihr(?:e|en|em|er)?|deren)\s*|"
            r"\bkein(?:e|en|er|em)?\s+(?:fest(?:e|en|er|em)?\s*)?\s*)$",
            source[:pattern_start],
            re.IGNORECASE,
        )
    )


def _has_conflicting_residence_address_targets(source: str) -> bool:
    city_capture = r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[,.;!?]|$))"
    residence_patterns = (
        re.compile(
            rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:^|[.!?;,\n]\s*)(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz)\s+"
            rf"(?:ist|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:^|[.!?;,\n]\s*)(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz)\s+"
            r"(?!(?:ist|liegt|befindet\s+sich)\b)"
            rf"{city_capture}",
            re.IGNORECASE,
        ),
    )
    address_patterns = (
        re.compile(
            r"\b(?:mein(?:e)?|unser(?:e)?)\s*"
            r"(?:adresse|wohnadresse|wohnanschrift|anschrift)\s+"
            rf"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:meine|unsere)\s+"
            r"(?:adresse|wohnadresse|wohnanschrift|anschrift)\s+(?:in|bei)\s+"
            rf"{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            r"[,;]\s*(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz)\s+"
            rf"(?:ist|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?{city_capture}",
            re.IGNORECASE,
        ),
    )

    def collect(patterns: tuple[re.Pattern[str], ...]) -> set[str]:
        values: set[str] = set()
        for pattern in patterns:
            for match in pattern.finditer(source):
                city = _clean_city(match.group("city"))
                if city:
                    values.add(_city_comparison_key(city))
        return values

    residence_cities = collect(residence_patterns)
    address_cities = collect(address_patterns)
    return bool(residence_cities and address_cities and residence_cities.isdisjoint(address_cities))


def _has_ambiguous_residence_targets(source: str) -> bool:
    residence = r"(?:wohne|wohnen|lebe|leben|wohn|leb|gemeldet|registriert)"
    residence_targets: set[str] = set()
    target_patterns = (
        re.compile(
            rf"\b(?:ich|wir)\s+{residence}\s+(?:in|bei)\s+"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[,.;!?]|$|\b(?:und|aber|doch|jedoch)\b))",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+"
            r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[,.;!?]|$|\b(?:und|aber|doch|jedoch)\b))",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:zuhause|zu\s+hause|daheim)\s+"
            r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[,.;!?]|$|\b(?:und|aber|doch|jedoch)\b))",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:zuhause|zu\s+hause|daheim)\s+"
            r"(?!(?:ist|liegt|befindet|bleibt|heißt|heisst|nenn\w*|bezeichn\w*|genannt)\b)"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[,.;!?]|$))",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:zu\s+hause|zuhause|daheim)\s+bin\s+(?:ich|wir)\s+(?:in|bei)\s+"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[,.;!?]|$))",
            re.IGNORECASE,
        ),
    )
    for pattern in target_patterns:
        for match in pattern.finditer(source):
            city = _clean_city(match.group("city"))
            if city:
                residence_targets.add(_city_comparison_key(city))
    if len(residence_targets) > 1:
        return True
    bare_label_conflict = re.search(
        r"(?:^|[.!?;\n]\s*)(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*"
        r"(?::|=|,)?\s*(?P<first>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*(?:[,;]|\bund\b)\s*"
        r"(?!(?:aber|doch|jedoch|genauer\b|konkret\b|nämlich\b|naemlich\b|und\s+zwar\b|"
        r"umgebung\b|region\b|nähe\b|naehe\b|"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:geburtsort|geburtsstadt|heimat|heimatstadt|"
        r"herkunftsort|herkunftsstadt)\b))"
        r"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]*?)\s*(?:[.!?;,]|$)",
        source,
        re.IGNORECASE,
    )
    if bare_label_conflict:
        first = _clean_city(bare_label_conflict.group("first"))
        second_raw = bare_label_conflict.group("second").strip()
        second = _clean_city(bare_label_conflict.group("second"))
        if (
            first
            and not re.match(r"(?i)^(?:in|bei)\s+", second_raw)
            and second
            and second.casefold() not in (_NON_CITY_RESIDENCE_NAMES | _NON_CITY_REGION_NAMES)
        ):
            return True
    if re.search(
        rf"\b{residence}\s+(?:mal|teils|teilweise)\s+(?:in|bei)\s+[^,.;!?]+,\s*"
        r"(?:mal|teils|teilweise)\s+(?:in|bei)\s+[^,.;!?]+",
        source,
        re.IGNORECASE,
    ) or re.search(
        rf"\b{residence}\s+abwechselnd\s+(?:in|bei)\s+[^,.;!?]+\s+und\s+"
        r"(?:in|bei)\s+[^,.;!?]+",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:meine|unsere)\s+wohnorte?\s+(?:sind|liegen)\s+[^,.;!?]+\s+und\s+[^,.;!?]+",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"\b{residence}\s+zwischen\s+[^,.;!?]+\s+und\s+[^,.;!?]+",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^;.!?]+;\s*"
        r"[^;.!?]*(?:zuhause|zu\s+hause|daheim|wohnort|wohnsitz)\b"
        r"[^;.!?]*(?:in|bei)\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]*",
        source,
        re.IGNORECASE,
    ):
        return True
    for pattern in (
        re.compile(
            rf"\b{residence}\s+(?:in|bei)\s+(?P<first>[^,.;!?]{{1,80}})[,;]\s*"
            r"(?!(?:der|die|das|dem|den|des|aber|doch|jedoch|arbeite\w*|studier\w*|lern\w*|schlaf\w*|zieh\w*|"
            r"besuch\w*|pendl\w*|reis\w*|genauer\b|konkret\b|nämlich\b|naemlich\b|"
            r"und\s+zwar\b|besser\s+gesagt\b|sprich\b))"
            r"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*)\s*(?:[.!?;,]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
            r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?P<first>[^,.;!?]{1,80})[,;]\s*"
            r"(?!(?:der|die|das|dem|den|des|aber|doch|jedoch|arbeite\w*|studier\w*|lern\w*|schlaf\w*|zieh\w*|"
            r"besuch\w*|pendl\w*|reis\w*|genauer\b|konkret\b|nämlich\b|naemlich\b|"
            r"und\s+zwar\b|besser\s+gesagt\b|sprich\b))"
            r"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*)\s*(?:[.!?;,]|$)",
            re.IGNORECASE,
        ),
    ):
        comma_match = pattern.search(source)
        first = comma_match.groupdict().get("first", "") if comma_match else ""
        if first and re.search(
            r"(?i)(?:straße|strasse|weg|allee|gasse|platz|ufer|ring|chaussee|steig|promenade)\s+\d+[a-z]?\b",
            first,
        ):
            continue
        if comma_match and comma_match.group("second").casefold() not in (
            _NON_CITY_RESIDENCE_NAMES | _NON_CITY_REGION_NAMES
        ):
            return True
    if re.search(
        rf"\b{residence}\s+(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung)(?:\s+von)?|im\s+raum|"
        r"rund\s+um|nahe|unweit(?:\s+von)?|au(?:ßerhalb|sserhalb)(?:\s+von)?|am\s+stadtrand\s+von|im\s+umland(?:\s+von)?|"
        r"im\s+(?:norden|süden|osten|westen)(?:\s+von)?|am\s+rand(?:\s+von)?|"
        r"nord[-\s]?östlich\s+von|nord[-\s]?westlich\s+von|süd[-\s]?östlich\s+von|"
        r"süd[-\s]?westlich\s+von|"
        r"nördlich\s+von|südlich\s+von|östlich\s+von|westlich\s+von)\s+"
        r"[^,.;!?]{1,80}\s+und\s+"
        r"(?!nicht\w*\b|(?:ich\s+)?(?:wohne|lebe)\s+nicht\b|(?:(?:ich|wir)\s+)?arbeit\w*\b|"
        r"(?:(?:ich|wir)\s+)?studier\w*\b|(?:(?:ich|wir)\s+)?lern\w*\b|"
        r"(?:(?:ich|wir)\s+)?schlaf\w*\b|(?:(?:ich|wir)\s+)?mach\w*\b|"
        r"(?:(?:ich|wir)\s+)?komm\w*\b|(?:(?:ich|wir)\s+)?fahr\w*\b|"
        r"(?:(?:ich|wir)\s+)?geh\w*\b|(?:(?:ich|wir)\s+)?zieh\w*\b|"
        r"hab\w*\b|besuch\w*\b|verbring\w*\b|treff\w*\b|reis\w*\b|pend\w*\b|"
        r"seh\w*\b|übernacht\w*\b|uebernacht\w*\b)[\wÄÖÜäöüß'-]+",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+[^,.;!?]{1,80}\s+und\s+"
        r"(?!(?:(?:ich|wir)\s+)?(?:arbeit|studier|lern|schlaf|mach|komm|fahr|geh|zieh|hab|besuch|verbring|treff|reis|pendl|seh|übernacht|uebernacht)\w*\b)"
        r"(?:(?:in|bei)\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß'-]*",
        source,
        re.IGNORECASE,
    ):
        return True
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
            r"(?!nicht\w*\b|(?:ich\s+)?(?:wohne|lebe)\s+nicht\b|"
            r"bin\b|sein\b|sind\s+(?:beruflich|dienstlich|zum\s+arbeiten)\b|arbeit\w*\b|studier\w*\b|lern\w*\b|zieh\w*\b|"
            r"schlaf\w*\b|mach\w*\b|komm\w*\b|fahr\w*\b|geh\w*\b|"
            r"hab\w*\b|besuch\w*\b|verbring\w*\b|treff\w*\b|reis\w*\b|"
            r"pend\w*\b|seh\w*\b|übernacht\w*\b|uebernacht\w*\b|"
            r"unser(?:e)?\s+(?:wohnort|wohnsitz|hauptwohnsitz|arbeitsort)\b)[\wÄÖÜäöüß'-]+",
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


def _has_historical_residence_prefix(source: str, match_start: int) -> bool:
    prefix = source[:match_start]
    sentence = re.split(r"(?<!\bSt)[.!?;\n]\s*", prefix, flags=re.IGNORECASE)[-1]
    return bool(
        re.search(
            r"(?i)\b(?:ehemalig\w*|ehemals\b|frueh\w*|früh\w*|einstig\w*|vormalig\w*|damalig\w*|"
            r"alt\w*|vorherig\w*)\s*$",
            sentence,
        )
    ) or bool(re.search(r"(?i)\bwar(?:en)?(?:\s+\w+){0,3}\s*$", sentence))


def _has_future_residence_prefix(source: str, match_start: int, city_start: int | None = None) -> bool:
    prefix_end = city_start if city_start is not None else match_start
    prefix = source[:prefix_end]
    sentence = re.split(r"(?<!\d)(?<!\bSt)[.!?;\n]\s*", prefix, flags=re.IGNORECASE)[-1]
    clause = re.split(r"[,;]\s*", sentence)[-1]
    return bool(
        re.search(
            r"(?i)(?:\bab\s+(?:dem\s+)?(?:nächste\w*|naechste\w*|kommende\w*)\s+"
            r"(?:jahr\w*|monat\w*|woche\w*)\b|\bab\s+\d{4}\b|"
            r"\bab\s+(?:morgen|uebermorgen|übermorgen|sommer|winter|frühling|fruehling|herbst)\b|"
            r"\bab\s+(?:dem\s+)?\d{1,2}\.\d{1,2}\.\d{2,4}\b|"
            r"\bab\s+(?:dem\s+)?(?:\d{1,2}\.\s+)?(?:januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember|"
            r"sommer|winter|frühling|fruehling|herbst|weihnachten|ostern|neujahr)\b|"
            r"\bam\s+\d{1,2}\.\d{1,2}\.\d{2,4}\b|"
            r"\bam\s+(?:\d{1,2}\.\s+)?(?:januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember)\b|"
            r"\b(?:im|in)\s+(?:januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember|"
            r"sommer|winter|frühling|fruehling|herbst)\b|\bzu\s+(?:weihnachten|ostern|neujahr)\b|"
            r"\bseit\s+(?:morgen|uebermorgen|übermorgen)\b|\b(?:demnächst|demnaechst)\b|\bbald\b|"
            r"\b(?:nächste\w*|naechste\w*|kommende\w*)\s+jahr\w*\b|\bin\s+zukunft\b|"
            r"\b(?:künft\w*|kuenft\w*|zukünft\w*|zukuenft\w*|geplant\w*)\b)",
            clause,
        )
    )


def _has_historical_residence_suffix(source: str, city_end: int) -> bool:
    tail = source[city_end:]
    sentence = re.split(r"(?<!\bSt)[.!?;\n]", tail, maxsplit=1, flags=re.IGNORECASE)[0]
    return bool(
        re.match(
            r"(?i)\s+(?:(?:wohnhaft|ansässig|ansaessig)\s+)?(?:gewesen|worden|frueher|frühere?\b|"
            r"ehemals|damals|vormalig\w*)\b",
            sentence,
        )
    )


def _has_future_residence_suffix(source: str, city_end: int) -> bool:
    tail = source[city_end:]
    sentence = re.split(r"(?<!\bSt)[.!?;\n]", tail, maxsplit=1, flags=re.IGNORECASE)[0]
    return bool(
        re.match(
            r"(?i)\s+(?:ab\s+(?:dem\s+)?(?:nächste\w*|naechste\w*|kommende\w*)\s+"
            r"(?:jahr\w*|monat\w*|woche\w*)\b|ab\s+(?:morgen|uebermorgen|übermorgen|"
            r"sommer|winter|frühling|fruehling|herbst)|ab\s+\d{4}\b|"
            r"(?:künft\w*|kuenft\w*|zukünft\w*|zukuenft\w*|geplant\w*)\b)",
            sentence,
        )
    )


def _has_temporal_residence_suffix_text(value: str) -> bool:
    return bool(
        re.search(
            r"(?i)\s+(?:ab\s+(?:dem\s+)?(?:nächste\w*|naechste\w*|kommende\w*)\s+"
            r"(?:jahr\w*|monat\w*|woche\w*)|ab\s+(?:morgen|uebermorgen|übermorgen|"
            r"sommer|winter|frühling|fruehling|herbst)|ab\s+\d{4}|"
            r"(?:künft\w*|kuenft\w*|zukünft\w*|zukuenft\w*|geplant\w*|"
            r"frueher|früher|ehemals|damals|vormalig\w*)\s*\.?$)",
            str(value or "").strip(),
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
    if source.count(")") > source.count("("):
        source = re.sub(r"[.!?;,]+$", "", source).rstrip(")").rstrip()
    normalized_source = re.sub(r"\s+", " ", source).strip(" .,:;!?")
    known_compound_city = _KNOWN_COMPOUND_CITY_NAMES.get(normalized_source.casefold())
    if known_compound_city:
        return known_compound_city
    if re.search(r"(?i)\s+(?:oder|sowie|bzw\.?|beziehungsweise)\s+", source):
        return ""
    first_sentence = re.split(r"(?<!\bSt)[.!?;]\s+", source, maxsplit=1, flags=re.IGNORECASE)[0]
    if re.search(
        r"(?i)\b(?:auf\s+besuch|zu\s+besuch|im\s+urlaub|zum\s+urlaub|"
        r"f(?:ür|uer)\s+den\s+urlaub|als\s+(?:tourist|besucher))\b",
        first_sentence,
    ):
        return ""
    city = CITY_TRAILING_STOP_RE.sub("", source).strip(" .,:;!?")
    city = re.sub(r"\s+", " ", city)
    city = re.sub(
        r"(?i)\s+(?:offiziell|polizeilich|privat|dauerhaft|permanent|vorübergehend|vorlaeufig)$",
        "",
        city,
    ).strip()
    city = re.sub(r"\s+\d{5}(?:-\d{4})?$", "", city)
    city = re.split(r"(?<!\bSt)[.!?]\s+", city, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,:;!?")
    city = re.sub(r"(?i)^(?:in|bei)\s+", "", city)
    city = re.sub(r"(?i)(?<!er)(?:[-\s]+)(?:nähe|umgebung)\b$", "", city).strip()
    city = re.sub(
        rf"(?i)[-\s]+(?:{'|'.join(_CITY_AREA_SUFFIXES)})$",
        "",
        city,
    ).strip()
    city = _IRREGULAR_CITY_ADJECTIVE_BASES.get(city.casefold(), city)
    city = _GENITIVE_CITY_REPAIRS.get(city.casefold(), city)
    if not city or len(city) < 2 or len(city) > MAX_CITY_LENGTH:
        return ""
    if (
        city.casefold() in _NON_CITY_RESIDENCE_NAMES
        or city.casefold() in _NON_CITY_CONTEXT_TOKENS
        or city.casefold() in _NON_CITY_REGION_NAMES
    ):
        return ""
    if any(char.isdigit() for char in city):
        return ""
    if re.match(
        r"(?i)^(?:der|die|das|den|dem|des|dies(?:er|e|es)|jen(?:er|e|es)|"
        r"welch(?:er|e|es)|irgendein|mehrere|einige|manche|ohne|unbekannt\w*|"
        r"unbestimmt\w*|ab|wird|soll|geplant\w*|voraussichtlich|"
        r"(?:nächste\w*|naechste\w*|kommende\w*)\s+jahr\w*|"
        r"künftig|kuenftig|zukünftig|zukuenftig|"
        r"aktuell|derzeit|momentan|gerade|jetzt|nun|inzwischen|mittlerweile|unklar|egal|"
        r"nimmer|werktags|wochentags|hier|dort|da|sondern|"
        r"vielleicht|vermutlich|wahrscheinlich|wohl|angeblich|laut|derzeitig|ist|sind|bin|lautet|heißt|heisst|nennt|genannt|keineswegs|keinesfalls|niemals|nirgendwo|nirgends|nie|fast|beinahe|"
        r"möglicherweise|moeglicherweise|könnte|koennte|wäre|waere|würde|wuerde|"
        r"sollte|dürfte|duerfte|muss|müsste|muesste|nördlich|südlich|östlich|westlich|"
        r"nord[-\s]?östlich|nord[-\s]?westlich|süd[-\s]?östlich|süd[-\s]?westlich)\b",
        city,
    ):
        return ""
    if re.match(
        r"(?i)^(?:nahe|vor|hinter|innerhalb|außerhalb|ausserhalb|unter|aus|f(?:ür|uer)|"
        r"wegen|als|neben|mit|w(?:ährend|aehrend)|zusammen|auf|am|im)\b",
        city,
    ):
        return ""
    if re.search(
        r"(?i)\b(?:nicht(?:\s+mehr)?|kein(?:e|er|em|en)?|mein(?:e|er|em|en)?|"
        r"unser(?:e|er|em|en)?|ein(?:e|er|em|en)?|könnte|koennte|wäre|waere|"
        r"würde|wuerde|soll|sollte|dürfte|duerfte|muss|müsste|muesste)\b",
        city,
    ):
        return ""
    if re.search(r"(?i)\b(?:gewesen|worden|geblieben)\b", city):
        return ""
    if re.search(
        r"(?i)\b(?:arbeit\w*|beruflich|dienstlich|studier\w*|lern\w*|schule\w*|schlaf\w*|mach\w*|komm\w*|bin\w*|"
        r"fahr\w*|geh\w*|hab\w*|besuch\w*|verbring\w*|treff\w*|reis\w*|"
        r"pend\w*|seh\w*|übernacht\w*|uebernacht\w*)\b",
        city,
    ):
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
