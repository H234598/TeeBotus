from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from TeeBotus.runtime.accounts import AccountStore, AccountStoreError, utc_now
from TeeBotus.runtime.action_buttons import NOTIFICATION_LOUDNESS_BUTTONS
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.activity_profile import contact_timing_decision
from TeeBotus.runtime.events import IncomingEvent
from TeeBotus.runtime.timezone import to_local

NOTIFICATION_LOUDNESS_SYSTEM_ITEM = "notification_loudness"
NOTIFICATION_LOUDNESS_INTENT = "notification_loudness_check"
NOTIFICATION_LOUDNESS_ONLINE_WINDOW = timedelta(minutes=5)
NOTIFICATION_LOUDNESS_WAKE_HOURS = (8, 22)
NOTIFICATION_LOUDNESS_PENDING_STATUS = "pending"
NOTIFICATION_LOUDNESS_TERMINAL_STATUSES = frozenset({"confirmed", "declined"})
NOTIFICATION_LOUDNESS_MUTE_TERMS = frozenset(
    {
        "stumm",
        "lautlos",
        "stummgeschaltet",
        "lautlosgeschaltet",
        "stummschaltung",
        "lautlosmodus",
        "stummmodus",
        "mute",
        "muted",
        "muting",
        "silence",
        "silenced",
        "silencing",
        "silent",
        "quiet",
        "quieter",
        "quietest",
        "soft",
        "softer",
        "softest",
        "softly",
        "quietly",
        "leise",
        "leiser",
        "leiseste",
        "leisesten",
        "inaudible",
        "unhoerbar",
        "hidden",
        "suppressed",
        "unsichtbar",
        "verborgen",
        "unterdrueckt",
    }
)
NOTIFICATION_LOUDNESS_OFF_TERMS = frozenset(
    {
        "aus",
        "ausgeschaltet",
        "ausschalten",
        "auszuschalten",
        "auszumachen",
        "deaktiviert",
        "deaktivieren",
        "abgeschaltet",
        "abschalten",
        "abzuschalten",
        "ausgemacht",
        "inaktiv",
        "inactive",
        "deactivated",
        "off",
        "disabled",
    }
)
NOTIFICATION_LOUDNESS_NEGATION_TERMS = frozenset(
    {
        "nicht",
        "nie",
        "kein",
        "keine",
        "keiner",
        "keinem",
        "keinen",
        "keines",
        "keinerlei",
        "keineswegs",
        "keinesfalls",
        "nichts",
        "nix",
        "weder",
        "ohne",
        "no",
        "none",
        "not",
        "never",
        "nothing",
        "neither",
        "without",
    }
)
NOTIFICATION_LOUDNESS_QUANTIFIER_TERMS = frozenset(
    {
        "kein",
        "keine",
        "keiner",
        "keinem",
        "keinen",
        "keines",
        "keinerlei",
        "nichts",
        "weder",
        "no",
        "none",
        "nothing",
        "neither",
    }
)
NOTIFICATION_LOUDNESS_PARTIAL_QUANTIFIER_PHRASES = (
    "not all",
    "aren t all",
    "isn t all",
    "wasn t all",
    "weren t all",
    "not every",
    "not each",
    "not completely",
    "not fully",
    "not entirely",
    "not quite",
    "almost",
    "nearly",
    "hardly",
    "barely",
    "not all the way",
    "partially",
    "only partly",
    "nicht alle",
    "nicht jede",
    "nicht jeder",
    "nicht jedes",
    "nicht vollständig",
    "nicht vollstaendig",
    "nicht komplett",
    "nicht ganz",
    "teilweise",
    "nur teilweise",
    "nur zum teil",
    "some",
    "einige",
    "manche",
    "mehrere",
    "a few",
    "several",
    "ein paar",
    "most",
    "many",
    "almost all",
    "all but",
    "at least",
    "at most",
    "a majority",
    "die meisten",
    "viele",
    "wenige",
    "fast alle",
    "bis auf",
    "mindestens",
    "höchstens",
)
NOTIFICATION_LOUDNESS_NEGATION_PHRASES = (
    "don t",
    "doesn t",
    "didn t",
    "haven t",
    "hasn t",
    "isn t",
    "aren t",
    "wasn t",
    "weren t",
    "couldn t",
    "wouldn t",
    "shouldn t",
    "can t",
    "cannot",
)
NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES = frozenset({"aber", "jedoch", "sondern", "und", "oder", "but", "however", "or", "and"})
NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN = "<clause>"
NOTIFICATION_LOUDNESS_UNCERTAINTY_PHRASES = (
    "weiss nicht",
    "keine ahnung",
    "nicht sicher",
    "unsicher",
    "unklar",
    "nicht klar",
    "fraglich",
    "zweifelhaft",
    "nicht eindeutig",
    "ungewiss",
    "nicht gewiss",
    "vielleicht",
    "wahrscheinlich",
    "ich glaube",
    "glaube ich",
    "ich denke",
    "denke ich",
    "ich vermute",
    "vermute ich",
    "ich schätze",
    "ich nehme an",
    "ich bezweifle",
    "anscheinend",
    "scheinbar",
    "es scheint",
    "soweit ich weiss",
    "weiss es nicht",
    "weiss nicht genau",
    "nicht genau",
    "kann nicht sagen",
    "ich erinnere mich nicht",
    "ich habe vergessen",
    "vergessen",
    "ich kann nicht bestätigen",
    "ich kann nicht verifizieren",
    "ich kann nicht sicher sein",
    "nicht in der lage zu bestaetigen",
    "nicht in der lage zu verifizieren",
    "nicht absolut sicher",
    "nicht völlig sicher",
    "nicht ueberzeugt",
    "nicht überzeugt",
    "nicht genug informationen",
    "keine möglichkeit zu wissen",
    "keine möglichkeit zu sagen",
    "i don t know",
    "i don t really know",
    "i do not really know",
    "i really don t know",
    "i really do not know",
    "not sure",
    "not really",
    "not definitely",
    "not certainly",
    "not clearly",
    "not obviously",
    "not surely",
    "nicht wirklich",
    "nicht definitiv",
    "uncertain",
    "maybe",
    "may have",
    "might have",
    "could have",
    "possibly",
    "probably",
    "perhaps",
    "it is possible",
    "possible that",
    "it is likely",
    "likely that",
    "it is unlikely",
    "unlikely that",
    "it is necessary",
    "necessary that",
    "not necessary that",
    "not checked",
    "not verified",
    "not confirmed",
    "i have not checked",
    "i haven t checked",
    "i did not check",
    "i didn t check",
    "i have not verified",
    "i haven t verified",
    "i did not verify",
    "i didn t verify",
    "i have not confirmed",
    "i haven t confirmed",
    "i did not confirm",
    "i didn t confirm",
    "es ist möglich",
    "möglicherweise",
    "moeglicherweise",
    "möglich dass",
    "moeglich dass",
    "es ist wahrscheinlich",
    "wahrscheinlich dass",
    "es ist unwahrscheinlich",
    "unwahrscheinlich dass",
    "es ist notwendig",
    "notwendig dass",
    "nicht notwendig dass",
    "nicht geprueft",
    "nicht ueberprueft",
    "nicht bestaetigt",
    "ich habe nicht geprueft",
    "ich habe nicht ueberprueft",
    "ich habe nicht bestaetigt",
    "ungeprueft",
    "presumably",
    "i guess",
    "i suppose",
    "i assume",
    "i suspect",
    "i doubt",
    "apparently",
    "it seems",
    "seems like",
    "as far as i know",
    "i am pretty sure",
    "i m pretty sure",
    "i hope",
    "hopefully",
    "i pray",
    "i wish",
    "hoffentlich",
    "ich hoffe",
    "hoffe ich",
    "i think",
    "i believe",
    "don t think",
    "don t believe",
    "do not know",
    "do not think",
    "do not believe",
    "didn t know",
    "did not know",
    "didn t think",
    "did not think",
    "didn t believe",
    "did not believe",
    "wusste nicht",
    "ich weiss wirklich nicht",
    "ich weiss nicht wirklich",
    "can t tell",
    "cannot tell",
    "no idea",
    "no clue",
    "not certain",
    "someone told me",
    "someone says",
    "they told me",
    "someone said",
    "they said",
    "according to someone",
    "according to the user",
    "reported that",
    "reportedly",
    "allegedly",
    "supposedly",
    "i heard that",
    "heard that",
    "i heard notifications are",
    "i heard notifications were",
    "i heard messages are",
    "i heard messages were",
    "not exactly",
    "unsure",
    "cannot say",
    "can t say",
    "can t remember",
    "cannot remember",
    "don t remember",
    "forgot",
    "can t recall",
    "cannot recall",
    "unclear",
    "not clear",
    "cannot confirm",
    "can t confirm",
    "cannot verify",
    "can t verify",
    "i do not deny that",
    "i don t deny that",
    "i cannot deny that",
    "i can t deny that",
    "ich bestreite nicht dass",
    "ich verneine nicht dass",
    "unable to confirm",
    "unable to verify",
    "unable to tell",
    "unable to know",
    "not able to confirm",
    "not able to verify",
    "not able to tell",
    "don t have enough information",
    "not enough information",
    "no proof",
    "no evidence",
    "not impossible",
    "kein beweis",
    "keine beweise",
    "keine belege",
    "nicht unmoeglich",
    "no way to know",
    "no way to tell",
    "there is no way to tell",
    "cannot be sure",
    "can t be sure",
    "not absolutely sure",
    "not completely sure",
    "not entirely sure",
    "not fully convinced",
    "not convinced",
)
NOTIFICATION_LOUDNESS_HISTORICAL_PHRASES = (
    "used to",
    "formerly",
    "previously",
    "yesterday",
    "earlier",
    "before",
    "last night",
    "last week",
    "i had ",
    "i was ",
    "i were ",
    "ich hatte ",
    "ich war ",
    "früher",
    "vorher",
    "gestern",
    "damals",
    "war ",
    "waren ",
    "hatte ",
    "had ",
    "was ",
    "were ",
)
NOTIFICATION_LOUDNESS_CURRENT_TIME_MARKER_PHRASES = (
    "now",
    "right now",
    "just now",
    "currently",
    "at the moment",
    "today",
    "jetzt",
    "nun",
    "aktuell",
    "gerade",
    "derzeit",
    "momentan",
    "inzwischen",
    "mittlerweile",
    "im moment",
    "zurzeit",
    "gegenwaertig",
    "since then",
    "in the meantime",
    "meanwhile",
    "ever since",
    "from then on",
    "heute",
    "neuerdings",
)
NOTIFICATION_LOUDNESS_NON_ASSERTIVE_STARTS = (
    "if ",
    "when ",
    "assuming ",
    "suppose ",
    "unless ",
    "provided ",
    "in case ",
    "falls ",
    "wenn ",
    "sofern ",
    "angenommen ",
)
NOTIFICATION_LOUDNESS_HABITUAL_MARKERS = (
    "usually",
    "always",
    "normally",
    "generally",
    "typically",
    "regularly",
    "often",
    "sometimes",
    "never",
    "meistens",
    "normalerweise",
    "immer",
    "häufig",
    "oft",
    "manchmal",
    "nie",
    "grundsätzlich",
)
NOTIFICATION_LOUDNESS_NON_DECLARATIVE_STARTS = (
    "stell ",
    "stelle ",
    "mach ",
    "mache ",
    "make ",
    "restore ",
    "bring ",
    "raise ",
    "increase ",
    "repair ",
    "schalte ",
    "aktiviere ",
    "setze ",
    "stell sicher ",
    "stelle sicher ",
    "bitte stell ",
    "bitte stelle ",
    "bitte mach ",
    "bitte schalte ",
    "i want ",
    "i would like ",
    "i d like ",
    "i don t want ",
    "i don t mute ",
    "i do not mute ",
    "i don t keep ",
    "i do not keep ",
    "i don t leave ",
    "i do not leave ",
    "i don t set ",
    "i do not set ",
    "i don t turn ",
    "i do not turn ",
    "i need ",
    "i need to ",
    "i have to ",
    "i can t ",
    "i couldn t ",
    "i won t ",
    "i can mute ",
    "i can keep ",
    "i can set ",
    "i can turn ",
    "i can switch ",
    "i can make ",
    "i can put ",
    "i can restore ",
    "i can bring ",
    "i can raise ",
    "i can increase ",
    "i can repair ",
    "i restore ",
    "i bring ",
    "i raise ",
    "i increase ",
    "i repair ",
    "ich entferne ",
    "ich drehe ",
    "i can enable ",
    "i can activate ",
    "i can disable ",
    "i can leave ",
    "i have decided to ",
    "i have been meaning to ",
    "i am planning to ",
    "i should ",
    "i would ",
    "i may ",
    "i ought ",
    "i am allowed to ",
    "i am supposed to ",
    "i am expected to ",
    "i am likely to ",
    "i am unlikely to ",
    "i am meant to ",
    "i must ",
    "i could ",
    "i might ",
    "i cannot ",
    "i can not ",
    "i shouldn t ",
    "i wouldn t ",
    "i don t need ",
    "i do not need ",
    "i don t have to ",
    "i do not have to ",
    "i have to check ",
    "i should check ",
    "i am checking ",
    "i am trying ",
    "i m trying ",
    "i am about to ",
    "i m about to ",
    "i am working on ",
    "i m working on ",
    "i am in the process of ",
    "i m in the process of ",
    "i am able to ",
    "i m able to ",
    "i tried not to ",
    "i attempted not to ",
    "i was trying not to ",
    "i m trying not to ",
    "i failed not to ",
    "i tried to ",
    "i attempted to ",
    "i intended to ",
    "i planned to ",
    "i wanted to ",
    "i hoped to ",
    "i meant to ",
    "i was trying to ",
    "i was planning to ",
    "i was about to ",
    "i am turning ",
    "i m turning ",
    "i am prevented from ",
    "i am being prevented from ",
    "i was prevented from ",
    "i were prevented from ",
    "i am protected from ",
    "i was protected from ",
    "i am shielded from ",
    "i was shielded from ",
    "i am safe from ",
    "i was safe from ",
    "i am safe to ",
    "i was safe to ",
    "i am immune to ",
    "i was immune to ",
    "i am free from ",
    "i was free from ",
    "i am free to ",
    "i was free to ",
    "i am saved from ",
    "i was saved from ",
    "ich wurde vor der stummschaltung verschont",
    "ich wurde von der stummschaltung verschont",
    "ich blieb von der stummschaltung verschont",
    "ich wurde vor der stummschaltung verschont ",
    "ich wurde von der stummschaltung verschont ",
    "ich blieb von der stummschaltung verschont ",
    "ich wurde daran gehindert ",
    "ich werde daran gehindert ",
    "ich bin daran gehindert ",
    "i am switching ",
    "i m switching ",
    "i am muting ",
    "i m muting ",
    "i am setting ",
    "i m setting ",
    "i am enabling ",
    "i m enabling ",
    "i am activating ",
    "i m activating ",
    "i am disabling ",
    "i m disabling ",
    "i am making ",
    "i m making ",
    "i am putting ",
    "i m putting ",
    "i am taking ",
    "i m taking ",
    "i am removing ",
    "i m removing ",
    "i am keeping ",
    "i m keeping ",
    "i am leaving ",
    "i m leaving ",
    "tell me ",
    "please tell me ",
    "tell us ",
    "please tell us ",
    "let me know ",
    "please let me know ",
    "let us know ",
    "please let us know ",
    "please state ",
    "state whether ",
    "state if ",
    "please answer ",
    "answer whether ",
    "answer if ",
    "we need to know ",
    "need to know ",
    "the question is ",
    "my question is ",
    "the question remains ",
    "i wonder ",
    "what if ",
    "how do i know ",
    "whether ",
    "in theory ",
    "i make ",
    "i put ",
    "i activate ",
    "i disable ",
    "i deactivate ",
    "i turn ",
    "i switch ",
    "i mute ",
    "i set ",
    "i take ",
    "i remove ",
    "i keep ",
    "i leave ",
    "i let ",
    "i will ",
    "i am going to ",
    "i m going to ",
    "i am not going to ",
    "i m not going to ",
    "i plan to ",
    "i am not planning to ",
    "i m not planning to ",
    "i intend to ",
    "i am not intending to ",
    "i m not intending to ",
    "i am not about to ",
    "i m not about to ",
    "i am not trying to ",
    "i m not trying to ",
    "i am not willing to ",
    "i m not willing to ",
    "i refuse to ",
    "i declined to ",
    "i decided not to ",
    "i have decided not to ",
    "i no longer mute ",
    "i no longer keep ",
    "i no longer turn ",
    "i no longer switch ",
    "i no longer set ",
    "i no longer make ",
    "ich will ",
    "ich kann ",
    "ich könnte ",
    "ich koennte ",
    "ich darf ",
    "ich dürfte ",
    "ich duerfte ",
    "ich würde ",
    "ich wuerde ",
    "ich sollte ",
    "ich muss ",
    "ich soll ",
    "ich konnte ",
    "ich versuchte ",
    "ich habe versucht ",
    "ich probierte ",
    "ich habe probiert ",
    "ich habe es versucht ",
    "ich habe beschlossen ",
    "ich kann nachrichten laut ",
    "ich kann die nachrichten laut ",
    "ich kann nachrichten stumm ",
    "ich kann die nachrichten stumm ",
    "ich kann nachrichten nicht stumm ",
    "ich kann die nachrichten nicht stumm ",
    "ich möchte ",
    "ich moechte ",
    "ich werde ",
    "ich plane ",
    "ich habe vor ",
    "bitte sag mir ",
    "bitte sag uns ",
    "sag uns ",
    "bitte teile mir mit ",
    "bitte teile uns mit ",
    "teile mir mit ",
    "teile uns mit ",
    "gib mir bescheid ",
    "bitte gib mir bescheid ",
    "bitte beantworte ",
    "beantworte ",
    "wir muessen wissen ",
    "muessen wissen ",
    "die frage ist ",
    "meine frage ist ",
    "die frage lautet ",
    "ich muss prüfen ",
    "ich muss pruefen ",
    "ich prüfe ",
    "ich pruefe ",
    "ich versuche ",
    "ich bin dabei ",
    "ich bin gerade dabei ",
    "remain ",
    "remains ",
    "remained ",
    "stay ",
    "stays ",
    "stayed ",
    "bleibt ",
    "bleiben ",
    "blieb ",
    "blieben ",
    "become ",
    "becomes ",
    "became ",
    "get ",
    "gets ",
    "got ",
    "come ",
    "comes ",
    "came ",
    "returned ",
    "ich schalte ",
    "ich stelle ",
    "ich mache ",
    "ich aktiviere ",
    "ich setze ",
    "ich halte ",
    "ich lasse ",
    "lass ",
    "lasst ",
    "please turn ",
    "please keep ",
    "please set ",
    "please take ",
    "please remove ",
    "please make ",
    "please confirm ",
    "please verify ",
    "please check ",
    "confirm ",
    "verify ",
    "check ",
    "make sure ",
    "ensure ",
    "don t mute ",
    "do not mute ",
    "don t keep ",
    "do not keep ",
    "don t leave ",
    "do not leave ",
    "nicht stumm lassen",
    "nicht auf lautlos lassen",
    "nicht ausgeschaltet lassen",
    "nicht aus lassen",
    "bitte nicht stumm",
    "can ",
    "could ",
    "will ",
    "would ",
    "do ",
    "does ",
    "have ",
    "has ",
    "can you ",
    "could you ",
    "kann man ",
    "können ",
    "koennen ",
    "turn ",
    "take ",
    "remove ",
    "set ",
    "keep ",
    "kannst du ",
    "koenntest du ",
    "könntest du ",
    "sag mir ",
    "bitte bestaetige ",
    "bitte pruefe ",
    "bitte ueberpruefe ",
    "bestaetige ",
    "pruefe ",
    "ueberpruefe ",
    "weisst du ",
    "weißt du ",
)
NOTIFICATION_LOUDNESS_QUESTION_TAILS = (
    "oder",
    "oder nicht",
    "stimmt",
    "richtig",
    "right",
    "correct",
    "isn t it",
    "aren t they",
)
NOTIFICATION_LOUDNESS_STATUS_LEAD_TERMS = frozenset(
    {
        "laut",
        "loud",
        "auf",
        "an",
        "on",
        "aus",
        "off",
        "stumm",
        "lautlos",
        "stummgeschaltet",
        "lautlosgeschaltet",
        "muted",
        "silenced",
        "silent",
        "ausgeschaltet",
        "deaktiviert",
        "abgeschaltet",
        "disabled",
        "nicht",
        "not",
        "done",
        "completed",
        "finished",
        "erledigt",
        "fertig",
        "abgeschlossen",
        "gemacht",
        "getan",
        "geschafft",
    }
)
NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS = frozenset(
    {
        "jetzt",
        "nun",
        "aktuell",
        "gerade",
        "eben",
        "wieder",
        "heute",
        "now",
        "currently",
        "right",
        "today",
        "recently",
        "newly",
        "again",
        "back",
        "still",
        "noch",
        "weiterhin",
        "dauerhaft",
        "dauernd",
        "permanent",
        "fortwaehrend",
        "kontinuierlich",
        "derzeit",
        "momentan",
        "bislang",
        "bisher",
        "inzwischen",
        "mittlerweile",
        "permanently",
        "persistently",
        "continuously",
        "indefinitely",
        "continually",
        "durably",
        "neuerdings",
        "no",
        "longer",
        "anymore",
        "any",
        "all",
        "alle",
        "mehr",
        "immer",
        "already",
        "bereits",
        "schon",
        "yet",
        "definitely",
        "certainly",
        "clearly",
        "obviously",
        "surely",
        "undoubtedly",
        "demonstrably",
        "undeniably",
        "definitiv",
        "sicher",
        "eindeutig",
        "offensichtlich",
        "zweifellos",
        "bekanntermassen",
        "nachweislich",
        "really",
        "actually",
        "truly",
        "indeed",
        "sufficiently",
        "adequately",
        "ausreichend",
        "tatsaechlich",
        "wirklich",
    }
)
NOTIFICATION_LOUDNESS_NON_ASSERTIVE_OPTIONAL_MODIFIERS = frozenset(
    set(NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS) | {"just"}
)
NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS = frozenset(
    {
        "laut",
        "loud",
        "louder",
        "an",
        "on",
        "aktiv",
        "active",
        "enabled",
        "hoerbar",
        "audible",
        "unmuted",
        "back",
        "visible",
        "sichtbar",
    }
)
NOTIFICATION_LOUDNESS_VOLUME_TERMS = frozenset({"lautstaerke", "volume"})
NOTIFICATION_LOUDNESS_VOLUME_POSITIVE_TERMS = frozenset(
    {"hoch", "high", "voll", "voller", "full", "maximum", "maximal", "up"}
)
NOTIFICATION_LOUDNESS_VOLUME_NEGATIVE_TERMS = frozenset(
    {"niedrig", "low", "leise", "quiet", "minimum", "down", "runter", "herunter"}
)
NOTIFICATION_LOUDNESS_GRADIENT_POSITIVE_PHRASES = (
    "loud enough",
    "laut genug",
    "sufficiently loud",
    "adequately loud",
    "sufficiently audible",
    "adequately audible",
    "audible enough",
    "clear enough",
    "clear enough to hear",
    "not inadequate",
    "not insufficient",
    "nicht unzureichend",
    "ausreichend laut",
    "ausreichend hoerbar",
    "hoerbar genug",
    "gut hoerbar",
    "adequate volume",
    "an adequate volume",
    "at an adequate volume",
    "sufficient volume",
    "volume is adequate",
    "volume is sufficient",
    "is adequate",
    "is sufficient",
    "are adequate",
    "are sufficient",
    "ausreichende lautstaerke",
    "lautstaerke ist ausreichend",
    "lautstaerke ist angemessen",
    "ist ausreichend",
    "ist angemessen",
    "sind ausreichend",
    "sind angemessen",
    "clearly hear notifications",
    "clearly hear messages",
    "clearly hear notification sound",
    "clearly hear message sound",
    "clearly hear the notification sound",
    "clearly hear the message sound",
    "hear notifications clearly",
    "hear messages clearly",
    "hear notification sound clearly",
    "hear message sound clearly",
    "hear the notification sound clearly",
    "hear the message sound clearly",
    "clearly audible",
    "deutlich hoerbar",
    "deutlich hoeren",
    "klar hoeren",
    "gut hoeren",
)
NOTIFICATION_LOUDNESS_GRADIENT_NEGATIVE_PHRASES = (
    "insufficiently loud",
    "insufficiently audible",
    "inadequately loud",
    "inadequately audible",
    "barely audible",
    "hardly audible",
    "faintly audible",
    "unzureichend laut",
    "unzureichend hoerbar",
    "inadequate volume",
    "an inadequate volume",
    "at an inadequate volume",
    "insufficient volume",
    "volume is inadequate",
    "volume is insufficient",
    "is inadequate",
    "is insufficient",
    "are inadequate",
    "are insufficient",
    "not adequate",
    "not sufficient",
    "unzureichende lautstaerke",
    "lautstaerke ist unzureichend",
    "lautstaerke ist zu niedrig",
    "nicht ausreichend",
    "ist unzureichend",
    "ist zu niedrig",
    "sind unzureichend",
    "sind zu niedrig",
    "too quiet",
    "zu leise",
    "barely hear notifications",
    "barely hear messages",
    "barely hear notification sound",
    "barely hear message sound",
    "barely hear the notification sound",
    "barely hear the message sound",
    "hardly hear notifications",
    "hardly hear messages",
    "hardly hear notification sound",
    "hardly hear message sound",
    "hardly hear the notification sound",
    "hardly hear the message sound",
    "kaum hoeren",
    "kaum hoerbar",
    "only faintly hear notifications",
    "only faintly hear messages",
    "too faint to hear",
    "nur schwach hoeren",
    "loud just not enough",
    "loud but not enough",
    "laut nur nicht genug",
    "laut aber nicht genug",
)
NOTIFICATION_LOUDNESS_COMPLETION_PHRASES = (
    "erledigt",
    "gemacht",
    "getan",
    "fertig",
    "done",
    "completed",
    "finished",
    "did it",
    "did that",
    "did so",
    "all set",
    "took care of it",
    "take care of it",
    "taken care of",
    "handled it",
    "sorted it",
    "fixed it",
    "fixed them",
    "wrapped it up",
    "geschafft",
    "abgeschlossen",
    "damit durch",
    "darum gekuemmert",
    "mich darum gekuemmert",
    "eingeschaltet",
    "angeschaltet",
    "aktiviert",
    "laut gestellt",
    "laut geschaltet",
    "lautgeschaltet",
    "entstummt",
    "turned them on",
    "switched them on",
    "enabled them",
    "turned it on",
    "switched it on",
    "enabled it",
    "activated it",
    "unmuted it",
    "made it loud",
    "set it loud",
    "set it to loud",
    "put it on",
    "restored it",
    "restored them",
    "brought it back",
    "brought them back",
    "made it audible",
    "made them audible",
    "made it ring",
    "made them ring",
    "turned the sound back on",
    "brought the sound back",
    "got it working again",
    "got them working again",
    "set it back to loud",
    "repaired it",
    "repaired them",
    "den ton zurueckgebracht",
    "ton zurueckgebracht",
    "zurueckgebracht",
    "repariert",
    "unmuted",
    "made loud",
    "made them loud",
    "turned it up",
    "turned the sound on",
    "switched the sound on",
    "enabled the sound",
    "activated the sound",
    "got the sound back",
    "put the sound on mute",
    "put sound on mute",
    "ton ausgemacht",
    "turned them up",
    "turned the sound up",
    "raised it",
    "raised them",
    "raised the volume",
    "raised the notification volume",
    "increased it",
    "increased them",
    "increased the volume",
    "increased the notification volume",
    "made it louder",
    "made them louder",
    "made the notifications audible again",
    "made notifications audible again",
    "make it louder",
    "make them louder",
    "lautstaerke erhoeht",
    "lauter gemacht",
    "restore it",
    "restore them",
    "bring it back",
    "bring them back",
    "remove the mute",
    "remove mute",
    "set it high",
    "set the volume high",
    "hochgedreht",
    "hochgesetzt",
    "hochgestellt",
    "entfernte die stummschaltung",
    "drehte die lautstaerke hoch",
    "set to loud",
    "set them to loud",
    "gelungen",
)
NOTIFICATION_LOUDNESS_PENDING_DIRECT_COMPLETION_PHRASES = frozenset(
    {
        "i restored the sound",
        "the sound is restored",
        "the sound was restored",
        "i can hear the sound again",
        "i hear the sound now",
        "ich habe den ton wiederhergestellt",
        "ich habe den ton wieder hergestellt",
        "ich habe den ton wieder angemacht",
        "der ton wurde wiederhergestellt",
        "it worked",
        "it worked now",
        "it has worked",
        "everything worked",
        "es funktioniert",
        "es funktioniert jetzt",
        "es hat funktioniert",
        "hat funktioniert",
        "hat geklappt",
        "klappt",
    }
)
NOTIFICATION_LOUDNESS_PENDING_DIRECT_FAILURE_PHRASES = frozenset(
    {
        "i could not restore the sound",
        "i couldn t restore the sound",
        "i could not get notifications working again",
        "i couldn t get notifications working again",
        "ich kann die benachrichtigungen nicht entstummen",
        "ich kann den ton nicht wiederherstellen",
        "ich kann den nachrichtenton nicht wiederherstellen",
        "ich kann den benachrichtigungston nicht wiederherstellen",
        "it failed",
        "everything failed",
        "es hat nicht funktioniert",
        "hat nicht funktioniert",
        "es hat nicht geklappt",
        "hat nicht geklappt",
    }
)
NOTIFICATION_LOUDNESS_PENDING_AUXILIARY_CONFIRMATION_REPLIES = frozenset(
    {
        "yes i have",
        "yes i ve",
        "yep i have",
        "yep i ve",
        "yeah i have",
        "yeah i ve",
        "sure i have",
        "sure i ve",
    }
)
NOTIFICATION_LOUDNESS_PENDING_AUXILIARY_DECLINE_REPLIES = frozenset(
    {
        "no i have not",
        "no i haven t",
        "no i ve not",
        "nope i have not",
        "nope i haven t",
        "nope i ve not",
    }
)
NOTIFICATION_LOUDNESS_COMPLETION_PRONOUN_PHRASES = (
    "did it",
    "did that",
    "did so",
    "done it",
    "completed it",
    "finished it",
    "did not do it",
    "didn t do it",
    "have not done it",
    "haven t done it",
    "never did it",
    "never done it",
    "restored it",
    "restored them",
    "brought it back",
    "brought them back",
    "made it audible",
    "made them audible",
    "made it ring",
    "made them ring",
    "got it working again",
    "got them working again",
    "repaired it",
    "repaired them",
    "fixed them",
    "turned it up",
    "turned the sound on",
    "switched the sound on",
    "enabled the sound",
    "activated the sound",
    "got the sound back",
    "put the sound on mute",
    "put sound on mute",
    "turned them up",
    "turned the sound up",
    "raised it",
    "raised them",
    "raised the volume",
    "increased it",
    "increased them",
        "increased the volume",
        "made it louder",
        "made them louder",
        "made it loud enough",
        "made them loud enough",
        "made it not loud enough",
        "made them not loud enough",
        "made it sufficiently loud",
        "made them sufficiently loud",
        "make it loud enough",
        "make them loud enough",
        "make it sufficiently loud",
        "make them sufficiently loud",
        "set it loud enough",
        "set them loud enough",
        "set it to loud enough",
        "set them to loud enough",
        "made notifications louder",
        "make it louder",
        "make them louder",
        "make notifications louder",
        "turned notifications louder",
        "turn notifications louder",
        "habe es geschafft",
        "habe es nicht geschafft",
        "ist mir gelungen",
        "ist mir nicht gelungen",
        "lauter gestellt",
        "lauter gemacht",
    "restore it",
    "restore them",
    "bring it back",
    "bring them back",
    "remove the mute",
    "remove mute",
    "set it high",
    "set the volume high",
    "hochgedreht",
    "hochgesetzt",
    "hochgestellt",
    "entfernte die stummschaltung",
    "drehte die lautstaerke hoch",
    "den ton zurueckgebracht",
    "ton zurueckgebracht",
    "repariert",
)
NOTIFICATION_LOUDNESS_FAILED_ACTION_PHRASES = (
    "failed to",
    "couldn t manage",
    "could not manage",
    "couldn t make",
    "could not make",
    "was unable to",
    "were unable to",
    "never managed to",
    "have not managed to",
    "haven t managed to",
    "has not managed to",
    "hasn t managed to",
    "did not manage to",
    "didn t manage to",
    "did not make",
    "didn t make",
    "have not succeeded in",
    "haven t succeeded in",
    "has not succeeded in",
    "hasn t succeeded in",
    "never succeeded in",
    "did not succeed",
    "didn t succeed",
    "have not been able to",
    "haven t been able to",
    "has not been able to",
    "hasn t been able to",
    "never been able to",
    "was never able to",
    "were never able to",
    "tried and failed",
    "but failed",
    "did not work",
    "didn t work",
    "did not work out",
    "didn t work out",
    "nicht geklappt",
    "nicht funktioniert",
    "hat nicht geklappt",
    "hat nicht funktioniert",
    "gescheitert",
    "fehlgeschlagen",
    "nicht gelungen",
    "nicht geschafft",
    "nie geschafft",
    "niemals geschafft",
    "bin nicht in der lage",
    "ist nicht in der lage",
    "sind nicht in der lage",
    "war nicht in der lage",
    "waren nicht in der lage",
    "nie in der lage",
    "niemals in der lage",
    "konnte nicht",
    "konnten nicht",
    "was not able to",
    "wasn t able to",
    "were not able to",
    "weren t able to",
    "unable to",
    "not able to",
    "cannot unmute",
    "can not unmute",
    "can t unmute",
    "could not unmute",
    "couldn t unmute",
    "cannot restore notification sound",
    "can not restore notification sound",
    "can t restore notification sound",
    "could not restore notification sound",
    "couldn t restore notification sound",
    "kann benachrichtigungen nicht entstummen",
    "konnte benachrichtigungen nicht entstummen",
    "kann den benachrichtigungston nicht wiederherstellen",
    "konnte den benachrichtigungston nicht wiederherstellen",
)
NOTIFICATION_LOUDNESS_SUCCESSFUL_ABILITY_PHRASES = (
    "was able to",
    "were able to",
    "have been able to",
    "has been able to",
    "was able not to",
    "were able not to",
    "have been able not to",
    "has been able not to",
)
NOTIFICATION_LOUDNESS_EXPLICIT_HISTORICAL_TIME_PHRASES = (
    "used to",
    "formerly",
    "previously",
    "yesterday",
    "earlier",
    "before",
    "last night",
    "last week",
    "früher",
    "vorher",
    "gestern",
    "damals",
)
NOTIFICATION_LOUDNESS_ATTEMPT_ACTION_PHRASES = (
    "tried",
    "attempted",
    "intended",
    "planned",
    "wanted",
    "hoped",
    "meant",
    "versuchte",
    "versucht",
    "wollte",
    "plante",
    "hoffte",
    "meinte",
    "probierte",
    "probiert",
)
NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES = (
    "off mute",
    "off of mute",
    "removed mute",
    "removed the mute",
    "taken off mute",
    "taken off of mute",
    "taken off the mute",
    "took off mute",
    "took off the mute",
    "turned off mute",
    "turned off the mute",
    "turned mute off",
    "turned the mute off",
    "the mute is off",
    "switched mute off",
    "switched off the mute",
    "switched the mute off",
    "turned off silent mode",
    "turned silent mode off",
    "turn off silent mode",
    "switch off silent mode",
    "disable silent mode",
    "deactivate silent mode",
    "switched off silent mode",
    "switched silent mode off",
    "turned off quiet mode",
    "turned quiet mode off",
    "turn off quiet mode",
    "switch off quiet mode",
    "disable quiet mode",
    "deactivate quiet mode",
    "switched off quiet mode",
    "switched quiet mode off",
    "disabled quiet mode",
    "deactivated quiet mode",
    "quiet mode off",
    "quiet mode is off",
    "quiet mode is turned off",
    "quiet mode was turned off",
    "quiet mode has been turned off",
    "quiet mode disabled",
    "quiet mode is disabled",
    "quiet mode deactivated",
    "quiet mode is deactivated",
    "disabled silent mode",
    "deactivated silent mode",
    "silent mode off",
    "silent mode is off",
    "silent mode is turned off",
    "silent mode was turned off",
    "silent mode has been turned off",
    "silent mode disabled",
    "silent mode is disabled",
    "silent mode deactivated",
    "silent mode is deactivated",
    "lautlosmodus deaktiviert",
    "lautlosmodus ist deaktiviert",
    "lautlosmodus wurde deaktiviert",
    "stummmodus deaktiviert",
    "stummmodus ist deaktiviert",
    "stummmodus wurde deaktiviert",
    "lautlosmodus aus",
    "lautlosmodus ist aus",
    "stummmodus aus",
    "stummmodus ist aus",
    "disabled mute",
    "disabled the mute",
    "deactivated mute",
    "deactivated the mute",
    "anything but muted",
    "anything but silent",
    "alles andere als stumm",
    "alles andere als lautlos",
    "frei von stummschaltung",
    "free of mute",
    "free from mute",
    "free from silence",
    "stummschaltung entfernt",
    "entfernte die stummschaltung",
    "stummschaltung aufgehoben",
    "stummschaltung fuer benachrichtigungen aufgehoben",
    "removed the mute from notifications",
    "removed mute from notifications",
    "took notifications off silent",
    "stummschaltung von benachrichtigungen entfernt",
    "benachrichtigungen aus dem stummmodus genommen",
    "stummschaltung deaktiviert",
    "stummschaltung ausgeschaltet",
    "stummschaltung ausgemacht",
    "stummschaltung abgeschaltet",
    "lautlosmodus abgeschaltet",
    "stummmodus abgeschaltet",
    "stummschaltung wurde entfernt",
    "stummschaltung ist entfernt",
    "lautlosmodus ausgeschaltet",
    "lautlosmodus ausgemacht",
    "lautlosmodus fuer nachrichten ausgeschaltet",
    "stummmodus ausgeschaltet",
    "stummmodus ausgemacht",
    "nicht stoeren modus ausgeschaltet",
    "nicht stoeren modus ausgemacht",
    "disabled do not disturb for notifications",
    "turned off do not disturb for notifications",
    "do not disturb is disabled for notifications",
)
NOTIFICATION_LOUDNESS_NEGATED_POSITIVE_MUTE_PHRASES = (
    "mute is not off",
    "mute isn t off",
    "the mute is not off",
    "the mute isn t off",
    "silent mode is not turned off",
    "silent mode was not turned off",
    "silent mode is not disabled",
    "quiet mode is not turned off",
    "quiet mode was not turned off",
    "quiet mode is not disabled",
)
NOTIFICATION_LOUDNESS_ACTION_WORDS = frozenset({"hab", "habe", "haben", "getan", "gemacht", "erledigt", "did", "done"})
NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS = frozenset(
    {"ja", "yes", "jep", "jo", "ok", "okay", "klar", "yep", "yup", "yeah", "yea", "sure"}
)
NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS = frozenset(
    {"nein", "no", "nee", "nop", "nope", "nah", "nö", "noe"}
)
NOTIFICATION_LOUDNESS_PENDING_POSITIVE_STATUS_REPLIES = frozenset(
    {
        "laut",
        "loud",
        "an",
        "on",
        "hoch",
        "high",
        "lauter",
        "louder",
        "hoeher",
        "higher",
        "voll",
        "voller",
        "full",
        "maximum",
        "maximal",
        "volle lautstaerke",
        "hohe lautstaerke",
        "voller lautstaerke",
        "maximale lautstaerke",
        "high volume",
        "full volume",
        "maximum volume",
        "100 prozent",
        "100 percent",
        "100%",
        "nicht stumm",
        "nicht lautlos",
        "nicht aus",
        "not muted",
        "not off",
        "not disabled",
    }
)
NOTIFICATION_LOUDNESS_PENDING_NEGATIVE_STATUS_REPLIES = frozenset(
    {
        "stumm",
        "lautlos",
        "muted",
        "silent",
        "aus",
        "off",
        "disabled",
        "niedrig",
        "low",
        "leise",
        "leiser",
        "quiet",
        "softer",
        "niedriger",
        "lower",
        "minimum",
        "down",
        "runter",
        "herunter",
        "leise lautstaerke",
        "niedrige lautstaerke",
        "minimale lautstaerke",
        "minimum volume",
        "low volume",
        "quiet volume",
        "0 prozent",
        "0 percent",
        "0%",
        "nicht laut",
        "nicht an",
        "not loud",
        "insufficiently loud",
        "insufficiently audible",
        "unzureichend laut",
        "unzureichend hoerbar",
        "not on",
    }
)

