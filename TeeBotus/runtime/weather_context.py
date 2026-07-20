from __future__ import annotations

import json
import hashlib
import re
import urllib.parse
import urllib.request
from copy import deepcopy
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
        "bis",
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
        "offiziell",
        "amtlich",
        "privat",
        "polizeilich",
        "dauerhaft",
        "permanent",
        "vorübergehend",
        "vorlaeufig",
        "gemeldet",
        "registriert",
        "ansässig",
        "ansaessig",
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
_RESIDENCE_ALIAS_WORDS = frozenset({"auch", "ebenfalls", "ebenso", "gleichfalls"})
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
        "nrw",
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
_CITY_AREA_ADJECTIVE_BASES = {
    "berliner": "Berlin",
    "hamburger": "Hamburg",
    "dresdner": "Dresden",
    "münchner": "München",
    "muenchner": "München",
    "kölner": "Köln",
    "koelner": "Köln",
    "frankfurter": "Frankfurt am Main",
}
_KNOWN_COMPOUND_CITY_NAMES = {
    "brandenburg an der havel": "Brandenburg an der Havel",
    "frankfurt an der oder": "Frankfurt an der Oder",
    "frankfurt (oder)": "Frankfurt (Oder)",
    "frankfurt am main": "Frankfurt am Main",
    "königstein im taunus": "Königstein im Taunus",
    "ludwigshafen am rhein": "Ludwigshafen am Rhein",
    "mülheim an der ruhr": "Mülheim an der Ruhr",
    "neustadt an der weinstrasse": "Neustadt an der Weinstraße",
    "rüdesheim am rhein": "Rüdesheim am Rhein",
    "halle (saale)": "Halle (Saale)",
    "halle saale": "Halle (Saale)",
    "st. georgen im schwarzwald": "St. Georgen im Schwarzwald",
    "wörth am rhein": "Wörth am Rhein",
    "weiden in der oberpfalz": "Weiden in der Oberpfalz",
    "weil am rhein": "Weil am Rhein",
    "neustadt bei coburg": "Neustadt bei Coburg",
    "buchholz in der nordheide": "Buchholz in der Nordheide",
    "freiburg im breisgau": "Freiburg im Breisgau",
    "freiberg am neckar": "Freiberg am Neckar",
    "burg auf fehmarn": "Burg auf Fehmarn",
    "dillingen an der donau": "Dillingen an der Donau",
    "neumarkt in der oberpfalz": "Neumarkt in der Oberpfalz",
    "mühlhausen/thüringen": "Mühlhausen/Thüringen",
    "muehlhausen/thueringen": "Mühlhausen/Thüringen",
    "schwedt/oder": "Schwedt/Oder",
    "wittstock/dosse": "Wittstock/Dosse",
}
_STREET_COMPOUND_CITY_PATTERN = (
    r"(?:Brandenburg\s+an\s+der\s+Havel|Frankfurt\s+an\s+der\s+Oder|"
    r"Frankfurt\s+\(Oder\)|"
    r"Frankfurt\s+am\s+Main|Königstein\s+im\s+Taunus|Ludwigshafen\s+am\s+Rhein|"
    r"Mülheim\s+an\s+der\s+Ruhr|Neustadt\s+an\s+der\s+Weinstraße|"
    r"Rüdesheim\s+am\s+Rhein|Wörth\s+am\s+Rhein|Weiden\s+in\s+der\s+Oberpfalz|"
    r"Weil\s+am\s+Rhein|Neustadt\s+bei\s+Coburg|Buchholz\s+in\s+der\s+Nordheide|"
    r"Freiburg\s+im\s+Breisgau|Freiberg\s+am\s+Neckar|Burg\s+auf\s+Fehmarn|"
    r"Dillingen\s+an\s+der\s+Donau|Neumarkt\s+in\s+der\s+Oberpfalz|"
    r"Mühlhausen/Thüringen|Muehlhausen/Thueringen|Schwedt/Oder|Wittstock/Dosse|"
    r"St\.\s+Georgen\s+im\s+Schwarzwald)"
)
_REGION_NAME_PATTERN = "|".join(
    re.escape(name) for name in sorted(_NON_CITY_REGION_NAMES, key=len, reverse=True)
)
_KNOWN_CITY_DISTRICT_BASES = {
    "berlin-mitte": "Berlin",
    "berlin-kreuzberg": "Berlin",
    "berlin (mitte)": "Berlin",
    "berlin (kreuzberg)": "Berlin",
    "berlin (prenzlauer berg)": "Berlin",
    "berlin kreuzberg": "Berlin",
    "berlin mitte": "Berlin",
    "berlin prenzlauer berg": "Berlin",
    "kreuzberg": "Berlin",
    "im prenzlauer berg": "Berlin",
    "prenzlauer berg": "Berlin",
    "hamburg-altona": "Hamburg",
    "hamburg (altona)": "Hamburg",
    "hamburg altona": "Hamburg",
    "köln-deutz": "Köln",
    "köln (deutz)": "Köln",
    "köln deutz": "Köln",
    "köln ehrenfeld": "Köln",
    "münchen-schwabing": "München",
    "münchen schwabing": "München",
    "frankfurt am main (sachsenhausen)": "Frankfurt am Main",
    "frankfurt am main sachsenhausen": "Frankfurt am Main",
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
    rf"(?:(?:schon\s+)?seit\s+{_RESIDENCE_DURATION}|schon\s+lange|schon\s+immer|seitdem|"
    r"(?:schon\s+)?seit\s+(?:gestern|heute|vorgestern)|jetzt|nun|nunmehr|aktuell|derzeit|gerade|grad|momentan|inzwischen|mittlerweile|zurzeit|zur\s+zeit|"
    r"weiterhin|nach\s+wie\s+vor|noch\s+immer|immer\s+noch|"
    rf"dauerhaft|permanent|langfristig|kurzfristig|befristet|unbefristet|vorläufig|vorlaeufig|endgültig|endgueltig|"
    rf"ständig|staendig|wieder|erneut|für\s+{_RESIDENCE_DURATION}|"
    r"zur\s+(?:miete|untermiete|zwischenmiete)|"
    r"bis\s+(?:heute|morgen|übermorgen|uebermorgen|auf\s+weiteres|"
    r"(?:zum\s+)?ende\s+der\s+woche|"
    r"zum\s+ende\s+(?:des\s+)?(?:monats|jahres)|"
    r"ende\s+(?:des\s+)?(?:monats|jahres)|(?:monats|jahres)ende|"
    r"(?:zum\s+)?jahresende)|"
    r"während\s+(?:(?:dieser|der|des)\s+)?(?:woche|wochen|monats|monate|monaten|zeit)|"
    r"vor(?:uebergehend|übergehend))"
)
_RESIDENCE_LOCATION_ADVERB = (
    r"(?:(?:hier|dort|da|direkt|nur|allein|überwiegend|ueberwiegend|"
    r"hauptsächlich|hauptsaechlich|vorwiegend|meistens|primär|primaer|normalerweise|"
    r"gewöhnlich|gewoehnlich|regulär|regulaer|üblicherweise|ueblicherweise|in\s+der\s+regel|"
    r"irgendwo|dahoam|erst|immer|"
    r"bisher|bislang|vorerst|zeitweise)|"
    r"(?:sicher|wirklich|definitiv|tatsächlich|tatsaechlich))"
)
_RESIDENCE_DISTANCE_PREFIX = (
    r"(?:(?:ungefähr|ungefaehr|ca\.?|circa|etwa|rund|knapp)\s+)?"
    r"(?:\d+(?:[,.]\d+)?|ein(?:e|en)?|ein\s+paar|mehrere|wenige|"
    r"null|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn|elf|"
    r"zwölf|zwoelf|dreizehn|vierzehn|fünfzehn|fuenfzehn|sechzehn|"
    r"siebzehn|achtzehn|neunzehn|zwanzig|hundert|tausend)\s*"
    r"(?:km|kilometer)\s+"
)
_PRIMARY_RESIDENCE_LABEL = r"(?:lebensmittelpunkt|hauptwohnsitz)"
_SECONDARY_RESIDENCE_LABEL = (
    r"(?:(?:zweite\w*\s+(?:wohn(?:sitz|ort)|wohnung)|"
    r"zweit\w*(?:wohn(?:sitz|ort)|wohnung))|"
    r"neben(?:wohn(?:sitz|ort)|wohnung)|ferien(?:wohn(?:sitz|ort)|wohnung\w*))"
)
_OTHER_PERSON_RESIDENCE_LABEL = (
    r"(?:freund\w*|partner\w*|eltern|familie|kind\w*|mutter\w*|vater\w*|"
    r"tochter\w*|sohn\w*|bruder\w*|schwester\w*|geschwister|frau\w*|"
    r"mann\w*|ehefrau\w*|ehemann\w*|ehepartner\w*|kolleg\w*|"
    r"mitbewohner\w*|nachbar\w*|chef\w*|vorgesetz\w*|oma\w*|opa\w*|"
    r"großeltern|grosseltern|cousin\w*|lebensgefährt\w*|lebensgefaehrt\w*|"
    r"betreuer\w*|therapeut\w*|arzt\w*)"
)
_OTHER_PERSON_REFERENCE = (
    r"(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?|"
    r"sein(?:e|en|em|er|es)?|ihr(?:e|en|em|er|es)?|deren|"
    r"der|die|das|ein(?:e|en|em|er|es)?)"
)
_OTHER_PERSON_NON_SELF_REFERENCE = (
    r"(?:sein(?:e|en|em|er|es)?|ihr(?:e|en|em|er|es)?|deren|dessen)"
)
_OTHER_PERSON_LOCATION_LABEL = (
    r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
    r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
    r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)"
)
_OTHER_RESIDENCE_OWNER_LABEL = (
    rf"(?:{_OTHER_PERSON_RESIDENCE_LABEL}|arbeitgeber\w*|firm\w*|unternehmen\w*|"
    r"betrieb\w*|organisation\w*|verein\w*|schule\w*|abteilung\w*|praxis\w*|"
    r"klinik\w*|universit(?:ät|aet)\w*|hochschule\w*|institut\w*|verband\w*|"
    r"behörde\w*|behoerde\w*|krankenhaus\w*)"
)
_OTHER_PERSON_FOREIGN_MARKER = (
    rf"(?:{_OTHER_PERSON_NON_SELF_REFERENCE}\s+{_OTHER_PERSON_LOCATION_LABEL}|"
    rf"{_OTHER_PERSON_REFERENCE}\s+{_OTHER_PERSON_RESIDENCE_LABEL}|"
    rf"{_OTHER_PERSON_LOCATION_LABEL}\s+von\s+{_OTHER_PERSON_RESIDENCE_LABEL}|"
    rf"(?:der|die|das|ein(?:e|en|em|er|es)?)?\s*"
    rf"{_OTHER_PERSON_LOCATION_LABEL}\s+(?:von\s+)?"
    rf"{_OTHER_PERSON_REFERENCE}\s+{_OTHER_PERSON_RESIDENCE_LABEL}|"
    rf"{_OTHER_PERSON_LOCATION_LABEL}\s+(?:von\s+)?"
    rf"{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}|"
    rf"{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\s+"
    r"(?:hat|haben)\s+(?:"
    rf"{_OTHER_PERSON_REFERENCE}\s+)?{_OTHER_PERSON_LOCATION_LABEL}|"
    rf"{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\s+"
    r"(?:ist|liegt|bleibt|befindet\s+sich)\s+(?:in|bei)|"
    rf"{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\s+"
    r"(?:ist|liegt|bleibt|befindet\s+sich)\s+"
    r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert|zuhause|zu\s+hause|daheim)\s+(?:in|bei)|"
    rf"{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\s+hat\s+"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+als\s+"
    rf"{_OTHER_PERSON_LOCATION_LABEL})"
)
_RESIDENCE_LABEL_DETERMINER = (
    r"(?:meine|unsere|mein|unser|der|die|das|ein(?:e|en|em|er|es)?)"
)
_RESIDENCE_LABEL_CURRENT_QUALIFIER = (
    r"aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
    r"jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*|tatsächlich\w*|"
    r"tatsaechlich\w*|dauerhaft\w*|permanent\w*|vorübergehend\w*|"
    r"vorlaeufig\w*|befristet\w*|unbefristet\w*|fest\w*|hauptsächlich\w*|"
    r"hauptsaechlich\w*|ständig\w*|staendig\w*|stabil\w*|momentan\w*"
)
_STREET_NUMBER_LABEL = r"(?:Nr\.?|Nummer|Hausnummer|Haus[- ]?Nr\.?|Hs\.?-?Nr\.?)"
_STREET_TYPE = (
    r"(?:straße|strasse|str\.?|weg|allee|gasse|platz|ufer|ring|chaussee|steig|promenade|"
    r"damm|kai|deich|hang|höhe|hoehe|markt|wall|tor|brücke|bruecke|bogen|zeile|stein|"
    r"winkel|kamp|koppel|dorf|feld|wiesen|park|terrasse|hof|berg|gürtel|guertel)"
)
_POSTAL_CODE = r"(?:[A-Z]{1,3}[- ]?)?\d{5}"
_COUNTRY_POSTAL_CODE = r"(?:[A-Z]{1,3}[- ]?)?\d{4,5}"
_LABELED_STREET_ADDRESS_DETAIL = (
    r"(?:"
    r"(?:hinterhaus|vorderhaus|hinterhof|vorderhof|seitenflügel|seitenfluegel|"
    r"(?:\d+\.\s*)?(?:og|eg|dg|ug|stock|etage|ober(?:geschoss)?|erdgeschoss|"
    r"dachgeschoss|untergeschoss|souterrain)|"
    r"(?:wohnung|whg\.?|apartment|appartement|einheit|aufgang|haus)\s*[A-Z0-9-]+)"
    r"(?:\s+(?:links|rechts))?"
    r")"
)
_LABELED_STREET_ADDRESS_CORE = (
    r"(?:"
    rf"[^,.;!?]{{1,100}}?{_STREET_TYPE}\s+|"
    rf"{_STREET_TYPE}\s+(?:"
    r"[^,.;!?]{1,100}?\d{1,2}\.\s+[^,.;!?]{1,100}?|"
    r"[^,.;!?]{1,100}?)\s+|"
    r"(?:am|an der|an den|auf der|auf dem|auf den|unter der|unter den|in der|in den|der|"
    r"im|zum|zur|vom|von der|vor der|hinter der)\s+(?:"
    r"[^,.;!?]{1,100}?\d{1,2}\.\s+[^,.;!?]{1,100}?|"
    r"[^,.;!?]{1,100}?)\s+"
    r")"
    rf"(?:{_STREET_NUMBER_LABEL}\s*)?\d+[a-z]?(?:[/-]\s*\d+[a-z]?|\s+[a-z])?(?:,\s*{_LABELED_STREET_ADDRESS_DETAIL})*"
)
_LABELED_STREET_ADDRESS = rf"{_LABELED_STREET_ADDRESS_CORE}(?:\s*,\s*|\s+)(?:{_POSTAL_CODE}\s+)?"
_AREA_BEFORE_STREET_PREFIX = (
    r"(?:im\s+(?:nördlichen|noerdlichen|südlichen|suedlichen|östlichen|"
    r"oestlichen|westlichen|nordöstlichen|nordoestlichen|nordwestlichen|"
    r"südöstlichen|suedöstlichen|südwestlichen|suedwestlichen)\s+|"
    r"im\s+(?:norden|süden|sueden|osten|westen|nordosten|nordwesten|"
    r"südosten|suedosten|südwesten|suedwesten)\s+|"
    r"im\s+(?:stadtteil|bezirk|stadtviertel|viertel)\s+[^,.;!?]{1,80}?\s*"
    r"(?:(?:in|bei)\s+|,\s*))"
)
_AREA_BEFORE_STREET_CITY = (
    rf"(?P<city>(?:{_STREET_COMPOUND_CITY_PATTERN}|"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?))s?(?:\s+(?:in|an|auf|unter)\s+|,\s*)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)"
)
_AREA_RELATION_NOUNS = (
    r"(?:stadtgebiet|stadtteil|stadtviertel|bezirk|viertel|innenstadt|stadtmitte|"
    r"stadtrand|rand|vorstadt|vorort|umland|stadtzentrum|zentrum|raum|region|gebiet|gegend)"
)
_ATTRIBUTIVE_AREA_BEFORE_STREET_CITY = (
    rf"(?P<city>(?:{_STREET_COMPOUND_CITY_PATTERN}|"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?))(?:er|s)\s+"
    rf"{_AREA_RELATION_NOUNS}\s+(?:[^,.;!?]{{1,80}}?\s+)?"
    r"(?:in|an|auf|unter)\s+"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)"
)
_GENITIVE_AREA_BEFORE_STREET_CITY = (
    rf"(?:im|in\s+der)\s+{_AREA_RELATION_NOUNS}\s+"
    rf"(?P<city>(?:{_STREET_COMPOUND_CITY_PATTERN}|"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?))s?(?:\s+(?:in|an|auf|unter)\s+|,\s*)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)"
)
_GENITIVE_AREA_NAME_BEFORE_STREET_CITY = (
    rf"(?:im|in\s+der)\s+{_AREA_RELATION_NOUNS}\s+"
    r"[^,.;!?]{1,80}?\s+"
    rf"(?P<city>(?:{_STREET_COMPOUND_CITY_PATTERN}|"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?))s?,\s*"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)"
)
_POSTAL_CITY_BEFORE_STREET = (
    rf"{_POSTAL_CODE}\s+"
    rf"(?P<city>(?:{_STREET_COMPOUND_CITY_PATTERN}|"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?))(?:\s+(?:in|an|auf|unter)\s+|,\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*(?:[.!?;,]|wohnhaft|ansässig|ansaessig|gemeldet|registriert|$))"
)
_COUNTRY_CITY_BEFORE_STREET = (
    r"(?:in\s+(?:der\s+)?)?(?:deutschland|österreich|oesterreich|schweiz)\s*,\s*"
    r"(?:(?:in|bei)\s+)?"
    rf"(?:{_COUNTRY_POSTAL_CODE}\s+)?"
    rf"(?P<city>(?:{_STREET_COMPOUND_CITY_PATTERN}|"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?))(?:\s+(?:in|an|auf|unter)\s+|,\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*(?:[.!?;,]|wohnhaft|ansässig|ansaessig|gemeldet|registriert|$))"
)
_PARENTHESIZED_AREA_STREET_ADDRESS = re.compile(
    r"\b(?:im|in\s+der)\s+(?:stadtteil|bezirk|stadtviertel|viertel)\s+"
    r"[^,.;!?()]{1,80}?\(\s*"
    rf"(?P<city>(?:{_STREET_COMPOUND_CITY_PATTERN}|"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?))\s*\)"
    rf"(?=\s*,\s*{_LABELED_STREET_ADDRESS_CORE}(?=\s*[.!?;,]|$))",
    re.IGNORECASE,
)
_PARENTHESIZED_STREET_DETAIL = re.compile(
    rf"(?P<address>{_LABELED_STREET_ADDRESS_CORE})\s*\(\s*"
    rf"{_LABELED_STREET_ADDRESS_DETAIL}\s*\)(?=\s*(?:[,.;!?]|(?:auf|nach|statt|sondern|aber|und|gezogen|umgezogen|übersiedelt|uebergesiedelt)\b|$))",
    re.IGNORECASE,
)
_CITY_CHANGE_CITY_FRAGMENT = (
    rf"(?:(?:{_POSTAL_CODE})\s+)?(?:{_STREET_COMPOUND_CITY_PATTERN}|[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)"
)
_CITY_CHANGE_CITY_BEFORE_STREET_MOVE = re.compile(
    r"\b(?:"
    r"(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+"
    r"(?:wechselte|wurde)\s+von\s+|"
    r"(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+hat\s+sich\s+von\s+|"
    r"(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:meine|unsere)\s+"
    r"(?:wohnadresse|wohnanschrift|adresse)\s+von\s+"
    rf")(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+(?:auf|nach)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*(?:geändert|geaendert|verlagert|umgemeldet|aktualisiert|[.!?;,]|$))",
    re.IGNORECASE,
)
_CITY_CHANGE_CITY_BEFORE_STREET_MOVE_FROM = re.compile(
    r"\b(?:ich|wir)\s+(?:bin|sind)\s+von\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+nach\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s+(?:gezogen|umgezogen|übersiedelt|uebergesiedelt)\b|\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_CURRENT_CITY_BEFORE_STREET = re.compile(
    r"\b(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+"
    r"(?:ist|lautet)\s+(?:jetzt|nun|aktuell|derzeit|inzwischen)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+statt\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_OLD_NEW_CITY_BEFORE_STREET = re.compile(
    r"\b(?:meine|unsere)\s+(?:alte|ehemalige|frühere|fruehere)\s+"
    r"wohnadresse\s+war\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*,\s*"
    r"(?:meine|unsere)\s+(?:neue|aktuelle|jetzige)\s+"
    r"(?:wohnadresse\s+)?ist\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_FORMER_ADDRESS_CURRENT_CITY = re.compile(
    r"\b(?:meine|unsere)\s+(?:alte|ehemalige|frühere|fruehere)\s+"
    r"(?:adresse|anschrift)\s+war\s+"
    r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]\s*"
    r"(?:meine|unsere)\s+(?:neue|aktuelle|jetzige|derzeitige)\s+"
    r"(?:(?:adresse|anschrift)\s+)?(?:ist|lautet)\s+"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_LABELLED_CITY_BEFORE_STREET = re.compile(
    r"\b(?:wohnadresse|wohnanschrift|anschrift|adresse)\s*:\s*"
    r"(?:vorher|früher|frueher|zuvor|ehemals)\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*,\s*"
    r"(?:jetzt|nun|aktuell|derzeit|inzwischen)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_LABELLED_DIRECTION_CITY_BEFORE_STREET = re.compile(
    r"\b(?:wohnadresse|wohnanschrift|anschrift|adresse)\s+"
    r"(?:geändert|geaendert|verlagert|umgemeldet|aktualisiert)\s*:?\s*"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+(?:auf|nach)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_DIRECTIONAL_CITY_BEFORE_STREET = re.compile(
    r"\bvon\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+nach\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"\s*:\s*(?:neue|aktuelle|jetzige)\s+"
    r"(?:wohnadresse|wohnanschrift|adresse)\b",
    re.IGNORECASE,
)
_CITY_CHANGE_MOVE_FROM_CITY_BEFORE_STREET = re.compile(
    r"(?<!ziehe\s)(?<!ziehen\s)(?<!ziehe\sgerade\s)(?<!ziehen\sgerade\s)\b"
    r"(?:(?:ich|wir)\s+(?:bin|sind)\s+)?(?:aus|von)\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}(?:\s+bin\s+ich)?\s+nach\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s+(?:gezogen|umgezogen|übersiedelt|uebergesiedelt)\b|\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_ZOG_CITY_BEFORE_STREET = re.compile(
    r"\b(?:ich|wir)\s+zog(?:en)?\s+von\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+nach\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_MOVE_LABEL_CITY_BEFORE_STREET = re.compile(
    r"\b(?:mein(?:e)?|unser(?:e)?)?\s*umzug\s+von\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+nach\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*[:;,]\s*"
    r"(?:neue|aktuelle|jetzige)\s+(?:wohnadresse|wohnanschrift|adresse)\b",
    re.IGNORECASE,
)
_CITY_CHANGE_CURRENT_AS_RESIDENCE_CITY_BEFORE_STREET = re.compile(
    r"\b(?:ich|wir)\s+hab(?:e|en)?\s+(?:jetzt|nun|aktuell|derzeit)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+als\s+"
    r"(?:(?:meine|unsere)\s+)?(?:wohnadresse|wohnanschrift|adresse)\s+statt\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_UPDATED_NEW_FIRST_CITY_BEFORE_STREET = re.compile(
    r"\b(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+"
    r"hat\s+sich\s+(?:geändert|geaendert|verlagert|aktualisiert)\s*:\s*"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*,\s*"
    r"(?:früher|frueher|vorher|zuvor|ehemals|alt)\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_CURRENT_NOT_MORE_CITY_BEFORE_STREET = re.compile(
    r"\b(?:die|meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+"
    r"ist\s+(?:jetzt|nun|aktuell|derzeit)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+(?:und\s+)?nicht\s+mehr\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_OLD_PRONOUN_CURRENT_CITY_BEFORE_STREET = re.compile(
    r"\b(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+war\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*[,.!?;]\s*"
    r"(?:"
    r"(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|seitdem)\s+)?"
    r"(?:ist|lautet|bleibt(?:\s+aber)?)\s+(?:(?:sie|diese|die)\s+)?|"
    r"(?:sie|diese|die)\s+(?:ist|lautet|bleibt(?:\s+aber)?)\s+"
    r"(?:jetzt|nun|aktuell|derzeit|inzwischen|seitdem)?\s*"
    r")"
    r"(?:(?:in|bei)\s+)?"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_LEADING_OLD_PRONOUN_CURRENT_CITY_BEFORE_STREET = re.compile(
    r"\b(?:früher|frueher|zuvor|ehemals)\s+war\s+"
    r"(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*[,.;!?]\s*"
    r"(?:jetzt|nun|aktuell|derzeit|inzwischen)\s+"
    r"(?:ist|lautet|bleibt(?:\s+aber)?)\s+(?:(?:sie|diese|die)\s+)?"
    r"(?:(?:in|bei)\s+)?"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_CITY_BEFORE_RESIDENCE_LABEL = re.compile(
    r"\b"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?\s+"
    r"war\s+(?:meine|unsere)\s+(?:alte|ehemalige|frühere|fruehere)\s+"
    r"(?:wohnadresse|wohnanschrift|adresse)\s*[,;]\s*"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?\s+"
    r"ist\s+(?:jetzt|nun|aktuell|derzeit|inzwischen)\s+"
    r"(?:meine|unsere)\s+(?:neue|aktuelle|jetzige)\s+"
    r"(?:wohnadresse|wohnanschrift|adresse)\b"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_STREET_BEFORE_RESIDENCE_LABEL = re.compile(
    r"\b"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+war\s+"
    r"(?:meine|unsere)\s+(?:alte|ehemalige|frühere|fruehere)\s+"
    r"(?:wohnadresse|wohnanschrift|adresse)\s*[,;]\s*"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+ist\s+"
    r"(?:jetzt|nun|aktuell|derzeit|inzwischen)\s+"
    r"(?:meine|unsere)\s+(?:neue|aktuelle|jetzige)"
    r"(?:\s+(?:wohnadresse|wohnanschrift|adresse))?\b"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_FORMER_LABEL_STREET_BEFORE_CURRENT = re.compile(
    r"\b(?:meine|unsere)\s+(?:alte|ehemalige|frühere|fruehere)\s+"
    r"(?:wohnadresse|wohnanschrift|adresse)\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+ist\s+vorbei\s*[,;]\s*"
    r"(?:jetzt|nun|aktuell|derzeit|inzwischen)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_STREET_BEFORE_LABEL_CURRENT_CITY = re.compile(
    r"\b"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+war\s+"
    r"(?:meine|unsere)\s+(?:alte|ehemalige|frühere|fruehere)\s+"
    r"(?:wohnadresse|wohnanschrift|adresse)\s*[,;]\s*"
    r"(?:jetzt|nun|heute|aktuell|derzeit|inzwischen)?\s*"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_STREET_BEFORE_LABEL_NOT_MORE = re.compile(
    r"\b"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+ist\s+nicht\s+mehr\s+"
    r"(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s*[,;]\s*"
    r"(?:sondern\s+)?(?:jetzt|nun|heute|aktuell|derzeit|inzwischen)?\s*"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_COLON_LABELLED_OLD_NEW_STREET = re.compile(
    r"\b(?:(?:meine|unsere)\s+)?(?:alte|ehemalige|frühere|fruehere)\s+"
    r"(?:wohnadresse|wohnanschrift|adresse)\s*:\s*"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*[.!?;,]\s*"
    r"(?:(?:meine|unsere)\s+)?(?:neue|aktuelle|jetzige)\s*"
    r"(?:(?:wohnadresse|wohnanschrift|adresse)\s*)?:\s*"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_LABELLED_ALT_NEW_COLON_STREET = re.compile(
    r"\b(?:wohnadresse|wohnanschrift|adresse)\s+(?:alt|früher|frueher|vorher)\s*:\s*"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*[.!?;,]\s*"
    r"(?:wohnadresse|wohnanschrift|adresse)\s+(?:neu|aktuell|jetzt)\s*:\s*"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_LABELLED_TEMPORAL_INLINE_CITY = re.compile(
    r"\b(?:wohnadresse|wohnanschrift|adresse)\s+"
    r"(?:(?:alt|früher|frueher|vorher)\s+)?"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*[,;]\s*"
    r"(?:heute|jetzt|nun|aktuell|derzeit|inzwischen)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_LABELLED_FROM_TO_STREET = re.compile(
    r"\b(?:wohnadresse|wohnanschrift|anschrift|adresse)\s+von\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+(?:zu|nach|auf)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+"
    r"(?:geändert|geaendert|verlegt|verlagert|umgemeldet|aktualisiert)\b"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_PASSIVE_LABELLED_FROM_TO_STREET = re.compile(
    r"\b(?:die|meine|unsere)?\s*(?:wohnadresse|wohnanschrift|anschrift|adresse)\s+"
    r"wurde\s+(?:aus|von)\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+(?:nach|zu|auf)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+"
    r"(?:verlegt|verlagert|geändert|geaendert|umgemeldet|aktualisiert)\b"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_NOMINAL_MOVE_LABELLED_STREET = re.compile(
    r"\b(?:der|ein|der\s+)?\s*umzug\s+der\s+"
    r"(?:wohnadresse|wohnanschrift|anschrift|adresse)\s+von\s+"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+nach\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s+ist\s+erfolgt\b"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_CITY_CHANGE_LABELLED_COLON_SEPARATOR_STREET = re.compile(
    r"\b(?:wohnadresse|wohnanschrift|anschrift|adresse)\s*:\s*"
    rf"(?P<old_city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}\s*(?:->|nach|auf)\s*"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_MAIN_RESIDENCE_CITY_BEFORE_STREET = re.compile(
    r"\b(?:meine|unsere|die)\s+hauptwohnung\s+"
    r"(?:ist|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*(?:[.!?;,]|und\s+(?:die|meine|unsere)\s+))",
    re.IGNORECASE,
)
_MAIN_RESIDENCE_CITY = re.compile(
    r"\b(?:meine|unsere|die)\s+hauptwohnung\s+"
    r"(?:ist|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
    r"(?=\s*(?:[.!?;,]|\b(?:und|sowie)\b|$))",
    re.IGNORECASE,
)
_COMPOUND_CITY_RESIDENCE = re.compile(
    r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
    rf"(?P<city>{_STREET_COMPOUND_CITY_PATTERN})"
    r"(?=\s*(?:[.!?;,]|(?:in|an|auf|unter)\s+|$))",
    re.IGNORECASE,
)
_COMPOUND_CITY_CONTRAST_RESIDENCE = re.compile(
    r"\b(?:(?:aber|doch|jedoch)\s+)?(?:(?:ich|wir)\s+)?"
    r"(?:wohne|wohnen|lebe|leben)\s+(?:aber\s+)?(?:in|bei)\s+"
    rf"(?P<city>{_STREET_COMPOUND_CITY_PATTERN})"
    r"(?=\s*(?:[.!?;,]|(?:in|an|auf|unter)\s+|$))",
    re.IGNORECASE,
)
_QUALIFIED_RESIDENCE = re.compile(
    r"\b(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+(?:aber\s+)?"
    r"(?:beruflich|dienstlich)\s+(?:in|bei)\s+"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
    r"(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_CURRENT_RESIDENCE_LABEL_CITY = re.compile(
    r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
    r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|adresse|"
    r"wohnadresse|wohnanschrift|anschrift)\s+"
    r"(?:ist|lautet|liegt|befindet\s+sich|bleibt)\s+"
    r"(?:jetzt|nun|aktuell|derzeit|momentan|gegenwärtig|gegenwaertig)\s+"
    r"(?:(?:in|bei)\s+)?"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
    r"(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_LABELED_COMPOUND_RESIDENCE_CITY = re.compile(
    r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
    r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
    r"adresse|wohnadresse|wohnanschrift|anschrift)\s+"
    r"(?:ist|lautet|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
    rf"(?P<city>{_STREET_COMPOUND_CITY_PATTERN})"
    r"(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_GENITIVE_RESIDENCE_ADDRESS_CITY = re.compile(
    r"\b(?:die|der|das|eine|meine|unsere)?\s*"
    r"(?:adresse|wohnadresse|wohnanschrift|anschrift|ort)\s+"
    r"(?:meines|meiner|unseres|unserer)\s+"
    r"(?:wohnort(?:s|es)?|wohnsitz(?:es)?|hauptwohnsitz(?:es)?|"
    r"lebensmittelpunkt(?:s|es)?|wohnung|zuhauses?)\s+"
    r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
    r"(?:(?:in|bei)\s+)?"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_RELATIVE_RESIDENCE_REGISTRATION_CITY = re.compile(
    r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
    r"(?:dort|da|hier)\s*,?\s*wo\s+"
    r"(?:meine|unsere)\s+"
    r"(?:meldeadresse|meldeanschrift|meldesitz)\s+(?:in|bei)\s+"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
    r"(?:ist|liegt|befindet\s+sich)\b",
    re.IGNORECASE,
)
_INVERTED_RELATIVE_RESIDENCE_CITY = re.compile(
    r"(?:"
    r"\bwo\s+(?:ich|wir)\s+(?:gemeldet|registriert|wohnhaft|ansässig|ansaessig)\s+"
    r"(?:bin|sind)\s*,?\s*(?:da|dort|hier)\s+"
    r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)"
    r"|"
    r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:dort|da|hier)\s*,?\s*wo\s+"
    r"(?:ich|wir)\s+(?:meinen|unseren)\s+"
    r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt)\s+"
    r"(?:habe|haben)"
    r")\s*[:=,]\s*(?:(?:in|bei)\s+)?"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_SHORT_SELF_RESIDENCE_AFTER_OTHER_PERSON_CITY = re.compile(
    rf"\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
    r"(?:wohnt|wohnen|lebt|leben|ist|sind)\s+(?:in|bei)\s+"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s*"
    r"(?:(?:[,;]\s*(?:und|sowie|aber|doch|jedoch|während|waehrend)?|"
    r"(?:und|sowie|aber|doch|jedoch|während|waehrend))\s*)"
    r"(?:ich|wir)\s+(?:in|bei)\s+"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:wohne|wohnen|lebe|leben)\b|[.!?;,]|$)",
    re.IGNORECASE,
)
_SHORT_SELF_RESIDENCE_AFTER_OTHER_PERSON_LABEL_CITY = re.compile(
    rf"\b(?:der|die|das|ein(?:e|en|em|er|es)?)?\s*"
    rf"{_OTHER_PERSON_LOCATION_LABEL}\s+"
    rf"{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}"
    r"(?:\s+(?:ist|liegt|bleibt|lautet|befindet\s+sich)\s+(?:(?:in|bei)\s+)?|"
    r"\s*[:=]\s*(?:(?:in|bei)\s+)?)"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s*"
    r"(?:(?:[,;]\s*(?:und|sowie|aber|doch|jedoch|während|waehrend)?|"
    r"(?:und|sowie|aber|doch|jedoch|während|waehrend))\s*)"
    r"(?:ich|wir)\s+(?:in|bei)\s+"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:wohne|wohnen|lebe|leben)\b|[.!?;,]|$)",
    re.IGNORECASE,
)
_TEMPORAL_REGISTERED_CITY = re.compile(
    rf"\b(?:schon\s+)?seit\s+{_RESIDENCE_DURATION}\s+"
    r"(?:(?:ich|wir)\s+(?:bin|sind)|(?:bin|sind)\s+(?:ich|wir))\s+(?:in|bei)\s+"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
    r"(?:gemeldet|registriert)\b",
    re.IGNORECASE,
)
_INVERTED_REGISTERED_CITY = re.compile(
    r"(?:^|[.!?;,:]\s*)"
    r"(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|dauerhaft\w*|aktuell\w*)\s+)?"
    r"(?:gemeldet|registriert)\s+(?:bin|sind)\s*(?:ich|wir)\s*"
    r"(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|dauerhaft\w*|aktuell\w*)\s+)?"
    r"(?::\s*|(?:in|bei)\s+)"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_DIRECT_RESIDENCE_REGISTRATION_LABEL_PAIR = re.compile(
    rf"(?:^|[.!?;\n]\s*)(?:{_RESIDENCE_LABEL_DETERMINER}\s+)?"
    r"(?P<first_label>wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
    r"meldeadresse|meldeanschrift|meldesitz)"
    r"\s*(?::|=|,|\s+)\s*(?:(?:in|bei)\s+)?"
    r"(?P<first_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]\s*"
    r"(?:(?:aber|doch|jedoch|sondern)\s+)?"
    rf"(?:{_RESIDENCE_LABEL_DETERMINER}\s+)?"
    r"(?P<second_label>wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
    r"meldeadresse|meldeanschrift|meldesitz)"
    r"\s*(?::|=|,|\s+)\s*(?:(?:in|bei)\s+)?"
    r"(?P<second_city>(?!(?:auch|ebenfalls|ebenso|gleichfalls)(?=\s*(?:[.!?;,]|$)))"
    r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_DIRECT_RESIDENCE_REGISTRATION_LABEL_ALIAS_PAIR = re.compile(
    rf"(?:^|[.!?;\n]\s*)(?:{_RESIDENCE_LABEL_DETERMINER}\s+)?"
    r"(?P<first_label>wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
    r"meldeadresse|meldeanschrift|meldesitz)"
    r"\s*(?::|=|,|\s+)\s*(?:(?:in|bei)\s+)?"
    r"(?P<first_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]\s*"
    r"(?:(?:aber|doch|jedoch|sondern)\s+)?"
    rf"(?:{_RESIDENCE_LABEL_DETERMINER}\s+)?"
    r"(?P<second_label>wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
    r"meldeadresse|meldeanschrift|meldesitz)"
    r"\s*(?::|=|,|\s+)\s*(?:auch|ebenfalls|ebenso|gleichfalls)(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_CITY_BEFORE_RESIDENCE_LABEL_WITH_LAUTET = re.compile(
    r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+lautet\s+"
    r"(?:mein(?:e)?|unser(?:e)?)\s+"
    r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
    re.IGNORECASE,
)
_LABELED_COUNTRY_CITY = re.compile(
    rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER}\s+)?"
    r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
    r"adresse|wohnadresse|wohnanschrift|anschrift)\s*"
    r"(?:(?::|=|,)\s*(?:in\s+)?|"
    r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:in\s+)?|in\s+)"
    r"(?:deutschland|österreich|oesterreich|(?:der\s+)?schweiz)\s*[,;]\s*"
    r"(?:(?:genauer(?:\s+gesagt)?|konkret|nämlich|naemlich|und\s+zwar|"
    r"besser\s+gesagt|sprich)\s*:?[ \t]+)?"
    r"(?:(?:in|bei)\s+)?"
    rf"(?:{_COUNTRY_POSTAL_CODE}\s+)?"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
    r"(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_REGIONAL_PREFIX_RESIDENCE = re.compile(
    r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|im)\s+"
    rf"(?:{_REGION_NAME_PATTERN})\s*,\s*(?:in|bei)\s+"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
    r"(?=\s*(?:[.!?;,]|$))",
    re.IGNORECASE,
)
_HAVE_PRIMARY_HOME_CITY_BEFORE_STREET = re.compile(
    r"\b(?:ich|wir)\s+hab(?:e|en)?\s+"
    r"(?:(?:meine|unsere|eine|ein|die|das)\s+)?wohnung\s+"
    r"(?:in|bei)\s+"
    rf"(?P<city>{_CITY_CHANGE_CITY_FRAGMENT})(?:\s+\([^)]{{1,30}}\))?"
    r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
    rf"{_LABELED_STREET_ADDRESS_CORE}"
    r"(?=\s*[.!?;,]|$)",
    re.IGNORECASE,
)
_HAVE_PRIMARY_HOME_CITY = re.compile(
    r"\b(?:ich|wir)\s+hab(?:e|en)?\s+"
    r"(?:meine|unsere|eine|ein)\s+hauptwohnung\s+(?:in|bei)\s+"
    r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
    r"(?=\s*(?:und|[,;]|$))",
    re.IGNORECASE,
)

CITY_CHANGE_PATTERNS = (
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+nicht\s+mehr\s+(?:in|bei)\s+"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+\([^)]{1,30}\))?"
        r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}\s*,\s*"
        r"(?:sondern|aber|jetzt)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+\([^)]{1,30}\))?"
        r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    _LABELED_COUNTRY_CITY,
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]\s*"
        r"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_SECONDARY_RESIDENCE_LABEL}\b",
        re.IGNORECASE,
    ),
    _CITY_CHANGE_CITY_BEFORE_STREET_MOVE,
    _CITY_CHANGE_CITY_BEFORE_STREET_MOVE_FROM,
    _CITY_CHANGE_CURRENT_CITY_BEFORE_STREET,
    _CITY_CHANGE_OLD_NEW_CITY_BEFORE_STREET,
    _CITY_CHANGE_LABELLED_CITY_BEFORE_STREET,
    _CITY_CHANGE_LABELLED_DIRECTION_CITY_BEFORE_STREET,
    _CITY_CHANGE_DIRECTIONAL_CITY_BEFORE_STREET,
    _CITY_CHANGE_MOVE_FROM_CITY_BEFORE_STREET,
    _CITY_CHANGE_ZOG_CITY_BEFORE_STREET,
    _CITY_CHANGE_MOVE_LABEL_CITY_BEFORE_STREET,
    _CITY_CHANGE_CURRENT_AS_RESIDENCE_CITY_BEFORE_STREET,
    _CITY_CHANGE_UPDATED_NEW_FIRST_CITY_BEFORE_STREET,
    _CITY_CHANGE_CURRENT_NOT_MORE_CITY_BEFORE_STREET,
    _CITY_CHANGE_OLD_PRONOUN_CURRENT_CITY_BEFORE_STREET,
    _CITY_CHANGE_LEADING_OLD_PRONOUN_CURRENT_CITY_BEFORE_STREET,
    _CITY_CHANGE_CITY_BEFORE_RESIDENCE_LABEL,
    _CITY_CHANGE_FORMER_ADDRESS_CURRENT_CITY,
    _CITY_CHANGE_STREET_BEFORE_RESIDENCE_LABEL,
    _CITY_CHANGE_FORMER_LABEL_STREET_BEFORE_CURRENT,
    _CITY_CHANGE_STREET_BEFORE_LABEL_CURRENT_CITY,
    _CITY_CHANGE_STREET_BEFORE_LABEL_NOT_MORE,
    _CITY_CHANGE_COLON_LABELLED_OLD_NEW_STREET,
    _CITY_CHANGE_LABELLED_ALT_NEW_COLON_STREET,
    _CITY_CHANGE_LABELLED_TEMPORAL_INLINE_CITY,
    _CITY_CHANGE_LABELLED_FROM_TO_STREET,
    _CITY_CHANGE_PASSIVE_LABELLED_FROM_TO_STREET,
    _CITY_CHANGE_NOMINAL_MOVE_LABELLED_STREET,
    _CITY_CHANGE_LABELLED_COLON_SEPARATOR_STREET,
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+von\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+auf\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s+(?:geändert|geaendert|umgemeldet|aktualisiert)\b|\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+"
        r"(?:ist|lautet)\s+(?:jetzt|nun|aktuell|derzeit)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+statt\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+(?:wohnadresse|wohnanschrift|adresse)\s+wurde\s+von\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+auf\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s+(?:geändert|geaendert|umgemeldet|aktualisiert)\b|\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnadresse|wohnanschrift|adresse|wohnort|wohnsitz)\s+hat\s+sich\s+von\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+nach\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s+(?:geändert|geaendert|verlagert)\b|\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+(?:alte|ehemalige|frühere|fruehere)\s+wohnadresse\s+war\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,\s*"
        r"(?:meine|unsere)\s+(?:neue|aktuelle|jetzige)\s+(?:wohnadresse\s+)?ist\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:wohnadresse|wohnanschrift|anschrift|adresse|meldeadresse|meldeanschrift|meldesitz)\s*:\s*"
        r"(?:vorher|früher|frueher|zuvor|ehemals)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,\s*"
        r"(?:jetzt|nun|aktuell|derzeit|inzwischen)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+von\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+nach\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s+(?:gezogen|umgezogen|übersiedelt|uebergesiedelt)\b|\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+wohnadresse\s+"
        r"(?:wechselte|wechselt|änderte\s+sich|aenderte\s+sich)\s+von\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+auf\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+nicht\s+mehr\s+(?:in|bei)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,\s*"
        r"(?:sondern|aber|jetzt)\s+(?:in|bei)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser|einen|eine|ein|den|die|das)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift|meldeadresse|meldeanschrift|meldesitz)"
        r"\s+(?:in|bei)\s+(?:\d{5}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?(?:\s+\([^)]{1,30}\))?)\s*,\s*"
        r"(?:genauer\s+genommen|genauer\s+gesagt|beziehungsweise|bzw\.?|konkret|"
        r"nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s*:?\s*"
        r"(?:(?:in|bei)\s+)?(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?(?:\s+\([^)]{1,30}\))?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,\n]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse|"
        r"meldeadresse|meldeanschrift|meldesitz)"
        r"(?:\s*(?::|=|,)\s*|\s+)"
        r"(?:\d{5}\s+)?"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?"
        r"(?:\s+\([^)]{1,30}\))?)\s*,\s*"
        r"(?:genauer\s+genommen|genauer\s+gesagt|beziehungsweise|bzw\.?|konkret|"
        r"nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s*:?\s*"
        r"(?:(?:in|bei)\s+)?(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?"
        r"(?:\s+\([^)]{1,30}\))?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz)\s*[:=]?\s*"
        r"(?:in\s+)?(?:deutschland|österreich|oesterreich|(?:der\s+)?schweiz)\s*[,;]\s*"
        r"(?:(?:genauer\s+gesagt|konkret|nämlich|naemlich|und\s+zwar)\s+)?"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})"
        r"(?=\s*[.!?;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[^,.;!?]{1,80}\s+nicht\s*,\s+sondern\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+(?!(?:ist|war|bleibt|wird)\b)"
        r"[\wÄÖÜäöüß'-]+){0,6})"
        r"(?:\s+ist)?(?=\s+(?:mein|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:nicht\s+)?[^,.;!?]{1,80}?\s+(?:ist\s+)?(?:nicht\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*"
        r"[,;]\s*(?:sondern|aber|doch|jedoch)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s+(?:ist\s+)?(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|"
        r"gegenwärtig|gegenwaertig|vorläufig|vorlaeufig|dauerhaft|temporär|temporaer)?\s*"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b|"
        r"\s*[.!?;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}?(?:\s*,\s*|\s*;\s*|\s+und\s+)"
        r"(?:aber|doch|jedoch)?\s*(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:lebensmittelpunkt|hauptwohnsitz)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[^,.;!?]{1,80}?\s+ist\s+(?:meine|unsere)\s+"
        r"(?:alte|ehemalige|frühere|fruehere)\s+"
        r"(?:wohnadresse|wohnanschrift|adresse|anschrift|wohnort|wohnsitz)\s*"
        r"[,;]\s*(?:(?:ist|liegt|befindet\s+sich)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:meine|unsere)\s+"
        r"(?:aktuelle|jetzige|derzeitige|gegenwärtige|gegenwaertige)\s+"
        r"(?:wohnadresse|wohnanschrift|adresse|anschrift|wohnort|wohnsitz)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[^,.;!?]{1,80}?\s+war\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*"
        r"[,;]\s*(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|seitdem)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:ist\s+)?(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[^,.;!?]{1,80}?\s+ist\s+nicht(?:\s+mehr)?\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*"
        r"[,;]\s*(?:aber|doch|jedoch|sondern)?\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+ist\s+es\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80}\s*,\s*(?:genau\s+genommen|beziehungsweise|bzw\.)\s+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:nicht\s+(?:mehr|l(?:aenger|änger))?|nicht)\s+(?:in|bei)\s+"
        r"[^,.;!?]{1,80},\s+aber\s+(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+ist\s+nicht\s+(?:mehr\s+)?mein(?:e)?\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*,\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+schon\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+ist\s+nicht\s+(?:mehr\s+)?mein(?:e)?\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s*,\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+bleibt\s+es\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+ist\s+"
        r"(?:kein(?:e|en|er|em)?|keinesfalls|niemals)\s+"
        r"(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)"
        r"(?:\s+von\s+mir)?\s*,\s*(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+schon\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+nicht\s+als\s+"
        r"(?:mein(?:e)?\s+)?(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)"
        r"\s*,\s*sondern\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bnicht\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80},\s*sondern\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:arbeite|arbeiten)\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"obwohl\s+(?:ich|wir)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:arbeite|arbeiten|studiere|studieren|lerne|lernen)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,?\s*"
        r"(?:weil|da|denn)\s+(?:ich|wir)\s+dort\s+(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:arbeite|arbeiten|studiere|studieren|lerne|lernen)\s+"
        r"(?:in|bei)\s+[^,.;!?]{1,80},?\s*"
        r"(?:weil|da|denn|wobei|während|waehrend|auch\s+wenn)\s+(?:ich|wir)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohne|wohnen|lebe|leben)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+ist\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:arbeitsort|arbeitsadresse|geschäftsadresse|geschaeftsadresse|dienstadresse|"
        r"büroadresse|bueroadresse)\s*,\s*"
        r"(?:auch\s+wenn|trotzdem|dennoch)\s+(?:ist\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:ist\s+)?(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b"
        r"(?:\s+ist)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+[^,.;!?]{1,80}\s+(?:arbeite|arbeiten|studiere|studieren|lerne|lernen)\s+"
        r"(?:ich|wir)\s+und\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,\s*"
        r"(?:obwohl|wobei|während|waehrend)\s+(?:ich|wir)\s+(?:in|bei)\s+[^,.;!?]{1,80}\s+"
        r"(?:arbeite|arbeiten|studiere|studieren|lerne|lernen)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+"
        r"\((?:arbeitsort|arbeitsadresse|geschäftsadresse|geschaeftsadresse|dienstadresse|"
        r"büroadresse|bueroadresse)\)\s*[,;/]\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"\((?:wohnort|wohnsitz|wohnadresse|wohnanschrift|anschrift|hauptwohnsitz)\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"\((?:wohnort|wohnsitz|wohnadresse|wohnanschrift|anschrift|hauptwohnsitz)\)\s*[,;/]\s*"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+"
        r"\((?:arbeitsort|arbeitsadresse|geschäftsadresse|geschaeftsadresse|dienstadresse|"
        r"büroadresse|bueroadresse)\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)"
        r"(?!(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben|bin|sind)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s*,\s*"
        r"(?:daheim|zuhause|zu\s+hause)(?=\s*[.!?;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:daheim|zuhause|zu\s+hause)(?=\s*[.!?;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)"
        r"(?!(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben|bin|sind)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*"
        r"(?:\s+(?!(?:ist|war|bleibt|wird|inzwischen|jetzt|nun|aktuell|derzeit|momentan|"
        r"mein(?:e)?|unser(?:e)?|dein(?:e)?|wo|ich|wir)\b)[\wÄÖÜäöüß'-]+){0,3}?)\s+"
        r"(?:daheim|zuhause|zu\s+hause)(?=\s*[.!?;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;\n]\s*)(?:früher|frueher|ehemals|damals)\s+(?:in\s+)?"
        r"[^,.;!?]{1,80}\s*,\s*(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"(?:(?:in|bei)\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+habe(?:n)?\s+mich\s+"
        r"(?:(?:von\s+[^,.;!?]{1,80}\s+nach)|(?:in|bei))\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+umgemeldet\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:nach|seit)\s+(?:dem|meinem|unserem)\s+umzug\s+"
        r"(?:ist|bleibt)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+war\s+"
        r"[^,.;!?]{1,80}[,;]\s*(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+"
        r"ist\s+(?:er|sie|es)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|hauptwohnsitz)\s+(?:ist|wurde)\s+"
        r"(?:von\s+[^,.;!?]{1,80}\s+nach|nach|in|zu)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:verlegt|umgezogen)\b",
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
        r"vorwiegend|mehrheitlich|primär|primaer|normalerweise|gewöhnlich|gewoehnlich|"
        r"regulär|regulaer|üblicherweise|ueblicherweise|in\s+der\s+regel)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,\s*"
        r"(?:meistens|hauptsächlich|hauptsaechlich|überwiegend|ueberwiegend|"
        r"vorwiegend|mehrheitlich|primär|primaer|normalerweise|gewöhnlich|gewoehnlich|"
        r"regulär|regulaer|üblicherweise|ueblicherweise|in\s+der\s+regel)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,\n]\s*)(?:im\s+urlaub|in\s+den\s+ferien|"
        r"während\s+der\s+ferien|waehrend\s+der\s+ferien|"
        r"während\s+(?:der|des|einer|eines|meines|meiner)\s+"
        r"(?:ferien|urlaubs|reise|dienstreise|aufenthalts)|"
        r"auf\s+(?:dienstreise|reisen)|während\s+(?:einer|der)\s+dienstreise|"
        r"bei\s+besuch|zu\s+besuch|während\s+(?:des|eines|meines)\s+besuchs|"
        r"geschäftlich|geschaeftlich|beruflich|am\s+wochenende|unter\s+der\s+woche|"
        r"werktags|wochentags|montags?|dienstags?|mittwochs?|donnerstags?|freitags?|"
        r"samstags?|sonntags?)\s+"
        r"(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)(?:\s+(?:ich|wir))?\s+)?"
        r"(?:in|bei)\s+"
        r"(?P<old_city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*,?\s*"
        r"(?:sonst|ansonsten)\s+(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)(?:\s+(?:ich|wir))?\s+)?"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
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
        rf"(?:(?:{_RESIDENCE_LOCATION_ADVERB})\s+)?"
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
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
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
        r"(?:aber\s+)?(?:grad\s+|gerade\s+|jetzt\s+|nun\s+|aktuell\s+|derzeit\s+)(?:in|bei)\s+"
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
        r"(?:genauer(?:\s+gesagt)?|konkret|nämlich|naemlich|und\s+zwar|besser\s+gesagt|sprich)\s*:?[ \t]+"
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
        r"(?:^|[.!?;\n]\s*)(?:von|aus)\s+[^,.;!?]{1,80}\s+nach\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+"
        r"(?:gezogen|umgezogen|gewechselt|weggezogen|übersiedelt|uebergesiedelt)\b",
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
_CITY_CHANGE_CITY_BEFORE_STREET = CITY_CHANGE_PATTERNS[0]
CITY_PATTERNS = (
    _MAIN_RESIDENCE_CITY_BEFORE_STREET,
    _MAIN_RESIDENCE_CITY,
    _COMPOUND_CITY_RESIDENCE,
    _COMPOUND_CITY_CONTRAST_RESIDENCE,
    _QUALIFIED_RESIDENCE,
    _CURRENT_RESIDENCE_LABEL_CITY,
    _LABELED_COMPOUND_RESIDENCE_CITY,
    _INVERTED_REGISTERED_CITY,
    _GENITIVE_RESIDENCE_ADDRESS_CITY,
    _RELATIVE_RESIDENCE_REGISTRATION_CITY,
    _INVERTED_RELATIVE_RESIDENCE_CITY,
    _SHORT_SELF_RESIDENCE_AFTER_OTHER_PERSON_CITY,
    _SHORT_SELF_RESIDENCE_AFTER_OTHER_PERSON_LABEL_CITY,
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)?\s*{_OTHER_PERSON_LOCATION_LABEL}\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s|[,;.!?]|$)\s*[,;]?\s*"
        r"(?:und|sowie|aber|doch|jedoch|oder|sondern|während|waehrend)?\s*"
        rf"(?=[^.!?;,\n]{{0,160}}\b{_OTHER_PERSON_FOREIGN_MARKER}\b)"
        r"[^.!?;,\n]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:ist\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"{_OTHER_PERSON_LOCATION_LABEL}\s*[,;]?\s*"
        r"(?:und|sowie|aber|doch|jedoch|oder|sondern|während|waehrend)?\s*"
        rf"(?=[^.!?;,\n]{{0,160}}\b{_OTHER_PERSON_FOREIGN_MARKER}\b)"
        r"[^.!?;,\n]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohne|wohnen|lebe|leben)(?:\s+(?:ich|wir))?"
        r"(?=\s*(?:[.!?;,]|$|\b(?:und|sowie|aber|doch|jedoch|während|waehrend)\b))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]?\s*"
        r"(?:und|sowie|aber|doch|jedoch|oder|sondern|während|waehrend)?\s*"
        r"(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:zeitweise|vorübergehend|voruebergehend|gelegentlich|derzeit|aktuell|momentan)\s+)?"
        r"(?:bei|mit)\s+(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+(?:in|bei)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s|[,;.!?]|$)\s*[,;]?\s*"
        r"(?:und|sowie|aber|doch|jedoch|oder|sondern|während|waehrend)?\s*"
        rf"(?=[^.!?;,\n]{{0,160}}\b{_OTHER_PERSON_FOREIGN_MARKER}\b)"
        r"[^.!?;,\n]+",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+(?:(?:ich|wir)\s+)?(?:bin|sind)\s+"
        r"(?:in|bei)\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+"
        r"(?:zu\s+besuch|auf\s+besuch)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]?\s*"
        r"(?:und|sowie|aber|doch|jedoch)\s+(?:(?:in|bei)\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+"
        r"(?:"
        r"(?:arbeite\w*|studier\w*|lern\w*|schlaf\w*|pendl\w*|reis\w*|"
        r"besuch\w*|übernacht\w*|uebernacht\w*|fahr\w*|geh\w*|komm\w*)\s+(?:ich|wir)\b|"
        r"bin\s+(?:ich|wir)\s+(?:beruflich|dienstlich|zum\s+arbeiten|zur\s+arbeit|"
        r"zum\s+studieren|heute|gerade|nur\s+unterwegs)\b|"
        r"mach\w*\s+(?:ich|wir)\s+(?:eine\s+)?ausbildung\b)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+(?:(?:in|bei)\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:geburtsort|geburtsstadt|heimat|heimatstadt|herkunftsort|herkunftsstadt|"
        r"studienort|universität|universitaet|uni|ausbildungsort|arbeitsstelle|"
        r"dienststelle|schule|arbeitsplatz)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        rf"\({_PRIMARY_RESIDENCE_LABEL}\)(?=\s*(?:[.!?;,]|\b(?:und|sowie)\b|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig|gegenwaertig|"
        r"vorübergehend\w*|voruebergehend\w*|zeitweise|temporär\w*|temporaer\w*|"
        r"befristet\w*|unbefristet\w*|dauerhaft\w*|permanent|vorläufig\w*|vorlaeufig\w*)\s+)?"
        r"(?:hauptadresse|adresse|wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:und|sowie|aber|doch|jedoch|sondern)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        r"(?:ist\s+)?(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig|gegenwaertig|"
        r"überwiegend|ueberwiegend|hauptsächlich|hauptsaechlich|vorwiegend|meistens|"
        r"normalerweise|gewöhnlich|gewoehnlich|üblicherweise|ueblicherweise)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+ist\s+"
        rf"(?:(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+(?:sofort|jetzt)|"
        r"bis\s+(?:zum\s+)?jahresende|"
        r"überwiegend|ueberwiegend|hauptsächlich|hauptsaechlich|vorwiegend|meistens|"
        r"primär|primaer|normalerweise|gewöhnlich|gewoehnlich|regulär|regulaer|"
        r"üblicherweise|ueblicherweise|in\s+der\s+regel)\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim)\b"
        rf"(?:\s+(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+(?:sofort|jetzt)))?"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+ist\s+"
        rf"(?:(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+(?:sofort|jetzt)|"
        r"bis\s+(?:zum\s+)?jahresende)\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig|gegenwaertig|"
        r"vorübergehend\w*|voruebergehend\w*|zeitweise|temporär\w*|temporaer\w*|"
        r"befristet\w*|unbefristet\w*|dauerhaft\w*|permanent|vorläufig\w*|vorlaeufig\w*)\s+)?"
        r"(?:hauptadresse|adresse|wohnadresse|wohnanschrift|privatadresse|privatanschrift|"
        r"anschrift|meldeadresse|meldeanschrift|meldesitz)\b"
        rf"(?:\s+(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+(?:sofort|jetzt)))?"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    _TEMPORAL_REGISTERED_CITY,
    _CITY_BEFORE_RESIDENCE_LABEL_WITH_LAUTET,
    _LABELED_COUNTRY_CITY,
    _REGIONAL_PREFIX_RESIDENCE,
    _HAVE_PRIMARY_HOME_CITY_BEFORE_STREET,
    _HAVE_PRIMARY_HOME_CITY,
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        rf"{_COUNTRY_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        r"(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+)?"
        r"(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s+\([^)]{1,30}\))?"
        r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        rf"(?:\s+(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER}))?\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b"
        rf"(?:\s+(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+(?:sofort|jetzt)))?"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?!(?:bei|in)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß.'-]*"
        r"(?:\s+(?!(?:und|oder|sowie)\b)[\wÄÖÜäöüß.'-]+)*)\s+"
        r"(?:bin|sind)\s+(?:ich|wir)\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b"
        rf"(?:\s+(?:{_RESIDENCE_TIME_QUALIFIER}|ab\s+(?:sofort|jetzt)))?"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"{_COUNTRY_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)(?:\s+|\s*[:=,]\s*)"
        rf"{_COUNTRY_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*"
        rf"{_COUNTRY_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        rf"{_AREA_BEFORE_STREET_PREFIX}{_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei)\s+"
        rf"{_POSTAL_CITY_BEFORE_STREET}\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)"
        r"(?:\s+(?:in|bei)\s+|\s*[:=,]\s*|\s+)"
        rf"{_POSTAL_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        rf"{_POSTAL_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
        rf"{_POSTAL_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+(?:in|bei)\s+"
        rf"{_POSTAL_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*"
        rf"(?:(?:in|bei)\s+)?{_POSTAL_CITY_BEFORE_STREET}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        rf"(?:im|in\s+der)\s+{_ATTRIBUTIVE_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        rf"{_GENITIVE_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        rf"{_GENITIVE_AREA_NAME_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"(?:im|in\s+der)\s+{_ATTRIBUTIVE_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"{_GENITIVE_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"{_GENITIVE_AREA_NAME_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+"
        rf"(?:im|in\s+der)\s+{_ATTRIBUTIVE_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+"
        rf"{_GENITIVE_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+"
        rf"{_GENITIVE_AREA_NAME_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*"
        rf"(?:im|in\s+der)\s+{_ATTRIBUTIVE_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*"
        rf"{_GENITIVE_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*"
        rf"{_GENITIVE_AREA_NAME_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"{_AREA_BEFORE_STREET_PREFIX}{_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+"
        rf"{_AREA_BEFORE_STREET_PREFIX}{_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*"
        rf"{_AREA_BEFORE_STREET_PREFIX}{_AREA_BEFORE_STREET_CITY}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"im\s+(?:nördlichen|noerdlichen|südlichen|suedlichen|östlichen|"
        r"oestlichen|westlichen|nordöstlichen|nordöstlichen|nordwestlichen|"
        r"südöstlichen|suedöstlichen|südwestlichen|suedwestlichen)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"im\s+(?:norden|süden|sueden|osten|westen|nordosten|nordwesten|"
        r"südosten|suedosten|südwesten|suedwesten)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)s\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"im\s+(?:stadtteil|bezirk|stadtviertel|viertel)\s+[^,.;!?]{1,80}?\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben|bin|sind)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?:\s*,\s*|\s+)(?:zu\s+hause|zuhause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:zu\s+hause|zuhause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:zu\s+hause|zuhause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:aktuell\w*|momentan\w*|derzeit\w*|inzwischen\w*|weiterhin\w*|jetzt\w*|nun\w*)\s+)?"
        r"(?:in|bei)\s+"
        rf"(?P<city>{_STREET_COMPOUND_CITY_PATTERN})\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:aktuell\w*|momentan\w*|derzeit\w*|inzwischen\w*|weiterhin\w*|jetzt\w*|nun\w*)\s+)?"
        r"(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*(?:[.!?;,]|wohnhaft|ansässig|ansaessig|gemeldet|registriert|"
        r"und\s+(?:umgebung|region|nähe|naehe)|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:in|bei)\s+|"
        r"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+(?:in|bei)\s+)"
        rf"(?P<city>{_STREET_COMPOUND_CITY_PATTERN})\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei|im)\s+"
        r"(?:der\s+(?:stadt|gemeinde|kommune|ortschaft|landeshauptstadt|metropole|"
        r"großstadt|grossstadt)|stadtgebiet(?:\s+von)?)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz)\s*(?::|=|,)\s*(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz)\s*(?::|=|,)\s*(?:in|bei|im)\s+"
        r"(?:der\s+(?:stadt|gemeinde|kommune|ortschaft|landeshauptstadt|metropole|"
        r"großstadt|grossstadt)|stadtgebiet(?:\s+von)?)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?:\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}(?=\s*[.!?;,]|$)|"
        r"(?=\s*[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+(?:in|bei|im)\s+"
        r"(?:der\s+(?:stadt|gemeinde|kommune|ortschaft|landeshauptstadt|metropole|"
        r"großstadt|grossstadt)|stadtgebiet(?:\s+von)?)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?:\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}(?=\s*[.!?;,]|$)|"
        r"(?=\s*[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:in|bei|im)\s+"
        r"(?:der\s+(?:stadt|gemeinde|kommune|ortschaft|landeshauptstadt|metropole|"
        r"großstadt|grossstadt)|stadtgebiet(?:\s+von)?)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?:\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}(?=\s*[.!?;,]|$)|"
        r"(?=\s*[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:in|an|auf|unter)\s+"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)"
        r"(?:\s+(?:in|bei)\s+|\s*[:=,]\s*)"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser|einen|eine|ein)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|anschrift|bleibe)\s+(?:in|bei)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig)\s+(?:in|bei)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:aktuell\w*|momentan\w*|derzeit\w*|inzwischen\w*|weiterhin\w*|jetzt\w*|nun\w*)\s+)?"
        r"(?:in|bei)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei)\s+"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei)\s+(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohnhaft|ansässig|ansaessig)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<city>(?:Frankfurt\s+an\s+der\s+Oder|Ludwigshafen\s+am\s+Rhein)|"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,70}\s+\([^)]{1,30}\))"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+im\s+"
        r"(?!(?:Paris|Reims|Worms|Tours|Cannes|Lens)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?:er|s)\s+"
        r"(?:norden|süden|osten|westen|nord[-\s]?osten|nord[-\s]?westen|"
        r"süd[-\s]?osten|süd[-\s]?westen)\b",
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
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser|einen|eine|ein|den|die|das)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift)\s+(?:in|bei)\s+"
        r"(?:\d{5}\s+)?"
        r"(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+(?!umgebung\b|region\b|nähe\b|naehe\b))"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?!(?:aber|doch|jedoch|sondern|jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+ist\s+"
        r"(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:aktuell\w*|jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*|"
        r"vorläufig\w*|vorlaeufig\w*|vorübergehend\w*|dauerhaft\w*|temporär\w*|temporaer\w*|"
        r"befristet\w*|unbefristet\w*|fest\w*|hauptsächlich\w*|hauptsaechlich\w*|"
        r"gemeldet\w*|offiziell\w*|privat\w*|tatsächlich\w*|tatsaechlich)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:{_RESIDENCE_TIME_QUALIFIER})\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|anschrift)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser)\s+"
        r"(?:aktuell\w*|jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*|"
        r"gemeldet\w*|offiziell\w*|privat\w*|dauerhaft\w*|fest\w*)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser)\s+"
        rf"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+(?:{_RESIDENCE_TIME_QUALIFIER})\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+"
        r"(?:(?:neu\w*|aktuell\w*|jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:wohnung|unterkunft|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        rf"(?:(?:{_RESIDENCE_TIME_QUALIFIER})\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
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
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s+"
        r"(?:ist|liegt|lautet|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)?\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz|privatadresse|privatanschrift)\s*"
        r"(?::|=|,)\s*(?:(?:in|bei)\s+)?"
        r"(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse|"
        r"meldeadresse|meldeanschrift|meldesitz)"
        r"(?:(?::|=|,)\s*|\s+)"
        r"(?!(?:ist|war|wird|liegt|lautet|befindet\s+sich|bleibt)\b)"
        r"(?:\d{5}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?"
        r"(?:\s+\([^)]{1,30}\))?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:(?:offiziell\w*|privat\w*|aktuell\w*|amtlich\w*|neu\w*|gemeldet\w*)\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:(?::|=|,)\s*|(?:ist|liegt|lautet|befindet\s+sich)\s+)"
        r"\d{5}\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere|mein|unser)\s+"
        r"(?:offiziell\w*|privat\w*)\s+"
        r"(?:meldadresse|meldeadresse|meldeanschrift|meldesitz)\s+"
        r"(?:ist|liegt|lautet|befindet\s+sich|:|=)\s*(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?;,:]\s*)(?:meine|unsere|mein|unser)?\s*"
        r"(?:offiziell\w*|privat\w*)\s+"
        r"(?:meldadresse|meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?::|=|,)\s*(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:eine|meine|unsere)\s+"
        r"(?:offiziell\w*|privat\w*)\s+"
        r"(?:meldadresse|meldeadresse|meldeanschrift|meldesitz)\s+"
        r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere|mein|unser)\s+"
        r"(?:(?:aktuell\w*|amtlich\w*|neu\w*|gemeldet\w*)\s+)?"
        r"(?:meldadresse|meldeadresse|meldeanschrift|meldesitz)\s+"
        r"(?:ist|liegt|lautet|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine|unsere)\s+"
        r"(?:(?:aktuell\w*|jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:wohnung|wg|unterkunft)\s+"
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
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:amtlich\s+)?registriert\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:(?:derzeit|aktuell|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:in|bei)\s+(?![^.!?;,]*\b(?:beruflich|dienstlich|zur\s+schule|zur\s+arbeit)\b)"
        r"(?P<city>(?![^.!?;,]*\s+(?:und|oder)\s+)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:amtlich\s+)?(?:gemeldet|registriert)\b",
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
        r"(?:(?:aktuell\w*|derzeit\w*|jetzig\w*|gegenwärtig\w*|gegenwaertig\w*|"
        r"offiziell\w*|gemeldet\w*|amtlich\w*)\s+)?"
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
        r"\b(?:ich|i|wir)\s+(?:habe|haben)\s+(?:(?:jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\s+)?"
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
        r"\b(?:ich|wir)\s+(?:bin|sind)\s+"
        r"(?!(?:in|bei)\s+[^.!?;,]*\b(?:beruflich|dienstlich)\b)"
        r"(?:in\s+der\s+(?:nähe|naehe|umgebung|gegend)\s+von|nahe|unweit\s+von)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohnhaft|ansässig|ansaessig)\b",
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
        rf"(?:{_RESIDENCE_DISTANCE_PREFIX})(?:von|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+entfernt\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|i|wir)\s+(?:wohne|wohn|wohnen|lebe|leb|leben)\s+"
        rf"(?:{_RESIDENCE_DISTANCE_PREFIX})au(?:ßerhalb|sserhalb)\s+von\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
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
        rf"\b(?:{_RESIDENCE_LABEL_DETERMINER}\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift|meldeadresse|meldeanschrift|meldesitz)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})"
        r"(?=\s*[.!?;,]|$)",
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
        rf"\b(?:{_RESIDENCE_LABEL_DETERMINER}\s+)?"
        r"(?:adresse|wohnadresse|wohnanschrift|anschrift|meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,|[-–—])\s*"
        rf"(?:{_LABELED_STREET_ADDRESS})?(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})"
        r"(?=\s*[.!?;,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine\s+|unsere\s+)?(?:adresse|wohnadresse|wohnanschrift|anschrift)\s*:\s*"
        r"\d{5}\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:meine\s+|unsere\s+)?(?:adresse|wohnadresse|wohnanschrift|anschrift)\s*:\s*"
        rf"{_LABELED_STREET_ADDRESS}(?:\d{{5}}\s+)?"
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
        r"\b(?:hier|dort|da)\s*[,;]\s*(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?=\s*(?:[,;]\s*)?(?:wohne|wohnen|lebe|leben)\s+(?:ich|wir)\b)",
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
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\b\s*"
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
        rf"[^,.;!?]{{1,100}}?{_STREET_TYPE}\s+"
        rf"(?:{_STREET_NUMBER_LABEL}\s*)?\d+[a-z]?\s*(?:,\s*|\s+)(?:(?:in|bei)\s+)?(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:adresse|wohnadresse|wohnanschrift|anschrift|wohnort|wohnsitz)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        rf"[^,.;!?]{{1,100}}?{_STREET_TYPE}\s+"
        rf"(?:{_STREET_NUMBER_LABEL}\s*)?\d+[a-z]?\s*(?:,\s*|\s+)(?:(?:in|bei)\s+)?(?:\d{{5}}\s+)?"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:meine|unsere)\s+"
        r"(?:adresse|wohnadresse|wohnanschrift|anschrift)\s+"
        rf"[^,.;!?]{{1,100}}?{_STREET_TYPE}\s+"
        rf"(?:{_STREET_NUMBER_LABEL}\s*)?\d+[a-z]?\s*(?:,\s*|\s+)(?:(?:in|bei)\s+)?(?:\d{{5}}\s+)?"
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
        r"(?:(?:offiziell|polizeilich|privat|amtlich|dauerhaft|permanent|vorübergehend|vorlaeufig)\s+)?"
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
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:amtlich\s+)?gemeldet\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_RESIDENCE_TIME_QUALIFIER}\s+)?(?:ich\s+)?bin\s+"
        rf"(?:{_RESIDENCE_LOCATION_ADVERB}\s+)?(?:in|bei)\s+\d{{5}}\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:amtlich\s+)?(?:gemeldet|registriert)\b",
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
        r"nördlich\s+von|südlich\s+von|östlich\s+von|westlich\s+von|rund\s+um|nahe|unweit\s+von|"
        r"nicht\s+weit\s+(?:entfernt\s+)?von)\s+"
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
        r"\b(?!(?:aber|doch|jedoch|sondern|jetzt|nun|aktuell|derzeit|inzwischen|mittlerweile)\b)"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80})\s+ist\s+"
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
        rf"(?:(?:weiterhin|nach\s+wie\s+vor|noch\s+immer|immer\s+noch|vorerst|"
        rf"bis\s+auf\s+weiteres|seit\s+{_RESIDENCE_DURATION})\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"(?:wohne|wohn|lebe|leb)\s+(?:ich|wir)\b"
        r"(?=\s*(?:[.!?;,]|$))",
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
    r"(?:ist|bleibt)\s+es\b|laut\b.*|"
    r"ab\s+sofort|"
    r"bis\s+(?:heute|morgen|übermorgen|uebermorgen|auf\s+weiteres|"
    r"(?:zum\s+)?ende\s+der\s+woche|"
    r"zum\s+ende\s+(?:des\s+)?(?:monats|jahres)|"
    r"ende\s+(?:des\s+)?(?:monats|jahres)|(?:zum\s+)?jahresende)|"
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
CityMemorySnapshot = tuple[list[dict[str, Any]], dict[str, Any]]