NOTIFICATION_LOUDNESS_PROMPT = (
    "Bitte stell meine Nachrichten in diesem Chat auf laut, damit Erinnerungen, Termine und wichtige Hinweise nicht untergehen.\n"
    "Hast du das erledigt? Antworte bitte mit „ja, laut“ oder „nein“."
)
NOTIFICATION_LOUDNESS_CONFIRMED_REPLY = "Danke, ich frage deswegen nicht weiter nach."
NOTIFICATION_LOUDNESS_DECLINED_REPLY = "Okay, ich frage deswegen nicht weiter nach."


def maybe_handle_notification_loudness_response(
    event: IncomingEvent,
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> tuple[SendText, ...] | None:
    if not account_id or not _is_private_chat_type(event.chat_type):
        return None
    try:
        if not _event_belongs_to_account(account_store, event, account_id):
            return None
        if not _event_has_current_private_route(account_store, event):
            return None
        with _account_proactive_outbox_lock(account_store, account_id):
            if not _event_belongs_to_account(account_store, event, account_id):
                return None
            if not _event_has_current_private_route(account_store, event):
                return None
            if not isinstance(account_store.read_agent_state(account_id), dict):
                return None
            route_status = _route_status(account_store, account_id, event)
            if route_status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES or route_status == "<invalid>":
                return None
            state = account_store.read_agent_state(account_id)
            notification_state = state.get("notification_loudness") if isinstance(state, dict) else None
            routes = notification_state.get("routes") if isinstance(notification_state, dict) else None
            route_state = _find_route_state(routes, _route_key(event)) if isinstance(routes, Mapping) else None
            if isinstance(route_state, Mapping) and not _notification_loudness_checks_active(route_state):
                return None
            decision = _notification_loudness_decision(event.text, pending=route_status == "pending")
            if decision is None:
                return None
            _set_notification_loudness_status(account_store, account_id, event, decision, now=now)
            _cancel_pending_notification_loudness_items(account_store, account_id, event)
            text = NOTIFICATION_LOUDNESS_CONFIRMED_REPLY if decision == "confirmed" else NOTIFICATION_LOUDNESS_DECLINED_REPLY
            return (SendText(event.chat_id, text, track=False),)
    except (AccountStoreError, OSError, ValueError):
        return None


def maybe_notification_loudness_prompt_action(
    event: IncomingEvent,
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> SendText | None:
    if not _is_private_chat_type(event.chat_type) or not account_id:
        return None
    try:
        if not _event_belongs_to_account(account_store, event, account_id):
            return None
        if not _event_has_current_private_route(account_store, event):
            return None
        with _account_proactive_outbox_lock(account_store, account_id):
            if not _event_belongs_to_account(account_store, event, account_id):
                return None
            if not _event_has_current_private_route(account_store, event):
                return None
            state = account_store.read_agent_state(account_id)
            if not isinstance(state, dict):
                return None
            route_state = _ensure_route_state(state, event)
            normalized_status = _normalized_route_status(route_state)
            if normalized_status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES or normalized_status == "<invalid>":
                return None
            if not _notification_loudness_checks_active(route_state):
                return None
            resolved_now = _resolve_loudness_now(now)
            if not _notification_loudness_prompt_allowed(route_state, resolved_now, require_online=False):
                account_store.write_agent_state(account_id, state)
                return None
            _mark_notification_loudness_prompted(route_state, event, resolved_now)
            account_store.write_agent_state(account_id, state)
            return SendText(event.chat_id, NOTIFICATION_LOUDNESS_PROMPT, track=False, buttons=NOTIFICATION_LOUDNESS_BUTTONS)
    except (AccountStoreError, OSError, ValueError):
        return None


def queue_due_notification_loudness_prompts(
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    try:
        with _account_proactive_outbox_lock(account_store, account_id):
            return _queue_due_notification_loudness_prompts_unlocked(account_store, account_id, now=now)
    except (AccountStoreError, OSError, ValueError):
        return ()


def _queue_due_notification_loudness_prompts_unlocked(
    account_store: AccountStore,
    account_id: str,
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    state = account_store.read_agent_state(account_id)
    if not isinstance(state, dict):
        return ()
    state.setdefault("schema_version", 1)
    notification_state = state.get("notification_loudness")
    if not isinstance(notification_state, dict):
        return ()
    routes = notification_state.get("routes")
    if not isinstance(routes, dict):
        return ()
    resolved_now = _resolve_loudness_now(now)
    queued_ids: list[str] = []
    state_changed = False
    terminal_route_keys = {
        _normalize_route_key(route_key)
        for route_key, route_state in routes.items()
        if isinstance(route_state, dict) and _normalized_route_status(route_state) in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES
    }
    for route_key, route_state in list(routes.items()):
        if not isinstance(route_state, dict):
            continue
        status = str(route_state.get("status") or "unknown").strip().casefold()
        if status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES:
            state_changed = _mark_notification_loudness_checks_stopped(route_state, status) or state_changed
            continue
        if _normalize_route_key(route_key) in terminal_route_keys:
            continue
        if status != NOTIFICATION_LOUDNESS_PENDING_STATUS:
            continue
        if not _notification_loudness_checks_active(route_state):
            continue
        route_state_changed, current_route_found = _refresh_route_state_from_account_routes(
            account_store, account_id, str(route_key), route_state
        )
        state_changed = route_state_changed or state_changed
        if not current_route_found:
            continue
        route = route_state.get("route")
        if not _private_route(route):
            continue
        if not _notification_loudness_prompt_allowed(route_state, resolved_now, require_online=True):
            continue
        if isinstance(route, Mapping):
            adaptive_decision = contact_timing_decision(account_store, account_id, now=resolved_now, route=route)
            if not adaptive_decision.allowed:
                continue
        if _has_queued_notification_loudness_item(account_store, account_id, route_key):
            continue
        if _has_notification_loudness_item_in_wake_window(account_store, account_id, route_key, resolved_now):
            continue
        _mark_route_state_prompted(route_state, resolved_now)
        queued_ids.append(
            account_store.append_proactive_outbox_item(
                account_id,
                {
                    "status": "queued",
                    "category": "system",
                    "intent": NOTIFICATION_LOUDNESS_INTENT,
                    "message_text": NOTIFICATION_LOUDNESS_PROMPT,
                    "reason_memory_ids": [],
                    "due_at": resolved_now.isoformat(timespec="seconds"),
                    "risk_gate": "none",
                    "planner": {"source": "system", "system_item": NOTIFICATION_LOUDNESS_SYSTEM_ITEM},
                    "policy_result": "allowed",
                    "policy_reason": "system_notification_loudness_prompt",
                    "route": dict(route),
                    "system_item": NOTIFICATION_LOUDNESS_SYSTEM_ITEM,
                    "route_key": str(route_key),
                    "status_history": [{"at": utc_now(), "status": "queued", "reason": "created"}],
                },
            )
        )
    if queued_ids or state_changed:
        account_store.write_agent_state(account_id, state)
    return tuple(queued_ids)


def is_notification_loudness_outbox_item(item: Mapping[str, Any] | None) -> bool:
    if not isinstance(item, Mapping):
        return False
    if str(item.get("system_item") or "").strip().casefold() == NOTIFICATION_LOUDNESS_SYSTEM_ITEM:
        return True
    planner = item.get("planner")
    return isinstance(planner, Mapping) and str(planner.get("system_item") or "").strip().casefold() == NOTIFICATION_LOUDNESS_SYSTEM_ITEM


def notification_loudness_outbox_item_is_active(account_store: AccountStore, account_id: str, item: Mapping[str, Any]) -> bool:
    """Return whether a queued loudness prompt still belongs to an open check."""
    with _account_proactive_outbox_lock(account_store, account_id):
        return _notification_loudness_outbox_item_is_active_unlocked(account_store, account_id, item)


def _notification_loudness_outbox_item_is_active_unlocked(
    account_store: AccountStore, account_id: str, item: Mapping[str, Any]
) -> bool:
    item_status = _notification_loudness_outbox_status(item)
    if item_status not in {"queued", "dispatching"}:
        return False
    if not _outbox_route_is_consistent(item):
        return False
    route_key = _outbox_route_key(item)
    if not route_key:
        return False
    state = account_store.read_agent_state(account_id)
    notification_state = state.get("notification_loudness") if isinstance(state, dict) else None
    routes = notification_state.get("routes") if isinstance(notification_state, dict) else None
    if not isinstance(routes, dict):
        return False
    route_state = _find_route_state(routes, route_key)
    if not isinstance(route_state, dict):
        return False
    if _normalized_route_status(route_state) != NOTIFICATION_LOUDNESS_PENDING_STATUS:
        return False
    if not _notification_loudness_checks_active(route_state):
        return False
    _, current_route_found = _refresh_route_state_from_account_routes(account_store, account_id, route_key, route_state)
    return current_route_found


def _notification_loudness_decision(text: str, *, pending: bool) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None
    normalized = _notification_loudness_canonicalize_epistemic_forms(
        _notification_loudness_canonicalize_double_temporal_negation(normalized)
    )
    if (
        pending
        and "?" not in str(text or "")
        and normalized in NOTIFICATION_LOUDNESS_PENDING_DIRECT_COMPLETION_PHRASES
    ):
        return "confirmed"
    if (
        pending
        and "?" not in str(text or "")
        and normalized in NOTIFICATION_LOUDNESS_PENDING_DIRECT_FAILURE_PHRASES
    ):
        return "declined"
    if pending and "?" not in str(text or ""):
        if normalized in NOTIFICATION_LOUDNESS_PENDING_AUXILIARY_CONFIRMATION_REPLIES:
            return "confirmed"
        if normalized in NOTIFICATION_LOUDNESS_PENDING_AUXILIARY_DECLINE_REPLIES:
            return "declined"
    if _notification_loudness_has_unrelated_identity_description(normalized):
        return None
    if _notification_loudness_has_negative_possession_description(normalized):
        return None
    if _notification_loudness_has_negative_german_existential_description(normalized):
        return None
    if _notification_loudness_has_ambiguous_comparative_negation(normalized):
        return None
    proposition_negation_decision = _notification_loudness_explicit_negated_status_decision(
        normalized, pending=pending
    )
    if proposition_negation_decision is not None:
        return proposition_negation_decision
    reply_prefix = _notification_loudness_leading_reply_prefix(text)
    if reply_prefix is not None:
        prefix_decision, remainder = reply_prefix
        if remainder and _notification_loudness_has_reply_status_context(remainder):
            remainder_decision = _notification_loudness_decision(remainder, pending=pending)
            if remainder_decision is not None:
                if remainder_decision == prefix_decision:
                    return prefix_decision
                return None
    if pending and "?" not in str(text or ""):
        direct_pronoun_decision = None
        if not _notification_loudness_has_uncertainty(normalized):
            candidate_texts = [normalized]
            tokens = normalized.split()
            if tokens and tokens[0] in NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS | NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS:
                candidate_texts.append(" ".join(tokens[1:]))
            for candidate in candidate_texts:
                direct_pronoun_decision = _notification_loudness_pending_pronoun_decision(candidate)
                candidate_tokens = candidate.split()
                if direct_pronoun_decision is None and len(candidate_tokens) >= 2 and candidate_tokens[0] in {"sie", "die", "das", "er", "they", "it"}:
                    if candidate_tokens[1] in {"ist", "sind", "is", "are", "re"}:
                        if (
                            _notification_loudness_has_ambiguous_status_qualifier(candidate)
                            or _notification_loudness_has_ambiguous_location_status(candidate)
                        ):
                            continue
                        if _notification_loudness_has_non_assertive_status(candidate):
                            continue
                        if _notification_loudness_has_positive_current_status(candidate):
                            direct_pronoun_decision = "confirmed"
                        elif _notification_loudness_has_negative_current_status(candidate):
                            direct_pronoun_decision = "declined"
                if direct_pronoun_decision is not None:
                    break
        if direct_pronoun_decision is not None:
            return direct_pronoun_decision
    if pending and normalized in NOTIFICATION_LOUDNESS_PENDING_POSITIVE_STATUS_REPLIES:
        return "confirmed"
    if pending and normalized in NOTIFICATION_LOUDNESS_PENDING_NEGATIVE_STATUS_REPLIES:
        return "declined"
    if pending:
        modified_reply_decision = _notification_loudness_pending_modified_reply_decision(normalized)
        if modified_reply_decision is not None:
            return modified_reply_decision
        negated_volume_reply_decision = _notification_loudness_pending_negated_volume_reply_decision(normalized)
        if negated_volume_reply_decision is not None:
            return negated_volume_reply_decision
    words = set(normalized.split())
    explicit_context_needles = (
        "benachrichtigung",
        "benachrichtigungen",
        "benachrichtigungston",
        "benachrichtigungsbox",
        "nachricht",
        "nachrichten",
        "nachrichtenton",
        "notification",
        "notifications",
        "message",
        "messages",
        "nachrichtenlautstaerke",
        "benachrichtigungslautstaerke",
        "message volume",
        "notification volume",
        "chat",
        "conversation",
        "thread",
        "push",
        "alert",
        "alerts",
        "mute",
        "silent mode",
        "quiet mode",
        "lautlosmodus",
        "stummmodus",
        "sound is back",
        "the sound is back",
        "sound has returned",
        "the sound has returned",
        "sound is audible again",
        "the sound is audible again",
        "sound returned",
        "the sound returned",
        "sound came back",
        "the sound came back",
        "sound has come back",
        "the sound has come back",
        "the sound was restored",
        "the notification sound was restored",
        "the sound was brought back",
        "the notification sound was brought back",
        "notification sound is restored",
        "the notification sound is restored",
        "the mute is off",
        "der ton ist wieder da",
        "der nachrichtenton wurde wiederhergestellt",
        "der benachrichtigungston ist wieder da",
        "benachrichtigungston wiederhergestellt",
        "i can hear the notification sound again",
        "can hear the notification sound again",
        "i hear the notification sound now",
        "hear the notification sound now",
        "ich kann die benachrichtigungen wieder hoeren",
        "ich kann den benachrichtigungston wieder hoeren",
        "sound was restored",
        "notification sound was restored",
        "sound was brought back",
        "notification sound was brought back",
        "sound was lost",
        "notification sound was lost",
        "der ton kam zurueck",
        "der nachrichtenton kam zurueck",
        "der ton ist zurueckgekehrt",
        "der nachrichtenton ist zurueckgekehrt",
        "sound is gone",
        "the sound is gone",
    )
    has_explicit_notification_context = any(
        _contains_normalized_phrase(normalized, needle) for needle in explicit_context_needles
    )
    has_volume_context = any(
        _contains_normalized_phrase(normalized, needle)
        for needle in ("nachrichtenlautstaerke", "benachrichtigungslautstaerke", "message volume", "notification volume")
    ) or (
        has_explicit_notification_context
        and any(_contains_normalized_phrase(normalized, term) for term in NOTIFICATION_LOUDNESS_VOLUME_TERMS)
    )
    has_notification_context = has_explicit_notification_context or any(
        _contains_normalized_phrase(normalized, needle)
        for needle in (
            "laut",
            "loud",
            *NOTIFICATION_LOUDNESS_MUTE_TERMS,
            *NOTIFICATION_LOUDNESS_OFF_TERMS,
        )
    )
    has_notification_context = has_notification_context or has_volume_context
    polarity_normalized = _notification_loudness_canonicalize_double_temporal_negation(
        _normalize_text_for_polarity(text)
    )
    polarity_normalized = _notification_loudness_canonicalize_epistemic_forms(polarity_normalized)
    has_explicit_confirmation = _notification_loudness_has_explicit_confirmation(normalized)
    has_sequenced_action_status = _notification_loudness_has_sequenced_action_status(polarity_normalized)
    has_notification_context = has_notification_context or has_explicit_confirmation or has_sequenced_action_status
    leading_copula_status_tokens = normalized.split()[1:]
    while (
        leading_copula_status_tokens
        and leading_copula_status_tokens[0] in NOTIFICATION_LOUDNESS_NON_ASSERTIVE_OPTIONAL_MODIFIERS
    ):
        leading_copula_status_tokens = leading_copula_status_tokens[1:]
    if leading_copula_status_tokens and leading_copula_status_tokens[0] in {"not", "nicht"}:
        leading_copula_status_tokens = leading_copula_status_tokens[1:]
    if (
        not pending
        and normalized.startswith(("ist ", "sind ", "is ", "are "))
        and len(leading_copula_status_tokens) <= 1
        and not has_explicit_notification_context
        and not has_explicit_confirmation
        and not has_sequenced_action_status
    ):
        # A leading copula without a subject cannot establish a global status
        # when no pending route supplies the omitted notification context.
        return None
    has_attributive_positive, has_attributive_negative = (
        _notification_loudness_attributive_quantifier_polarity(normalized)
    )
    if _notification_loudness_has_verification_question(normalized):
        return None
    has_completed_action_positive, has_completed_action_negative = _notification_loudness_completed_action_polarity(
        polarity_normalized, has_notification_context=has_notification_context
    )
    has_unnegated_mute, has_negated_mute = _notification_loudness_mute_polarity(polarity_normalized)
    has_unnegated_german_still, has_negated_german_still = _notification_loudness_german_still_polarity(
        polarity_normalized
    )
    has_unnegated_mute = has_unnegated_mute or has_unnegated_german_still
    has_negated_mute = has_negated_mute or has_negated_german_still
    has_unnegated_off, has_negated_off = _notification_loudness_term_polarity(
        polarity_normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
    )
    historical_causal_prefix = _notification_loudness_historical_causal_prefix(polarity_normalized)
    if historical_causal_prefix:
        has_unnegated_mute, has_negated_mute = _notification_loudness_mute_polarity(
            historical_causal_prefix
        )
        has_unnegated_german_still, has_negated_german_still = _notification_loudness_german_still_polarity(
            historical_causal_prefix
        )
        has_unnegated_mute = has_unnegated_mute or has_unnegated_german_still
        has_negated_mute = has_negated_mute or has_negated_german_still
        has_unnegated_off, has_negated_off = _notification_loudness_term_polarity(
            historical_causal_prefix, NOTIFICATION_LOUDNESS_OFF_TERMS
        )
    has_negated_completion = _notification_loudness_has_negated_phrase(
        polarity_normalized, NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
    )
    has_completion_phrase = any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
    )
    has_pending_pronoun_completion = pending and any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "set it loud",
            "set it to loud",
            "put it on",
            "made it audible",
            "made them audible",
            "set it high",
            "set the volume high",
            "put the sound on mute",
            "put sound on mute",
            "re-enabled notifications",
            "reactivated notifications",
            "made notifications audible",
            "made notifications louder",
            "turned notifications louder",
            "got notifications working again",
            "got the notification sound working again",
            "restored notification sound",
        )
    )
    allow_completion_pronoun = pending and any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_COMPLETION_PRONOUN_PHRASES
    )
    has_indirect_positive_mute_action = _notification_loudness_has_indirect_positive_mute_action(normalized)
    has_positive_unmute_phrase = _notification_loudness_has_unnegated_phrase(
        normalized, NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES
    ) or has_indirect_positive_mute_action
    has_negated_positive_unmute_phrase = _notification_loudness_has_negated_phrase(
        polarity_normalized, NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES
    ) or any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_NEGATED_POSITIVE_MUTE_PHRASES
    )
    has_failed_action = _notification_loudness_has_failed_action(normalized)
    has_negated_failure_action = _notification_loudness_has_negated_failure_action(normalized)
    has_successful_ability_action = _notification_loudness_has_successful_ability_action(normalized)
    has_notification_context = has_notification_context or has_positive_unmute_phrase
    has_audibility_gradient = _notification_loudness_has_audibility_gradient(normalized)
    has_direct_audibility_experience = _notification_loudness_has_direct_audibility_experience(normalized)
    has_progressive_status_transition = _notification_loudness_has_progressive_status_transition(normalized)
    has_pending_quantified_gradient = pending and has_audibility_gradient and any(
        normalized.startswith(f"{prefix} ")
        for prefix in ("none", "no", "neither", "keine", "keinerlei", "weder")
    )
    if _notification_loudness_has_uncertainty(normalized) and (has_notification_context or pending):
        return None
    if has_notification_context and _notification_loudness_has_conditional_status(normalized):
        return None
    if (
        (has_notification_context or (pending and has_completion_phrase))
        and not has_explicit_confirmation
        and not (has_audibility_gradient and has_direct_audibility_experience)
        and not has_failed_action
        and _notification_loudness_has_non_assertive_status(normalized)
    ):
        return None
    if (
        (has_notification_context or (pending and has_completion_phrase))
        and not has_audibility_gradient
        and _notification_loudness_has_partial_quantifier(normalized)
        and not _notification_loudness_has_later_current_status_clause(
            _notification_loudness_canonicalize_double_temporal_negation(
                _normalize_text_for_polarity(text)
            )
        )
    ):
        return None
    polarity_text = _notification_loudness_canonicalize_double_temporal_negation(
        _normalize_text_for_polarity(text)
    )
    polarity_text = _notification_loudness_canonicalize_epistemic_forms(polarity_text)
    transition_segment = _notification_loudness_current_transition_segment(polarity_text)
    intent_segment = _notification_loudness_current_intent_segment(polarity_text)
    temporal_segment = (
        _notification_loudness_current_temporal_segment(polarity_text)
        or transition_segment
        or intent_segment
    )
    later_current_status_segment = _notification_loudness_later_current_status_segment(
        polarity_normalized,
        allow_completion_pronoun=allow_completion_pronoun,
    )
    later_current_status_prefix = _notification_loudness_prior_clause_before_later_status(
        polarity_normalized, later_current_status_segment
    )
    has_completion_pronoun_prefix = pending and later_current_status_prefix is not None and any(
        _contains_normalized_phrase(later_current_status_prefix, phrase)
        for phrase in NOTIFICATION_LOUDNESS_COMPLETION_PRONOUN_PHRASES
    )
    if (
        (has_notification_context or (pending and has_completion_phrase and not has_negated_completion))
        and _notification_loudness_has_historical_marker(historical_causal_prefix or normalized)
        and not (
            _notification_loudness_has_recent_completion_marker(normalized)
            or temporal_segment
            or has_failed_action
            or has_negated_failure_action
            or (
                has_successful_ability_action
                and not _notification_loudness_has_explicit_historical_time(normalized)
            )
            or (
                has_indirect_positive_mute_action
                and not _notification_loudness_has_explicit_historical_time(normalized)
            )
            or (
                (has_completed_action_positive or has_completed_action_negative)
                and not _notification_loudness_has_explicit_historical_time(normalized)
                and not _notification_loudness_has_past_perfect_marker(normalized)
            )
            or has_sequenced_action_status
        )
    ):
        return None
    if temporal_segment:
        normalized = temporal_segment
        polarity_normalized = normalized
        has_unnegated_mute, has_negated_mute = _notification_loudness_mute_polarity(polarity_normalized)
        has_unnegated_german_still, has_negated_german_still = _notification_loudness_german_still_polarity(
            polarity_normalized
        )
        has_unnegated_mute = has_unnegated_mute or has_unnegated_german_still
        has_negated_mute = has_negated_mute or has_negated_german_still
        has_unnegated_off, has_negated_off = _notification_loudness_term_polarity(
            polarity_normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
        )
        has_negated_completion = _notification_loudness_has_negated_phrase(
            polarity_normalized, NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
        )
        has_indirect_positive_mute_action = (
            has_indirect_positive_mute_action
            or _notification_loudness_has_indirect_positive_mute_action(normalized)
        )
        has_positive_unmute_phrase = _notification_loudness_has_unnegated_phrase(
            normalized, NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES
        ) or has_indirect_positive_mute_action
        has_notification_context = has_notification_context or has_positive_unmute_phrase
        has_completed_action_positive, has_completed_action_negative = _notification_loudness_completed_action_polarity(
            polarity_normalized, has_notification_context=has_notification_context
        )
        has_failed_action = _notification_loudness_has_failed_action(normalized)
        has_negated_failure_action = _notification_loudness_has_negated_failure_action(normalized)
        has_attributive_positive, has_attributive_negative = (
            _notification_loudness_attributive_quantifier_polarity(normalized)
        )
        if later_current_status_segment is None:
            later_current_status_segment = _notification_loudness_later_current_status_segment(
                polarity_normalized,
                allow_completion_pronoun=allow_completion_pronoun,
            )
        if later_current_status_prefix is None:
            later_current_status_prefix = _notification_loudness_prior_clause_before_later_status(
                polarity_normalized, later_current_status_segment
            )
    if has_progressive_status_transition and later_current_status_segment is None:
        return None
    if later_current_status_segment:
        has_completed_action_positive = False
        has_completed_action_negative = False
    if has_negated_failure_action:
        has_completed_action_positive = True
        has_completed_action_negative = False
    if (
        has_notification_context
        and _notification_loudness_has_failed_action(normalized)
        and not later_current_status_segment
    ):
        if (
            not has_explicit_notification_context
            and _notification_loudness_has_ambiguous_status_qualifier(normalized)
        ):
            return None
        failed_action_polarity = _notification_loudness_failed_action_polarity(normalized)
        if failed_action_polarity == "negative":
            return None
        return "declined"
    if (
        has_notification_context
        and _notification_loudness_has_habitual_marker(normalized)
        and not (has_completed_action_positive or has_completed_action_negative)
        and not has_completion_pronoun_prefix
    ):
        return None
    if has_notification_context and normalized.startswith(NOTIFICATION_LOUDNESS_NON_ASSERTIVE_STARTS):
        return None
    if has_notification_context and _notification_loudness_has_question_tail(normalized):
        return None
    if has_notification_context and "?" in str(text or ""):
        return None
    if has_notification_context and _notification_loudness_has_ambiguous_alternative(normalized):
        return None
    if has_notification_context and _notification_loudness_has_ambiguous_status_qualifier(normalized):
        return None
    if has_notification_context and _notification_loudness_has_ambiguous_location_status(normalized):
        return None
    if has_notification_context and _notification_loudness_has_ambiguous_chat_activity(normalized):
        return None
    if (
        has_notification_context
        and not has_explicit_notification_context
        and _notification_loudness_has_unscoped_subject_status(normalized)
        and not _notification_loudness_has_sequenced_action_status(polarity_normalized)
        and not has_explicit_confirmation
        and not allow_completion_pronoun
        and not has_positive_unmute_phrase
        and not has_pending_quantified_gradient
    ):
        return None
    has_audibility_state = _notification_loudness_has_audibility_state(normalized)
    if (
        has_notification_context
        and _notification_loudness_is_non_declarative(text, normalized)
        and not has_pending_pronoun_completion
        and not (
            has_audibility_state
            or (has_audibility_gradient and has_direct_audibility_experience)
            or has_explicit_confirmation
            or _notification_loudness_has_sequenced_action_status(polarity_normalized)
            or transition_segment
            or intent_segment
        )
    ):
        return None
    has_volume_positive, has_volume_negative = _notification_loudness_volume_polarity(
        normalized, has_volume_context=has_volume_context
    )
    if has_volume_positive and has_volume_negative:
        return None
    if has_completed_action_positive and has_completed_action_negative and not has_negated_positive_unmute_phrase:
        return None
    if has_attributive_positive and has_attributive_negative:
        return None
    has_positive_current_status = _notification_loudness_has_positive_current_status(normalized)
    has_negative_current_status = _notification_loudness_has_negative_current_status(polarity_normalized)
    has_absolute_negative_positive_status = _notification_loudness_has_absolute_negative_positive_status(normalized)
    has_absolute_negative_mute = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_MUTE_TERMS
    )
    has_absolute_negative_off = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
    )
    has_absolute_negative_positive_inner_negation = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS, inner_negated=True
    )
    has_absolute_negative_mute_inner_negation = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_MUTE_TERMS, inner_negated=True
    )
    has_absolute_negative_still = _notification_loudness_has_absolute_negative_german_still(normalized)
    has_absolute_negative_still_inner_negation = _notification_loudness_has_absolute_negative_german_still(
        normalized, inner_negated=True
    )
    has_absolute_negative_off_inner_negation = _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_OFF_TERMS, inner_negated=True
    )
    if has_notification_context and _notification_loudness_has_contradictory_state(
        polarity_normalized
    ) and not _notification_loudness_has_sequenced_action_status(
        polarity_normalized, activation_only=True
    ) and not (
        has_indirect_positive_mute_action and has_sequenced_action_status
    ) and not has_progressive_status_transition and not (
        later_current_status_segment
        and later_current_status_prefix is not None
        and (
            not _notification_loudness_is_explicit_status_segment(later_current_status_prefix)
            or _notification_loudness_has_set_partial_quantifier(later_current_status_prefix)
        )
    ) and not (
        has_positive_current_status
        and not has_negative_current_status
        and not has_unnegated_mute
        and not has_unnegated_off
    ):
        return None
    if has_notification_context and _notification_loudness_has_cross_subject_conflict(
        polarity_normalized,
        has_unnegated_mute=has_unnegated_mute,
        has_negated_mute=has_negated_mute,
        has_unnegated_off=has_unnegated_off,
        has_negated_off=has_negated_off,
        has_positive_unmute_phrase=has_positive_unmute_phrase,
        has_positive_current_status=has_positive_current_status,
        has_negative_current_status=has_negative_current_status,
    ):
        return None
    if has_notification_context and _notification_loudness_has_cross_subject_gradient_conflict(
        polarity_normalized
    ):
        return None
    if later_current_status_segment:
        scoped_normalized = later_current_status_segment
        has_unnegated_mute, has_negated_mute = _notification_loudness_mute_polarity(
            scoped_normalized
        )
        has_unnegated_german_still, has_negated_german_still = _notification_loudness_german_still_polarity(
            scoped_normalized
        )
        has_unnegated_mute = has_unnegated_mute or has_unnegated_german_still
        has_negated_mute = has_negated_mute or has_negated_german_still
        has_unnegated_off, has_negated_off = _notification_loudness_term_polarity(
            scoped_normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
        )
        has_positive_unmute_phrase = _notification_loudness_has_unnegated_phrase(
            scoped_normalized, NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES
        ) or _notification_loudness_has_indirect_positive_mute_action(scoped_normalized)
        has_positive_current_status = _notification_loudness_has_positive_current_status(
            scoped_normalized
        )
        has_negative_current_status = _notification_loudness_has_negative_current_status(
            scoped_normalized
        )
        has_absolute_negative_positive_status = _notification_loudness_has_absolute_negative_positive_status(
            scoped_normalized
        )
        has_absolute_negative_mute = _notification_loudness_has_absolute_negative_term(
            scoped_normalized, NOTIFICATION_LOUDNESS_MUTE_TERMS
        )
        has_absolute_negative_off = _notification_loudness_has_absolute_negative_term(
            scoped_normalized, NOTIFICATION_LOUDNESS_OFF_TERMS
        )
        has_absolute_negative_positive_inner_negation = _notification_loudness_has_absolute_negative_term(
            scoped_normalized, NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS, inner_negated=True
        )
        has_absolute_negative_mute_inner_negation = _notification_loudness_has_absolute_negative_term(
            scoped_normalized, NOTIFICATION_LOUDNESS_MUTE_TERMS, inner_negated=True
        )
        has_absolute_negative_still = _notification_loudness_has_absolute_negative_german_still(
            scoped_normalized
        )
        has_absolute_negative_still_inner_negation = _notification_loudness_has_absolute_negative_german_still(
            scoped_normalized, inner_negated=True
        )
        has_absolute_negative_off_inner_negation = _notification_loudness_has_absolute_negative_term(
            scoped_normalized, NOTIFICATION_LOUDNESS_OFF_TERMS, inner_negated=True
        )
    status_scope_normalized = later_current_status_segment or normalized
    status_scope_polarity = later_current_status_segment or polarity_normalized
    if (
        later_current_status_segment
        and _notification_loudness_has_set_partial_quantifier(status_scope_normalized)
        and _notification_loudness_has_audibility_gradient_phrase(status_scope_normalized)
    ):
        return None
    audibility_gradient_decision = _notification_loudness_audibility_gradient_decision(
        status_scope_normalized
    )
    if audibility_gradient_decision is not None and (pending or has_notification_context):
        if (
            audibility_gradient_decision == "confirmed"
            and has_completed_action_negative
            and not has_completed_action_positive
        ):
            return "declined"
        if not pending and not has_explicit_notification_context and not has_direct_audibility_experience:
            return None
        return audibility_gradient_decision
    confirmed_needles = (
        "ja laut",
        "laut gestellt",
        "benachrichtigungen an",
        "benachrichtigung an",
        "notifications on",
        "notification on",
        "notifications enabled",
        "notification enabled",
        "silent mode is turned off",
        "silent mode was turned off",
        "silent mode is disabled",
        "silent mode is deactivated",
        "quiet mode is turned off",
        "quiet mode was turned off",
        "quiet mode is disabled",
        "quiet mode is deactivated",
        "lautlosmodus aus",
        "lautlosmodus ist aus",
        "stummmodus aus",
        "stummmodus ist aus",
        "nicht aus",
        "not off",
        "ist laut",
        "sind laut",
        "ist auf laut",
        "sind auf laut",
        "auf laut",
        "steht auf laut",
        "stehen auf laut",
        "are loud",
        "wieder laut",
        "ist an",
        "sind an",
        "are on",
        "been on",
        "turned on",
        "are enabled",
        "enabled",
        "was able to",
        "were able to",
        "have been able to",
        "has been able to",
        "are active",
        "sind aktiv",
        "turned on",
        "switched on",
        "unmuted",
        "laut geschaltet",
        "lautgeschaltet",
        "entstummt",
        "made loud",
        "made them loud",
        "made messages loud",
        "made notifications loud",
        "made notifications louder",
        "turned notifications louder",
        "managed to re-enable notifications",
        "managed to reactivate notifications",
        "succeeded in re-enabling notifications",
        "succeeded in reactivating notifications",
        "benachrichtigungen lauter gestellt",
        "die benachrichtigungen lauter gestellt",
        "benachrichtigungston ist jetzt lauter",
        "der benachrichtigungston ist jetzt lauter",
        "set notifications to loud",
        "got notifications working again",
        "got the notification sound working again",
        "restored notification sound",
        "restored the sound",
        "restored the notification sound",
        "notification sound is restored",
        "the notification sound is restored",
        "the mute is off",
        "der ton ist wieder da",
        "der ton ist wiederhergestellt",
        "der ton wurde wiederhergestellt",
        "der nachrichtenton wurde wiederhergestellt",
        "der benachrichtigungston ist wieder da",
        "ton wiederhergestellt",
        "benachrichtigungston wiederhergestellt",
        "i can hear the notification sound again",
        "can hear the notification sound again",
        "i hear the notification sound now",
        "hear the notification sound now",
        "ich kann die benachrichtigungen wieder hoeren",
        "ich kann den benachrichtigungston wieder hoeren",
        "nachrichtenton wiederhergestellt",
        "benachrichtigungen wieder zum klingen gebracht",
        "stummschaltung von benachrichtigungen entfernt",
        "benachrichtigungen aus dem stummmodus genommen",
        "re-enabled notifications",
        "reactivated notifications",
        "made notifications audible",
        "the notification volume is higher now",
        "notification volume is higher",
        "lautstaerke der benachrichtigungen erhoeht",
        "lautstaerke der nachrichten erhoeht",
        "benachrichtigungslautstaerke erhoeht",
        "nachrichtenlautstaerke erhoeht",
        "the sound is audible again",
        "sound is audible again",
        "set them to loud",
        "kann die nachrichten jetzt hoeren",
        "kann die benachrichtigungen jetzt hoeren",
        "ich hoere jetzt benachrichtigungen",
        "ich kann jetzt benachrichtigungen hoeren",
        "i can hear the message sound now",
        "can hear the message sound now",
        "man kann die nachrichten jetzt hoeren",
        "man kann die benachrichtigungen jetzt hoeren",
        "can hear notifications now",
        "can hear message notifications now",
        "can hear notifications",
        "can hear messages",
        "can hear message notifications",
        "notifications are back on",
        "notifications are back loud",
        "notifications are back audible",
        "notifications are back to being loud",
        "the notification sound has returned",
        "notification sound returned",
        "the sound has returned",
        "sound returned",
        "the sound returned",
        "sound came back",
        "the sound came back",
        "sound has come back",
        "the sound has come back",
        "the sound was restored",
        "the notification sound was restored",
        "the sound was brought back",
        "the notification sound was brought back",
        "der ton kam zurueck",
        "der nachrichtenton kam zurueck",
        "der ton ist zurueckgekehrt",
        "der nachrichtenton ist zurueckgekehrt",
        "the sound is back",
        "sound is back",
        "notifications are working again",
        "messages are working again",
        "notifications were restored to loud",
        "notifications returned to loud",
        "notifications returned to being loud",
        "notifications came back on",
        "notifications have come back on",
        "notifications have returned to being loud",
        "back",
        "they are back",
        "it is back",
        "they are ringing now",
        "they started again",
        "reappeared",
        "sind wieder da",
        "notifications came back",
        "the notifications came back",
        "notifications reappeared",
        "notifications appeared again",
        "messages started ringing",
        "notification sound started",
        "the notification sound started",
        "i got the notification sound back",
        "die nachrichten sind wieder da",
        "die benachrichtigungen tauchen wieder auf",
        "der nachrichtenton ist zurueck",
        "der nachrichtenton ist wieder da",
        "i hear notifications",
        "i hear messages",
        "i hear the notifications",
        "i hear the messages",
        "there is sound for notifications",
        "there is sound for messages",
        "there is a sound for notifications",
        "there is a sound for messages",
        "notifications ring",
        "messages ring",
        "notifications are ringing",
        "messages are ringing",
        "i receive notification sounds",
        "i receive message sounds",
        "i get notification sounds",
        "i get message sounds",
        "messages ring now",
        "notifications ring now",
        "die nachrichten klingeln jetzt",
        "die benachrichtigungen klingeln jetzt",
        "notification bell is ringing",
        "message bell is ringing",
        "bell is ringing",
        "nachrichten klingeln",
        "benachrichtigungen klingeln",
        "kann die nachrichten hoeren",
        "kann die benachrichtigungen hoeren",
        "kann nachrichten hoeren",
        "kann benachrichtigungen hoeren",
        "sound from messages",
        "a notification sound",
        "get notification sound",
        "receive message sounds",
        "sound comes from messages",
        "messages make a sound",
        "notifications make a sound",
        "messages produce sound",
        "hear message notifications",
        "hoere den nachrichtenton",
        "einen benachrichtigungston",
        "kommt ein ton",
        "machen einen ton",
        "geben einen ton",
        "mit ton",
        "notifications show up",
        "notifications appear",
        "messages show up",
        "i see message notifications",
        "alerts are showing",
        "notifications are showing",
        "notifications are displayed",
        "benachrichtigungen werden angezeigt",
        "nachrichten erscheinen",
        "eingeschaltet",
        "angeschaltet",
        "aktiviert",
        "erledigt",
        "gemacht",
        "getan",
        "fertig",
        "done",
        "completed",
        "geschafft",
        "gelungen",
        "ich kann bestaetigen",
        "ich kann belegen",
        "ich bestaetige",
        "ich habe bestaetigt",
        "bestaetigt",
    )
    declined_needles = (
        "ablehnen",
        "abgelehnt",
        "nicht fragen",
        "frag nicht",
        "nicht laut",
        "nicht auf laut",
        "nicht an",
        "not loud",
        "insufficiently loud",
        "insufficiently audible",
        "unzureichend laut",
        "unzureichend hoerbar",
        "not on",
        "not enabled",
        "aren t loud",
        "isn t loud",
        "aren t on",
        "isn t on",
        "aren t enabled",
        "isn t enabled",
        "noch nicht",
        "nicht erledigt",
        "nicht gemacht",
        "nicht eingeschaltet",
        "nicht aktiviert",
        "did not",
        "didn t",
        "haven t",
        "have not done",
        "haven t done",
        "have not completed",
        "haven t completed",
        "not yet",
        "benachrichtigungen nicht lauter gestellt",
        "die benachrichtigungen nicht lauter gestellt",
        "did not make notifications louder",
        "didn t make notifications louder",
        "did not turn notifications louder",
        "didn t turn notifications louder",
        "silent mode is not turned off",
        "silent mode was not turned off",
        "silent mode is not disabled",
        "quiet mode is not turned off",
        "quiet mode was not turned off",
        "quiet mode is not disabled",
        "mute is not off",
        "mute isn t off",
        "the mute is not off",
        "the mute isn t off",
        "notification sound is not restored",
        "the notification sound is not restored",
        "notification sound was not restored",
        "the notification sound was not restored",
        "sound is not restored",
        "the sound is not restored",
        "nachrichtenton nicht wiederhergestellt",
        "der nachrichtenton ist nicht wiederhergestellt",
        "benachrichtigungston nicht wiederhergestellt",
        "der ton ist nicht wieder da",
        "der nachrichtenton ist nicht wieder da",
        "keine benachrichtigung",
        "keine benachrichtigungen",
        "benachrichtigungen aus",
        "notifications off",
        "notification off",
        "do not disturb is enabled for notifications",
        "do not disturb is on for notifications",
        "dnd is enabled for notifications",
        "dnd is on for notifications",
        "ist aus",
        "sind aus",
        "kann ich nicht",
        "will nicht",
        "moechte nicht",
        "möchte nicht",
        "keine nachfrage",
        "will ich nicht",
        "moechte ich nicht",
        "möchte ich nicht",
        "kann die nachrichten nicht hoeren",
        "kann die benachrichtigungen nicht hoeren",
        "cannot hear notifications",
        "can not hear notifications",
        "can t hear notifications",
        "cannot hear messages",
        "can not hear messages",
        "can t hear messages",
        "could not hear notifications",
        "couldn t hear notifications",
        "could not hear messages",
        "couldn t hear messages",
        "could not hear message notifications",
        "couldn t hear message notifications",
        "i do not hear notifications",
        "i don t hear notifications",
        "the notification sound has not returned",
        "notification sound did not return",
        "the sound has not returned",
        "sound has not returned",
        "the sound is not back",
        "sound is not back",
        "the sound is gone again",
        "sound is gone again",
        "gone",
        "the sound stopped",
        "they are gone",
        "it is gone",
        "they disappeared",
        "disappeared",
        "stayed gone",
        "blieben weg",
        "notifications disappeared",
        "the notifications disappeared",
        "notifications no longer appear",
        "messages no longer show up",
        "notifications stopped ringing",
        "messages stopped making a sound",
        "the notification sound stopped",
        "i lost notification sound",
        "the sound was lost",
        "notifications vanished",
        "the messages are gone",
        "notifications are gone",
        "die benachrichtigungen sind verschwunden",
        "der nachrichtenton ist weg",
        "there is no sound for notifications",
        "there is no sound for messages",
        "there is no notification sound",
        "there is no message sound",
        "i receive no notification sounds",
        "i receive no message sounds",
        "i get no notification sounds",
        "i get no message sounds",
        "messages do not ring",
        "messages don t ring",
        "do not ring",
        "don t ring",
        "does not ring",
        "notifications do not ring",
        "notifications don t ring",
        "nicht klingeln",
        "die nachrichten klingeln nicht",
        "die benachrichtigungen klingeln nicht",
        "messages are not audible",
        "notifications are not audible",
        "notification bell is not ringing",
        "message bell is not ringing",
        "bell is not ringing",
        "nachrichten klingeln nicht",
        "benachrichtigungen klingeln nicht",
        "notifications don t show up",
        "notifications do not show up",
        "notifications do not appear",
        "notification does not appear",
        "messages aren t popping up",
        "messages don t pop up",
        "i don t see notifications",
        "i cannot see message notifications",
        "no alerts appear",
        "there are no message alerts",
        "benachrichtigungen erscheinen nicht",
        "nachrichten tauchen nicht auf",
        "keine nachrichtenhinweise",
        "keine benachrichtigungen erscheinen",
        "no sound from messages",
        "no notification sound",
        "isn t any notification sound",
        "no message sounds",
        "no sound comes from messages",
        "messages make no sound",
        "notifications make no sound",
        "messages produce no sound",
        "hear no message notifications",
        "i don t get notification sound",
        "i do not get notification sound",
        "i don t receive message sounds",
        "i do not receive message sounds",
        "keinen nachrichtenton",
        "keinen benachrichtigungston",
        "bekomme keinen nachrichtenton",
        "bekomme keinen benachrichtigungston",
        "kein ton",
        "keinen ton",
        "ohne ton",
    )
    has_negated_confirmed_phrase = _notification_loudness_has_negated_phrase(
        status_scope_polarity, confirmed_needles
    )
    has_negated_positive_unmute_phrase = _notification_loudness_has_negated_phrase(
        polarity_normalized, NOTIFICATION_LOUDNESS_POSITIVE_MUTE_PHRASES
    ) or any(
        _contains_normalized_phrase(status_scope_normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_NEGATED_POSITIVE_MUTE_PHRASES
    )
    has_declined_phrase = any(
        _contains_normalized_phrase(status_scope_normalized, needle)
        for needle in declined_needles
        if (
            (
                needle not in {
                    "keine benachrichtigung",
                    "keine benachrichtigungen",
                    "did not",
                    "didn t",
                    "haven t",
                    "not yet",
                    "noch nicht",
                }
                or not (has_negated_mute or has_negated_off)
            )
            and not (
                has_positive_unmute_phrase
                and needle in {"notifications off", "notification off", "benachrichtigungen aus"}
            )
            and not (
                has_completed_action_positive
                and needle in {"notifications off", "notification off", "benachrichtigungen aus"}
            )
            and not (
                has_negated_off
                and needle in {"notifications off", "notification off", "benachrichtigungen aus"}
            )
            and not _notification_loudness_phrase_is_double_negated(status_scope_normalized, needle)
            and not (
                has_positive_current_status
                and not has_negative_current_status
                and needle in {"did not", "didn t"}
            )
        )
    )
    has_declined_phrase = (
        has_declined_phrase
        or (
            has_unnegated_mute
            and not has_absolute_negative_mute
            and (
                not has_positive_unmute_phrase
                or (has_indirect_positive_mute_action and has_sequenced_action_status)
            )
        )
        or (
            has_unnegated_off
            and not has_absolute_negative_off
            and (
                not has_positive_unmute_phrase
                or (has_indirect_positive_mute_action and has_sequenced_action_status)
            )
        )
        or (
            has_negated_completion
            and not (has_completion_pronoun_prefix and later_current_status_segment)
        )
        or (
            has_negated_positive_unmute_phrase
            and not (
                later_current_status_segment
                and _notification_loudness_is_explicit_status_segment(later_current_status_segment)
            )
        )
        or (has_negated_confirmed_phrase and not has_absolute_negative_positive_inner_negation)
        or (has_negative_current_status and not has_absolute_negative_positive_inner_negation)
        or has_absolute_negative_positive_status
        or has_absolute_negative_mute_inner_negation
        or has_absolute_negative_still_inner_negation
        or has_absolute_negative_off_inner_negation
        or has_attributive_negative
        or has_volume_negative
        or (
            has_completion_pronoun_prefix
            and later_current_status_segment
            and (
                (has_unnegated_mute and not has_negated_mute)
                or (has_unnegated_off and not has_negated_off)
            )
        )
        or (
            has_completed_action_negative
            and not has_explicit_confirmation
            and not has_positive_unmute_phrase
            and not (has_positive_current_status and not has_negative_current_status)
            and not (
                has_absolute_negative_mute
                or has_absolute_negative_still
                or has_absolute_negative_off
            )
        )
    )
    if has_absolute_negative_positive_inner_negation:
        has_declined_phrase = False
    if has_declined_phrase and (pending or has_notification_context):
        return "declined"
    if pending and (
        normalized in NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS | {"erledigt", "gemacht"}
        or words & {"ja", "yes"}
        and has_notification_context
    ):
        return "confirmed"
    if (
        pending
        and words & NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS
        and words & NOTIFICATION_LOUDNESS_ACTION_WORDS
        and words & NOTIFICATION_LOUDNESS_NEGATION_TERMS
        and not has_notification_context
    ):
        return "declined"
    if pending and words & NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS and words & NOTIFICATION_LOUDNESS_ACTION_WORDS:
        return "confirmed"
    if pending and words & NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS and has_notification_context:
        return "confirmed"
    if (
        pending
        and words & NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS
        and words & NOTIFICATION_LOUDNESS_ACTION_WORDS
        and not (has_negated_mute or has_negated_off)
    ):
        if any(
            _contains_normalized_phrase(status_scope_normalized, phrase)
            for phrase in NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
        ) and not has_negated_completion:
            return "confirmed"
        return "declined"
    if pending and any(
        _contains_normalized_phrase(status_scope_normalized, needle)
        for needle in NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
    ):
        if _notification_loudness_is_non_declarative(
            text, status_scope_normalized
        ) and not _notification_loudness_has_sequenced_action_status(
            polarity_normalized
        ) and not has_pending_pronoun_completion:
            return None
        return "confirmed"
    if pending and normalized in NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS:
        return "declined"
    if has_notification_context and (
        (
            any(_contains_normalized_phrase(status_scope_normalized, needle) for needle in confirmed_needles)
            and not has_negated_confirmed_phrase
        )
        or (has_negated_mute and not has_absolute_negative_mute_inner_negation)
        or (has_negated_off and not has_absolute_negative_off_inner_negation)
        or has_positive_unmute_phrase
        or has_positive_current_status
        or has_absolute_negative_positive_inner_negation
        or has_absolute_negative_mute
        or has_absolute_negative_still
        or has_absolute_negative_off
        or has_attributive_positive
        or has_volume_positive
        or has_completed_action_positive
    ):
        return "confirmed"
    if has_notification_context and has_declined_phrase:
        return "declined"
    return None


def _set_notification_loudness_status(
    account_store: AccountStore,
    account_id: str,
    event: IncomingEvent,
    status: str,
    *,
    now: datetime | None = None,
) -> None:
    state = account_store.read_agent_state(account_id)
    route_state = _ensure_route_state(state, event)
    timestamp = _resolve_loudness_now(now).isoformat(timespec="seconds")
    route_state["status"] = status
    route_state["decided_at"] = timestamp
    route_state["updated_at"] = timestamp
    if status in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES:
        route_state["checks_active"] = False
        route_state["checks_stopped_at"] = timestamp
        route_state["checks_stop_reason"] = status
    route_state.pop("next_check_at", None)
    account_store.write_agent_state(account_id, state)


def _route_status(account_store: AccountStore, account_id: str, event: IncomingEvent) -> str:
    state = account_store.read_agent_state(account_id)
    notification_state = state.get("notification_loudness") if isinstance(state, dict) else None
    if not isinstance(notification_state, dict):
        return "unknown"
    routes = notification_state.get("routes")
    if not isinstance(routes, dict):
        return "unknown"
    route_state = _find_route_state(routes, _route_key(event))
    if not isinstance(route_state, dict):
        return "unknown"
    return _normalized_route_status(route_state)


def _ensure_route_state(state: dict[str, Any], event: IncomingEvent) -> dict[str, Any]:
    state.setdefault("schema_version", 1)
    notification_state = state.setdefault("notification_loudness", {})
    if not isinstance(notification_state, dict):
        notification_state = {}
        state["notification_loudness"] = notification_state
    notification_state["schema_version"] = 1
    routes = notification_state.setdefault("routes", {})
    if not isinstance(routes, dict):
        routes = {}
        notification_state["routes"] = routes
    route_key = _route_key(event)
    route_state = _find_route_state(routes, route_key)
    if route_state is None:
        route_state = {}
        routes[route_key] = route_state
    route_state.setdefault("status", "unknown")
    route_state["route_key"] = route_key
    route_state["route"] = _event_route(event)
    route_state["identity_key"] = event.identity_key
    return route_state


def _mark_notification_loudness_prompted(route_state: dict[str, Any], event: IncomingEvent, now: datetime) -> None:
    route_state["route"] = _event_route(event)
    _mark_route_state_prompted(route_state, now)


def _mark_route_state_prompted(route_state: dict[str, Any], now: datetime) -> None:
    timestamp = now.isoformat(timespec="seconds")
    route_state["status"] = NOTIFICATION_LOUDNESS_PENDING_STATUS
    route_state["checks_active"] = True
    route_state.pop("checks_stopped_at", None)
    route_state.pop("checks_stop_reason", None)
    route_state["last_prompt_at"] = timestamp
    route_state.pop("next_check_at", None)
    route_state["updated_at"] = timestamp
    prompts_by_date = route_state.setdefault("prompted_windows_by_date", {})
    if not isinstance(prompts_by_date, dict):
        prompts_by_date = {}
        route_state["prompted_windows_by_date"] = prompts_by_date
    date_key = _wake_date_key(now)
    windows = prompts_by_date.setdefault(date_key, [])
    if not isinstance(windows, list):
        windows = []
        prompts_by_date[date_key] = windows
    window = _wake_window_label(now)
    if window and window not in windows:
        windows.append(window)
    _trim_prompted_window_dates(prompts_by_date)


def _cancel_pending_notification_loudness_items(account_store: AccountStore, account_id: str, event: IncomingEvent) -> None:
    route_key = _route_key(event)
    with _account_proactive_outbox_lock(account_store, account_id):
        rows = account_store.read_proactive_outbox(account_id)
        changed = False
        timestamp = utc_now()
        for item in rows:
            if not isinstance(item, dict) or not is_notification_loudness_outbox_item(item):
                continue
            if _outbox_route_key(item) != _normalize_route_key(route_key):
                continue
            # A dispatching item was already claimed. Let its worker finish; the
            # active re-check linearizes cancellation before or after sending.
            if _notification_loudness_outbox_status(item) != "queued":
                continue
            item["status"] = "cancelled"
            item["updated_at"] = timestamp
            history = item.setdefault("status_history", [])
            if not isinstance(history, list):
                history = []
                item["status_history"] = history
            history.append({"at": timestamp, "status": "cancelled", "reason": "notification_loudness_decided"})
            changed = True
        if changed:
            account_store.write_proactive_outbox(account_id, rows)


def _has_queued_notification_loudness_item(account_store: AccountStore, account_id: str, route_key: str) -> bool:
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict) or not is_notification_loudness_outbox_item(item):
            continue
        if _outbox_route_key(item) != _normalize_route_key(route_key):
            continue
        if _notification_loudness_outbox_status(item) in {"queued", "dispatching"}:
            return True
    return False


def _has_notification_loudness_item_in_wake_window(
    account_store: AccountStore,
    account_id: str,
    route_key: str,
    now: datetime,
) -> bool:
    date_key = _wake_date_key(now)
    window = _wake_window_label(now)
    if not window:
        return False
    for item in account_store.read_proactive_outbox(account_id):
        if not isinstance(item, dict) or not is_notification_loudness_outbox_item(item):
            continue
        if _outbox_route_key(item) != _normalize_route_key(route_key):
            continue
        for field_name in ("due_at", "created_at", "updated_at"):
            item_at = _parse_datetime(str(item.get(field_name) or ""))
            if item_at is None:
                continue
            if _wake_date_key(item_at) == date_key and _wake_window_label(item_at) == window:
                return True
            break
    return False


def _account_proactive_outbox_lock(account_store: AccountStore, account_id: str):
    lock = getattr(account_store, "proactive_outbox_lock", None)
    if callable(lock):
        return lock(account_id)
    return nullcontext()


def _notification_loudness_outbox_status(item: Mapping[str, Any]) -> str | None:
    if "status" not in item:
        return "queued"
    value = item.get("status")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().casefold()


def _mark_notification_loudness_checks_stopped(route_state: dict[str, Any], reason: str) -> bool:
    stopped_at = route_state.get("checks_stopped_at")
    if (
        route_state.get("checks_active") is False
        and route_state.get("checks_stop_reason") == reason
        and isinstance(stopped_at, str)
        and _parse_datetime(stopped_at) is not None
    ):
        return False
    route_state["checks_active"] = False
    route_state["checks_stopped_at"] = utc_now()
    route_state["checks_stop_reason"] = reason
    return True