class _ResidenceMemoryRollbackError(RuntimeError):
    """Signal that residence-memory recovery did not complete safely."""


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
    previous_state = deepcopy(state)
    weather_state = _ensure_weather_state(state)
    city = extract_residence_city(text)
    city_changed = False
    city_memory_snapshot: CityMemorySnapshot | None = None
    if city:
        previous_city = str(weather_state.get("city") or "").strip()
        city_changed = _city_comparison_key(city) != _city_comparison_key(previous_city)
        if not city_changed:
            city = previous_city
        memory_ok, city_memory_snapshot = _append_city_memory(account_store, account_id, city, resolved_now)
        if not memory_ok:
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
        if city:
            _write_weather_state(account_store, account_id, state, previous_state, city_memory_snapshot)
        return WeatherContextResult(skipped_reason="no_city")
    last_checked = _parse_datetime(str(weather_state.get("last_checked_at") or ""))
    elapsed_since_check = resolved_now - last_checked if last_checked is not None else None
    if not city_changed and elapsed_since_check is not None and timedelta(0) <= elapsed_since_check < WEATHER_CHECK_INTERVAL:
        if city:
            _write_weather_state(account_store, account_id, state, previous_state, city_memory_snapshot)
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
        _write_weather_state(account_store, account_id, state, previous_state, city_memory_snapshot)
        return WeatherContextResult(city=current_city, checked=True, skipped_reason="weather_error")
    weather_state["summary"] = summary[:500]
    weather_state["last_checked_at"] = resolved_now.isoformat(timespec="seconds")
    weather_state["last_error"] = ""
    weather_state["updated_at"] = resolved_now.isoformat(timespec="seconds")
    _write_weather_state(account_store, account_id, state, previous_state, city_memory_snapshot)
    return WeatherContextResult(city=current_city, weather_text=weather_state["summary"], checked=True)