def _event_route(event: IncomingEvent) -> dict[str, Any]:
    return {
        "channel": _normalize_channel(event.channel),
        "chat_id": event.chat_id,
        "chat_type": _normalize_chat_type(event.chat_type),
        "adapter_slot": event.adapter_slot,
    }


def _route_key(event: IncomingEvent) -> str:
    return _route_key_for_channel_chat(event.channel, event.adapter_slot, event.chat_id)


def _private_route(route: Any) -> bool:
    return (
        isinstance(route, Mapping)
        and _is_private_chat_type(route.get("chat_type"))
        and bool(str(route.get("channel") or "").strip())
        and bool(str(route.get("chat_id") or "").strip())
        and _route_slot(route.get("adapter_slot")) is not None
    )


def _event_has_current_private_route(account_store: AccountStore, event: IncomingEvent) -> bool:
    route = account_store.get_identity_route(event.identity_key)
    if not _private_route(route):
        return False
    if not _is_private_chat_type(event.chat_type):
        return False
    route_slot = _route_slot(route.get("adapter_slot"))
    event_slot = _route_slot(event.adapter_slot)
    if route_slot is None or event_slot is None:
        return False
    return (
        str(route.get("channel") or "").strip().casefold() == str(event.channel or "").strip().casefold()
        and str(route.get("chat_id") or "").strip() == str(event.chat_id or "").strip()
        and route_slot == event_slot
    )


def _event_belongs_to_account(account_store: AccountStore, event: IncomingEvent, account_id: str) -> bool:
    return account_store.get_account_for_identity(event.identity_key) == account_id


def _route_slot(value: Any) -> int | None:
    if value is None:
        return 1
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        slot = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return 1
        if not text.isdecimal():
            return None
        slot = int(text)
    else:
        return None
    return slot if slot >= 1 else None


def _refresh_route_state_from_account_routes(
    account_store: AccountStore, account_id: str, route_key: str, route_state: dict[str, Any]
) -> tuple[bool, bool]:
    identity_key = str(route_state.get("identity_key") or "").strip()
    try:
        account_identity_keys = [str(identity) for identity in account_store.list_identities_for_account(account_id)]
    except Exception:
        return False, False
    candidate_keys = [identity_key] if identity_key and identity_key in account_identity_keys else []
    candidate_keys.extend(identity for identity in account_identity_keys if identity not in candidate_keys)
    for candidate in candidate_keys:
        route = account_store.get_identity_route(candidate)
        if not _private_route(route):
            continue
        if _route_key_from_route(route) != _normalize_route_key(route_key):
            continue
        changed = route_state.get("identity_key") != candidate or route_state.get("route") != route
        route_state["identity_key"] = candidate
        route_state["route"] = route
        return changed, True
    return False, False


def _find_route_state(routes: Mapping[str, Any], route_key: Any) -> dict[str, Any] | None:
    direct = routes.get(route_key) if isinstance(route_key, str) else None
    normalized_key = _normalize_route_key(route_key)
    fallback: dict[str, Any] | None = direct if isinstance(direct, dict) else None
    for candidate_key, candidate in routes.items():
        if not isinstance(candidate, dict) or _normalize_route_key(candidate_key) != normalized_key:
            continue
        if _normalized_route_status(candidate) in NOTIFICATION_LOUDNESS_TERMINAL_STATUSES:
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback


def _normalized_route_status(route_state: Mapping[str, Any]) -> str:
    if "status" not in route_state:
        return "unknown"
    value = route_state.get("status")
    if not isinstance(value, str) or not value.strip():
        return "<invalid>"
    return value.strip().casefold()


def _notification_loudness_checks_active(route_state: Mapping[str, Any]) -> bool:
    if "checks_active" not in route_state:
        return True
    return _normalize_bool(route_state.get("checks_active"), default=False)


def _normalize_route_key(route_key: Any) -> str:
    parts = str(route_key or "").strip().split(":", 2)
    if len(parts) != 3:
        return str(route_key or "").strip()
    return _route_key_for_channel_chat(parts[0], parts[1], parts[2])


def _route_key_from_route(route: Mapping[str, Any]) -> str:
    return _route_key_for_channel_chat(route.get("channel"), route.get("adapter_slot"), route.get("chat_id"))


def _outbox_route_key(item: Mapping[str, Any]) -> str:
    route_key = _canonical_outbox_route_key(item.get("route_key"))
    if route_key:
        return route_key
    route = item.get("route")
    return _canonical_outbox_route_key(_route_key_from_route(route)) if isinstance(route, Mapping) else ""


def _outbox_route_is_consistent(item: Mapping[str, Any]) -> bool:
    declared_key = _canonical_outbox_route_key(item.get("route_key"))
    route = item.get("route")
    if not isinstance(route, Mapping):
        return True
    if "chat_type" in route and not _is_private_chat_type(route.get("chat_type")):
        return False
    route_key = _canonical_outbox_route_key(_route_key_from_route(route))
    return not declared_key or not route_key or declared_key == route_key


def _canonical_outbox_route_key(route_key: Any) -> str:
    normalized = _normalize_route_key(route_key)
    parts = normalized.split(":", 2)
    if len(parts) != 3 or not parts[0] or not parts[2] or _route_slot(parts[1]) is None:
        return ""
    return normalized


def _route_key_for_channel_chat(channel: Any, adapter_slot: Any, chat_id: Any) -> str:
    normalized_channel = str(channel or "").strip().casefold()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_slot = _route_slot(adapter_slot)
    slot_label = str(normalized_slot) if normalized_slot is not None else "<invalid>"
    return f"{normalized_channel}:{slot_label}:{normalized_chat_id}"


def _notification_loudness_prompt_allowed(route_state: Mapping[str, Any], now: datetime, *, require_online: bool) -> bool:
    if _wake_window_label(now) == "":
        return False
    raw_next_check = route_state.get("next_check_at")
    if raw_next_check not in (None, ""):
        next_check = _parse_datetime(str(raw_next_check))
        if next_check is None or next_check > now:
            return False
    if _already_prompted_in_wake_window(route_state, now):
        return False
    if require_online:
        route = route_state.get("route")
        if not isinstance(route, Mapping) or not _route_recently_seen(route, now):
            return False
    return True


def _already_prompted_in_wake_window(route_state: Mapping[str, Any], now: datetime) -> bool:
    prompts_by_date = route_state.get("prompted_windows_by_date")
    if not isinstance(prompts_by_date, Mapping):
        return False
    windows = prompts_by_date.get(_wake_date_key(now))
    if not isinstance(windows, list):
        return False
    return _wake_window_label(now) in {str(window) for window in windows}


def _wake_date_key(now: datetime) -> str:
    return to_local(now).date().isoformat()


def _wake_window_label(now: datetime) -> str:
    local = to_local(now)
    start_hour, end_hour = NOTIFICATION_LOUDNESS_WAKE_HOURS
    if not _hour_in_window(local.hour, start_hour, end_hour):
        return ""
    midpoint = start_hour + ((end_hour - start_hour) % 24) / 2
    if start_hour < end_hour:
        return "first" if local.hour + local.minute / 60 < midpoint else "second"
    hour_value = local.hour + local.minute / 60
    normalized = hour_value if hour_value >= start_hour else hour_value + 24
    return "first" if normalized < midpoint else "second"


def _hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _route_recently_seen(route: Mapping[str, Any], now: datetime) -> bool:
    last_seen = _parse_datetime(str(route.get("last_seen_at") or ""))
    if last_seen is None:
        return False
    age = _resolve_loudness_now(now) - last_seen
    return timedelta(0) <= age <= NOTIFICATION_LOUDNESS_ONLINE_WINDOW


def _trim_prompted_window_dates(prompts_by_date: dict[str, Any]) -> None:
    for date_key in sorted(prompts_by_date, key=lambda value: str(value))[:-14]:
        prompts_by_date.pop(date_key, None)


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
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _resolve_loudness_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _normalize_text(text: str) -> str:
    return _normalize_text_value(text, preserve_clause_boundaries=False)


def _notification_loudness_canonicalize_double_temporal_negation(normalized: str) -> str:
    return (
        normalized.replace("not no longer", "still")
        .replace("nicht mehr nicht", "weiterhin")
        .replace("nicht laenger nicht", "weiterhin")
    )


def _notification_loudness_canonicalize_epistemic_forms(normalized: str) -> str:
    return (
        normalized.replace("do not doubt", "don t doubt")
        .replace("do not dispute", "don t dispute")
        .replace("no doubt", "certainly")
        .replace("without doubt", "certainly")
        .replace("for sure", "certainly")
        .replace("in fact", "actually")
        .replace("in der tat", "tatsaechlich")
        .replace("ohne zweifel", "sicher")
        .replace("kein zweifel", "sicher")
        .replace("it is not possible that", "it is not true that")
        .replace("it is impossible that", "it is not true that")
        .replace("es ist nicht moeglich dass", "nicht wahr dass")
        .replace("es ist unmoeglich dass", "nicht wahr dass")
    )


def _notification_loudness_leading_reply_prefix(text: str) -> tuple[str, str] | None:
    raw = str(text or "").strip().casefold()
    pronoun_or_status_subjects = {
        "sie",
        "die",
        "das",
        "er",
        "they",
        "it",
        "notification",
        "notifications",
        "nachricht",
        "nachrichten",
        "benachrichtigung",
        "benachrichtigungen",
        "message",
        "messages",
    }
    ambiguous_negative_determiners = {"no", "nein", "nee"}
    for word in sorted(
        NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS | NOTIFICATION_LOUDNESS_NEGATION_REPLY_WORDS,
        key=len,
        reverse=True,
    ):
        if not raw.startswith(word):
            continue
        remainder = raw[len(word) :]
        if not remainder:
            continue
        if remainder[0] in ",;:!?":
            remainder = remainder[1:].strip()
        else:
            if not remainder[0].isspace():
                continue
            remainder = remainder.strip()
            first_remainder_word = remainder.split(maxsplit=1)[0] if remainder else ""
            if word in ambiguous_negative_determiners and first_remainder_word not in pronoun_or_status_subjects - {
                "notification",
                "notifications",
                "nachricht",
                "nachrichten",
                "benachrichtigung",
                "benachrichtigungen",
                "message",
                "messages",
            }:
                continue
        if not remainder:
            continue
        decision = "confirmed" if word in NOTIFICATION_LOUDNESS_AFFIRMATION_WORDS else "declined"
        return decision, remainder
    return None


def _notification_loudness_has_reply_status_context(text: str) -> bool:
    normalized = _normalize_text(text)
    tokens = set(normalized.split())
    return bool(
        tokens
        & (
            {
                "benachrichtigung",
                "benachrichtigungen",
                "nachricht",
                "nachrichten",
                "notification",
                "notifications",
                "message",
                "messages",
                "laut",
                "loud",
                "an",
                "on",
                "aus",
                "off",
            }
            | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
            | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
        )
    )


def _notification_loudness_pending_modified_reply_decision(normalized: str) -> str | None:
    """Accept a known short reply surrounded only by current-state modifiers."""
    tokens = normalized.split()
    reply_modifiers = set(NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS) - {
        "any",
        "no",
        "mehr",
        "longer",
    }
    for replies, decision in (
        (NOTIFICATION_LOUDNESS_PENDING_POSITIVE_STATUS_REPLIES, "confirmed"),
        (NOTIFICATION_LOUDNESS_PENDING_NEGATIVE_STATUS_REPLIES, "declined"),
    ):
        for reply in sorted(replies, key=len, reverse=True):
            reply_tokens = reply.split()
            for prefix_length in range(len(tokens) - len(reply_tokens) + 1):
                prefix = tokens[:prefix_length]
                if not all(token in reply_modifiers for token in prefix):
                    continue
                start = prefix_length
                end = start + len(reply_tokens)
                if tokens[start:end] != reply_tokens:
                    continue
                suffix = tokens[end:]
                if all(token in reply_modifiers for token in suffix):
                    return decision
    return None


def _notification_loudness_pending_negated_volume_reply_decision(normalized: str) -> str | None:
    """Invert only explicit volume short replies prefixed by ``not/nicht``."""
    negation = None
    for candidate in ("not", "nicht"):
        if normalized.startswith(f"{candidate} "):
            negation = candidate
            break
    if negation is None:
        return None
    remainder = normalized[len(negation) + 1 :]
    volume_markers = {"volume", "lautstaerke", "prozent", "percent", "%"}
    scalar_positive = {"hoch", "high", "voll", "voller", "full", "maximum", "maximal"}
    scalar_negative = {"niedrig", "low", "leise", "quiet", "minimum", "down", "runter", "herunter"}
    for replies, decision in (
        (NOTIFICATION_LOUDNESS_PENDING_POSITIVE_STATUS_REPLIES, "declined"),
        (NOTIFICATION_LOUDNESS_PENDING_NEGATIVE_STATUS_REPLIES, "confirmed"),
    ):
        for reply in replies:
            if not volume_markers.intersection(reply.split()) and not reply.endswith("%"):
                continue
            if remainder == reply:
                return decision
    if remainder.startswith(("not ", "nicht ")):
        return None
    remainder_decision = _notification_loudness_pending_modified_reply_decision(remainder)
    if remainder_decision is not None:
        remainder_tokens = set(remainder.split())
        if remainder_tokens & volume_markers or remainder_tokens & scalar_positive or remainder_tokens & scalar_negative:
            return "declined" if remainder_decision == "confirmed" else "confirmed"
    if remainder in scalar_positive:
        return "declined"
    if remainder in scalar_negative:
        return "confirmed"
    return None


def _normalize_text_for_polarity(text: str) -> str:
    return _normalize_text_value(text, preserve_clause_boundaries=True)


def _normalize_text_value(text: str, *, preserve_clause_boundaries: bool) -> str:
    normalized = str(text or "").casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    for char in ",.;:!?":
        replacement = f" {NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN} " if preserve_clause_boundaries else " "
        normalized = normalized.replace(char, replacement)
    for char in "()[]{}\"'’‘":
        normalized = normalized.replace(char, " ")
    return " ".join(normalized.split())


def _contains_normalized_phrase(normalized: str, phrase: str) -> bool:
    phrase_tokens = str(phrase or "").split()
    if not phrase_tokens:
        return False
    tokens = normalized.split()
    width = len(phrase_tokens)
    return any(tokens[index : index + width] == phrase_tokens for index in range(len(tokens) - width + 1))


def _notification_loudness_mute_polarity(normalized: str) -> tuple[bool, bool]:
    return _notification_loudness_term_polarity(normalized, NOTIFICATION_LOUDNESS_MUTE_TERMS)


def _notification_loudness_german_still_polarity(normalized: str) -> tuple[bool, bool]:
    """Treat German ``still`` as quiet without confusing English temporal ``still``."""
    tokens = normalized.split()
    copulas = {"ist", "sind", "war", "waren", "bleibt", "bleiben"}
    has_unnegated = False
    has_negated = False
    for index, token in enumerate(tokens):
        if token != "still":
            continue
        for copula_index in range(max(0, index - 5), index):
            if tokens[copula_index] not in copulas:
                continue
            negation_count = _notification_loudness_scoped_negation_count(
                tokens, copula_index + 1, index
            )
            if negation_count % 2:
                has_negated = True
            else:
                has_unnegated = True
            break
    return has_unnegated, has_negated


def _notification_loudness_term_polarity(
    normalized: str, terms: frozenset[str]
) -> tuple[bool, bool]:
    tokens = normalized.split()
    relation_terms = {
        "avoid",
        "avoided",
        "avoiding",
        "prevent",
        "prevented",
        "preventing",
        "keep",
        "kept",
        "keeping",
        "leave",
        "left",
        "leaving",
        "vermeide",
        "vermeiden",
        "vermieden",
        "verhindere",
        "verhindern",
        "verhindert",
        "verhinderte",
        "bewahren",
        "bewahrt",
        "bewahre",
        "bewahrte",
        "gehindert",
        "hindern",
        "protect",
        "protected",
        "protecting",
        "shield",
        "shielded",
        "shielding",
        "geschuetzt",
        "schuetzen",
        "schuetzte",
        "escape",
        "escaped",
        "escaping",
        "save",
        "saved",
        "saving",
        "safe",
        "free",
        "immune",
        "entgehen",
        "entging",
        "entgingen",
        "entgangen",
        "verschonen",
        "verschont",
        "verschonte",
        "lassen",
    }
    direct_positive_relation_terms = {
        "avoid",
        "avoided",
        "avoiding",
        "prevent",
        "prevented",
        "preventing",
        "vermeide",
        "vermeiden",
        "vermieden",
        "verhindere",
        "verhindern",
        "verhindert",
        "verhinderte",
        "bewahren",
        "bewahrt",
        "bewahre",
        "bewahrte",
        "protect",
        "protected",
        "protecting",
        "shield",
        "shielded",
        "shielding",
        "geschuetzt",
        "schuetzen",
        "schuetzte",
        "escape",
        "escaped",
        "escaping",
        "save",
        "saved",
        "saving",
        "safe",
        "free",
        "immune",
        "entgehen",
        "entging",
        "entgingen",
        "entgangen",
        "verschonen",
        "verschont",
        "verschonte",
    }
    conditional_positive_relation_terms = {"keep", "kept", "keeping", "leave", "left", "leaving", "lassen"}
    passive_relation_terms = {
        "prevented",
        "verhindert",
        "verhinderte",
        "bewahrt",
        "bewahrte",
        "gehindert",
        "protected",
        "shielded",
        "geschuetzt",
        "escaped",
        "escaping",
        "saved",
        "saving",
        "safe",
        "free",
        "immune",
        "entging",
        "entgingen",
        "entgangen",
        "verschont",
        "verschonte",
    }
    passive_markers = {
        "am",
        "is",
        "are",
        "was",
        "were",
        "bin",
        "ist",
        "sind",
        "wurde",
        "wurden",
        "werde",
        "wird",
        "bleibt",
        "bleiben",
        "blieb",
        "blieben",
    }
    notification_subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    has_unnegated = False
    has_negated = False
    for index, token in enumerate(tokens):
        if token not in terms:
            continue
        preceding_start = max(0, index - 5)
        for boundary_index in range(preceding_start, index):
            if (
                tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
            ):
                preceding_start = boundary_index + 1
        negation_count = _notification_loudness_scoped_negation_count(tokens, preceding_start, index)
        relation_search_start = max(0, preceding_start - 4)
        for boundary_index in range(preceding_start - 1, relation_search_start - 1, -1):
            if (
                tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
            ):
                relation_search_start = boundary_index + 1
                break
        bridge_relation_terms = {
            "prevented",
            "verhindert",
            "verhinderte",
            "bewahrt",
            "bewahrte",
            "gehindert",
            "protected",
            "shielded",
            "geschuetzt",
        }
        bridge_target_terms = set(NOTIFICATION_LOUDNESS_MUTE_TERMS) | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
        bridge_subject_terms = {
            "die",
            "der",
            "das",
            "nachricht",
            "nachrichten",
            "message",
            "messages",
            "benachrichtigung",
            "benachrichtigungen",
            "notification",
            "notifications",
        }
        if (
            preceding_start <= index
            and preceding_start > 0
            and tokens[preceding_start - 1]
            in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN}
            and (
                tokens[preceding_start] in {"dass", "that"}
                or (
                    tokens[preceding_start] in bridge_target_terms
                    and set(tokens[max(0, preceding_start - 4) : preceding_start]) & bridge_relation_terms
                )
                or (
                    tokens[preceding_start] in bridge_subject_terms
                    and set(tokens[max(0, preceding_start - 4) : preceding_start]) & bridge_relation_terms
                )
            )
        ):
            relation_search_start = max(0, preceding_start - 8)
            for boundary_index in range(preceding_start - 2, relation_search_start - 1, -1):
                if (
                    tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ):
                    relation_search_start = boundary_index + 1
                    break
        relation_index = next(
            (
                candidate
                for candidate in range(index - 1, relation_search_start - 1, -1)
                if tokens[candidate] in relation_terms
            ),
            None,
        )
        if relation_index is not None:
            relation_negated = _notification_loudness_scoped_negation_count(
                tokens, relation_search_start, relation_index
            ) % 2 == 1
            relation_target_tokens = set(tokens[relation_index + 1 : index])
            relation_is_positive = tokens[relation_index] in direct_positive_relation_terms
            if tokens[relation_index] in {"safe", "free"}:
                relation_is_positive = bool(relation_target_tokens & {"from", "vor", "von"})
            elif tokens[relation_index] == "immune":
                relation_is_positive = bool(relation_target_tokens & {"from", "to", "vor", "von"})
            elif tokens[relation_index] in {"save", "saved", "saving"}:
                relation_is_positive = bool(relation_target_tokens & {"from", "vor", "von"})
            passive_user_relation = (
                tokens[relation_index] in passive_relation_terms
                and bool(set(tokens[relation_search_start:relation_index]) & passive_markers)
                and not bool(set(tokens[relation_search_start:relation_index]) & notification_subject_terms)
            )
            if passive_user_relation:
                continue
            if relation_negated and relation_index >= preceding_start:
                negation_count -= 1
            elif (
                relation_is_positive
                or (
                    tokens[relation_index] in conditional_positive_relation_terms
                    and relation_target_tokens & {"from", "dass", "zu"}
                )
            ) and not passive_user_relation:
                negation_count += 1
        if negation_count % 2:
            has_negated = True
        else:
            has_unnegated = True
    return has_unnegated, has_negated


def _notification_loudness_has_uncertainty(normalized: str) -> bool:
    direct_can_not_hear = any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "can not clearly hear",
            "kann nicht deutlich hoeren",
            "kann nicht klar hoeren",
        )
    )
    direct_negative_clarity_gradient = direct_can_not_hear or any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "not clear enough",
            "nicht klar genug",
            "nicht deutlich genug",
        )
    )
    for phrase in NOTIFICATION_LOUDNESS_UNCERTAINTY_PHRASES:
        normalized_phrase = _normalize_text(phrase)
        if normalized_phrase in {"not clear", "not clearly"} and direct_negative_clarity_gradient:
            continue
        if _contains_normalized_phrase(normalized, normalized_phrase):
            return True
    return False


def _notification_loudness_has_non_assertive_status(normalized: str) -> bool:
    """Reject modal or future state claims unless a later clause states a fact."""
    modal_terms = frozenset(
        {
            "will",
            "shall",
            "may",
            "might",
            "could",
            "would",
            "should",
            "must",
            "can",
            "cannot",
            "kann",
            "koennte",
            "koennten",
            "könnte",
            "könnten",
            "muss",
            "muessen",
            "müssen",
            "soll",
            "sollen",
            "sollte",
            "sollten",
            "duerfen",
            "duerfte",
            "duerften",
            "dürfen",
            "dürfte",
            "dürften",
            "wuerde",
            "würde",
            "moechte",
            "möchte",
            "plane",
            "plant",
            "plan",
            "planned",
            "planning",
            "versuche",
            "versucht",
            "trying",
            "try",
            "intend",
            "intended",
            "supposed",
            "expected",
            "becoming",
            "getting",
            "likely",
            "unlikely",
            "seem",
            "seems",
            "appear",
            "appears",
            "look",
            "looks",
            "scheine",
            "scheint",
            "scheinen",
            "wirke",
            "wirkt",
            "wirken",
            "sieht",
            "said",
            "believed",
            "told",
            "informed",
            "reported",
            "heisst",
            "gesagt",
            "berichtet",
            "gemeldet",
        }
    )
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
        | {
            phrase
            for phrase in NOTIFICATION_LOUDNESS_COMPLETION_PHRASES
            if " " not in phrase
        }
        | {"work", "works", "worked", "funktioniert", "funktionieren", "klappt", "geklappt"}
    )
    clause_boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
    }
    tokens = normalized.split()
    if "in der lage" in normalized and set(tokens) & state_terms:
        if set(tokens) & {"bin", "ist", "sind"}:
            return True
    clauses: list[list[str]] = [[]]
    for token in tokens:
        if token in clause_boundaries:
            clauses.append([])
        else:
            clauses[-1].append(token)
    for clause in reversed(clauses):
        state_indices = [index for index, token in enumerate(clause) if token in state_terms]
        if not state_indices:
            continue
        first_state_index = state_indices[0]
        prefix = clause[:first_state_index]
        if any(
            index > 0
            and token == "being"
            and prefix[index - 1] in {"is", "are", "was", "were"}
            for index, token in enumerate(prefix)
        ):
            return True
        if "gerade" in prefix and set(prefix) & {"werde", "werden", "wird"}:
            return True
        if modal_terms.intersection(prefix):
            return True
        if {"werde", "werden", "wird"}.intersection(prefix):
            return "sein" in clause[first_state_index + 1 :]
        return False
    return False


def _notification_loudness_has_progressive_status_transition(normalized: str) -> bool:
    tokens = normalized.split()
    english_transition_terms = {
        "becoming",
        "getting",
    }
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
        | {"quiet", "leise", "still"}
    )
    if set(tokens) & english_transition_terms and set(tokens) & state_terms:
        return True
    german_transition_terms = {"werden", "werde", "wird"}
    german_state_terms = {"laut", "loud", "leise", "quiet", "stumm", "silent"}
    return any(
        token in german_transition_terms
        and bool(set(tokens[index + 1 :]) & german_state_terms)
        for index, token in enumerate(tokens)
    )


def _notification_loudness_has_conditional_status(normalized: str) -> bool:
    conditional_terms = {
        "if",
        "when",
        "unless",
        "provided",
        "assuming",
        "suppose",
        "falls",
        "wenn",
        "sofern",
        "vorausgesetzt",
        "angenommen",
    }
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    )
    tokens = normalized.split()
    if any(token in conditional_terms and bool(set(tokens) & state_terms) for token in tokens):
        return True
    return bool(
        any(token in conditional_terms for token in tokens)
        and _notification_loudness_has_audibility_gradient(normalized)
    )


def _notification_loudness_later_current_status_segment(
    normalized: str, *, allow_completion_pronoun: bool = False
) -> str | None:
    tokens = normalized.split()
    notification_subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
    }
    boundary_indices = [
        index
        for index, token in enumerate(tokens)
        if token in boundaries and token not in {"or", "oder"}
        and not (token == "but" and index > 0 and tokens[index - 1] == "all")
    ]
    for boundary_index in reversed(boundary_indices):
        segment = " ".join(tokens[boundary_index + 1 :])
        if not segment or _notification_loudness_has_non_assertive_status(segment):
            continue
        indirect_relation_terms = {
            "prevent",
            "prevented",
            "preventing",
            "protected",
            "protecting",
            "shielded",
            "shielding",
            "saved",
            "saving",
            "avoided",
            "avoiding",
            "verhindert",
            "verhindern",
            "gehindert",
            "geschützt",
            "geschuetzt",
            "bewahrt",
            "bewahren",
            "verschont",
            "verschonen",
        }
        if not _notification_loudness_is_explicit_status_segment(
            segment,
            allow_pronoun=bool(indirect_relation_terms.intersection(tokens[:boundary_index]))
            or (
                bool(set(tokens[:boundary_index]) & notification_subject_terms)
                and _notification_loudness_has_audibility_gradient(
                    " ".join(tokens[:boundary_index])
                )
            )
            or allow_completion_pronoun,
        ):
            continue
        has_positive = _notification_loudness_has_positive_current_status(segment)
        has_negative = _notification_loudness_has_negative_current_status(segment)
        has_unnegated_mute, has_negated_mute = _notification_loudness_mute_polarity(segment)
        has_unnegated_off, has_negated_off = _notification_loudness_term_polarity(
            segment, NOTIFICATION_LOUDNESS_OFF_TERMS
        )
        has_gradient = _notification_loudness_has_audibility_gradient_phrase(segment)
        if (
            has_positive
            or has_negative
            or has_unnegated_mute
            or has_negated_mute
            or has_unnegated_off
            or has_negated_off
            or has_gradient
        ):
            return segment
    return None


def _notification_loudness_is_explicit_status_segment(
    normalized: str, *, allow_pronoun: bool = False
) -> bool:
    tokens = normalized.split()
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    pronoun_terms = {"sie", "die", "das", "er", "they", "it"}
    copulas = {
        "ist",
        "sind",
        "is",
        "are",
        "re",
        "remain",
        "remains",
        "remained",
        "stay",
        "stays",
        "stayed",
        "bleibt",
        "bleiben",
        "blieb",
        "blieben",
        "been",
    }
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    )
    has_explicit_subject = bool(set(tokens) & subject_terms)
    has_temporal_pronoun_context = bool(
        set(tokens) & pronoun_terms
        and (
            set(tokens) & set(NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS)
            or allow_pronoun
        )
    )
    return bool(
        (has_explicit_subject or has_temporal_pronoun_context)
        and set(tokens) & copulas
        and set(tokens) & state_terms
    )


def _notification_loudness_prior_clause_before_later_status(
    normalized: str, later_segment: str | None
) -> str | None:
    if not later_segment:
        return None
    tokens = normalized.split()
    segment_tokens = later_segment.split()
    boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
    }
    boundary_indices = [index for index, token in enumerate(tokens) if token in boundaries]
    for boundary_index in reversed(boundary_indices):
        if tokens[boundary_index + 1 :] == segment_tokens:
            return " ".join(tokens[:boundary_index])
    return None


def _notification_loudness_has_later_current_status_clause(normalized: str) -> bool:
    return _notification_loudness_later_current_status_segment(normalized) is not None