def _write_weather_state(
    account_store: AccountStore,
    account_id: str,
    state: dict[str, Any],
    previous_state: dict[str, Any],
    city_memory_snapshot: CityMemorySnapshot | None,
) -> None:
    try:
        account_store.write_agent_state(account_id, state)
    except Exception:
        rollback_errors: list[Exception] = []
        restores: list[Callable[[], None]] = [
            lambda: account_store.write_agent_state(account_id, previous_state),
        ]
        if city_memory_snapshot is not None:
            previous_rows, previous_index = city_memory_snapshot
            restores.extend(
                (
                    lambda: account_store.write_memory_entries(account_id, previous_rows),
                    lambda: account_store.write_memory_index(account_id, previous_index),
                )
            )
        for restore in restores:
            try:
                restore()
            except Exception as rollback_exc:  # noqa: BLE001 - preserve failure visibility.
                rollback_errors.append(rollback_exc)
        if rollback_errors:
            raise RuntimeError("weather state rollback failed; account state or residence memory may be inconsistent") from rollback_errors[0]
        raise


def _append_city_memory(
    account_store: AccountStore,
    account_id: str,
    city: str,
    now: datetime,
) -> tuple[bool, CityMemorySnapshot | None]:
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
                return True, None
            previous_index = account_store.read_memory_index(account_id)
            account_store.append_structured_memory_entry(account_id, entry)
            return True, ([dict(row) for row in rows if isinstance(row, Mapping)], deepcopy(previous_index))
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
            return True, (previous_rows, deepcopy(previous_index))
        except Exception:
            rollback_errors: list[Exception] = []
            for restore in (
                lambda: account_store.write_memory_entries(account_id, previous_rows),
                lambda: account_store.write_memory_index(account_id, previous_index),
            ):
                try:
                    restore()
                except Exception as rollback_exc:  # noqa: BLE001 - expose incomplete recovery.
                    rollback_errors.append(rollback_exc)
            if rollback_errors:
                raise _ResidenceMemoryRollbackError(
                    "residence memory rollback failed; entries and index may be inconsistent"
                ) from rollback_errors[0]
            raise
    except _ResidenceMemoryRollbackError:
        raise
    except Exception:
        return False, None


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
    for district_name, base_city in _KNOWN_CITY_DISTRICT_BASES.items():
        if "(" in district_name:
            source = re.sub(
                rf"(?<!\w){re.escape(district_name)}(?!\w)",
                base_city,
                source,
                flags=re.IGNORECASE,
            )
    source = re.sub(r"\bhalle\s*\(\s*saale\s*\)", "Halle Saale", source, flags=re.IGNORECASE)
    source = _PARENTHESIZED_STREET_DETAIL.sub(
        lambda match: match.group("address"),
        source,
    )
    source = _PARENTHESIZED_AREA_STREET_ADDRESS.sub(
        lambda match: f"in {match.group('city')}",
        source,
    )
    if _has_non_residential_companion_context(source):
        return ""

    def latest_match(patterns: tuple[re.Pattern[str], ...]) -> str:
        candidates: list[tuple[int, str]] = []
        compound_pattern = re.compile(
            rf"(?<!\w)(?:{'|'.join(re.escape(name) for name in _KNOWN_COMPOUND_CITY_NAMES)})(?!\w)",
            re.IGNORECASE,
        )
        compound_spans = tuple((match.start(), match.end()) for match in compound_pattern.finditer(source))

        def collect_matches(value: str, offset: int) -> None:
            for pattern in patterns:
                for match in pattern.finditer(value):
                    pattern_start = offset + match.start()
                    city_start = offset + match.start("city")
                    city_end = offset + match.end("city")
                    if _is_implicit_residence_alias_fragment(source, city_start, city_end):
                        continue
                    if _has_historical_residence_prefix(source, pattern_start):
                        continue
                    if _has_companion_residence_prefix(source, city_start):
                        continue
                    if _has_non_residential_label_prefix(source, pattern_start):
                        continue
                    if _has_other_person_residence_prefix(source, pattern_start) or _has_other_person_residence_prefix(
                        source, city_start
                    ) or _has_other_person_residence_prefix(source, city_end):
                        continue
                    if _has_other_person_as_residence_label(source, city_start, city_end):
                        continue
                    if _has_transient_location_fragment(source, city_start, city_end):
                        continue
                    if _has_temporary_residence_prefix(source, pattern_start):
                        continue
                    if _has_other_person_residence_suffix(source, city_end):
                        continue
                    if _has_future_residence_prefix(source, pattern_start, city_start):
                        continue
                    if _has_uncertain_residence_prefix(source, pattern_start):
                        continue
                    if _has_other_person_residence_candidate(match.group("city")):
                        continue
                    if re.match(
                        r"(?i)^\s*(?:vielleicht|vermutlich|möglicherweise|moeglicherweise|eventuell|"
                        r"wahrscheinlich|wohl|angeblich|anscheinend|scheinbar)\b|"
                        r"^\s*(?:ich|wir)\s+(?:glaube|denke|vermute)\b|"
                        r"^\s*ich\s+nehme\s+an\b|^\s*soweit\s+ich\s+wei(?:ß|ss)\b",
                        match.group("city"),
                    ):
                        continue
                    if re.match(r"(?i)^\s*wei(?:ß|ss)t\s+du\b", match.group("city")):
                        continue
                    if (
                        _has_non_residential_city_tail(match.group("city"))
                        or _has_non_residential_city_suffix(source, city_end)
                    ):
                        continue
                    if _has_unresolved_location_separator(source, city_end):
                        continue
                    if _has_future_residence_suffix(source, city_end):
                        continue
                    if _has_historical_residence_suffix(source, city_end):
                        continue
                    if _has_uncertain_residence_suffix(source, city_end):
                        continue
                    if _has_temporal_residence_suffix_text(match.group("city")):
                        continue
                    city = _clean_city(match.group("city"))
                    if city:
                        # Generic patterns may match trailing pieces inside a known compound city.
                        comparable_city_end = city_end
                        while (
                            comparable_city_end > city_start
                            and source[comparable_city_end - 1] in " .,:;!?"
                        ):
                            comparable_city_end -= 1
                        if any(
                            span_start <= city_start
                            and comparable_city_end <= span_end
                            and (span_start, span_end) != (city_start, comparable_city_end)
                            for span_start, span_end in compound_spans
                        ):
                            continue
                        candidates.append((city_start, city))

        collect_matches(source, 0)
        for boundary in re.finditer(r"(?<!\bSt)[.!?;]\s+", source, re.IGNORECASE):
            collect_matches(source[boundary.end() :], boundary.end())
        if candidates:
            return max(candidates, key=lambda candidate: candidate[0])[1]
        return ""

    if (
        _has_conflicting_residence_address_targets(source)
        or _has_explicit_residence_multiplicity(source)
        or _has_conflicting_direct_residence_labels(source)
        or _has_conflicting_parenthetical_residence_labels(source)
    ):
        return ""
    city = latest_match(CITY_CHANGE_PATTERNS)
    if city:
        return city
    if _has_ambiguous_residence_targets(source):
        return ""
    return latest_match(CITY_PATTERNS)


def _has_explicit_residence_multiplicity(source: str) -> bool:
    multiplicity_source = re.sub(r"(?i)str\.(?=\s)", "str", source)
    for pair in _DIRECT_RESIDENCE_REGISTRATION_LABEL_PAIR.finditer(multiplicity_source):
        first_is_registration = pair.group("first_label").casefold() in {
            "meldeadresse",
            "meldeanschrift",
            "meldesitz",
        }
        second_is_registration = pair.group("second_label").casefold() in {
            "meldeadresse",
            "meldeanschrift",
            "meldesitz",
        }
        first = _clean_city(pair.group("first_city"))
        second = _clean_city(pair.group("second_city"))
        if (
            first_is_registration != second_is_registration
            and first
            and second
            and _city_comparison_key(first) == _city_comparison_key(second)
        ):
            return False
    for pair in _DIRECT_RESIDENCE_REGISTRATION_LABEL_ALIAS_PAIR.finditer(multiplicity_source):
        first_is_registration = pair.group("first_label").casefold() in {
            "meldeadresse",
            "meldeanschrift",
            "meldesitz",
        }
        second_is_registration = pair.group("second_label").casefold() in {
            "meldeadresse",
            "meldeanschrift",
            "meldesitz",
        }
        if first_is_registration != second_is_registration:
            return False
    if any(
        pattern.search(source)
        for pattern in (
            _CITY_CHANGE_COLON_LABELLED_OLD_NEW_STREET,
            _CITY_CHANGE_LABELLED_ALT_NEW_COLON_STREET,
            _CITY_CHANGE_LABELLED_TEMPORAL_INLINE_CITY,
            _CITY_CHANGE_LABELLED_COLON_SEPARATOR_STREET,
            _COMPOUND_CITY_RESIDENCE,
            _COMPOUND_CITY_CONTRAST_RESIDENCE,
            _LABELED_COUNTRY_CITY,
        )
    ):
        return False
    if re.search(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        rf"{_STREET_COMPOUND_CITY_PATTERN}(?=\s*[.!?;,]|$)",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*"
        rf"{_COUNTRY_CITY_BEFORE_STREET}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*"
        rf"{_AREA_BEFORE_STREET_PREFIX}{_AREA_BEFORE_STREET_CITY}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz)\s*(?::|=|,)\s*(?:(?:in|bei)\s+)?"
        rf"(?:{_STREET_COMPOUND_CITY_PATTERN}|[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)"
        r"(?:\s+\([^)]{1,30}\))?(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}(?=\s*[.!?;,]|$)",
        source,
        re.IGNORECASE,
    ):
        return False
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
                if not re.match(
                    r"(?i)^(?:(?:mein(?:e)?|unser(?:e)?)\s+)?"
                    r"(?:geburtsort|geburtsstadt|heimat|heimatstadt|herkunftsort|herkunftsstadt|"
                    r"arbeitsort|arbeitsadresse|geschäftsadresse|geschaeftsadresse|"
                    r"dienstadresse|büroadresse|bueroadresse)\b",
                    second_raw,
                ) and not re.match(
                    rf"(?i)^(?:(?:mein(?:e)?|unser(?:e)?)\s+)?{_SECONDARY_RESIDENCE_LABEL}"
                    r"(?=\s|[:=,]|$)",
                    second_raw,
                ) and not re.match(
                    r"(?i)^(?:(?:mein(?:e)?|unser(?:e)?)\s+)?"
                    r"(?:ehemalig\w*|ehemals|frueh\w*|früh\w*|vormalig\w*|damalig\w*|"
                    r"alt\w*)\s+(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|"
                    r"lebensmittelpunkt|wohnadresse|wohnanschrift|adresse|anschrift)\b",
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
        r"primaer|primär|normalerweise|gewöhnlich|gewoehnlich|regulär|regulaer|"
        r"üblicherweise|ueblicherweise|in\s+der\s+regel)\b",
        source,
        re.IGNORECASE,
    ):
        multiplicity_source = re.sub(r"\bmanchmal\b", "", source, flags=re.IGNORECASE)
    if re.search(
        r"\b(?:wohne|wohnen|lebe|leben)\b[^.!?;\n]*\b(?:und)\s+"
        r"(?:der\s+)?(?:umgebung|region|nähe|naehe)\s+von\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}",
        multiplicity_source,
        re.IGNORECASE,
    ):
        return True
    residence_with_owned_domicile = re.search(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<first>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:und|,|;)\s+"
        r"(?:habe|haben)\s+"
        r"(?:(?:meinen|meine|mein|unseren|unsere|unser|einen|eine|ein|den|die|das)\s+)?"
        r"(?:(?:fest|dauerhaft|aktuell|offiziell)\w*\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+"
        r"(?:in|bei)\s+"
        r"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
        multiplicity_source,
        re.IGNORECASE,
    )
    if residence_with_owned_domicile:
        first = _clean_city(residence_with_owned_domicile.group("first"))
        second = _clean_city(residence_with_owned_domicile.group("second"))
        if (
            first
            and second
            and _city_comparison_key(first) != _city_comparison_key(second)
        ):
            return True
    if re.search(
        r"\b(?:wohne|wohnen|lebe|leben|wohnort|wohnsitz)\b[^.!?;\n]*\b(?:im|in\s+der)\s+"
        r"(?:(?:großraum|grossraum|raum|gebiet|region|umland|umgebung)\s+(?:von\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+und\s+|"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß'-]+\s+(?:raum|region|gebiet|großraum|grossraum|umland|umgebung)\s+und\s+)"
        r"(?!(?:ich\s+)?(?:arbeite|arbeitest|arbeiten|studier\w*|lern\w*|schlaf\w*|"
        r"mach\w*|komm\w*|fahr\w*|geh\w*|zieh\w*|hab\w*|besitz\w*|bin|bist|sind|sein|"
        r"besuch\w*|verbring\w*|treff\w*|reis\w*|pendl\w*|seh\w*|übernacht\w*|uebernacht\w*)\b|"
        r"umgebung\b|region\b|nähe\b|naehe\b)(?:(?:in|bei)\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?=\s*(?:[.!?;,]|$))",
        multiplicity_source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:wohne|wohnen|lebe|leben)\b\s+"
        r"(?:(?:meistens|hauptsächlich|hauptsaechlich|überwiegend|ueberwiegend|"
        r"vorwiegend|mehrheitlich|primär|primaer|normalerweise|gewöhnlich|gewoehnlich|"
        r"regulär|regulaer|üblicherweise|ueblicherweise|in\s+der\s+regel)\s+)?"
        r"(?:in|bei)\s+[^,.;!?]{1,80}\s+und\s+"
        r"(?!(?:ich\s+)?(?:arbeite|arbeitest|arbeiten|studier\w*|"
        r"lern\w*|schlaf\w*|mach\w*|komm\w*|fahr\w*|geh\w*|zieh\w*|hab\w*|bin|bist|"
        r"sind|sein|besuch\w*|verbring\w*|treff\w*|reis\w*|pendl\w*|seh\w*|übernacht\w*|"
        r"uebernacht\w*)\b|(?:umgebung|region|nähe|naehe)\b(?!\s+von\b))"
        r"(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+)?"
        r"(?:(?:in|bei)\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?=\s*(?:[.!?;,]|$))",
        multiplicity_source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:wohne|wohnen|lebe|leben)\b\s+(?:in|bei)\s+[^,.;!?]{1,80},\s*"
        r"(?:meistens|hauptsächlich|hauptsaechlich|überwiegend|ueberwiegend|"
        r"vorwiegend|mehrheitlich|primär|primaer|normalerweise|gewöhnlich|gewoehnlich|"
        r"regulär|regulaer|üblicherweise|ueblicherweise|in\s+der\s+regel)\s+"
        r"(?:in|bei)\s+[^,.;!?]{1,80}\s+und\s+"
        r"(?!(?:ich\s+)?(?:arbeite|arbeitest|arbeiten|studier\w*|"
        r"lern\w*|schlaf\w*|mach\w*|komm\w*|fahr\w*|geh\w*|zieh\w*|hab\w*|bin|bist|"
        r"sind|sein|besuch\w*|verbring\w*|treff\w*|reis\w*|pendl\w*|seh\w*|übernacht\w*|"
        r"uebernacht\w*)\b|(?:umgebung|region|nähe|naehe)\b(?!\s+von\b))"
        r"(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+)?"
        r"(?:(?:in|bei)\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?=\s*(?:[.!?;,]|$))",
        multiplicity_source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:wohne|wohnen|lebe|leben|wohnort|wohnsitz)\b[^.!?;\n]*\b"
        r"(?:außerhalb|ausserhalb)\s+(?:der\s+stadt\s+|von\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+und\s+"
        r"(?!(?:ich\s+)?(?:arbeite|arbeitest|arbeiten|studier\w*|lern\w*|schlaf\w*|"
        r"mach\w*|komm\w*|fahr\w*|geh\w*|zieh\w*|hab\w*|besitz\w*|bin|bist|sind|sein|"
        r"besuch\w*|verbring\w*|treff\w*|reis\w*|pendl\w*|seh\w*|übernacht\w*|uebernacht\w*)\b)"
        r"(?:(?:in|bei)\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?=\s*(?:[.!?;,]|$))",
        multiplicity_source,
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            r"\b(?:wohne|wohnen|lebe|leben)\b[^.!?;\n]*\b(?:mal|manchmal|teils|teilweise|abwechselnd|zwischen|"
            r"oder|weder)\b|"
            r"\b(?:wohne|wohnen|lebe|leben)\b[^.!?;\n]*\b(?:beziehungsweise|bzw\.?)"
            r"(?!\s+(?:in|bei)\b)|"
            r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnorte|wohnsitze)\b",
            multiplicity_source,
            re.IGNORECASE,
        )
    )