def _notification_loudness_has_historical_marker(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, _normalize_text(phrase.strip()))
        for phrase in NOTIFICATION_LOUDNESS_HISTORICAL_PHRASES
    )


def _notification_loudness_has_past_perfect_marker(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in ("had", "hatte", "hatten")
    )


def _notification_loudness_historical_causal_prefix(normalized: str) -> str | None:
    """Return the asserted prefix when a causal tail only describes the past."""
    tokens = normalized.split()
    causal_terms = {"because", "since", "as", "weil", "da", "denn"}
    past_copulas = {"was", "were", "war", "waren", "had", "hatte", "hatten"}
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    )
    boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
    }
    for connector_index, token in enumerate(tokens):
        if token not in causal_terms:
            continue
        tail_end = len(tokens)
        for boundary_index in range(connector_index + 1, len(tokens)):
            if tokens[boundary_index] in boundaries:
                tail_end = boundary_index
                break
        tail = tokens[connector_index + 1 : tail_end]
        if not set(tail) & past_copulas or not set(tail) & state_terms:
            continue
        if set(tail) & set(NOTIFICATION_LOUDNESS_CURRENT_TIME_MARKER_PHRASES):
            continue
        return " ".join(tokens[:connector_index])
    return None


def _notification_loudness_has_failed_action(normalized: str) -> bool:
    for phrase in NOTIFICATION_LOUDNESS_FAILED_ACTION_PHRASES:
        if (
            _contains_normalized_phrase(normalized, phrase)
            and not _notification_loudness_phrase_is_negated(normalized, _normalize_text(phrase))
        ):
            return True
    tokens = normalized.split()
    for index, token in enumerate(tokens):
        if token not in {"konnte", "konnten"}:
            continue
        if _notification_loudness_scoped_negation_count(tokens, index + 1, len(tokens)) % 2:
            return True
    return False


def _notification_loudness_has_negated_failure_action(normalized: str) -> bool:
    tokens = normalized.split()
    failure_terms = {"failed", "gescheitert", "fehlgeschlagen"}
    for index, token in enumerate(tokens):
        if token not in failure_terms:
            continue
        if _notification_loudness_scoped_negation_count(tokens, max(0, index - 4), index) % 2:
            return True
    return False


def _notification_loudness_failed_action_polarity(normalized: str) -> str | None:
    tokens = normalized.split()
    failure_phrases = tuple(
        _normalize_text(phrase).split() for phrase in NOTIFICATION_LOUDNESS_FAILED_ACTION_PHRASES
    )
    windows: list[list[str]] = []
    for phrase_tokens in failure_phrases:
        width = len(phrase_tokens)
        if not width:
            continue
        for index in range(len(tokens) - width + 1):
            if tokens[index : index + width] != phrase_tokens:
                continue
            windows.append(tokens[max(0, index - 8) : min(len(tokens), index + width + 10)])
    for index, token in enumerate(tokens):
        if token not in {"konnte", "konnten"}:
            continue
        if _notification_loudness_scoped_negation_count(tokens, index + 1, len(tokens)) % 2 == 0:
            continue
        window_end = min(len(tokens), index + 14)
        for boundary_index in range(index + 1, window_end):
            if (
                tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
            ):
                window_end = boundary_index
                break
        windows.append(tokens[max(0, index - 8) : window_end])
    if not windows:
        return None
    positive_targets = (
        "laut",
        "loud",
        "an",
        "on",
        "enabled",
        "enable",
        "aktiv",
        "aktiviert",
        "activate",
        "activated",
        "unmute",
        "unmuted",
        "entstummt",
        "anschalten",
        "anzuschalten",
        "einschalten",
        "einzuschalten",
        "hoch",
        "up",
        "full",
    )
    negative_targets = (
        "stumm",
        "lautlos",
        "muted",
        "mute",
        "muting",
        "silent",
        "silenced",
        "silencing",
        "aus",
        "off",
        "disabled",
        "disable",
        "disabling",
        "inaktiv",
        "deaktiviert",
        "deactivate",
        "deactivated",
        "deactivating",
        "ausschalten",
        "auszuschalten",
        "abschalten",
        "abzuschalten",
        "turning",
        "switching",
        "leise",
        "quiet",
        "down",
        "low",
    )
    has_positive_target = any(set(window).intersection(positive_targets) for window in windows)
    has_negative_target = any(set(window).intersection(negative_targets) for window in windows)
    if has_positive_target and not has_negative_target:
        return "positive"
    if has_negative_target and not has_positive_target:
        return "negative"
    return None


def _notification_loudness_explicit_negated_status_decision(
    normalized: str, *, pending: bool
) -> str | None:
    tokens = normalized.split()
    markers = (
        ("not", "the", "case", "that"),
        ("nicht", "der", "fall", "dass"),
        ("not", "true", "that"),
        ("nicht", "wahr", "dass"),
        ("stimmt", "nicht", "dass"),
        ("false", "that"),
        ("falsch", "dass"),
        ("deny", "that"),
        ("denies", "that"),
        ("denied", "that"),
        ("bestreite", "dass"),
        ("bestreitet", "dass"),
        ("bestritt", "dass"),
        ("verneine", "dass"),
        ("verneint", "dass"),
        ("verneinte", "dass"),
        ("not", "true"),
        ("nicht", "wahr"),
    )
    for marker in sorted(markers, key=len, reverse=True):
        width = len(marker)
        for index in range(len(tokens) - width + 1):
            if tuple(tokens[index : index + width]) != marker:
                continue
            preceding = tokens[max(0, index - 3) : index]
            if (
                set(preceding) & {"not", "nicht", "cannot", "t"}
                or {"don", "t"}.issubset(preceding)
                or {"do", "not"}.issubset(preceding)
            ):
                continue
            remainder = " ".join(tokens[index + width :]).strip()
            if not remainder:
                continue
            inner_decision = _notification_loudness_decision(remainder, pending=pending)
            if inner_decision == "confirmed":
                return "declined"
            if inner_decision == "declined":
                return "confirmed"
    return None


def _notification_loudness_has_successful_ability_action(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_SUCCESSFUL_ABILITY_PHRASES
    )


def _notification_loudness_has_indirect_positive_mute_action(normalized: str) -> bool:
    tokens = normalized.split()
    relation_tokens = {
        "avoid",
        "avoided",
        "avoiding",
        "prevent",
        "prevented",
        "preventing",
        "keep",
        "kept",
        "keeping",
        "vermeiden",
        "vermieden",
        "vermeide",
        "verhindern",
        "verhindert",
        "verhindere",
        "verhinderte",
        "bewahren",
        "bewahrt",
        "bewahre",
        "bewahrte",
        "protect",
        "protected",
        "protecting",
        "shield",
        "shielded",
        "shielding",
        "geschuetzt",
        "schuetzen",
        "schuetzte",
        "escape",
        "escaped",
        "escaping",
        "save",
        "saved",
        "saving",
        "safe",
        "free",
        "immune",
        "entgehen",
        "entging",
        "entgingen",
        "entgangen",
        "verschonen",
        "verschont",
        "verschonte",
    }
    completed_relations = {
        "avoided",
        "avoiding",
        "prevented",
        "preventing",
        "kept",
        "keeping",
        "vermieden",
        "verhindert",
        "verhinderte",
        "bewahrt",
        "bewahrte",
        "protected",
        "shielded",
        "geschuetzt",
        "escaped",
        "saved",
        "safe",
        "free",
        "immune",
        "entgangen",
        "verschont",
        "verschonte",
    }
    success_markers = (
        "managed to",
        "succeeded in",
        "successfully",
        "was able to",
        "were able to",
        "have been able to",
        "has been able to",
        "geschafft",
        "gelungen",
    )
    attempt_or_failure_terms = {
        "tried",
        "attempted",
        "versuchte",
        "versucht",
        "probierte",
        "probiert",
        "failed",
        "gescheitert",
        "fehlgeschlagen",
    }
    negative_action_terms = {
        "mute",
        "muted",
        "muting",
        "silence",
        "silenced",
        "silencing",
        "stumm",
        "lautlos",
        "stummgeschaltet",
        "ausschalten",
        "auszuschalten",
        "turn",
        "turning",
        "switch",
        "switching",
    }
    negative_state_terms = set(NOTIFICATION_LOUDNESS_MUTE_TERMS) | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    passive_relation_terms = {
        "prevented",
        "verhindert",
        "verhinderte",
        "bewahrt",
        "bewahrte",
        "gehindert",
        "protected",
        "shielded",
        "geschuetzt",
        "escaped",
        "escaping",
        "saved",
        "saving",
        "safe",
        "free",
        "immune",
        "entgangen",
        "verschont",
        "verschonte",
    }
    passive_markers = {
        "am",
        "is",
        "are",
        "was",
        "were",
        "bin",
        "ist",
        "sind",
        "wurde",
        "wurden",
        "werde",
        "wird",
        "bleibt",
        "bleiben",
        "blieb",
        "blieben",
    }
    notification_subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    for relation_index, relation in enumerate(tokens):
        if relation not in relation_tokens:
            continue
        preceding_start = max(0, relation_index - 8)
        preceding = tokens[preceding_start:relation_index]
        if _notification_loudness_scoped_negation_count(tokens, preceding_start, relation_index) % 2:
            continue
        if set(preceding) & attempt_or_failure_terms:
            continue
        if (
            relation in passive_relation_terms
            and set(preceding) & passive_markers
            and not set(preceding) & notification_subject_terms
        ):
            continue
        tail_connector_terms = {"from", "dass", "zu", "to", "vor", "von", "being"}
        if relation in {"safe", "free"} and not set(tokens[relation_index + 1 :]) & {"from", "vor", "von"}:
            continue
        if relation == "immune" and not set(tokens[relation_index + 1 :]) & {"from", "to", "vor", "von"}:
            continue
        if relation in {"save", "saved", "saving"} and not set(tokens[relation_index + 1 :]) & {"from", "vor", "von"}:
            continue
        prefix_text = " ".join(preceding)
        is_completed = relation in completed_relations or any(
            _contains_normalized_phrase(prefix_text, marker) for marker in success_markers
        )
        if not is_completed:
            continue
        tail_end = min(len(tokens), relation_index + 12)
        for boundary_index in range(relation_index + 1, tail_end):
            if (
                tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
            ):
                tail_end = boundary_index
                break
        tail = tokens[relation_index + 1 : tail_end]
        if not set(tail) & negative_state_terms:
            continue
        if relation in {"avoid", "avoided", "avoiding", "vermeiden", "vermieden", "vermeide"}:
            if set(tail) & negative_action_terms or "zu" in tail:
                return True
            continue
        if set(tail) & negative_action_terms and set(tail) & tail_connector_terms:
            return True
        if relation in {"escape", "escaped", "escaping", "entgehen", "entging", "entgingen", "entgangen"}:
            if set(tail) & (negative_action_terms | negative_state_terms):
                return True
        if (
            relation
            in {
                "prevent",
                "prevented",
                "preventing",
                "verhindern",
                "verhindert",
                "verhindere",
                "verhinderte",
                "bewahren",
                "bewahrt",
                "bewahre",
                "bewahrte",
                "protect",
                "protected",
                "protecting",
                "shield",
                "shielded",
                "shielding",
                "geschuetzt",
                "schuetzen",
                "schuetzte",
            }
            and set(tail) & negative_action_terms
            and tail
            and tail[0] in negative_action_terms
        ):
            return True
    postposed_relation_terms = {"verschont", "verschonte"}
    for relation_index, relation in enumerate(tokens):
        if relation not in postposed_relation_terms:
            continue
        preceding_start = max(0, relation_index - 12)
        preceding = tokens[preceding_start:relation_index]
        if not set(preceding) & negative_state_terms:
            continue
        if (
            set(preceding) & passive_markers
            and not set(preceding) & notification_subject_terms
        ):
            continue
        if set(preceding) & {"vor", "von"}:
            return True
    return False


def _notification_loudness_has_explicit_historical_time(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in NOTIFICATION_LOUDNESS_EXPLICIT_HISTORICAL_TIME_PHRASES
    )


def _notification_loudness_has_current_temporal_contrast(normalized: str) -> bool:
    return _notification_loudness_current_temporal_segment(normalized) is not None


def _notification_loudness_current_temporal_segment(normalized: str) -> str | None:
    tokens = normalized.split()
    historical_phrases = tuple(
        _normalize_text(phrase.strip()).split()
        for phrase in NOTIFICATION_LOUDNESS_HISTORICAL_PHRASES
    ) + tuple(
        _normalize_text(phrase).split()
        for phrase in NOTIFICATION_LOUDNESS_FAILED_ACTION_PHRASES
    ) + tuple(
        _normalize_text(phrase).split()
        for phrase in NOTIFICATION_LOUDNESS_ATTEMPT_ACTION_PHRASES
    )
    current_phrases = tuple(_normalize_text(phrase).split() for phrase in NOTIFICATION_LOUDNESS_CURRENT_TIME_MARKER_PHRASES)
    historical_ranges: list[tuple[int, int]] = []
    current_starts: list[int] = []
    for phrase in historical_phrases:
        width = len(phrase)
        historical_ranges.extend(
            (index, index + width)
            for index in range(len(tokens) - width + 1)
            if tokens[index : index + width] == phrase
        )
    for phrase in current_phrases:
        width = len(phrase)
        current_starts.extend(
            index
            for index in range(len(tokens) - width + 1)
            if tokens[index : index + width] == phrase
        )
    candidates: list[tuple[int, int]] = []
    for historical_start, historical_end in historical_ranges:
        for current_start in current_starts:
            if current_start < historical_end:
                continue
            between = tokens[historical_end:current_start]
            if not between or any(
                token in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                or token == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                for token in between
            ):
                boundary_indices = [
                    index
                    for index in range(historical_end, current_start)
                    if tokens[index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ]
                segment_start = (max(boundary_indices) + 1) if boundary_indices else historical_end
                candidates.append((current_start, segment_start))
    if not candidates:
        return None
    _, segment_start = max(candidates)
    segment = [token for token in tokens[segment_start:] if token != NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN]
    return " ".join(segment) or None


def _notification_loudness_current_transition_segment(normalized: str) -> str | None:
    """Return the last clause only when it explicitly describes a state transition."""
    tokens = normalized.split()
    boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
    }
    boundary_indices = [index for index, token in enumerate(tokens) if token in boundaries]
    if not boundary_indices:
        return None
    segment_start = boundary_indices[-1] + 1
    segment = tokens[segment_start:]
    transition_markers = {
        "back",
        "returned",
        "return",
        "reappeared",
        "reappear",
        "came",
        "come",
        "started",
        "start",
        "again",
        "now",
        "currently",
        "stopped",
        "stop",
        "disappeared",
        "vanished",
        "lost",
        "gone",
        "weg",
        "verschwunden",
        "verschwanden",
        "aufgetaucht",
        "auftauchen",
        "wieder",
    }
    if not set(segment) & transition_markers:
        return None
    return " ".join(token for token in segment if token != NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN) or None


def _notification_loudness_current_intent_segment(normalized: str) -> str | None:
    """Prefer a later explicit state over an earlier intent or failed action."""
    tokens = normalized.split()
    boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
    }
    boundary_indices = [index for index, token in enumerate(tokens) if token in boundaries]
    if not boundary_indices:
        return None
    segment_start = boundary_indices[-1] + 1
    segment = tokens[segment_start:]
    if segment and segment[0] in {"ob", "whether", "dass", "that"}:
        return None
    status_copulas = {
        "ist",
        "sind",
        "is",
        "are",
        "re",
        "aren",
        "isn",
        "remain",
        "remains",
        "stay",
        "stays",
        "bleibt",
        "bleiben",
    }
    if not set(segment) & status_copulas:
        return None
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
        | {"loud", "laut", "ringing", "klingeln", "klingelt"}
    )
    if not set(segment) & state_terms:
        return None
    intent_terms = {
        "want",
        "wanted",
        "plan",
        "planned",
        "planning",
        "try",
        "trying",
        "tried",
        "should",
        "must",
        "will",
        "would",
        "could",
        "might",
        "may",
        "need",
        "failed",
        "attempted",
        "attempting",
        "cannot",
        "moechte",
        "wollte",
        "plane",
        "plante",
        "versuche",
        "versuchte",
        "sollte",
        "muss",
        "werde",
        "wuerde",
        "koennte",
        "gescheitert",
        "fehlgeschlagen",
        "konnte",
    }
    if not set(tokens[:segment_start]) & intent_terms:
        return None
    return " ".join(token for token in segment if token != NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN) or None


def _notification_loudness_has_partial_quantifier(normalized: str) -> bool:
    if any(
        _contains_normalized_phrase(normalized, _normalize_text(phrase))
        for phrase in NOTIFICATION_LOUDNESS_PARTIAL_QUANTIFIER_PHRASES
    ):
        return True
    tokens = normalized.split()
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    absolute_negation_tokens = {"not", "nicht", "no", "none", "neither", "kein", "keine", "weder"}
    for index, token in enumerate(tokens[:-1]):
        if token != "any" or tokens[index + 1] not in subject_terms:
            continue
        preceding = tokens[max(0, index - 3) : index]
        if (
            set(preceding) & absolute_negation_tokens
            or tuple(preceding[-2:]) in {("aren", "t"), ("isn", "t"), ("weren", "t"), ("wasn", "t")}
        ):
            continue
        return True
    return False


def _notification_loudness_has_set_partial_quantifier(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, _normalize_text(phrase))
        for phrase in (
            "not all",
            "aren t all",
            "isn t all",
            "wasn t all",
            "weren t all",
            "not every",
            "not each",
            "not completely",
            "not fully",
            "not entirely",
            "not quite",
            "almost",
            "nearly",
            "partially",
            "only partly",
            "some",
            "a few",
            "several",
            "most",
            "many",
            "almost all",
            "all but",
            "at least",
            "at most",
            "a majority",
            "nicht alle",
            "nicht jede",
            "nicht jeder",
            "nicht jedes",
            "nicht vollstaendig",
            "nicht komplett",
            "nicht ganz",
            "teilweise",
            "nur teilweise",
            "nur zum teil",
            "einige",
            "manche",
            "mehrere",
            "ein paar",
            "die meisten",
            "viele",
            "wenige",
            "fast alle",
            "bis auf",
            "mindestens",
            "hoechstens",
        )
    )


def _notification_loudness_attributive_quantifier_polarity(
    normalized: str,
) -> tuple[bool, bool]:
    """Read German ``keine + state adjective + notification`` phrases."""
    tokens = normalized.split()
    subject_terms = {
        "nachricht",
        "nachrichten",
        "benachrichtigung",
        "benachrichtigungen",
        "message",
        "messages",
        "notification",
        "notifications",
    }
    positive_adjectives = {
        "laut",
        "laute",
        "lauten",
        "lautes",
        "loud",
        "hoerbar",
        "hoerbare",
        "hoerbaren",
        "hoerbares",
        "audible",
        "angeschaltet",
        "angeschaltete",
        "angeschalteten",
        "eingeschaltet",
        "eingeschaltete",
        "eingeschalteten",
        "aktiv",
        "aktive",
        "aktiviert",
        "aktivierte",
        "aktivierten",
        "an",
        "on",
        "enabled",
        "unmuted",
        "entstummt",
    }
    negative_adjectives = {
        "stumm",
        "stumme",
        "stummen",
        "stummes",
        "lautlos",
        "lautlose",
        "lautlosen",
        "unhoerbare",
        "unhoerbaren",
        "unhoerbares",
        "stummgeschaltet",
        "stummgeschaltete",
        "stummgeschalteten",
        "muted",
        "silent",
        "quiet",
        "inaudible",
        "unhoerbar",
        "still",
        "stille",
        "stillen",
        "leise",
        "leisen",
        "ausgeschaltet",
        "ausgeschaltete",
        "ausgeschalteten",
        "abgeschaltet",
        "abgeschaltete",
        "abgeschalteten",
        "deaktiviert",
        "deaktivierte",
        "deaktivierten",
        "inaktiv",
        "inactive",
        "off",
        "disabled",
    }
    negative_prefixes = (
        ("keine",),
        ("keinen",),
        ("kein",),
        ("keinerlei",),
        ("es", "gibt", "keine"),
        ("es", "gibt", "keinen"),
        ("es", "gibt", "kein"),
        ("es", "gibt", "keinerlei"),
    )
    positive = False
    negative = False
    for prefix in negative_prefixes:
        if tokens[: len(prefix)] != list(prefix):
            continue
        state_index = len(prefix)
        subject_index = state_index + 1
        if subject_index >= len(tokens) or tokens[subject_index] not in subject_terms:
            continue
        state = tokens[state_index]
        if state in positive_adjectives:
            negative = True
        elif state in negative_adjectives:
            positive = True
    return positive, negative


def _notification_loudness_has_absolute_negative_positive_status(normalized: str) -> bool:
    return _notification_loudness_has_absolute_negative_term(
        normalized, NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS
    )


def _notification_loudness_has_absolute_negative_term(
    normalized: str, terms: frozenset[str], *, inner_negated: bool = False
) -> bool:
    tokens = normalized.split()
    quantifier_patterns = (
        ("not", "a", "single"),
        ("not", "one"),
        ("there", "are", "not", "any"),
        ("there", "is", "not", "any"),
        ("there", "aren", "t", "any"),
        ("there", "isn", "t", "any"),
        ("there", "wasn", "t", "any"),
        ("there", "weren", "t", "any"),
        ("there", "are", "not", "a"),
        ("there", "is", "not", "a"),
        ("there", "aren", "t", "a"),
        ("there", "isn", "t", "a"),
        ("there", "wasn", "t", "a"),
        ("there", "weren", "t", "a"),
        ("nicht", "eine", "einzige"),
        ("nicht", "eine"),
        ("nicht", "ein", "einziger"),
        ("no",),
        ("none",),
        ("neither",),
        ("kein",),
        ("keine",),
        ("keinerlei",),
        ("weder",),
    )
    for pattern in quantifier_patterns:
        width = len(pattern)
        for start in range(len(tokens) - width + 1):
            if tuple(tokens[start : start + width]) != pattern:
                continue
            for index in range(start + width, len(tokens)):
                if tokens[index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES:
                    if width == 1 and tokens[index] in {"or", "nor", "oder", "noch"}:
                        continue
                    break
                if tokens[index] not in terms:
                    continue
                between = tokens[start + width : index]
                has_inner_negation = bool({"not", "nicht"}.intersection(between))
                if has_inner_negation is inner_negated:
                    return True
    return False


def _notification_loudness_has_absolute_negative_german_still(
    normalized: str, *, inner_negated: bool = False
) -> bool:
    has_german_still, has_negated_german_still = _notification_loudness_german_still_polarity(normalized)
    if not (has_german_still or has_negated_german_still):
        return False
    return _notification_loudness_has_absolute_negative_term(
        normalized, frozenset({"still"}), inner_negated=inner_negated
    )


def _notification_loudness_has_recent_completion_marker(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "just now",
            "right now",
            "just turned on",
            "just enabled",
            "recently turned on",
            "recently enabled",
            "newly enabled",
            "just muted",
            "recently muted",
            "just silenced",
            "recently silenced",
            "just disabled",
            "recently disabled",
            "gerade eben",
            "gerade angeschaltet",
            "gerade aktiviert",
            "gerade stummgeschaltet",
            "gerade deaktiviert",
            "soeben",
            "sound was restored",
            "notification sound was restored",
            "sound was brought back",
            "notification sound was brought back",
            "sound was lost",
            "notification sound was lost",
            "restored to loud",
            "restored to muted",
        )
    )


def _notification_loudness_has_habitual_marker(normalized: str) -> bool:
    for phrase in NOTIFICATION_LOUDNESS_HABITUAL_MARKERS:
        normalized_phrase = _normalize_text(phrase)
        if phrase == "immer" and (
            _contains_normalized_phrase(normalized, "immer noch")
            or _contains_normalized_phrase(normalized, "noch immer")
        ):
            continue
        if _contains_normalized_phrase(normalized, normalized_phrase):
            return True
    return False


def _notification_loudness_has_question_tail(normalized: str) -> bool:
    return any(
        normalized == _normalize_text(tail) or normalized.endswith(f" {_normalize_text(tail)}")
        for tail in NOTIFICATION_LOUDNESS_QUESTION_TAILS
    )


def _notification_loudness_canonicalize_present_perfect_status(normalized: str) -> str:
    return (
        normalized.replace("have not been", "remain not")
        .replace("has not been", "remains not")
        .replace("have been", "remain")
        .replace("has been", "remains")
    )