def _has_conflicting_direct_residence_labels(source: str) -> bool:
    cities: set[str] = set()
    for pair in _DIRECT_RESIDENCE_REGISTRATION_LABEL_PAIR.finditer(source):
        first_is_registration = pair.group("first_label").casefold() in {
            "meldeadresse",
            "meldeanschrift",
            "meldesitz",
        }
        second_is_registration = pair.group("second_label").casefold() in {
            "meldeadresse",
            "meldeanschrift",
            "meldesitz",
        }
        if first_is_registration == second_is_registration:
            continue
        first = _clean_city(pair.group("first_city"))
        second = _clean_city(pair.group("second_city"))
        if (
            first
            and second
            and _city_comparison_key(first) != _city_comparison_key(second)
        ):
            return True
    pattern = re.compile(
        r"(?:^|[.!?;,\n]\s*)(?:aber|doch|jedoch|sondern|jetzt|nun|aktuell|derzeit)?\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|derzeit\w*|jetzig\w*|gegenwärtig\w*|gegenwaertig\w*|"
        r"gemeldet\w*|offiziell\w*|amtlich\w*|neu\w*|privat\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"wohnadresse|wohnanschrift|meldeadresse|meldeanschrift|adresse|anschrift|"
        r"zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    )
    contrast_pattern = re.compile(
        r"(?:^|[.!?;,\n]\s*)(?:aber|doch|jedoch)\s*"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:ist\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|derzeit\w*|jetzig\w*|gegenwärtig\w*|gegenwaertig\w*|"
        r"gemeldet\w*|offiziell\w*|amtlich\w*|neu\w*|privat\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"wohnadresse|wohnanschrift|meldeadresse|meldeanschrift|adresse|anschrift|"
        r"zuhause|zu\s+hause|daheim)\b",
        re.IGNORECASE,
    )
    for match in (*pattern.finditer(source), *contrast_pattern.finditer(source)):
        city = _clean_city(match.group("city"))
        if city:
            cities.add(_city_comparison_key(city))
    if len(cities) > 1:
        return True
    pair = re.search(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?P<first>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*[,;]\s*"
        r"(?:bleibt|ist)\s+(?:aber|doch|jedoch)?\s*(?:(?:in|bei)\s+)?"
        r"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*[.!?;]|$)",
        source,
        re.IGNORECASE,
    )
    if pair:
        first = _clean_city(pair.group("first"))
        second = _clean_city(pair.group("second"))
        return bool(first and second and _city_comparison_key(first) != _city_comparison_key(second))
    return False


def _has_conflicting_parenthetical_residence_labels(source: str) -> bool:
    cities: set[str] = set()
    pattern = re.compile(
        r"(?:^|[.!?;,:]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
        r"\((?P<label>[^)]{1,50})\)(?=\s*(?:[.!?;,]|\b(?:und|sowie)\b|$))",
        re.IGNORECASE,
    )
    for match in pattern.finditer(source):
        label = match.group("label").strip()
        if re.fullmatch(rf"(?i){_SECONDARY_RESIDENCE_LABEL}", label):
            continue
        if re.search(
            r"(?i)\b(?:ehemalig\w*|ehemals|frueh\w*|früh\w*|vormalig\w*|damalig\w*|"
            r"alt\w*|arbeitsort|arbeitsadresse|geschäftsadresse|geschaeftsadresse|"
            r"dienstadresse|büroadresse|bueroadresse)\b",
            label,
        ):
            continue
        if not re.search(
            r"(?i)\b(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\b",
            label,
        ):
            continue
        city = _clean_city(match.group("city"))
        if city:
            cities.add(_city_comparison_key(city))
    return len(cities) > 1


def _has_non_residential_label_prefix(source: str, pattern_start: int) -> bool:
    prefix_source = source[:pattern_start]
    if pattern_start < len(source) and source[pattern_start] in ",;":
        prefix_source += source[pattern_start]
    boundary = re.match(r"(?i)(?:und|sowie|oder|aber|doch|jedoch|sondern)\b", source[pattern_start:])
    if boundary:
        prefix_source += " " + boundary.group(0)
    prefix = re.split(
        r"(?:[,;]|\b(?:und|sowie|oder|aber|doch|jedoch|sondern)\b)\s*",
        prefix_source,
        flags=re.IGNORECASE,
    )[-1]
    label_start = re.match(r"\s*(?:\S+\s+){0,3}\S*", source[pattern_start:])
    secondary_label_context = prefix + " " + (label_start.group(0) if label_start else "")
    if re.search(
        rf"(?i)\b(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_SECONDARY_RESIDENCE_LABEL}\b",
        secondary_label_context,
    ):
        return True
    if re.search(r"\b(?:dein(?:e)?|euer(?:e)?)\s*$", prefix, re.IGNORECASE) and re.match(
        r"\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\b",
        source[pattern_start:],
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(
            r"(?:\b(?:dienst\w*|beruf\w*|arbeits[-\s]?\w*|geschäft\w*|geschaeft\w*|büro\w*|buero\w*)\s*|"
            r"\b(?:der|die|das|sein(?:e|en|em|er)?|ihr(?:e|en|em|er)?|deren)\s*|"
            r"\bkein(?:e|en|er|em)?\s+(?:fest(?:e|en|er|em)?\s*)?\s*)$",
            prefix,
            re.IGNORECASE,
        )
    )


def _has_companion_residence_prefix(source: str, city_start: int) -> bool:
    prefix = source[:city_start]
    separators = tuple(
        re.finditer(r"[,;]|\b(?:und|aber|doch|jedoch)\b", prefix, flags=re.IGNORECASE)
    )
    if not separators:
        return False
    clause = prefix[separators[-1].end() :]
    return bool(
        re.fullmatch(
            rf"(?i)\s*(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
            r"(?:(?:zeitweise|vorübergehend|voruebergehend|gelegentlich|derzeit|aktuell|momentan|gerade)\s+)?|"
            r"(?:zeitweise|vorübergehend|voruebergehend|gelegentlich|derzeit|aktuell|momentan|gerade)\s+)?"
            rf"(?:bei|mit)\s+(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
            rf"{_OTHER_RESIDENCE_OWNER_LABEL}\s+(?:in|bei)\s*",
            clause,
        )
    )


def _has_other_person_residence_prefix(source: str, pattern_start: int) -> bool:
    prefix = source[:pattern_start]
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_NON_SELF_REFERENCE}\s*$",
        prefix.rstrip(),
    ):
        return True
    if pattern_start < len(source) and source[pattern_start] in ",;":
        prefix += source[pattern_start]
    boundary = re.match(r"(?i)(?:und|sowie|oder|aber|doch|jedoch|sondern)\b", source[pattern_start:])
    if boundary:
        prefix += " " + boundary.group(0)
    segment = re.split(
        r"(?:[.!?\n]|[,;]|\b(?:und|sowie|oder|aber|doch|jedoch|sondern|während|waehrend)\b)\s*",
        prefix,
        flags=re.IGNORECASE,
    )[-1]
    if re.search(
        rf"(?i)\b(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+hat\s+"
        r"(?:ihr(?:e|en|em|er)?|sein(?:e|en|em|er)?|deren|den|einen?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+"
        r"(?:(?:zuhause|zu\s+hause|daheim)\s+)?(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b(?:der|die|das|ein(?:e|en|em|er|es)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+"
        r"(?:(?:von)\s+)?"
        rf"(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:hat|nennt|bezeichnet|betrachtet|führt|sieht)\s+"
        r"(?:ihr(?:e|en|em|er)?|sein(?:e|en|em|er)?|deren|den|einen?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:wohnt|wohnen|lebt|leben|ist|liegt|befindet\s+sich)\s+"
        r"(?:(?:zuhause|zu\s+hause|daheim)\s+)?(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_NON_SELF_REFERENCE}\s+{_OTHER_PERSON_LOCATION_LABEL}\s+"
        r"(?:wohnt|wohnen|lebt|leben|ist|liegt|befindet\s+sich)\s+"
        r"(?:(?:zuhause|zu\s+hause|daheim)\s+)?(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_LOCATION_LABEL}\s+(?:von\s+)?"
        rf"(?:{_OTHER_PERSON_REFERENCE}\s+)?{_OTHER_RESIDENCE_OWNER_LABEL}\b"
        r"[^.!?;,\n]{0,80}\b(?:ist|lautet|bleibt|liegt|befindet\s+sich)\s+"
        r"(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\s+"
        rf"(?:hat|haben)\s+(?:{_OTHER_PERSON_REFERENCE}\s+)?"
        rf"{_OTHER_PERSON_LOCATION_LABEL}\s+(?:in|bei)\s*$",
        segment,
    ) or re.search(
        rf"(?i)\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\s+"
        r"(?:ist|liegt|bleibt|befindet\s+sich)\s+(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\s+"
        r"(?:ist|liegt|bleibt|befindet\s+sich)\s+"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert|zuhause|zu\s+hause|daheim)\s+(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        rf"{_OTHER_PERSON_LOCATION_LABEL}\s+"
        r"(?:ist|lautet|bleibt|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_NON_SELF_REFERENCE}\s+{_OTHER_PERSON_LOCATION_LABEL}\s+"
        r"(?:ist|lautet|bleibt|liegt|befindet\s+sich)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b(?:der|die|das|ein(?:e|en|em|er|es)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+"
        r"(?:(?:von)\s+)?"
        rf"(?:{_OTHER_PERSON_REFERENCE}\s+)?{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:ist|lautet|bleibt|liegt|befindet\s+sich)\s+(?:in|bei)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b(?:der|die|das|ein(?:e|en|em|er|es)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+"
        r"(?:(?:von)\s+)?"
        rf"(?:{_OTHER_PERSON_REFERENCE}\s+)?{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:ist|lautet|bleibt|liegt|befindet\s+sich)\s*$",
        segment,
    ):
        return True
    if re.search(
        rf"(?i)\b{_OTHER_PERSON_LOCATION_LABEL}\s+(?:von\s+)?"
        rf"(?:{_OTHER_PERSON_REFERENCE}\s+)?{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:ist|lautet|bleibt|liegt|befindet\s+sich)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}(?=\s*[.!?;,]|\s*$)",
        segment,
    ) or re.search(
        rf"(?i)\b{_OTHER_PERSON_LOCATION_LABEL}\s+von\s+"
        rf"{_OTHER_PERSON_NON_SELF_REFERENCE}\s+"
        r"(?:ist|lautet|bleibt|liegt|befindet\s+sich)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}(?=\s*[.!?;,]|\s*$)",
        segment,
    ):
        return True
    return bool(
        re.search(
            rf"(?i)\b(?:der|die|das|ein(?:e|en|em|er|es)?)?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
            r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+"
            r"(?:(?:von)\s+)?"
            rf"(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?)\s+"
            rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+(?:ist|lautet|bleibt)\s*$",
            segment,
        )
    )


def _has_other_person_residence_candidate(value: str) -> bool:
    candidate = str(value or "")
    return bool(
        re.search(rf"(?i)\b{_OTHER_PERSON_FOREIGN_MARKER}\b", candidate)
        or re.search(rf"(?i)\bvon\s+{_OTHER_PERSON_RESIDENCE_LABEL}\b", candidate)
        or re.search(rf"(?i)\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\b", candidate)
    )


def _has_other_person_residence_suffix(source: str, city_end: int) -> bool:
    suffix = source[city_end:]
    if re.match(
        rf"(?i)\s+(?:als\s+)?{_OTHER_PERSON_LOCATION_LABEL}\s+(?:von\s+)?"
        rf"(?:{_OTHER_PERSON_REFERENCE}\s+)?{_OTHER_RESIDENCE_OWNER_LABEL}\b",
        suffix,
    ):
        return True
    if re.match(
        rf"(?i)\s+(?:ist|war|bleibt|liegt|befindet\s+sich)\s+"
        rf"{_OTHER_PERSON_NON_SELF_REFERENCE}\s+{_OTHER_PERSON_LOCATION_LABEL}\b",
        suffix,
    ):
        return True
    if re.match(
        r"(?i)\s+(?:ist|war|bleibt|liegt|befindet\s+sich)\s+"
        r"(?:(?:der|die|das|ein(?:e|en|em|er|es)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft|"
        r"arbeitsort|arbeitsadresse)\s+"
        r"(?:(?:von)\s+)?(?:mein(?:er|es|em|en)?|unser(?:er|es|em|en)?|"
        r"der|die|das|dem|den|des|ein(?:er|es|em|en)?)\s+"
        rf"{_OTHER_RESIDENCE_OWNER_LABEL}\b",
        suffix,
    ):
        return True
    return bool(
        re.match(
            rf"(?i)\s+(?:wohnt|wohnen|lebt|leben)\s+{_OTHER_PERSON_REFERENCE}\s+"
            rf"{_OTHER_PERSON_RESIDENCE_LABEL}\b",
            suffix,
        )
    )


def _has_other_person_as_residence_label(source: str, city_start: int, city_end: int) -> bool:
    prefix = source[:city_start]
    segment = re.split(
        r"(?:[,;]|\b(?:und|sowie|oder|aber|doch|jedoch|sondern)\b)\s*",
        prefix,
        flags=re.IGNORECASE,
    )[-1]
    if not re.search(
        rf"(?i)\b(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:hat|nennt|bezeichnet|betrachtet|führt|sieht)\s*$",
        segment,
    ):
        return False
    return bool(
        re.match(
            r"(?i)\s+(?:als\s+)?"
            r"(?:(?:ihr(?:e|en|em|er)?|sein(?:e|en|em|er)?|deren|den|einen?)\s+)?"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
            r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\b",
            source[city_end:],
        )
    )


def _has_non_residential_companion_context(source: str) -> bool:
    companion_pattern = re.compile(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:mit|bei)\s+"
        r"(?P<companion>[^,.;!?]{1,80})\s+(?:in|bei)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}(?=\s*(?:[.!?;,]|$))",
        re.IGNORECASE,
    )
    for match in companion_pattern.finditer(source):
        if re.search(
            r"\b(?:ausbild\w*|firma|unternehmen\w*|betrieb\w*|geschäft\w*|geschaeft\w*|"
            r"chef\w*|vorgesetz\w*|arbeitgeber\w*|schule\w*|uni\b|"
            r"universit(?:ät|aet)\w*|hochschule\w*|institut\w*|verband\w*|"
            r"behörde\w*|behoerde\w*|krankenhaus\w*|klinik\w*|praxis\w*|"
            r"abteilung\w*|organisation\w*|verein\w*)\b",
            match.group("companion"),
            re.IGNORECASE,
        ):
            return True
    return False


def _is_implicit_residence_alias_fragment(source: str, city_start: int, city_end: int) -> bool:
    candidate = source[city_start:city_end].strip(" .,:;!?")
    if candidate == "Auch" or candidate.casefold() not in _RESIDENCE_ALIAS_WORDS:
        return False
    return bool(
        re.search(
            r"\b(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|meldeadresse|meldeanschrift|meldesitz|"
            r"adresse|anschrift|zuhause|zu\s+hause|daheim)\s*"
            r"(?:(?:ist|liegt|lautet|befindet\s+sich)\s*)?$",
            source[:city_start].rstrip(),
            re.IGNORECASE,
        )
    )


def _standalone_residence_aliases(source: str) -> set[str]:
    aliases: set[str] = set()
    for match in re.finditer(
        r"\b(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"wohnadresse|wohnanschrift|meldeadresse|meldeanschrift|meldesitz|"
        r"adresse|anschrift|zuhause|zu\s+hause|daheim)\s+"
        r"(?P<alias>auch|ebenfalls|ebenso|gleichfalls)(?=\s*(?:[,.;!?]|$))",
        source,
        re.IGNORECASE,
    ):
        alias = match.group("alias")
        if alias == alias.casefold():
            aliases.add(alias)
    return aliases


def _has_conflicting_residence_address_targets(source: str) -> bool:
    if re.search(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"[^.!?;\n]{1,80}\s+(?:und|,)\s+(?:habe|haben)\s+"
        r"(?:dort|da|hier)\s+(?:keinen|keine|kein)\s+"
        r"(?:(?:fest\w*|dauerhaft\w*|eigen\w*|ständig\w*|staendig\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnadresse|wohnanschrift|anschrift|adresse)\b",
        source,
        re.IGNORECASE,
    ):
        return True
    city_capture = (
        r"(?:\d{5}\s+)?"
        r"(?:auch\s+)?(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?"
        r"(?:\s+\([^)]{1,30}\))?)(?=\s*(?:[,.;!?]|$))"
    )
    city_before_street_capture = (
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)"
        r"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*[.!?;,]|$)"
    )
    area_before_street_capture = rf"{_AREA_BEFORE_STREET_PREFIX}{_AREA_BEFORE_STREET_CITY}"
    attributive_area_before_street_capture = _ATTRIBUTIVE_AREA_BEFORE_STREET_CITY
    genitive_area_before_street_capture = _GENITIVE_AREA_BEFORE_STREET_CITY
    postal_city_before_street_capture = _POSTAL_CITY_BEFORE_STREET
    country_city_before_street_capture = _COUNTRY_CITY_BEFORE_STREET
    locality_prefix = (
        r"(?:in|bei|im)\s+(?:der\s+(?:stadt|gemeinde|kommune|ortschaft|landeshauptstadt|"
        r"metropole|großstadt|grossstadt)|stadtgebiet(?:\s+von)?)\s+"
    )
    street_address_prefix = _LABELED_STREET_ADDRESS
    short_residence_cities: set[str] = set()
    for match in re.finditer(
        r"\b(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:(?:aber|doch|jedoch)\s+)?(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
        source,
        re.IGNORECASE,
    ):
        if _has_other_person_residence_prefix(source, match.start("city")):
            continue
        city = _clean_city(match.group("city"))
        if city:
            short_residence_cities.add(_city_comparison_key(city))
    short_registered_cities: set[str] = set()
    for pattern in (
        re.compile(
            r"(?:^|[.!?;,:]\s*)(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|"
            r"dauerhaft\w*|aktuell\w*)\s+)?(?:gemeldet|registriert)\s+"
            r"(?:in|bei)\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:^|[.!?;,:]\s*)(?:in|bei)\s+"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:gemeldet|registriert)\b",
            re.IGNORECASE,
        ),
    ):
        for match in pattern.finditer(source):
            if _has_other_person_residence_prefix(source, match.start("city")):
                continue
            city = _clean_city(match.group("city"))
            if city:
                short_registered_cities.add(_city_comparison_key(city))
    if short_residence_cities and short_registered_cities and short_residence_cities.isdisjoint(
        short_registered_cities
    ):
        return True
    residence_patterns = (
        _INVERTED_RELATIVE_RESIDENCE_CITY,
        _SHORT_SELF_RESIDENCE_AFTER_OTHER_PERSON_CITY,
        _SHORT_SELF_RESIDENCE_AFTER_OTHER_PERSON_LABEL_CITY,
        _CITY_CHANGE_CITY_BEFORE_STREET,
        _CITY_CHANGE_CITY_BEFORE_STREET_MOVE,
        _CITY_CHANGE_CITY_BEFORE_STREET_MOVE_FROM,
        _CITY_CHANGE_CURRENT_CITY_BEFORE_STREET,
        _CITY_CHANGE_OLD_NEW_CITY_BEFORE_STREET,
        _CITY_CHANGE_LABELLED_CITY_BEFORE_STREET,
        _CITY_CHANGE_LABELLED_DIRECTION_CITY_BEFORE_STREET,
        _CITY_CHANGE_DIRECTIONAL_CITY_BEFORE_STREET,
        _CITY_CHANGE_MOVE_FROM_CITY_BEFORE_STREET,
        _CITY_CHANGE_ZOG_CITY_BEFORE_STREET,
        _CITY_CHANGE_MOVE_LABEL_CITY_BEFORE_STREET,
        _CITY_CHANGE_CURRENT_AS_RESIDENCE_CITY_BEFORE_STREET,
        _CITY_CHANGE_UPDATED_NEW_FIRST_CITY_BEFORE_STREET,
        _CITY_CHANGE_CURRENT_NOT_MORE_CITY_BEFORE_STREET,
        _CITY_CHANGE_OLD_PRONOUN_CURRENT_CITY_BEFORE_STREET,
        _CITY_CHANGE_LEADING_OLD_PRONOUN_CURRENT_CITY_BEFORE_STREET,
        _CITY_CHANGE_CITY_BEFORE_RESIDENCE_LABEL,
        _CITY_CHANGE_STREET_BEFORE_RESIDENCE_LABEL,
        _CITY_CHANGE_FORMER_LABEL_STREET_BEFORE_CURRENT,
        _CITY_CHANGE_STREET_BEFORE_LABEL_CURRENT_CITY,
        _CITY_CHANGE_STREET_BEFORE_LABEL_NOT_MORE,
        _CITY_CHANGE_COLON_LABELLED_OLD_NEW_STREET,
        _CITY_CHANGE_LABELLED_ALT_NEW_COLON_STREET,
        _CITY_CHANGE_LABELLED_TEMPORAL_INLINE_CITY,
        _CITY_CHANGE_LABELLED_FROM_TO_STREET,
        _CITY_CHANGE_PASSIVE_LABELLED_FROM_TO_STREET,
        _CITY_CHANGE_NOMINAL_MOVE_LABELLED_STREET,
        _CITY_CHANGE_LABELLED_COLON_SEPARATOR_STREET,
        re.compile(
            rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
            rf"{country_city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
            rf"{area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
            rf"{street_address_prefix}{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,\n]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*(?:wohnort|wohnsitz)\s+"
            rf"(?:ist|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,\n]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+"
            r"(?!(?:ist|liegt|befindet\s+sich)\b)"
            rf"{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
            r"(?:meinen|meine|mein|unseren|unsere|unser|einen|eine|ein|den|die|das)\s+"
            rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"adresse|wohnadresse|wohnanschrift|anschrift)\s+(?:in|bei)\s+"
            rf"{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
            rf"(?:im|in\s+der)\s+{attributive_area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+"
            rf"{genitive_area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
            rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
            r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+"
            rf"(?:im|in\s+der)\s+{attributive_area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
            rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
            r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)(?:\s+|\s*[:=,]\s*)"
            rf"{country_city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei)\s+"
            rf"{postal_city_before_street_capture}\s+"
            r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
            r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)"
            r"(?:\s+(?:in|bei)\s+|\s*[:=,]\s*|\s+)"
            rf"{postal_city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
            rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
            r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+"
            rf"{genitive_area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
            rf"{postal_city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
            rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
            r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+(?:in|bei)\s+"
            rf"{postal_city_before_street_capture}",
            re.IGNORECASE,
        ),
    )
    address_patterns = (
        _GENITIVE_RESIDENCE_ADDRESS_CITY,
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
            rf"{country_city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
            rf"{street_address_prefix}{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
            rf"{postal_city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
            rf"(?:im|in\s+der)\s+{attributive_area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
            rf"{genitive_area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
            rf"{area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
            rf"{city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
            rf"{locality_prefix}{city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)\s+"
            r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
            rf"{locality_prefix}{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
            r"(?:wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"(?:(?::|=|,)\s*|\s+)"
            rf"{street_address_prefix}{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"\s*(?::|=|,)\s*"
            rf"{country_city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"\s*(?::|=|,)\s*(?:(?:in|bei)\s+)?"
            rf"{postal_city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"\s*(?::|=|,)\s*"
            rf"(?:im|in\s+der)\s+{attributive_area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"\s*(?::|=|,)\s*"
            rf"{genitive_area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"\s*(?::|=|,)\s*"
            rf"{area_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"\s*(?::|=|,)\s*(?:(?:in|bei)\s+)?"
            rf"{city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"\s*(?::|=|,)\s*"
            rf"{locality_prefix}{city_before_street_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
            r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"\s*(?::|=|,)\s*"
            rf"{locality_prefix}{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
            r"jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
            r"(?:adresse|wohnadresse|wohnanschrift|anschrift)\s+"
            rf"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
            rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
            r"(?:wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse)"
            r"(?:(?::|=|,)\s*|\s+)"
            r"(?!(?:ist|war|wird|liegt|lautet|befindet\s+sich|bleibt)\b)"
            rf"{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+(?:meine|unsere)\s+"
            r"(?:adresse|wohnadresse|wohnanschrift|anschrift)\s+(?:in|bei)\s+"
            rf"{city_capture}",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
            r"(?:meine|unsere|eine|ein|die|das)\s+"
            r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
            r"jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
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
                pattern_start = match.start()
                city_start = match.start("city")
                city_end = match.end("city")
                if _is_implicit_residence_alias_fragment(source, city_start, city_end):
                    continue
                if (
                    _has_historical_residence_prefix(source, pattern_start)
                    or _has_future_residence_prefix(source, pattern_start, city_start)
                    or _has_uncertain_residence_prefix(source, pattern_start)
                    or _has_temporary_residence_prefix(source, pattern_start)
                    or _has_historical_residence_suffix(source, city_end)
                    or _has_future_residence_suffix(source, city_end)
                    or _has_uncertain_residence_suffix(source, city_end)
                    or _has_other_person_residence_candidate(match.group("city"))
                    or _has_other_person_residence_prefix(source, pattern_start)
                    or _has_other_person_residence_prefix(source, city_start)
                    or _has_other_person_residence_prefix(source, city_end)
                    or _has_other_person_as_residence_label(source, city_start, city_end)
                    or _has_other_person_residence_suffix(source, city_end)
                    or _has_non_residential_city_tail(match.group("city"))
                    or _has_non_residential_city_suffix(source, city_end)
                ):
                    continue
                city = _clean_city(match.group("city"))
                if city:
                    values.add(_city_comparison_key(city))
        return values

    residence_cities = collect(residence_patterns)
    address_cities = collect(address_patterns)
    genitive_address_cities = collect((_GENITIVE_RESIDENCE_ADDRESS_CITY,))
    if len(genitive_address_cities) > 1:
        return True
    for match in re.finditer(
        rf"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:hauptadresse|adresse|wohnadresse|wohnanschrift|privatadresse|privatanschrift|"
        r"anschrift)\s*(?::|=|,|\s+(?:ist|lautet|liegt|befindet\s+sich)\s+)"
        rf"(?:(?:in|bei)\s+)?(?:(?:auch|ebenfalls|ebenso|gleichfalls)\s+)?{city_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        r"ist\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:hauptadresse|adresse|wohnadresse|wohnanschrift|privatadresse|privatanschrift|"
        r"anschrift)\b",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\bund\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        r"ist\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:hauptadresse|adresse|wohnadresse|wohnanschrift|privatadresse|privatanschrift|"
        r"anschrift)\b",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        r"(?:ist\s+)?(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim)\b",
        source,
        re.IGNORECASE,
    ):
        city_start = match.start("city")
        city_end = match.end("city")
        if (
            _has_historical_residence_prefix(source, match.start())
            or _has_future_residence_prefix(source, match.start(), city_start)
            or _has_uncertain_residence_prefix(source, match.start())
            or _has_temporary_residence_prefix(source, match.start())
            or _has_historical_residence_suffix(source, city_end)
            or _has_future_residence_suffix(source, city_end)
            or _has_uncertain_residence_suffix(source, city_end)
            or _has_non_residential_city_tail(match.group("city"))
            or _has_non_residential_city_suffix(source, city_end)
        ):
            continue
        city = _clean_city(match.group("city"))
        if city:
            residence_cities.add(_city_comparison_key(city))
    registered_address_cities: set[str] = set()
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:(?::|=|,)\s*|(?:ist|lautet|liegt|befindet\s+sich)\s+)?"
        rf"(?:{street_address_prefix}|(?:(?:in|bei)\s+))?"
        rf"{city_capture}",
        source,
        re.IGNORECASE,
    ):
        if (
            _has_historical_residence_prefix(source, match.start())
            or _has_future_residence_prefix(source, match.start(), match.start("city"))
            or _has_uncertain_residence_prefix(source, match.start())
            or _has_historical_residence_suffix(source, match.end("city"))
            or _has_future_residence_suffix(source, match.end("city"))
            or _has_uncertain_residence_suffix(source, match.end("city"))
        ):
            continue
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\bund\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        r"ist\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\b",
        source,
        re.IGNORECASE,
    ):
        city_start = match.start("city")
        city_end = match.end("city")
        if (
            _has_historical_residence_prefix(source, match.start())
            or _has_future_residence_prefix(source, match.start(), city_start)
            or _has_uncertain_residence_prefix(source, match.start())
            or _has_historical_residence_suffix(source, city_end)
            or _has_future_residence_suffix(source, city_end)
            or _has_uncertain_residence_suffix(source, city_end)
        ):
            continue
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        rf"{country_city_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        if (
            _has_historical_residence_prefix(source, match.start())
            or _has_future_residence_prefix(source, match.start(), match.start("city"))
            or _has_uncertain_residence_prefix(source, match.start())
            or _has_historical_residence_suffix(source, match.end("city"))
            or _has_future_residence_suffix(source, match.end("city"))
            or _has_uncertain_residence_suffix(source, match.end("city"))
        ):
            continue
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)\s*"
        rf"{country_city_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    registration_patterns = (
        re.compile(
            r"(?:^|[.!?;,:]\s*|\bund\s+)"
            r"(?:(?:aber|doch|jedoch)\s+)?"
            r"(?:(?:ich|wir)\s+)?"
            r"(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|dauerhaft\w*|aktuell\w*)\s+)?"
            r"(?:bin|sind)\s+(?:(?:aber|doch|jedoch)\s+)?"
            r"(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|dauerhaft\w*|aktuell\w*)\s+)?"
            r"(?:in|bei)\s+"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
            r"(?:gemeldet|registriert)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:^|[.!?;,:]\s*|\bund\s+)"
            r"(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|dauerhaft\w*|aktuell\w*)\s+)?"
            r"(?:ich|wir)\s+(?:bin|sind)\s+"
            r"(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|dauerhaft\w*|aktuell\w*)\s+)?"
            r"(?:in|bei)\s+"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
            r"(?:gemeldet|registriert)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:^|[.!?;,:]\s*|\bund\s+)"
            r"(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|dauerhaft\w*|aktuell\w*)\s+)?"
            r"(?:gemeldet|registriert)\s+(?:in|bei)\s+"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:^|[.!?;,:]\s*|\bund\s+)"
            r"(?:(?:aber|doch|jedoch)\s+)?(?:in|bei)\s+"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
            r"(?:gemeldet|registriert)\b",
            re.IGNORECASE,
        ),
        _INVERTED_REGISTERED_CITY,
        re.compile(
            r"\b(?:meine|unsere|mein|unser)\s+"
            r"(?:(?:offiziell\w*|amtlich\w*|polizeilich\w*|aktuell\w*)\s+)?"
            r"(?:meldung|registrierung)\s+(?:ist|lautet|liegt)\s+"
            r"(?:(?:in|bei)\s+)?"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:^|[.!?;,:]\s*|\bund\s+)(?:in|bei)\s+"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
            r"(?:bin|sind)\s+(?:ich|wir)\s+(?:gemeldet|registriert)\b",
            re.IGNORECASE,
        ),
    )
    for pattern in registration_patterns:
        for match in pattern.finditer(source):
            if (
                _has_historical_residence_prefix(source, match.start())
                or _has_future_residence_prefix(source, match.start(), match.start("city"))
                or _has_uncertain_residence_prefix(source, match.start())
                or _has_temporary_residence_prefix(source, match.start())
            ):
                continue
            city = _clean_city(match.group("city"))
            if city:
                registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        rf"{postal_city_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)\s*"
        r"(?:(?:in|bei)\s+)?"
        rf"{postal_city_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        rf"(?:im|in\s+der)\s+{attributive_area_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        rf"{genitive_area_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)\s*"
        rf"(?:im|in\s+der)\s+{attributive_area_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)\s*"
        rf"{genitive_area_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)\s*"
        r"(?:(?:in|bei)\s+)?"
        rf"{city_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        rf"{area_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)\s*"
        rf"{area_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)\s*"
        rf"{locality_prefix}{city_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*(?::|=|,)\s*"
        rf"{locality_prefix}{city_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        rf"{locality_prefix}{city_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        rf"{locality_prefix}{city_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"\b(?:(?:{_RESIDENCE_LABEL_DETERMINER})\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\s*"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        rf"{city_before_street_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*|\bund\s+)(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        r"ist\s+(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:meldeadresse|meldeanschrift|meldesitz)\b",
        source,
        re.IGNORECASE,
    ):
        city_start = match.start("city")
        city_end = match.end("city")
        if (
            _has_historical_residence_prefix(source, match.start())
            or _has_future_residence_prefix(source, match.start(), city_start)
            or _has_uncertain_residence_prefix(source, match.start())
            or _has_historical_residence_suffix(source, city_end)
            or _has_future_residence_suffix(source, city_end)
            or _has_uncertain_residence_suffix(source, city_end)
        ):
            continue
        city = _clean_city(match.group("city"))
        if city:
            registered_address_cities.add(_city_comparison_key(city))
    registered_address_cities = {
        city
        for city in registered_address_cities
        if not _has_other_person_residence_candidate(city)
    }
    foreign_registered_city_keys: set[str] = set()
    for match in re.finditer(
        rf"(?i)\b{_OTHER_PERSON_REFERENCE}\s+{_OTHER_RESIDENCE_OWNER_LABEL}\s+"
        r"(?:hat|haben)\s+"
        rf"(?:{_OTHER_PERSON_REFERENCE}\s+)?{_OTHER_PERSON_LOCATION_LABEL}\s+"
        r"(?:in|bei)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*[.!?;,]|\s*$)",
        source,
    ):
        city = _clean_city(match.group("city"))
        if city:
            foreign_registered_city_keys.add(_city_comparison_key(city))
    registered_address_cities.difference_update(foreign_registered_city_keys)
    registered_address_cities.difference_update(_standalone_residence_aliases(source))
    if (
        short_residence_cities
        and registered_address_cities
        and short_residence_cities.isdisjoint(registered_address_cities)
    ):
        return True
    residence_address_cities = residence_cities | address_cities
    if (
        residence_address_cities
        and registered_address_cities
        and residence_address_cities.isdisjoint(registered_address_cities)
    ):
        return True
    if any(
        pattern.search(source)
        for pattern in (
            _CITY_CHANGE_CITY_BEFORE_STREET,
            _CITY_CHANGE_CITY_BEFORE_STREET_MOVE,
            _CITY_CHANGE_CITY_BEFORE_STREET_MOVE_FROM,
            _CITY_CHANGE_CURRENT_CITY_BEFORE_STREET,
            _CITY_CHANGE_OLD_NEW_CITY_BEFORE_STREET,
            _CITY_CHANGE_LABELLED_CITY_BEFORE_STREET,
            _CITY_CHANGE_LABELLED_DIRECTION_CITY_BEFORE_STREET,
            _CITY_CHANGE_DIRECTIONAL_CITY_BEFORE_STREET,
            _CITY_CHANGE_MOVE_FROM_CITY_BEFORE_STREET,
            _CITY_CHANGE_ZOG_CITY_BEFORE_STREET,
            _CITY_CHANGE_MOVE_LABEL_CITY_BEFORE_STREET,
            _CITY_CHANGE_CURRENT_AS_RESIDENCE_CITY_BEFORE_STREET,
            _CITY_CHANGE_UPDATED_NEW_FIRST_CITY_BEFORE_STREET,
            _CITY_CHANGE_CURRENT_NOT_MORE_CITY_BEFORE_STREET,
            _CITY_CHANGE_OLD_PRONOUN_CURRENT_CITY_BEFORE_STREET,
            _CITY_CHANGE_LEADING_OLD_PRONOUN_CURRENT_CITY_BEFORE_STREET,
            _CITY_CHANGE_CITY_BEFORE_RESIDENCE_LABEL,
            _CITY_CHANGE_STREET_BEFORE_RESIDENCE_LABEL,
            _CITY_CHANGE_FORMER_LABEL_STREET_BEFORE_CURRENT,
            _CITY_CHANGE_STREET_BEFORE_LABEL_CURRENT_CITY,
            _CITY_CHANGE_STREET_BEFORE_LABEL_NOT_MORE,
            _CITY_CHANGE_COLON_LABELLED_OLD_NEW_STREET,
            _CITY_CHANGE_LABELLED_ALT_NEW_COLON_STREET,
            _CITY_CHANGE_LABELLED_TEMPORAL_INLINE_CITY,
            _CITY_CHANGE_LABELLED_FROM_TO_STREET,
            _CITY_CHANGE_PASSIVE_LABELLED_FROM_TO_STREET,
            _CITY_CHANGE_NOMINAL_MOVE_LABELLED_STREET,
            _CITY_CHANGE_LABELLED_COLON_SEPARATOR_STREET,
        )
    ) and not registered_address_cities:
        return False
    work_address_cities: set[str] = set()
    for match in re.finditer(
        r"\b(?:(?:mein(?:e)?|unser(?:e)?)\s+)?"
        r"(?:arbeitsadresse|geschäftsadresse|geschaeftsadresse|dienstadresse|büroadresse|bueroadresse|"
        r"arbeitsanschrift|dienstanschrift)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+(?:(?:in|bei)\s+)?"
        rf"{city_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            work_address_cities.add(_city_comparison_key(city))
    for match in re.finditer(
        r"\b(?:meine|unsere|meinen|unseren)\s+"
        r"(?:arbeitsadresse|geschäftsadresse|geschaeftsadresse|dienstadresse|büroadresse|bueroadresse|"
        r"arbeitsanschrift|dienstanschrift)\s+(?:in|bei)\s+"
        rf"{city_capture}",
        source,
        re.IGNORECASE,
    ):
        city = _clean_city(match.group("city"))
        if city:
            work_address_cities.add(_city_comparison_key(city))
    if address_cities and work_address_cities and address_cities.isdisjoint(work_address_cities):
        return True
    return bool(residence_cities and address_cities and residence_cities.isdisjoint(address_cities))


def _has_ambiguous_residence_targets(source: str) -> bool:
    residence = r"(?:wohne|wohnen|lebe|leben|wohn|leb|gemeldet|registriert)"
    residence_targets: set[str] = set()
    same_city_residence_label = re.search(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        r"(?P<first>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+(?:und|,)\s+"
        r"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:meldeadresse|meldeanschrift|meldesitz|wohnadresse|wohnanschrift|"
        r"adresse|anschrift|wohnsitz)\b",
        source,
        re.IGNORECASE,
    )
    if same_city_residence_label:
        first = _clean_city(same_city_residence_label.group("first"))
        second = _clean_city(same_city_residence_label.group("second"))
        if first and second and _city_comparison_key(first) == _city_comparison_key(second):
            return False
    same_city_reference_label = re.search(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich|bleibt)\s+"
        r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+und\s+"
        r"(?:dort|da|hier)\s+(?:ist|liegt|befindet\s+sich|bleibt)\s+"
        r"(?:auch\s+)?(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:meldeadresse|meldeanschrift|meldesitz|wohnadresse|wohnanschrift|"
        r"adresse|anschrift|wohnsitz)\b(?=\s*(?:[.!?;]|$))",
        source,
        re.IGNORECASE,
    )
    if same_city_reference_label and _clean_city(same_city_reference_label.group("city")):
        return False
    same_city_genitive_address = re.search(
        r"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich|bleibt)\s+"
        r"(?P<first>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+und\s+"
        r"(?:die|der|das|eine|meine|unsere)?\s*"
        r"(?:adresse|wohnadresse|wohnanschrift|anschrift|ort)\s+"
        r"(?:meines|meiner|unseres|unserer)\s+"
        r"(?:wohnort(?:s|es)?|wohnsitz(?:es)?|hauptwohnsitz(?:es)?|"
        r"lebensmittelpunkt(?:s|es)?|wohnung|zuhauses?)\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich)\s+"
        r"(?:auch|ebenfalls|ebenso|gleichfalls)?\s*"
        r"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)(?=\s*(?:[.!?;,]|$))",
        source,
        re.IGNORECASE,
    )
    if same_city_genitive_address:
        first = _clean_city(same_city_genitive_address.group("first"))
        second = _clean_city(same_city_genitive_address.group("second"))
        if first and second and _city_comparison_key(first) == _city_comparison_key(second):
            return False
    if re.search(
        r"(?:\b(?:ich|wir)\s+(?:bin|sind)\s+(?:in|bei)\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+|"
        r"(?:^|[.!?;,:]\s*)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+"
        r"(?:bin|sind)\s+(?:ich|wir)\s+)"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\b\s+"
        r"(?:ab\s+(?:morgen|übermorgen|uebermorgen|nächste\w*|naechste\w*|kommende\w*)\b|"
        r"ab\s+(?:dem\s+)?(?:nächste\w*|naechste\w*|kommende\w*)\s+"
        r"(?:jahr\w*|monat\w*|woche\w*)\b|"
        r"ab\s+(?:übermorgen|uebermorgen|morgen|sommer|winter|frühling|fruehling|herbst)\b|"
        r"ab\s+\d{4}\b|"
        r"(?:künft\w*|kuenft\w*|zukünft\w*|zukuenftig|geplant\w*|beabsichtig\w*)\b)",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(?:^|[.!?;,:]\s*)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim)\b\s+"
        r"(?:ab\s+(?:morgen|übermorgen|uebermorgen|nächste\w*|naechste\w*|kommende\w*)\b|"
        r"ab\s+(?:dem\s+)?(?:nächste\w*|naechste\w*|kommende\w*)\s+"
        r"(?:jahr\w*|monat\w*|woche\w*)\b|"
        r"ab\s+(?:übermorgen|uebermorgen|morgen|sommer|winter|frühling|fruehling|herbst)\b|"
        r"ab\s+\d{4}\b|"
        r"(?:künft\w*|kuenft\w*|zukünft\w*|zukuenft\w*|geplant\w*|beabsichtig\w*)\b|"
        r"(?:gewesen|worden|ehemals|damals|vormalig\w*|früher|frueher)\b)",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(?:^|[.!?;,:]\s*)[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:hauptadresse|adresse|wohnadresse|wohnanschrift|privatadresse|privatanschrift|"
        r"anschrift|meldeadresse|meldeanschrift|meldesitz)\b\s+"
        r"(?:ab\s+(?:morgen|übermorgen|uebermorgen|nächste\w*|naechste\w*|kommende\w*)\b|"
        r"ab\s+(?:dem\s+)?(?:nächste\w*|naechste\w*|kommende\w*)\s+"
        r"(?:jahr\w*|monat\w*|woche\w*)\b|"
        r"ab\s+(?:übermorgen|uebermorgen|morgen|sommer|winter|frühling|fruehling|herbst)\b|"
        r"ab\s+\d{4}\b|"
        r"(?:künft\w*|kuenft\w*|zukünft\w*|zukuenft\w*|geplant\w*|beabsichtig\w*)\b|"
        r"(?:gewesen|worden|ehemals|damals|vormalig\w*|früher|frueher)\b)",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:(?:und|sowie|aber|doch|jedoch|oder|sondern|während|waehrend)\s+)?"
        rf"[^.!?;,\n]{{0,160}}\b{_OTHER_PERSON_FOREIGN_MARKER}\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b(?:mein(?:e)?|unser(?:e)?)?\s*{_OTHER_PERSON_LOCATION_LABEL}\s+"
        r"(?:ist|lautet|liegt|befindet\s+sich|bleibt)\s+(?:(?:in|bei)\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s*[,;]?\s*"
        r"(?:und|sowie|aber|doch|jedoch|oder|sondern|während|waehrend)?\s*"
        rf"[^.!?;,\n]{{0,160}}\b{_OTHER_PERSON_FOREIGN_MARKER}\b",
        source,
        re.IGNORECASE,
    ) or re.search(
        r"\b[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+(?:ist\s+)?"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        rf"{_OTHER_PERSON_LOCATION_LABEL}\s*[,;]?\s*"
        r"(?:und|sowie|aber|doch|jedoch|oder|sondern|während|waehrend)?\s*"
        rf"[^.!?;,\n]{{0,160}}\b{_OTHER_PERSON_FOREIGN_MARKER}\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+"
        rf"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:"
        r"(?:ist|liegt|befindet\s+sich)\s+(?:(?:zuhause|zu\s+hause|daheim)\s+)?"
        r"|hat\s+(?:ihr(?:e|en|em|er)?|sein(?:e|en|em|er)?|deren|den|einen?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+"
        r")"
        r"(?:in|bei)\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+"
        rf"(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:hat|nennt|bezeichnet|betrachtet)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}\s+"
        r"(?:als\s+)?"
        r"(?:(?:ihr(?:e|en|em|er)?|sein(?:e|en|em|er)?|deren|den|einen?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+"
        r"(?:der|die|das|ein(?:e|en|em|er|es)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+"
        r"(?:(?:von)\s+)?"
        rf"(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+(?:in|bei)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+"
        r"(?:der|die|das|ein(?:e|en|em|er|es)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+"
        r"(?:(?:von)\s+)?"
        rf"(?:mein(?:e|en|em|er|es)?|unser(?:e|en|em|er|es)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+(?:ist|lautet|bleibt)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}[,;]\s*"
        r"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_SECONDARY_RESIDENCE_LABEL}\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
        rf"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:wohne|wohnen|wohnt|lebe|leben|lebt)\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
        r"(?:(?:in|bei)\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+"
        r"(?:wohnt|leben|lebt|wohnen)\s+"
        rf"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+{_OTHER_PERSON_RESIDENCE_LABEL}\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
        r"(?:(?:in|bei)\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+ist\s+"
        rf"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:zuhause|zu\s+hause|daheim|wohnhaft|gemeldet|registriert)\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+"
        r"(?:ist|war|bleibt|liegt|befindet\s+sich)\s+"
        r"(?:(?:der|die|das|ein(?:e|en|em|er|es)?)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft|"
        r"arbeitsort|arbeitsadresse)\s+"
        r"(?:(?:von)\s+)?(?:mein(?:er|es|em|en)?|unser(?:er|es|em|en)?|"
        r"der|die|das|dem|den|des|ein(?:er|es|em|en)?)\s+"
        rf"{_OTHER_RESIDENCE_OWNER_LABEL}\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        rf"{_CITY_CHANGE_CITY_FRAGMENT}(?:\s+\([^)]{{1,30}}\))?\s*,\s*"
        rf"{_LABELED_STREET_ADDRESS_CORE}\s+und\s+"
        rf"(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:zeitweise|abwechselnd|teilweise|vorübergehend|voruebergehend)\s+"
        r"(?:in|bei)\s+"
        rf"{_CITY_CHANGE_CITY_FRAGMENT}(?:\s+\([^)]{{1,30}}\))?\s*,\s*"
        rf"{_LABELED_STREET_ADDRESS_CORE}(?=\s*[.!?;,]|$)",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(_COUNTRY_CITY_BEFORE_STREET, source, re.IGNORECASE):
        return False
    if re.search(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        rf"(?:{_STREET_COMPOUND_CITY_PATTERN}|[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)"
        rf"(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+){_LABELED_STREET_ADDRESS_CORE}"
        r"(?=\s*(?:[.!?;,]|wohnhaft|ansässig|ansaessig|gemeldet|registriert|"
        r"und\s+(?:umgebung|region|nähe|naehe)|$))",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        rf"{_POSTAL_CITY_BEFORE_STREET}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz)\s*(?::|=|,)\s*(?:(?:in|bei)\s+)?"
        rf"(?:{_STREET_COMPOUND_CITY_PATTERN}|[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)"
        r"(?:\s+\([^)]{1,30}\))?(?:\s*,\s*|\s+(?:in|an|auf|unter)\s+)"
        rf"{_LABELED_STREET_ADDRESS_CORE}(?=\s*[.!?;,]|$)",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz)\s*(?::|=|,)\s*(?:(?:in|bei)\s+)?"
        rf"{_POSTAL_CITY_BEFORE_STREET}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        r"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben|bin|sind)\s+(?:in|bei)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s*,\s*"
        r"(?:zu\s+hause|zuhause|daheim)\s*[.!?;]?$",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}},\s*"
        r"(?:ganz\s+)?(?:sicher|wirklich|tatsächlich|tatsaechlich)\s*[.!?]?$",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+[^,.;!?]{1,80}?"
        r"(?:\s*,\s*|\s*;\s*|\s+und\s+)"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:arbeitsort|arbeitsadresse|geschäftsadresse|geschaeftsadresse|dienstadresse|"
        r"büroadresse|bueroadresse)\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"(?:\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+|"
        rf"\b(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+|"
        rf"(?:^|[.!?;,:]\s*)(?:(?:ich|wir)\s+(?:bin|sind)\s+)?"
        rf"(?:(?:{_RESIDENCE_LABEL_CURRENT_QUALIFIER})\s+)?"
        r"(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert)\s+|"
        rf"(?:^|[.!?;,:]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|hauptwohnsitz|lebensmittelpunkt|wohnadresse|wohnanschrift|"
        r"anschrift|adresse|privatadresse|privatanschrift|meldeadresse|meldeanschrift|"
        r"meldesitz|wohnung|unterkunft|bleibe|mietwohnung|wg)\s*(?::|=|,)\s*)"
        rf"{_AREA_BEFORE_STREET_PREFIX}{_AREA_BEFORE_STREET_CITY}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        r"\b(?:ich|wir)\s+hab(?:e|en)?['’]?\s+"
        r"(?:meinen|meine|mein|unseren|unsere|unser|einen|eine|ein|den|die|das)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"jetzig\w*|derzeitig\w*|gegenwärtig\w*|gegenwaertig\w*)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"adresse|wohnadresse|wohnanschrift|anschrift)\s+(?:in|bei)\s+"
        r"(?:\d{5}\s+)?[^,.;!?]{1,80}\s+und\s+"
        r"(?!(?:umgebung|region|nähe|naehe)\b)(?:\d{5}\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}",
        source,
        re.IGNORECASE,
    ):
        return True
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
        re.compile(
            r"(?:^|[.!?;,\n]\s*)(?:aber|doch|jedoch|sondern)?\s*"
            r"(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s+"
            r"ist\s+(?:mein(?:e)?|unser(?:e)?)\s+"
            r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|zuhause|zu\s+hause|daheim)\b",
            re.IGNORECASE,
        ),
    )
    for pattern in target_patterns:
        for match in pattern.finditer(source):
            pattern_start = match.start()
            city_start = match.start("city")
            city_end = match.end("city")
            if (
                _has_historical_residence_prefix(source, pattern_start)
                or _has_future_residence_prefix(source, pattern_start, city_start)
                or _has_uncertain_residence_prefix(source, pattern_start)
                or _has_historical_residence_suffix(source, city_end)
                or _has_future_residence_suffix(source, city_end)
                or _has_uncertain_residence_suffix(source, city_end)
                or _has_other_person_residence_candidate(match.group("city"))
                or _has_other_person_residence_prefix(source, pattern_start)
                or _has_other_person_residence_prefix(source, city_start)
                or _has_other_person_residence_prefix(source, city_end)
            ):
                continue
            city = _clean_city(match.group("city"))
            if city:
                residence_targets.add(_city_comparison_key(city))
    if len(residence_targets) > 1:
        return True
    bare_label_conflict = re.search(
        rf"(?:^|[.!?;\n]\s*)(?:{_RESIDENCE_LABEL_DETERMINER})?\s*"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse|"
        r"meldeadresse|meldeanschrift|meldesitz|zuhause|zu\s+hause|daheim)\s*"
        r"(?::|=|,)?\s*(?:\d{5}\s+)?(?P<first>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?)\s*"
        r"(?:[,;]|\bund\b)\s*(?:\d{5}\s+)?"
        r"(?!(?:aber|doch|jedoch|genauer\b|konkret\b|nämlich\b|naemlich\b|und\s+zwar\b|"
        r"umgebung\b|region\b|nähe\b|naehe\b|"
        r"(?:mein(?:e)?|unser(?:e)?)?\s*(?:geburtsort|geburtsstadt|heimat|heimatstadt|"
        r"herkunftsort|herkunftsstadt|arbeitsort|arbeitsadresse|geschäftsadresse|"
        r"geschaeftsadresse|dienstadresse|büroadresse|bueroadresse|"
        r"wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"wohnadresse|wohnanschrift|privatadresse|privatanschrift|anschrift|adresse|"
        r"meldeadresse|meldeanschrift|meldesitz|zuhause|zu\s+hause|daheim)\b))"
        r"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]*?)\s*(?:[.!?;,]|$)",
        source,
        re.IGNORECASE,
    )
    if bare_label_conflict:
        first_raw = bare_label_conflict.group("first").strip()
        first = _clean_city(first_raw)
        second_raw = bare_label_conflict.group("second").strip()
        second = _clean_city(bare_label_conflict.group("second"))
        if (
            first
            and not re.match(r"(?i)^(?:in|bei)\s+", second_raw)
            and second
            and second.casefold() not in (_NON_CITY_RESIDENCE_NAMES | _NON_CITY_REGION_NAMES)
            and not re.match(
                rf"(?i)^(?:(?:mein(?:e)?|unser(?:e)?)\s+)?{_SECONDARY_RESIDENCE_LABEL}"
                r"(?=\s|[:=,]|$)",
                second_raw,
            )
        ):
            if _has_other_person_residence_candidate(first_raw) or _has_other_person_residence_candidate(second_raw):
                return False
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
        second = comma_match.group("second") if comma_match else ""
        if first and re.search(
            rf"(?i){_STREET_TYPE}\s+(?:{_STREET_NUMBER_LABEL}\s*)?\d+[a-z]?\b|"
            r"(?:am|an der|an den|auf der|auf dem|auf den|unter der|unter den|in der|in den|"
            rf"im|zum|zur|vom|von der|vor der|hinter der)\s+[^,.;!?]{{1,100}}?\s+(?:{_STREET_NUMBER_LABEL}\s*)?\d+[a-z]?\b",
            first,
        ) or re.search(rf"(?i){_STREET_TYPE}$", second.strip()):
            continue
        if comma_match and comma_match.group("second").casefold() not in (
            _NON_CITY_RESIDENCE_NAMES | _NON_CITY_REGION_NAMES
        ):
            return True
    if re.search(
        rf"\b{residence}\s+(?:in\s+der\s+(?:naehe|n(?:ä|ae)he|umgebung)(?:\s+von)?|im\s+raum|"
        r"rund\s+um|nahe|unweit(?:\s+von)?|nicht\s+weit\s+(?:entfernt\s+)?von|"
        r"au(?:ßerhalb|sserhalb)(?:\s+von)?|am\s+stadtrand\s+von|im\s+umland(?:\s+von)?|"
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
        r"hab\w*\b|besitz\w*\b|besuch\w*\b|verbring\w*\b|treff\w*\b|reis\w*\b|pend\w*\b|"
        r"seh\w*\b|übernacht\w*\b|uebernacht\w*\b|"
        r"(?:umgebung|region|nähe|naehe)(?!\s+von\b)\b)[\wÄÖÜäöüß'-]+",
        source,
        re.IGNORECASE,
    ):
        return True
    ambiguous_label_match = re.search(
        r"\b(?:mein(?:e)?|unser(?:e)?)?\s*(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim)\s+"
        r"(?:ist|liegt|befindet\s+sich|bleibt)\s+[^,.;!?]{1,80}\s+und\s+"
        r"(?!(?:(?:ich|wir)\s+)?(?:arbeit|studier|lern|schlaf|mach|komm|fahr|geh|zieh|hab|besuch|verbring|treff|reis|pendl|seh|übernacht|uebernacht)\w*\b)"
        r"(?:(?:in|bei)\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß'-]*",
        source,
        re.IGNORECASE,
    )
    if ambiguous_label_match and not re.search(
        rf"(?i)\b{_OTHER_PERSON_NON_SELF_REFERENCE}\s*$",
        source[: ambiguous_label_match.start()],
    ):
        return True
    for match in re.finditer(
        rf"\b(?:ich|wir)\s+(?:wohne|wohnen|lebe|leben)\s+(?:in|bei)\s+"
        rf"(?P<first>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)(?=\s*(?:[,;]|\bund\b))\s*"
        r"(?:[,;]|\bund\b)\s*(?!(?:aber|doch|jedoch|sondern)\b)"
        rf"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"jetzig\w*|derzeitig\w*|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|zuhause|zu\s+hause|daheim|wohnung)\b",
        source,
        re.IGNORECASE,
    ):
        first = _clean_city(match.group("first"))
        second = _clean_city(match.group("second"))
        if (
            first
            and second
            and _city_comparison_key(first) != _city_comparison_key(second)
            and not _has_historical_residence_suffix(source, match.start("second"))
            and not _has_other_person_residence_suffix(source, match.end("second"))
        ):
            return True
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+(?:(?:in|bei)\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+"
        r"(?:arbeite\w*|studier\w*|lern\w*|schlaf\w*|pendl\w*|reis\w*|"
        r"besuch\w*|übernacht\w*|uebernacht\w*|fahr\w*|geh\w*|komm\w*)\s+(?:ich|wir)\b|"
        r"bin\s+(?:ich|wir)\s+(?:beruflich|dienstlich|zum\s+arbeiten|zur\s+arbeit|"
        r"zum\s+studieren|heute|gerade|nur\s+unterwegs)\b|"
        r"mach\w*\s+(?:ich|wir)\s+(?:eine\s+)?ausbildung\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+(?:(?:in|bei)\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:geburtsort|geburtsstadt|heimat|heimatstadt|herkunftsort|herkunftsstadt|"
        r"studienort|universität|universitaet|uni|ausbildungsort|arbeitsstelle|"
        r"dienststelle|schule|arbeitsplatz)\b",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+"
        r"(?:(?:(?:ich|wir)\s+)?(?:wohne|wohnen|lebe|leben)\s+"
        r"(?:zeitweise|vorübergehend|voruebergehend|gelegentlich|derzeit|aktuell|momentan)\s+)?"
        r"(?:bei|mit)\s+(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+(?:in|bei)\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+"
        rf"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+hat\s+"
        r"(?:ihr(?:e|en|em|er)?|sein(?:e|en|em|er)?|deren|den|einen?)\s+"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnadresse|wohnanschrift|meldeadresse|"
        r"meldeanschrift|meldesitz|adresse|anschrift|wohnung|unterkunft)\s+"
        r"(?:in|bei)\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s*[,;]?\s*"
        r"(?:und|aber|doch|jedoch)\s+"
        rf"(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+"
        r"(?:ist|liegt|befindet\s+sich)\s+"
        r"(?:(?:zuhause|zu\s+hause|daheim)\s+)?(?:in|bei)\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}",
        source,
        re.IGNORECASE,
    ):
        return False
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
        rf"(?:(?:ich\s+)?{residence}\s+)?(?:in|bei)\s+",
        source,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+ist\s+"
        r"(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:arbeitsort|arbeitsadresse|geschäftsadresse|geschaeftsadresse|"
        r"dienstadresse|büroadresse|bueroadresse)\b",
        source,
        re.IGNORECASE,
    ):
        return False
    for match in re.finditer(
        rf"(?:^|[.!?;,:]\s*)(?P<first>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        r"(?:ist\s+)?(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnung)\b\s*(?:[,;]|\bund\b)\s*"
        rf"(?P<second>[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}?)\s+"
        r"(?:ist\s+)?(?:mein(?:e)?|unser(?:e)?)\s+"
        r"(?:(?:aktuell\w*|offiziell\w*|privat\w*|gemeldet\w*|amtlich\w*|neu\w*|"
        r"haupt\w*|jetzig\w*|derzeitig\w*|gegenwärtig|gegenwaertig)\s+)?"
        r"(?:wohnort|wohnsitz|wohnstadt|hauptwohnsitz|lebensmittelpunkt|"
        r"zuhause|zu\s+hause|daheim|wohnung)\b",
        source,
        re.IGNORECASE,
    ):
        first_raw = match.group("first")
        second_raw = match.group("second")
        first = _clean_city(match.group("first"))
        second = _clean_city(match.group("second"))
        if (
            first
            and second
            and _city_comparison_key(first) != _city_comparison_key(second)
            and not re.search(
                r"(?i)\b(?:war|waren|ehemalig\w*|ehemals|frueh\w*|früh\w*|"
                r"einstig\w*|vormalig\w*|damalig\w*|alt\w*|vorherig\w*|"
                r"künftig\w*|kuenftig\w*|zukünftig\w*|zukuenftig|geplant\w*|"
                r"beabsichtig\w*|vielleicht|vermutlich|möglicherweise|moeglicherweise|"
                r"eventuell|wahrscheinlich|angeblich|anscheinend|scheinbar)\b",
                f"{first_raw} {second_raw}",
            )
        ):
            return True
    return bool(
        re.search(
            rf"\b{residence}\s+(?:in|bei)\s+[^,.;!?]{{1,80}}\s+und\s+"
            r"(?!nicht\w*\b|(?:ich\s+)?(?:wohne|lebe)\s+nicht\b|"
            r"bin\b|war\w*\b|sein\b|sind\s+(?:beruflich|dienstlich|zum\s+arbeiten)\b|arbeit\w*\b|studier\w*\b|lern\w*\b|zieh\w*\b|"
            r"schlaf\w*\b|mach\w*\b|komm\w*\b|fahr\w*\b|geh\w*\b|"
            r"hab\w*\b|besitz\w*\b|vermiet\w*\b|verkauf\w*\b|verwalt\w*\b|"
            r"renovier\w*\b|sanier\w*\b|nutz\w*\b|teil\w*\b|besuch\w*\b|verbring\w*\b|treff\w*\b|reis\w*\b|"
            r"pend\w*\b|seh\w*\b|übernacht\w*\b|uebernacht\w*\b|"
            r"unser(?:e)?\s+(?:wohnort|wohnsitz|hauptwohnsitz|arbeitsort)\b)[\wÄÖÜäöüß'-]+",
            source,
            re.IGNORECASE,
        )
    )