def _notification_loudness_has_positive_current_status(normalized: str) -> bool:
    normalized = _notification_loudness_canonicalize_present_perfect_status(normalized)
    normalized = normalized.replace("at the moment", "currently")
    normalized = normalized.replace("just now", "now")
    normalized = normalized.replace("im moment", "momentan")
    normalized = normalized.replace("zurzeit", "momentan")
    normalized = normalized.replace("gegenwaertig", "aktuell")
    normalized = normalized.replace("ab jetzt", "jetzt")
    normalized = normalized.replace("bis jetzt", "jetzt")
    normalized = normalized.replace("bis heute", "heute")
    normalized = normalized.replace("seit heute", "heute")
    normalized = normalized.replace("seitdem", "weiterhin")
    normalized = normalized.replace("are continuing to be", "remain")
    normalized = normalized.replace("is continuing to be", "remains")
    normalized = normalized.replace("continue to be", "remain")
    normalized = normalized.replace("continues to be", "remains")
    normalized = normalized.replace("nach wie vor", "weiterhin")
    tokens = normalized.split()
    copulas = {
        "ist",
        "sind",
        "is",
        "are",
        "re",
        "remain",
        "remains",
        "remained",
        "stay",
        "stays",
        "stayed",
        "become",
        "becomes",
        "became",
        "get",
        "gets",
        "got",
        "come",
        "comes",
        "came",
        "returned",
        "bleibt",
        "bleiben",
        "blieb",
        "blieben",
    }
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "benachrichtigungston",
        "notification",
        "notifications",
        "sie",
        "die",
        "das",
        "er",
        "they",
        "it",
    }
    for status_index, token in enumerate(tokens):
        if token not in NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS:
            continue
        for copula_index in range(max(0, status_index - 4), status_index):
            if tokens[copula_index] not in copulas:
                continue
            between = tokens[copula_index + 1 : status_index]
            if not all(
                value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS
                or value in NOTIFICATION_LOUDNESS_NEGATION_TERMS
                for value in between
            ):
                between_is_status_only = False
            else:
                between_is_status_only = True
            negation_count = sum(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in between)
            if between_is_status_only and negation_count % 2 == 0:
                return True
            before_copula = tokens[max(0, copula_index - 3) : copula_index]
            if negation_count % 2 == 0 and before_copula and all(
                value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in before_copula
            ) and any(
                value in subject_terms for value in between
            ):
                return True
    for copula_index, copula in enumerate(tokens):
        if copula not in {"ist", "sind", "bleibt", "bleiben", "blieb", "blieben"}:
            continue
        for status_index in range(max(0, copula_index - 4), copula_index):
            if tokens[status_index] not in NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS:
                continue
            before_status = tokens[max(0, status_index - 4) : status_index]
            after_status = tokens[status_index + 1 : copula_index]
            if sum(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in before_status) % 2:
                continue
            if any(value in subject_terms for value in before_status) and all(
                value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in after_status
            ):
                return True
    return False


def _notification_loudness_volume_polarity(
    normalized: str, *, has_volume_context: bool
) -> tuple[bool, bool]:
    if not has_volume_context:
        return False, False
    tokens = normalized.split()
    positive = False
    negative = False
    copulas = {
        "ist",
        "sind",
        "is",
        "are",
        "remain",
        "remains",
        "remained",
        "stay",
        "stays",
        "stayed",
        "become",
        "becomes",
        "became",
        "get",
        "gets",
        "got",
        "come",
        "comes",
        "came",
        "returned",
        "bleibt",
        "bleiben",
        "blieb",
        "blieben",
    }
    for index, token in enumerate(tokens):
        if token not in NOTIFICATION_LOUDNESS_VOLUME_POSITIVE_TERMS | NOTIFICATION_LOUDNESS_VOLUME_NEGATIVE_TERMS:
            continue
        if not any(tokens[candidate] in copulas for candidate in range(max(0, index - 5), index)):
            continue
        negated = _notification_loudness_scoped_negation_count(
            tokens, max(0, index - 3), index
        ) % 2 == 1
        is_positive_term = token in NOTIFICATION_LOUDNESS_VOLUME_POSITIVE_TERMS
        if is_positive_term is negated:
            negative = True
        else:
            positive = True
    for phrase in (
        "volle lautstaerke",
        "voller lautstaerke",
        "auf voller lautstaerke",
        "full volume",
        "maximum volume",
        "at full volume",
    ):
        if not _contains_normalized_phrase(normalized, phrase):
            continue
        if _notification_loudness_phrase_is_negated(normalized, phrase):
            negative = True
        else:
            positive = True
    if any(_contains_normalized_phrase(normalized, phrase) for phrase in (
        "leise gestellt",
    )):
        negative = True
    for index, token in enumerate(tokens):
        if token != "turned":
            continue
        following = tokens[index + 1 : index + 6]
        negated = _notification_loudness_scoped_negation_count(
            tokens, max(0, index - 3), index
        ) % 2 == 1
        if "up" in following:
            if negated:
                negative = True
            else:
                positive = True
        if "down" in following:
            if negated:
                positive = True
            else:
                negative = True
    for action, action_is_positive in (
        ("hochgestellt", True),
        ("hochgedreht", True),
        ("hochgesetzt", True),
        ("runtergedreht", False),
        ("heruntergedreht", False),
    ):
        if action not in tokens:
            continue
        index = tokens.index(action)
        negated = _notification_loudness_scoped_negation_count(
            tokens, max(0, index - 3), index
        ) % 2 == 1
        if action_is_positive is negated:
            negative = True
        else:
            positive = True
    if "100" in tokens and any(value in tokens for value in {"prozent", "percent"}):
        positive = True
    if "0" in tokens and any(value in tokens for value in {"prozent", "percent"}):
        negative = True
    return positive, negative


def _notification_loudness_completed_action_polarity(
    normalized: str, *, has_notification_context: bool
) -> tuple[bool, bool]:
    if not has_notification_context:
        return False, False
    action_boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN,
        "because",
        "since",
        "as",
        "weil",
        "da",
        "denn",
    }
    tokens = normalized.split()
    actions = {
        "set",
        "put",
        "make",
        "made",
        "turn",
        "turned",
        "switch",
        "switched",
        "enable",
        "enabled",
        "activate",
        "activated",
        "muted",
        "silenced",
        "disabled",
    }
    positive_targets = {
        "laut",
        "loud",
        "an",
        "on",
        "up",
        "hoch",
        "high",
        "full",
        "unmuted",
        "enabled",
        "active",
        "hochgedreht",
        "hochgesetzt",
        "hochgestellt",
    }
    negative_targets = {
        "stumm",
        "lautlos",
        "muted",
        "silent",
        "off",
        "down",
        "niedrig",
        "low",
        "leise",
        "runtergedreht",
        "heruntergedreht",
        "runtergesetzt",
    }
    subjects = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
        "chat",
        "conversation",
        "thread",
    }

    def target_polarity(start: int, end: int) -> tuple[bool, bool]:
        target_positive = False
        target_negative = False
        temporal_on_phrases = (
            ("from", "now", "on"),
            ("from", "right", "now", "on"),
            ("from", "this", "point", "on"),
            ("from", "here", "on"),
            ("from", "then", "on"),
        )
        for target_index in range(start, end):
            target = tokens[target_index]
            if any(
                target == "on"
                and target_index - len(phrase) + 1 >= start
                and tuple(tokens[target_index - len(phrase) + 1 : target_index + 1]) == phrase
                for phrase in temporal_on_phrases
            ):
                # In these phrases, ``on`` is temporal rather than a state.
                continue
            if target not in positive_targets | negative_targets:
                continue
            target_negated = _notification_loudness_scoped_negation_count(
                tokens, start, target_index
            ) % 2 == 1
            if target in positive_targets:
                if target_negated:
                    target_negative = True
                else:
                    target_positive = True
            elif target_negated:
                target_positive = True
            else:
                target_negative = True
        return target_positive, target_negative

    positive = False
    negative = False
    for auxiliary_index, auxiliary in enumerate(tokens):
        if auxiliary not in {"have", "has"}:
            continue
        for action_index in range(auxiliary_index + 1, min(len(tokens), auxiliary_index + 10)):
            action = tokens[action_index]
            if action in action_boundaries:
                break
            if action not in actions:
                continue
            tail_end = min(len(tokens), action_index + 10)
            for boundary_index in range(action_index + 1, tail_end):
                if (
                    tokens[boundary_index] in action_boundaries
                ):
                    tail_end = boundary_index
                    break
            tail = tokens[action_index + 1 : tail_end]
            has_positive_target, has_negative_target = target_polarity(action_index + 1, tail_end)
            if action in {"enabled", "activated"} and set(tail) & subjects:
                has_positive_target = True
            if action in {"muted", "silenced", "disabled"} and set(tail) & subjects:
                has_negative_target = True
            if not has_positive_target and not has_negative_target:
                continue
            negated = _notification_loudness_scoped_negation_count(
                tokens, max(0, action_index - 4), action_index
            ) % 2 == 1
            if has_positive_target:
                if negated:
                    negative = True
                else:
                    positive = True
            if has_negative_target:
                if negated:
                    positive = True
                else:
                    negative = True
    simple_past_actions = {
        "turned",
        "switched",
        "enabled",
        "activated",
        "muted",
        "silenced",
        "disabled",
        "unmuted",
        "made",
        "set",
        "put",
        "stellte",
        "schaltete",
        "machte",
        "setzte",
        "gestellt",
        "geschaltet",
        "gemacht",
        "gesetzt",
        "turn",
        "switch",
        "mute",
        "silence",
        "enable",
        "activate",
        "disable",
        "hochgedreht",
        "hochgesetzt",
        "hochgestellt",
        "runtergedreht",
        "heruntergedreht",
        "runtergesetzt",
    }
    status_copulas = {
        "ist",
        "sind",
        "is",
        "are",
        "remain",
        "remains",
        "stay",
        "stays",
        "bleibt",
        "bleiben",
    }
    status_action_terms = {
        "muted",
        "silenced",
        "disabled",
        "enabled",
        "unmuted",
        "activated",
    }
    did_actions = {"turn", "switch", "mute", "silence", "enable", "activate", "disable"}
    for action_index, action in enumerate(tokens):
        if action not in simple_past_actions:
            continue
        if action in status_action_terms:
            status_clause = False
            for copula_index in range(max(0, action_index - 4), action_index):
                if tokens[copula_index] not in status_copulas:
                    continue
                between = tokens[copula_index + 1 : action_index]
                if all(
                    token in NOTIFICATION_LOUDNESS_NEGATION_TERMS
                    or token in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS
                    for token in between
                ):
                    status_clause = True
                    break
            if status_clause:
                continue
        if action in did_actions and not any(
            tokens[candidate] in {"did", "didn"}
            for candidate in range(max(0, action_index - 3), action_index)
        ):
            if not any(
                tokens[candidate]
                in {"ist", "sind", "war", "waren", "wurde", "wurden", "is", "are", "was", "were"}
                for candidate in range(max(0, action_index - 5), action_index)
            ):
                continue
        context_start = max(0, action_index - 5)
        for boundary_index in range(context_start, action_index):
            if (
                tokens[boundary_index] in action_boundaries
            ):
                context_start = boundary_index + 1
        context_end = min(len(tokens), action_index + 10)
        for boundary_index in range(action_index + 1, context_end):
            if (
                tokens[boundary_index] in action_boundaries
            ):
                context_end = boundary_index
                break
        context = tokens[context_start:context_end]
        if action in {
            "muted",
            "mute",
            "silenced",
            "silence",
            "disabled",
            "disable",
            "unmuted",
            "enabled",
            "activated",
            "enable",
            "activate",
        } and not (
            set(context) & subjects
        ):
            continue
        if any(
            tokens[candidate] in {"keep", "kept", "keeping"}
            for candidate in range(context_start, action_index)
        ):
            # Keeping a state is not evidence that the user completed a switch.
            continue
        before_positive, before_negative = target_polarity(context_start, action_index)
        after_positive, after_negative = target_polarity(action_index + 1, context_end)
        action_positive = action in positive_targets
        action_negative = action in negative_targets
        if action in {"enabled", "activated", "enable", "activate", "unmuted"} and set(context) & subjects:
            action_positive = True
        if action in {"muted", "mute", "silenced", "silence", "disabled", "disable"} and set(context) & subjects:
            action_negative = True
        negated = _notification_loudness_scoped_negation_count(
            tokens, max(0, action_index - 5), action_index
        ) % 2 == 1
        if negated:
            after_positive, after_negative = after_negative, after_positive
            action_positive, action_negative = action_negative, action_positive
        has_positive_target = before_positive or after_positive or action_positive
        has_negative_target = before_negative or after_negative or action_negative
        if not has_positive_target and not has_negative_target:
            continue
        if has_positive_target:
            positive = True
        if has_negative_target:
            negative = True
    successful_prefixes = (
        ("succeeded", "in"),
        ("managed", "to"),
        ("managed", "not", "to"),
        ("was", "able", "to"),
        ("were", "able", "to"),
        ("have", "been", "able", "to"),
        ("has", "been", "able", "to"),
        ("was", "able", "not", "to"),
        ("were", "able", "not", "to"),
        ("have", "been", "able", "not", "to"),
        ("has", "been", "able", "not", "to"),
    )
    successful_actions = {
        "turn",
        "turned",
        "turning",
        "switch",
        "switched",
        "switching",
        "set",
        "setting",
        "put",
        "putting",
        "make",
        "made",
        "making",
        "keep",
        "keeping",
        "leave",
        "leaving",
        "enable",
        "enabled",
        "enabling",
        "activate",
        "activated",
        "activating",
        "disable",
        "disabled",
        "disabling",
        "deactivate",
        "deactivated",
        "deactivating",
        "mute",
        "muted",
        "muting",
        "silence",
        "silenced",
        "silencing",
        "unmute",
        "unmuted",
        "unmuting",
    }
    for prefix_start in range(len(tokens)):
        matched_prefix = next(
            (
                prefix
                for prefix in sorted(successful_prefixes, key=len, reverse=True)
                if tokens[prefix_start : prefix_start + len(prefix)] == list(prefix)
            ),
            None,
        )
        if matched_prefix is None:
            continue
        action_index = prefix_start + len(matched_prefix)
        if action_index >= len(tokens):
            continue
        if tokens[action_index] == "not":
            action_index += 1
        if action_index >= len(tokens):
            continue
        action = tokens[action_index]
        if action not in successful_actions:
            continue
        context_end = min(len(tokens), action_index + 12)
        for boundary_index in range(action_index + 1, context_end):
            if (
                tokens[boundary_index] in action_boundaries
            ):
                context_end = boundary_index
                break
        tail = tokens[action_index + 1 : context_end]
        if (
            set(tail) & {"chat", "conversation", "thread"}
            and not set(tokens)
            & {
                "nachricht",
                "nachrichten",
                "message",
                "messages",
                "benachrichtigung",
                "benachrichtigungen",
                "notification",
                "notifications",
                "push",
                "alert",
                "alerts",
            }
            and action
            in {
                "enable",
                "enabled",
                "enabling",
                "activate",
                "activated",
                "activating",
                "disable",
                "disabled",
                "disabling",
                "deactivate",
                "deactivated",
                "deactivating",
            }
        ):
            continue
        has_positive_target, has_negative_target = target_polarity(action_index + 1, context_end)
        if action in {"enable", "enabled", "enabling", "activate", "activated", "activating"}:
            if set(tail) & subjects:
                has_positive_target = True
        if action in {
            "disable",
            "disabled",
            "disabling",
            "deactivate",
            "deactivated",
            "deactivating",
        }:
            if set(tail) & subjects:
                has_negative_target = True
        if action in {"unmute", "unmuted", "unmuting"}:
            if set(tail) & subjects:
                has_positive_target = True
        if action in {"mute", "muted", "muting", "silence", "silenced", "silencing"}:
            if set(tail) & subjects:
                has_negative_target = True
        if not has_positive_target and not has_negative_target:
            continue
        action_negated = _notification_loudness_negation_count(
            tokens[prefix_start:action_index]
        ) % 2 == 1
        if action_negated:
            has_positive_target, has_negative_target = has_negative_target, has_positive_target
        if has_positive_target:
            positive = True
        if has_negative_target:
            negative = True
    has_perfect_never = bool(
        {"habe", "haben", "hat", "have", "has"}.intersection(tokens)
        and {"nie", "niemals", "never"}.intersection(tokens)
    )
    if has_perfect_never:
        for phrase, action_is_positive in (
            ("laut gestellt", True),
            ("laut geschaltet", True),
            ("stumm geschaltet", False),
            ("stummgeschaltet", False),
            ("ausgeschaltet", False),
        ):
            if not _contains_normalized_phrase(normalized, phrase):
                continue
            if action_is_positive:
                negative = True
            else:
                positive = True
    return positive, negative


def _notification_loudness_phrase_is_negated(normalized: str, phrase: str) -> bool:
    tokens = normalized.split()
    phrase_tokens = phrase.split()
    width = len(phrase_tokens)
    for index in range(len(tokens) - width + 1):
        if tokens[index : index + width] != phrase_tokens:
            continue
        if _notification_loudness_scoped_negation_count(
            tokens, max(0, index - 3), index
        ) % 2:
            return True
    return False


def _notification_loudness_phrase_is_double_negated(normalized: str, phrase: str) -> bool:
    phrase_tokens = phrase.split()
    if not phrase_tokens or phrase_tokens[0] not in {"not", "nicht"}:
        return False
    tokens = normalized.split()
    width = len(phrase_tokens)
    for index in range(len(tokens) - width + 1):
        if tokens[index : index + width] != phrase_tokens or index == 0:
            continue
        if tokens[index - 1] in {"not", "nicht"}:
            return True
    return False


def _notification_loudness_has_unnegated_phrase(normalized: str, phrases: tuple[str, ...]) -> bool:
    """Return true when at least one matching phrase occurrence is unnegated."""
    tokens = normalized.split()
    for phrase in phrases:
        phrase_tokens = phrase.split()
        width = len(phrase_tokens)
        for index in range(len(tokens) - width + 1):
            if tokens[index : index + width] != phrase_tokens:
                continue
            preceding_start = max(0, index - 3)
            for boundary_index in range(preceding_start, index):
                if (
                    tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ):
                    preceding_start = boundary_index + 1
            if _notification_loudness_scoped_negation_count(tokens, preceding_start, index) % 2 == 0:
                return True
    return False


def _notification_loudness_has_negative_current_status(normalized: str) -> bool:
    normalized = _notification_loudness_canonicalize_present_perfect_status(normalized)
    tokens = normalized.split()
    positive_status_terms = NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS
    contracted_copulas = {"isn", "aren", "re"}
    english_persistent_copulas = {
        "remain",
        "remains",
        "remained",
        "stay",
        "stays",
        "stayed",
        "become",
        "becomes",
        "became",
        "get",
        "gets",
        "got",
        "come",
        "comes",
        "came",
        "returned",
    }
    german_persistent_copulas = {"bleibt", "bleiben", "blieb", "blieben"}
    for status_index, token in enumerate(tokens):
        if token not in positive_status_terms:
            continue
        for copula_index in range(max(0, status_index - 4), status_index):
            copula = tokens[copula_index]
            between_start = copula_index + 1
            for boundary_index in range(between_start, status_index):
                if (
                    tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ):
                    between_start = boundary_index + 1
            between = tokens[between_start:status_index]
            if (
                copula in {"is", "are", "re"} | english_persistent_copulas
                and sum(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in between) % 2
            ):
                return True
            if (
                copula in {"ist", "sind"} | german_persistent_copulas
                and sum(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in between) % 2
            ):
                return True
            if copula in contracted_copulas and sum(value == "t" for value in between) % 2:
                return True
    for copula_index, copula in enumerate(tokens):
        if copula not in {"ist", "sind"} | german_persistent_copulas:
            continue
        for status_index in range(max(0, copula_index - 4), copula_index):
            if tokens[status_index] not in positive_status_terms:
                continue
            before_status = tokens[max(0, status_index - 4) : status_index]
            after_status = tokens[status_index + 1 : copula_index]
            if (
                any(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in before_status)
                and any(
                    value
                    in {
                        "nachricht",
                        "nachrichten",
                        "message",
                        "messages",
                        "benachrichtigung",
                        "benachrichtigungen",
                        "die",
                        "sie",
                    }
                    for value in before_status
                )
                and all(value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in after_status)
            ):
                return True
    return False


def _notification_loudness_has_contradictory_state(normalized: str) -> bool:
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    )
    for term in state_terms:
        has_unnegated, has_negated = _notification_loudness_term_polarity(normalized, frozenset({term}))
        if has_unnegated and has_negated:
            return True
    german_still_unnegated, german_still_negated = _notification_loudness_german_still_polarity(normalized)
    if german_still_unnegated and german_still_negated:
        return True
    for left, right, negated_pair_is_contradictory in (
        ("on", "off", True),
        ("aktiv", "inaktiv", True),
        ("active", "inactive", True),
        ("enabled", "disabled", True),
        ("sichtbar", "unsichtbar", True),
        ("visible", "hidden", True),
        ("loud", "muted", False),
    ):
        left_unnegated, left_negated = _notification_loudness_term_polarity(
            normalized, frozenset({left})
        )
        right_unnegated, right_negated = _notification_loudness_term_polarity(
            normalized, frozenset({right})
        )
        if left_unnegated and right_unnegated:
            return True
        if negated_pair_is_contradictory and left_negated and right_negated:
            return True
    for loud_term in ("loud", "laut"):
        for mute_term in (
            "muted",
            "silenced",
            "silent",
            "quiet",
            "inaudible",
            "unhoerbar",
            "stumm",
            "lautlos",
        ):
            loud_unnegated, _ = _notification_loudness_term_polarity(
                normalized, frozenset({loud_term})
            )
            mute_unnegated, _ = _notification_loudness_term_polarity(
                normalized, frozenset({mute_term})
            )
            if loud_unnegated and mute_unnegated:
                return True
    for audible_term in ("audible", "hoerbar"):
        for mute_term in ("muted", "silenced", "silent", "inaudible", "unhoerbar", "stumm", "lautlos"):
            audible_unnegated, _ = _notification_loudness_term_polarity(
                normalized, frozenset({audible_term})
            )
            mute_unnegated, _ = _notification_loudness_term_polarity(
                normalized, frozenset({mute_term})
            )
            if audible_unnegated and mute_unnegated:
                return True
    return False


def _notification_loudness_has_sequenced_action_status(
    normalized: str, *, activation_only: bool = False
) -> bool:
    tokens = normalized.split()
    action_terms = {
        "set",
        "put",
        "make",
        "made",
        "turn",
        "turned",
        "switch",
        "switched",
        "enable",
        "enabled",
        "activate",
        "activated",
        "mute",
        "muted",
        "silence",
        "silenced",
        "disable",
        "disabled",
        "stellte",
        "schaltete",
        "machte",
        "setzte",
        "gestellt",
        "geschaltet",
        "gemacht",
        "gesetzt",
        "checked",
        "verified",
        "confirmed",
        "noticed",
        "saw",
        "avoid",
        "avoided",
        "avoiding",
        "prevent",
        "prevented",
        "preventing",
        "keep",
        "kept",
        "keeping",
        "vermeide",
        "vermeiden",
        "vermieden",
        "verhindere",
        "verhindern",
        "verhindert",
        "verhinderte",
        "gehindert",
        "protect",
        "protected",
        "protecting",
        "shield",
        "shielded",
        "shielding",
        "geschuetzt",
        "schuetzen",
        "schuetzte",
        "escape",
        "escaped",
        "escaping",
        "save",
        "saved",
        "saving",
        "safe",
        "free",
        "immune",
        "entgehen",
        "entging",
        "entgingen",
        "entgangen",
        "verschonen",
        "verschont",
        "verschonte",
        "muting",
        "silencing",
        "geprueft",
        "sichergestellt",
    }
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
        "sie",
        "er",
        "they",
        "it",
        "die",
        "das",
    }
    if activation_only:
        state_terms = {
            "an",
            "on",
            "aktiv",
            "active",
            "enabled",
            "sichtbar",
            "visible",
            *NOTIFICATION_LOUDNESS_OFF_TERMS,
        }
    else:
        state_terms = (
            set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
            | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
            | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
        )
    boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
    }
    for boundary_index, token in enumerate(tokens):
        if token not in boundaries:
            continue
        before = tokens[:boundary_index]
        after = tokens[boundary_index + 1 :]
        if (
            any(value in action_terms for value in before)
            and any(value in subject_terms for value in after)
            and any(value in state_terms for value in after)
        ):
            return True
    return False


def _notification_loudness_has_cross_subject_conflict(
    normalized: str,
    *,
    has_unnegated_mute: bool,
    has_negated_mute: bool,
    has_unnegated_off: bool,
    has_negated_off: bool,
    has_positive_unmute_phrase: bool,
    has_positive_current_status: bool,
    has_negative_current_status: bool,
) -> bool:
    tokens = set(normalized.split())
    message_subject = tokens & {"nachricht", "nachrichten", "message", "messages"}
    notification_subject = tokens & {
        "benachrichtigung",
        "benachrichtigungen",
        "benachrichtigungston",
        "notification",
        "notifications",
    }
    if not message_subject or not notification_subject:
        return False
    conflict_boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        "because",
        "since",
        "as",
        "although",
        "while",
        "though",
        "despite",
        "weil",
        "da",
        "denn",
    }
    if not (tokens & conflict_boundaries or NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN in tokens):
        return False
    positive = has_negated_mute or has_negated_off or has_positive_unmute_phrase or has_positive_current_status
    negative = has_unnegated_mute or has_unnegated_off or has_negative_current_status
    return positive and negative