def _has_unresolved_location_separator(source: str, city_end: int) -> bool:
    tail = source[city_end:]
    if re.match(
        r"(?i)\s*[,;]\s*(?:aber|doch|jedoch)\s+(?:(?:in|bei)\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+"
        r"(?:arbeite\w*|studier\w*|lern\w*|schlaf\w*|pendl\w*|reis\w*|"
        r"besuch\w*|übernacht\w*|uebernacht\w*)\b",
        tail,
    ):
        return False
    if re.match(
        rf"(?i)\s*[,;]\s*(?:aber|doch|jedoch)\s+(?:derzeit|aktuell|momentan|gerade)?\s*"
        r"(?:bei|mit)\s+(?:mein(?:e|en|em|er)?|unser(?:e|en|em|er)?)\s+"
        rf"{_OTHER_PERSON_RESIDENCE_LABEL}\s+(?:in|bei)\s+[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{{1,80}}",
        tail,
    ):
        return False
    if re.match(
        r"(?i)\s*[,;]\s*(?:aber|doch|jedoch)\s+(?:(?:in|bei)\s+)?"
        r"[A-ZÄÖÜ][\wÄÖÜäöüß .'-]{1,80}?\s+bin\s+(?:ich|wir)\s+"
        r"(?:beruflich|dienstlich|zum\s+arbeiten|zur\s+arbeit|zum\s+studieren|"
        r"heute|gerade|nur\s+unterwegs)\b",
        tail,
    ):
        return False
    boundary = re.search(r"[.!?;\n]", tail)
    segment = tail if boundary is None else tail[: boundary.start()]
    return bool(
        re.match(
            r"\s*(?:[,;]\s*(?:aber|doch|jedoch)\s+(?!nicht\b)(?:in|bei)\s+[A-ZÄÖÜ]|"
            r"[,;]\s*sondern\b|/|&)\s*(?!arbeite\b|studiere\b|lerne\b|schlafe\b|"
            r"besuche\b|reise\b|pendle\b|fahre\b|gehe\b|komme\b|"
            r"habe\b|bin\b|mein(?:e)?\b|der\b|die\b|das\b|"
            r"arbeitsort\b|arbeitsadresse\b|arbeitsanschrift\b|geburtsort\b|geburtsstadt\b|"
            r"heimat\b|heimatstadt\b)[A-ZÄÖÜäöüß]",
            segment,
            re.IGNORECASE,
        )
    )


def _has_historical_residence_prefix(source: str, match_start: int) -> bool:
    prefix = source[:match_start]
    if match_start < len(source) and source[match_start] in ",;":
        prefix += source[match_start]
    boundary = re.match(r"(?i)(?:und|sowie|oder|aber|doch|jedoch|sondern)\b", source[match_start:])
    if boundary:
        prefix += " " + boundary.group(0)
    sentence = re.split(r"(?<!\bSt)[.!?;\n]\s*", prefix, flags=re.IGNORECASE)[-1]
    clause = re.split(
        r"(?:[,;]|\b(?:und|sowie|oder|aber|doch|jedoch|sondern)\b)\s*",
        sentence,
        flags=re.IGNORECASE,
    )[-1]
    return bool(
        re.search(
            r"(?i)\b(?:ehemalig\w*|ehemals\b|frueh\w*|früh\w*|einstig\w*|vormalig\w*|damalig\w*|"
            r"alt\w*|vorherig\w*)\s*$",
            clause,
        )
    ) or bool(re.search(r"(?i)\bwar(?:en)?(?:\s+\w+){0,3}\s*$", clause))


def _has_future_residence_prefix(source: str, match_start: int, city_start: int | None = None) -> bool:
    prefix_end = city_start if city_start is not None else match_start
    prefix = source[:prefix_end]
    sentence = re.split(r"(?<!\d)(?<!\bSt)[.!?;\n]\s*", prefix, flags=re.IGNORECASE)[-1]
    match_sentence = re.split(
        r"(?<!\d)(?<!\bSt)[.!?;\n]\s*", source[:match_start], flags=re.IGNORECASE
    )[-1]
    if re.search(
        r"(?i)(?:\bkünft\w*|\bkuenft\w*|\bzukünft\w*|\bzukuenft\w*|\bgeplant\w*|\bplan\w*|\bbeabsichtig\w*|\bvorhab\w*)\s*[,;]?\s*$",
        match_sentence,
    ):
        return True
    clause = re.split(r"[,;]\s*", sentence)[-1]
    if re.search(
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
        r"\b(?:künft\w*|kuenft\w*|zukünft\w*|zukuenft\w*|geplant\w*|plan\w*|beabsichtig\w*|vorhab\w*)\b)",
        clause,
    ):
        return True
    if re.search(
        r"(?i)\b(?:werd(?:e|en|et|est)?|soll(?:e|en|t|te|ten)?|"
        r"möchte|moechte|"
        r"müsste|muesste|könnte|koennte|dürfte|duerfte|würde|wuerde)\b"
        r"[^.!?;\n]*$",
        clause,
    ):
        return True
    return bool(
        re.search(
            r"(?i)\b(?:ich|wir)\s+h(?:abe|aben)\s+vor\b[^.!?;\n]*$",
            sentence,
        )
    )


def _has_uncertain_residence_prefix(source: str, match_start: int) -> bool:
    prefix = source[:match_start]
    sentence = re.split(r"(?<!\bSt)[.!?;\n]\s*", prefix, flags=re.IGNORECASE)[-1]
    if re.search(
        r"(?i)(?:möglich\w*|moeglich\w*|wahrscheinlich\w*|vermutlich\w*|"
        r"potenziell\w*|eventuell\w*)\s*$",
        sentence,
    ):
        return True
    clause = re.split(r"[,;]\s*", sentence)[-1]
    return bool(
        re.search(
            r"(?i)(?:\bvielleicht\b|\bvermutlich\b|\bmöglicherweise\b|\bmoeglicherweise\b|"
            r"\beventuell\b|\bwahrscheinlich\b|\bwohl\b|\bangeblich\b|\banscheinend\b|"
            r"\bscheinbar\b|\bvoraussichtlich\b|\bwomöglich\b|\bwomoeglich\b|"
            r"\bmutmaßlich\b|\bmutmasslich\b|\btheoretisch\b|\bhypothetisch\b|"
            r"\bpotenziell\b|\bpotentiell\b)\s*$",
            clause,
        )
    ) or bool(
        re.search(
            r"(?i)(?:^|[,;]\s*)(?:ich|wir)\s+(?:glaube|denke|vermute)\b[^.!?;\n]*$|"
            r"(?:^|[,;]\s*)ich\s+nehme\s+an\b[^.!?;\n]*$|"
            r"(?:^|[,;]\s*)soweit\s+ich\s+wei(?:ß|ss)\b[^.!?;\n]*$|"
            r"(?:^|[,;]\s*)es\s+scheint\b[^.!?;\n]*$|"
            r"(?:^|[,;]\s*)nach\s+meinem\s+wissen\b[^.!?;\n]*$|"
            r"(?:^|[,;]\s*)nach\s+allem,\s+was\s+ich\s+wei(?:ß|ss)\b[^.!?;\n]*$|"
            r"(?:^|[,;]\s*)(?:ich|wir)?\s*(?:könnte|koennte|soll(?:e|en|t|te|ten)?|"
            r"müsste|muesste|dürfte|duerfte|würde|wuerde)\b[^.!?;\n]*$",
            sentence,
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


def _has_uncertain_residence_suffix(source: str, city_end: int) -> bool:
    tail = source[city_end:]
    sentence = re.split(r"(?<!\bSt)[.!?;]", tail, maxsplit=1, flags=re.IGNORECASE)[0]
    return bool(
        re.match(
            r"(?i)\s*,?\s*(?:glaube|denke|vermute)\s+ich\b|"
            r"\s*,?\s*(?:nehme\s+ich\s+an|soweit\s+ich\s+weiß|soweit\s+ich\s+weiss)\b",
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


def _has_non_residential_city_tail(value: str) -> bool:
    return bool(
        re.search(
            r"(?i)\s+dient\s+als\s+(?:büro|buero|arbeitsplatz|geschäft|geschaeft)\b|"
            r"\s+(?:ist|war|wird)\s+(?:für|fuer)\s+"
            r"(?:(?:meinen|meine|den|die|das)\s+)?(?:urlaub|arbeit)\b|"
            r"\s+(?:ist|war|wird)\s+(?:(?:die|der|das)\s+)?"
            r"(?:(?:meines|meiner|meinem|meinen|unseres|unserer|unserem|unseren)\s+)?"
            r"(?:arbeitgeber\w*|firma\w*|unternehmen\w*|betrieb\w*|organisation\w*|verein\w*)\b|"
            rf"\s+(?:nebenwohnsitzlich|als\s+{_SECONDARY_RESIDENCE_LABEL})\b|"
            rf"\s+\({_SECONDARY_RESIDENCE_LABEL}\)",
            str(value or ""),
        )
    )


def _has_non_residential_city_suffix(source: str, city_end: int) -> bool:
    return bool(
        re.match(
            rf"(?i)\s*\({_SECONDARY_RESIDENCE_LABEL}\)|"
            rf"\s*(?:nebenwohnsitzlich|als\s+{_SECONDARY_RESIDENCE_LABEL})\b",
            source[city_end:],
        )
    )


def _has_transient_location_fragment(source: str, city_start: int, city_end: int) -> bool:
    prefix = source[:city_start]
    sentence = re.split(r"(?<!\bSt)[.!?;\n]\s*", prefix, flags=re.IGNORECASE)[-1]
    clause = re.split(r"[,;]\s*", sentence)[-1]
    if not re.match(
        r"(?i)^\s*(?:(?:aber|doch|jedoch)\s+)?gerade\s+(?:in|bei)\s*$",
        clause,
    ):
        return False
    if re.match(
        r"(?i)\s+(?:wohnhaft|ansässig|ansaessig|gemeldet|registriert|"
        r"zuhause|zu\s+hause|daheim)\b",
        source[city_end:],
    ):
        return False
    return True


def _has_temporary_residence_prefix(source: str, match_start: int) -> bool:
    prefix = source[:match_start]
    sentence = re.split(r"(?<!\bSt)[.!?;\n]\s*", prefix, flags=re.IGNORECASE)[-1]
    return bool(
        re.search(
            r"(?i)(?:\bim|\bin\s+den|\bwährend\s+der|\bwährend\s+meines|\bwaehrend\s+der|"
            r"\bwaehrend\s+meines)\s+(?:urlaub|ferien)\s*$|"
            r"\b(?:während|waehrend)\s+(?:der|des|einer|eines|meines|meiner)\s+"
            r"(?:ferien|urlaubs|reise|dienstreise|aufenthalts)\s*$|"
            r"\b(?:bei|zu)\s+besuch\s*$|"
            r"\b(?:während|waehrend)\s+(?:des|eines|meines)\s+besuchs\s*$|"
            r"\b(?:am\s+wochenende|unter\s+der\s+woche|werktags|wochentags|"
            r"montags?|dienstags?|mittwochs?|donnerstags?|freitags?|samstags?|sonntags?|"
            r"morgens|vormittags|mittags|nachmittags|abends|nachts|tagsüber|tagsueber)\s*$",
            sentence,
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
    if not isinstance(payload, Mapping):
        return str(city or "").strip()
    current_values = payload.get("current_condition")
    area_values = payload.get("nearest_area")
    current = current_values[0] if isinstance(current_values, list) and current_values else {}
    area = area_values[0] if isinstance(area_values, list) and area_values else {}
    if not isinstance(current, Mapping):
        current = {}
    if not isinstance(area, Mapping):
        area = {}
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
    if re.search(
        rf"(?i){_STREET_TYPE}\s+(?:{_STREET_NUMBER_LABEL}\s*)?\d+[a-z]?(?:[/-]\s*\d+[a-z]?|\s+[a-z])?\b",
        source,
    ):
        return ""
    if source.count(")") > source.count("("):
        source = re.sub(r"[.!?;,]+$", "", source).rstrip(")").rstrip()
    normalized_source = re.sub(r"\s+", " ", source).strip(" .,:;!?")
    if re.search(
        r"(?i)\b(?:mag|vielleicht|vermutlich|wahrscheinlich|möglicherweise|moeglicherweise|"
        r"eventuell|wohl|angeblich|anscheinend|scheinbar|voraussichtlich|womöglich|"
        r"womoeglich|mutmaßlich|mutmasslich|theoretisch|hypothetisch|potenziell|potentiell)\b",
        normalized_source,
    ):
        return ""
    normalized_source = re.sub(
        rf"(?i)\s+\({_PRIMARY_RESIDENCE_LABEL}\)$",
        "",
        normalized_source,
    ).strip()
    known_compound_city = _KNOWN_COMPOUND_CITY_NAMES.get(normalized_source.casefold())
    if known_compound_city:
        return known_compound_city
    known_city_district_base = _KNOWN_CITY_DISTRICT_BASES.get(normalized_source.casefold())
    if known_city_district_base:
        return known_city_district_base
    city_area_match = re.fullmatch(
        r"(?i)(?:der\s+)?(?P<adjective>[a-zäöüß-]+)\s+"
        r"(?:umgebung|region|gegend|nähe|naehe)",
        normalized_source,
    )
    if city_area_match:
        known_city_area_base = _CITY_AREA_ADJECTIVE_BASES.get(
            city_area_match.group("adjective").casefold()
        )
        if known_city_area_base:
            return known_city_area_base
    if re.search(r"(?i)\s+(?:oder|sowie|bzw\.?|beziehungsweise)\s+", source):
        return ""
    first_sentence = re.split(r"(?<!\bSt)[.!?;]\s+", source, maxsplit=1, flags=re.IGNORECASE)[0]
    if re.search(
        r"(?i)\b(?:auf\s+besuch|zu\s+besuch|im\s+urlaub|zum\s+urlaub|"
        r"f(?:ür|uer)\s+den\s+urlaub|als\s+(?:tourist|besucher))\b",
        first_sentence,
    ):
        return ""
    city = re.sub(
        r"(?i)^(?:(?:nur|rein|bloß|bloss)\s+)?"
        r"(?:seit\s+(?:gestern|heute|vorgestern)|ab\s+(?:sofort|jetzt)|"
        r"bis\s+auf\s+weiteres|vorübergehend|voruebergehend|zeitweise|temporär|temporaer|"
        r"befristet|unbefristet|dauerhaft|permanent|kurzfristig|langfristig|"
        r"vorläufig|vorlaeufig)\s+(?:in|bei)\s+",
        "",
        source,
    ).strip()
    city = re.sub(r"(?i)^(?:(?:auch|ebenfalls|ebenso|gleichfalls)\s+)?(?:in|bei)\s+", "", city)
    city = re.sub(r"(?i)^(?:auch|ebenfalls|ebenso|gleichfalls)\s+", "", city)
    city = CITY_TRAILING_STOP_RE.sub("", city).strip(" .,:;!?")
    city = re.sub(
        r"(?i)\s+(?:ist|war|wird|liegt|lautet|bleibt|befindet\s+sich)$",
        "",
        city,
    ).strip()
    city = re.sub(r"\s+", " ", city)
    city = re.sub(
        rf"(?i)\s+\({_PRIMARY_RESIDENCE_LABEL}\)$",
        "",
        city,
    ).strip()
    city = re.sub(
        r"(?i)\s+(?:offiziell|polizeilich|privat|dauerhaft|permanent|vorübergehend|vorlaeufig)$",
        "",
        city,
    ).strip()
    city = re.sub(r"(?i)^(?:[A-Z]{1,3}[- ]?)?\d{5}\s+", "", city)
    city = re.sub(r"(?i)\s+(?:[A-Z]{1,3}[- ]?)?\d{5}(?:-\d{4})?$", "", city)
    city = re.sub(
        r"(?i)\s+\((?:deutschland|österreich|oesterreich|schweiz)\)$",
        "",
        city,
    ).strip()
    city = re.split(r"(?<!\bSt)[.!?]\s+", city, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,:;!?")
    city = re.sub(r"(?i)^(?:(?:auch|ebenfalls|ebenso|gleichfalls)\s+)?(?:in|bei)\s+", "", city)
    city = re.sub(r"(?i)^(?:auch|ebenfalls|ebenso|gleichfalls)\s+", "", city)
    city = re.sub(r"(?i)(?<!er)(?:[-\s]+)(?:nähe|umgebung)\b$", "", city).strip()
    city = re.sub(
        rf"(?i)[-\s]+(?:{'|'.join(_CITY_AREA_SUFFIXES)})$",
        "",
        city,
    ).strip()
    if re.fullmatch(rf"(?i)(?:{_LABELED_STREET_ADDRESS_DETAIL}|links|rechts)", city):
        return ""
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
        r"aktuell|derzeit|momentan|gerade|jetzt|nun|inzwischen|mittlerweile|unklar|egal|entweder|"
        r"nimmer|werktags|wochentags|wo|hier|dort|da|sondern|liegt|befindet|"
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
        r"(?i)\b(?:nicht(?:\s+mehr)?|kein(?:e|er|em|en|es)?|mein(?:e|er|em|en|es)?|"
        r"unser(?:e|er|em|en|es)?|ein(?:e|er|em|en|es)?|könnte|koennte|wäre|waere|"
        r"würde|wuerde|soll|sollte|dürfte|duerfte|muss|müsste|muesste)\b",
        city,
    ):
        return ""
    if re.search(r"(?i)\b(?:gewesen|worden|geblieben)\b", city):
        return ""
    if re.search(
        r"(?i)\b(?:arbeit(?:e|en|est|et|ete|eten|end)?|beruflich|dienstlich|"
        r"studier(?:e|en|st|t|te|ten|end)?|lern(?:e|en|st|t|te|ten|end)?|"
        r"schule(?:n)?|schlaf(?:e|en|st|t|te|ten|end)?|"
        r"mach(?:e|en|st|t|te|ten|end)?|komm(?:e|en|st|t|te|ten|end)?|bin|"
        r"fahr(?:e|st|t|te|ten|end)?|geh(?:e|en|st|t|te|ten|end)?|"
        r"hab(?:e|en|st|t|te|ten|end)?|besuch(?:e|en|st|t|te|ten|end|er)?|"
        r"verbring(?:e|en|st|t|te|ten|end)?|treff(?:e|en|st|t|te|ten|end)?|"
        r"reis(?:e|en|t|te|ten|end)?|pend(?:le|eln|elst|elt|elte|elnd)?|"
        r"seh(?:e|en|st|t|te|ten|end)?|übernacht(?:e|en|st|t|te|ten|end)?|"
        r"uebernacht(?:e|en|st|t|te|ten|end)?)\b",
        city,
    ):
        return ""
    return city


def _city_id_token(city: str) -> str:
    normalized = re.sub(r"\s+", "_", city.strip().casefold())
    safe = re.sub(r"[^a-z0-9_]+", "", normalized)
    if any(ord(char) > 127 for char in normalized):
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"{safe[:31]}_{digest}" if safe else digest
    if len(normalized) > 48:
        digest = hashlib.sha256(city.encode("utf-8")).hexdigest()[:16]
        return f"{safe[:31]}_{digest}"
    return safe or hashlib.sha256(city.encode("utf-8")).hexdigest()[:16]


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