def _notification_loudness_has_cross_subject_gradient_conflict(normalized: str) -> bool:
    boundaries = NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES | {
        NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN,
        "because",
        "since",
        "as",
        "weil",
        "da",
        "denn",
    }
    clauses: list[list[str]] = [[]]
    for token in normalized.split():
        if token in boundaries:
            clauses.append([])
        else:
            clauses[-1].append(token)
    notification_states: set[str] = set()
    message_states: set[str] = set()
    notification_terms = {
        "benachrichtigung",
        "benachrichtigungen",
        "benachrichtigungston",
        "notification",
        "notifications",
    }
    message_terms = {"nachricht", "nachrichten", "message", "messages"}
    for clause in clauses:
        clause_text = " ".join(clause)
        state = _notification_loudness_audibility_gradient_decision(clause_text)
        if state is None:
            unnegated_mute, negated_mute = _notification_loudness_mute_polarity(clause_text)
            unnegated_off, negated_off = _notification_loudness_term_polarity(
                clause_text, NOTIFICATION_LOUDNESS_OFF_TERMS
            )
            positive_status = _notification_loudness_has_positive_current_status(clause_text)
            negative_status = _notification_loudness_has_negative_current_status(clause_text)
            if (unnegated_mute or unnegated_off) and not (negated_mute or negated_off):
                state = "declined"
            elif (negated_mute or negated_off) and not (unnegated_mute or unnegated_off):
                state = "confirmed"
            elif positive_status and not negative_status:
                state = "confirmed"
            elif negative_status and not positive_status:
                state = "declined"
        if state is None:
            continue
        terms = set(clause)
        has_notification = bool(terms & notification_terms)
        has_message = bool(terms & message_terms)
        if has_notification and not has_message:
            notification_states.add(state)
        elif has_message and not has_notification:
            message_states.add(state)
    return bool(
        ("confirmed" in notification_states and "declined" in message_states)
        or ("declined" in notification_states and "confirmed" in message_states)
    )


def _notification_loudness_has_audibility_state(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "cannot hear notifications",
            "can not hear notifications",
            "can t hear notifications",
            "cannot hear messages",
            "can not hear messages",
            "can t hear messages",
            "could not hear notifications",
            "couldn t hear notifications",
            "could not hear messages",
            "couldn t hear messages",
            "could not hear message notifications",
            "couldn t hear message notifications",
            "i do not hear notifications",
            "i don t hear notifications",
            "i can hear notifications",
            "i can hear messages",
            "i can hear message notifications",
            "i can hear the message sound now",
            "can hear the message sound now",
            "ich hoere jetzt benachrichtigungen",
            "ich kann jetzt benachrichtigungen hoeren",
            "ich kann nachrichten hoeren",
            "ich kann nachrichten jetzt hoeren",
            "ich kann die nachrichten hoeren",
            "ich kann die nachrichten jetzt hoeren",
            "ich kann die benachrichtigungen hoeren",
            "ich kann die benachrichtigungen jetzt hoeren",
            "ich kann die benachrichtigungen wieder hoeren",
            "ich kann den benachrichtigungston wieder hoeren",
            "kann die nachrichten nicht hoeren",
            "kann die benachrichtigungen nicht hoeren",
        )
    )


def _notification_loudness_has_audibility_gradient_phrase(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            *NOTIFICATION_LOUDNESS_GRADIENT_NEGATIVE_PHRASES,
            *NOTIFICATION_LOUDNESS_GRADIENT_POSITIVE_PHRASES,
        )
    )


def _notification_loudness_gradient_absolute_polarity(
    normalized: str, phrase: str
) -> str | None:
    marker = "__loudness_gradient__"
    candidate = normalized.replace(phrase, marker)
    if candidate == normalized:
        return None
    marker_terms = frozenset({marker})
    if _notification_loudness_has_absolute_negative_term(
        candidate, marker_terms, inner_negated=True
    ):
        return "inner"
    if _notification_loudness_has_absolute_negative_term(candidate, marker_terms):
        return "outer"
    return None


def _notification_loudness_audibility_gradient_decision(normalized: str) -> str | None:
    """Resolve explicit loudness thresholds while respecting local negation."""
    negative_matches = tuple(
        phrase
        for phrase in NOTIFICATION_LOUDNESS_GRADIENT_NEGATIVE_PHRASES
        if _contains_normalized_phrase(normalized, phrase)
    )
    positive_matches = tuple(
        phrase
        for phrase in NOTIFICATION_LOUDNESS_GRADIENT_POSITIVE_PHRASES
        if _contains_normalized_phrase(normalized, phrase)
    )
    for phrase in negative_matches:
        absolute_polarity = _notification_loudness_gradient_absolute_polarity(normalized, phrase)
        if absolute_polarity == "outer":
            return "confirmed"
        if absolute_polarity == "inner":
            return "declined"
    for phrase in positive_matches:
        absolute_polarity = _notification_loudness_gradient_absolute_polarity(normalized, phrase)
        if absolute_polarity == "outer":
            return "declined"
        if absolute_polarity == "inner":
            return "confirmed"
    if _notification_loudness_has_set_partial_quantifier(normalized):
        return None
    if _notification_loudness_has_partial_quantifier(normalized) and not negative_matches:
        return None
    for phrase in NOTIFICATION_LOUDNESS_GRADIENT_NEGATIVE_PHRASES:
        if phrase not in negative_matches:
            continue
        return (
            "confirmed"
            if _notification_loudness_phrase_is_negated(normalized, phrase)
            else "declined"
        )
    for phrase in NOTIFICATION_LOUDNESS_GRADIENT_POSITIVE_PHRASES:
        if phrase not in positive_matches:
            continue
        return (
            "declined"
            if _notification_loudness_phrase_is_negated(normalized, phrase)
            else "confirmed"
        )
    return None


def _notification_loudness_has_audibility_gradient(normalized: str) -> bool:
    return _notification_loudness_audibility_gradient_decision(normalized) is not None


def _notification_loudness_has_direct_audibility_experience(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "barely hear notifications",
            "barely hear messages",
            "barely hear notification sound",
            "barely hear message sound",
            "barely hear the notification sound",
            "barely hear the message sound",
            "hardly hear notifications",
            "hardly hear messages",
            "hardly hear notification sound",
            "hardly hear message sound",
            "hardly hear the notification sound",
            "hardly hear the message sound",
            "clearly hear notifications",
            "clearly hear messages",
            "clearly hear notification sound",
            "clearly hear message sound",
            "clearly hear the notification sound",
            "clearly hear the message sound",
            "hear notifications clearly",
            "hear messages clearly",
            "hear notification sound clearly",
            "hear message sound clearly",
            "hear the notification sound clearly",
            "hear the message sound clearly",
            "can not clearly hear",
            "cannot clearly hear",
            "can t clearly hear",
            "kaum hoeren",
            "deutlich hoeren",
            "klar hoeren",
            "gut hoeren",
        )
    )


def _notification_loudness_has_explicit_confirmation(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "made sure",
            "verified that",
            "confirmed that",
            "i can confirm",
            "i can verify",
            "i can prove",
            "sichergestellt",
            "ich kann bestaetigen",
            "ich kann belegen",
            "ich bestaetige",
            "ich habe bestaetigt",
            "ich kann bestätigen",
            "ich kann beweisen",
            "ich bestätige",
            "ich habe bestätigt",
        )
    )


def _notification_loudness_has_verification_question(normalized: str) -> bool:
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "checked if",
            "checked whether",
            "verified if",
            "verified whether",
            "checked to see if",
            "geprueft ob",
            "geprüft ob",
            "nachgesehen ob",
            "ueberprueft ob",
            "überprüft ob",
        )
    )


def _notification_loudness_has_ambiguous_alternative(normalized: str) -> bool:
    tokens = set(normalized.split())
    if not tokens & {"or", "oder"}:
        return False
    positive_phrases = (
        "laut",
        "loud",
        "audible",
        "hoerbar",
        "visible",
        "sichtbar",
        "an",
        "on",
        "active",
        "enabled",
        "unmuted",
        "nicht stumm",
        "nicht lautlos",
        "not muted",
        "not off",
        "not disabled",
        "not silent",
        "not quiet",
        "not suppressed",
        "not hidden",
    )
    negative_phrases = (
        "stumm",
        "lautlos",
        "muted",
        "silenced",
        "silent",
        "aus",
        "off",
        "disabled",
        "nicht laut",
        "not loud",
        "not on",
    )
    return (
        any(_contains_normalized_phrase(normalized, phrase) for phrase in positive_phrases)
        and any(_contains_normalized_phrase(normalized, phrase) for phrase in negative_phrases)
    )


def _notification_loudness_has_ambiguous_status_qualifier(normalized: str) -> bool:
    if set(normalized.split()) & {
        "video",
        "videos",
        "movie",
        "movies",
        "film",
        "films",
        "music",
        "television",
        "tv",
        "radio",
        "podcast",
        "podcasts",
        "speaker",
        "speakers",
        "headphones",
        "fernseher",
        "lautsprecher",
        "kopfhoerer",
        "alarm",
        "alarms",
        "voice",
        "wecker",
        "weckers",
        "stimme",
        "stimmen",
    }:
        return True
    if any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "in the video",
            "of the video",
            "on the video",
            "in the movie",
            "of the movie",
            "in the film",
            "of the film",
            "of music",
            "of my voice",
            "my voice",
            "of my alarm",
            "my alarm",
            "im video",
            "in dem video",
            "des videos",
            "im film",
            "des films",
            "meiner stimme",
            "meines weckers",
        )
    ):
        return True
    platform_phrases = (
        "on telegram",
        "on signal",
        "on whatsapp",
        "on matrix",
        "on discord",
        "on slack",
        "on facebook",
        "on email",
        "on the internet",
        "on the app",
        "on in the app",
        "on in app",
        "on the web",
        "on the website",
        "on the server",
        "on the way",
        "on schedule",
        "off matrix",
        "off discord",
        "off slack",
        "off facebook",
        "off email",
        "off the internet",
        "off the app",
        "off the web",
        "off the website",
        "off the server",
    )
    if any(_contains_normalized_phrase(normalized, phrase) for phrase in platform_phrases):
        other_state_terms = (
            set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS) - {"on"}
        ) | set(NOTIFICATION_LOUDNESS_MUTE_TERMS) | (
            set(NOTIFICATION_LOUDNESS_OFF_TERMS) - {"off"}
        ) | {"laut", "loud"}
        if not any(_contains_normalized_phrase(normalized, term) for term in other_state_terms):
            return True
    return any(
        _contains_normalized_phrase(normalized, phrase)
        for phrase in (
            "on hold",
            "on pause",
            "on standby",
            "on vacation",
            "off topic",
            "off duty",
            "on do not disturb",
            "on dnd",
            "notifications on do not disturb",
            "notifications on dnd",
            "free to mute",
            "free to be muted",
            "safe to mute",
            "safe to be muted",
            "saved to mute",
            "saved to be muted",
            "saved notifications to mute",
            "saved notifications to be muted",
            "saved messages to mute",
            "saved messages to be muted",
        )
    )


def _notification_loudness_has_ambiguous_location_status(normalized: str) -> bool:
    location_phrases = (
        "on my phone",
        "on the phone",
        "on my device",
        "on the device",
        "on screen",
        "on the screen",
        "on the lock screen",
        "on the table",
        "off the table",
        "auf dem tisch",
        "vom tisch",
        "off my phone",
        "off the phone",
        "off the record",
    )
    if not any(_contains_normalized_phrase(normalized, phrase) for phrase in location_phrases):
        return False
    other_state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS) - {"on"}
    ) | set(NOTIFICATION_LOUDNESS_MUTE_TERMS) | (set(NOTIFICATION_LOUDNESS_OFF_TERMS) - {"off"}) | {
        "laut",
        "loud",
    }
    return not any(_contains_normalized_phrase(normalized, term) for term in other_state_terms)


def _notification_loudness_has_ambiguous_chat_activity(normalized: str) -> bool:
    tokens = set(normalized.split())
    if not tokens & {"chat", "conversation", "thread"}:
        return False
    if tokens & {
        "laut",
        "loud",
        "stumm",
        "lautlos",
        "muted",
        "silenced",
        "silent",
        "unmuted",
        "audible",
        "hoerbar",
        "volume",
    }:
        return False
    return bool(
        tokens
        & {
            "aktiv",
            "active",
            "inaktiv",
            "inactive",
            "enabled",
            "disabled",
            "sichtbar",
            "visible",
            "an",
            "on",
            "aus",
            "off",
        }
    )


def _notification_loudness_pending_pronoun_decision(normalized: str) -> str | None:
    if (
        _notification_loudness_has_ambiguous_status_qualifier(normalized)
        or _notification_loudness_has_ambiguous_location_status(normalized)
    ):
        return None
    if normalized in {
        "sie sind an",
        "ist an",
        "sind an",
        "ist aktiviert",
        "sind aktiviert",
        "ist eingeschaltet",
        "sind eingeschaltet",
        "ist angeschaltet",
        "sind angeschaltet",
        "is enabled",
        "are enabled",
        "is active",
        "are active",
        "ist aktiv",
        "sind aktiv",
        "ist hoerbar",
        "sind hoerbar",
        "is audible",
        "are audible",
        "is set to loud",
        "are set to loud",
        "is set to high",
        "are set to high",
        "is set to unmuted",
        "are set to unmuted",
        "ist laut gestellt",
        "sind laut gestellt",
        "sie sind laut",
        "sie sind nicht aus",
        "sie sind nicht ausgeschaltet",
        "sie sind nicht stumm",
        "sie sind nicht lautlos",
        "sie sind nicht still",
        "die sind an",
        "die sind laut",
        "die sind nicht aus",
        "die sind nicht ausgeschaltet",
        "die sind nicht stumm",
        "die sind nicht lautlos",
        "die sind nicht still",
        "das ist an",
        "das ist laut",
        "das ist nicht aus",
        "das ist nicht ausgeschaltet",
        "das ist nicht stumm",
        "das ist nicht lautlos",
        "das ist nicht still",
        "they are on",
        "they re on",
        "is on",
        "are on",
        "they are loud",
        "they re loud",
        "they are not off",
        "they re not off",
        "they are not disabled",
        "they re not disabled",
        "they are not muted",
        "they re not muted",
        "they are enabled",
        "they re enabled",
        "they are unmuted",
        "they re unmuted",
        "it is on",
        "it is loud",
        "it is not off",
        "it is not disabled",
        "it is not muted",
    }:
        return "confirmed"
    if normalized in {
        "sie sind aus",
        "sie sind stumm",
        "sie sind lautlos",
        "sie sind still",
        "sie sind nicht laut",
        "sie sind nicht an",
        "sie sind ausgeschaltet",
        "die sind aus",
        "die sind stumm",
        "die sind lautlos",
        "die sind still",
        "die sind nicht laut",
        "die sind nicht an",
        "die sind ausgeschaltet",
        "das ist aus",
        "das ist stumm",
        "das ist lautlos",
        "das ist still",
        "das ist nicht laut",
        "das ist nicht an",
        "das ist ausgeschaltet",
        "they are off",
        "they re off",
        "they are muted",
        "they re muted",
        "they are not loud",
        "they re not loud",
        "they are disabled",
        "they re disabled",
        "they are not on",
        "they re not on",
        "it is off",
        "it is muted",
        "it is silent",
        "it is not loud",
        "it is not on",
        "it is disabled",
        "ist inaktiv",
        "sind inaktiv",
        "is inactive",
        "are inactive",
        "ist unhoerbar",
        "sind unhoerbar",
        "is inaudible",
        "are inaudible",
        "is set to low",
        "are set to low",
        "is set to muted",
        "are set to muted",
        "is set to quiet",
        "are set to quiet",
        "ist leise gestellt",
        "sind leise gestellt",
    }:
        return "declined"
    tokens = normalized.split()
    pronouns = {"sie", "die", "das", "er", "they", "it", "this", "that", "these", "those"}
    copulas = {"ist", "sind", "is", "are", "re", "s"}
    status_terms = (
        NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS
        | NOTIFICATION_LOUDNESS_MUTE_TERMS
        | NOTIFICATION_LOUDNESS_OFF_TERMS
    )
    if len(tokens) >= 3 and tokens[0] in pronouns and tokens[1] in copulas:
        for status_index in range(2, len(tokens)):
            status = tokens[status_index]
            if status not in status_terms:
                continue
            between = tokens[2:status_index]
            if not all(
                value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS
                or value in NOTIFICATION_LOUDNESS_NEGATION_TERMS
                for value in between
            ):
                continue
            after = tokens[status_index + 1 :]
            if not all(value in NOTIFICATION_LOUDNESS_CURRENT_STATUS_MODIFIERS for value in after):
                continue
            negated = sum(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in between) % 2 == 1
            if status in NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS:
                return "declined" if negated else "confirmed"
            return "confirmed" if negated else "declined"
    return None


def _notification_loudness_has_unscoped_subject_status(normalized: str) -> bool:
    copulas = (
        "bin",
        "ist",
        "sind",
        "am",
        "is",
        "are",
        "been",
        "remain",
        "remains",
        "remained",
        "stay",
        "stays",
        "stayed",
        "become",
        "becomes",
        "became",
        "get",
        "gets",
        "got",
        "come",
        "comes",
        "came",
        "returned",
        "bleibt",
        "bleiben",
        "blieb",
        "blieben",
    )
    if normalized.startswith(tuple(f"{copula} " for copula in copulas)):
        return False
    return any(_contains_normalized_phrase(normalized, copula) for copula in copulas)


def _notification_loudness_has_unrelated_identity_description(normalized: str) -> bool:
    """Reject identity statements that only describe another notification object."""
    tokens = normalized.split()
    negative_identity_prefixes = (
        ("i", "am", "not"),
        ("i", "m", "not"),
        ("that", "is", "not"),
        ("that", "isn", "t"),
        ("this", "is", "not"),
        ("this", "isn", "t"),
    )
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    )
    for prefix in negative_identity_prefixes:
        if tokens[: len(prefix)] != list(prefix):
            continue
        for subject_index in range(len(prefix) + 1, len(tokens) - 1):
            if tokens[subject_index - 1] not in {"a", "an", "the"}:
                continue
            if tokens[subject_index] not in subject_terms:
                continue
            relative_index = next(
                (
                    index
                    for index in range(subject_index + 1, len(tokens))
                    if tokens[index] in {"that", "which"}
                ),
                None,
            )
            if relative_index is not None and any(
                token in state_terms for token in tokens[relative_index + 1 :]
            ):
                return True
    return False


def _notification_loudness_has_negative_possession_description(normalized: str) -> bool:
    """Reject negative possession claims whose relative clause only describes an object."""
    tokens = normalized.split()
    negative_possession_prefixes = (
        ("i", "don", "t", "have"),
        ("i", "do", "not", "have"),
        ("i", "haven", "t", "got"),
        ("i", "have", "no"),
        ("ich", "habe", "keine"),
        ("ich", "habe", "keinen"),
        ("ich", "habe", "kein"),
    )
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    )
    for prefix in negative_possession_prefixes:
        if tokens[: len(prefix)] != list(prefix):
            continue
        for subject_index in range(len(prefix), len(tokens)):
            if tokens[subject_index] not in subject_terms:
                continue
            relative_index = next(
                (
                    index
                    for index in range(subject_index + 1, len(tokens))
                    if tokens[index] in {"that", "which", "die", "welche"}
                ),
                None,
            )
            if relative_index is not None and any(
                token in state_terms for token in tokens[relative_index + 1 :]
            ):
                return True
    return False


def _notification_loudness_has_negative_german_existential_description(normalized: str) -> bool:
    """Reject German negative existential relative clauses as global status claims."""
    tokens = normalized.split()
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    state_terms = (
        set(NOTIFICATION_LOUDNESS_POSITIVE_STATUS_TERMS)
        | set(NOTIFICATION_LOUDNESS_MUTE_TERMS)
        | set(NOTIFICATION_LOUDNESS_OFF_TERMS)
    )
    negative_prefixes = (
        ("keine",),
        ("keinen",),
        ("kein",),
        ("keiner",),
        ("keinerlei",),
        ("es", "gibt", "keine"),
        ("es", "gibt", "keinen"),
        ("es", "gibt", "kein"),
        ("es", "gibt", "keinerlei"),
    )
    relative_terms = {"die", "der", "das", "welche", "welcher", "welches", "welchen"}
    for prefix in negative_prefixes:
        if tokens[: len(prefix)] != list(prefix):
            continue
        for subject_index in range(len(prefix), len(tokens)):
            if tokens[subject_index] not in subject_terms:
                continue
            relative_index = next(
                (
                    index
                    for index in range(subject_index + 1, len(tokens))
                    if tokens[index] in relative_terms
                ),
                None,
            )
            if relative_index is not None and any(
                token in state_terms for token in tokens[relative_index + 1 :]
            ):
                return True
    return False


def _notification_loudness_has_ambiguous_comparative_negation(normalized: str) -> bool:
    """Keep relative comparisons without an absolute state interpretation."""
    token_list = normalized.split()
    tokens = set(token_list)
    comparative_terms = {
        "louder",
        "lauter",
        "higher",
        "hoeher",
        "quieter",
        "softer",
        "leiser",
        "lower",
        "niedriger",
    }
    negation_or_quantifier_terms = {
        "not",
        "nicht",
        "no",
        "kein",
        "keine",
        "keinen",
        "keinerlei",
    }
    if not (tokens & comparative_terms and tokens & negation_or_quantifier_terms):
        return False
    completed_comparative_actions = (
        "made it louder",
        "made them louder",
        "make it louder",
        "make them louder",
        "raised it",
        "raised them",
        "raised the volume",
        "increased it",
        "increased them",
        "increased the volume",
        "made notifications louder",
        "make notifications louder",
        "turned notifications louder",
        "turn notifications louder",
        "lauter gestellt",
        "lauter gemacht",
        "hoeher gedreht",
    )
    if any(_contains_normalized_phrase(normalized, phrase) for phrase in completed_comparative_actions):
        return False
    subject_terms = {
        "nachricht",
        "nachrichten",
        "message",
        "messages",
        "benachrichtigung",
        "benachrichtigungen",
        "notification",
        "notifications",
    }
    copulas = {"ist", "sind", "is", "are", "remain", "remains", "bleibt", "bleiben"}
    for comparative_index, token in enumerate(token_list):
        if token not in comparative_terms:
            continue
        for subject_index, subject in enumerate(token_list[:comparative_index]):
            if subject not in subject_terms:
                continue
            if any(
                candidate in copulas
                for candidate in token_list[subject_index + 1 : comparative_index]
            ):
                return False
    return True


def _notification_loudness_is_non_declarative(text: str, normalized: str) -> bool:
    if "?" in str(text or ""):
        return True
    if normalized.startswith(("do not disturb is ", "dnd is ")):
        return False
    tokens = normalized.split()
    if tokens and tokens[0] in {"sind", "ist", "are", "is"}:
        status_tokens = tokens[1:]
        while status_tokens and status_tokens[0] in NOTIFICATION_LOUDNESS_NON_ASSERTIVE_OPTIONAL_MODIFIERS:
            status_tokens = status_tokens[1:]
        return bool(status_tokens) and status_tokens[0] not in NOTIFICATION_LOUDNESS_STATUS_LEAD_TERMS
    if normalized.startswith(NOTIFICATION_LOUDNESS_NON_DECLARATIVE_STARTS):
        return True
    without_temporal_fillers = " ".join(
        token
        for token in tokens
        if token not in NOTIFICATION_LOUDNESS_NON_ASSERTIVE_OPTIONAL_MODIFIERS
    )
    return without_temporal_fillers.startswith(NOTIFICATION_LOUDNESS_NON_DECLARATIVE_STARTS)


def _notification_loudness_has_negated_phrase(normalized: str, phrases: tuple[str, ...]) -> bool:
    tokens = normalized.split()
    for phrase in phrases:
        phrase_tokens = phrase.split()
        width = len(phrase_tokens)
        for index in range(len(tokens) - width + 1):
            if tokens[index : index + width] != phrase_tokens:
                continue
            preceding_start = max(0, index - 3)
            for boundary_index in range(preceding_start, index):
                if (
                    tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
                    or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
                ):
                    preceding_start = boundary_index + 1
            if _notification_loudness_scoped_negation_count(tokens, preceding_start, index) % 2:
                return True
    return False


def _notification_loudness_negation_count(tokens: list[str]) -> int:
    count = sum(value in NOTIFICATION_LOUDNESS_NEGATION_TERMS for value in tokens)
    for phrase in NOTIFICATION_LOUDNESS_NEGATION_PHRASES:
        phrase_tokens = phrase.split()
        width = len(phrase_tokens)
        count += sum(tokens[index : index + width] == phrase_tokens for index in range(len(tokens) - width + 1))
    return count


def _notification_loudness_scoped_negation_count(tokens: list[str], start: int, end: int) -> int:
    count = _notification_loudness_negation_count(tokens[start:end])
    clause_start = 0
    for boundary_index in range(end - 1, -1, -1):
        if (
            tokens[boundary_index] in NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARIES
            or tokens[boundary_index] == NOTIFICATION_LOUDNESS_CLAUSE_BOUNDARY_TOKEN
        ):
            clause_start = boundary_index + 1
            break
    if clause_start < start:
        count += sum(token in NOTIFICATION_LOUDNESS_QUANTIFIER_TERMS for token in tokens[clause_start:start])
    return count


def _normalize_channel(channel: Any) -> str:
    return str(channel or "").strip().casefold()


def _normalize_chat_type(chat_type: Any) -> str:
    return str(chat_type or "").strip().casefold()


def _is_private_chat_type(chat_type: Any) -> bool:
    return _normalize_chat_type(chat_type) == "private"


def _normalize_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on", "enabled", "ja", "an"}:
        return True
    if text in {"0", "false", "no", "off", "disabled", "nein", "aus"}:
        return False
    return default
